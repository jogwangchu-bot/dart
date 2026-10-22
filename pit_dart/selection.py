from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date

PATTERN = re.compile(r"^\s*(?:\[[^\]]+\]\s*)*(사업보고서|반기보고서|분기보고서)\s*\((\d{4})[.\-/](\d{1,2})\)")


def describe(title):
    match = PATTERN.match(title)
    if not match:
        return None
    name, year, month = match.groups()
    try:
        period = date(int(year), int(month), 1)
    except ValueError:
        return None
    kind = "annual" if name == "사업보고서" else "interim"
    correction = next((label for label in ("기재정정", "첨부정정", "첨부추가", "정정", "철회") if f"[{label}]" in title), "")
    return kind, period.strftime("%Y-%m"), correction


@dataclass
class Selection:
    kind: str
    record: dict | None
    period: str = ""
    status: str = "CANDIDATE_REQUIRES_DOCUMENT_VERIFICATION"
    reason: str = ""


def select_reports(records, end: date, *, listing_complete: bool):
    selections = []
    for kind in ("annual", "interim"):
        eligible, ambiguous = [], False
        for item in records:
            if item["rcept_dt"] > end.strftime("%Y%m%d"):
                continue
            title = item["report_nm"]
            metadata = describe(title)
            if metadata and metadata[0] == kind:
                eligible.append((metadata[1], item["rcept_no"], item, metadata[2]))
            elif not metadata and any(name in title for name in (("사업보고서",) if kind == "annual" else ("반기보고서", "분기보고서"))):
                ambiguous = True
        if not listing_complete:
            selections.append(Selection(kind, None, status="FETCH_FAILED", reason="DISCLOSURE_LIST_INCOMPLETE"))
        elif not eligible:
            selections.append(Selection(kind, None, status="PIT_REVIEW_REQUIRED" if ambiguous else "NOT_FILED_IN_SEARCHED_RANGE",
                                        reason="REPORTING_PERIOD_UNRESOLVED" if ambiguous else "HISTORICAL_COVERAGE_MUST_BE_VERIFIED"))
        else:
            period, _, item, correction = max(eligible, key=lambda value: value[:2])
            status = "PIT_REVIEW_REQUIRED" if ambiguous or correction == "철회" else "CANDIDATE_REQUIRES_DOCUMENT_VERIFICATION"
            reason = "REPORT_PERIOD_AMBIGUOUS_OR_WITHDRAWAL" if status == "PIT_REVIEW_REQUIRED" else ""
            year, month = map(int, period.split("-"))
            if date(year, month, calendar.monthrange(year, month)[1]) > end:
                status, reason = "PIT_REVIEW_REQUIRED", "REPORTING_PERIOD_AFTER_CUTOFF"
            selections.append(Selection(kind, item, period, status, reason))
    return selections


def validate_document(selection, archive_record, documents, identity, records, reviews):
    """Bind official-record review to exact bytes and reject explicit contradictions.

    Titles identify candidates only. Hash-bound official record evidence is
    mandatory because current API bytes alone cannot establish historical state.
    """
    from lxml import etree
    from .documents import xml_tree
    record = selection.record
    if not record or identity.get("status") != "VERIFIED_WITH_REVIEW_EVIDENCE":
        return "PIT_REVIEW_REQUIRED", "HISTORICAL_IDENTITY_UNVERIFIED"
    if selection.status == "PIT_REVIEW_REQUIRED":
        return "PIT_REVIEW_REQUIRED", selection.reason
    number = record["rcept_no"]
    evidence = reviews.document(number)
    expected = {"corp_code": identity["corp_code"], "stock_code": identity["stock_code"],
                "receipt_no": number, "reporting_period": selection.period, "document_type": selection.kind,
                "raw_sha256": archive_record["sha256"], "asof": reviews.asof.isoformat()}
    if any(evidence.get(key) != value for key, value in expected.items()):
        return "PIT_REVIEW_REQUIRED", "OFFICIAL_RECORD_BYTE_BOUND_EVIDENCE_REQUIRED"
    for field in ("receipt_checked", "corporation_checked", "period_checked", "historical_version_checked", "full_content_checked", "attachments_checked"):
        if evidence.get(field) is not True:
            return "PIT_REVIEW_REQUIRED", "OFFICIAL_RECORD_CHECKS_INCOMPLETE"
    if evidence.get("missing_attachments") != []:
        return "PIT_REVIEW_REQUIRED", "OFFICIAL_ATTACHMENTS_MISSING_OR_UNCHECKED"
    if not reviews.evidence(evidence):
        return "PIT_REVIEW_REQUIRED", "OFFICIAL_RECORD_EVIDENCE_INVALID_OR_MISSING"
    # When the original contains explicit machine-readable identifiers, a manual
    # approval cannot override a contradiction.
    for source in documents.values():
        root = xml_tree(source)
        for element in root.iter():
            if not isinstance(element.tag, str):
                continue
            tag = etree.QName(element).localname.upper()
            value = (element.text or "").strip()
            if tag in ("RECEIPT-NO", "RCEPT_NO") and re.fullmatch(r"\d{14}", value) and value != number:
                return "FAILED", "ORIGINAL_RECEIPT_MISMATCH"
            if tag == "COMPANY-NAME" and element.get("AREGCIK") and element.get("AREGCIK") != identity["corp_code"]:
                return "FAILED", "ORIGINAL_CORPORATION_MISMATCH"
            if tag in ("CORP-CODE", "CORP_CODE") and re.fullmatch(r"\d{8}", value) and value != identity["corp_code"]:
                return "FAILED", "ORIGINAL_CORPORATION_MISMATCH"
            if tag in ("STOCK-CODE", "STOCK_CODE") and re.fullmatch(r"\d{6}", value) and value != identity["stock_code"]:
                return "FAILED", "ORIGINAL_STOCK_CODE_MISMATCH"
            if tag in ("REPORTING-PERIOD", "REPORTING_PERIOD") and re.fullmatch(r"\d{4}[.\-/]\d{2}", value):
                if value[:4] + "-" + value[-2:] != selection.period:
                    return "FAILED", "ORIGINAL_PERIOD_MISMATCH"
            if tag == "DOCUMENT-NAME" and element.get("ACODE") in ("11011", "11012", "11013", "11014"):
                if (element.get("ACODE") == "11011") != (selection.kind == "annual"):
                    return "FAILED", "ORIGINAL_DOCUMENT_TYPE_MISMATCH"
    by_number = {row["rcept_no"]: row for row in records}
    same_period = [row for row in records if describe(row["report_nm"]) and describe(row["report_nm"])[:2] == (selection.kind, selection.period)]
    seen, cursor = set(), number
    while cursor:
        if cursor in seen or cursor not in by_number:
            return "PIT_REVIEW_REQUIRED", "CORRECTION_RELATION_UNRESOLVED"
        seen.add(cursor)
        item = by_number[cursor]
        metadata = describe(item["report_nm"])
        if not metadata or metadata[:2] != (selection.kind, selection.period):
            return "PIT_REVIEW_REQUIRED", "CORRECTION_PERIOD_MISMATCH"
        if metadata[2] == "철회":
            return "PIT_REVIEW_REQUIRED", "WITHDRAWAL_REQUIRES_RECONSTRUCTION"
        if not metadata[2]:
            break
        relation = reviews.document(cursor)
        parent = relation.get("correction_parent", "")
        if (not parent or not reviews.evidence(relation) or relation.get("correction_relation_checked") is not True
                or parent >= cursor or parent not in by_number):
            return "PIT_REVIEW_REQUIRED", "CORRECTION_RELATION_UNRESOLVED"
        cursor = parent
    if set(row["rcept_no"] for row in same_period) != seen:
        return "PIT_REVIEW_REQUIRED", "UNCONNECTED_SAME_PERIOD_FILINGS"
    return "VERIFIED_WITH_REVIEW_EVIDENCE", ""
