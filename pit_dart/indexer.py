from __future__ import annotations

import calendar
import re
from datetime import date, timedelta

from .core import CollectorError, IntegrityError, canonical, digest


def yearly_windows(start: date, end: date):
    while start <= end:
        stop = min(date(start.year, 12, 31), end)
        yield start, stop
        start = stop + timedelta(days=1)


def validate_records(records, corp_code, start, end):
    seen = set()
    for item in records:
        number = str(item.get("rcept_no", ""))
        if not re.fullmatch(r"\d{14}", number) or number in seen:
            raise IntegrityError("Invalid/duplicate receipt number in disclosure listing")
        try:
            publication = date.fromisoformat(item["rcept_dt"][:4] + "-" + item["rcept_dt"][4:6] + "-" + item["rcept_dt"][6:])
        except (KeyError, TypeError, ValueError):
            raise IntegrityError("Invalid publication date in disclosure listing") from None
        if not start <= publication <= end or number[:8] != publication.strftime("%Y%m%d"):
            raise IntegrityError("Disclosure outside requested window or receipt date mismatch")
        if item.get("corp_code") != corp_code or not isinstance(item.get("report_nm"), str):
            raise IntegrityError("Disclosure corporation mismatch or missing title")
        seen.add(number)


class Indexer:
    def __init__(self, client, state, resume=True):
        self.client, self.state, self.resume = client, state, resume

    def window(self, corp_code, start, end):
        key = f"{corp_code}:{start}:{end}:N:100:v1"
        cached = self.state.get("windows", key) if self.resume else None
        if cached and cached.get("complete"):
            records = cached.get("records", [])
            if digest(canonical(records).encode()) == cached.get("sha256") and len(records) == cached.get("total_count"):
                validate_records(records, corp_code, start, end)
                return records, {k: v for k, v in cached.items() if k != "records"}
        records, expected_count, expected_pages = [], None, None
        page = 1
        while True:
            payload = self.client.list(corp_code=corp_code, bgn_de=start.strftime("%Y%m%d"), end_de=end.strftime("%Y%m%d"),
                                       last_reprt_at="N", page_count=100, page_no=page, sort="date", sort_mth="asc")
            if payload.get("status") == "013":
                if page != 1 or payload.get("list") or str(payload.get("total_count", 0)) != "0":
                    raise IntegrityError("No-data response contradicts pagination")
                expected_count, expected_pages = 0, 0
                break
            try:
                count, pages = int(payload["total_count"]), int(payload["total_page"])
                items = payload["list"]
                if int(payload["page_no"]) != page or int(payload["page_count"]) != 100:
                    raise ValueError
                if count <= 0 or pages != (count + 99) // 100 or pages > 10000:
                    raise ValueError
                if not isinstance(items, list) or len(items) != min(100, count - (page - 1) * 100):
                    raise ValueError
            except (KeyError, TypeError, ValueError):
                raise IntegrityError("Disclosure pagination metadata/count inconsistent") from None
            if expected_count is not None and (count, pages) != (expected_count, expected_pages):
                raise IntegrityError("Disclosure totals changed while paging; retry the whole window")
            expected_count, expected_pages = count, pages
            records.extend(items)
            if page == pages:
                break
            page += 1
        validate_records(records, corp_code, start, end)
        if len(records) != expected_count:
            raise IntegrityError("Disclosure count mismatch")
        metadata = {"start": str(start), "end": str(end), "total_count": expected_count,
                    "total_page": expected_pages, "complete": True, "sha256": digest(canonical(records).encode())}
        self.state.put("windows", key, {**metadata, "records": records})
        return records, metadata

    def collect(self, corp_code, start, end):
        all_records, coverage = [], []
        for first, last in yearly_windows(start, end):
            # One bounded whole-window retry handles changed pagination/duplicate boundaries.
            try:
                records, meta = self.window(corp_code, first, last)
            except IntegrityError:
                original = self.resume
                self.resume = False
                try:
                    records, meta = self.window(corp_code, first, last)
                finally:
                    self.resume = original
            all_records.extend(records)
            coverage.append(meta)
        validate_records(all_records, corp_code, start, end)
        return sorted(all_records, key=lambda item: item["rcept_no"]), coverage
