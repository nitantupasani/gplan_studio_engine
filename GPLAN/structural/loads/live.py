"""Imposed load case builder (IS 875 Part 2).

`build_live(model)` returns the unfactored ("LL", "LLR") pair:

    LL   floor and landing panels.  A panel's occupancy comes from the rooms
         it covers, each resolved through `codes.is875.OCCUPANCY_TO_IS875`
         (critic finding 22: the adapter parsed names once; this module maps
         the enum, nothing more).  A panel spanning rooms of differing imposed
         loads takes the maximum, disclosed.  Landings and every corridor /
         stair occupancy carry 3.0 kPa through the same table.  A room whose
         interior is unknown counts as residential (critic finding 39).
    LLR  roof panels: `roof_non_accessible` (0.75 kPa) by default,
         `roof_accessible` (1.5 kPa) when a stairs core reaches the roof
         storey; a pitched roof (meta.roof) takes the Table 2 sloping-roof
         formula on plan and lands on the eave members exactly as its dead
         load does.

The Cl 3.2.1 multi-storey reduction is NOT applied here: the takedown applies
it member-wise to columns, walls and footings only, tracking floors carried.
Beams take no tributary-area reduction in v1 (conservative, stated here).

Override (`live_load_kpa`, optional).  A caller may replace the Table 1 imposed
load the code would have used:

    build_live(model)                    every panel takes IS 875 (Part 2)
    build_live(model, 3.5)               3.5 kPa on HABITABLE panels, that is
                                         every panel whose governing occupancy
                                         key is `residential_room`
    build_live(model, {"toilet_bath": 2.5, "balcony": 4.0})
                                         per-occupancy, keyed either by the
                                         Part 2 occupancy key or by a
                                         model.Occupancy value ("bath")

The code value is still read and traced, the applied value is traced beside it
as a `request` record naming what it replaced, and the substitution lands on
the ladder as `W_LIVE_LOAD_OVERRIDDEN`.  With no override the case is byte for
byte the one the code alone produces: no extra call, no extra trace record and
no extra disclosure.  Roof imposed loads (LLR, Table 2) are never overridden.
"""

from __future__ import annotations

import math
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple, Union

from ..codes import is875
from ..codes.trace import TraceEntry, current_sink
from ..model import (
    CoreKind,
    GEOM_TOL_M,
    Occupancy,
    RoomPoly,
    SlabKind,
    StructuralModel,
    polygon_rect,
)
from . import CASE_LL, CASE_LLR, AreaLoad, CaseKind, LoadCase
from .dead import _rect_overlap_area, pitched_roof_context, pitched_roof_line_loads, roof_storey_index

_STAGE = "loads.live"

_SRC_TABLE1 = "IS 875-2:1987 Table 1"
_SRC_TABLE2 = "IS 875-2:1987 Table 2"
_SRC_SLOPED = "IS 875-2:1987 Table 2, sloping roof (access for maintenance only)"
_SRC_OVERRIDE = "request override (live_load_kpa), replacing " + _SRC_TABLE1

#: Registry code for a request value standing in for the Table 1 value.
OVERRIDE_CODE = "W_LIVE_LOAD_OVERRIDDEN"

#: The Part 2 floor occupancy keys an override may name, deterministic order.
#: Roof keys are absent on purpose: LLR comes from Table 2 and is not overridable.
OVERRIDABLE_KEYS = tuple(sorted(set(is875.OCCUPANCY_TO_IS875.values())))

#: A scalar override applies to the habitable key and to nothing else.
HABITABLE_KEY = is875.OCCUPANCY_FALLBACK_KEY


def _override_value(value: Any, label: str) -> float:
    """One override value as a positive finite kPa float; anything else raises."""
    what = "live_load_kpa " + (label + " " if label else "")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(what + "must be a number in kPa, got " + repr(value))
    number = float(value)
    if not math.isfinite(number) or number <= 0.0:
        raise ValueError(what + "must be a positive finite kPa value, got " + repr(value))
    return number


def _override_key(raw_key: Any, label: str) -> str:
    """One override key as a Part 2 floor occupancy key; anything else raises."""
    if isinstance(raw_key, str) and raw_key in OVERRIDABLE_KEYS:
        return raw_key
    mapping = is875.is875_occupancy_key(raw_key)
    if not mapping.mapped:
        raise ValueError(
            "live_load_kpa key "
            + repr(label)
            + " is neither an IS 875 (Part 2) floor occupancy key ("
            + ", ".join(OVERRIDABLE_KEYS)
            + ") nor a model Occupancy that maps to one"
        )
    return mapping.key


def resolve_live_override(live_load_kpa: Any) -> Dict[str, float]:
    """Normalize the override argument to {Part 2 occupancy key: q_kpa}.

    A number applies to `HABITABLE_KEY` alone.  A mapping is keyed by a Part 2
    occupancy key (`residential_room`, `toilet_bath`, ...) or by a
    model.Occupancy value (`habitable`, `bath`, ...), which resolves through the
    one occupancy bridge in `codes.is875`.  A key that names neither, a
    non-positive value, and two source keys that resolve to the same Part 2 key
    with different values all raise ValueError: an override the engine cannot
    honour exactly is refused, never quietly dropped (this whole argument exists
    because it used to be dropped).
    """
    if live_load_kpa is None:
        return {}
    if not isinstance(live_load_kpa, Mapping):
        return {HABITABLE_KEY: _override_value(live_load_kpa, "")}
    rows = []  # type: List[Tuple[str, str, Any]]
    for raw_key in live_load_kpa:
        label = raw_key.value if isinstance(raw_key, Occupancy) else str(raw_key)
        rows.append((_override_key(raw_key, label), label, live_load_kpa[raw_key]))
    rows.sort(key=lambda row: (row[0], row[1]))
    out = {}  # type: Dict[str, float]
    seen = {}  # type: Dict[str, str]
    for key, label, value in rows:
        number = _override_value(value, "for " + repr(label))
        if key in out and abs(out[key] - number) > 1e-12:
            raise ValueError(
                "live_load_kpa keys "
                + repr(seen[key])
                + " and "
                + repr(label)
                + " both resolve to "
                + key
                + " with different values ("
                + repr(out[key])
                + " and "
                + repr(number)
                + ")"
            )
        out[key] = number
        seen[key] = label
    return out


def _room_q_kpa(
    model: StructuralModel,
    room: RoomPoly,
    fallbacks: List[str],
    q_of: Callable[[str], float],
) -> Tuple[float, str]:
    """(q, is875 key) for one room; unknown-interior rooms read as residential."""
    if room.interior_unknown:
        return (q_of("residential_room"), "residential_room")
    mapping = is875.is875_occupancy_key(room.occupancy)
    if not mapping.mapped:
        fallbacks.append(room.id)
    return (q_of(mapping.key), mapping.key)


def _disclose_overrides(
    model: StructuralModel,
    overrides: Dict[str, float],
    replaced: Dict[str, Tuple[float, float]],
    panels: List[str],
) -> None:
    """Trace each substitution against the value it replaced, then disclose it.

    Called only when an override was supplied, so the default path adds nothing.
    The trace record is not a clause: it goes into the one `codes.trace` sink
    under the code "request", one per replaced occupancy key and after the Table
    1 records it stood in for, carrying the code value beside the value used, so
    a calc sheet shows the substitution rather than an unexplained number.
    """
    sink = current_sink()
    for key in sorted(replaced):
        code_q, applied = replaced[key]
        if sink is not None:
            sink.append(
                TraceEntry(
                    code="request",
                    ref="live_load_kpa",
                    title="Imposed load overridden on the request",
                    symbol="q",
                    inputs={
                        "occupancy_key": key,
                        "code_q_kpa": code_q,
                        "replaced": _SRC_TABLE1,
                    },
                    output=applied,
                    units="kPa",
                )
            )
    if replaced:
        model.add_warning(
            OVERRIDE_CODE,
            "live_load_kpa replaced the "
            + _SRC_TABLE1
            + " imposed load: "
            + ", ".join(
                "%s %.2f -> %.2f kPa" % (key, replaced[key][0], replaced[key][1])
                for key in sorted(replaced)
            ),
            sorted(set(panels)),
            clause=_SRC_TABLE1,
            stage=_STAGE,
        )
    unused = sorted(key for key in overrides if key not in replaced)
    if unused:
        model.add_warning(
            OVERRIDE_CODE,
            "live_load_kpa named "
            + ", ".join("%s %.2f kPa" % (key, overrides[key]) for key in unused)
            + " but no floor panel takes that occupancy; nothing was replaced there",
            (),
            clause=_SRC_TABLE1,
            stage=_STAGE,
        )


def terrace_accessible(model: StructuralModel) -> bool:
    """True when a stairs core reaches the roof storey (terrace access)."""
    top = roof_storey_index(model)
    if bool((model.meta or {}).get("terrace_access", False)):
        return True
    for core in model.cores:
        if core.kind == CoreKind.STAIRS and top in (core.storeys or []):
            return True
    return False


def build_live(
    model: StructuralModel,
    live_load_kpa: Optional[Union[float, Mapping[Any, float]]] = None,
) -> Tuple[LoadCase, LoadCase]:
    """The unfactored ("LL", "LLR") cases; see the module docstring.

    `live_load_kpa` optionally replaces the Table 1 imposed load: one kPa value
    for habitable panels, or a mapping by occupancy (Part 2 key or
    model.Occupancy).  It is honoured, traced against the code value it stood in
    for, and disclosed as `W_LIVE_LOAD_OVERRIDDEN`.  Omitted (the default), this
    call is byte for byte the one the code alone produces.
    """
    overrides = resolve_live_override(live_load_kpa)
    replaced = {}  # type: Dict[str, Tuple[float, float]]
    overridden_panels = []  # type: List[str]

    def q_of(key: str) -> float:
        """Imposed load for one Part 2 floor key: the code value, or the override."""
        code_q = is875.part2_imposed(key)
        if key not in overrides:
            return code_q
        replaced[key] = (code_q, overrides[key])
        return overrides[key]

    def src_of(key: str) -> str:
        return (_SRC_OVERRIDE if key in overrides else _SRC_TABLE1) + " (" + key + ")"

    ll = LoadCase(name=CASE_LL, kind=CaseKind.LIVE)
    llr = LoadCase(name=CASE_LLR, kind=CaseKind.ROOF_LIVE)

    fallback_rooms = []  # type: List[str]
    mixed_panels = []  # type: List[str]
    accessible = terrace_accessible(model)
    roof_key = "roof_accessible" if accessible else "roof_non_accessible"
    roof_q = is875.part2_imposed(roof_key)

    for slab in sorted(model.slabs, key=lambda s: (s.storey, s.id)):
        if slab.kind == SlabKind.ROOF:
            llr.area.append(
                AreaLoad(
                    panel_id=slab.id,
                    q_kpa=roof_q,
                    kind=CaseKind.ROOF_LIVE,
                    source=_SRC_TABLE2 + " (" + roof_key + ")",
                )
            )
            continue
        if slab.kind == SlabKind.LANDING:
            if "corridor_stair" in overrides:
                overridden_panels.append(slab.id)
            ll.area.append(
                AreaLoad(
                    panel_id=slab.id,
                    q_kpa=q_of("corridor_stair"),
                    kind=CaseKind.LIVE,
                    source=src_of("corridor_stair"),
                    note="stair landing",
                )
            )
            continue
        rect = polygon_rect(slab.polygon)
        values = {}  # type: Dict[str, float]
        for room in sorted(model.rooms_on(slab.storey), key=lambda r: r.id):
            if _rect_overlap_area(rect, polygon_rect(room.polygon)) <= GEOM_TOL_M:
                continue
            q, key = _room_q_kpa(model, room, fallback_rooms, q_of)
            values[key] = max(values.get(key, 0.0), q)
        if not values:
            fallback_rooms.append(slab.id)
            q = q_of(is875.OCCUPANCY_FALLBACK_KEY)
            key = is875.OCCUPANCY_FALLBACK_KEY
            note = "no room maps onto this panel; fallback occupancy"
        else:
            q = max(values.values())
            keys = sorted(k for k, v in values.items() if v == q)
            key = keys[0]
            note = ""
            if len(set(values.values())) > 1:
                mixed_panels.append(slab.id)
                note = "max of " + ", ".join("%s %.2f" % (k, values[k]) for k in sorted(values))
        if key in overrides:
            overridden_panels.append(slab.id)
        ll.area.append(
            AreaLoad(
                panel_id=slab.id,
                q_kpa=q,
                kind=CaseKind.LIVE,
                source=src_of(key),
                note=note,
            )
        )

    if overrides:
        _disclose_overrides(model, overrides, replaced, overridden_panels)

    if fallback_rooms:
        model.add_warning(
            is875.OCCUPANCY_FALLBACK_CODE,
            "occupancy carried no code imposed load; residential_room used",
            sorted(set(fallback_rooms)),
            stage=_STAGE,
        )
    if mixed_panels:
        # closest registered code: the panel's imposed load was not read off a
        # single occupancy row but resolved conservatively across several
        model.add_warning(
            is875.OCCUPANCY_FALLBACK_CODE,
            "panel(s) span rooms of differing imposed loads; the maximum governs",
            sorted(set(mixed_panels)),
            stage=_STAGE,
        )

    # pitched roof: sloping-roof imposed load on plan, on the eave members
    roof_ctx = pitched_roof_context(model)
    if roof_ctx is not None:
        q_plan = is875.part2_sloped_roof_live(roof_ctx["alpha_deg"])
        loads, bare = pitched_roof_line_loads(
            model,
            roof_ctx,
            q_plan,
            CaseKind.ROOF_LIVE,
            _SRC_SLOPED,
            note="roof %s, alpha %.1f deg" % (roof_ctx["type"], roof_ctx["alpha_deg"]),
        )
        llr.line.extend(loads)
        if bare:
            model.add_warning(
                "E_TRANSFER_REQUIRED",
                "pitched roof eave edge(s) found no supporting member for the imposed load: " + ", ".join(sorted(bare)),
                (),
                stage=_STAGE,
            )

    return (ll, llr)
