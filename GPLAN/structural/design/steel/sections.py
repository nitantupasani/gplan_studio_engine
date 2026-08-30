"""IS 808 / SP 6(1) rolled section database.

`data/sections_is808.yaml` is transcribed handbook data, not computed geometry:
every record carries `verify: "print"` and the caller is expected to say so in
the report. The table is validated on import (a malformed or incomplete record
raises ValueError naming the designation) so a bad transcription fails loudly
at load time instead of silently sizing a member.

Units follow the package rule: the stored table is handbook cm/cm2/cm4/cm3, and
the `*_mm*` helpers on SteelSection convert to the N/mm/MPa regime the IS 800
clause layer works in. Nothing here is in feet.

Plastic moduli are estimated as 1.12 x Zex wherever `zp_computed` is true (SP
6(1) tabulates no Zp); the factor sits below the true shape factor of a rolled
I-section, so a capacity taken from it is on the safe side. Angle struts must
use `rvv_cm`, the minor principal radius, not `ry_cm`.
"""

from __future__ import annotations

import difflib
from typing import Any, Dict, List, NamedTuple, Optional, Tuple

from ...data._loader import load_yaml, require_keys

TABLE_NAME = "sections_is808"

# Handbook columns every record must carry. Optional extras (rvv_cm, cyy_cm)
# are absent from the sections that have no use for them.
REQUIRED_FIELDS = (
    "mass_kg_m",
    "h_mm",
    "bf_mm",
    "tf_mm",
    "tw_mm",
    "a_cm2",
    "ixx_cm4",
    "iyy_cm4",
    "zex_cm3",
    "zey_cm3",
    "zpx_cm3",
    "rx_cm",
    "ry_cm",
)

# Fields `lightest_section` may be asked to satisfy.
CRITERIA = (
    "a_cm2",
    "ixx_cm4",
    "iyy_cm4",
    "mass_kg_m",
    "rx_cm",
    "ry_cm",
    "zex_cm3",
    "zey_cm3",
    "zpx_cm3",
)


class SteelSection(NamedTuple):
    """One handbook row. Immutable; the loader owns the only instances."""

    designation: str
    family: str
    mass_kg_m: float
    h_mm: float
    bf_mm: float
    tf_mm: float
    tw_mm: float
    a_cm2: float
    ixx_cm4: float
    iyy_cm4: float
    zex_cm3: float
    zey_cm3: float
    zpx_cm3: float
    rx_cm: float
    ry_cm: float
    zp_computed: bool = True
    rvv_cm: Optional[float] = None
    cyy_cm: Optional[float] = None
    verify: str = ""

    # -- conversions into the mm/N/MPa regime the code layer uses ----------

    def a_mm2(self) -> float:
        return self.a_cm2 * 100.0

    def ixx_mm4(self) -> float:
        return self.ixx_cm4 * 1.0e4

    def iyy_mm4(self) -> float:
        return self.iyy_cm4 * 1.0e4

    def zex_mm3(self) -> float:
        return self.zex_cm3 * 1.0e3

    def zey_mm3(self) -> float:
        return self.zey_cm3 * 1.0e3

    def zpx_mm3(self) -> float:
        return self.zpx_cm3 * 1.0e3

    def rx_mm(self) -> float:
        return self.rx_cm * 10.0

    def ry_mm(self) -> float:
        return self.ry_cm * 10.0

    def rvv_mm(self) -> Optional[float]:
        """Minor principal radius in mm, or None for a section without one."""
        return None if self.rvv_cm is None else self.rvv_cm * 10.0

    def web_area_mm2(self) -> float:
        """Shear area of an I-section or channel per IS 800 Cl 8.4.1.1, h x tw."""
        return self.h_mm * self.tw_mm


def _family_of(designation: str) -> str:
    token = designation.strip().split()[0] if designation.strip() else ""
    if not token.isalpha():
        raise ValueError(
            TABLE_NAME + ": designation " + repr(designation) + " does not start with an alphabetic family token"
        )
    return token.upper()


def _number(record: Dict[str, Any], key: str, designation: str) -> float:
    value = record.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(
            TABLE_NAME + ": " + designation + " field " + key + " must be a number, got " + repr(value)
        )
    return float(value)


def _optional_number(record: Dict[str, Any], key: str, designation: str) -> Optional[float]:
    if record.get(key) is None:
        return None
    return _number(record, key, designation)


def _build(designation: str, record: Any) -> SteelSection:
    if not isinstance(record, dict):
        raise ValueError(TABLE_NAME + ": " + designation + " must be a mapping, got " + type(record).__name__)
    require_keys(record, REQUIRED_FIELDS, TABLE_NAME + "[" + designation + "]")
    return SteelSection(
        designation=designation,
        family=_family_of(designation),
        mass_kg_m=_number(record, "mass_kg_m", designation),
        h_mm=_number(record, "h_mm", designation),
        bf_mm=_number(record, "bf_mm", designation),
        tf_mm=_number(record, "tf_mm", designation),
        tw_mm=_number(record, "tw_mm", designation),
        a_cm2=_number(record, "a_cm2", designation),
        ixx_cm4=_number(record, "ixx_cm4", designation),
        iyy_cm4=_number(record, "iyy_cm4", designation),
        zex_cm3=_number(record, "zex_cm3", designation),
        zey_cm3=_number(record, "zey_cm3", designation),
        zpx_cm3=_number(record, "zpx_cm3", designation),
        rx_cm=_number(record, "rx_cm", designation),
        ry_cm=_number(record, "ry_cm", designation),
        zp_computed=bool(record.get("zp_computed", False)),
        rvv_cm=_optional_number(record, "rvv_cm", designation),
        cyy_cm=_optional_number(record, "cyy_cm", designation),
        verify=str(record.get("verify", "")),
    )


def _load_table() -> Tuple[Dict[str, SteelSection], Dict[str, Any]]:
    table = load_yaml(TABLE_NAME)
    require_keys(table, ("source", "edition", "sections"), TABLE_NAME)
    raw = table["sections"]
    if not isinstance(raw, dict) or not raw:
        raise ValueError(TABLE_NAME + ": `sections` must be a non-empty mapping keyed by designation")
    built = {}  # type: Dict[str, SteelSection]
    for designation in sorted(str(key) for key in raw):
        built[designation] = _build(designation, raw[designation])
    return built, table


# Validated once, at import: a broken table must not reach a design loop.
_SECTIONS, _TABLE = _load_table()

# Designations sorted by mass then name, so every iteration order in this
# module is the design order (lightest first) and is reproducible.
_BY_MASS = tuple(sorted(_SECTIONS.values(), key=lambda s: (s.mass_kg_m, s.designation)))


def _clean(designation: str) -> str:
    """Collapse whitespace. Case is left alone: 'ISA 75x75x8' keeps its x."""
    return " ".join(str(designation).split())


def _fold(designation: str) -> str:
    """Lookup key: case and spacing folded away, so 'ismb300' finds 'ISMB 300'."""
    return _clean(designation).upper().replace(" ", "")


def _build_index() -> Tuple[Dict[str, str], Dict[str, str]]:
    """(folded spelling -> designation, upper designation -> designation).

    Two entries that fold together would make a lookup ambiguous, so that is an
    import-time ValueError rather than a silent first-wins.
    """
    folded = {}  # type: Dict[str, str]
    upper = {}  # type: Dict[str, str]
    for name in sorted(_SECTIONS):
        key = _fold(name)
        if key in folded:
            raise ValueError(
                TABLE_NAME + ": " + name + " and " + folded[key] + " fold to the same lookup key"
            )
        folded[key] = name
        upper.setdefault(name.upper(), name)
    return folded, upper


_FOLDED, _UPPER = _build_index()


def get_section(designation: str) -> SteelSection:
    """The handbook row for `designation`, e.g. "ISMB 300".

    Spelling is folded for case and spacing only; a fold never lands on a
    different section. An unknown designation raises KeyError naming the
    closest entries (or the whole family when the family token is known) so a
    typo does not read as an empty database.
    """
    canonical = _FOLDED.get(_fold(designation))
    if canonical is not None:
        return _SECTIONS[canonical]

    cleaned = _clean(designation)
    close = [_UPPER[m] for m in difflib.get_close_matches(cleaned.upper(), sorted(_UPPER), n=5, cutoff=0.5)]
    family = cleaned.split()[0].upper() if cleaned.split() else ""
    same_family = [s.designation for s in _BY_MASS if s.family == family]
    suggestions = close or same_family
    if suggestions:
        hint = "did you mean: " + ", ".join(sorted(set(suggestions))[:8])
    else:
        hint = "known families: " + ", ".join(families())
    raise KeyError(
        "unknown steel section " + repr(str(designation)) + " in " + TABLE_NAME + "; " + hint
    )


def sections(family: Optional[str] = None) -> List[SteelSection]:
    """Every section, or one family, ascending by mass then designation."""
    if family is None:
        return list(_BY_MASS)
    wanted = str(family).strip().upper()
    return [s for s in _BY_MASS if s.family == wanted]


def families() -> List[str]:
    """Family tokens present in the table, sorted."""
    return sorted(set(s.family for s in _BY_MASS))


def lightest_section(family: str, criterion: str, min_value: float) -> Optional[SteelSection]:
    """Lightest section of `family` whose `criterion` reaches `min_value`.

    Returns None when the family cannot meet the demand: an exhausted database
    is a normal design outcome, and the caller discloses it (a built-up or
    plated section is outside this table). Raises ValueError for an unknown
    family or a criterion that is not a numeric column.
    """
    wanted = str(family).strip().upper()
    pool = [s for s in _BY_MASS if s.family == wanted]
    if not pool:
        raise ValueError(
            "unknown section family " + repr(str(family)) + "; known families: " + ", ".join(families())
        )
    if criterion not in CRITERIA:
        raise ValueError(
            "unknown section criterion " + repr(str(criterion)) + "; choose one of " + ", ".join(CRITERIA)
        )
    target = float(min_value)
    for section in pool:  # already ascending by mass
        if getattr(section, criterion) >= target:
            return section
    return None


def table_provenance() -> Dict[str, Any]:
    """Bibliography row for the report: where this database came from."""
    return {
        "table": TABLE_NAME,
        "source": _TABLE.get("source", ""),
        "edition": _TABLE.get("edition", ""),
        "count": len(_SECTIONS),
        "zp_estimate_factor": _TABLE.get("zp_estimate_factor"),
        "verify": "print",
    }


__all__ = [
    "CRITERIA",
    "REQUIRED_FIELDS",
    "TABLE_NAME",
    "SteelSection",
    "families",
    "get_section",
    "lightest_section",
    "sections",
    "table_provenance",
]
