import csv
import json
from pathlib import Path
from zipfile import ZipFile

import pytest

from pit_dart.cli import main
from pit_dart.core import DailyLimit, InputError, digest, read_universe
from pit_dart.packaging import create_package
from pit_dart.pipeline import Pipeline
from pit_dart.state import State
from .helpers import ANNUAL, ASOF, FakeClient, reviews, workbook


def setup(root, *, approved=True, resume=True):
    source = workbook(root / "input" / "universe.xlsx")
    fake = FakeClient()
    review = reviews(root, fake, approved=approved)
    state = State(root / "cache" / "state.sqlite3")
    pipeline = Pipeline(root, ASOF, read_universe(source), digest(source.read_bytes()), review, state, resume=resume)
    pipeline.prepare()
    return pipeline, fake, state


def read(path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def test_full_synthetic_pipeline_and_resume(tmp_path):
    pipeline, fake, state = setup(tmp_path)
    batch, status = pipeline.collect(pipeline.stocks, fake)
    assert status == 0
    assert read(batch / "coverage.csv")[0]["status"] == "READY"
    assert len(read(batch / "manifest.csv")) == 2
    assert len(fake.document_calls) == 2
    calls = len(fake.list_calls)
    pipeline.collect(pipeline.stocks, fake)
    assert len(fake.document_calls) == 2 and len(fake.list_calls) == calls
    assert pipeline.verify()["verified_originals"] == 2
    package = create_package(batch, reviews=pipeline.reviews)[0]
    with ZipFile(package) as archive:
        assert len([name for name in archive.namelist() if name.startswith("raw/")]) == 2
        assert all("CURRENT_NAME_2026" not in archive.read(name).decode("utf-8-sig") and "FUTURE_CORRECTION_2026" not in archive.read(name).decode("utf-8-sig") for name in archive.namelist() if name.endswith(".csv"))
        assert not any(name.startswith(("cache/", "config/", "input/")) for name in archive.namelist())
    state.close()


def test_unverified_identity_downloads_quarantined_not_packaged(tmp_path):
    pipeline, fake, state = setup(tmp_path, approved=False)
    batch, status = pipeline.collect(pipeline.stocks, fake)
    assert status == 0
    assert read(batch / "coverage.csv")[0]["status"] == "REVIEW_REQUIRED"
    assert len(list((tmp_path / "cache" / "raw").glob("*.zip"))) == 2
    assert read(batch / "manifest.csv") == []
    assert read(batch / "disclosure_index.csv") == []
    with ZipFile(create_package(batch, reviews=pipeline.reviews)[0]) as archive:
        assert not any(name.startswith(("raw/", "readable/")) for name in archive.namelist())
        assert "CURRENT_NAME_2026" not in archive.read("identity_review.csv").decode("utf-8-sig")
    state.close()


def test_missing_history_coverage_cannot_be_ready(tmp_path):
    pipeline, fake, state = setup(tmp_path)
    pipeline.reviews.data.pop("history")
    batch, _ = pipeline.collect(pipeline.stocks, fake)
    assert read(batch / "coverage.csv")[0]["status"] == "REVIEW_REQUIRED"
    state.close()


def test_daily_limit_stops_remaining_document_requests(tmp_path):
    pipeline, fake, state = setup(tmp_path)
    calls = []
    def daily_limit(number):
        calls.append(number)
        raise DailyLimit("synthetic daily limit")
    fake.document = daily_limit
    batch, status = pipeline.collect(pipeline.stocks, fake)
    assert status == 2 and len(calls) == 1
    assert read(batch / "coverage.csv")[0]["reason"] == "DAILY_LIMIT"
    state.close()


def test_initial_api_http_failure_keeps_safe_diagnostic_for_pc_handoff(tmp_path):
    pipeline, fake, state = setup(tmp_path)
    from pit_dart.core import APIHTTPError
    def unavailable():
        raise APIHTTPError("corpCode.xml", 502, exhausted=True)
    fake.corporations = unavailable
    batch, status = pipeline.collect(pipeline.stocks, fake)
    assert status == 2
    assert fake.list_calls == [] and fake.document_calls == []
    events = [json.loads(line) for line in (tmp_path / "logs" / "events.jsonl").read_text().splitlines()]
    assert events[0]["event"] == "api_failure"
    assert events[0]["http_status"] == 502 and events[0]["stage"] == "corpCode.xml"
    assert "SYNTHETIC" not in (tmp_path / "logs" / "events.jsonl").read_text()
    state.close()


def test_package_rechecks_hash(tmp_path):
    pipeline, fake, state = setup(tmp_path)
    batch, _ = pipeline.collect(pipeline.stocks, fake)
    original = batch / "raw" / (ANNUAL["rcept_no"] + ".zip")
    original.write_bytes(b"corrupt")
    from pit_dart.core import IntegrityError
    with pytest.raises(IntegrityError):
        create_package(batch, reviews=pipeline.reviews)
    assert pipeline.verify()["failed_receipts"] == [ANNUAL["rcept_no"]]
    assert read(batch / "coverage.csv")[0]["status"] == "FAILED"
    assert read(pipeline.output / "coverage.csv")[0]["integrity"] == "FAILED"
    manifest = read(batch / "manifest.csv")
    assert [r for r in manifest if r["receipt_no"] == ANNUAL["rcept_no"]][0]["pit_status"] == "FAILED"
    state.close()


def test_missing_quarantined_original_detected_not_ignored(tmp_path):
    pipeline, fake, state = setup(tmp_path, approved=False)
    pipeline.collect(pipeline.stocks, fake)
    (tmp_path / "cache" / "raw" / (ANNUAL["rcept_no"] + ".zip")).unlink()
    assert pipeline.verify()["failed_receipts"] == [ANNUAL["rcept_no"]]
    assert read(pipeline.output / "coverage.csv")[0]["integrity"] == "FAILED"
    state.close()


def test_unverified_identity_cannot_be_reported_as_definitely_not_filed(tmp_path):
    pipeline, fake, state = setup(tmp_path, approved=False)
    fake.records = []
    batch, _ = pipeline.collect(pipeline.stocks, fake)
    row = read(batch / "coverage.csv")[0]
    assert row["status"] == "REVIEW_REQUIRED"
    assert row["annual"] == row["interim"] == "IDENTITY_UNVERIFIED"
    state.close()


def test_changed_review_or_evidence_prevents_stale_package(tmp_path):
    pipeline, fake, state = setup(tmp_path)
    batch, _ = pipeline.collect(pipeline.stocks, fake)
    from pit_dart.core import IntegrityError
    evidence = tmp_path / pipeline.reviews.data["identities"]["000001"]["evidence"][0]["path"]
    evidence.write_text("tampered evidence")
    with pytest.raises(IntegrityError):
        create_package(batch, reviews=pipeline.reviews)
    assert pipeline.all_coverage()[0]["status"] == "REVIEW_REQUIRED"
    state.close()


def test_extra_admin_column_in_csv_rejected_during_packaging(tmp_path):
    pipeline, fake, state = setup(tmp_path)
    batch, _ = pipeline.collect(pipeline.stocks, fake)
    path = batch / "universe_asof.csv"
    content = path.read_text(encoding="utf-8-sig").splitlines()
    content[0] += ",future_status_2026"
    path.write_text("\n".join(content), encoding="utf-8-sig")
    from pit_dart.core import IntegrityError
    with pytest.raises(IntegrityError):
        create_package(batch, reviews=pipeline.reviews)
    state.close()


def test_large_run_is_gated(tmp_path):
    pipeline, fake, state = setup(tmp_path)
    with pytest.raises(InputError):
        pipeline.enforce_gate(pipeline.stocks * 6)
    assert fake.list_calls == []
    state.close()


def test_gates_accept_only_explicitly_reviewed_real_query_exceptions(tmp_path):
    pipeline, fake, state = setup(tmp_path, approved=False)
    from pit_dart.core import Stock
    pipeline.stocks = [Stock(i, f"{i:06d}", i+1) for i in range(1, 7)]
    accepted = {}
    for stock in pipeline.stocks[:5]:
        row = pipeline.blank(stock)
        row.update(status="REVIEW_REQUIRED", reason="HISTORICAL_IDENTITY_UNVERIFIED", disclosure_index="CANDIDATE_ONLY")
        state.put("coverage", f"{pipeline.scope}:{stock.code}", row)
        accepted[stock.code] = {"status": row["status"], "reason": row["reason"], "official_sources_checked": True, "documented_cause": "SYNTHETIC reviewed exception"}
    path = tmp_path / "config" / "evidence" / "gate.md"
    path.write_text("SYNTHETIC five-stock review")
    gate = {"asof": str(ASOF), "input_sha256": pipeline.input_hash, "major_defects_resolved": True, "reviewed_by": "Synthetic Reviewer",
            "report_path": str(path.relative_to(tmp_path)), "report_sha256": digest(path.read_bytes()), "accepted_exceptions": accepted}
    (tmp_path / "config" / "validation-gates.json").write_text(json.dumps({"five": gate}))
    pipeline.enforce_gate(pipeline.stocks)
    accepted["000001"]["official_sources_checked"] = False
    (tmp_path / "config" / "validation-gates.json").write_text(json.dumps({"five": gate}))
    with pytest.raises(InputError):
        pipeline.enforce_gate(pipeline.stocks)
    state.close()


def test_25_stock_delivery_splits_into_12_and_13(tmp_path):
    pipeline, fake, state = setup(tmp_path, approved=False)
    from pit_dart.core import Stock
    selected = [Stock(i, f"{i:06d}", i+1) for i in range(1, 26)]
    batch = pipeline.output / "batch_001_025"
    pipeline.export(batch, selected, [], [], [], [], [pipeline.blank(s) for s in selected], {})
    paths = create_package(batch, reviews=pipeline.reviews, split_size=12)
    sizes = []
    for path in paths:
        with ZipFile(path) as archive:
            import io
            sizes.append(len(list(csv.DictReader(io.StringIO(archive.read("universe_asof.csv").decode("utf-8-sig"))))))
    assert sizes == [12, 13]
    state.close()


def test_input_change_does_not_reuse_existing_output_scope(tmp_path):
    pipeline, fake, state = setup(tmp_path)
    with pytest.raises(InputError):
        Pipeline(tmp_path, ASOF, pipeline.stocks, "changed-input-hash", pipeline.reviews, state)
    state.close()


def test_prepare_cli_is_offline_and_does_not_claim_collection(tmp_path, capsys):
    source = workbook(tmp_path / "input.xlsx")
    status = main(["--workspace", str(tmp_path), "--input", str(source), "--asof", str(ASOF), "--prepare"])
    assert status == 0
    assert '"actual_downloads":0' in capsys.readouterr().out
    assert read(tmp_path / "output" / str(ASOF) / "coverage.csv")[0]["status"] == "NOT_RUN"


def test_live_cli_missing_key_records_failure_without_fake_success(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("DART_API_KEY", raising=False)
    source = workbook(tmp_path / "input.xlsx")
    status = main(["--workspace", str(tmp_path), "--input", str(source), "--asof", str(ASOF), "--test"])
    assert status == 2
    assert "CREDENTIAL_REQUIRED" in capsys.readouterr().err
    assert read(tmp_path / "output" / str(ASOF) / "coverage.csv")[0]["reason"] == "CREDENTIAL_REQUIRED"


def test_verify_with_no_files_is_explicit(tmp_path, capsys):
    source = workbook(tmp_path / "input.xlsx")
    assert main(["--workspace", str(tmp_path), "--input", str(source), "--asof", str(ASOF), "--verify"]) == 0
    assert '"zero_files_is_not_collection_validation":true' in capsys.readouterr().out
