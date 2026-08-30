"""Load combinations: IS 456 Cl 18.2.3 Table 18 (ULS), service (SLS) and the
masonry permissible-stress set (WS).

`generate(cases_present)` expands purely from the case-name roster it is
handed, so the lateral cases the seismic and wind builders add ("EQX+" ...
"WY-") compose without this module importing either builder.  Expansion order
is fixed: the gravity combination first, then one block per lateral case in
`LATERAL_CASE_ROSTER` order, so ids are stable for a given roster.

Rules carried from the spec (section 11):
    ULS   UL01 1.5DL + 1.5LL; per lateral L: 1.2(DL+LL+L), 1.5(DL+L),
          0.9DL + 1.5L.
    SLS   SL01 DL + LL; per lateral L: DL + L, DL + 0.8LL + 0.8L.
    WS    WS01 DL + LL; per lateral L: DL + LL + L with
          allowable_stress_factor 1.25 (IS 1905 practice; the factor rides on
          the Combo, the masonry design applies it).
LLR rides with the LL factors wherever LL appears.  Wind and seismic are never
combined: every combination carries at most one lateral case.
"""

from __future__ import annotations

from typing import Dict, Iterable, List

from . import CASE_DL, CASE_LL, CASE_LLR, LATERAL_CASE_ROSTER, Combo

_ULS_SOURCE = "IS 456:2000 Cl 18.2.3, Table 18 (partial safety factors for loads, limit state of collapse)"
_SLS_SOURCE = "IS 456:2000 Cl 18.2.3, Table 18 (limit state of serviceability)"
_WS_SOURCE = "IS 1905:1987 permissible stress practice; 25 percent overstress under wind or earthquake"

#: Overstress multiplier attached to WS combinations that include a lateral case.
WS_ALLOWABLE_STRESS_FACTOR = 1.25


def _name(factors: Dict[str, float]) -> str:
    """Deterministic display name: DL, LL, LLR then the lateral, joined by +."""
    order = [CASE_DL, CASE_LL, CASE_LLR] + list(LATERAL_CASE_ROSTER)
    parts = []
    for case in order:
        if case in factors:
            factor = factors[case]
            text = ("%g" % factor) if factor != 1.0 else ""
            parts.append(text + case)
    return "+".join(parts)


def _combo(prefix: str, index: int, kind: str, factors: Dict[str, float], source: str, asf: float = 1.0) -> Combo:
    return Combo(
        id="%s%02d" % (prefix, index),
        name=_name(factors),
        kind=kind,
        factors=tuple(sorted(factors.items())),
        source=source,
        allowable_stress_factor=asf,
    )


def _gravity(present: Iterable[str], dl: float, ll: float) -> Dict[str, float]:
    """DL/LL/LLR factors filtered to the cases actually present."""
    roster = set(present)
    factors = {}
    if CASE_DL in roster and dl != 0.0:
        factors[CASE_DL] = dl
    if ll != 0.0:
        if CASE_LL in roster:
            factors[CASE_LL] = ll
        if CASE_LLR in roster:
            factors[CASE_LLR] = ll  # LLR rides with the LL factors (spec 11)
    return factors


def laterals_present(cases_present: Iterable[str]) -> List[str]:
    """The lateral cases of the roster that are present, in roster order."""
    roster = set(str(c) for c in cases_present)
    return [case for case in LATERAL_CASE_ROSTER if case in roster]


def generate(cases_present: Iterable[str], code: str = "IS456") -> List[Combo]:
    """Expand the deterministic combination set for the case-name roster.

    `cases_present` is any iterable of canonical case names ("DL", "LL",
    "LLR", "EQX+", ...).  Only cases present are expanded: a gravity-only
    roster yields exactly one combination per kind.  `code` reserves the EC
    analogue slot; only "IS456" is implemented.
    """
    if str(code) != "IS456":
        raise ValueError("unsupported combination code: " + repr(str(code)))
    roster = sorted(set(str(c) for c in cases_present))
    laterals = laterals_present(roster)

    uls = []  # type: List[Combo]
    sls = []  # type: List[Combo]
    ws = []  # type: List[Combo]

    # gravity block
    factors = _gravity(roster, 1.5, 1.5)
    if factors:
        uls.append(_combo("UL", 1, "ULS", factors, _ULS_SOURCE))
    factors = _gravity(roster, 1.0, 1.0)
    if factors:
        sls.append(_combo("SL", 1, "SLS", factors, _SLS_SOURCE))
        ws.append(_combo("WS", 1, "WS", dict(factors), _WS_SOURCE))

    # one block per lateral case; wind and seismic never share a combination
    for lateral in laterals:
        factors = _gravity(roster, 1.2, 1.2)
        factors[lateral] = 1.2
        uls.append(_combo("UL", len(uls) + 1, "ULS", factors, _ULS_SOURCE))
        factors = _gravity(roster, 1.5, 0.0)
        factors[lateral] = 1.5
        uls.append(_combo("UL", len(uls) + 1, "ULS", factors, _ULS_SOURCE))
        factors = _gravity(roster, 0.9, 0.0)
        factors[lateral] = 1.5
        uls.append(_combo("UL", len(uls) + 1, "ULS", factors, _ULS_SOURCE))

        factors = _gravity(roster, 1.0, 0.0)
        factors[lateral] = 1.0
        sls.append(_combo("SL", len(sls) + 1, "SLS", factors, _SLS_SOURCE))
        factors = _gravity(roster, 1.0, 0.8)
        factors[lateral] = 0.8
        sls.append(_combo("SL", len(sls) + 1, "SLS", factors, _SLS_SOURCE))

        factors = _gravity(roster, 1.0, 1.0)
        factors[lateral] = 1.0
        ws.append(_combo("WS", len(ws) + 1, "WS", factors, _WS_SOURCE, asf=WS_ALLOWABLE_STRESS_FACTOR))

    return uls + sls + ws
