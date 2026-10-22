from __future__ import annotations

import json
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path

from .core import (CollectorError, CredentialError, DailyLimit, InputError, IntegrityError,
                   atomic_write, canonical, cutoff, digest, receipt_url, universe_projection, write_csv, write_json)
from .documents import Downloader, inspect_archive, readable_html
from .identity import parse_corporations, resolve
from .indexer import Indexer
from .selection import describe, select_reports, validate_document

UNIVERSE = ["order", "stock_code", "asof", "historical_name"]
MANIFEST = ["stock_code", "filename", "document_name", "publication_date", "receipt_no", "source_url", "sha256", "is_correction",
            "corp_code", "reporting_period", "document_type", "correction_type", "pit_status", "download_status", "file_size", "readable_sha256"]
DISCLOSURES = ["stock_code", "corp_code", "document_name", "publication_date", "receipt_no", "document_type", "correction_type", "filer", "source_url"]
MISSING = ["stock_code", "required_document", "missing_reason", "attempted_sources"]
IDENTITY = ["stock_code", "status", "reason", "attempted_sources"]
COVERAGE = ["order", "stock_code", "identity", "annual", "interim", "disclosure_index", "pit", "integrity", "status", "reason"]


class Pipeline:
    def __init__(self, root, asof, stocks, input_hash, reviews, state, *, history_start=date(1999, 1, 1), resume=False):
        self.root, self.asof, self.stocks = root, asof, stocks
        self.input_hash, self.reviews, self.state = input_hash, reviews, state
        self.review_fingerprint = digest(canonical(reviews.data).encode())
        self.start, self.end, self.resume = history_start, cutoff(asof).date(), resume
        if self.start > self.end:
            raise InputError("History start is after the information cutoff")
        self.scope = digest(f"{input_hash}:{asof}:{history_start}".encode())
        self.output = root / "output" / str(asof)
        self.cache = root / "cache"
        marker = self.output / "input_scope.json"
        expected = {"input_sha256": input_hash, "asof": str(asof), "history_start": str(history_start)}
        if marker.exists() and json.loads(marker.read_text()) != expected:
            raise InputError("Output directory belongs to a different input/history scope; use a different --workspace")
        write_json(marker, expected)

    def event(self, event, **fields):
        path = self.root / "logs" / "events.jsonl"
        entry = {"at": datetime.now(timezone.utc).isoformat(), "event": event, **fields}
        previous = path.read_bytes() if path.exists() else b""
        atomic_write(path, previous + (canonical(entry) + "\n").encode())

    def blank(self, stock):
        return {"order": stock.order, "stock_code": stock.code, "identity": "NOT_RUN", "annual": "NOT_RUN", "interim": "NOT_RUN",
                "disclosure_index": "NOT_RUN", "pit": "NOT_RUN", "integrity": "NOT_RUN", "status": "NOT_RUN", "reason": ""}

    def failure_event(self, error, stage):
        http_status = getattr(error, "http_status", None)
        api_status = getattr(error, "api_status", None)
        if not isinstance(http_status, int) or not 100 <= http_status <= 599:
            http_status = None
        if not isinstance(api_status, str) or len(api_status) != 3 or not api_status.isascii() or not api_status.isdigit():
            api_status = None
        self.event("api_failure", stage=stage, error_code=error.code, http_status=http_status, api_status=api_status)

    def history_verified(self):
        record = self.reviews.data.get("history", {})
        return (record.get("available_from") == str(self.start) and record.get("earliest_available_checked") is True
                and self.reviews.evidence(record))

    def all_coverage(self):
        rows = []
        for stock in self.stocks:
            row = self.state.get("coverage", f"{self.scope}:{stock.code}") or self.blank(stock)
            if row["status"] == "READY" and (row.get("approval_fingerprint") != self.review_fingerprint or not self.reviews.identity(stock.code)):
                row.update(status="REVIEW_REQUIRED", pit="PIT_REVIEW_REQUIRED", reason="REVIEW_EVIDENCE_CHANGED_OR_INVALID")
            rows.append(row)
        return rows

    def prepare(self):
        # No present-day names or administrator columns are copied here.
        write_csv(self.output / "universe_asof.csv", UNIVERSE, universe_projection(self.stocks, self.asof))
        write_csv(self.output / "coverage.csv", COVERAGE, self.all_coverage())
        write_json(self.root / "cache" / "input_audit.json", {
            "input_sha256": self.input_hash, "stock_count": len(self.stocks), "input_order_preserved": True,
            "future_columns_quarantined": True, "cutoff_kst": cutoff(self.asof).isoformat(),
            "worksheet_rows": [{"order": s.order, "stock_code": s.code, "row": s.row, "administrator_hints": s.hints} for s in self.stocks]})

    def enforce_gate(self, selected):
        if len(selected) <= 5:
            return
        stage = "five" if len(selected) <= 25 else "twenty_five"
        required = 5 if stage == "five" else 25
        path = self.root / "config" / "validation-gates.json"
        try:
            gates = json.loads(path.read_text())
            gate = gates[stage]
            record_path = (self.root / gate["report_path"]).resolve()
            record_path.relative_to(self.root / "config" / "evidence")
            valid = (gate["asof"] == str(self.asof) and gate["input_sha256"] == self.input_hash
                     and gate["major_defects_resolved"] is True and gate["reviewed_by"]
                     and digest(record_path.read_bytes()) == gate["report_sha256"])
            accepted = gate.get("accepted_exceptions", {})
            verified = []
            for item in self.all_coverage():
                if item["status"] == "READY":
                    verified.append(item)
                elif item["status"] in ("MISSING", "REVIEW_REQUIRED") and item["disclosure_index"] in ("COMPLETE", "CANDIDATE_ONLY"):
                    exception = accepted.get(item["stock_code"], {})
                    if (exception.get("status") == item["status"] and exception.get("reason") == item["reason"]
                            and exception.get("official_sources_checked") is True and exception.get("documented_cause")):
                        verified.append(item)
            if not valid or len(verified) < required:
                raise ValueError
        except (OSError, KeyError, TypeError, ValueError):
            raise InputError(f"Live validation gate not met: {required} verified real stocks and a hash-bound review report required; run --test first") from None

    def _corporations(self, client):
        path = self.cache / "corpCode.zip"
        metadata = self.state.get("meta", "corpCode")
        if self.resume and path.exists() and metadata and digest(path.read_bytes()) == metadata.get("sha256"):
            return parse_corporations(path.read_bytes())
        body = client.corporations()
        records = parse_corporations(body)
        atomic_write(path, body)
        self.state.put("meta", "corpCode", {"sha256": digest(body), "checked_at": datetime.now(timezone.utc).isoformat()})
        return records

    def collect(self, selected, client):
        self.enforce_gate(selected)
        manifest, disclosures, missing, identity_rows, coverage, names = [], [], [], [], [], {}
        batch = self.output / f"batch_{selected[0].order:03d}_{selected[-1].order:03d}"
        halted, fatal_code = False, None
        try:
            corporations = self._corporations(client)
        except CollectorError as error:
            self.failure_event(error, "corpCode.xml")
            corporations, fatal_code = [], error.code
            halted = True
        downloader = Downloader(self.cache, client, self.state)
        for stock in selected:
            row = self.blank(stock)
            try:
                if halted:
                    row.update(status="FAILED", reason=fatal_code or "STOPPED_AFTER_DAILY_LIMIT")
                    missing.append({"stock_code": stock.code, "required_document": "all", "missing_reason": row["reason"], "attempted_sources": "OpenDART"})
                    continue
                identity = resolve(stock, corporations, self.reviews)
                write_json(self.cache / "admin" / self.scope / f"identity_{stock.code}.json", identity)
                row["identity"] = identity["status"]
                verified = identity["status"] == "VERIFIED_WITH_REVIEW_EVIDENCE"
                identity_rows.append({"stock_code": stock.code, "status": identity["status"], "reason": identity["reason"],
                                      "attempted_sources": "corpCode.xml; administrative historical-identity evidence"})
                if verified:
                    names[stock.code] = identity["historical_name"]
                corp_code = identity.get("corp_code") or identity.get("candidate_corp_code")
                if not corp_code:
                    row.update(status="REVIEW_REQUIRED", reason="IDENTITY_NOT_RESOLVED")
                    missing.append({"stock_code": stock.code, "required_document": "all", "missing_reason": "IDENTITY_NOT_RESOLVED", "attempted_sources": "corpCode.xml; historical identity review required"})
                    continue
                # Unverified candidates are investigated in the admin cache only;
                # their documents/listings cannot enter the evaluation package.
                records, windows = Indexer(client, self.state, self.resume).collect(corp_code, self.start, self.end)
                write_json(self.cache / "admin" / self.scope / f"index_{stock.code}.json", {"records": records, "windows": windows,
                           "query_start": str(self.start), "query_end": str(self.end), "earliest_observed": min((r["rcept_dt"] for r in records), default=None),
                           "unsupported_before": str(self.start), "historical_start_independently_verified": self.history_verified(),
                           "identity_verified": verified})
                row["disclosure_index"] = "COMPLETE" if verified else "CANDIDATE_ONLY"
                if verified:
                    for item in records:
                        description = describe(item["report_nm"])
                        disclosures.append({"stock_code": stock.code, "corp_code": corp_code, "document_name": item["report_nm"],
                                            "publication_date": item["rcept_dt"], "receipt_no": item["rcept_no"],
                                            "document_type": description[0] if description else "other_or_nonperiodic",
                                            "correction_type": description[2] if description else "", "filer": item.get("flr_nm", ""),
                                            "source_url": receipt_url(item["rcept_no"])})
                admin_documents = []
                for selection in select_reports(records, self.end, listing_complete=True):
                    if not selection.record:
                        status = "NOT_FILED_ASOF" if selection.status == "NOT_FILED_IN_SEARCHED_RANGE" and self.history_verified() and verified else selection.status
                        if not verified:
                            status = "IDENTITY_UNVERIFIED"
                        row[selection.kind] = status
                        missing.append({"stock_code": stock.code, "required_document": selection.kind, "missing_reason": status,
                                        "attempted_sources": "OpenDART list.json; all requested years/pages"})
                        continue
                    item, metadata = selection.record, describe(selection.record["report_nm"])
                    entry = {"stock_code": stock.code, "filename": "", "document_name": item["report_nm"], "publication_date": item["rcept_dt"],
                             "receipt_no": item["rcept_no"], "source_url": receipt_url(item["rcept_no"]), "sha256": "", "is_correction": bool(metadata[2]),
                             "corp_code": corp_code if verified else "", "reporting_period": selection.period, "document_type": selection.kind,
                             "correction_type": metadata[2], "pit_status": "PIT_REVIEW_REQUIRED", "download_status": "FETCH_FAILED", "file_size": 0}
                    try:
                        raw, documents, archive_record = downloader.obtain(item["rcept_no"])
                        entry.update(sha256=archive_record["sha256"], file_size=archive_record["file_size"], download_status="DOWNLOADED_QUARANTINED")
                        pit, reason = validate_document(selection, archive_record, documents, identity, records, self.reviews)
                        entry["pit_status"] = pit
                        try:
                            readable = readable_html(documents)
                            atomic_write(self.cache / "readable" / f"{item['rcept_no']}.html", readable)
                        except IntegrityError:
                            pit, reason = "PIT_REVIEW_REQUIRED", "CONVERSION_FAILED"
                            entry["pit_status"] = pit
                            readable = None
                        row[selection.kind] = pit
                        if pit == "VERIFIED_WITH_REVIEW_EVIDENCE" and readable is not None:
                            entry["filename"] = f"raw/{item['rcept_no']}.zip"
                            entry["download_status"] = "VERIFIED"
                            entry["readable_sha256"] = digest(readable)
                            atomic_write(batch / entry["filename"], raw.read_bytes())
                            atomic_write(batch / "readable" / f"{item['rcept_no']}.html", readable)
                        else:
                            missing.append({"stock_code": stock.code, "required_document": selection.kind, "missing_reason": reason,
                                            "attempted_sources": "OpenDART document.xml; official record comparison required"})
                    except DailyLimit:
                        if verified:
                            manifest.append(entry)
                        raise
                    except CredentialError:
                        if verified:
                            manifest.append(entry)
                        raise
                    except CollectorError as error:
                        self.failure_event(error, "document.xml")
                        row[selection.kind] = error.code
                        missing.append({"stock_code": stock.code, "required_document": selection.kind, "missing_reason": error.code,
                                        "attempted_sources": "OpenDART document.xml"})
                    # Even provisional title metadata is held out when company
                    # identity is unresolved: record only generic exceptions.
                    if verified:
                        manifest.append(entry)
                    admin_documents.append(entry)
                    write_json(self.cache / "admin" / self.scope / f"documents_{stock.code}.json", admin_documents)
                successful = all(row[k] == "VERIFIED_WITH_REVIEW_EVIDENCE" for k in ("annual", "interim"))
                row["pit"] = "VERIFIED_WITH_REVIEW_EVIDENCE" if successful else "PIT_REVIEW_REQUIRED"
                relevant = admin_documents
                row["integrity"] = "VERIFIED" if len(relevant) == 2 and all(e.get("sha256") for e in relevant) else "NOT_FULLY_VERIFIED"
                if any(row[k] in ("FETCH_FAILED", "INTEGRITY_FAILED", "FAILED") for k in ("annual", "interim")):
                    row.update(status="FAILED", reason="DOCUMENT_FETCH_OR_VALIDATION_FAILED")
                elif successful and row["disclosure_index"] == "COMPLETE" and self.history_verified():
                    row.update(status="READY", reason="")
                elif not verified:
                    row.update(status="REVIEW_REQUIRED", reason="HISTORICAL_IDENTITY_UNVERIFIED")
                elif any(row[k] in ("NOT_FILED_ASOF", "NOT_FILED_IN_SEARCHED_RANGE") for k in ("annual", "interim")):
                    row.update(status="MISSING", reason="REQUIRED_REPORT_NOT_AVAILABLE_OR_HISTORY_UNVERIFIED")
                else:
                    row.update(status="REVIEW_REQUIRED", reason="HISTORY_SCOPE_UNVERIFIED" if successful else "IDENTITY_OR_PIT_UNVERIFIED")
            except (DailyLimit, CredentialError) as error:
                self.failure_event(error, "collection")
                halted, fatal_code = True, error.code
                row.update(status="FAILED", reason=error.code)
                missing.append({"stock_code": stock.code, "required_document": "remaining", "missing_reason": error.code, "attempted_sources": "OpenDART"})
            except CollectorError as error:
                self.failure_event(error, "list.json")
                row.update(status="FAILED", reason=error.code, disclosure_index="FETCH_FAILED")
                missing.append({"stock_code": stock.code, "required_document": "disclosure_index", "missing_reason": error.code, "attempted_sources": "OpenDART list.json"})
            finally:
                row["approval_fingerprint"] = self.review_fingerprint
                self.state.put("coverage", f"{self.scope}:{stock.code}", row)
                coverage.append(row)
                self.event("stock_checkpoint", stock_code=stock.code, status=row["status"], reason=row["reason"])
                self.export(batch, selected, manifest, disclosures, missing, identity_rows, coverage, names)
        if halted or any(r["status"] == "FAILED" for r in coverage):
            return batch, 2
        return batch, 0

    def export(self, batch, selected, manifest, disclosures, missing, identities, coverage, names):
        write_json(batch / "approval_scope.json", {"review_fingerprint": self.review_fingerprint})
        write_csv(batch / "universe_asof.csv", UNIVERSE, universe_projection(selected, self.asof, names))
        write_csv(batch / "manifest.csv", MANIFEST, manifest)
        write_csv(batch / "disclosure_index.csv", DISCLOSURES, disclosures)
        write_csv(batch / "missing.csv", MISSING, missing)
        write_csv(batch / "identity_review.csv", IDENTITY, identities)
        by_code = {row["stock_code"]: row for row in coverage}
        write_csv(batch / "coverage.csv", COVERAGE, [by_code.get(s.code, self.blank(s)) for s in selected])
        write_csv(self.output / "coverage.csv", COVERAGE, self.all_coverage())
        counts = Counter(row["status"] for row in coverage)
        actual = len({row["receipt_no"] for row in manifest if row.get("sha256")})
        # Include quarantined originals in the audit count, not the evaluation manifest.
        selected_numbers = []
        for stock in selected:
            audit = self.cache / "admin" / self.scope / f"index_{stock.code}.json"
            if audit.exists():
                records = json.loads(audit.read_text())["records"]
                selected_numbers.extend(s.record["rcept_no"] for s in select_reports(records, self.end, listing_complete=True) if s.record)
        actual = 0
        for number in set(selected_numbers):
            known = self.state.get("documents", number)
            path = self.cache / "raw" / f"{number}.zip"
            if known and path.exists() and digest(path.read_bytes()) == known["sha256"]:
                actual += 1
        summary = (f"# Collection status\n\nAs of: {self.asof}; information cutoff: {cutoff(self.asof).isoformat()}.\n\n"
                   f"Selected stocks: {len(selected)}; processed checkpoints: {len(coverage)}.\n"
                   f"Downloaded originals (including quarantined): {actual}; approved evaluation originals: {sum(bool(r['filename']) for r in manifest)}.\n"
                   f"Statuses: {canonical(dict(counts))}.\n\n"
                   f"Search range: {self.start} through {self.end}, inclusive. Earlier periods are outside the API search scope; "
                   f"earliest available date independently verified: {self.history_verified()}.\n\n"
                   "Only hash-bound official-record review and integrity-checked originals can enter raw/ and readable/. "
                   "Unresolved identities and current corporate names/remarks remain in administrator cache. "
                   "A zero exit code is execution success, not a claim of complete collection or PIT approval. "
                   "Inspect coverage.csv and missing.csv. Independent Claude Code review has not been performed.\n")
        atomic_write(batch / "collection_report.md", summary.encode())

    def blocked(self, selected, code):
        batch = self.output / f"batch_{selected[0].order:03d}_{selected[-1].order:03d}"
        coverage = []
        for stock in selected:
            row = self.blank(stock)
            row.update(status="FAILED", reason=code)
            self.state.put("coverage", f"{self.scope}:{stock.code}", row)
            coverage.append(row)
        missing = [{"stock_code": s.code, "required_document": "all", "missing_reason": code, "attempted_sources": "credential preflight; no API call made"} for s in selected]
        self.export(batch, selected, [], [], missing, [], coverage, {})
        self.event("run_blocked", code=code, selected=len(selected))
        return batch

    def verify(self):
        failures, checked = [], 0
        expected = dict(self.state.items("documents"))
        numbers = set(expected) | {p.stem for p in (self.cache / "raw").glob("*.zip")}
        for number in sorted(numbers):
            path = self.cache / "raw" / f"{number}.zip"
            known = expected.get(number)
            try:
                if not path.exists() or not known or digest(path.read_bytes()) != known["sha256"] or len(path.read_bytes()) != known["file_size"]:
                    raise IntegrityError("Saved original checksum mismatch")
                inspect_archive(path.read_bytes())
                checked += 1
            except CollectorError:
                failures.append(number)
        batches = []
        for batch in sorted(self.output.glob("batch_*")):
            if not batch.is_dir() or not (batch / "manifest.csv").exists():
                continue
            import csv
            with (batch / "manifest.csv").open(encoding="utf-8-sig", newline="") as stream:
                rows = list(csv.DictReader(stream))
                batches.append((batch, rows))
                for row in rows:
                    if not row["filename"]:
                        continue
                    path = batch / "raw" / f"{row['receipt_no']}.zip"
                    readable = batch / "readable" / f"{row['receipt_no']}.html"
                    if (not path.exists() or digest(path.read_bytes()) != row["sha256"] or not readable.exists()
                            or digest(readable.read_bytes()) != row["readable_sha256"]):
                        failures.append(row["receipt_no"])
        failed = set(failures)
        for batch, manifest in batches:
            affected = {r["stock_code"] for r in manifest if r["receipt_no"] in failed}
            import csv
            with (batch / "coverage.csv").open(encoding="utf-8-sig", newline="") as stream:
                existing_codes = {r["stock_code"] for r in csv.DictReader(stream)}
            for code in existing_codes:
                path = self.cache / "admin" / self.scope / f"documents_{code}.json"
                if path.exists() and any(r["receipt_no"] in failed for r in json.loads(path.read_text())):
                    affected.add(code)
            if not affected:
                continue
            def read(name):
                with (batch / name).open(encoding="utf-8-sig", newline="") as stream:
                    return list(csv.DictReader(stream))
            coverage, missing = read("coverage.csv"), read("missing.csv")
            for row in manifest:
                if row["receipt_no"] in failed:
                    row.update(pit_status="FAILED", download_status="VERIFY_FAILED", filename="")
                    missing.append({"stock_code": row["stock_code"], "required_document": row["document_type"],
                                    "missing_reason": "STORED_ARTIFACT_INTEGRITY_FAILED", "attempted_sources": "offline hash and XML revalidation"})
            for row in coverage:
                if row["stock_code"] in affected:
                    row.update(status="FAILED", pit="FAILED", integrity="FAILED", reason="STORED_ARTIFACT_INTEGRITY_FAILED")
                    self.state.put("coverage", f"{self.scope}:{row['stock_code']}", row)
                    missing.append({"stock_code": row["stock_code"], "required_document": "stored_original_or_readable",
                                    "missing_reason": "STORED_ARTIFACT_INTEGRITY_FAILED", "attempted_sources": "offline hash and XML revalidation"})
            selected = [s for s in self.stocks if s.code in {r["stock_code"] for r in coverage}]
            names = {s.code: self.reviews.identity(s.code)["historical_name"] for s in selected if self.reviews.identity(s.code)}
            self.export(batch, selected, manifest, read("disclosure_index.csv"), missing, read("identity_review.csv"), coverage, names)
        result = {"verified_originals": checked, "failed_receipts": sorted(set(failures)), "zero_files_is_not_collection_validation": checked == 0}
        write_json(self.root / "logs" / "verify_result.json", result)
        return result
