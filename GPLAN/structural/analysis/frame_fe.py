"""Frame FE adapter: the backend-agnostic model, and the Pynite escape hatch.

Phase 2 lives here. v1 ships the mapping and refuses the solve, so the package
costs no dependency: NOTHING imports Pynite at module import time, the import
sits inside `PyniteBackend.build`, and a missing dependency comes back as
`BackendUnavailable` naming the numpy pin that blocks it.

    PyNiteFEA 3.x requires Python >= 3.11 and numpy >= 2.4; the engine pins
    numpy==1.26.0. Until either the last numpy 1.x compatible PyNite release is
    verified in CI or the engine bumps numpy, `analyze(method="auto")` falls
    back to takedown + diaphragm with the report line
    `method: takedown (FE backend unavailable)`.

`build_generic_model` is where the structural model becomes nodes, members,
constraints and nodal loads. Backends only translate that description; they
never re-read the StructuralModel, so two backends cannot disagree about the
model.

Wave-3 boundary. Nothing here imports from the `loads` package: lateral cases
arrive as the PLAIN DICTS `loads/seismic.py` and `loads/wind.py` emit,

    {"name": "EQX+", "storey_forces": [{"storey", "fx_kn", "fy_kn", "z_m", "source"}, ...]}

and the wave-5 orchestrator adapts its `LoadCase` objects to that shape (or
hands the dicts straight through; the keys are exactly `loads.StoreyForce`).
`analyze_lateral` is the v1 path: assemble storey shears from those cases and
distribute them with `analysis/diaphragm.py`.

Units are SI: metres, kN; section dimensions are millimetres and carry `_mm`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

try:  # pragma: no cover - typing.Protocol is stdlib from 3.8
    from typing import Protocol
except ImportError:  # pragma: no cover
    Protocol = object  # type: ignore

from ..model import BeamKind, DisclosureLog, StructuralModel, pos_token
from . import diaphragm

STAGE = "analysis.frame_fe"

GENERIC_SCHEMA = "structural.frame_fe.generic/1"

# Spec section 14: refuse past this many nodes rather than run an unbounded solve.
NODE_CAP = 3000

# Spec section 15: envelopes are sampled at 11 stations per member under FE.
FE_STATIONS = 11

PYNITE_UNAVAILABLE_MESSAGE = (
    "PyNiteFEA is not installed, so the FE backend cannot build. PyNiteFEA 3.x requires "
    "Python >= 3.11 and numpy >= 2.4, which conflicts with the engine pin numpy==1.26.0. "
    "Either pin the last PyNite 2.x release verified against numpy 1.26.0 in CI, or bump "
    "numpy engine-wide after the full battery passes. Until then analyze(method='auto') "
    "falls back to takedown + diaphragm."
)

PYNITE_TRANSLATION_MESSAGE = (
    "PyNiteFEA is importable here, but the translation from the generic frame model to "
    "PyNite is phase 2 work and is not written yet; the numpy==1.26.0 pin has to be "
    "resolved and verified in CI before this backend is adopted. Use the generic model "
    "from build_generic_model, or analyze(method='auto') for takedown + diaphragm."
)

_MM = 1000.0
_TINY = 1e-9


class BackendUnavailable(RuntimeError):
    """The FE backend cannot run: dependency missing, or translation not written."""


# ---------------------------------------------------------------------------
# contracts
# ---------------------------------------------------------------------------


@dataclass
class FEResult:
    """What a backend returns; the shape `analysis/__init__.py` reduces."""

    envelopes: Dict[str, Any] = field(default_factory=dict)
    reactions: Dict[str, Any] = field(default_factory=dict)
    drifts: List[Dict[str, Any]] = field(default_factory=list)
    diagnostics: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "envelopes": {key: self.envelopes[key] for key in sorted(self.envelopes)},
            "reactions": {key: self.reactions[key] for key in sorted(self.reactions)},
            "drifts": list(self.drifts),
            "diagnostics": dict(self.diagnostics),
        }


class FrameBackend(Protocol):
    """The whole backend surface: build a model, solve combos, hand back FEResult."""

    name: str

    def build(self, model: StructuralModel, cases: Sequence[Dict[str, Any]]) -> None:
        ...  # pragma: no cover - protocol

    def solve(self, combos: Sequence[Dict[str, Any]]) -> FEResult:
        ...  # pragma: no cover - protocol


@dataclass(frozen=True)
class GenericModelParams:
    """Mapping choices the description records so a backend cannot invent them."""

    node_cap: int = NODE_CAP
    base_fixity: str = "fixed"  # fixed | pinned
    rigid_diaphragm: bool = True
    release_secondary_ends: bool = True
    stations: int = FE_STATIONS
    p_delta: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_cap": int(self.node_cap),
            "base_fixity": str(self.base_fixity),
            "rigid_diaphragm": bool(self.rigid_diaphragm),
            "release_secondary_ends": bool(self.release_secondary_ends),
            "stations": int(self.stations),
            "p_delta": bool(self.p_delta),
        }


# ---------------------------------------------------------------------------
# generic model
# ---------------------------------------------------------------------------


def _mm_key(value_m: float) -> int:
    return int(round(float(value_m) * _MM))


def _node_id(level: int, x_m: float, y_m: float) -> str:
    return "nd-L" + str(int(level)) + "-@" + pos_token(x_m) + "x" + pos_token(y_m)


def _levels(model: StructuralModel, storeys: Sequence[int]) -> List[Dict[str, Any]]:
    """Level 0 is the base; level k is the top of storey k - 1."""
    base = model.storey(storeys[0])
    levels = [
        {
            "index": 0,
            "z_m": float(base.bottom_z_m),
            "storey": None,
            "base": True,
        }
    ]
    for offset, storey in enumerate(storeys):
        record = model.storey(storey)
        levels.append(
            {
                "index": offset + 1,
                "z_m": float(record.bottom_z_m) + float(record.height_m),
                "storey": int(storey),
                "base": False,
            }
        )
    return levels


def _positions(model: StructuralModel, storeys: Sequence[int]) -> Tuple[List[float], List[float]]:
    """Grid line positions in X and in Y, axes first, member ends folded in."""
    xs = {}  # type: Dict[int, float]
    ys = {}  # type: Dict[int, float]

    def add(table: Dict[int, float], value: float) -> None:
        table.setdefault(_mm_key(value), float(value))

    for axis in model.axes:
        if str(getattr(axis.dir, "value", axis.dir)) == "x":
            add(xs, axis.pos_m)
        else:
            add(ys, axis.pos_m)
    for storey in storeys:
        for column in model.columns_on(storey):
            add(xs, column.x_m)
            add(ys, column.y_m)
        for beam in model.beams_on(storey):
            add(xs, beam.a[0])
            add(xs, beam.b[0])
            add(ys, beam.a[1])
            add(ys, beam.b[1])
    return (
        [xs[key] for key in sorted(xs)],
        [ys[key] for key in sorted(ys)],
    )


def _section(width_m: Optional[float], depth_m: Optional[float]) -> Dict[str, Any]:
    return {
        "b_mm": None if width_m is None else int(round(float(width_m) * _MM)),
        "d_mm": None if depth_m is None else int(round(float(depth_m) * _MM)),
    }


def build_generic_model(
    model: StructuralModel,
    cases: Sequence[Dict[str, Any]] = (),
    params: Optional[GenericModelParams] = None,
    log: Optional[DisclosureLog] = None,
) -> Dict[str, Any]:
    """The backend-agnostic node, member, constraint and load description.

    Nodes sit at grid-axis intersections on every level plus the base; members
    are the PLACED columns and beams with their sections; secondary beam ends
    are moment released; each level carries a rigid-diaphragm master node when
    the backend supports one. Slab gravity is not meshed: the takedown has
    already distributed it to the beams, so there are no shells here.

    Past `params.node_cap` nodes the description comes back with
    `refused: True` and an empty node list, disclosed, and the caller falls
    back to takedown + diaphragm.
    """
    settings = params or GenericModelParams()
    ladder = DisclosureLog()
    storeys = sorted({record.index for record in model.storeys})
    if not storeys:
        raise ValueError("the model carries no storey, so no frame can be built")

    levels = _levels(model, storeys)
    xs, ys = _positions(model, storeys)
    masters = len(levels) - 1 if settings.rigid_diaphragm else 0
    candidates = len(xs) * len(ys) * len(levels) + masters

    description = {
        "schema": GENERIC_SCHEMA,
        "units": {"length": "m", "force": "kN", "moment": "kN m", "section": "mm"},
        "params": settings.to_dict(),
        "levels": levels,
        "grid": {"x_m": list(xs), "y_m": list(ys)},
        "refused": False,
        "refusal_reason": None,
        "nodes": [],
        "members": [],
        "constraints": [],
        "loads": [],
        "cases": [str(case.get("name", "")) for case in cases],
        "assumptions": [
            "nodes at grid-axis intersections per level, plus the bases",
            "bases " + settings.base_fixity,
            "slab gravity is pre-distributed to the beams by the takedown; no shells",
            "secondary beam ends are moment released"
            if settings.release_secondary_ends
            else "no member end releases",
            "rigid diaphragm per level via a master node; a backend without constraints "
            "emulates it with a stiff in-plane bracing lattice, which it must disclose"
            if settings.rigid_diaphragm
            else "no diaphragm constraint",
            "linear static, P-delta off in v1",
            "lateral cases are applied at the diaphragm masters; the design eccentricity "
            "belongs to the case and is applied by the backend",
        ],
        "diagnostics": {
            "candidate_nodes": candidates,
            "grid_x": len(xs),
            "grid_y": len(ys),
            "levels": len(levels),
        },
    }

    if candidates > settings.node_cap:
        reason = (
            "the grid would need "
            + str(candidates)
            + " nodes, past the "
            + str(settings.node_cap)
            + " node cap; the FE model is refused and the analysis falls back to "
            + "takedown + diaphragm"
        )
        description["refused"] = True
        description["refusal_reason"] = reason
        ladder.add("W_COARSE_ITER", reason, clause=None, stage=STAGE)
        description["disclosures"] = ladder.to_dict()
        if log is not None:
            log.extend(ladder.entries)
        return description

    level_of_storey = {
        int(level["storey"]): int(level["index"]) for level in levels if level["storey"] is not None
    }
    known_x = {_mm_key(value): value for value in xs}
    known_y = {_mm_key(value): value for value in ys}

    nodes = {}  # type: Dict[str, Dict[str, Any]]
    for level in levels:
        for x in xs:
            for y in ys:
                node_id = _node_id(level["index"], x, y)
                nodes[node_id] = {
                    "id": node_id,
                    "x_m": x,
                    "y_m": y,
                    "z_m": level["z_m"],
                    "level": level["index"],
                    "support": settings.base_fixity if level["base"] else None,
                    "master": False,
                    "used": False,
                }

    members = []  # type: List[Dict[str, Any]]
    unmapped = []  # type: List[str]

    def node_at(level_index: int, x: float, y: float) -> Optional[Dict[str, Any]]:
        if _mm_key(x) not in known_x or _mm_key(y) not in known_y:
            return None
        return nodes.get(_node_id(level_index, known_x[_mm_key(x)], known_y[_mm_key(y)]))

    for storey in storeys:
        top = level_of_storey[storey]
        for column in sorted(model.columns_on(storey), key=lambda c: c.id):
            lower = node_at(top - 1, column.x_m, column.y_m)
            upper = node_at(top, column.x_m, column.y_m)
            if lower is None or upper is None:
                unmapped.append(column.id)
                continue
            lower["used"] = True
            upper["used"] = True
            members.append(
                {
                    "id": column.id,
                    "type": "column",
                    "storey": int(storey),
                    "i": lower["id"],
                    "j": upper["id"],
                    "material": "rc",
                    "section": _section(column.width_m, column.depth_m),
                    "rot_deg": int(getattr(column, "rot", 0) or 0),
                    "releases": {"i": [], "j": []},
                }
            )
        for beam in sorted(model.beams_on(storey), key=lambda b: b.id):
            start = node_at(top, beam.a[0], beam.a[1])
            end = node_at(top, beam.b[0], beam.b[1])
            if start is None or end is None or start["id"] == end["id"]:
                unmapped.append(beam.id)
                continue
            start["used"] = True
            end["used"] = True
            secondary = beam.kind == BeamKind.SECONDARY and settings.release_secondary_ends
            releases = ["My", "Mz"] if secondary else []
            members.append(
                {
                    "id": beam.id,
                    "type": "beam",
                    "storey": int(storey),
                    "i": start["id"],
                    "j": end["id"],
                    "material": "rc",
                    "section": _section(beam.width_m, beam.depth_m),
                    "kind": str(getattr(beam.kind, "value", beam.kind)),
                    "releases": {"i": list(releases), "j": list(releases)},
                }
            )

    kept = [node for node in nodes.values() if node["used"]]
    kept.sort(key=lambda node: (node["level"], _mm_key(node["x_m"]), _mm_key(node["y_m"])))

    constraints = []  # type: List[Dict[str, Any]]
    if settings.rigid_diaphragm:
        for level in levels:
            if level["base"]:
                continue
            slaves = [node["id"] for node in kept if node["level"] == level["index"]]
            if not slaves:
                continue
            centre_x = sum(node["x_m"] for node in kept if node["level"] == level["index"]) / len(slaves)
            centre_y = sum(node["y_m"] for node in kept if node["level"] == level["index"]) / len(slaves)
            master_id = "nd-M" + str(level["index"])
            kept.append(
                {
                    "id": master_id,
                    "x_m": centre_x,
                    "y_m": centre_y,
                    "z_m": level["z_m"],
                    "level": level["index"],
                    "support": None,
                    "master": True,
                    "used": True,
                }
            )
            constraints.append(
                {
                    "kind": "rigid_diaphragm",
                    "level": level["index"],
                    "storey": level["storey"],
                    "master": master_id,
                    "slaves": slaves,
                }
            )

    loads = []  # type: List[Dict[str, Any]]
    for case in cases:
        name = str(case.get("name", ""))
        for force in case.get("storey_forces", []):
            storey = int(force["storey"])
            level_index = level_of_storey.get(storey)
            if level_index is None:
                unmapped.append(name + "@storey" + str(storey))
                continue
            target = "nd-M" + str(level_index) if settings.rigid_diaphragm else None
            loads.append(
                {
                    "case": name,
                    "level": level_index,
                    "storey": storey,
                    "node": target,
                    "fx_kn": float(force.get("fx_kn", 0.0) or 0.0),
                    "fy_kn": float(force.get("fy_kn", 0.0) or 0.0),
                    "z_m": float(force.get("z_m", 0.0) or 0.0),
                    "source": str(force.get("source", "")),
                }
            )

    if len(kept) > settings.node_cap:
        reason = (
            "the frame needs "
            + str(len(kept))
            + " nodes, past the "
            + str(settings.node_cap)
            + " node cap; the FE model is refused and the analysis falls back to "
            + "takedown + diaphragm"
        )
        description["refused"] = True
        description["refusal_reason"] = reason
        ladder.add("W_COARSE_ITER", reason, clause=None, stage=STAGE)
        description["disclosures"] = ladder.to_dict()
        if log is not None:
            log.extend(ladder.entries)
        return description

    if unmapped:
        ladder.add(
            "W_CLIENT_GRID_DIFFERS",
            "no grid node exists under "
            + str(len(unmapped))
            + " placed element(s): "
            + ", ".join(sorted(set(unmapped))[:8])
            + "; they were left out of the FE model",
            element_ids=sorted(set(unmapped)),
            stage=STAGE,
        )

    kept.sort(key=lambda node: (node["level"], node["master"], _mm_key(node["x_m"]), _mm_key(node["y_m"])))
    for node in kept:
        node.pop("used", None)
    description["nodes"] = kept
    description["members"] = members
    description["constraints"] = constraints
    description["loads"] = loads
    description["diagnostics"].update(
        {
            "nodes": len(kept),
            "members": len(members),
            "columns": sum(1 for member in members if member["type"] == "column"),
            "beams": sum(1 for member in members if member["type"] == "beam"),
            "constraints": len(constraints),
            "loads": len(loads),
            "unmapped_elements": sorted(set(unmapped)),
        }
    )
    description["disclosures"] = ladder.to_dict()
    if log is not None:
        log.extend(ladder.entries)
    return description


# ---------------------------------------------------------------------------
# backends
# ---------------------------------------------------------------------------


def _import_pynite() -> Any:
    """Import Pynite lazily. Patched in tests to exercise the refusal path."""
    import Pynite  # noqa: F401  (import inside the function on purpose)

    return Pynite


class PyniteBackend:
    """PyNiteFEA backend, deferred to phase 2 behind the numpy pin.

    `build` imports Pynite lazily and raises `BackendUnavailable` when the
    dependency is missing, with the message that names the numpy pin. Nothing
    at module import time touches Pynite, so shipping this file costs no
    dependency.
    """

    name = "pynite"

    def __init__(self, params: Optional[GenericModelParams] = None) -> None:
        self.params = params or GenericModelParams()
        self.generic = None  # type: Optional[Dict[str, Any]]
        self._pynite = None  # type: Any

    def build(self, model: StructuralModel, cases: Sequence[Dict[str, Any]] = ()) -> None:
        try:
            self._pynite = _import_pynite()
        except ImportError as exc:
            raise BackendUnavailable(PYNITE_UNAVAILABLE_MESSAGE) from exc
        self.generic = build_generic_model(model, cases, self.params)
        raise BackendUnavailable(PYNITE_TRANSLATION_MESSAGE)

    def solve(self, combos: Sequence[Dict[str, Any]] = ()) -> FEResult:
        raise BackendUnavailable(PYNITE_TRANSLATION_MESSAGE)


# ---------------------------------------------------------------------------
# v1 path
# ---------------------------------------------------------------------------


def assemble_storey_shears(cases: Sequence[Dict[str, Any]]) -> Dict[str, Dict[int, float]]:
    """Envelope of storey shear magnitudes over a set of lateral cases.

    The plus and minus case of one axis give the same magnitudes, so the
    envelope over `[EQX+, EQX-, EQY+, EQY-]` is simply the per-axis
    distribution; mixing wind and seismic cases takes the larger of the two,
    which is what a lateral envelope means (they are never combined).
    """
    out = {"x": {}, "y": {}}  # type: Dict[str, Dict[int, float]]
    for case in cases:
        shears = diaphragm.storey_shears_from_case(case)
        for direction in ("x", "y"):
            for storey, value in shears[direction].items():
                current = out[direction].get(storey)
                if current is None or value > current:
                    out[direction][storey] = value
    return {direction: dict(sorted(table.items())) for direction, table in out.items()}


def analyze_lateral(
    model: StructuralModel,
    cases: Sequence[Dict[str, Any]],
    ctx: Optional[diaphragm.LateralContext] = None,
    centres_of_mass: Optional[Dict[int, Tuple[float, float]]] = None,
    log: Optional[DisclosureLog] = None,
    trace: Optional[List[Any]] = None,
) -> diaphragm.LateralResult:
    """v1 lateral analysis: cases -> storey shears -> rigid-diaphragm shares.

    This is what `analyze(method="auto")` calls while the FE backend is
    unavailable; the report line stays `method: takedown (FE backend
    unavailable)`.
    """
    shears = assemble_storey_shears(cases)
    return diaphragm.run(
        model,
        shears,
        ctx=ctx,
        centres_of_mass=centres_of_mass,
        log=log,
        trace=trace,
    )
