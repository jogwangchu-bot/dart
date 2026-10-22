"""Offline regressions from actual official web-listing metadata.

These are candidate-selection checks, NOT live API/original/PIT approvals.
Search scope was 2019-01-01..2019-09-17, not the full historical index.
"""
import json
from datetime import date
from pathlib import Path

import pytest

from pit_dart.selection import select_reports

REFERENCE = json.loads((Path(__file__).parent / "fixtures" / "public_dart_2019_candidates.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("stock", REFERENCE["stocks"], ids=lambda item: item["stock_code"])
def test_actual_public_listed_periods_and_pre_cutoff_corrections(stock):
    records = [{"rcept_no": row["receipt_no"], "rcept_dt": row["receipt_no"][:8], "report_nm": row["title"]} for row in stock["periodic_candidates"]]
    annual, interim = select_reports(records, date(2019, 9, 17), listing_complete=True)
    assert annual.record["rcept_no"] == stock["expected_annual_receipt"]
    assert interim.record["rcept_no"] == stock["expected_interim_receipt"]
    if stock["stock_code"] == "000970":
        assert annual.period == "2019-03"
        assert "분기보고서" in interim.record["report_nm"]
    if stock["stock_code"] == "000890":
        assert "기재정정" in annual.record["report_nm"]
    assert annual.status != "VERIFIED_WITH_REVIEW_EVIDENCE"
