"""Core planning: stair and lift cores to shafts, anchors, trimmers and flights.

`plan_cores` runs BEFORE column placement (spec 02 section 6): it decides shaft
mode versus columns mode, builds the ShaftWall panels and the corner anchor
list, and picks each core's door edge. `frame_core_openings` then produces the
per-level framing around every core: trimmer beams on all four opening edges,
the shaft header (coupling) beam over the door edge, landing beams from the
stair landing hint, StairSlab flight records, and the lift pit / machine room
notes the foundations and loads modules consume.

Units: the StructuralModel is SI metres (finding 1); this module quantizes to
integer millimetres privately and re-emits metres. Only `*_mm` names carry
millimetres. Determinism: cores are walked sorted by id, edges in the fixed
order n, e, s, w, and every derived id comes from the core id and geometry.

The door edge of a shaft is an assumption (engine cores carry no doors): the
edge whose outward probe lands inside the storey footprint and closest to the
footprint centre is taken as the entry, ties resolving in edge order. The
assumption is reported in the core notes, never hidden.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..grid import AxisGrid, FrameParams
from ..model import (
    BeamKind,
    Core,
    CoreKind,
    DisclosureLog,
    StructuralModel,
)

# Shaft wall thumb thickness (finding 40): 200 mm, 160 mm floor for very low
# stacks; carried as a prescription, disclosed N_SHAFT_WALL_UNDESIGNED.
SHAFT_WALL_T_MM = 200
SHAFT_WALL_T_LOW_MM = 160

# Landing strip depth at a stair short end, per the spec (1.25 m strip).
LANDING_DEPTH_MM = 1250

# Pre-sizes; design/rcc re-sizes everything downstream.
TRIMMER_WIDTH_MM = 230
TRIMMER_DEPTH_MM = 300
LANDING_WIDTH_MM = 230
LANDING_DEPTH_BEAM_MM = 300
HEADER_WIDTH_MM = 200
HEADER_DEPTH_MM = 450

# Outward probe distance for the door-edge pick.
_PROBE_MM = 300

# Edge order is the determinism anchor: n (y = y0), e (x = x1), s (y = y1),
# w (x = x0), in the y-down plan frame.
EDGE_TAGS = ("n", "e", "s", "w")

_STAGE = "placement.cores"


def _mm(value_m: float) -> int:
    return int(round(float(value_m) * 1000.0))


def _m(value_mm: int) -> float:
    return int(value_mm) / 1000.0


@dataclass
class ShaftWall:
    """One full-height RC shaft panel on a core edge (shaft mode only)."""

    id: str
    core_id: str
    edge: str
    a_mm: Tuple[int, int]
    b_mm: Tuple[int, int]
    t_mm: int
    base_storey: int
    top_storey: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "core_id": self.core_id,
            "edge": self.edge,
            "x1_m": _m(self.a_mm[0]),
            "y1_m": _m(self.a_mm[1]),
            "x2_m": _m(self.b_mm[0]),
            "y2_m": _m(self.b_mm[1]),
            "t_mm": int(self.t_mm),
            "base_storey": int(self.base_storey),
            "top_storey": int(self.top_storey),
        }


@dataclass
class StairSlab:
    """One inclined flight, load-taken as an inclined area load in v1."""

    id: str
    core_id: str
    storey: int
    flight: int
    span_m: float
    width_m: float
    rise_m: float
    incline_deg: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "core_id": self.core_id,
            "storey": int(self.storey),
            "flight": int(self.flight),
            "span_m": round(self.span_m, 4),
            "width_m": round(self.width_m, 4),
            "rise_m": round(self.rise_m, 4),
            "incline_deg": round(self.incline_deg, 2),
        }


@dataclass
class CoreBeam:
    """A core-generated beam segment; frame.py adopts these as always-kept."""

    level: int
    kind: BeamKind
    orient: str  # "h" runs in x, "v" runs in y
    pos_mm: int
    lo_mm: int
    hi_mm: int
    width_mm: int
    depth_mm: int
    core_id: str
    note: str = ""


@dataclass
class CorePlan:
    """What plan_cores decided; place_columns and frame_beams both read it."""

    mode: str = "columns"  # "columns" | "shaft"
    anchors_mm: List[Tuple[int, int, str]] = field(default_factory=list)
    shaft_walls: List[ShaftWall] = field(default_factory=list)
    door_edges: Dict[str, str] = field(default_factory=dict)
    core_rects_mm: Dict[str, Tuple[int, int, int, int]] = field(default_factory=dict)
    core_storeys: Dict[str, List[int]] = field(default_factory=dict)
    notes: List[Dict[str, Any]] = field(default_factory=list)
    log: DisclosureLog = field(default_factory=DisclosureLog)

    def shaft_rects_mm(self) -> List[Tuple[int, int, int, int]]:
        """Rects of cores that became shafts (columns keep off their faces)."""
        if self.mode != "shaft":
            return []
        return [self.core_rects_mm[cid] for cid in sorted(self.core_rects_mm)]


def _core_rect_mm(core: Core) -> Tuple[int, int, int, int]:
    x0 = _mm(core.x_m)
    y0 = _mm(core.y_m)
    x1 = _mm(core.x_m + core.w_m)
    y1 = _mm(core.y_m + core.h_m)
    return (x0, y0, x1, y1)


def _edge_segment(rect: Sequence[int], tag: str) -> Tuple[Tuple[int, int], Tuple[int, int]]:
    x0, y0, x1, y1 = rect
    if tag == "n":
        return ((x0, y0), (x1, y0))
    if tag == "e":
        return ((x1, y0), (x1, y1))
    if tag == "s":
        return ((x0, y1), (x1, y1))
    return ((x0, y0), (x0, y1))


def _edge_probe(rect: Sequence[int], tag: str) -> Tuple[int, int]:
    """Midpoint of the edge pushed outward of the core by the probe distance."""
    x0, y0, x1, y1 = rect
    cx = (x0 + x1) // 2
    cy = (y0 + y1) // 2
    if tag == "n":
        return (cx, y0 - _PROBE_MM)
    if tag == "e":
        return (x1 + _PROBE_MM, cy)
    if tag == "s":
        return (cx, y1 + _PROBE_MM)
    return (x0 - _PROBE_MM, cy)


def _footprint_centre_mm(grid: AxisGrid, storey: int) -> Optional[Tuple[int, int]]:
    footprint = grid.footprints.get(storey)
    if footprint is None:
        return None
    box = footprint.bbox_mm()
    if box is None:
        return None
    return ((box[0] + box[2]) // 2, (box[1] + box[3]) // 2)


def _probe_storey(grid: AxisGrid, storeys: Sequence[int]) -> Optional[int]:
    for storey in sorted(storeys):
        footprint = grid.footprints.get(storey)
        if footprint is not None and not footprint.is_empty():
            return storey
    return None


def _pick_door_edge(grid: AxisGrid, core: Core, rect: Sequence[int], tags: Sequence[str]) -> str:
    """The entry edge: outward probe inside the footprint, nearest the centre.

    Ties resolve in fixed edge order; when no probe lands inside (a core at the
    very boundary), the first tag stands. Deterministic by construction.
    """
    storey = _probe_storey(grid, core.storeys or [0])
    if storey is None:
        return tags[0]
    footprint = grid.footprints.get(storey)
    centre = _footprint_centre_mm(grid, storey)
    if footprint is None or centre is None:
        return tags[0]
    best = None  # type: Optional[Tuple[int, int, str]]
    for order, tag in enumerate(tags):
        px, py = _edge_probe(rect, tag)
        if not footprint.covers(px, py):
            continue
        dist = abs(px - centre[0]) + abs(py - centre[1])
        key = (dist, order, tag)
        if best is None or key < best:
            best = key
    return best[2] if best is not None else tags[0]


def _stair_axis(rect: Sequence[int]) -> Tuple[str, int, int, int]:
    """('x'|'y' long direction, long lo, long hi, short size)."""
    x0, y0, x1, y1 = rect
    if (x1 - x0) >= (y1 - y0):
        return ("x", x0, x1, y1 - y0)
    return ("y", y0, y1, x1 - x0)


def _short_end_tags(rect: Sequence[int]) -> Tuple[str, str]:
    """The two SHORT-end edge tags (low end first) of the stair rect."""
    long_dir = _stair_axis(rect)[0]
    if long_dir == "x":
        return ("w", "e")
    return ("n", "s")


def plan_cores(model: StructuralModel, grid: AxisGrid, params: Optional[FrameParams] = None) -> CorePlan:
    """Decide shaft vs columns mode and prepare anchors / shaft walls.

    Shaft mode (building storeys >= params.shaft_min_storeys) replaces each
    core's boundary walls with ShaftWall panels, one per edge minus the door
    edge; corner columns are omitted (the shaft is the support). Columns mode
    injects the four core corners as mandatory +100 anchors into placement.
    The core's four edge axes are registered in the grid either way (grid.py
    harvests core faces with source `core`).
    """
    params = params if params is not None else FrameParams()
    plan = CorePlan()
    storey_count = len(model.storeys)
    if storey_count == 0:
        storey_count = len(grid.storeys)
    plan.mode = "shaft" if storey_count >= int(params.shaft_min_storeys) else "columns"
    shaft_t = SHAFT_WALL_T_LOW_MM if storey_count <= 2 else SHAFT_WALL_T_MM

    cores = sorted(model.cores, key=lambda c: c.id)
    shaft_note_added = False
    for core in cores:
        rect = _core_rect_mm(core)
        if rect[2] <= rect[0] or rect[3] <= rect[1]:
            continue
        storeys = sorted(core.storeys) if core.storeys else list(grid.storeys)
        plan.core_rects_mm[core.id] = rect
        plan.core_storeys[core.id] = storeys
        door_edge = _pick_door_edge(grid, core, rect, EDGE_TAGS)
        plan.door_edges[core.id] = door_edge
        plan.notes.append(
            {
                "core_id": core.id,
                "storey": storeys[0] if storeys else 0,
                "note": "door_edge_assumed:" + door_edge,
            }
        )
        if plan.mode == "shaft":
            base = storeys[0] if storeys else 0
            top = storeys[-1] if storeys else 0
            for tag in EDGE_TAGS:
                if tag == door_edge:
                    continue
                a, b = _edge_segment(rect, tag)
                plan.shaft_walls.append(
                    ShaftWall(
                        id="shaft-" + core.id + "-" + tag,
                        core_id=core.id,
                        edge=tag,
                        a_mm=a,
                        b_mm=b,
                        t_mm=shaft_t,
                        base_storey=base,
                        top_storey=top,
                    )
                )
            if not shaft_note_added:
                plan.log.add(
                    "N_SHAFT_WALL_UNDESIGNED",
                    "shaft walls carry a %d mm thumb thickness and a 0.25 pct "
                    "two-way steel prescription, not a design" % shaft_t,
                    sorted(w.id for w in plan.shaft_walls),
                    stage=_STAGE,
                )
                shaft_note_added = True
        else:
            x0, y0, x1, y1 = rect
            for cx, cy in ((x0, y0), (x1, y0), (x0, y1), (x1, y1)):
                plan.anchors_mm.append((cx, cy, core.id))
    plan.anchors_mm.sort()
    plan.shaft_walls.sort(key=lambda w: w.id)
    return plan


def _landing_lines(rect: Sequence[int], hint: str, entry_end: str) -> List[Tuple[str, int]]:
    """Landing line stations: (short-end tag, position along the long axis)."""
    long_dir, lo, hi, _short = _stair_axis(rect)
    low_tag, high_tag = _short_end_tags(rect)
    lines = []  # type: List[Tuple[str, int]]
    if hint == "far":
        far_tag = high_tag if entry_end == low_tag else low_tag
        if far_tag == low_tag:
            lines.append((low_tag, lo + LANDING_DEPTH_MM))
        else:
            lines.append((high_tag, hi - LANDING_DEPTH_MM))
    else:  # "both" is the default
        lines.append((low_tag, lo + LANDING_DEPTH_MM))
        lines.append((high_tag, hi - LANDING_DEPTH_MM))
    kept = []  # type: List[Tuple[str, int]]
    for tag, pos in lines:
        if lo < pos < hi:
            kept.append((tag, pos))
    return kept


def frame_core_openings(
    model: StructuralModel,
    grid: AxisGrid,
    core_plan: CorePlan,
    params: Optional[FrameParams] = None,
) -> Tuple[List[CoreBeam], List[StairSlab], List[Dict[str, Any]]]:
    """Per-level framing around every core opening.

    Returns (beams, stair_slabs, notes). Beams: trimmers on every opening edge
    at every level the core exists (the door edge becomes the shaft header
    beam, kind LINTEL, in shaft mode), plus landing beams for stairs from the
    landing hint. Stair flights land as StairSlab records; lifts contribute a
    `lift_pit` note at the base and a `machine_room_load` note at the top.
    """
    params = params if params is not None else FrameParams()
    beams = []  # type: List[CoreBeam]
    slabs = []  # type: List[StairSlab]
    notes = list(core_plan.notes)

    cores = sorted(model.cores, key=lambda c: c.id)
    for core in cores:
        rect = core_plan.core_rects_mm.get(core.id)
        if rect is None:
            continue
        storeys = core_plan.core_storeys.get(core.id, [])
        door_edge = core_plan.door_edges.get(core.id, EDGE_TAGS[0])
        for storey in storeys:
            for tag in EDGE_TAGS:
                (ax, ay), (bx, by) = _edge_segment(rect, tag)
                orient = "h" if ay == by else "v"
                pos = ay if orient == "h" else ax
                lo = min(ax, bx) if orient == "h" else min(ay, by)
                hi = max(ax, bx) if orient == "h" else max(ay, by)
                header = core_plan.mode == "shaft" and tag == door_edge
                beams.append(
                    CoreBeam(
                        level=storey,
                        kind=BeamKind.LINTEL if header else BeamKind.TRIMMER,
                        orient=orient,
                        pos_mm=pos,
                        lo_mm=lo,
                        hi_mm=hi,
                        width_mm=HEADER_WIDTH_MM if header else TRIMMER_WIDTH_MM,
                        depth_mm=HEADER_DEPTH_MM if header else TRIMMER_DEPTH_MM,
                        core_id=core.id,
                        note="shaft_header" if header else "core_trimmer",
                    )
                )

        if core.kind == CoreKind.STAIRS:
            hint = core.stair_landing_hint or "both"
            long_dir, lo, hi, short_mm = _stair_axis(rect)
            low_tag, high_tag = _short_end_tags(rect)
            # entry end: reuse the door-edge probe among the two short ends
            entry_end = _pick_door_edge(grid, core, rect, (low_tag, high_tag))
            for storey in storeys:
                for tag, station in _landing_lines(rect, hint, entry_end):
                    if long_dir == "x":
                        beams.append(
                            CoreBeam(
                                level=storey,
                                kind=BeamKind.LANDING,
                                orient="v",
                                pos_mm=station,
                                lo_mm=rect[1],
                                hi_mm=rect[3],
                                width_mm=LANDING_WIDTH_MM,
                                depth_mm=LANDING_DEPTH_BEAM_MM,
                                core_id=core.id,
                                note="landing_" + tag,
                            )
                        )
                    else:
                        beams.append(
                            CoreBeam(
                                level=storey,
                                kind=BeamKind.LANDING,
                                orient="h",
                                pos_mm=station,
                                lo_mm=rect[0],
                                hi_mm=rect[2],
                                width_mm=LANDING_WIDTH_MM,
                                depth_mm=LANDING_DEPTH_BEAM_MM,
                                core_id=core.id,
                                note="landing_" + tag,
                            )
                        )
            landings = 2 if hint != "far" else 1
            run_mm = max(300, (hi - lo) - landings * LANDING_DEPTH_MM)
            width_m = _m(short_mm) / 2.0
            for storey in storeys:
                record = model.storey(storey)
                height_m = record.height_m if record is not None else 3.0
                rise_m = height_m / 2.0
                run_m = _m(run_mm)
                incline = math.degrees(math.atan2(rise_m, run_m))
                for flight in (1, 2):
                    slabs.append(
                        StairSlab(
                            id="stair-" + core.id + "-s" + str(storey) + "-f" + str(flight),
                            core_id=core.id,
                            storey=storey,
                            flight=flight,
                            span_m=run_m,
                            width_m=width_m,
                            rise_m=rise_m,
                            incline_deg=incline,
                        )
                    )

        if core.kind == CoreKind.LIFT and storeys:
            notes.append({"core_id": core.id, "storey": storeys[0], "note": "lift_pit"})
            notes.append(
                {"core_id": core.id, "storey": storeys[-1], "note": "machine_room_load"}
            )

    beams.sort(key=lambda b: (b.level, b.orient, b.pos_mm, b.lo_mm, b.hi_mm, b.core_id, b.kind.value))
    slabs.sort(key=lambda s: s.id)
    notes = sorted(notes, key=lambda n: (str(n.get("core_id")), int(n.get("storey", 0)), str(n.get("note"))))
    return (beams, slabs, notes)
