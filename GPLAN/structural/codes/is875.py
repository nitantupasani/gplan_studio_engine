"""IS 875 clause callables: dead loads, imposed loads, wind.

One clause is one pure callable that reads its numbers from `data/is875_*.yaml`
and returns a float or a NamedTuple. Every callable is registered in
CLAUSE_REGISTRY by the `@clause` decorator in `codes/trace.py` and records a
TraceEntry whenever a sink is open; nothing here prints, logs or holds state.

Units are SI: metres, kN, kPa (kN/m2), kN/m3, m/s, degrees for angles.

Tables covered
    Part 1 : 1987  unit weights (Table 1) and component area loads (Table 2)
    Part 2 : 1987  imposed floor loads (Table 1), roofs (Table 2), the
                   multi-storey reduction (Cl 3.2.1)
    Part 3 : 2015  basic wind speed, k2 (Table 2), Ka (Table 4), design wind
                   speed and pressure (Cl 6.2, 6.3), Cpe for walls (Table 5)
                   and pitched roofs (Table 6), Cpi (Cl 7.3.2)

Disclosure is the caller's job: these functions have no model to write to, so
the conditions worth an entry on the ladder come back as fields on the returned
NamedTuple or from the small predicates next to them.

    part2_reduction_factor(...).applied is False -> the >5 kPa bar blocked the
        reduction; the takedown discloses it.
    is875_occupancy_key(occ).mapped is False -> the fallback occupancy was
        used; loads/live.py raises W_LOAD_OCCUPANCY_FALLBACK.
    part3_k2_range(z_m) != "in_table", CpeWalls.out_of_table,
        CpeRoof.out_of_table -> loads/wind.py raises W_WIND_STATIC_LIMIT.

Clause numbers follow the editions named in the YAML headers. Values the loads
spec did not itself vet carry verify: "print" in the data files; they are
planning defaults, not a transcription anyone has checked against the printed
code.
"""

from __future__ import annotations

from typing import Any, Dict, List, NamedTuple, Optional, Sequence, Tuple

from ..data._loader import load_yaml, require_keys
from ..model import Occupancy
from .trace import clause

PART1 = "IS 875-1:1987"
PART2 = "IS 875-2:1987"
PART3 = "IS 875-3:2015"

# Band comparisons are on ratios of measured lengths; a hair of tolerance keeps
# an exactly-on-the-boundary ratio inside the band the code intends.
_BAND_TOL = 1e-9


# ---------------------------------------------------------------------------
# table access
# ---------------------------------------------------------------------------

_REQUIRED = {
    "is875_1_unit_weights": ("source", "edition", "materials", "area_loads", "defaults"),
    "is875_2_imposed": ("source", "edition", "occupancies", "roofs", "sloped_roof", "reduction"),
    "is875_3_wind": ("source", "edition", "basic_wind_speed", "k2", "factors", "cpe_walls", "cpe_pitched_roof", "cpi"),
}

_VALIDATED = set()  # type: set


def _table(name: str) -> Dict[str, Any]:
    """Load a table once, validating its top-level keys on first use."""
    table = load_yaml(name)
    if name not in _VALIDATED:
        require_keys(table, _REQUIRED[name], name + ".yaml")
        _VALIDATED.add(name)
    return table


def _key(name: Any) -> str:
    """Normalized lookup key: trimmed, lower case."""
    return str(name).strip().lower()


def _pick(mapping: Dict[str, Any], name: Any, what: str) -> Any:
    """Fetch `name` from `mapping` or raise naming every known key, sorted."""
    key = _key(name)
    if key in mapping:
        return mapping[key]
    known = ", ".join(sorted(str(k) for k in mapping))
    raise KeyError("unknown " + what + ": " + repr(str(name)) + "; known keys: " + known)


def _value_of(entry: Any, field: str) -> float:
    """Read a numeric leaf, whether the entry is a bare number or a mapping."""
    if isinstance(entry, dict):
        return float(entry[field])
    return float(entry)


# ---------------------------------------------------------------------------
# interpolation
# ---------------------------------------------------------------------------


def _interp_1d(x: float, xs: Sequence[float], ys: Sequence[float]) -> float:
    """Piecewise-linear on an ascending `xs`, clamped outside the range."""
    if len(xs) != len(ys) or not xs:
        raise ValueError("interpolation needs equal, non-empty sample lists")
    if x <= xs[0]:
        return float(ys[0])
    if x >= xs[-1]:
        return float(ys[-1])
    for i in range(1, len(xs)):
        x1 = float(xs[i])
        if x <= x1:
            x0 = float(xs[i - 1])
            y0 = float(ys[i - 1])
            y1 = float(ys[i])
            if x1 == x0:
                return y0
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return float(ys[-1])


def _bilinear(x: float, y: float, xs: Sequence[float], ys: Sequence[float], grid: Sequence[Sequence[float]]) -> float:
    """`grid[i][j]` sampled at `xs[i]`, `ys[j]`; linear in y, then in x, clamped."""
    if len(grid) != len(xs):
        raise ValueError("grid row count does not match the x samples")
    rows = [_interp_1d(y, ys, grid[i]) for i in range(len(xs))]
    return _interp_1d(x, xs, rows)


# ---------------------------------------------------------------------------
# returned shapes
# ---------------------------------------------------------------------------


class LiveReduction(NamedTuple):
    """Cl 3.2.1 reduction on an imposed load carried by a column, wall or footing."""

    reduction: float  # fraction removed, 0.00 to 0.50
    factor: float  # multiplier on the raw imposed load, 1 - reduction
    applied: bool  # False when the >5 kPa bar of Cl 3.2.2 blocked the reduction
    floors_carried: int


class OccupancyMapping(NamedTuple):
    """model.Occupancy resolved onto an IS 875 (Part 2) occupancy key."""

    key: str
    mapped: bool  # False -> the fallback key; the caller discloses


class CpeWalls(NamedTuple):
    """Table 5 wall coefficients for wind normal to the face, plus the frame net."""

    windward: float
    leeward: float
    side: float
    net: float  # windward - leeward, the coefficient the storey shear uses
    out_of_table: bool


class CpeRoof(NamedTuple):
    """Table 6 pitched roof coefficients on the windward and leeward slopes."""

    windward: float
    leeward: float
    out_of_table: bool


class Cpi(NamedTuple):
    """Cl 7.3.2 internal pressure coefficient, acting either way."""

    magnitude: float
    plus: float
    minus: float


# ---------------------------------------------------------------------------
# Part 1 : dead loads
# ---------------------------------------------------------------------------


@clause(code=PART1, ref="Table 1", title="Unit weight of a building material", symbol="gamma", units="kN/m3")
def part1_unit_weight(name: str) -> float:
    """Unit weight in kN/m3, for example `rcc` -> 25.0."""
    entry = _pick(_table("is875_1_unit_weights")["materials"], name, "material")
    return _value_of(entry, "gamma_kn_m3")


@clause(code=PART1, ref="Table 2", title="Area load of a building component", symbol="q", units="kPa")
def part1_area_load(name: str) -> float:
    """Area load in kPa of a finish, fill or roof covering, for example `floor_finish` -> 1.5.

    `sunken_fill` is quoted for the reference depth recorded in the table; scale
    it linearly with the actual sink depth at the caller.
    """
    entry = _pick(_table("is875_1_unit_weights")["area_loads"], name, "area load")
    return _value_of(entry, "q_kpa")


def dead_load_default(name: str) -> Any:
    """An engine dead-load default from the Part 1 table (`plaster_thickness_m`,
    `parapet_height_m`, `parapet_thickness_m`, `partition_allowance_kpa`,
    `opening_deduction`).

    Not a clause: these are engine conventions parked with the data they belong
    to, not printed code values. Whoever applies one discloses it.
    """
    entry = _pick(_table("is875_1_unit_weights")["defaults"], name, "dead load default")
    return entry["value"] if isinstance(entry, dict) else entry


def area_load_reference_depth_m(name: str) -> Optional[float]:
    """Depth an area load is quoted for, when it is depth-dependent (else None)."""
    entry = _pick(_table("is875_1_unit_weights")["area_loads"], name, "area load")
    if isinstance(entry, dict) and "reference_depth_m" in entry:
        return float(entry["reference_depth_m"])
    return None


# ---------------------------------------------------------------------------
# Part 2 : imposed loads
# ---------------------------------------------------------------------------

# Finding 22: the adapter is the only room-name parser. This maps the resolved
# model.Occupancy enum onto the Part 2 occupancy keys, nothing more. Occupancy
# is a str Enum, so a raw value string keys the dict just as well as a member.
OCCUPANCY_TO_IS875 = {
    Occupancy.HABITABLE.value: "residential_room",
    Occupancy.KITCHEN.value: "residential_room",
    Occupancy.UTILITY.value: "residential_room",
    Occupancy.BATH.value: "toilet_bath",
    Occupancy.WC.value: "toilet_bath",
    Occupancy.BALCONY.value: "balcony",
    Occupancy.GREEN.value: "balcony",
    Occupancy.CORRIDOR.value: "corridor_stair",
    Occupancy.STAIR.value: "corridor_stair",
    Occupancy.LIFT.value: "corridor_stair",
    Occupancy.LOBBY.value: "corridor_stair",
    Occupancy.STORAGE.value: "store",
    Occupancy.PARKING.value: "garage_light",
}  # type: Dict[str, str]

# Occupancy.VOID and Occupancy.OTHER are deliberately absent: they carry no code
# imposed load, so they take the fallback and the caller discloses.
OCCUPANCY_FALLBACK_KEY = "residential_room"
OCCUPANCY_FALLBACK_CODE = "W_LOAD_OCCUPANCY_FALLBACK"


def is875_occupancy_key(occupancy: Any) -> OccupancyMapping:
    """Resolve a model Occupancy (member or value) to a Part 2 occupancy key.

    Unmapped occupancies come back as the fallback with `mapped` False; the
    caller raises `W_LOAD_OCCUPANCY_FALLBACK` on the model's ladder. Not a
    clause: it is a vocabulary bridge, not a code rule.
    """
    value = occupancy.value if isinstance(occupancy, Occupancy) else _key(occupancy)
    key = OCCUPANCY_TO_IS875.get(value)
    if key is None:
        return OccupancyMapping(key=OCCUPANCY_FALLBACK_KEY, mapped=False)
    return OccupancyMapping(key=key, mapped=True)


@clause(code=PART2, ref="Table 1", title="Imposed load by occupancy", symbol="q", units="kPa")
def part2_imposed(occupancy_key: str) -> float:
    """Imposed load in kPa for an occupancy key, for example `residential_room` -> 2.0.

    Roof keys (`roof_accessible`, `roof_non_accessible`) resolve here too, so a
    panel of either kind takes one call.
    """
    table = _table("is875_2_imposed")
    key = _key(occupancy_key)
    for block in ("occupancies", "roofs"):
        entry = table[block].get(key)
        if entry is not None:
            return _value_of(entry, "q_kpa")
    known = sorted(list(table["occupancies"]) + list(table["roofs"]))
    raise KeyError("unknown occupancy key: " + repr(str(occupancy_key)) + "; known keys: " + ", ".join(known))


@clause(code=PART2, ref="Table 2", title="Imposed load on a sloping roof", symbol="q_r", units="kPa")
def part2_sloped_roof_live(alpha_deg: float) -> float:
    """Roof imposed load with access for maintenance only, by roof slope.

    0.75 kPa to the threshold slope, then less 0.02 kPa per degree, floored at
    0.4 kPa. Flat roof 0.75, 20 deg 0.55, 30 deg 0.4 (the floor governs).
    """
    rule = _table("is875_2_imposed")["sloped_roof"]
    base = float(rule["base_q_kpa"])
    threshold = float(rule["slope_threshold_deg"])
    alpha = float(alpha_deg)
    if alpha <= threshold:
        return base
    reduced = base - float(rule["per_degree_kpa"]) * (alpha - threshold)
    return max(reduced, float(rule["min_q_kpa"]))


@clause(code=PART2, ref="3.2.1", title="Reduction in imposed load on multi-storey supports", symbol="reduction", units="")
def part2_reduction_factor(n_floors_carried: int, q_kpa: Optional[float] = None) -> LiveReduction:
    """Cl 3.2.1 reduction for a column, wall or footing carrying `n_floors_carried` floors.

    The roof counts as the first floor carried. `reduction` is the fraction
    removed (5 floors -> 0.40) and `factor` is the multiplier the takedown
    applies (0.60). Pass the governing storey imposed load as `q_kpa` to enforce
    Cl 3.2.2: above 5 kPa no reduction is taken, `factor` comes back 1.0 and
    `applied` False for the caller to disclose.

    Never applied to slab or beam design forces (spec section 8).
    """
    block = _table("is875_2_imposed")["reduction"]
    floors = int(n_floors_carried)
    if floors < 1:
        floors = 1
    if q_kpa is not None and float(q_kpa) > float(block["no_reduction_above_kpa"]):
        return LiveReduction(reduction=0.0, factor=1.0, applied=False, floors_carried=floors)
    reduction = 0.0
    for band in block["bands"]:
        upper = band["floors_carried_max"]
        if floors >= int(band["floors_carried_min"]) and (upper is None or floors <= int(upper)):
            reduction = float(band["reduction"])
            break
    return LiveReduction(reduction=reduction, factor=1.0 - reduction, applied=True, floors_carried=floors)


# ---------------------------------------------------------------------------
# Part 3 : wind
# ---------------------------------------------------------------------------


@clause(code=PART3, ref="5.2", title="Basic wind speed", symbol="Vb", units="m/s")
def part3_basic_wind_speed(zone: str) -> float:
    """Basic wind speed for a map zone `1`..`6` (33, 39, 44, 47, 50, 55 m/s).

    A city name from the Annex A subset resolves too, so a caller with a place
    rather than a zone has one call.
    """
    block = _table("is875_3_wind")["basic_wind_speed"]
    key = _key(zone)
    zones = block["zones"]
    if key in zones:
        return float(zones[key])
    cities = block.get("cities", {}).get("values", {})
    if key in cities:
        return float(cities[key])
    known = ", ".join(sorted(str(k) for k in zones))
    raise KeyError("unknown wind zone: " + repr(str(zone)) + "; known zones: " + known + " (or an Annex A city name)")


@clause(code=PART3, ref="Table 2", title="Terrain, height and structure size factor", symbol="k2", units="")
def part3_k2(category: float, z_m: float) -> float:
    """k2 by terrain category (1 to 4) and height, bilinear on the Table 2 grid.

    Heights under the first tabulated height take the 10 m row, the conservative
    standard reading; `part3_k2_range` tells the caller which side of the table
    a height fell on.
    """
    block = _table("is875_3_wind")["k2"]
    return _bilinear(
        float(category),
        float(z_m),
        [float(c) for c in block["categories"]],
        [float(h) for h in block["heights_m"]],
        block["grid"],
    )


def part3_k2_range(z_m: float) -> str:
    """`below_table`, `in_table` or `above_table` for a height against Table 2.

    Not a clause: it reports where `part3_k2` clamped, so loads/wind.py can put
    `W_WIND_STATIC_LIMIT` on the ladder when a height leaves the printed range.
    """
    heights = _table("is875_3_wind")["k2"]["heights_m"]
    z = float(z_m)
    if z < float(heights[0]):
        return "below_table"
    if z > float(heights[-1]):
        return "above_table"
    return "in_table"


@clause(code=PART3, ref="6.2", title="Design wind speed", symbol="Vz", units="m/s")
def part3_design_wind_speed(Vb: float, k1: float, k2: float, k3: float, k4: float) -> float:
    """Vz = Vb k1 k2 k3 k4 at the height k2 was read at."""
    return float(Vb) * float(k1) * float(k2) * float(k3) * float(k4)


@clause(code=PART3, ref="6.3", title="Wind pressure at height z", symbol="pz", units="kPa")
def part3_wind_pressure(Vz: float) -> float:
    """pz = 0.6 Vz^2 in N/m2, returned in kPa (SI regime, spec section 1)."""
    return 0.6 * float(Vz) * float(Vz) / 1000.0


@clause(code=PART3, ref="6.3.1", title="Design wind pressure", symbol="pd", units="kPa")
def part3_design_pressure(pz: float, Kd: float = 1.0, Ka: float = 1.0, Kc: float = 1.0) -> float:
    """pd = Kd Ka Kc pz.

    All three factors default to 1.0, which is the conservative v1 default: the
    wind module passes the stored 0.9 / Ka / 0.9 only when the caller asks for
    them, and the choice is traced either way.
    """
    return float(pz) * float(Kd) * float(Ka) * float(Kc)


@clause(code=PART3, ref="Table 4", title="Area averaging factor", symbol="Ka", units="")
def part3_ka(area_m2: float) -> float:
    """Ka by tributary area: 1.0 at 10 m2, 0.9 at 25 m2, 0.8 at 100 m2 and above."""
    curve = _table("is875_3_wind")["factors"]["ka"]
    return _interp_1d(float(area_m2), [float(a) for a in curve["areas_m2"]], [float(v) for v in curve["values"]])


def part3_stored_factor(name: str) -> float:
    """The stored Kd or Kc value (0.9 each), defaulted off in v1.

    Not a clause: reading the number is not applying it. `part3_design_pressure`
    is where either one enters a pressure, and that call is traced.
    """
    entry = _pick(_table("is875_3_wind")["factors"], name, "wind factor")
    return _value_of(entry, "value")


def _band_rows(rows: Sequence[Dict[str, Any]], h_over_w: float) -> Tuple[List[Dict[str, Any]], bool]:
    """Rows of the first h/w band that contains the ratio, else the widest band."""
    caps = sorted({float(row["h_over_w_max"]) for row in rows})
    for cap in caps:
        if float(h_over_w) <= cap + _BAND_TOL:
            return [row for row in rows if float(row["h_over_w_max"]) == cap], False
    cap = caps[-1]
    return [row for row in rows if float(row["h_over_w_max"]) == cap], True


@clause(code=PART3, ref="Table 5", title="External pressure coefficients for walls", symbol="Cpe", units="")
def part3_cpe_walls(h_over_w: float, l_over_w: float) -> CpeWalls:
    """Wall Cpe for a rectangular clad building, wind normal to the face.

    Bands, not interpolation: the table is banded on h/w (1/2, 3/2, 6) and on
    l/w (3/2, 4). `net` is windward minus leeward, the frame coefficient the
    storey shear uses; Cpi cancels on the diaphragm total and is not in it.
    Ratios past the printed bands clamp to the widest band with `out_of_table`.
    """
    block = _table("is875_3_wind")["cpe_walls"]
    rows = block["rows"]
    band, out = _band_rows(rows, h_over_w)
    chosen = None
    for row in band:
        if float(l_over_w) <= float(row["l_over_w_max"]) + _BAND_TOL:
            chosen = row
            break
    if chosen is None:
        chosen = band[-1]
        out = True
    if float(l_over_w) >= max(float(row["l_over_w_max"]) for row in rows):
        out = True
    windward = float(chosen["windward"])
    leeward = float(chosen["leeward"])
    return CpeWalls(
        windward=windward,
        leeward=leeward,
        side=float(chosen["side"]),
        net=windward - leeward,
        out_of_table=bool(out),
    )


@clause(code=PART3, ref="Table 6", title="External pressure coefficients for pitched roofs", symbol="Cpe", units="")
def part3_cpe_pitched_roof(alpha_deg: float, h_over_w: float) -> CpeRoof:
    """Pitched roof Cpe on the windward and leeward slopes, wind along the span.

    Banded on h/w as Table 5 is, linear on the roof angle inside the band.
    Angles outside the printed 0 to 60 deg range clamp with `out_of_table`.
    """
    block = _table("is875_3_wind")["cpe_pitched_roof"]
    bands = block["bands"]
    band, out = _band_rows(bands, h_over_w)
    row = band[0]
    angles = [float(a) for a in row["angles_deg"]]
    alpha = float(alpha_deg)
    if alpha < angles[0] - _BAND_TOL or alpha > angles[-1] + _BAND_TOL:
        out = True
    return CpeRoof(
        windward=_interp_1d(alpha, angles, [float(v) for v in row["windward"]]),
        leeward=_interp_1d(alpha, angles, [float(v) for v in row["leeward"]]),
        out_of_table=bool(out),
    )


@clause(code=PART3, ref="7.3.2", title="Internal pressure coefficient", symbol="Cpi", units="")
def part3_cpi(permeability: str = "normal") -> Cpi:
    """Cpi by wall permeability: normal (low) 0.2, medium 0.5, large 0.7.

    Returned both ways round: the coefficient acts as suction and as pressure,
    and the governing sign belongs to the surface being checked.
    """
    block = _table("is875_3_wind")["cpi"]
    key = _key(permeability)
    if key == "low":
        key = "normal"
    entry = _pick({k: v for k, v in block.items() if isinstance(v, dict)}, key, "permeability")
    magnitude = float(entry["magnitude"])
    return Cpi(magnitude=magnitude, plus=magnitude, minus=-magnitude)


def part3_static_limits() -> Dict[str, float]:
    """Validity gates for the static method (height, slenderness, plan aspect).

    Not a clause: loads/wind.py compares the building against these and raises
    `W_WIND_STATIC_LIMIT` itself.
    """
    block = _table("is875_3_wind")["static_method_limits"]
    return {
        "max_height_m": float(block["max_height_m"]),
        "max_height_over_least_width": float(block["max_height_over_least_width"]),
        "max_plan_aspect_for_no_friction": float(block["max_plan_aspect_for_no_friction"]),
    }
