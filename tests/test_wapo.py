"""The wapo converter (the Washington Post's games service JSON)."""

import datetime as dt
import json

import pytest
from synthetic import WAPO_XD, as_bytes, wapo

from xdfetch import convert
from xdfetch.convert import wapo as converter
from xdfetch.xd import REBUS_KEYS

RAW = as_bytes(wapo())
SUNDAY = dt.date(2026, 10, 25)


def test_sniff_and_fixture():
    assert converter.sniff(RAW)
    assert convert.detect(RAW) == "wapo"
    fmt, p = convert.convert(RAW, convert.Context("wap", SUNDAY, "wap-2026-10-25.json"))
    assert fmt == "wapo"
    assert p.tricky == []
    assert p.check() == []
    assert p.to_xd() == WAPO_XD


def test_date_mismatch_is_tricky():
    _, p = convert.convert(RAW, convert.Context("wap", dt.date(2026, 11, 1), "f"))
    assert p.tricky == ["puzzleId is dated 2026/10/25, file dated 2026-11-01"]


def test_bad_width():
    d = json.loads(RAW)
    d["width"] = 4
    with pytest.raises(convert.ConvertError):
        converter.convert(json.dumps(d).encode(), convert.Context("wap", SUNDAY, "f"))


def test_markup_in_a_clue_and_a_missing_number():
    d = wapo()
    d["words"][0]["clue"] = "<i>Male</i> duck"
    del d["cells"][0]["number"]  # numbered from the grid instead
    _, p = convert.convert(as_bytes(d), convert.Context("wap", SUNDAY, "f"))
    assert p.clues[0].text == "{/Male/} duck"
    assert p.clues[0].number == 1
    assert p.tricky == []


def doubled(values: list[str]) -> bytes:
    """A payload whose first cells each hold one of `values` as a rebus, one row of five."""
    cells = [{"answer": v, "number": i + 1} for i, v in enumerate(values)]
    while len(cells) % 5:
        cells.append({"type": "locked"})
    words = [
        {"clue": f"clue {r}", "direction": "across", "indexes": list(range(r * 5, min(r * 5 + 5, len(values))))}
        for r in range(len(cells) // 5)
    ]
    d = {
        "puzzleId": "sunday/2026/11/01",
        "title": "Part Two",
        "creator": "Ann Setter",
        "copyright": "© November 1, 2026, The Washington Post",
        "description": "",
        "width": 5,
        "cells": cells,
        "words": words,
    }
    return json.dumps(d).encode()


def test_rebus_keys_beyond_the_digits():
    # a doubled-letter theme can have more distinct rebus values than there are digits;
    # the keys continue in puz2xd's order
    values = [c * 2 for c in "CALFIPOVRYNSE"] + ["ES", "TH"] + [c * 3 for c in "ABCDE"]
    _, p = convert.convert(doubled(values), convert.Context("wap", dt.date(2026, 11, 1), "f"))
    keys = REBUS_KEYS[: len(values)]
    assert p.headers["Rebus"] == " ".join(f"{k}={v}" for k, v in zip(keys, values, strict=True))
    assert "".join(p.grid) == keys  # 20 values fill four rows of five exactly
    assert p.check() == []
    assert keys[9:13] == "0*?@"
    assert keys[17:19] == "♠♥"


def test_rebus_keys_run_out():
    values = [f"X{i}" for i in range(len(REBUS_KEYS) + 1)]
    with pytest.raises(convert.ConvertError, match="more rebus values than keys"):
        converter.convert(doubled(values), convert.Context("wap", dt.date(2026, 11, 1), "f"))
