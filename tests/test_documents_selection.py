import json
from datetime import date

import pytest

from pit_dart.core import IntegrityError, digest
from pit_dart.documents import Downloader, inspect_archive, readable_html
from pit_dart.identity import parse_corporations, resolve
from pit_dart.selection import describe, select_reports, validate_document
from pit_dart.core import Stock
from pit_dart.state import State
from .helpers import ANNUAL, ASOF, CORP, INTERIM, FakeClient, archive, disclosure, document, reviews


@pytest.mark.parametrize("payload", [b"<result><status>014</status></result>", b"PKbroken", archive({"error.xml": "<result><status>014</status></result>"}), archive({"bad.xml": "<broken>"}), archive({"../unsafe.xml": "<x/>"}), archive({"no-xml.txt": "x"})])
def test_bad_originals_never_accepted(payload):
    with pytest.raises(IntegrityError):
        inspect_archive(payload)


def test_entities_rejected_and_tables_preserved():
    malicious = archive({"x.xml": '<!DOCTYPE x [<!ENTITY xxe SYSTEM "file:///etc/passwd">]><x>&xxe;</x>'})
    with pytest.raises(IntegrityError):
        inspect_archive(malicious)
    files = {"x.xml": '<D><TABLE><TR><TH ROWSPAN="2">항목</TH><TD COLSPAN="2">1,234 백만원</TD></TR></TABLE><P>&lt;script&gt;</P></D>'.encode()}
    html = readable_html(files).decode()
    assert 'rowspan="2"' in html and 'colspan="2"' in html and "1,234 백만원" in html
    assert "<script>" not in html
    assert "&lt;D&gt;" in html  # Complete escaped source remains in addition to rendered table.


def test_unsupported_nested_table_conversion_fails_explicitly():
    with pytest.raises(IntegrityError):
        readable_html({"x.xml": b"<D><TABLE><TR><TD><TABLE><TR><TD>x</TD></TR></TABLE></TD></TR></TABLE></D>"})


def test_download_resume_revalidates_hash_and_repairs_corrupt_file(tmp_path):
    client, state = FakeClient(), State(tmp_path / "state.sqlite")
    downloader = Downloader(tmp_path, client, state)
    path, _, metadata = downloader.obtain(ANNUAL["rcept_no"])
    downloader.obtain(ANNUAL["rcept_no"])
    assert len(client.document_calls) == 1
    path.write_bytes(b"corrupt")
    downloader.obtain(ANNUAL["rcept_no"])
    assert len(client.document_calls) == 2
    assert digest(path.read_bytes()) == metadata["sha256"]
    assert list(path.parent.glob("*.untrusted-*"))
    state.close()


def test_latest_reporting_period_wins_over_late_older_year_correction():
    old = disclosure("20190916000001", "[기재정정]사업보고서 (2017.12)")
    selected = select_reports([old, ANNUAL, INTERIM], date(2019, 9, 17), listing_complete=True)
    assert selected[0].record == ANNUAL
    assert selected[1].record == INTERIM


def test_pre_cutoff_correction_selected_post_cutoff_excluded_and_current_remark_ignored():
    before = disclosure("20190910000001", "[기재정정]반기보고서 (2019.06)")
    future = disclosure("20200320000001", "[기재정정]반기보고서 (2019.06)")
    chosen = select_reports([INTERIM, before, future], date(2019, 9, 17), listing_complete=True)[1]
    assert chosen.record == before
    assert "FUTURE_CORRECTION" in chosen.record["rm"]
    assert chosen.status == "CANDIDATE_REQUIRES_DOCUMENT_VERIFICATION"


def test_non_december_fiscal_period_not_overridden():
    row = disclosure("20190628000001", "사업보고서 (2019.03)")
    assert select_reports([row], date(2019, 9, 17), listing_complete=True)[0].period == "2019-03"


def test_future_accounting_period_is_not_approved_by_early_receipt():
    row = disclosure("20190916000001", "반기보고서 (2020.06)")
    result = select_reports([row], date(2019, 9, 17), listing_complete=True)[1]
    assert result.status == "PIT_REVIEW_REQUIRED"
    assert result.reason == "REPORTING_PERIOD_AFTER_CUTOFF"


def test_unknown_period_and_incomplete_listing_do_not_become_not_filed():
    row = disclosure("20190901000001", "사업보고서 (알수없음)")
    assert select_reports([row], date(2019, 9, 17), listing_complete=True)[0].status == "PIT_REVIEW_REQUIRED"
    assert select_reports([], date(2019, 9, 17), listing_complete=False)[0].status == "FETCH_FAILED"


def test_current_mapping_not_historical_identity(tmp_path):
    fake = FakeClient()
    review = reviews(tmp_path, fake, approved=False)
    identity = resolve(Stock(1, "000001", 2), parse_corporations(fake.corporations()), review)
    assert identity["status"] == "REVIEW_REQUIRED"
    assert identity["candidate_corp_code"] == CORP


def test_duplicate_current_candidates_never_arbitrarily_selected(tmp_path):
    review = reviews(tmp_path, FakeClient(), approved=False)
    result = resolve(Stock(1, "000001", 2), [{"stock_code": "000001", "corp_code": CORP}, {"stock_code": "000001", "corp_code": "00000002"}], review)
    assert "candidate_corp_code" not in result
    assert result["reason"] == "MULTIPLE_IDENTITY_CANDIDATES"


def test_official_record_evidence_bound_to_exact_original(tmp_path):
    fake = FakeClient()
    review = reviews(tmp_path, fake)
    identity = resolve(Stock(1, "000001", 2), parse_corporations(fake.corporations()), review)
    selection = select_reports(fake.records, date(2019, 9, 17), listing_complete=True)[0]
    body = fake.bodies[ANNUAL["rcept_no"]]
    status, reason = validate_document(selection, {"sha256": digest(body)}, inspect_archive(body), identity, fake.records, review)
    assert status == "VERIFIED_WITH_REVIEW_EVIDENCE"
    status, reason = validate_document(selection, {"sha256": "0" * 64}, inspect_archive(body), identity, fake.records, review)
    assert status == "PIT_REVIEW_REQUIRED"


def test_matching_title_cannot_establish_correction_relation(tmp_path):
    correction = disclosure("20190910000001", "[기재정정]반기보고서 (2019.06)")
    fake = FakeClient([ANNUAL, INTERIM, correction])
    fake.bodies[correction["rcept_no"]] = document(correction["rcept_no"], "interim")
    review = reviews(tmp_path, fake)
    identity = resolve(Stock(1, "000001", 2), parse_corporations(fake.corporations()), review)
    selection = select_reports(fake.records, date(2019, 9, 17), listing_complete=True)[1]
    body = fake.bodies[correction["rcept_no"]]
    status, reason = validate_document(selection, {"sha256": digest(body)}, inspect_archive(body), identity, fake.records, review)
    assert (status, reason) == ("PIT_REVIEW_REQUIRED", "CORRECTION_RELATION_UNRESOLVED")
    review.data["documents"][correction["rcept_no"]].update(correction_parent=INTERIM["rcept_no"], correction_relation_checked=True)
    assert validate_document(selection, {"sha256": digest(body)}, inspect_archive(body), identity, fake.records, review)[0] == "VERIFIED_WITH_REVIEW_EVIDENCE"


@pytest.mark.parametrize("mutation", ["partial_original", "missing_attachment"])
def test_partial_original_or_missing_attachment_not_approved(tmp_path, mutation):
    fake = FakeClient()
    review = reviews(tmp_path, fake)
    evidence = review.data["documents"][ANNUAL["rcept_no"]]
    if mutation == "partial_original": evidence["full_content_checked"] = False
    if mutation == "missing_attachment": evidence["missing_attachments"] = ["SYNTHETIC missing exhibit"]
    identity = resolve(Stock(1, "000001", 2), parse_corporations(fake.corporations()), review)
    selection = select_reports(fake.records, date(2019, 9, 17), listing_complete=True)[0]
    body = fake.bodies[ANNUAL["rcept_no"]]
    assert validate_document(selection, {"sha256": digest(body)}, inspect_archive(body), identity, fake.records, review)[0] == "PIT_REVIEW_REQUIRED"


def test_manual_evidence_cannot_override_explicit_wrong_corporation(tmp_path):
    fake = FakeClient()
    fake.bodies[ANNUAL["rcept_no"]] = document(ANNUAL["rcept_no"], company="99999999")
    review = reviews(tmp_path, fake)
    identity = resolve(Stock(1, "000001", 2), parse_corporations(fake.corporations()), review)
    selection = select_reports(fake.records, date(2019, 9, 17), listing_complete=True)[0]
    body = fake.bodies[ANNUAL["rcept_no"]]
    assert validate_document(selection, {"sha256": digest(body)}, inspect_archive(body), identity, fake.records, review) == ("FAILED", "ORIGINAL_CORPORATION_MISMATCH")


@pytest.mark.parametrize("extra,reason", [("<REPORTING-PERIOD>2017-12</REPORTING-PERIOD>", "ORIGINAL_PERIOD_MISMATCH"), ("<STOCK-CODE>999999</STOCK-CODE>", "ORIGINAL_STOCK_CODE_MISMATCH")])
def test_manual_review_cannot_override_explicit_period_or_stock_mismatch(tmp_path, extra, reason):
    fake = FakeClient()
    fake.bodies[ANNUAL["rcept_no"]] = document(ANNUAL["rcept_no"], extra=extra)
    review = reviews(tmp_path, fake)
    identity = resolve(Stock(1, "000001", 2), parse_corporations(fake.corporations()), review)
    selection = select_reports(fake.records, date(2019, 9, 17), listing_complete=True)[0]
    body = fake.bodies[ANNUAL["rcept_no"]]
    assert validate_document(selection, {"sha256": digest(body)}, inspect_archive(body), identity, fake.records, review) == ("FAILED", reason)


@pytest.mark.parametrize("mutation", ["hash", "future", "outside", "credential_url", "nonofficial"])
def test_invalid_review_evidence_cannot_approve_identity(tmp_path, mutation):
    review = reviews(tmp_path, FakeClient())
    item = review.data["identities"]["000001"]["evidence"][0]
    if mutation == "hash": item["sha256"] = "0" * 64
    if mutation == "future": item["publication_date"] = "2020-01-01"
    if mutation == "outside": item["path"] = "../outside"
    if mutation == "credential_url": item["source_url"] = "https://dart.fss.or.kr/?crtfc_key=SECRET"
    if mutation == "nonofficial": item["source_url"] = "https://example.com/"
    assert review.identity("000001") is None
