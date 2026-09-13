"""IS 4326:1993 clause callables for earthquake resistant masonry.

Same shape as `is1905`: one clause, one pure `@clause` function, plain values or
small NamedTuples out, no model writes and no (value, ref) tuples. Every number
comes from `data/is4326_tables.yaml`, which also carries the seismic category
map, and is validated for shape at import.

Two modules consume these callables and neither one keeps a second copy of the
numbers: `placement/masonry.py` runs the opening checks at placement time and
places the band geometry, and `design/masonry.py` turns the band and bar specs
into the wall prescription that quantities and the report read.

Lengths are metres out (the tables carry mm because that is how the code prints
them), spans are metres in, bar and band dimensions stay in mm as section
dimensions do everywhere in this engine.
"""

from __future__ import annotations

from typing import Any, Dict, List, NamedTuple, Optional, Sequence, Tuple

from ..data._loader import load_yaml, require_keys
from ..model import Opening, WallLine, opening_span
from .is1905 import CodeInputError
from .trace import clause

CODE = "IS4326:1993"

TABLE_NAME = "is4326_tables"

CATEGORIES = ("A", "B", "C", "D", "E")

ROOF_TYPES = ("flat", "gable", "hip", "shed")

ZONE_ALIASES = {
    "1": "I",
    "2": "II",
    "3": "III",
    "4": "IV",
    "5": "V",
    "I": "I",
    "II": "II",
    "III": "III",
    "IV": "IV",
    "V": "V",
}

_ETA = 1e-9


class OpeningRules(NamedTuple):
    """The four Table 4 limits that apply to one wall segment, in SI metres."""

    category: str
    storeys: int
    b5_corner_min_m: float
    b4_pier_min_m: float
    opening_ratio_max: float
    h3_vertical_gap_min_m: float


class OpeningViolation(NamedTuple):
    """One Table 4 breach on one wall. `value` and `limit` share `units`."""

    check: str
    clause_id: str
    wall_id: str
    opening_ids: Tuple[str, ...]
    value: float
    limit: float
    units: str
    message: str


class BandSpec(NamedTuple):
    """A reinforced concrete band: what to build, per IS 4326 Table 6."""

    kind: str
    category: str
    span_band_m: float
    bars_n: int
    bar_dia_mm: int
    depth_mm: int
    link_dia_mm: int
    link_spacing_mm: int
    concrete_grade: str
    steel_grade: str
    width_source: str
    note: str


class BarSpec(NamedTuple):
    """Vertical steel at one storey of a wall, per IS 4326 Table 7."""

    category: str
    storeys: int
    storey_index: int
    position: str
    dia_mm: int
    bars_per_location: int
    steel_grade: str
    locations: Tuple[str, ...]
    note: str


# ---------------------------------------------------------------------------
# table access and validation
# ---------------------------------------------------------------------------


def tables() -> Dict[str, Any]:
    """The parsed IS 4326 table file. Shared cache entry, treat as read-only."""
    return load_yaml(TABLE_NAME)


def _table(key: str) -> Dict[str, Any]:
    block = tables().get(key)
    if not isinstance(block, dict):
        raise ValueError(TABLE_NAME + " is missing the table block: " + key)
    return block


def _validate_tables() -> None:
    """Shape asserts, run once at import so a bad edit is loud rather than silent."""
    require_keys(
        tables(),
        [
            "source",
            "edition",
            "seismic_category_map",
            "table_4_openings",
            "table_6_band_steel",
            "table_7_vertical_steel",
        ],
        TABLE_NAME,
    )

    category_map = _table("seismic_category_map")
    if tuple(category_map["ladder"]) != CATEGORIES:
        raise ValueError(TABLE_NAME + " category ladder must be " + ", ".join(CATEGORIES))
    for zone in sorted(category_map["base"]):
        if str(category_map["base"][zone]) not in CATEGORIES:
            raise ValueError(TABLE_NAME + " zone " + str(zone) + " maps outside the category ladder")

    t4 = _table("table_4_openings")
    for key in ("b5_corner_min_mm", "b4_pier_min_mm"):
        listed = sorted(str(c) for c in t4[key])
        if listed != sorted(CATEGORIES):
            raise ValueError(TABLE_NAME + " table 4 " + key + " must cover every category")
    ratios = t4["opening_ratio_max"]
    for category in CATEGORIES:
        klass = str(ratios["class_of"][category])
        if klass not in ratios["by_storeys"]:
            raise ValueError(TABLE_NAME + " table 4 has no ratio row for class " + klass)

    t6 = _table("table_6_band_steel")
    bands = [str(int(s)) for s in t6["span_bands_m"]]
    for span in bands:
        row = t6["values"][span]
        for category in t6["categories"]:
            entry = row[category]
            if len(entry) != 2:
                raise ValueError(TABLE_NAME + " table 6 entry " + span + "/" + str(category) + " must be [bars, dia_mm]")

    t7 = _table("table_7_vertical_steel")
    for storeys in sorted(t7["positions"]):
        positions = [str(p) for p in t7["positions"][storeys]]
        if len(positions) != int(storeys):
            raise ValueError(TABLE_NAME + " table 7 storey " + str(storeys) + " lists the wrong number of positions")
        for position in positions:
            if position not in t7["values"][storeys]:
                raise ValueError(TABLE_NAME + " table 7 storey " + str(storeys) + " has no row for " + position)


_validate_tables()


# ---------------------------------------------------------------------------
# input normalizers
# ---------------------------------------------------------------------------


def _normalize_category(category: Any) -> str:
    token = str(category).strip().upper()
    if token not in CATEGORIES:
        raise CodeInputError("unknown seismic category " + repr(category) + "; IS 4326 lists " + ", ".join(CATEGORIES))
    return token


def _normalize_zone(zone: Any) -> str:
    token = str(zone).strip().upper()
    if token not in ZONE_ALIASES:
        raise CodeInputError(
            "unknown seismic zone " + repr(zone) + "; expected II, III, IV or V (or the matching integer)"
        )
    return ZONE_ALIASES[token]


def _normalize_roof(roof_type: Any) -> str:
    token = str(roof_type).strip().lower()
    if token not in ROOF_TYPES:
        raise CodeInputError("unknown roof type " + repr(roof_type) + "; expected one of " + ", ".join(ROOF_TYPES))
    return token


# ---------------------------------------------------------------------------
# Cl 7 / Table 1: seismic category
# ---------------------------------------------------------------------------


@clause(
    code=CODE,
    ref="Table 1",
    title="Building category for seismic strengthening",
    symbol="cat",
    units="",
)
def seismic_category(zone: Any, importance: float = 1.0) -> str:
    """Category A to E from the seismic zone and the importance factor.

    At importance 1.0, the ordinary residential building, zones II, III, IV and V
    read B, C, D and E. An important building (importance at or above 1.5) moves
    one step up the ladder and stops at E.
    """
    table = _table("seismic_category_map")
    key = _normalize_zone(zone)
    base = table["base"]
    if key not in base:
        raise CodeInputError("IS 4326 category map has no zone " + key)
    ladder = [str(c) for c in table["ladder"]]
    index = ladder.index(str(base[key]))
    if float(importance) >= float(table["importance_bump_at"]) - _ETA:
        index = min(index + int(table["bump_steps"]), len(ladder) - 1)
    return ladder[index]


# ---------------------------------------------------------------------------
# Table 4: openings in bearing walls
# ---------------------------------------------------------------------------


@clause(
    code=CODE,
    ref="Table 4",
    title="Size and position of openings in bearing walls",
    symbol="rules",
    units="m",
)
def opening_limits(storeys: int, category: Any) -> OpeningRules:
    """The four Table 4 limits for a building of this height and category, in metres.

    A storey count above the encoded 3 reads the 3 storey row: load bearing
    masonry taller than that is refused upstream with E_MASONRY_LIMIT, so the
    clamp is never what decides a design. The clamped value is the `storeys`
    field of the result, next to the raw input in the trace.
    """
    table = _table("table_4_openings")
    cat = _normalize_category(category)
    count = int(storeys)
    if count < 1:
        raise CodeInputError("storeys must be at least 1, got " + repr(storeys))
    count = min(count, int(table["max_storeys_encoded"]))
    ratios = table["opening_ratio_max"]
    klass = str(ratios["class_of"][cat])
    return OpeningRules(
        category=cat,
        storeys=count,
        b5_corner_min_m=float(table["b5_corner_min_mm"][cat]) / 1000.0,
        b4_pier_min_m=float(table["b4_pier_min_mm"][cat]) / 1000.0,
        opening_ratio_max=float(ratios["by_storeys"][klass][str(count)]),
        h3_vertical_gap_min_m=float(table["h3_vertical_gap_min_mm"]) / 1000.0,
    )


def _sorted_openings(wall: WallLine) -> List[Tuple[float, float, Opening]]:
    """(s0, s1, opening) triples along the wall, ordered so the check is stable."""
    spans = []
    for opening in wall.openings:
        s0, s1 = opening_span(wall, opening)
        spans.append((float(s0), float(s1), opening))
    spans.sort(key=lambda item: (item[0], item[1], str(item[2].id)))
    return spans


def _union_length(spans: Sequence[Tuple[float, float, Opening]]) -> float:
    """Total wall length covered by openings, counting an overlap once."""
    total = 0.0
    reach = None  # type: Optional[float]
    for s0, s1, _ in spans:
        if reach is None or s0 > reach:
            total += s1 - s0
            reach = s1
        elif s1 > reach:
            total += s1 - reach
            reach = s1
    return total


@clause(
    code=CODE,
    ref="Cl 8.3",
    title="Opening checks on a bearing wall",
    symbol="violations",
    units="m",
)
def check_openings(
    wall: WallLine,
    rules: OpeningRules,
    corner_ends: Sequence[bool] = (True, True),
) -> List[OpeningViolation]:
    """Every Table 4 breach on one bearing wall segment, in wall order.

    Four checks run: b5, the distance from an end jamb to the inside corner;
    the total opening ratio along the segment; b4, the pier between two
    consecutive openings; and h3, the clear vertical gap between two openings
    one above the other. `corner_ends` says which of the two segment ends is a
    real building corner, so an interior segment that runs into a T junction is
    not measured against the corner rule; the default treats both ends as
    corners, the conservative reading.

    The ratio is measured on the union of the plan spans, so an opening stacked
    above another counts once. A pair with no sill or head data skips the h3
    check rather than guessing at it; the assumed-opening disclosure upstream is
    what tells the reader the geometry was synthesized.
    """
    length = float(wall.length_m())
    if length <= 0.0:
        raise CodeInputError("wall " + str(wall.id) + " has no length")
    if len(corner_ends) != 2:
        raise CodeInputError("corner_ends must name both ends of the wall")

    spans = _sorted_openings(wall)
    violations = []  # type: List[OpeningViolation]
    clause_id = CODE + " Table 4"
    if not spans:
        return violations

    if bool(corner_ends[0]):
        first = spans[0]
        if first[0] < rules.b5_corner_min_m - _ETA:
            violations.append(
                OpeningViolation(
                    check="b5_corner",
                    clause_id=clause_id,
                    wall_id=str(wall.id),
                    opening_ids=(str(first[2].id),),
                    value=first[0],
                    limit=rules.b5_corner_min_m,
                    units="m",
                    message=(
                        "opening jamb sits "
                        + ("%.3f" % first[0])
                        + " m from the wall corner, below the category "
                        + rules.category
                        + " minimum of "
                        + ("%.3f" % rules.b5_corner_min_m)
                        + " m"
                    ),
                )
            )
    if bool(corner_ends[1]):
        last = spans[-1]
        tail = length - last[1]
        if tail < rules.b5_corner_min_m - _ETA:
            violations.append(
                OpeningViolation(
                    check="b5_corner",
                    clause_id=clause_id,
                    wall_id=str(wall.id),
                    opening_ids=(str(last[2].id),),
                    value=tail,
                    limit=rules.b5_corner_min_m,
                    units="m",
                    message=(
                        "opening jamb sits "
                        + ("%.3f" % tail)
                        + " m from the far wall corner, below the category "
                        + rules.category
                        + " minimum of "
                        + ("%.3f" % rules.b5_corner_min_m)
                        + " m"
                    ),
                )
            )

    ratio = _union_length(spans) / length
    if ratio > rules.opening_ratio_max + _ETA:
        violations.append(
            OpeningViolation(
                check="opening_ratio",
                clause_id=clause_id,
                wall_id=str(wall.id),
                opening_ids=tuple(str(item[2].id) for item in spans),
                value=ratio,
                limit=rules.opening_ratio_max,
                units="ratio",
                message=(
                    "openings cover "
                    + ("%.3f" % ratio)
                    + " of the wall segment, above the category "
                    + rules.category
                    + " limit of "
                    + ("%.3f" % rules.opening_ratio_max)
                    + " at "
                    + str(rules.storeys)
                    + " storeys"
                ),
            )
        )

    for index in range(len(spans) - 1):
        left = spans[index]
        right = spans[index + 1]
        pier = right[0] - left[1]
        if pier < -_ETA:
            continue  # the openings overlap in plan; that is the h3 case below
        if pier < rules.b4_pier_min_m - _ETA:
            violations.append(
                OpeningViolation(
                    check="b4_pier",
                    clause_id=clause_id,
                    wall_id=str(wall.id),
                    opening_ids=(str(left[2].id), str(right[2].id)),
                    value=pier,
                    limit=rules.b4_pier_min_m,
                    units="m",
                    message=(
                        "pier between openings is "
                        + ("%.3f" % pier)
                        + " m, below the category "
                        + rules.category
                        + " minimum of "
                        + ("%.3f" % rules.b4_pier_min_m)
                        + " m"
                    ),
                )
            )

    for index in range(len(spans)):
        for other in range(index + 1, len(spans)):
            lower = spans[index]
            upper = spans[other]
            if upper[0] > lower[1] - _ETA or lower[0] > upper[1] - _ETA:
                continue  # no overlap in plan, so they are side by side, not stacked
            gap = _vertical_gap(lower[2], upper[2])
            if gap is None or gap >= rules.h3_vertical_gap_min_m - _ETA:
                continue
            violations.append(
                OpeningViolation(
                    check="h3_vertical_gap",
                    clause_id=clause_id,
                    wall_id=str(wall.id),
                    opening_ids=(str(lower[2].id), str(upper[2].id)),
                    value=gap,
                    limit=rules.h3_vertical_gap_min_m,
                    units="m",
                    message=(
                        "stacked openings are "
                        + ("%.3f" % gap)
                        + " m apart vertically, below the "
                        + ("%.3f" % rules.h3_vertical_gap_min_m)
                        + " m minimum"
                    ),
                )
            )
    return violations


def _vertical_gap(first: Opening, second: Opening) -> Optional[float]:
    """Clear vertical distance between two openings on the same wall, or None."""
    heights = []
    for lower, upper in ((first, second), (second, first)):
        if lower.head_m is None or upper.sill_m is None:
            continue
        gap = float(upper.sill_m) - float(lower.head_m)
        if gap >= -_ETA:
            heights.append(gap)
    if not heights:
        return None
    return min(heights)


# ---------------------------------------------------------------------------
# Table 6: reinforced concrete bands
# ---------------------------------------------------------------------------


def _span_band(span_m: Optional[float]) -> Optional[str]:
    """The Table 6 row a span falls in, or None when no span was supplied."""
    if span_m is None:
        return None
    table = _table("table_6_band_steel")
    bands = sorted(int(s) for s in table["span_bands_m"])
    span = float(span_m)
    if span <= 0.0:
        raise CodeInputError("band span must be positive, got " + repr(span_m))
    for band in bands:
        if span <= float(band) + _ETA:
            return str(band)
    raise CodeInputError(
        "band span "
        + ("%.3f" % span)
        + " m is past the last row of IS 4326 Table 6 ("
        + str(bands[-1])
        + " m); a longer band needs its own design, not an extrapolated table row"
    )


def _band_spec(kind: str, category: str, span_m: Optional[float], note: str) -> Optional[BandSpec]:
    """Assemble one BandSpec, or None when the category takes no band at all."""
    table = _table("table_6_band_steel")
    if category in [str(c) for c in table["categories_without_band"]]:
        return None
    row = _span_band(span_m)
    if row is None:
        bars_n = int(table["nominal"]["bars_n"])
        dia_mm = int(table["nominal"]["bar_dia_mm"])
        span_band = 0.0
    else:
        entry = table["values"][row][category]
        bars_n = int(entry[0])
        dia_mm = int(entry[1])
        span_band = float(int(row))
    two_layer = bars_n >= int(table["two_layer_bars_n"]) or dia_mm > int(table["two_layer_bar_dia_mm"])
    depth_mm = int(table["depth_mm_two_layer"]) if two_layer else int(table["depth_mm_base"])
    return BandSpec(
        kind=kind,
        category=category,
        span_band_m=span_band,
        bars_n=bars_n,
        bar_dia_mm=dia_mm,
        depth_mm=depth_mm,
        link_dia_mm=int(table["link_dia_mm"]),
        link_spacing_mm=int(table["link_spacing_mm"]),
        concrete_grade=str(table["concrete_grade"]),
        steel_grade=str(table["steel_grade"]),
        width_source=str(table["width_source"]),
        note=note,
    )


@clause(
    code=CODE,
    ref="Table 6 lintel",
    title="Lintel band",
    symbol="lintel_band",
    units="mm",
)
def lintel_band(span_m: float, category: Any) -> Optional[BandSpec]:
    """The lintel band for a category B to E building. None for category A.

    The band runs as a continuous closed loop over every bearing wall at the
    opening head level; `span_m` is its clear span between cross walls, which is
    what picks the Table 6 row.
    """
    cat = _normalize_category(category)
    return _band_spec("lintel", cat, span_m, "continuous closed loop at lintel level over every bearing wall")


@clause(
    code=CODE,
    ref="Table 6 roof",
    title="Roof band",
    symbol="roof_band",
    units="mm",
)
def roof_band(span_m: float, category: Any, roof_type: Any, cast_in_situ_slab: bool = True) -> Optional[BandSpec]:
    """The eaves band, or None where a cast-in-situ RC roof slab already is one.

    Cl 8.4.6 exempts a flat roof whose slab is cast in situ and monolithic with
    the walls: the slab is the band. That is the flat-roof default this engine
    ships, so the exemption is the usual answer and is returned as None with the
    reason in the trace, never dropped silently. A precast or otherwise
    non-monolithic flat roof (`cast_in_situ_slab=False`) puts the band back, and
    every pitched roof carries one at the eaves.
    """
    cat = _normalize_category(category)
    roof = _normalize_roof(roof_type)
    table = _table("table_6_band_steel")
    if roof in [str(r) for r in table["roof_band_exempt_roofs"]] and bool(cast_in_situ_slab):
        return None
    note = "eaves band, also the wall plate line the rafters anchor to"
    if roof in [str(r) for r in table["roof_band_exempt_roofs"]]:
        note = "roof band required: the flat roof is not a cast-in-situ slab monolithic with the walls"
    return _band_spec("roof", cat, span_m, note)


@clause(
    code=CODE,
    ref="Table 6 plinth",
    title="Plinth band",
    symbol="plinth_band",
    units="mm",
)
def plinth_band(category: Any, soft_soil: bool = False, span_m: Optional[float] = None) -> Optional[BandSpec]:
    """The plinth band where Cl 8.4.7 makes one mandatory, otherwise None.

    Mandatory on soft or filled soil, and for categories D and E on any soil.
    Elsewhere it is recommended rather than required, and this returns None so
    the report can say so. With no span the nominal two 8 mm bar band is used.
    """
    cat = _normalize_category(category)
    if not (bool(soft_soil) or cat in ("D", "E")):
        return None
    reason = "soft or filled soil" if bool(soft_soil) else ("category " + cat)
    return _band_spec("plinth", cat, span_m, "plinth band mandatory: " + reason)


@clause(
    code=CODE,
    ref="Table 6 gable",
    title="Gable band",
    symbol="gable_band",
    units="mm",
)
def gable_band(category: Any, roof_type: Any, span_m: Optional[float] = None) -> Optional[BandSpec]:
    """A band along the raking top of a gable or shed end wall, otherwise None.

    Only a gable and a shed roof have a raking end wall to band. A hip roof has
    none, so its level eaves band is the whole story, and a flat roof has no
    raking wall at all.
    """
    cat = _normalize_category(category)
    roof = _normalize_roof(roof_type)
    table = _table("table_6_band_steel")
    if roof not in [str(r) for r in table["gable_band_roofs"]]:
        return None
    return _band_spec("gable", cat, span_m, "raking band on the " + roof + " end wall, tied into the eaves band at both ends")


# ---------------------------------------------------------------------------
# Table 7: vertical steel
# ---------------------------------------------------------------------------


@clause(
    code=CODE,
    ref="Table 7",
    title="Vertical steel in masonry walls",
    symbol="vertical_bars",
    units="mm",
)
def vertical_bars(storeys: int, storey_index: int, category: Any) -> Optional[BarSpec]:
    """The single HYSD bar diameter at one storey, or None where none is required.

    `storey_index` is 0 based with 0 = ground, matching the rest of the engine.
    Categories A and B take no vertical steel from Table 7 and return None. A
    stack taller than the 3 storeys transcribed here raises rather than reading
    a row that is not in the file; load bearing masonry that tall is refused
    upstream with E_MASONRY_LIMIT.
    """
    table = _table("table_7_vertical_steel")
    cat = _normalize_category(category)
    count = int(storeys)
    index = int(storey_index)
    if count < 1:
        raise CodeInputError("storeys must be at least 1, got " + repr(storeys))
    if index < 0 or index >= count:
        raise CodeInputError("storey_index " + repr(storey_index) + " is outside a " + str(count) + " storey stack")
    if count > int(table["max_storeys_encoded"]):
        raise CodeInputError(
            str(count)
            + " storeys is past the transcribed rows of IS 4326 Table 7 (up to "
            + str(table["max_storeys_encoded"])
            + "); load bearing masonry that tall is refused upstream"
        )
    if cat in [str(c) for c in table["categories_without_steel"]]:
        return None
    key = str(count)
    position = str(table["positions"][key][index])
    dia = table["values"][key][position][cat]
    if dia is None:
        return None
    return BarSpec(
        category=cat,
        storeys=count,
        storey_index=index,
        position=position,
        dia_mm=int(dia),
        bars_per_location=int(table["bars_per_location"]),
        steel_grade=str(table["steel_grade"]),
        locations=tuple(str(loc) for loc in table["locations"][cat]),
        note=str(table["locations_note"]),
    )
