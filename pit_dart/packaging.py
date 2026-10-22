from __future__ import annotations

import csv
import io
import re
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from .core import IntegrityError, atomic_write, canonical, digest

CSV_FILES = ("universe_asof.csv", "manifest.csv", "disclosure_index.csv", "missing.csv", "identity_review.csv", "coverage.csv")


def create_package(batch: Path, *, reviews, split_size: int | None = None):
    """An explicit whitelist: never zip a checkout/cache/admin directory recursively."""
    if not (batch / "coverage.csv").exists():
        raise IntegrityError("No collection report available for packaging")
    import json
    from .pipeline import UNIVERSE, MANIFEST, DISCLOSURES, MISSING, IDENTITY, COVERAGE
    schemas = dict(zip(CSV_FILES, (UNIVERSE, MANIFEST, DISCLOSURES, MISSING, IDENTITY, COVERAGE)))
    scope = json.loads((batch / "approval_scope.json").read_text())
    if scope.get("review_fingerprint") != digest(canonical(reviews.data).encode()):
        raise IntegrityError("Review configuration changed; rerun collection with --resume before packaging")
    def read(name):
        with (batch / name).open(encoding="utf-8-sig", newline="") as stream:
            return list(csv.DictReader(stream))
    coverage, manifest = read("coverage.csv"), read("manifest.csv")
    codes = [row["stock_code"] for row in coverage]
    groups = [codes] if not split_size else [group for group in (codes[:split_size], codes[split_size:]) if group]
    results = []
    for part, group in enumerate(groups, 1):
        members = set(group)
        buffer = io.BytesIO()
        with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
            for name in CSV_FILES:
                with (batch / name).open(encoding="utf-8-sig", newline="") as stream:
                    reader = csv.DictReader(stream)
                    fields = reader.fieldnames or []
                    if fields != schemas[name]:
                        raise IntegrityError("Unexpected evaluation CSV fields; possible administrator data contamination")
                    rows = [row for row in reader if row.get("stock_code") in members]
                out = io.StringIO(newline="")
                writer = csv.DictWriter(out, fieldnames=fields, lineterminator="\n")
                writer.writeheader()
                writer.writerows(rows)
                archive.writestr(name, out.getvalue().encode("utf-8-sig"))
            for row in manifest:
                if row["stock_code"] not in members or row["pit_status"] != "VERIFIED_WITH_REVIEW_EVIDENCE":
                    continue
                number = row["receipt_no"]
                evidence = reviews.document(number)
                if not reviews.identity(row["stock_code"]) or not reviews.evidence(evidence) or evidence.get("raw_sha256") != row["sha256"]:
                    raise IntegrityError("Approval evidence changed or is no longer valid")
                if not re.fullmatch(r"\d{14}", number) or row["filename"] != f"raw/{number}.zip":
                    raise IntegrityError("Unsafe manifest path")
                raw = batch / row["filename"]
                if digest(raw.read_bytes()) != row["sha256"] or len(raw.read_bytes()) != int(row["file_size"]):
                    raise IntegrityError("Approved original changed before packaging")
                archive.write(raw, row["filename"])
                readable = batch / "readable" / f"{number}.html"
                if not readable.is_file() or digest(readable.read_bytes()) != row.get("readable_sha256"):
                    raise IntegrityError("Readable artifact missing or changed before packaging")
                archive.write(readable, f"readable/{number}.html")
            # This is a batch-wide summary; only generic counts, no admin records.
            archive.write(batch / "collection_report.md", "collection_report.md")
        suffix = f"_part{part:02d}" if split_size else ""
        destination = batch.parent / (batch.name + suffix + ".zip")
        atomic_write(destination, buffer.getvalue())
        results.append(destination)
    return results
