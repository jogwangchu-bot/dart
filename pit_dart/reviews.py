from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .core import InputError, IntegrityError, digest

OFFICIAL_HOSTS = {"dart.fss.or.kr", "opendart.fss.or.kr", "data.krx.co.kr", "kind.krx.co.kr"}


class Reviews:
    """Explicit, auditable human-reviewed evidence, never inference from today's map.

    Evidence files are administrator-only. A reviewer must independently inspect
    their provenance; hashing a file does not prove its authenticity.
    """
    def __init__(self, root: Path, path: Path | None, asof: date):
        self.root, self.asof = root.resolve(), asof
        self.data = {}
        if path and path.exists():
            try:
                self.data = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(self.data, dict) or any(not isinstance(self.data.get(key, {}), dict) for key in ("identities", "documents", "history")):
                    raise ValueError
            except (ValueError, OSError):
                raise InputError("Invalid review configuration") from None

    def evidence(self, record: dict) -> bool:
        if not isinstance(record, dict) or not record.get("reviewed_by") or not record.get("reviewed_at"):
            return False
        items = record.get("evidence", [])
        if not isinstance(items, list) or not items:
            return False
        try:
            for item in items:
                url = urlsplit(item["source_url"])
                if url.scheme != "https" or url.hostname not in OFFICIAL_HOSTS or url.username or url.password:
                    return False
                if any(k.lower() in ("crtfc_key", "api_key", "token") for k in parse_qs(url.query)):
                    return False
                if date.fromisoformat(item["publication_date"]) >= self.asof:
                    return False
                path = (self.root / item["path"]).resolve()
                path.relative_to(self.root / "config" / "evidence")
                if digest(path.read_bytes()) != item["sha256"]:
                    return False
        except (KeyError, TypeError, ValueError, OSError):
            return False
        return True

    def identity(self, stock_code: str):
        record = self.data.get("identities", {}).get(stock_code, {})
        if (not isinstance(record, dict) or record.get("asof") != self.asof.isoformat()
                or not re.fullmatch(r"\d{8}", str(record.get("corp_code", "")))
                or not record.get("historical_name")
                or not all(record.get(field) is True for field in ("stock_code_continuity_checked", "corporate_actions_checked", "historical_name_checked"))
                or not self.evidence(record)):
            return None
        return record

    def document(self, number: str):
        return self.data.get("documents", {}).get(number, {})
