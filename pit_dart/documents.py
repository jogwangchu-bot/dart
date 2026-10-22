from __future__ import annotations

import html
import io
import re
from pathlib import Path, PurePosixPath
from zipfile import BadZipFile, ZipFile

from defusedxml import ElementTree
from lxml import etree

from .core import IntegrityError, atomic_write, digest


def inspect_archive(data: bytes) -> dict[str, bytes]:
    try:
        with ZipFile(io.BytesIO(data)) as archive:
            infos = [item for item in archive.infolist() if not item.is_dir()]
            if not infos or len(infos) > 1000 or sum(item.file_size for item in infos) > 256 * 1024 * 1024:
                raise IntegrityError("ZIP has no files or exceeds expansion limits")
            names = [item.filename for item in infos]
            if len(set(names)) != len(names):
                raise IntegrityError("ZIP contains duplicate file names")
            for item in infos:
                path = PurePosixPath(item.filename.replace("\\", "/"))
                if path.is_absolute() or ".." in path.parts or item.flag_bits & 1:
                    raise IntegrityError("ZIP has unsafe names or encrypted members")
            if archive.testzip() is not None:
                raise IntegrityError("ZIP CRC verification failed")
            documents = {item.filename: archive.read(item) for item in infos if item.filename.lower().endswith(".xml")}
            if not documents:
                raise IntegrityError("ZIP contains no XML documents")
            for source in documents.values():
                root = ElementTree.fromstring(source)
                if root.tag.lower() == "result" and root.find("status") is not None:
                    raise IntegrityError("ZIP contains an API error XML")
            return documents
    except IntegrityError:
        raise
    except Exception:
        raise IntegrityError("Invalid ZIP/XML, unsupported encoding, or unsafe XML entity") from None


def xml_tree(source: bytes):
    # The independent safe parser rejects entity expansion before lxml conversion.
    ElementTree.fromstring(source)
    parser = etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True, recover=False,
                             remove_blank_text=False, remove_comments=False)
    return etree.fromstring(source, parser=parser)


def readable_html(documents: dict[str, bytes]) -> bytes:
    """Full escaped XML plus table renderings; never run embedded markup/scripts.

    The complete decoded source is retained verbatim. Rendered tables are an
    additional view, not a replacement for source or official ZIP bytes.
    """
    output = ['<!doctype html><html><head><meta charset="utf-8">',
              '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'">',
              '<style>table,td,th{border:1px solid;border-collapse:collapse}td,th{white-space:pre-wrap}pre{white-space:pre-wrap}</style></head><body>']
    for name, source in documents.items():
        try:
            root = xml_tree(source)
            encoding = root.getroottree().docinfo.encoding or "utf-8"
            text = source.decode(encoding)
            output.append(f"<h1>{html.escape(name)}</h1>")
            for table in root.iter():
                if not isinstance(table.tag, str) or etree.QName(table).localname.upper() != "TABLE":
                    continue
                output.append("<table>")
                for row in table.iter():
                    if not isinstance(row.tag, str) or etree.QName(row).localname.upper() != "TR":
                        continue
                    # Nested tables cannot be flattened without ambiguity.
                    parents = [p for p in row.iterancestors() if isinstance(p.tag, str) and etree.QName(p).localname.upper() == "TABLE"]
                    if not parents or parents[0] is not table:
                        continue
                    output.append("<tr>")
                    for cell in row:
                        if not isinstance(cell.tag, str):
                            continue
                        tag = etree.QName(cell).localname.upper()
                        if tag not in ("TD", "TH", "TE", "TU"):
                            raise IntegrityError("Unsupported table cell structure; conversion needs review")
                        if any(isinstance(child.tag, str) and etree.QName(child).localname.upper() == "TABLE" for child in cell.iterdescendants()):
                            raise IntegrityError("Nested table conversion needs review")
                        spans = []
                        for attribute, value in cell.attrib.items():
                            lower = attribute.lower()
                            if lower in ("rowspan", "colspan"):
                                if not re.fullmatch(r"[1-9]\d{0,2}", value):
                                    raise IntegrityError("Invalid table span; conversion needs review")
                                spans.append(f' {lower}="{value}"')
                        target = "th" if tag == "TH" else "td"
                        output.append(f"<{target}{''.join(spans)}>{html.escape(''.join(cell.itertext()))}</{target}>")
                    output.append("</tr>")
                output.append("</table>")
            output.append("<pre>" + html.escape(text) + "</pre>")
        except IntegrityError:
            raise
        except Exception:
            raise IntegrityError("Readable conversion failed; official ZIP retained unchanged") from None
    output.append("</body></html>")
    return "\n".join(output).encode("utf-8")


class Downloader:
    def __init__(self, root: Path, client, state):
        self.root, self.client, self.state = root, client, state

    def obtain(self, number: str):
        if not re.fullmatch(r"\d{14}", number):
            raise IntegrityError("Invalid document receipt number")
        path = self.root / "raw" / (number + ".zip")
        known = self.state.get("documents", number)
        if path.exists():
            body = path.read_bytes()
            if known and digest(body) == known.get("sha256") and len(body) == known.get("file_size"):
                return path, inspect_archive(body), known
            # Preserve suspicious files as evidence instead of trusting/overwriting.
            path.replace(path.with_name(path.name + ".untrusted-" + digest(body)[:12]))
        body = self.client.document(number)
        documents = inspect_archive(body)
        atomic_write(path, body)
        record = {"receipt_no": number, "sha256": digest(body), "file_size": len(body)}
        self.state.put("documents", number, record)
        return path, documents, record
