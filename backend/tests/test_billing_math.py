from datetime import date
from decimal import Decimal as D

import pytest
from fastapi import HTTPException

from app.services.billing import LineInput, compute, fiscal_year, is_interstate


def L(q, p, rate="18", disc="0"):
    return LineInput(description="x", quantity=D(q), unit_price=D(p), tax_rate=D(rate), line_discount_pct=D(disc))


def test_intrastate_split_sums_exactly():
    t = compute([L("1", "100.01", "18")], interstate=False)
    line = t.lines[0]
    assert line.taxable_value == D("100.01")
    assert line.cgst + line.sgst == D("18.00")  # 18.0018 -> 18.00
    assert line.igst == 0
    assert t.total == D("118.01")


def test_odd_paisa_split():
    t = compute([L("1", "0.50", "18")], interstate=False)  # tax 0.09
    assert (t.cgst_total, t.sgst_total) == (D("0.04"), D("0.05"))
    assert t.total == D("0.59")


def test_interstate_uses_igst():
    t = compute([L("2", "500", "18")], interstate=True)
    assert t.igst_total == D("180.00") and t.cgst_total == 0 and t.total == D("1180.00")


def test_line_and_document_discount_allocation():
    t = compute([L("1", "1000", "18", disc="10"), L("1", "500", "5")], interstate=False,
                document_discount=D("100"))
    # net 900 and 500 -> doc discount split 64.29 / 35.71
    a, b = t.lines
    assert a.discount_amount == D("100") + D("64.29")
    assert b.discount_amount == D("35.71")
    assert t.discount_total == D("200.00")
    assert t.taxable_total == D("1300.00")
    assert t.total == t.taxable_total + t.tax_total
    assert t.subtotal - t.discount_total == t.taxable_total


def test_round_to_rupee():
    t = compute([L("1", "99.99", "0")], interstate=False, round_to_rupee=True)
    assert t.total == D("100") and t.round_off == D("0.01")


def test_validation():
    with pytest.raises(HTTPException):
        compute([], interstate=False)
    with pytest.raises(HTTPException):
        compute([L("1", "10")], interstate=False, document_discount=D("11"))


def test_fiscal_year_and_state():
    assert fiscal_year(date(2026, 3, 31)) == "2025-26"
    assert fiscal_year(date(2026, 4, 1)) == "2026-27"
    assert is_interstate("33", "29") and not is_interstate("33", "33")
    assert not is_interstate(None, "29") and not is_interstate("33", None)
