from __future__ import annotations

import re
from datetime import datetime, timezone

from defusedxml import ElementTree

from .core import IntegrityError
from .documents import inspect_archive


def parse_corporations(body: bytes):
    documents = inspect_archive(body)
    result = []
    for source in documents.values():
        root = ElementTree.fromstring(source)
        for entry in root.findall("list"):
            item = {child.tag: child.text or "" for child in entry}
            if not re.fullmatch(r"\d{8}", item.get("corp_code", "")):
                raise IntegrityError("Corporation mapping has invalid DART code")
            stock_code = item.get("stock_code", "").strip()
            if stock_code and not re.fullmatch(r"\d{6}", stock_code):
                raise IntegrityError("Corporation mapping has invalid stock code")
            item["stock_code"] = stock_code
            result.append(item)
    if not result:
        raise IntegrityError("Corporation mapping is empty")
    return result


def resolve(stock, corporations, reviews):
    verified = reviews.identity(stock.code)
    matches = [item for item in corporations if item["stock_code"] == stock.code]
    record = {"stock_code": stock.code, "source": "OpenDART corpCode.xml (current mapping, not historical proof)",
              "checked_at": datetime.now(timezone.utc).isoformat(), "current_candidates": matches,
              "status": "REVIEW_REQUIRED", "historical_name": "", "corp_code": "",
              "reason": "HISTORICAL_IDENTITY_UNVERIFIED"}
    if verified:
        record.update(status="VERIFIED_WITH_REVIEW_EVIDENCE", corp_code=verified["corp_code"],
                      historical_name=verified["historical_name"], reason="")
    elif len(matches) == 1:
        record["candidate_corp_code"] = matches[0]["corp_code"]
    else:
        # Hints are for administrative fallback only and do not establish identity.
        names = set(stock.hints[:2]) - {""}
        record["name_candidates"] = [item for item in corporations if item.get("corp_name") in names]
        record["reason"] = "MULTIPLE_IDENTITY_CANDIDATES" if matches else "IDENTITY_NOT_RESOLVED"
        record["fallback_sources"] = ["Excel historical-name hint", "DART historical-name search", "KRX historical listings", "Official corporate-action disclosures"]
    return record
