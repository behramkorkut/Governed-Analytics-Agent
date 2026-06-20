"""Rules-based anti-fabrication check (no extra LLM call, fully deterministic).

The deterministic facts are handed to the model to phrase (see insights.py); this
is the audit on the other side -- it confirms that every *figure the model wrote*
actually traces back to the returned rows or the pre-computed insights. A number
in the prose that matches nothing in the data is flagged.

Deliberately conservative, to avoid crying wolf: it skips years and small counts
(which aren't data claims), accepts rounding, and tolerates both EN ("1,234.5")
and FR ("1 234,5") number formatting. It is an *advisory* signal surfaced in the
UI, not a hard gate.
"""

from __future__ import annotations

import re

from .insights import Insights

# Thousands separators we tolerate inside a number run: regular space plus the
# no-break (U+00A0) and narrow no-break (U+202F) spaces common in FR numbers.
# Built with chr() so the source stays pure ASCII (no confusable literals).
_THIN_SPACES = (chr(0xA0), chr(0x202F))
_NUMBER_RE = re.compile(r"-?\d[\d " + "".join(_THIN_SPACES) + r",.]*\d|\d")
_REL_TOL = 0.015
_ABS_TOL = 0.5


def _to_float(x: object) -> float | None:
    try:
        return float(x)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _candidates(token: str) -> list[float]:
    """Both plausible numeric readings of a token (EN vs FR conventions)."""
    t = token.strip().strip("%€$ ")
    for sp in (" ", *_THIN_SPACES):  # strip thousands separators
        t = t.replace(sp, "")
    out: set[float] = set()
    a = _to_float(t.replace(",", ""))  # comma = thousands, dot = decimal
    if a is not None:
        out.add(a)
    b = _to_float(t.replace(".", "").replace(",", "."))  # comma = decimal (FR)
    if b is not None:
        out.add(b)
    return list(out)


def _is_data_claim(token: str, value: float) -> bool:
    """Is this token a figure worth checking (vs a year or a small count)?"""
    if any(sym in token for sym in ("%", "€", "$")):
        return True
    if "." in token or "," in token:
        return True
    if 1900 <= value <= 2100:  # a year, not a measurement
        return False
    return abs(value) >= 100


def supported_values(rows: list[dict], insights: Insights | None) -> set[float]:
    """Every number the answer is allowed to cite: row cells + computed facts,
    plus rounded variants so a rounded restatement still matches."""
    vals: set[float] = set()
    for row in rows:
        for cell in row.values():
            f = _to_float(cell)
            if f is not None:
                vals.add(f)
    if insights is not None:
        if insights.total is not None:
            vals.add(insights.total)
        for s in insights.shares:
            vals.add(s["share_pct"])
            vals.add(s["value"])
        for end in (insights.top, insights.bottom):
            if end is not None:
                vals.add(end["value"])
        if insights.delta is not None:
            for key in ("abs", "pct", "latest_value", "previous_value"):
                f = _to_float(insights.delta.get(key))
                if f is not None:
                    vals.add(f)

    rounded: set[float] = set()
    for v in vals:
        rounded.update({round(v), round(v, 1), round(v, 2)})
    return vals | rounded


def _matches(value: float, supported: set[float]) -> bool:
    return any(abs(value - s) <= max(_ABS_TOL, _REL_TOL * abs(s)) for s in supported)


def check_answer(answer: str, rows: list[dict], insights: Insights | None) -> list[str]:
    """Return the figures in `answer` not backed by the data (empty == clean)."""
    supported = supported_values(rows, insights)
    flagged: list[str] = []
    for token in _NUMBER_RE.findall(answer):
        cands = _candidates(token)
        if not cands or not _is_data_claim(token, cands[0]):
            continue
        if not any(_matches(c, supported) for c in cands):
            flagged.append(token.strip())
    return flagged
