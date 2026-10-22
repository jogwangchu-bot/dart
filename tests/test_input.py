import csv
from datetime import date

import pytest

from pit_dart.core import InputError, cutoff, read_universe, universe_projection, write_csv
from .helpers import workbook


def test_preserve_codes_and_input_order(tmp_path):
    source = workbook(tmp_path / "input.xlsx", [(1, "A", "000140"), (3, "B", 390), (7, "C", "005930")])
    stocks = read_universe(source, expected_count=3)
    assert [(s.order, s.code) for s in stocks] == [(1, "000140"), (3, "000390"), (7, "005930")]


@pytest.mark.parametrize("value", [None, True, 1.5, -1, 1000000, "123", "１２３４５６", "=1+1", "ABCDEF"])
def test_bad_stock_code_not_silently_skipped(tmp_path, value):
    with pytest.raises(InputError):
        read_universe(workbook(tmp_path / "bad.xlsx", [(1, "A", value)]))


@pytest.mark.parametrize("rows", [[(1, "A", "000001"), (2, "B", "000001")], [(2, "A", "000001"), (1, "B", "000002")], [(1.1, "A", "000001")]])
def test_duplicates_and_bad_order_fail_whole_input(tmp_path, rows):
    with pytest.raises(InputError):
        read_universe(workbook(tmp_path / "bad.xlsx", rows))


def test_count_mismatch_is_not_accepted(tmp_path):
    with pytest.raises(InputError):
        read_universe(workbook(tmp_path / "one.xlsx"), expected_count=390)


def test_future_admin_columns_do_not_enter_projection(tmp_path):
    rows = read_universe(workbook(tmp_path / "one.xlsx"))
    result = universe_projection(rows, date(2019, 9, 18))
    assert result == [{"order": 1, "stock_code": "000001", "asof": "2019-09-18", "historical_name": ""}]
    path = tmp_path / "universe_asof.csv"
    write_csv(path, list(result[0]), result)
    assert "2026" not in path.read_text(encoding="utf-8-sig")


def test_cutoff_is_previous_day_kst():
    assert cutoff(date(2019, 9, 18)).isoformat() == "2019-09-17T23:59:59+09:00"
