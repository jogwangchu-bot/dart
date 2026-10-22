from datetime import date

import pytest
import requests
import responses

from pit_dart.client import BASE, DartClient
from pit_dart.core import CollectorError, CredentialError, DailyLimit, IntegrityError
from pit_dart.indexer import Indexer, yearly_windows
from pit_dart.state import State
from .helpers import ANNUAL, CORP, FakeClient, disclosure


def client():
    return DartClient("SYNTHETIC-KEY-NEVER-LIVE", sleep=lambda seconds: None, clock=lambda: 0)


@responses.activate
@pytest.mark.parametrize("status,error", [("020", DailyLimit), ("010", CredentialError), ("012", CredentialError), ("100", CollectorError)])
def test_api_error_status_not_treated_as_no_data(status, error):
    responses.get(BASE + "list.json", json={"status": status, "message": "server might reflect a secret"})
    with pytest.raises(error) as caught:
        client().list(end_de="20190917")
    assert "server might" not in str(caught.value)
    assert len(responses.calls) == 1


@responses.activate
def test_error_xml_is_not_a_document_zip():
    responses.get(BASE + "document.xml", body="<result><status>014</status><message>not found</message></result>")
    with pytest.raises(CollectorError):
        client().document("20190814000001")


@responses.activate
def test_timeout_retries_bounded_and_credential_not_in_error():
    responses.get(BASE + "list.json", body=requests.Timeout("SYNTHETIC-KEY-NEVER-LIVE"))
    with pytest.raises(CollectorError) as caught:
        client().list()
    assert "SYNTHETIC-KEY" not in str(caught.value)
    assert len(responses.calls) == 3


@responses.activate
def test_http_429_can_recover_without_disabling_tls():
    responses.get(BASE + "list.json", status=429, headers={"Retry-After": "0"})
    responses.get(BASE + "list.json", json={"status": "013"})
    assert client().list()["status"] == "013"
    assert len(responses.calls) == 2


@responses.activate
def test_redirect_is_not_followed_with_key():
    responses.get(BASE + "list.json", status=302, headers={"Location": "https://evil.invalid/"})
    with pytest.raises(CollectorError):
        client().list()
    assert len(responses.calls) == 1


def test_year_boundaries_are_contiguous_and_leap_year_safe():
    windows = list(yearly_windows(date(2016, 2, 29), date(2019, 9, 17)))
    assert windows[0] == (date(2016, 2, 29), date(2016, 12, 31))
    assert windows[-1] == (date(2019, 1, 1), date(2019, 9, 17))
    for previous, current in zip(windows, windows[1:]):
        assert (current[0] - previous[1]).days == 1


def test_all_pages_count_and_resume(tmp_path):
    records = [disclosure(f"20190329{i:06d}", "수시공시") for i in range(1, 206)]
    fake, state = FakeClient(records), State(tmp_path / "state.sqlite")
    index = Indexer(fake, state)
    found, windows = index.collect(CORP, date(2019, 1, 1), date(2019, 9, 17))
    assert len(found) == 205
    assert [r["page_no"] for r in fake.list_calls] == [1, 2, 3]
    assert all(r["last_reprt_at"] == "N" and r["page_count"] == 100 and r["end_de"] == "20190917" for r in fake.list_calls)
    index.collect(CORP, date(2019, 1, 1), date(2019, 9, 17))
    assert len(fake.list_calls) == 3
    state.close()


@pytest.mark.parametrize("mode", ["missing_page", "duplicate", "future", "wrong_corp", "count_changed"])
def test_broken_pagination_cannot_be_cached_complete(tmp_path, mode):
    records = [disclosure(f"20190329{i:06d}", "수시공시") for i in range(1, 102)]
    if mode == "duplicate":
        records[-1] = records[0]
    if mode == "wrong_corp":
        records[0] = {**records[0], "corp_code": "99999999"}
    fake = FakeClient(records)
    original = fake.list
    def modified(**params):
        reply = original(**params)
        if params["page_no"] == 2 and mode == "missing_page":
            return {"status": "013"}
        if params["page_no"] == 2 and mode == "count_changed":
            reply["total_count"] = 102
        if mode == "future":
            reply["list"][0] = disclosure("20200320000001", "수시공시")
        return reply
    fake.list = modified
    state = State(tmp_path / "state.sqlite")
    with pytest.raises(IntegrityError):
        Indexer(fake, state).collect(CORP, date(2019, 1, 1), date(2019, 9, 17))
    assert state.get("windows", f"{CORP}:2019-01-01:2019-09-17:N:100:v1") is None
    state.close()


def test_no_data_and_fetch_failure_are_distinct(tmp_path):
    state = State(tmp_path / "state.sqlite")
    fake = FakeClient([])
    result, windows = Indexer(fake, state).collect(CORP, date(2019, 1, 1), date(2019, 9, 17))
    assert result == [] and windows[0]["complete"] is True
    def unavailable(**parameters):
        raise CollectorError("synthetic transport failure")
    fake.list = unavailable
    with pytest.raises(CollectorError):
        Indexer(fake, state, resume=False).collect(CORP, date(2019, 1, 1), date(2019, 9, 17))
    state.close()


@responses.activate
def test_maintenance_response_has_bounded_retry():
    responses.get(BASE + "list.json", json={"status": "800"})
    responses.get(BASE + "list.json", json={"status": "013"})
    assert client().list()["status"] == "013"
    assert len(responses.calls) == 2


def test_no_data_with_nonzero_count_is_rejected(tmp_path):
    fake = FakeClient([])
    fake.list = lambda **params: {"status": "013", "total_count": 5}
    state = State(tmp_path / "state.sqlite")
    with pytest.raises(IntegrityError):
        Indexer(fake, state).collect(CORP, date(2019, 1, 1), date(2019, 9, 17))
    state.close()
