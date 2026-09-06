"""The four public entry points of the structural module, and nothing else.

Spec 08 sections 2 to 5, engine side. `run_options`, `run_layout`, `run_design`
and `run_check` are the only public surface (finding 17): `place` and `analyze`
are internal steps these functions sequence, and the Flask bridge and the Django
views call these four through `GPLAN.api.Documents` without adding logic of
their own.

Four rules shape this module.

Finding 18, the fixed sequence. `run_design` is the single orchestrator and its
order is not negotiable: adapt, validate, place, load model, gravity takedown,
`layout_foundations`, diaphragm, member design, at most ONE bounded referral
re-pass, quantities, report. `run_layout` runs the same adapt/validate/place
prefix, so layout and design never disagree on geometry, and it stops there:
a layout response carries NO sized footing, only unsized markers at the column
stacks, because a footing is sized from a takedown that layout never runs.

Finding 19, one re-pass. Design may refer work back to placement
(`add_secondary_beams`, `confined_masonry_conversion`). Those referrals are
applied once, the loads and the design re-run once, and then the loop STOPS:
whatever is still referred is disclosed as a warning rather than chased.

Finding 27, no local system rule. `params.system == "auto"` delegates the whole
decision to `placement.masonry.choose_system`, and the response carries that
decision's trace and refusal verbatim. This module contains no second rule.
`_Placement.system` is where the DELIVERED system is authoritative: what
`choose_system` resolved, corrected by whichever placer actually ran. `_place`
writes it into `model.system` on BOTH branches, the response echoes it, and
`report.py` reads it from the placement block, so an escalated run cannot be
reported over the system that was merely requested.

Finding 30, one soil table. `SOIL_ALIASES` and `resolve_soil` live here and
nowhere else; the resolved `{type, sbc_kpa, soft, founding_depth_m}` block feeds
the seismic context, `layout_foundations`, the footing designer and the
earthwork take-off from the one place.

Finding 29, the disclaimer. Every response of every entry point, including a
refusal and a validation failure, carries the verbatim notice through
`report.with_disclaimer`, which returns a mapping that cannot lose the key.

The size regime (`output.detail`, spec 07 section "size discipline"). A design
response crosses Celery and Redis and then the wire to a browser, so it is
budgeted. Content falls in three tiers and the tier decides what a level may do
to it:

  TIER 1, whole at every level, because a reader acts on it: the DISCLAIMER,
  EVERY Disclosure on the entry ladder (`errors` + `warnings`), `options_echo`,
  `placement`, `layout_score` / `report.layout_metrics`,
  the model's geometry slots, the take-off class rows and their bases, the whole
  BOQ with its subtotals and totals, `design.failed`, `design.coverage`, and the
  section, reinforcement, status, utilization and GOVERNING CHECK of every
  designed element.

  TIER 2, whole at every level, because it is what a user must see: the entire
  DesignResult of every BLOCKED (named by an ERROR) and every FAILED element,
  every check row and note included, and their element cards.

  TIER 3, elided at `compact` (the default) and whole at `full`: the non-governing
  check rows, notes, bars, stirrups and resize history of a passing member; a
  passing member's non-masonry extra detail blocks; `report.disclosures` (ERROR rows stay,
   while the entry ladder remains whole); the
  per-element unfactored load rows; the takedown's force envelopes, beam runs and
  column loads; the per-element concrete volumes and the per-bar schedule; the
  per-pier lateral distribution; the cards of members that are neither blocked nor
  failed. `DETAIL_POLICY` lists every one of them with the key that names where
  the whole block lives, `run_options()` publishes that table, and every design
   entry echoes the resolved level in `entry["detail"]`. `DETAIL_POLICY` names
   every elided block and `full` restores it; bulk blocks also carry their
   applicable `_ref` or `_total` marker.

`output.trace: true` resolves the level to `full` unless the caller states one,
because asking for the working and being handed a summary is a trap. Nothing a
level changes is a number: `full` and `compact` differ only in how much of the
same run they show.

Determinism (the backend's Redis dedup depends on it): sorted iteration
throughout, no RNG, and no wall clock inside a computed value. `meta.generated_at`
is None unless a caller injects a timestamp through `output.generated_at`, and
`input_ref.hash` is a sha256 over the canonical payload so two identical
requests hash identically.

Adaptations made here rather than in a sibling module, all deliberate:
  - `design/rcc/run_rcc_design` calls `design_slab(load, panel)` and
    `design_footing(loads, geom)` with the arguments the other way round from
    the shipped signatures `design_slab(panel, load)` and
    `design_footing(PadGeometry, FootingLoads, soil, ctx)`. `_design_members`
    below dispatches with the documented signatures instead, still through the
    finding 20 converters, and never edits the sibling. The one piece of the
    sibling it DOES call is `strip_geometry_from_model`, so a wall strip is read
    off the model in exactly one place and the two routes cannot drift.
  - `TakedownResult.footing_loads` hands `{id: {p_dl_kn, p_ll_reduced_kn}}` and
    `{id: {n_dl_kn_m, n_ll_kn_m}}`; `layout_foundations` documents plain floats.
    `_foundation_loads` sums the components into the service values it wants.
  - `loads.seismic.build_seismic` needs the storey weight ledger, which only the
    takedown produces. The gravity takedown therefore runs once to weigh the
    storeys before the lateral cases exist, and once more over the full
    combination roster; `analysis.storey_weight_source` says so on the wire.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import os
from typing import Any, Dict, List, Optional, Sequence, Tuple

from . import quantities as Q
from . import report as R
from .codes import is1893
from .data._loader import available_tables, data_path, load_yaml
from .grid import FrameParams, HOUSING_COLUMN_VARIANTS, _resolve_pos_mm, extract_axes
from .loads import (
    CASE_DL,
    CASE_LL,
    CASE_LLR,
    CaseKind,
    LoadCase,
    LoadModel,
    StoreyForce,
)
from .loads import combos as _combos
from .model import (
    REGISTRY,
    AxisDir,
    Disclosure,
    DisclosureLog,
    Footing,
    FootingKind,
    RC_SLAB_MIN_THICKNESS_MM,
    Severity,
    StructuralModel,
    System,
    ft_to_m,
    m_to_ft,
    make_disclosure,
    polygon_rect,
)
from .placement import foundations as _foundations
from .placement import frame as _frame
from .placement import masonry as _masonry
from .placement.housing_variants import assess as _assess_housing_layout
from .schema import (
    STRUCTURAL_SCHEMA_MAJOR,
    STRUCTURAL_SCHEMA_VERSION,
    units_block,
    validate_wire,
)

__all__ = [
    "STRUCTURAL_SCHEMA_VERSION",
    "STRUCTURAL_SCHEMA_MAJOR",
    "SOURCES",
    "REQUEST_SYSTEMS",
    "WIRE_SYSTEMS",
    "CODE_PROFILES",
    "ANALYSIS_MODES",
    "PLACEMENT_STRATEGIES",
    "SCOPES",
    "DUCTILITY",
    "SEISMIC_ZONES",
    "SOIL_TYPES",
    "SOIL_ALIASES",
    "LIMITS",
    "MAX_STOREYS_RC",
    "MAX_STOREYS_MASONRY",
    "MAX_STOREYS_MASONRY_ZONE_V",
    "MAX_ROOMS_PER_FLOOR",
    "MAX_CANTILEVER_M",
    "REFUSE_CANTILEVER_M",
    "MAX_BODY_BYTES",
    "REFERRAL_RE_PASSES",
    "DETAIL_LEVELS",
    "DETAIL_COMPACT",
    "DETAIL_FULL",
    "DEFAULT_DETAIL",
    "DETAIL_POLICY",
    "StructuralValidationError",
    "canonical_json",
    "payload_hash",
    "resolve_soil",
    "structural_fingerprint",
    "run_options",
    "run_layout",
    "run_design",
    "run_check",
]


# ---------------------------------------------------------------------------
# frozen vocabulary, every entry generated from a shipped constant (finding 42)
# ---------------------------------------------------------------------------

#: Request discriminators. "model" is the check source (spec 3.3).
SOURCES = ("plan", "building", "housing", "model")

#: Systems a request may ASK for (finding 26); "mixed" is an internal outcome.
REQUEST_SYSTEMS = ("auto",) + tuple(_masonry.REQUESTABLE_SYSTEMS)

#: Systems that may appear on the wire as the system actually used.
WIRE_SYSTEMS = tuple(member.value for member in System)

CODE_PROFILES = ("IS",)

# ``code_complete`` preserves the existing lateral-load pipeline.  The
# deliberately narrower ``gravity_only`` mode exists for like-for-like option
# screening; it is never described as a code-complete design in the response.
ANALYSIS_MODES = ("code_complete", "gravity_only")

# The original exhaustive architectural-axis placement remains the default for
# compatibility.  ``economy_grid`` regularizes those candidates before the
# frame is generated and is intended to be compared through a full design and
# quantity pass, not trusted on its placement score alone.
PLACEMENT_STRATEGIES = ("wall_aligned", "economy_grid")

SCOPES = ("placement", "full")

#: Ductility classes; the resolved default is OMRF up to zone III (finding 41).
DUCTILITY = ("OMRF", "SMRF")

_SEISMIC_TABLE = load_yaml("is1893")
_SOIL_TABLE = load_yaml("soil_defaults")

#: Zone -> Z, straight out of data/is1893.yaml Table 3.
SEISMIC_ZONES = dict(
    (str(key), float(value))
    for key, value in sorted(_SEISMIC_TABLE["zone_factor"]["values"].items())
)

#: IS 1893 Cl 6.4.2.1 soil types, from data/soil_defaults.yaml.
SOIL_TYPES = tuple(sorted(str(key) for key in _SOIL_TABLE["types"]))

#: The ONE soil mapping table (finding 30). hard/medium/soft are the words the
#: HTTP layer accepts; I / II / III are the code types every consumer reads.
SOIL_ALIASES = dict(
    (str(key), str(value)) for key, value in sorted(_SOIL_TABLE["aliases"].items())
)

#: IS 1893 Table 8 importance categories.
IMPORTANCE_CATEGORIES = tuple(
    sorted(str(key) for key in _SEISMIC_TABLE["importance_factor"]["values"])
)

_FRAME_DEFAULTS = FrameParams()

#: Validation caps. Each is the shipped constant, never a second literal.
MAX_STOREYS_RC = 12
MAX_STOREYS_MASONRY = max(int(v) for v in _masonry.MAX_STOREYS_BY_CATEGORY.values())
MAX_STOREYS_MASONRY_ZONE_V = int(_masonry.MAX_STOREYS_BY_CATEGORY["E"])
MAX_ROOMS_PER_FLOOR = 60
MAX_HOUSING_FLOORS = 4
MAX_CANTILEVER_M = float(_FRAME_DEFAULTS.cantilever_cap)
REFUSE_CANTILEVER_M = float(_frame.REFUSE_CANTILEVER_M)
MIN_SPAN_M = float(_FRAME_DEFAULTS.min_span)
MAX_SPAN_M = float(_FRAME_DEFAULTS.max_primary_span)
HARD_MAX_SPAN_M = 7.5
MAX_BODY_BYTES = 2000000

#: Finding 19: exactly one bounded referral re-pass, never two.
REFERRAL_RE_PASSES = 1

#: How much of the working a design response carries (`output.detail`, or
#: `params.detail`). See "The size regime" in the module docstring: `compact`
#: is the default and elides the bulk blocks, `full` restores every one of them.
#: Blocked and failed elements are FULL at both levels, always.
DETAIL_LEVELS = ("compact", "full")
DETAIL_COMPACT = "compact"
DETAIL_FULL = "full"
DEFAULT_DETAIL = DETAIL_COMPACT

#: What `compact` elides, block by block, with the sibling key that names where
#: the whole thing lives. This table IS the documentation: it is published on
#: `run_options` and echoed on every design response as `entry["detail"]`, so a
#: client never has to guess why a block is short.
DETAIL_POLICY = (
    {
        "block": "structural_model.design[]",
        "elided": [
            "bars", "materials", "notes", "referrals", "resize_history", "stirrups", "trace",
            "ductile, flexure, serviceability and shear extras for beams",
            "deflection_route, edges, method and slab_mode extras for slabs",
            "si extras for footings",
            "every check row but the governing one",
            "the derived numbers in `section` (effective depths, clear spans, panel "
            "spans, bearing pressures, table cases)",
        ],
        "kept": [
            "element_id", "element_type", "status",
            "section (the dimensions b_mm, D_mm, thickness_mm, cover_mm and the plan "
            "sizes, plus every descriptor: wall_id, support, kind, two_way)",
            "reinforcement (the display string)",
            "governing_check", "checks (the governing row, whole)", "utilization_max",
            "checks_total", "disclosure_codes", "warnings",
            "masonry and prescription extras for masonry walls",
        ],
        "reason": "a passing member's full working is roughly 8 kB; the governing "
                  "check, the section and the reinforcement string are what a reader acts on",
    },
    {
        "block": "structural_model.design[] of a BLOCKED or FAILED element",
        "elided": [],
        "kept": ["everything"],
        "reason": "a member a user must act on is never abbreviated, at any level",
    },
    {
        "block": "structural_model.loads.cases[].line / .area / .point",
        "elided": ["the per-element unfactored load rows"],
        "kept": ["every case name, kind, storey and row count", "combos"],
        "reason": "the takedown consumed them; the response reports what they produced",
    },
    {
        "block": "structural_model.analysis",
        "elided": ["envelopes", "beam_runs", "column_loads", "footing_loads", "disclosures"],
        "kept": ["wall_stresses", "storey_ledger", "conservation", "the per-block counts"],
        "reason": "the force envelopes are the designer's input, not the reader's; the "
                  "footing loads are on analysis.foundations and the ladder they raised "
                  "is on `warnings`, both in full",
    },
    {
        "block": "analysis.combos",
        "elided": ["the combination definitions, which become a pointer"],
        "kept": ["combos_used (the roster)", "structural_model.loads.combos, verbatim"],
        "reason": "two identical copies of one block is duplication, not disclosure",
    },
    {
        "block": "structural_model.quantities.takeoff",
        "elided": [
            "concrete_by_element", "earthwork.footings",
            "the element_ids roll-call on each concrete class row",
        ],
        "kept": [
            "every class total and subtotal, every count, every basis string, "
            "the totals block",
        ],
        "reason": "the BOQ is priced off the class rows, which stay whole; the ids "
                  "they name are the model's own",
    },
    {
        "block": "structural_model.quantities.bbs.items",
        "elided": ["the per-bar rows"],
        "kept": ["mass_by_dia", "mass_by_class", "total_kg", "total_with_wastage_kg"],
        "reason": "spec 07 size discipline; the aggregates are the priced numbers",
    },
    {
        "block": "structural_model.warnings",
        "elided": ["the WARNING and NOTE entries"],
        "kept": ["every ERROR entry", "warnings_ref to the entry-level ladder"],
        "reason": "the whole ladder rides once, in full, on `errors` and `warnings`",
    },
    {
        "block": "analysis.lateral",
        "elided": ["storeys[].elements", "base_forces", "disclosures"],
        "kept": [
            "every storey scalar (shear, drift, eccentricity, torsion verdict)",
            "overturning", "assumptions", "analysis.storey_shears",
        ],
        "reason": "the per-pier and per-column distribution is an intermediate; its "
                  "ladder is on `warnings` in full",
    },
    {
        "block": "report.element_cards",
        "elided": ["every card"],
        "kept": [
            "element_cards_total", "cards_elided", "element_cards_ref",
            "report.blocked_elements, which names every blocked and failed element "
            "with its codes and its reason",
        ],
        "reason": "a card is a rendered view of a design row that rides in the same "
                  "response, field for field; `element_cards_ref` names it",
    },
    {
        "block": "report.bbs.items / report.disclosures",
        "elided": ["the per-bar rows", "WARNING and NOTE report disclosures at compact"],
        "kept": [
            "every schedule aggregate", "blocked_mass_kg", "every ERROR disclosure",
            "disclosures_total, disclosures_ref and disclosures_elided",
        ],
        "reason": "the entry-level errors and warnings carry the whole ladder once; compact report disclosures keep ERROR rows and point there",
    },
    {
        "block": "design.failed[]",
        "elided": ["the warning texts of a failed member"],
        "kept": [
            "element_id", "element_type", "check", "utilization", "warnings_total",
            "failed_warnings_ref, said once for the block",
            "the whole warning list on the member's own design row, which is never "
            "abbreviated, and on the ladder",
        ],
        "reason": "the same sentences ride three times otherwise",
    },
    {
        "block": "design.referrals",
        "elided": ["the per-element rows of an action this orchestrator cannot act on"],
        "kept": ["every actionable referral in full", "a count and the element ids of the rest"],
        "reason": "an unactionable referral is a note about a class of members, not a task",
    },
)

#: Referral actions this orchestrator can act on; everything else is disclosed.
ACTIONABLE_REFERRALS = ("add_secondary_beams", "confined_masonry_conversion")

#: Plan/building adapter default, feet. Housing owns its distinct 10.4 ft
#: default; an omitted request value is left to the selected adapter.
DEFAULT_STOREY_HEIGHT_FT = 10.0

#: Element classes the v1 design layer owns, per system family.
_FRAME_DESIGN_CLASSES = ("beam", "column", "slab", "stair", "footing")
_MASONRY_DESIGN_CLASSES = ("wall",)

#: Every class `design.coverage` reports, owned or not. Lintels and bands are
#: placed and quantified with no v1 designer, and the coverage row says so.
_COVERAGE_CLASSES = ("band", "beam", "column", "footing", "lintel", "slab", "stair", "wall")

_MASONRY_SYSTEMS = (System.LOAD_BEARING_MASONRY.value, System.CONFINED_MASONRY.value)

_STAGE = "api"

LIMITS = {
    "max_storeys_rc": MAX_STOREYS_RC,
    "max_storeys_masonry": MAX_STOREYS_MASONRY,
    "max_storeys_masonry_zone_v": MAX_STOREYS_MASONRY_ZONE_V,
    "max_rooms_per_floor": MAX_ROOMS_PER_FLOOR,
    "max_housing_floors": MAX_HOUSING_FLOORS,
    "max_cantilever_m": MAX_CANTILEVER_M,
    "refuse_cantilever_m": REFUSE_CANTILEVER_M,
    "min_span_m": MIN_SPAN_M,
    "max_span_m": MAX_SPAN_M,
    "hard_max_span_m": HARD_MAX_SPAN_M,
    "max_body_bytes": MAX_BODY_BYTES,
    "referral_re_passes": REFERRAL_RE_PASSES,
}


# ---------------------------------------------------------------------------
# the refusal type
# ---------------------------------------------------------------------------


class StructuralValidationError(ValueError):
    """A request this engine will not run, naming the field that is wrong.

    Django maps it to 400 with the standard error envelope and the bridge to
    400 `{message}`; both read `field` and `message`. Anything softer than a
    refusal belongs on the disclosure ladder instead.
    """

    def __init__(self, field: str, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        super(StructuralValidationError, self).__init__(str(field) + ": " + str(message))
        self.field = str(field)
        self.message = str(message)
        self.details = dict(details or {})

    def to_dict(self) -> Dict[str, Any]:
        return {"field": self.field, "message": self.message, "details": dict(self.details)}


# ---------------------------------------------------------------------------
# small readers
# ---------------------------------------------------------------------------


def _mapping(value: Any, field: str) -> Dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    raise StructuralValidationError(field, "must be an object, got " + type(value).__name__)


def _num(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return float(default)
    if out != out or out in (float("inf"), float("-inf")):
        return float(default)
    return out


def _plain(value: Any) -> Any:
    """A JSON-safe copy: enums to their values, floats normalized, keys sorted."""
    if isinstance(value, float):
        return round(value, 9) + 0.0
    if isinstance(value, bool) or value is None or isinstance(value, (int, str)):
        return value
    if isinstance(value, dict):
        return dict((str(key), _plain(value[key])) for key in sorted(value, key=str))
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    inner = getattr(value, "value", None)
    if isinstance(inner, (str, int, float)):
        return inner
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return _plain(to_dict())
    return str(value)


def canonical_json(payload: Any) -> str:
    """The request as one canonical string: sorted keys, no incidental spacing."""
    return json.dumps(_plain(payload), sort_keys=True, separators=(",", ":"), default=str)


def payload_hash(payload: Any) -> str:
    """sha256 of the canonical payload; the backend hangs its dedup key on it.

    The entry points hash the UNWRAPPED request, so the same request posted bare
    and posted inside the engine envelope dedupes to one cache entry.
    """
    digest = hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
    return "sha256:" + digest


_FINGERPRINT_CACHE = []  # type: List[str]


def _runtime_source_components() -> List[Tuple[str, bytes]]:
    """Deterministic runtime Python sources that can change a result.

    The fingerprint originally covered only schema and YAML tables. A code-only
    rollout could therefore reuse cached structural results under the same id.
    Tests and bytecode are excluded; every shipped structural Python source is
    length-framed by its package-relative POSIX path and exact bytes.
    """
    package_root = os.path.dirname(os.path.abspath(__file__))
    components = []  # type: List[Tuple[str, bytes]]
    for root, dirs, files in os.walk(package_root):
        dirs[:] = sorted(
            name for name in dirs
            if name not in {"__pycache__", "tests", "data"}
        )
        for filename in sorted(files):
            if not filename.endswith(".py"):
                continue
            path = os.path.join(root, filename)
            relative = os.path.relpath(path, package_root).replace(os.sep, "/")
            with open(path, "rb") as handle:
                components.append((relative, handle.read()))
    return components


def _runtime_schema_components() -> List[Tuple[str, bytes]]:
    """Shipped JSON contracts that can change a response without Python edits."""
    package_root = os.path.dirname(os.path.abspath(__file__))
    schema_root = os.path.join(package_root, "schema")
    components = []  # type: List[Tuple[str, bytes]]
    if not os.path.isdir(schema_root):
        return components
    for root, dirs, files in os.walk(schema_root):
        dirs[:] = sorted(dirs)
        for filename in sorted(files):
            if not filename.endswith(".json"):
                continue
            path = os.path.join(root, filename)
            relative = os.path.relpath(path, package_root).replace(os.sep, "/")
            with open(path, "rb") as handle:
                components.append((relative, handle.read()))
    return components


def structural_fingerprint() -> str:
    """Schema, data tables and runtime implementation under one cache identity.

    The backend folds this into its cache key so a code, schema or table edit
    invalidates responses computed from the old implementation. Computed once
    per process: a response asks for it several times.

    Each component is length-framed. The framing makes the digest sensitive to
    table additions and removals and prevents a filename or byte boundary from
    being reinterpreted as part of a neighbouring component.
    """
    if _FINGERPRINT_CACHE:
        return _FINGERPRINT_CACHE[0]
    digest_builder = hashlib.sha256()

    def add_component(name: str, value: bytes) -> None:
        name_bytes = name.encode("utf-8")
        digest_builder.update(len(name_bytes).to_bytes(8, "big"))
        digest_builder.update(name_bytes)
        digest_builder.update(len(value).to_bytes(8, "big"))
        digest_builder.update(value)

    add_component("schema_version", STRUCTURAL_SCHEMA_VERSION.encode("utf-8"))
    names = available_tables()
    add_component("table_count", str(len(names)).encode("ascii"))
    for name in names:
        filename = name + ".yaml"
        with open(data_path(name), "rb") as handle:
            add_component(filename, handle.read())

    schemas = _runtime_schema_components()
    add_component("runtime_schema_count", str(len(schemas)).encode("ascii"))
    for relative, contents in schemas:
        add_component("schema/" + relative, contents)

    sources = _runtime_source_components()
    add_component("runtime_source_count", str(len(sources)).encode("ascii"))
    for relative, contents in sources:
        add_component("source/" + relative, contents)

    digest = digest_builder.hexdigest()
    _FINGERPRINT_CACHE.append("st-" + digest[:16])
    return _FINGERPRINT_CACHE[0]


# ---------------------------------------------------------------------------
# the soil table (finding 30): one mapping, three consumers
# ---------------------------------------------------------------------------


def resolve_soil(block: Any = None) -> Dict[str, Any]:
    """The frozen soil block, with every default it filled in named in `assumed`.

    Accepts the frozen shape `{type, sbc_kpa, soft, founding_depth_m}` and the
    older HTTP words hard / medium / soft, which `SOIL_ALIASES` maps onto the
    code types. `placement.foundations.Soil` does the table reading; this
    function owns only the vocabulary translation, so there is exactly one soil
    mapping in the module.
    """
    supplied = {}  # type: Dict[str, Any]
    if isinstance(block, str):
        word = block.strip().lower()
        if word in SOIL_ALIASES:
            supplied["type"] = SOIL_ALIASES[word]
        elif word.upper() in SOIL_TYPES:
            supplied["type"] = word.upper()
        else:
            raise StructuralValidationError(
                "params.soil",
                "unknown soil " + repr(block) + "; give a type in "
                + ", ".join(SOIL_TYPES)
                + " or one of "
                + ", ".join(sorted(SOIL_ALIASES)),
            )
    elif isinstance(block, dict):
        supplied = dict(block)
        raw_type = supplied.get("type")
        if isinstance(raw_type, str):
            word = raw_type.strip()
            if word.lower() in SOIL_ALIASES:
                supplied["type"] = SOIL_ALIASES[word.lower()]
            elif word.upper() in SOIL_TYPES:
                supplied["type"] = word.upper()
            else:
                raise StructuralValidationError(
                    "params.soil.type",
                    "unknown soil type " + repr(raw_type) + "; known: " + ", ".join(SOIL_TYPES),
                )
    elif block is not None:
        raise StructuralValidationError(
            "params.soil", "must be an object or a soil word, got " + type(block).__name__
        )
    soil = _foundations.Soil.from_params(supplied)
    return soil.to_dict()


# ---------------------------------------------------------------------------
# options (finding 42: content generated, never a second literal list)
# ---------------------------------------------------------------------------


def run_options() -> Dict[str, Any]:
    """Static capability discovery: what this engine accepts and what it caps.

    Every list is derived from the constant the pipeline actually enforces, so
    the frontend cannot drift from the engine by hardcoding an enum.
    """
    from .design import common as _design_common
    from .design import masonry as _design_masonry

    documents = {
        "schema_version": STRUCTURAL_SCHEMA_VERSION,
        "engine_fingerprint": structural_fingerprint(),
        "units": units_block(),
        "sources": list(SOURCES),
        "systems": list(REQUEST_SYSTEMS),
        "systems_returned": list(WIRE_SYSTEMS),
        "code_profiles": list(CODE_PROFILES),
        "analysis_modes": list(ANALYSIS_MODES),
        "placement_strategies": list(PLACEMENT_STRATEGIES),
        "housing_column_variants": {
            "values": list(HOUSING_COLUMN_VARIANTS), "source": "housing", "total_storeys": [1, 2, 3],
            "system": "rc_frame", "analysis_mode": "gravity_only", "placement_strategy": "wall_aligned",
        },
        "scopes": list(SCOPES),
        "seismic_zones": dict(SEISMIC_ZONES),
        "soils": {
            "types": list(SOIL_TYPES),
            "aliases": dict(SOIL_ALIASES),
            "defaults": resolve_soil(None),
        },
        "importance_categories": list(IMPORTANCE_CATEGORIES),
        "frame_ductility": list(DUCTILITY),
        "grades": {
            "concrete": ["M" + str(int(value)) for value in _design_common.CONCRETE_GRADES_MPA],
            "steel": ["Fe" + str(int(value)) for value in _design_common.REBAR_GRADES_MPA],
            "mortar": list(_design_masonry.is1905.MORTAR_GRADES),
            "masonry_unit_mpa": list(_design_masonry.DEFAULT_UNIT_STRENGTHS_MPA),
            "masonry_thickness_mm": list(_design_masonry.THICKNESS_LADDER_MM),
        },
        "spans": {
            "min_m": MIN_SPAN_M,
            "max_m": MAX_SPAN_M,
            "hard_max_m": HARD_MAX_SPAN_M,
            "min_ft": round(m_to_ft(MIN_SPAN_M), 4),
            "max_ft": round(m_to_ft(MAX_SPAN_M), 4),
        },
        "limits": dict(LIMITS),
        "detail": {
            "levels": list(DETAIL_LEVELS),
            "default": DEFAULT_DETAIL,
            "request_flag": "output.detail",
            "also_accepted": "params.detail, when a caller has no output block",
            "trace_implies": DETAIL_FULL,
            "full_detail_always": (
                "every blocked and every failed element keeps its whole DesignResult "
                "and its element card at both levels"
            ),
            "never_elided": (
                "the disclaimer, every disclosure, options_echo, placement, the layout "
                "metrics, the model geometry, the take-off class rows, the whole BOQ, and "
                "the section, reinforcement, status, utilization and governing check of "
                "every designed element"
            ),
            "policy": _plain(DETAIL_POLICY),
        },
        "endpoints": {
            "layout": "sync",
            "design": "async",
            "check": "auto",
            "options": "sync",
        },
        "defaults": _default_params_echo(),
        "disclosure_codes": dict(
            (code, {"severity": REGISTRY[code][0].value, "meaning": REGISTRY[code][1]})
            for code in sorted(REGISTRY)
        ),
    }
    documents["status"] = R.STATUS_OK
    documents["disclaimer"] = R.DISCLAIMER
    return _envelope("SUCCESS", "structural options", [documents])


def _default_params_echo() -> Dict[str, Any]:
    """The resolved defaults, each labeled with where the number comes from."""
    return {
        "system": {"value": "auto", "origin": "default"},
        "code_profile": {"value": "IS", "origin": "default"},
        "analysis_mode": {"value": "code_complete", "origin": "default"},
        "placement_strategy": {"value": "wall_aligned", "origin": "default"},
        "seismic_zone": {"value": "III", "origin": "default"},
        "importance_factor": {"value": 1.0, "origin": "IS 1893 Table 8 residential"},
        "soil": {"value": resolve_soil(None), "origin": "data/soil_defaults.yaml"},
        "grades": {
            "value": {"concrete": "M25", "steel": "Fe500", "mortar": "M1", "masonry_unit_mpa": 7.5},
            "origin": "design layer defaults",
        },
        "spans": {
            "value": {"max_m": MAX_SPAN_M, "min_m": MIN_SPAN_M},
            "origin": "grid.FrameParams (finding 35: metric engine defaults are canonical)",
        },
        "storey_height_ft": {
            "value": None,
            "origin": "source adapter default: plan/building 10.0 ft; housing 10.4 ft",
        },
        "wind": {"value": None, "origin": "wind is skipped unless a basic speed is supplied"},
        "output": {
            "value": {
                "include_report": True,
                "include_boq": True,
                "include_quantities": True,
                "trace": False,
                "detail": DEFAULT_DETAIL,
                "report_format": "json",
            },
            "origin": "default",
        },
    }


# ---------------------------------------------------------------------------
# request unwrapping and validation (spec section 5, in order)
# ---------------------------------------------------------------------------


def _unwrap_request(payload: Any) -> Dict[str, Any]:
    """The request object, however the caller wrapped it.

    A bare request is taken as is; a request posted inside the engine envelope
    (`{response: {Documents: {...}}}` or `{Documents: {...}}`) is unwrapped, so
    the structural endpoints accept the same envelopes every other engine API
    does.
    """
    if not isinstance(payload, dict):
        raise StructuralValidationError(
            "payload", "the request body must be a JSON object, got " + type(payload).__name__
        )
    if "source" in payload:
        return payload
    response = payload.get("response")
    if isinstance(response, dict) and isinstance(response.get("Documents"), dict):
        inner = response["Documents"]
        if "source" in inner:
            return inner
    documents = payload.get("Documents")
    if isinstance(documents, dict) and "source" in documents:
        return documents
    return payload


def _check_schema_version(request: Dict[str, Any]) -> str:
    version = request.get("schema_version")
    if version is None:
        return STRUCTURAL_SCHEMA_VERSION
    if not isinstance(version, str):
        raise StructuralValidationError(
            "schema_version", "must be a string, got " + type(version).__name__
        )
    if not version.startswith(STRUCTURAL_SCHEMA_MAJOR):
        raise StructuralValidationError(
            "schema_version",
            "unsupported " + repr(version) + ", this engine speaks " + STRUCTURAL_SCHEMA_MAJOR,
        )
    return version


def _check_source(request: Dict[str, Any], allowed: Sequence[str]) -> str:
    source = request.get("source")
    if source is None:
        raise StructuralValidationError(
            "source", "is required; one of " + ", ".join(allowed)
        )
    if not isinstance(source, str) or source not in allowed:
        raise StructuralValidationError(
            "source", "must be one of " + ", ".join(allowed) + ", got " + repr(source)
        )
    if request.get(source) is None:
        raise StructuralValidationError(
            source, "source is " + repr(source) + " so a " + repr(source) + " block is required"
        )
    for other in SOURCES:
        if other != source and request.get(other) is not None:
            raise StructuralValidationError(
                other,
                "source is " + repr(source) + " so the " + repr(other) + " block must be absent",
            )
    return source


def _check_params(params: Dict[str, Any]) -> None:
    """Params enums and ranges (spec 5.7). Field names are dotted for the client."""
    system = params.get("system", "auto")
    if not isinstance(system, str) or system not in REQUEST_SYSTEMS:
        raise StructuralValidationError(
            "params.system",
            "must be one of " + ", ".join(REQUEST_SYSTEMS) + ", got " + repr(system),
        )
    profile = params.get("code_profile", "IS")
    if not isinstance(profile, str) or profile not in CODE_PROFILES:
        raise StructuralValidationError(
            "params.code_profile",
            "only " + ", ".join(CODE_PROFILES) + " is implemented, got " + repr(profile),
        )
    analysis_mode = params.get("analysis_mode", "code_complete")
    if not isinstance(analysis_mode, str) or analysis_mode not in ANALYSIS_MODES:
        raise StructuralValidationError(
            "params.analysis_mode",
            "must be one of " + ", ".join(ANALYSIS_MODES) + ", got " + repr(analysis_mode),
        )
    placement_strategy = params.get("placement_strategy", "wall_aligned")
    if not isinstance(placement_strategy, str) or placement_strategy not in PLACEMENT_STRATEGIES:
        raise StructuralValidationError(
            "params.placement_strategy",
            "must be one of " + ", ".join(PLACEMENT_STRATEGIES) + ", got " + repr(placement_strategy),
        )
    variant = params.get("housing_column_variant")
    if variant is not None:
        if not isinstance(variant, str) or variant not in HOUSING_COLUMN_VARIANTS:
            raise StructuralValidationError("params.housing_column_variant", "must be one of " + ", ".join(HOUSING_COLUMN_VARIANTS))
        if system != "rc_frame" or params.get("analysis_mode") != "gravity_only" or placement_strategy != "wall_aligned":
            raise StructuralValidationError("params.housing_column_variant", "requires rc_frame, gravity_only and wall_aligned")
    zone = params.get("seismic_zone", "III")
    if not isinstance(zone, str) or zone not in SEISMIC_ZONES:
        raise StructuralValidationError(
            "params.seismic_zone",
            "must be one of " + ", ".join(sorted(SEISMIC_ZONES)) + ", got " + repr(zone),
        )
    ductility = params.get("frame_ductility")
    if ductility is not None:
        if not isinstance(ductility, str) or ductility.upper() not in DUCTILITY:
            raise StructuralValidationError(
                "params.frame_ductility",
                "must be one of " + ", ".join(DUCTILITY) + ", got " + repr(ductility),
            )
    importance = params.get("importance_factor")
    if importance is not None and not isinstance(importance, str):
        value = _num(importance, -1.0)
        if value <= 0.0:
            raise StructuralValidationError(
                "params.importance_factor", "must be a positive factor, got " + repr(importance)
            )
    elif isinstance(importance, str) and importance not in IMPORTANCE_CATEGORIES:
        raise StructuralValidationError(
            "params.importance_factor",
            "must be a factor or one of " + ", ".join(IMPORTANCE_CATEGORIES),
        )

    grades = _mapping(params.get("grades"), "params.grades")
    concrete = grades.get("concrete")
    if concrete is not None:
        known = ["M" + str(int(v)) for v in _concrete_grades()]
        if str(concrete) not in known:
            raise StructuralValidationError(
                "params.grades.concrete",
                "must be one of " + ", ".join(known) + ", got " + repr(concrete),
            )
    steel = grades.get("steel")
    if steel is not None:
        known = ["Fe" + str(int(v)) for v in _steel_grades()]
        if str(steel) not in known:
            raise StructuralValidationError(
                "params.grades.steel",
                "must be one of " + ", ".join(known) + ", got " + repr(steel),
            )
    mortar = grades.get("mortar")
    if mortar is not None and str(mortar).upper() not in _mortar_grades():
        raise StructuralValidationError(
            "params.grades.mortar",
            "must be one of " + ", ".join(_mortar_grades()) + ", got " + repr(mortar),
        )

    spans = _mapping(params.get("spans"), "params.spans")
    min_m, max_m = _resolve_spans(spans)
    if min_m < MIN_SPAN_M - 1e-9:
        raise StructuralValidationError(
            "params.spans.min",
            "minimum span %.3f m is below the %.3f m catalogue floor" % (min_m, MIN_SPAN_M),
        )
    if max_m > HARD_MAX_SPAN_M + 1e-9:
        raise StructuralValidationError(
            "params.spans.max",
            "maximum span %.3f m is above the %.3f m hard cap" % (max_m, HARD_MAX_SPAN_M),
        )
    if max_m <= min_m:
        raise StructuralValidationError(
            "params.spans.max",
            "maximum span %.3f m must exceed the minimum %.3f m" % (max_m, min_m),
        )

    cantilever = params.get("cantilever")
    if cantilever is not None:
        cap = _num(_mapping(cantilever, "params.cantilever").get("max_m"), MAX_CANTILEVER_M)
        if cap > REFUSE_CANTILEVER_M + 1e-9:
            raise StructuralValidationError(
                "params.cantilever.max_m",
                "cantilevers above %.1f m are refused; %.3f m was asked for"
                % (REFUSE_CANTILEVER_M, cap),
            )

    slab = _mapping(params.get("slab"), "params.slab")
    if slab.get("t_max_mm") is not None:
        slab_t_max_mm = _num(slab.get("t_max_mm"), RC_SLAB_MIN_THICKNESS_MM)
        if slab_t_max_mm < RC_SLAB_MIN_THICKNESS_MM - 1e-9:
            raise StructuralValidationError(
                "params.slab.t_max_mm",
                "slab target %.3f mm is below the %.0f mm project minimum"
                % (slab_t_max_mm, RC_SLAB_MIN_THICKNESS_MM),
            )

    # touches the one soil table, so an unknown soil word fails here not later
    resolve_soil(params.get("soil"))


def _concrete_grades() -> Tuple[float, ...]:
    from .design import common as _design_common

    return tuple(_design_common.CONCRETE_GRADES_MPA)


def _steel_grades() -> Tuple[float, ...]:
    from .design import common as _design_common

    return tuple(_design_common.REBAR_GRADES_MPA)


def _mortar_grades() -> Tuple[str, ...]:
    from .codes import is1905

    return tuple(is1905.MORTAR_GRADES)


def _resolve_spans(spans: Dict[str, Any]) -> Tuple[float, float]:
    """(min_m, max_m) from a spans block written in either metres or feet.

    Finding 35: the metric engine defaults are canonical and feet are accepted
    and converted, never the other way round.
    """
    min_m = MIN_SPAN_M
    max_m = MAX_SPAN_M
    if "min_m" in spans and spans["min_m"] is not None:
        min_m = _num(spans["min_m"], MIN_SPAN_M)
    elif "min_ft" in spans and spans["min_ft"] is not None:
        min_m = ft_to_m(_num(spans["min_ft"], m_to_ft(MIN_SPAN_M)))
    if "max_m" in spans and spans["max_m"] is not None:
        max_m = _num(spans["max_m"], MAX_SPAN_M)
    elif "max_ft" in spans and spans["max_ft"] is not None:
        max_m = ft_to_m(_num(spans["max_ft"], m_to_ft(MAX_SPAN_M)))
    return (min_m, max_m)


def _check_storey_caps(storeys: int, system: str, zone: str, field: str) -> None:
    """Storey caps by system and IS 4326 seismic category (spec 5.3)."""
    count = int(storeys)
    if count < 1:
        raise StructuralValidationError(field, "at least one storey is required, got " + str(count))
    if system in _MASONRY_SYSTEMS:
        cap = MAX_STOREYS_MASONRY_ZONE_V if zone == "V" else MAX_STOREYS_MASONRY
        if count > cap:
            raise StructuralValidationError(
                field,
                "%d exceeds the masonry limit %d for zone %s" % (count, cap, zone),
            )
        return
    if count > MAX_STOREYS_RC:
        raise StructuralValidationError(
            field, "%d exceeds the rc_frame limit %d" % (count, MAX_STOREYS_RC)
        )


def _check_rooms_per_floor(model: StructuralModel) -> None:
    counts = {}  # type: Dict[int, int]
    for room in model.rooms:
        counts[room.storey] = counts.get(room.storey, 0) + 1
    for storey in sorted(counts):
        if counts[storey] > MAX_ROOMS_PER_FLOOR:
            raise StructuralValidationError(
                "floors[" + str(storey) + "].rooms",
                "%d rooms on storey %d exceeds the %d room cap"
                % (counts[storey], storey, MAX_ROOMS_PER_FLOOR),
            )


# ---------------------------------------------------------------------------
# resolved options
# ---------------------------------------------------------------------------


class _Resolved(object):
    """Every knob this run used, with the origin of each resolved default.

    Built once per request and threaded through every stage, so the response's
    `options_echo` is the record of what actually ran rather than a second
    reading of the request.
    """

    def __init__(self, request: Dict[str, Any], overrides: Dict[str, Any]) -> None:
        # copied, never referenced: a request dict the caller still holds must
        # not change under it, and two runs of the same payload must be equal
        params = dict(_mapping(request.get("params"), "params"))
        output = dict(_mapping(request.get("output"), "output"))
        for key in sorted(overrides):
            if key in ("params", "output"):
                continue
            output[key] = overrides[key]
        if isinstance(overrides.get("params"), dict):
            merged = dict(params)
            merged.update(overrides["params"])
            params = merged
        if isinstance(overrides.get("output"), dict):
            output.update(overrides["output"])

        _check_params(params)

        self.params = params
        self.output = output
        self.origins = {}  # type: Dict[str, str]
        self.unapplied = []  # type: List[Dict[str, str]]

        self.system_requested = self._pick("system", params.get("system"), "auto")
        self.code_profile = self._pick("code_profile", params.get("code_profile"), "IS")
        self.analysis_mode = self._pick(
            "analysis_mode", params.get("analysis_mode"), "code_complete"
        )

        self.placement_strategy = self._pick(
            "placement_strategy", params.get("placement_strategy"), "wall_aligned"
        )
        self.housing_column_variant = params.get("housing_column_variant")
        if self.housing_column_variant is not None:
            if request.get("source") != "housing":
                raise StructuralValidationError("params.housing_column_variant", "is available only for Housing Structure")
            self.origins["housing_column_variant"] = "request"
        self.zone = self._pick("seismic_zone", params.get("seismic_zone"), "III")
        self.soil = resolve_soil(params.get("soil"))
        self.origins["soil"] = "request" if params.get("soil") is not None else "data/soil_defaults.yaml"
        importance = self._pick("importance_factor", params.get("importance_factor"), 1.0)
        # Keep a category word only for the request echo. Every engineering
        # consumer gets the one Table 8 factor resolved here (B26), so placement,
        # loads and masonry design cannot interpret the same option differently.
        self.importance_echo = importance
        self.importance = (
            is1893.importance_factor(importance)
            if isinstance(importance, str)
            else _num(importance, 1.0)
        )
        if isinstance(importance, str):
            self.origins["importance_factor"] = (
                "request category resolved by IS 1893 (Part 1):2016 Table 8"
            )
        self.seismic_system = None  # type: Optional[str]

        ductility = params.get("frame_ductility")
        if ductility is None:
            # finding 41: OMRF up to zone III, SMRF above; the resolved value is
            # what reaches SeismicContext, which defaults nothing itself.
            ductility = "OMRF" if self.zone in ("II", "III") else "SMRF"
            self.origins["frame_ductility"] = "derived from seismic_zone " + self.zone
        else:
            ductility = str(ductility).upper()
            self.origins["frame_ductility"] = "request"
        self.ductility = ductility

        grades = _mapping(params.get("grades"), "params.grades")
        self.concrete_grade = self._pick("grades.concrete", grades.get("concrete"), "M25")
        self.steel_grade = self._pick("grades.steel", grades.get("steel"), "Fe500")
        self.mortar_grade = str(self._pick("grades.mortar", grades.get("mortar"), "M1")).upper()
        self.masonry_unit_mpa = _num(
            self._pick("grades.masonry_unit_mpa", grades.get("masonry_unit_mpa"), 7.5), 7.5
        )
        self.exposure = self._pick("exposure", params.get("exposure"), "moderate")

        spans = _mapping(params.get("spans"), "params.spans")
        self.min_span_m, self.max_span_m = _resolve_spans(spans)
        self.origins["spans"] = "request" if spans else "grid.FrameParams"

        cantilever = _mapping(params.get("cantilever"), "params.cantilever")
        self.cantilever_m = _num(cantilever.get("max_m"), MAX_CANTILEVER_M)
        self.origins["cantilever.max_m"] = "request" if cantilever else "grid.FrameParams"

        slab = _mapping(params.get("slab"), "params.slab")
        self.slab_t_max_mm = max(
            _num(slab.get("t_max_mm"), float(_FRAME_DEFAULTS.slab_t_max_mm)),
            RC_SLAB_MIN_THICKNESS_MM,
        )
        self.origins["slab.t_max_mm"] = "request" if slab else "grid.FrameParams"

        walls = _mapping(params.get("walls"), "params.walls")
        self.exterior_wall_ft = walls.get("exterior_ft")
        self.interior_wall_ft = walls.get("interior_ft")
        self.origins["walls"] = "request" if walls else "adapter defaults"

        supplied_height = params.get("storey_height_ft")
        self.storey_height_supplied = supplied_height is not None
        if self.storey_height_supplied:
            self.storey_height_ft = _num(supplied_height, DEFAULT_STOREY_HEIGHT_FT)
            self.origins["storey_height_ft"] = "request"
        else:
            self.storey_height_ft = None  # type: Optional[float]
            self.origins["storey_height_ft"] = "source adapter default"
        self.live_load_kpa = params.get("live_load_kpa")
        self.origins["live_load_kpa"] = (
            "request" if self.live_load_kpa is not None else "IS 875-2 by occupancy"
        )
        wind = _mapping(params.get("wind"), "params.wind")
        self.wind_speed_ms = wind.get("basic_speed_ms")
        self.wind_terrain = wind.get("terrain_category", 2)
        self.origins["wind"] = "request" if self.wind_speed_ms is not None else "skipped"

        self.include_report = bool(output.get("include_report", True))
        self.include_boq = bool(output.get("include_boq", True))
        self.include_quantities = bool(output.get("include_quantities", True))
        self.trace = bool(output.get("trace", False))
        self.report_format = str(output.get("report_format", "json"))
        self.generated_at = output.get("generated_at")
        self.validate_only = bool(output.get("validate_only", False))
        self.scope = str(request.get("scope", "full"))
        self.detail = self._pick_detail(params, output)

    def _pick_detail(self, params: Dict[str, Any], output: Dict[str, Any]) -> str:
        """The resolved size regime, from `output.detail` or `params.detail`.

        Unstated, it is `compact` -- except with tracing on, where it resolves to
        `full`, because a caller who asked for the clause working and got a
        summary would have to guess that a second flag exists. A stated level
        always wins, tracing included.
        """
        supplied = output.get("detail")
        field = "output.detail"
        if supplied is None:
            supplied = params.get("detail")
            field = "params.detail"
        if supplied is None:
            if self.trace:
                self.origins["detail"] = "derived from output.trace"
                return DETAIL_FULL
            self.origins["detail"] = "default"
            return DEFAULT_DETAIL
        word = str(supplied).strip().lower()
        if word not in DETAIL_LEVELS:
            raise StructuralValidationError(
                field,
                "must be one of " + ", ".join(DETAIL_LEVELS) + ", got " + repr(supplied),
            )
        self.origins["detail"] = "request"
        return word

    @property
    def compact(self) -> bool:
        """True when the elidable tier is elided (the default)."""
        return self.detail == DETAIL_COMPACT

    def _pick(self, key: str, value: Any, default: Any) -> Any:
        if value is None:
            self.origins[key] = "default"
            return default
        self.origins[key] = "request"
        return value

    def fck_mpa(self) -> float:
        return float(str(self.concrete_grade).lstrip("Mm"))

    def fy_mpa(self) -> float:
        return float(str(self.steel_grade).lower().replace("fe", ""))

    def frame_params(self, system: str) -> FrameParams:
        return FrameParams(
            system=system,
            column_strategy=self.placement_strategy,
            housing_column_variant=self.housing_column_variant,
            max_primary_span=self.max_span_m,
            min_span=self.min_span_m,
            cantilever_cap=self.cantilever_m,
            slab_t_max_mm=self.slab_t_max_mm,
            # A gravity-only RC comparison must not quietly introduce
            # prescription-only shaft walls that the v1 member designer cannot
            # check.  Keep stairs framed by columns/trimmers in this mode.
            shaft_min_storeys=(MAX_STOREYS_RC + 1 if self.analysis_mode == "gravity_only" else _FRAME_DEFAULTS.shaft_min_storeys),
        )

    def masonry_params(self, system: str) -> Any:
        return _masonry.MasonryParams(
            system=system,
            zone=self.zone,
            importance=self.importance,
            mortar_grade=self.mortar_grade,
            soil=dict(self.soil),
        )

    def design_options(self) -> Dict[str, Any]:
        """The design layer's options block (design/rcc/detailing.as_context)."""
        return {
            "materials": {"fck": self.fck_mpa(), "fy": self.fy_mpa()},
            "seismic": {"zone": self.zone, "frame": self.ductility},
            "is13920": "off" if self.analysis_mode == "gravity_only" else "auto",
            "exposure": self.exposure,
        }

    def echo(self) -> Dict[str, Any]:
        """`options_echo`: every resolved value beside where it came from."""
        values = {
            "system": self.system_requested,
            "code_profile": self.code_profile,
            "analysis_mode": self.analysis_mode,
            "placement_strategy": self.placement_strategy,
            "seismic_zone": self.zone,
            "importance_factor": self.importance_echo,
            "frame_ductility": self.ductility,
            "soil": dict(self.soil),
            "grades": {
                "concrete": self.concrete_grade,
                "steel": self.steel_grade,
                "mortar": self.mortar_grade,
                "masonry_unit_mpa": self.masonry_unit_mpa,
            },
            "exposure": self.exposure,
            "spans": {"min_m": self.min_span_m, "max_m": self.max_span_m},
            "cantilever": {"max_m": self.cantilever_m, "refuse_m": REFUSE_CANTILEVER_M},
            "slab": {"t_max_mm": self.slab_t_max_mm},
            "walls": {
                "exterior_ft": self.exterior_wall_ft,
                "interior_ft": self.interior_wall_ft,
            },
            "storey_height_ft": self.storey_height_ft,
            "live_load_kpa": self.live_load_kpa,
            "wind": {"basic_speed_ms": self.wind_speed_ms, "terrain_category": self.wind_terrain},
            "output": {
                "include_report": self.include_report,
                "include_boq": self.include_boq,
                "include_quantities": self.include_quantities,
                "trace": self.trace,
                "detail": self.detail,
                "report_format": self.report_format,
            },
        }
        if self.seismic_system is not None:
            values["seismic_system"] = self.seismic_system
        if self.housing_column_variant is not None:
            values["housing_column_variant"] = self.housing_column_variant
        return {
            "values": _plain(values),
            "origins": dict((key, self.origins[key]) for key in sorted(self.origins)),
            "unapplied": list(self.unapplied),
        }

    def mark_unapplied(self, field: str, reason: str) -> None:
        """Record an option this engine accepted on the request and did not use.

        The ladder carries it too, but the ladder merges by code and another
        producer's message can win the entry; this list is per-field and cannot
        be merged away.
        """
        row = {"field": str(field), "reason": str(reason)}
        if row not in self.unapplied:
            self.unapplied.append(row)


# ---------------------------------------------------------------------------
# adapters (source dispatch)
# ---------------------------------------------------------------------------


def _record_adapter_storey_height(
    opts: _Resolved, source: str, models: Sequence[StructuralModel]
) -> None:
    """Echo the source adapter's effective default after it built geometry."""
    if opts.storey_height_supplied:
        return
    for model in models:
        storeys = sorted(model.storeys, key=lambda one: int(one.index))
        if not storeys:
            continue
        opts.storey_height_ft = m_to_ft(float(storeys[0].height_m))
        break
    module = {
        "plan": "adapters.plan_json.from_plan",
        "building": "adapters.building.from_building",
        "housing": "adapters.housing.from_housing",
    }[source]
    opts.origins["storey_height_ft"] = module + " default"


def _adapt(request: Dict[str, Any], source: str, opts: _Resolved) -> List[StructuralModel]:
    """One model per plan (or per built plot stack, for housing).

    The system hint reaches the adapter because it decides whether windows are
    synthesized for the IS 4326 opening checks (finding 10).
    """
    if opts.housing_column_variant is not None and source != "housing":
        raise StructuralValidationError("params.housing_column_variant", "is available only for Housing Structure")
    hint = System.RC_FRAME.value
    if opts.system_requested in _MASONRY_SYSTEMS:
        hint = opts.system_requested
    assume_windows = hint in _MASONRY_SYSTEMS

    thickness = {}  # type: Dict[str, Any]
    if opts.exterior_wall_ft is not None:
        thickness["exterior_wall_ft"] = _num(opts.exterior_wall_ft)
    if opts.interior_wall_ft is not None:
        thickness["interior_wall_ft"] = _num(opts.interior_wall_ft)

    if source == "plan":
        from .adapters.plan_json import from_plan

        plan_index = request.get("plan_index", 0)
        try:
            plan_index = int(plan_index)
        except (TypeError, ValueError):
            raise StructuralValidationError(
                "plan_index", "must be an integer, got " + repr(request.get("plan_index"))
            )
        if plan_index < 0:
            raise StructuralValidationError(
                "plan_index", "must not be negative, got " + str(plan_index)
            )
        storeys = request.get("storeys")
        if storeys is None:
            raise StructuralValidationError(
                "storeys", "a plan carries no storey information, so storeys is required"
            )
        try:
            storeys = int(storeys)
        except (TypeError, ValueError):
            raise StructuralValidationError(
                "storeys", "must be an integer, got " + repr(request.get("storeys"))
            )
        _check_storey_caps(storeys, hint, opts.zone, "storeys")
        adapter_options = dict(thickness)
        adapter_options.update({"system_hint": hint, "assume_windows": assume_windows})
        if opts.storey_height_supplied:
            adapter_options["storey_height_ft"] = opts.storey_height_ft
        model = from_plan(
            request["plan"],
            storeys=storeys,
            plan_index=plan_index,
            **adapter_options
        )
        _record_adapter_storey_height(opts, source, [model])
        return [model]

    if source == "building":
        from .adapters.building import from_building

        building = _mapping(request.get("building"), "building")
        total = building.get("totalFloors")
        try:
            _check_storey_caps(int(total), hint, opts.zone, "building.totalFloors")
        except (TypeError, ValueError):
            raise StructuralValidationError(
                "building.totalFloors", "must be an integer, got " + repr(total)
            )
        adapter_options = dict(thickness)
        adapter_options.update({"system_hint": hint, "assume_windows": assume_windows})
        if opts.storey_height_supplied:
            adapter_options["storey_height_ft"] = opts.storey_height_ft
        model = from_building(building, **adapter_options)
        _record_adapter_storey_height(opts, source, [model])
        return [model]

    from .adapters.housing import from_housing

    housing = _mapping(request.get("housing"), "housing")
    floors = housing.get("floors")
    if not isinstance(floors, list) or not floors:
        raise StructuralValidationError("housing.floors", "at least one floor is required")
    if opts.housing_column_variant is not None and len(floors) > 3:
        raise StructuralValidationError("housing.floors", "housing column alternatives support one to three total storeys, including ground")
    if len(floors) > MAX_HOUSING_FLOORS:
        raise StructuralValidationError(
            "housing.floors",
            "%d floors exceeds the housing limit of %d" % (len(floors), MAX_HOUSING_FLOORS),
        )
    _check_storey_caps(len(floors), hint, opts.zone, "housing.floors")
    adapter_options = dict(thickness)
    adapter_options.update({"system_hint": hint, "assume_windows": assume_windows})
    if opts.storey_height_supplied:
        adapter_options["storey_height_ft"] = opts.storey_height_ft
    models = list(
        from_housing(
            housing,
            plot_id=request.get("plot_id"),
            resolved_regions=request.get("resolved_regions"),
            **adapter_options
        )
    )
    _record_adapter_storey_height(opts, source, models)
    return models


# ---------------------------------------------------------------------------
# placement
# ---------------------------------------------------------------------------


class _Placement(object):
    """What the placement stage produced, for either system family."""

    def __init__(self) -> None:
        self.system = System.RC_FRAME.value
        self.decision = None  # type: Any
        self.frame = None  # type: Any
        self.masonry = None  # type: Any
        self.masonry_attempt = None  # type: Any
        # never an empty block: a reader must be able to tell "not scored" from
        # "scored zero", and the wire schema requires both keys either way
        self.layout_score = {
            "score": None,
            "score_version": None,
            "hard_violations": {},
            "metrics": {},
            "basis": "no frame was placed, so no layout score was computed",
        }  # type: Dict[str, Any]
        self.axes_source = ""
        self.valid = True

    def to_dict(self) -> Dict[str, Any]:
        out = {
            "system": self.system,
            "layout_score": _plain(self.layout_score),
            "axes_source": self.axes_source,
            "valid": bool(self.valid),
        }  # type: Dict[str, Any]
        if self.decision is not None:
            out["system_decision"] = _plain(self.decision.to_dict())
        if self.frame is not None:
            out["params"] = _plain(self.frame.params_echo)
            out["report"] = _plain(self.frame.report)
        if self.masonry is not None:
            out["masonry"] = _plain(self.masonry.to_dict())
        if self.masonry_attempt is not None:
            out["masonry_attempt"] = _plain(self.masonry_attempt)
        return out


def _score_block(result: Any) -> Dict[str, Any]:
    """The layout score, mirroring placement-frame's metrics field for field."""
    metrics = dict(result.metrics)
    hard = dict(metrics.get("hard_violations", {}))
    return {
        "score": metrics.get("score"),
        "score_version": metrics.get("score_version", R.UNVERSIONED_SCORE),
        "hard_violations": hard,
        "hard_violation_count": sum(int(value) for value in hard.values()),
        "metrics": dict(
            (key, metrics[key])
            for key in sorted(metrics)
            if key not in ("score", "score_version", "hard_violations")
        ),
        "valid": bool(result.valid),
    }


def _disclose_fallback(decision: Any, log: DisclosureLog) -> None:
    """A refusal that still produced a system is a labeled fallback, not a refusal.

    `choose_system` and `MasonryPlacer` both answer a system they will not build
    by producing the next one down and setting `refused`. The ERROR-coded
    condition stays verbatim in `placement.system_decision.refused`; the ladder
    entry is `W_RELEASED_CAP`, because a cap was relaxed and output WAS produced,
    and the run's status must not read as a refusal when a model came back.
    """
    refused = getattr(decision, "refused", None)
    if refused is None:
        return
    log.append(
        make_disclosure(
            "W_RELEASED_CAP",
            "%s was asked for and refused (%s); %s was produced instead: %s"
            % (
                getattr(decision, "requested", "auto"),
                refused.code or "no code",
                getattr(decision, "system", "rc_frame"),
                refused.reason,
            ),
            (),
            clause=refused.clause,
            stage="api.system",
        )
    )


def _place(model: StructuralModel, opts: _Resolved, log: DisclosureLog,
           force_secondary: Sequence[str] = (), housing_recipe: Optional[Dict[str, Any]] = None) -> _Placement:
    """Grid, then the frame or the masonry placer, then the write-back.

    Finding 27: the system is `choose_system`'s answer and no rule of this
    module's own. When the masonry placer escalates all the way back to
    rc_frame, its abandoned attempt describes geometry that is not in the
    output, so that attempt's ladder is reported under
    `placement.masonry_attempt` rather than merged into the run's ladder, and
    the frame placer produces the delivered geometry.

    `_Placement.system` is the DELIVERED system and the single source of truth
    for it: whatever `choose_system` resolved, corrected by whichever placer
    actually ran. Both branches write it into `model.system` before returning,
    so nothing downstream has to re-derive it and the model can never disagree
    with the response.
    """
    out = _Placement()
    params = opts.masonry_params(opts.system_requested)
    decision = _masonry.choose_system(model, params)
    out.decision = decision
    out.system = decision.system

    if out.system in _MASONRY_SYSTEMS:
        # the masonry path places no frame, so the axes come from the grid
        # extractor directly; the score block below says why it carries no score
        grid = extract_axes(model, opts.frame_params(out.system))
        log.extend(grid.log.entries)
        model.axes = grid.to_model_axes()
        out.axes_source = "grid.extract_axes"
        placer = _masonry.MasonryPlacer(params)
        placement = placer.place(model, params)
        out.decision = placement.system
        if placement.system.system in _MASONRY_SYSTEMS:
            placement.write_back(model)
            out.masonry = placement
            out.system = placement.system.system
            out.valid = bool(placement.bearing_walls)
            log.extend(placement.warnings)
            out.layout_score["basis"] = (
                "the layout score is placement-frame's metrics block (finding 33); "
                "the masonry path places no frame, so no comparable score is "
                "computed and none is invented"
            )
            _disclose_fallback(out.decision, log)
            return out
        out.masonry_attempt = placement.to_dict()
        out.system = System.RC_FRAME.value

    if housing_recipe is not None:
        result = _frame.replay_housing_candidate(
            model, opts.frame_params(out.system), housing_recipe,
            _force_secondary=tuple(force_secondary), search=housing_recipe.get("search"),
        )
    else:
        result = _frame.run_frame_placement(
            model, opts.frame_params(out.system), _force_secondary=tuple(force_secondary)
        )
    result.write_back(model)
    # The DELIVERED system, written back the way `masonry.write_back` writes it
    # back on the other branch. The adapter set `model.system` from the system
    # the caller ASKED for, so after an escalation the model would otherwise
    # keep saying load_bearing_masonry over an RC frame, and the takedown's
    # bearing-wall default (analysis/takedown._wall_supports_beams) would read
    # it. `_Placement.system` is the one source of truth; this keeps the model
    # agreeing with it.
    model.system = System(out.system)
    _frame.place_lintels_for_infill(model)
    out.frame = result
    out.axes_source = "placement.frame"
    out.valid = bool(result.valid)
    log.extend(result.log.entries)
    out.layout_score.update(_score_block(result))
    out.layout_score.pop("basis", None)
    _disclose_fallback(out.decision, log)
    return out


def _footing_markers(model: StructuralModel) -> List[Footing]:
    """Unsized markers at the ground column stacks (finding 18).

    A layout response carries no sized footing because a footing is sized from
    a takedown that layout never runs. The marker says where one will go, and
    `w_ft`, `h_ft` and `depth_ft` come back null so nobody can mistake it for a
    design.
    """
    if not model.columns:
        return []
    ground = min(column.storey for column in model.columns)
    out = []  # type: List[Footing]
    seen = set()
    for column in sorted(model.columns, key=lambda c: c.id):
        if column.storey != ground:
            continue
        key = column.stack_id or column.id
        if key in seen:
            continue
        seen.add(key)
        out.append(
            Footing(
                id="ftg-" + key,
                kind=FootingKind.ISOLATED,
                supports=[column.id],
                x_m=column.x_m,
                y_m=column.y_m,
                w_m=None,
                h_m=None,
                depth_m=None,
                placed_by="api.layout_marker",
            )
        )
    return out


# ---------------------------------------------------------------------------
# loads
# ---------------------------------------------------------------------------


def _plan_dims_m(model: StructuralModel) -> Dict[str, float]:
    """Base plan dimensions in metres, from the ground storey wall network."""
    xs = []  # type: List[float]
    ys = []  # type: List[float]
    ground = min((wall.storey for wall in model.walls), default=None)
    if ground is not None:
        for wall in model.walls:
            if wall.storey != ground:
                continue
            xs.extend([wall.a[0], wall.b[0]])
            ys.extend([wall.a[1], wall.b[1]])
    if not xs:
        for slab in model.slabs:
            rect = polygon_rect(slab.polygon)
            xs.extend([rect[0], rect[0] + rect[2]])
            ys.extend([rect[1], rect[1] + rect[3]])
    if not xs:
        return {"x_m": 1.0, "y_m": 1.0}
    return {"x_m": max(max(xs) - min(xs), 1e-3), "y_m": max(max(ys) - min(ys), 1e-3)}


def _storey_weight_rows(model: StructuralModel, ledger: Dict[int, Dict[str, float]]) -> List[Dict[str, Any]]:
    """The seismic storey ledger, in the shape `build_seismic` documents.

    The takedown owns these weights; this only renames its ledger columns and
    marks the top storey as the roof so Cl 7.3.2 can drop its imposed load.
    """
    if not ledger:
        return []
    top = max(ledger)
    rows = []  # type: List[Dict[str, Any]]
    for level in sorted(ledger):
        row = ledger[level]
        basis = row.get("ll_fraction_basis_kpa")
        rows.append(
            {
                "storey": int(level),
                "z_top_m": _num(row.get("z_m")),
                "w_dl_kn": _num(row.get("w_dl_kn")),
                "w_ll_kn": _num(row.get("w_ll_kn")),
                "ll_basis_kpa": None if not basis else float(basis),
                "roof": int(level) == int(top),
            }
        )
    return rows


def _lateral_case(record: Dict[str, Any]) -> LoadCase:
    """One seismic or wind case dict turned into the LoadCase the model carries."""
    kind = CaseKind.SEISMIC if str(record["name"]).startswith("EQ") else CaseKind.WIND
    case = LoadCase(name=str(record["name"]), kind=kind)
    for force in record.get("storey_forces", []):
        case.storey.append(
            StoreyForce(
                storey=int(force["storey"]),
                fx_kn=_num(force.get("fx_kn")),
                fy_kn=_num(force.get("fy_kn")),
                z_m=_num(force.get("z_m")),
                source=str(force.get("source", record["name"])),
            )
        )
    return case


def _seismic_system_key(model: StructuralModel, opts: _Resolved) -> str:
    """IS 1893 Table 9 key for the structural system that was actually built.

    Frame ductility selects only a frame row. Masonry rows instead follow the
    delivered placer output: confined construction is its own system, while
    load-bearing masonry earns the reinforced rows only when the placer emitted
    the corresponding bands and vertical-bar runs.
    """
    delivered = model.system.value if hasattr(model.system, "value") else str(model.system)
    if delivered == System.RC_FRAME.value:
        return opts.ductility.lower()
    if delivered == System.CONFINED_MASONRY.value:
        return "confined_masonry"
    if delivered == System.LOAD_BEARING_MASONRY.value:
        placement = model.meta.get("masonry_placement")
        if not isinstance(placement, dict):
            raise ValueError(
                "load-bearing masonry has no masonry_placement record from which "
                "to resolve its IS 1893 Table 9 system"
            )
        if placement.get("vertical_bars"):
            return "urm_bands_vertical"
        if placement.get("bands"):
            return "urm_bands"
        return "urm"
    raise ValueError(
        "no IS 1893 Table 9 response-reduction row is mapped for delivered system "
        + repr(delivered)
    )


def _build_loads(
    model: StructuralModel,
    opts: _Resolved,
    log: DisclosureLog,
    ledger: Dict[int, Dict[str, float]],
) -> Tuple[LoadModel, Optional[Dict[str, Any]], Optional[Dict[str, Any]], List[Dict[str, Any]]]:
    """Dead, live, then seismic and wind when their context is there, then combos."""
    from .loads.dead import build_dead
    from .loads.live import build_live
    from .loads.seismic import SeismicContext, build_seismic
    from .loads.wind import WindContext, build_wind

    dead = build_dead(model)
    live, roof_live = build_live(model)
    loadmodel = LoadModel(cases={CASE_DL: dead, CASE_LL: live, CASE_LLR: roof_live})
    if opts.live_load_kpa is not None:
        # accepted on the request and NOT applied: loads/live.py reads IS 875-2
        # by occupancy and takes no blanket override, so saying so beats
        # pretending the number was used
        opts.mark_unapplied(
            "params.live_load_kpa",
            "v1 takes every imposed load from IS 875 (Part 2) by room occupancy; "
            "loads/live.py accepts no blanket override",
        )
        log.append(
            make_disclosure(
                "W_RELEASED_CAP",
                "params.live_load_kpa was supplied (%s kPa) but v1 takes every imposed "
                "load from IS 875 (Part 2) by room occupancy; the override is recorded "
                "in options_echo and was NOT applied"
                % (_num(opts.live_load_kpa),),
                (),
                clause="IS 875 (Part 2):1987 Table 1",
                stage="api.loads",
            )
        )

    trace = []  # type: List[Any]
    seismic_report = None  # type: Optional[Dict[str, Any]]
    wind_report = None  # type: Optional[Dict[str, Any]]
    lateral_cases = []  # type: List[Dict[str, Any]]

    if opts.analysis_mode == "gravity_only":
        log.append(
            make_disclosure(
                "N_GRAVITY_ONLY",
                "PRELIMINARY GRAVITY-LOAD OPTION COMPARISON: wind, earthquake, "
                "lateral stability, drift, ductile detailing and robustness checks "
                "were intentionally not performed; not for construction, tender, "
                "permit or safety certification",
                (),
                clause="IS 456:2000 scope; NBC 2016 Part 6",
                stage="api.loads",
            )
        )
        if opts.wind_speed_ms is not None:
            opts.mark_unapplied(
                "params.wind",
                "analysis_mode gravity_only excludes wind by explicit request",
            )
        for field in ("seismic_zone", "importance_factor", "frame_ductility"):
            if field in opts.params:
                opts.mark_unapplied(
                    "params." + field,
                    "analysis_mode gravity_only excludes earthquake actions and ductile detailing",
                )
        loadmodel.combos = _combos.generate(sorted(loadmodel.cases))
        loadmodel.trace = []
        return (loadmodel, None, None, [])

    rows = _storey_weight_rows(model, ledger)
    plan_dims = _plan_dims_m(model)
    if rows:
        seismic_system = _seismic_system_key(model, opts)
        opts.seismic_system = seismic_system
        delivered = model.system.value if hasattr(model.system, "value") else str(model.system)
        opts.origins["seismic_system"] = "derived from placed " + delivered + " reinforcement"
        ctx = SeismicContext(
            zone=opts.zone,
            soil=str(opts.soil.get("type", "II")),
            importance=opts.importance,
            system=seismic_system,
            infilled=True,
        )
        try:
            cases, seismic_report = build_seismic(
                rows, plan_dims, ctx, base_z_m=0.0, log=log, trace=trace
            )
        except (ValueError, KeyError) as error:
            log.append(
                make_disclosure(
                    "W_RELEASED_CAP",
                    "the equivalent static seismic method could not run on this model ("
                    + str(error)
                    + "); the design is gravity only and no lateral case is reported",
                    (),
                    clause="IS 1893 (Part 1):2016 Cl 7",
                    stage="api.loads",
                )
            )
            cases = []
        for record in cases:
            loadmodel.cases[record["name"]] = _lateral_case(record)
        lateral_cases.extend(cases)

    if opts.wind_speed_ms is not None:
        try:
            storeys = sorted(model.storeys, key=lambda s: s.index)
            base_z_m = min(
                (float(storey.bottom_z_m) for storey in storeys),
                default=0.0,
            )
            model_like = {
                "width_m": plan_dims["x_m"],
                "depth_m": plan_dims["y_m"],
                "storey_levels": [
                    {
                        "storey": int(storey.index),
                        "z_top_m": float(storey.bottom_z_m) + float(storey.height_m),
                    }
                    for storey in storeys
                ],
                "base_z_m": base_z_m,
            }
            ctx = WindContext(
                Vb_ms=_num(opts.wind_speed_ms, 0.0),
                terrain_category=int(_num(opts.wind_terrain, 2)),
            )
            cases, wind_report = build_wind(model_like, ctx, log=log, trace=trace)
        except (ValueError, KeyError, TypeError) as error:
            log.append(
                make_disclosure(
                    "W_WIND_STATIC_LIMIT",
                    "the static wind method could not run on this model ("
                    + str(error)
                    + "); no wind case is reported",
                    (),
                    clause="IS 875 (Part 3):2015",
                    stage="api.loads",
                )
            )
            cases = []
        for record in cases:
            loadmodel.cases[record["name"]] = _lateral_case(record)
        lateral_cases.extend(cases)

    loadmodel.combos = _combos.generate(sorted(loadmodel.cases))
    loadmodel.trace = [_plain(entry) for entry in trace]
    return (loadmodel, seismic_report, wind_report, lateral_cases)


# ---------------------------------------------------------------------------
# analysis
# ---------------------------------------------------------------------------


def _gravity_ledger(model: StructuralModel, opts: _Resolved) -> Dict[int, Dict[str, float]]:
    """The storey weight ledger, from a gravity-only takedown pass.

    `build_seismic` needs the weight of each storey and only the takedown knows
    it, so the takedown runs once here on the gravity roster to weigh the
    building and once again afterwards over the full combination roster. This is
    a second pass, not a second method: the numbers come from the one takedown.
    """
    from .analysis import takedown
    from .loads.dead import build_dead
    from .loads.live import build_live

    live, roof_live = build_live(model)
    probe = LoadModel(
        cases={CASE_DL: build_dead(model), CASE_LL: live, CASE_LLR: roof_live}
    )
    probe.combos = _combos.generate(sorted(probe.cases))
    result = takedown.run(model, probe)
    return dict((int(level), dict(row)) for level, row in result.storey_ledger.items())


def _foundation_loads(result: Any) -> Tuple[Dict[str, float], Dict[str, float]]:
    """Takedown footing loads, adapted to the plain floats foundations documents.

    `layout_foundations` documents `wall_loads[wall_id] = n_service_kn_per_m` and
    `column_loads[id] = p_service_kn`; the takedown hands over a dict per element
    with the dead and reduced-imposed components apart. The service value is
    their sum, which is what a footing is sized on.
    """
    footing_loads = getattr(result, "footing_loads", {}) or {}
    columns = {}  # type: Dict[str, float]
    for key, row in sorted((footing_loads.get("columns") or {}).items()):
        columns[str(key)] = _num(row.get("p_dl_kn")) + _num(row.get("p_ll_reduced_kn"))
    walls = {}  # type: Dict[str, float]
    for key, row in sorted((footing_loads.get("walls") or {}).items()):
        walls[str(key)] = _num(row.get("n_dl_kn_m")) + _num(row.get("n_ll_kn_m"))
    return (columns, walls)


def _storey_shears(lateral_cases: Sequence[Dict[str, Any]]) -> Dict[str, Dict[int, float]]:
    """The worst storey shear per direction across the positive lateral cases.

    Only the "+" case of a direction is read: the minus case is the same
    distribution with the sign in its name, and adding both would cancel.
    """
    from .analysis import diaphragm

    out = {"x": {}, "y": {}}  # type: Dict[str, Dict[int, float]]
    for record in sorted(lateral_cases, key=lambda item: str(item.get("name", ""))):
        if int(_num(record.get("sign"), 1)) < 0:
            continue
        one = diaphragm.storey_shears_from_case(record)
        for direction in ("x", "y"):
            for storey, value in sorted(one[direction].items()):
                out[direction][storey] = max(out[direction].get(storey, 0.0), float(value))
    return out


def _centres_of_mass(model: StructuralModel) -> Dict[int, Tuple[float, float]]:
    """Slab-area centroid per storey, not a storey mass-centroid ledger."""
    acc = {}  # type: Dict[int, List[float]]
    for slab in model.slabs:
        rect = polygon_rect(slab.polygon)
        area = rect[2] * rect[3]
        if area <= 0.0:
            continue
        row = acc.setdefault(int(slab.storey), [0.0, 0.0, 0.0])
        row[0] += area * (rect[0] + 0.5 * rect[2])
        row[1] += area * (rect[1] + 0.5 * rect[3])
        row[2] += area
    return dict(
        (level, (row[0] / row[2], row[1] / row[2]))
        for level, row in sorted(acc.items())
        if row[2] > 0.0
    )


# ---------------------------------------------------------------------------
# member design
# ---------------------------------------------------------------------------


def _slab_design_context(
    base: Dict[str, Any], loadmodel: Optional[LoadModel], panel_id: str
) -> Dict[str, Any]:
    """Per-panel design context with the unfactored dead/imposed split.

    The frozen SlabLoad contract intentionally carries combined pressures only.
    The load model still owns the unfactored area rows, so the orchestrator
    sums those rows here instead of applying one building-wide live pressure to
    mixed occupancies and roof panels.
    """
    context = dict(base)
    if loadmodel is None:
        return context

    def _sum(case_names: Sequence[str]) -> Tuple[float, bool]:
        total = 0.0
        found = False
        for case_name in case_names:
            case = loadmodel.cases.get(case_name)
            if case is None:
                continue
            for area in case.area:
                if str(area.panel_id) != str(panel_id):
                    continue
                total += float(area.q_kpa)
                found = True
        return (total, found)

    dead, has_dead = _sum((CASE_DL,))
    imposed, has_imposed = _sum((CASE_LL, CASE_LLR))
    if has_dead:
        context["dead_kpa"] = dead
    if has_imposed:
        context["imposed_kpa"] = imposed
    return context


def _promote_result_errors(result: Any, log: DisclosureLog) -> None:
    """Move result-local ERROR disclosures onto the pipeline blocking ladder."""
    extras = getattr(result, "extras", {}) or {}
    for payload in extras.get("disclosures", ()) or ():
        if not isinstance(payload, dict):
            continue
        entry = Disclosure.from_dict(payload)
        if Severity(entry.severity) == Severity.ERROR:
            log.append(entry)


def _design_members(
    model: StructuralModel,
    analysis: Any,
    lateral: Any,
    opts: _Resolved,
    system: str,
    log: DisclosureLog,
    loadmodel: Optional[LoadModel] = None,
) -> List[Any]:
    """Design every element the analysis carries a demand for.

    The finding 20 converters are the only designer inputs: `to_beam_forces`,
    `to_column_forces` and `to_slab_load` turn an envelope into the demand
    shape, and the footing designer reads the takedown's own footing loads
    through `FootingLoads.from_envelope`.

    This dispatch exists instead of `design.rcc.run_rcc_design` because that
    entry calls `design_slab(load, panel)` and `design_footing(loads, geom)`
    with the arguments swapped relative to the shipped signatures; the sibling
    is left alone and the adaptation lives here (see the module docstring).
    """
    from .analysis import to_beam_forces, to_column_forces, to_slab_load
    from .design.common import DesignResult, m_to_mm
    from .design.rcc.beams import design_beam
    from .design.rcc.columns import COLUMN_ROLE_FRAME, COLUMN_ROLE_TIE, design_column
    from .design.rcc import (
        beam_support_condition,
        design_stair_flight,
        stair_design_inputs,
        stair_flights_from_model,
        strip_geometry_from_model,
    )
    from .design.rcc.footings import (
        STRIP_VERDICT_PLAIN,
        ColumnStub,
        CombinedGeometry,
        FootingLoads,
        PadGeometry,
        StripLoads,
        design_combined_footing,
        design_footing,
        design_strip_footing,
    )
    from .design.rcc.slabs import design_slab

    ctx = opts.design_options()
    results = []  # type: List[Any]

    if system in _MASONRY_SYSTEMS:
        from .design.masonry import design_masonry_walls

        results.extend(
            design_masonry_walls(
                model,
                analysis,
                lateral,
                options={
                    "zone": opts.zone,
                    "importance": opts.importance,
                    "assumed_mortar_grade": opts.mortar_grade,
                    "assumed_unit_strength_mpa": opts.masonry_unit_mpa,
                    "soft_soil": bool(opts.soil.get("soft", False)),
                },
            )
        )

    envelopes = getattr(analysis, "envelopes", {}) or {}
    beams = dict((beam.id, beam) for beam in model.beams)
    columns = dict((column.id, column) for column in model.columns)
    slabs = dict((slab.id, slab) for slab in model.slabs)
    footings = dict((footing.id, footing) for footing in model.footings)
    column_by_stack = {}  # type: Dict[str, Any]
    for column in sorted(model.columns, key=lambda c: (c.storey, c.id)):
        column_by_stack.setdefault(column.stack_id or column.id, column)

    for element_id in sorted(envelopes):
        envelope = envelopes[element_id]
        kind = getattr(envelope, "element_type", "")
        if kind == "beam":
            beam = beams.get(element_id)
            if beam is None or not beam.span_m():
                continue
            beam_forces = to_beam_forces(envelope)
            analysis_span_m = float(getattr(envelope, "length_m", 0.0) or beam.span_m())
            results.append(
                design_beam(
                    beam_forces,
                    {
                        "element_id": element_id,
                        "b_mm": m_to_mm(beam.width_m),
                        "D_mm": m_to_mm(beam.depth_m if beam.depth_m else 0.3),
                        # The support-to-support span used by takedown is the
                        # design geometry.  A display/wall fragment can be
                        # shorter and must never make the same demand appear
                        # easier to resist.
                        "span_mm": m_to_mm(analysis_span_m),
                        "storey": int(beam.storey),
                        "support": beam_support_condition(beam, beam_forces),
                    },
                    ctx,
                )
            )
        elif kind == "column":
            column = columns.get(element_id)
            if column is None:
                continue
            height_m = envelope.length_m
            if not height_m:
                storey = model.storey(int(column.storey))
                height_m = storey.height_m if storey is not None else 3.0
            results.append(
                design_column(
                    to_column_forces(envelope),
                    {
                        "element_id": element_id,
                        "b_mm": m_to_mm(column.width_m),
                        "depth_mm": m_to_mm(column.depth_m),
                        "height_mm": m_to_mm(height_m),
                        "clear_height_mm": m_to_mm(height_m),
                        "storey": int(column.storey),
                        # What the placer says this column IS. Only the
                        # orchestrator sees both sides, so the translation from
                        # placement provenance to design role happens here and
                        # nowhere else: an IS 4326 confining column is not a
                        # frame column and the ductile overlay must not size it
                        # with the IS 13920 Cl 7.1 frame geometry clause.
                        "role": (
                            COLUMN_ROLE_TIE
                            if _masonry.is_tie_column(column)
                            else COLUMN_ROLE_FRAME
                        ),
                    },
                    ctx,
                )
            )
        elif kind == "slab":
            panel = slabs.get(element_id)
            if panel is None:
                continue
            slab_result = design_slab(
                panel,
                to_slab_load(envelope),
                _slab_design_context(ctx, loadmodel, element_id),
            )
            _promote_result_errors(slab_result, log)
            results.append(slab_result)

    # Inclined flights are placed under frame-placement meta, not model.slabs,
    # and takedown emits no flight envelope. Give each one the shared synthetic
    # IS 875 stair occupancy input; the stair designer adds its own dead load.
    stairs = stair_flights_from_model(model)
    if stairs:
        stair_load, stair_ctx = stair_design_inputs(ctx)
        for stair in stairs:
            stair_result = design_stair_flight(stair, stair_load, stair_ctx)
            _promote_result_errors(stair_result, log)
            results.append(stair_result)

    # Footings are walked off the model, not off the envelope index: the
    # takedown envelopes one footing per column stack, while `layout_foundations`
    # may have merged two stacks into a combined rectangle that has no envelope
    # of its own, and a wall strip is keyed by its walls rather than by a stack
    # at all. The service loads come from the takedown's own footing ledger.
    stack_loads, wall_loads = _foundation_loads(analysis)
    walls_by_id = dict((wall.id, wall) for wall in model.walls)
    plain_strips = []  # type: List[str]
    footing_envelopes = dict(
        (element_id, envelopes[element_id])
        for element_id in envelopes
        if getattr(envelopes[element_id], "element_type", "") == "footing"
    )
    straps_by_footing = {}  # type: Dict[str, Tuple[str, float]]
    for strap in footings.values():
        strap_kind = str(getattr(strap.kind, "value", strap.kind))
        if strap_kind != "strap":
            continue
        ends = [str(one) for one in (getattr(strap, "supports", None) or [])]
        if len(ends) != 2:
            continue
        span = math.hypot(
            abs(float(getattr(strap, "w_m", 0.0) or 0.0)),
            abs(float(getattr(strap, "h_m", 0.0) or 0.0)),
        )
        straps_by_footing.setdefault(ends[0], (ends[1], span))
        straps_by_footing.setdefault(ends[1], (ends[0], span))

    def _stub(source: Any) -> Any:
        return ColumnStub(
            column_id=str(source.id),
            bx_mm=m_to_mm(source.width_m),
            dy_mm=m_to_mm(source.depth_m),
            x_m=float(source.x_m),
            y_m=float(source.y_m),
        )

    def _loads_for(source: Any, element_id: str) -> Any:
        envelope = footing_envelopes.get(element_id)
        if envelope is not None:
            return FootingLoads.from_envelope(envelope)
        key = source.stack_id or source.id
        return FootingLoads(
            p_service_kn=_num(stack_loads.get(key)), column_id=str(source.id)
        )

    for element_id in sorted(footings):
        footing = footings[element_id]
        kind = str(getattr(footing.kind, "value", footing.kind))
        # A strip carries a WALL, not a column, so it is routed before the column
        # roster is even consulted: its supports are wall ids and looking them up
        # among the columns would find nothing and drop the element.
        if kind == "strip":
            carried = sorted(
                (str(wall_id), _num(wall_loads.get(str(wall_id))))
                for wall_id in footing.supports
                if str(wall_id) in walls_by_id and str(wall_id) in wall_loads
            )
            if not carried:
                continue  # no wall, or no line load: _disclose_undesigned names it
            worst = max(carried, key=lambda row: (row[1], row[0]))
            result = design_strip_footing(
                strip_geometry_from_model(footing, walls_by_id),
                StripLoads(n_service_kn_per_m=worst[1], wall_id=worst[0]),
                opts.soil,
                ctx,
            )
            if str(result.section.get("verdict", "")) == STRIP_VERDICT_PLAIN:
                plain_strips.append(element_id)
            results.append(result)
            continue
        supports = []  # type: List[Any]
        unresolved = []  # type: List[str]
        declared_supports = sorted(footing.supports)
        for support in declared_supports:
            found = columns.get(support) or column_by_stack.get(support)
            if found is not None:
                supports.append(found)
            else:
                unresolved.append(str(support))
        if kind == "combined":
            if unresolved or len(supports) < 2:
                failure = DesignResult(element_id=element_id, element_type="footing")
                failure.section.update(
                    {
                        "kind": "combined",
                        "declared_support_count": len(declared_supports),
                        "resolved_support_count": len(supports),
                    }
                )
                reason = (
                    "combined footing " + element_id + " declares " + str(len(declared_supports))
                    + " supports but only " + str(len(supports)) + " resolved"
                )
                if unresolved:
                    reason += "; unresolved: " + ", ".join(unresolved)
                reason += "; refusing to design a subset"
                results.append(
                    failure.fail_with(
                        "combined footing support roster",
                        reason,
                        clause="foundation support routing completeness",
                        demand=float(len(declared_supports)),
                        capacity=float(len(supports)),
                        units="supports",
                    )
                )
                continue
            geometry = CombinedGeometry(
                element_id=element_id,
                columns=tuple(_stub(one) for one in supports),
                placed_bx_m=footing.w_m,
                placed_ly_m=footing.h_m,
            )
            results.append(
                design_combined_footing(
                    geometry,
                    [_loads_for(one, element_id) for one in supports],
                    opts.soil,
                    ctx,
                )
            )
            continue
        if not supports:
            continue
        source = supports[0]
        strap_partner, strap_span_m = straps_by_footing.get(element_id, ("", 0.0))
        geometry = PadGeometry(
            element_id=element_id,
            column=_stub(source),
            col_offset_x_m=float(source.x_m) - float(footing.x_m),
            col_offset_y_m=float(source.y_m) - float(footing.y_m),
            placed_bx_m=footing.w_m,
            placed_ly_m=footing.h_m,
            kind="strap" if strap_partner else kind,
            strap_partner_id=strap_partner,
            strap_span_m=strap_span_m,
        )
        results.append(design_footing(geometry, _loads_for(source, element_id), opts.soil, ctx))

    if plain_strips:
        # A plain verdict is an ANSWER, not an omission, and a reader who sees a
        # footing ship with no reinforcement has to be able to tell the two
        # apart: this is the code that says "designed, and it needs no steel".
        log.append(
            make_disclosure(
                "N_PLAIN_CONCRETE_FOOTING",
                "%d wall strip footing(s) came out inside the IS 456 Cl 34.1.3 plain concrete "
                "projection rule; they are designed, they carry a bearing and a projection check, "
                "and no reinforcement is required in them" % len(plain_strips),
                sorted(plain_strips),
                clause="IS 456 Cl 34.1.3",
                stage="api.design",
            )
        )

    results.sort(key=lambda item: (str(getattr(item, "element_type", "")), str(getattr(item, "element_id", ""))))
    return results


def _design_types_for_class(kind: str) -> Tuple[str, ...]:
    """Every `DesignResult.element_type` that counts as designing this class.

    Spec 06 freezes the masonry wall designer's type as `masonry_wall`
    (design/masonry.ELEMENT_TYPE_WALL), not the bare class word, so a coverage
    lookup on "wall" alone finds nothing and a fully designed masonry house
    reads as fully undesigned. The value is read from the design layer rather
    than restated here so the two cannot drift apart, and it is read late for
    the same reason every other design import in this module is: a layout call
    must not pay for the design layer's YAML.
    """
    if kind == "stair":
        # The existing stair mode deliberately returns element_type="slab";
        # identity, not the shared designer type, separates flights from panels.
        return ("slab",)
    if kind != "wall":
        return (kind,)
    from .design.masonry import ELEMENT_TYPE_WALL

    return ("wall", str(ELEMENT_TYPE_WALL))


def _design_ids(kind: str, element: Any) -> set:
    """Every `element_id` a design result may carry for this placed element.

    design/masonry.py designs one wall segment PER STOREY and keys the result
    `<wall_id>@s<storey>` (design/masonry.WallDemand.element_id), so the storey
    stays in the key and nothing else counts for a wall that has one: a stack
    designed on storey 0 and not on storey 1 reads as half covered, never as
    covered. Accepting the bare id as well would be the one way back to a
    silently over-reported coverage, so it is not accepted; a designer that
    ever keys a whole wall in one row reads here as an undesigned wall, which
    is the safe direction to be wrong in.
    """
    element_id = (
        str(element.get("id", ""))
        if isinstance(element, dict)
        else str(getattr(element, "id", ""))
    )
    storey = (
        element.get("storey")
        if isinstance(element, dict)
        else getattr(element, "storey", None)
    )
    if kind == "wall" and storey is not None:
        return {element_id + "@s" + str(int(storey))}
    return {element_id}


def _placed_design_id(kind: str, element: Any) -> str:
    """The deterministic primary id for one placed coverage roster entry."""
    return sorted(_design_ids(kind, element))[0]


def _designed_ids_by_class(results: Sequence[Any]) -> Dict[str, set]:
    """class -> every design result id under it, keyed by element_type."""
    by_type = {}  # type: Dict[str, set]
    for result in results:
        kind = str(getattr(result, "element_type", ""))
        by_type.setdefault(kind, set()).add(str(getattr(result, "element_id", "")))

    out = {}  # type: Dict[str, set]
    for kind in _COVERAGE_CLASSES:
        found = set()
        for name in _design_types_for_class(kind):
            found |= by_type.get(name, set())
        out[kind] = found
    return out


def _disclose_undesigned(
    model: StructuralModel,
    results: Sequence[Any],
    system: str,
    log: DisclosureLog,
) -> List[str]:
    """Name every element of a designed class that came back without a design.

    Disclose, never hide: an element the placer put down and the design layer
    did not reach must say so by id, not go missing between two blocks. The code
    is `N_ELEMENT_UNDESIGNED`, "placed and quantified, but no designer reached
    it", which is exactly the condition. It used to borrow
    `N_SHAFT_WALL_UNDESIGNED`, whose registry text is "shaft walls carry a
    prescription, not a design": that is a different statement about a different
    class, and a wrong code in a shipped response is worse than a missing design
    that says it is missing.
    """
    designed = _designed_ids_by_class(results)
    blocked = set()
    for entry in log.entries:
        if Severity(entry.severity) == Severity.ERROR:
            blocked.update(str(one) for one in entry.element_ids)

    from .design.rcc import stair_flights_from_model

    slots = {
        "column": model.columns,
        "beam": model.beams,
        "slab": model.slabs,
        "stair": stair_flights_from_model(model),
        "footing": model.footings,
    }
    if system in _MASONRY_SYSTEMS:
        slots["wall"] = [wall for wall in model.walls if wall.bearing]

    missing = []  # type: List[str]
    labels = []  # type: List[str]
    for kind in sorted(slots):
        ids = sorted(
            _placed_design_id(kind, element)
            for element in slots[kind]
            if not (_design_ids(kind, element) & designed[kind])
            and _placed_design_id(kind, element) not in blocked
        )
        if ids:
            missing.extend(ids)
            labels.append("%d %s(s)" % (len(ids), kind))
    if missing:
        log.append(
            make_disclosure(
                "N_ELEMENT_UNDESIGNED",
                "no v1 designer reached " + ", ".join(labels) + "; they ship with the "
                "placement geometry and are quantified, but they carry no design and no "
                "reinforcement was computed for them",
                sorted(missing),
                stage="api.design",
            )
        )
    return sorted(missing)


def _audit_designed_foundation_geometry(
    model: StructuralModel,
    results: Sequence[Any],
    log: DisclosureLog,
) -> None:
    """Recheck soil rectangles after the member designer has enlarged them.

    Foundation placement checks its seed rectangles, while the RC designer may
    grow `bx_mm`/`ly_mm`. Ranking a candidate without repeating overlap and
    no-cross-boundary checks on those final rectangles would validate different
    geometry from the BOQ and drawing.
    """
    footing_by_id = {str(row.id): row for row in model.footings}
    rectangles = []  # type: List[Tuple[str, Tuple[float, float, float, float]]]
    for result in results:
        if str(getattr(result, "element_type", "")) != "footing":
            continue
        if str(getattr(result, "status", "")) == "fail":
            continue
        element_id = str(getattr(result, "element_id", ""))
        footing = footing_by_id.get(element_id)
        if footing is None or str(getattr(footing.kind, "value", footing.kind)) == "strap":
            continue
        section = getattr(result, "section", {}) or {}
        width_m = _num(section.get("bx_mm") or section.get("length_mm")) / 1000.0
        height_m = _num(section.get("ly_mm") or section.get("width_mm")) / 1000.0
        if width_m <= 0.0:
            width_m = _num(getattr(footing, "w_m", 0.0))
        if height_m <= 0.0:
            height_m = _num(getattr(footing, "h_m", 0.0))
        if width_m <= 0.0 or height_m <= 0.0:
            continue
        rect = (
            float(footing.x_m) - 0.5 * width_m,
            float(footing.y_m) - 0.5 * height_m,
            width_m,
            height_m,
        )
        rectangles.append((element_id, rect))

    for index, (left_id, left) in enumerate(rectangles):
        for right_id, right in rectangles[index + 1:]:
            dx = min(left[0] + left[2], right[0] + right[2]) - max(left[0], right[0])
            dy = min(left[1] + left[3], right[1] + right[3]) - max(left[1], right[1])
            if dx <= 1e-6 or dy <= 1e-6:
                continue
            log.append(
                make_disclosure(
                    "W_FOOTING_OVERLAP",
                    "designed footing rectangles %s and %s overlap by %.3f m2 after member sizing; "
                    "the BOQ/drawing rectangles share bearing soil and require engineer resolution"
                    % (left_id, right_id, dx * dy),
                    [left_id, right_id],
                    clause="IS6403:1981",
                    stage="api.design.foundation_geometry",
                )
            )

    boundary_lines = _foundations._boundary_lines(model)
    for element_id, rect in rectangles:
        if not boundary_lines or not _foundations._crosses(rect, boundary_lines):
            continue
        log.append(
            make_disclosure(
                "W_ECCENTRIC_COLUMN",
                "designed footing %s is %.3f m x %.3f m after sizing and crosses an explicit "
                "plot/party no-cross boundary; placement seed compliance is no longer sufficient"
                % (element_id, rect[2], rect[3]),
                [element_id],
                clause="IS6403:1981",
                stage="api.design.foundation_geometry",
            )
        )


def _design_coverage(model: StructuralModel, results: Sequence[Any], system: str) -> Dict[str, Any]:
    """Which placed classes were designed, which were not, and why.

    An element class the v1 design layer does not own (lintels and seismic bands
    in the frame path, cores) is reported here rather than left as a silent gap;
    no registry code fits "placed but out of scope", so the absence is stated in
    the response instead of forced onto the ladder.
    """
    designed = _designed_ids_by_class(results)

    from .design.rcc import stair_flights_from_model

    placed = {
        "column": list(model.columns),
        "beam": list(model.beams),
        "slab": list(model.slabs),
        "stair": stair_flights_from_model(model),
        "footing": list(model.footings),
        "wall": [wall for wall in model.walls if wall.bearing],
        "lintel": list(model.lintels),
        "band": list(model.bands),
    }
    owned = set(_FRAME_DESIGN_CLASSES)
    if system in _MASONRY_SYSTEMS:
        owned |= set(_MASONRY_DESIGN_CLASSES)

    out = {}  # type: Dict[str, Any]
    for kind in sorted(placed):
        elements = sorted(
            placed[kind], key=lambda element: _placed_design_id(kind, element)
        )
        missing = sorted(
            _placed_design_id(kind, element)
            for element in elements
            if not (_design_ids(kind, element) & designed[kind])
        )
        row = {
            "placed": len(elements),
            "designed": len(elements) - len(missing),
            "undesigned": missing[:50],
            "undesigned_count": len(missing),
        }
        if kind not in owned:
            row["reason"] = (
                "the v1 design layer owns "
                + ", ".join(sorted(owned))
                + "; this class is placed and quantified but not designed"
            )
        elif missing:
            row["reason"] = "no analysis demand reached these elements"
        out[kind] = row
    return out


def _referrals(results: Sequence[Any]) -> Dict[str, List[Dict[str, Any]]]:
    """Design referrals grouped by action, in id order."""
    out = {}  # type: Dict[str, List[Dict[str, Any]]]
    for result in sorted(results, key=lambda item: str(getattr(item, "element_id", ""))):
        for referral in getattr(result, "referrals", ()) or ():
            action = str(referral.get("action", ""))
            out.setdefault(action, []).append(
                {
                    "element_id": str(getattr(result, "element_id", "")),
                    "element_type": str(getattr(result, "element_type", "")),
                    "action": action,
                    "detail": _plain(referral.get("detail")),
                }
            )
    return out


def _referrals_wire(
    referrals: Dict[str, List[Dict[str, Any]]], compact: bool
) -> Dict[str, Any]:
    """`design.referrals` for the wire; the unactionable actions fold at compact.

    An action this orchestrator can act on (`ACTIONABLE_REFERRALS`) always ships
    row by row, because the re-pass is about to consume it and a reader must be
    able to see what it did. An action nobody executes -- `joint_check_manual` is
    one note repeated over every joint -- folds at compact into its count, its
    element ids and the first row's detail, which is what the repeated rows say.
    """
    out = {}  # type: Dict[str, Any]
    for action in sorted(referrals):
        rows = referrals[action]
        if not compact or action in ACTIONABLE_REFERRALS:
            out[action] = [dict(row) for row in rows]
            continue
        out[action] = {
            "action": action,
            "count": len(rows),
            "element_ids": sorted({str(row.get("element_id", "")) for row in rows}),
            "detail": _plain(rows[0].get("detail")) if rows else None,
            "rows_elided": True,
            "detail_note": (
                "every row of this action carries the same note; ask for "
                "output.detail=" + DETAIL_FULL + " for one row per element"
            ),
        }
    return out


def _panel_ids_from(referrals: Sequence[Dict[str, Any]]) -> List[str]:
    """The slab ids an `add_secondary_beams` referral names."""
    return sorted({str(item["element_id"]) for item in referrals if item.get("element_id")})


def _design_wire(results: Sequence[Any], trace: bool) -> List[Dict[str, Any]]:
    """The DesignResult dicts for the wire, without their clause traces by default.

    Size discipline (spec 07 section 3): a member's trace is roughly forty times
    the rest of its result, so `output.trace` gates it. Turning it on changes no
    number, only how much of the working the response shows.
    """
    out = []  # type: List[Dict[str, Any]]
    for result in results:
        row = result.to_dict()
        if not trace:
            row["trace"] = []
            row["trace_elided"] = True
        out.append(row)
    return out


_CODE_SET_ORDER = (
    "IS 456:2000",
    "IS 875-1:1987",
    "IS 875-2:1987",
    "IS 875-3:2015",
    "IS 1893-1:2016",
    "IS 13920:2016",
    "IS 1905:1987",
    "IS 4326:1993",
)


def _emitted_code(value: Any) -> Optional[str]:
    """Return the published code prefix from one emitted clause or source."""
    text = str(value or "").strip()
    compact = text.replace(" ", "")
    if text.startswith("IS 456") or compact.startswith("IS456"):
        return "IS 456:2000"
    if text.startswith("IS 875-1"):
        return "IS 875-1:1987"
    if text.startswith("IS 875-2"):
        return "IS 875-2:1987"
    if text.startswith("IS 875-3"):
        return "IS 875-3:2015"
    if text.startswith("IS 1893-1") or compact.startswith("IS1893-1"):
        return "IS 1893-1:2016"
    if text.startswith("IS 13920") or compact.startswith("IS13920"):
        return "IS 13920:2016"
    if text.startswith("IS 1905") or compact.startswith("IS1905"):
        return "IS 1905:1987"
    if text.startswith("IS 4326") or compact.startswith("IS4326"):
        return "IS 4326:1993"
    return None


def _code_strings(value: Any, keys: Sequence[str]) -> List[str]:
    """Code-bearing values beneath `value`, in deterministic tree order."""
    wanted = set(str(key) for key in keys)
    found = []  # type: List[str]
    if isinstance(value, dict):
        for key in sorted(value):
            item = value[key]
            if key in wanted and isinstance(item, str):
                found.append(item)
            if isinstance(item, (dict, list, tuple)):
                found.extend(_code_strings(item, keys))
    elif isinstance(value, (list, tuple)):
        for item in value:
            found.extend(_code_strings(item, keys))
    return found


def _design_code_set(
    design_rows: Sequence[Dict[str, Any]], load_wire: Dict[str, Any], seismic: Any
) -> List[str]:
    """The codes actually cited by this design, never an imported-code roster."""
    cited = set()  # type: set
    for row in design_rows:
        for check in row.get("checks") or ():
            if isinstance(check, dict):
                code = _emitted_code(check.get("clause"))
                if code:
                    cited.add(code)
        for code_text in _code_strings(row.get("prescription"), ("code", "clause")):
            code = _emitted_code(code_text)
            if code:
                cited.add(code)
    for code_text in _code_strings(load_wire, ("source",)):
        code = _emitted_code(code_text)
        if code:
            cited.add(code)
    for code_text in _code_strings(seismic, ("code", "clause", "ref", "source")):
        code = _emitted_code(code_text)
        if code:
            cited.add(code)
    return [code for code in _CODE_SET_ORDER if code in cited]


#: What a compact design row carries out of the full DesignResult, verbatim.
#: `materials` is deliberately not here: it is the same two grades on every RC
#: member and `design.materials` states them once for the whole run.
_COMPACT_ROW_KEEP = ("element_id", "element_type", "status")

#: Masonry uses these small top-level extension blocks instead of an RC bar
#: schedule: `masonry` carries the wall check waterfall and `prescription` the
#: adopted material and escalation. They are actionable even on a passing row,
#: so compact preserves them while the larger RC, slab and footing extras stay
#: at full as DETAIL_POLICY records.
_COMPACT_EXTRA_KEEP = ("masonry", "prescription")

#: The NUMERIC section keys a compact row keeps: the dimensions a reader acts on
#: and builds from. Every other number in `DesignResult.section` -- effective
#: depths, clear spans, panel spans, bearing pressures, table case numbers -- is
#: working the designer computed on the way to those dimensions, and `full`
#: restores it. Non-numeric entries are kept whatever they are called, because
#: they are descriptors and identities (`wall_id`, `support`, `kind`,
#: `short_axis`, `two_way`), not working, and they cost almost nothing.
_COMPACT_SECTION_KEEP = (
    "D_mm",
    "b_mm",
    "bx_mm",
    "cover_mm",
    "depth_mm",
    "ly_mm",
    "thickness_mm",
    "waist_mm",
)


def _compact_section(section: Any) -> Dict[str, Any]:
    """The dimensions and descriptors out of a DesignResult section.

    Integral floats serialize as integers at the compact level. JSON's number
    type preserves the exact value, while avoiding two redundant characters on
    thousands of whole-millimetre dimensions in a large frame response.
    """
    if not isinstance(section, dict):
        return {}
    out = {}  # type: Dict[str, Any]
    for key in sorted(section):
        value = section[key]
        numeric = isinstance(value, (int, float)) and not isinstance(value, bool)
        if not numeric or key in _COMPACT_SECTION_KEEP:
            if isinstance(value, float) and value.is_integer():
                value = int(value)
            out[key] = value
    return out


def _governing_row(row: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The governing check, as the row it came from, in a one-item list.

    "The governing check of every element" means the row, not the name: the
    clause, the demand, the capacity, the unit and the ratio. `governing_check`
    names it and `utilization_max` repeats its ratio, both DesignResult's own
    keys, and `checks_total` says how many rows `full` would have shown. A
    designer that named no check contributes its worst row instead, so the list
    is empty only when the designer wrote no checks at all.
    """
    checks = [check for check in (row.get("checks") or []) if isinstance(check, dict)]
    if not checks:
        return []
    named = str(row.get("governing_check", ""))
    for check in checks:
        if named and str(check.get("name", "")) == named:
            return [dict(check)]
    return [dict(max(checks, key=lambda check: _num(check.get("ratio"))))]


def _compact_design_row(row: Dict[str, Any], codes: Sequence[str]) -> Dict[str, Any]:
    """One design row at `compact`: what a reader acts on, and nothing else.

    Exactly the fields the size regime promises: the section dimensions and
    descriptors, the reinforcement as the display string the element card carries
    (`report.reinforcement_text`, a lossless read of `bars` + `stirrups` for a
    reader and a twentieth of the bytes), the status, the utilization, the
    disclosure codes naming this element, and the GOVERNING CHECK as the row it
    came from. `checks_total` says how many rows `full` would have shown, and the
    designer's own warnings ride whole because they are short and they are what
    a reader chases. Referrals are not repeated here: `design.referrals` groups
    every one of them by action and names every element id.
    """
    out = {}  # type: Dict[str, Any]
    for key in _COMPACT_ROW_KEEP:
        if key in row:
            out[key] = row[key]
    out["section"] = _compact_section(row.get("section"))
    out["reinforcement"] = R.reinforcement_text(row.get("bars") or (), row.get("stirrups") or ())
    out["governing_check"] = str(row.get("governing_check", ""))
    out["checks"] = _governing_row(row)
    out["utilization_max"] = row.get("utilization_max", 0.0)
    out["checks_total"] = len([one for one in (row.get("checks") or []) if isinstance(one, dict)])
    if codes:
        out["disclosure_codes"] = list(codes)
    if row.get("warnings"):
        out["warnings"] = list(row["warnings"])
    for key in _COMPACT_EXTRA_KEEP:
        if key in row:
            out[key] = row[key]
    out["trace"] = []
    out["trace_elided"] = True
    out["detail"] = DETAIL_COMPACT
    return out


def _project_design_rows(
    rows: Sequence[Dict[str, Any]],
    detail: str,
    codes_by_element: Dict[str, List[str]],
    keep_full: Sequence[str],
) -> List[Dict[str, Any]]:
    """`structural_model.design` at the requested level.

    `full` passes every row through untouched. `compact` abbreviates the passing
    members and leaves the blocked and the failed ones whole, because those are
    the rows a user must read before doing anything with this design.
    """
    if detail != DETAIL_COMPACT:
        return [dict(row) for row in rows]
    whole = set(str(one) for one in keep_full)
    out = []  # type: List[Dict[str, Any]]
    for row in rows:
        element_id = str(row.get("element_id", ""))
        if element_id in whole or str(row.get("status", "")) == "fail":
            kept = dict(row)
            kept["detail"] = DETAIL_FULL
            out.append(kept)
            continue
        out.append(_compact_design_row(row, codes_by_element.get(element_id, ())))
    return out


def _codes_by_element(log: DisclosureLog) -> Dict[str, List[str]]:
    """element id -> the registry codes naming it, in ladder order."""
    out = {}  # type: Dict[str, List[str]]
    for entry in log.sorted_entries():
        for element_id in entry.element_ids:
            bucket = out.setdefault(str(element_id), [])
            if str(entry.code) not in bucket:
                bucket.append(str(entry.code))
    return out


# ---------------------------------------------------------------------------
# the compact projections of the stage outputs (the module docstring's tier 3)
# ---------------------------------------------------------------------------


def _elide(block: Dict[str, Any], key: str, ref: str, reason: str) -> None:
    """Replace one bulky list or dict with an empty one that says where it went.

    Never a silent removal: the emptied key keeps its type so a client's parser
    does not change shape, and three siblings say how many rows there were, what
    replaces them and how to get them back.
    """
    value = block.get(key)
    if value is None:
        return
    total = len(value) if isinstance(value, (list, dict, tuple)) else 1
    block[key] = {} if isinstance(value, dict) else []
    block[key + "_total"] = int(total)
    block[key + "_elided"] = True
    block[key + "_ref"] = ref
    block[key + "_elided_reason"] = reason


_ELIDED_FOR_DETAIL = (
    "elided at output.detail=" + DETAIL_COMPACT + "; ask for output.detail=" + DETAIL_FULL
)


def _compact_loads(loads: Any) -> Any:
    """`structural_model.loads` at compact: every case named, no per-element rows.

    The unfactored rows are the takedown's input and they run to one entry per
    beam per case. What a reader acts on is which cases were built and what they
    produced, and both survive: the case roster with its kind, storey and row
    counts, and the whole combination table.
    """
    if not isinstance(loads, dict):
        return loads
    out = dict(loads)
    cases = out.get("cases")
    if isinstance(cases, dict):
        folded = {}  # type: Dict[str, Any]
        for name in sorted(cases):
            case = cases[name]
            if not isinstance(case, dict):
                folded[name] = case
                continue
            row = dict(
                (key, case[key])
                for key in sorted(case)
                if key not in ("line", "area", "point")
            )
            for key in ("line", "area", "point"):
                rows = case.get(key)
                row[key] = []
                row[key + "_total"] = len(rows) if isinstance(rows, (list, tuple)) else 0
            row["rows_elided"] = True
            row["rows_ref"] = "structural_model.analysis (the takedown they produced)"
            row["rows_elided_reason"] = _ELIDED_FOR_DETAIL
            folded[name] = row
        out["cases"] = folded
    return out


def _compact_takedown(analysis: Any) -> Any:
    """`structural_model.analysis` at compact: the results, not the working.

    The force envelopes, the beam runs and the per-element loads are the design
    layer's INPUT; every verdict they produced is on the design rows, the loads
    the footings were sized from are on `analysis.foundations`, and the ladder
    they raised is on `warnings` in full. `wall_stresses`, `storey_ledger` and
    `conservation` stay: nothing else reports them.
    """
    if not isinstance(analysis, dict):
        return analysis
    out = dict(analysis)
    _elide(
        out, "envelopes", "structural_model.design (the checks they governed)",
        _ELIDED_FOR_DETAIL,
    )
    _elide(out, "beam_runs", "structural_model.beams", _ELIDED_FOR_DETAIL)
    _elide(out, "column_loads", "analysis.foundations", _ELIDED_FOR_DETAIL)
    _elide(out, "footing_loads", "analysis.foundations", _ELIDED_FOR_DETAIL)
    _elide(out, "disclosures", "warnings (the whole ladder, in full)", _ELIDED_FOR_DETAIL)
    return out


def _compact_lateral(lateral: Any) -> Any:
    """`analysis.lateral` at compact: every storey scalar, no per-pier rows."""
    if not isinstance(lateral, dict):
        return lateral
    out = dict(lateral)
    _elide(out, "disclosures", "warnings (the whole ladder, in full)", _ELIDED_FOR_DETAIL)
    _elide(
        out, "base_forces", "analysis.storey_shears and lateral.overturning",
        _ELIDED_FOR_DETAIL,
    )
    storeys = out.get("storeys")
    if isinstance(storeys, list):
        folded = []  # type: List[Any]
        for storey in storeys:
            if not isinstance(storey, dict):
                folded.append(storey)
                continue
            row = dict(storey)
            _elide(
                row,
                "elements",
                "structural_model.columns and structural_model.walls",
                _ELIDED_FOR_DETAIL,
            )
            folded.append(row)
        out["storeys"] = folded
    return out


def _compact_model_wire(wire: Dict[str, Any], opts: "_Resolved") -> Dict[str, Any]:
    """The serialized model at the requested level.

    Two blocks fold here and nowhere else. `meta.foundation_plan` is the same
    object `analysis.foundations` carries, so at compact it becomes a pointer at
    that one. `warnings` keeps every ERROR -- an ERROR blocks the elements it
    names and a model must carry its own blockers -- and points at the entry's
    `warnings`, which carries the whole ladder in full on every response.
    """
    if not opts.compact:
        return wire
    out = dict(wire)
    meta = out.get("meta")
    if isinstance(meta, dict) and meta.get("foundation_plan") is not None:
        meta = dict(meta)
        meta["foundation_plan"] = None
        meta["foundation_plan_ref"] = "analysis.foundations"
        meta["foundation_plan_elided_reason"] = _ELIDED_FOR_DETAIL
        out["meta"] = meta
    ladder = out.get("warnings")
    if isinstance(ladder, list):
        errors_only = [row for row in ladder if str(row.get("severity", "")) == "error"]
        if len(errors_only) != len(ladder):
            out["warnings"] = errors_only
            out["warnings_total"] = len(ladder)
            out["warnings_elided"] = True
            out["warnings_ref"] = "warnings (entry level: the whole ladder, in full)"
            out["warnings_elided_reason"] = _ELIDED_FOR_DETAIL
    return out


def _detail_block(
    opts: "_Resolved", rows: Sequence[Dict[str, Any]], warnings: Sequence[Dict[str, Any]]
) -> Dict[str, Any]:
    """`entry["detail"]`: the level this entry was built at, and what it cost.

    The whole policy table is on `run_options().detail.policy`; this block says
    which level ran, where it came from, and how many design rows are whole, so a
    client can tell a compact response from a full one without diffing it.
    """
    whole = sum(1 for row in rows if str(row.get("detail", DETAIL_FULL)) == DETAIL_FULL)
    return {
        "level": opts.detail,
        "levels": list(DETAIL_LEVELS),
        "request_flag": "output.detail",
        "origin": opts.origins.get("detail", "default"),
        "policy_ref": "run_options().detail.policy",
        "design_rows_full": int(whole),
        "design_rows_compact": int(len(rows) - whole),
        "full_detail_always": "blocked and failed elements, at every level",
        "never_elided": (
            "the disclaimer, every disclosure, the layout metrics, the BOQ, and the "
            "section, reinforcement, status, utilization and governing check of every "
            "designed element"
        ),
        "disclosures_total": len(warnings),
    }


# ---------------------------------------------------------------------------
# response assembly
# ---------------------------------------------------------------------------


def _batch_summary(entries: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    ok = 0
    warned = 0
    refused = 0
    for entry in entries:
        status = str(entry.get("status", "ok"))
        if status == R.STATUS_REFUSED:
            refused += 1
        elif status == R.STATUS_OK_WITH_WARNINGS:
            warned += 1
        else:
            ok += 1
    return {
        "plans": len(entries),
        "ok": ok,
        "warnings": warned,
        "refused": refused,
        "schema_version": STRUCTURAL_SCHEMA_VERSION,
    }


def _envelope(
    status: str,
    message: str,
    entries: Sequence[Dict[str, Any]],
    batch: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """The engine envelope, with the disclaimer stamped and protected.

    Finding 16: `Documents.structural` is ALWAYS a list, length one for a single
    plan or a building, one entry per built plot stack for housing, and it is
    always accompanied by `batch_summary`. Every entry point uses this one
    shape, refusals and the static options answer included, so a client parses
    one envelope and never four.
    """
    documents = {"structural": [dict(entry) for entry in entries]}  # type: Dict[str, Any]
    documents["batch_summary"] = batch if batch is not None else _batch_summary(entries)
    documents["schema_version"] = STRUCTURAL_SCHEMA_VERSION
    documents["engine_fingerprint"] = structural_fingerprint()
    return R.with_disclaimer(
        {
            "status": status,
            "message": message,
            "response": {"Documents": documents},
        }
    )


def _error_envelope(
    message: str,
    field: str = "",
    code: str = "",
    details: Optional[Dict[str, Any]] = None,
    entries: Sequence[Dict[str, Any]] = (),
) -> Dict[str, Any]:
    """A refusal, still carrying the disclaimer (finding 29) and a reason."""
    error = {"message": message, "type": "ValidationError" if field else "EngineError"}
    if field:
        error["field"] = field
    if code:
        error["code"] = code
        error["type"] = "EngineError"
    if details:
        error["details"] = _plain(details)
    envelope = _envelope("ERROR", message, entries)
    envelope["response"]["Documents"]["error"] = error
    return envelope


def _entry_head(
    model: StructuralModel,
    source: str,
    request: Dict[str, Any],
    opts: _Resolved,
    placement: _Placement,
    payload_ref: str,
) -> Dict[str, Any]:
    """The keys every per-plan entry carries, whatever the entry point."""
    head = {
        "schema_version": STRUCTURAL_SCHEMA_VERSION,
        "engine_fingerprint": structural_fingerprint(),
        "units": units_block(),
        "source": source,
        "system": placement.system,
        "input_ref": {
            "source": source,
            "plan_index": request.get("plan_index", 0),
            "plot_id": model.meta.get("plot_id") or request.get("plot_id"),
            "model_id": model.id,
            "hash": payload_ref,
        },
        "options_echo": opts.echo(),
        "placement": placement.to_dict(),
        "layout_score": _plain(placement.layout_score),
    }
    if opts.housing_column_variant is not None:
        housing_layout = _assess_housing_layout(model, opts.min_span_m)
        adjustments = []
        if placement.frame is not None:
            for axis in placement.frame.grid.axes():
                if axis.source.value != "wall" or not axis.candidates:
                    continue
                old = _resolve_pos_mm(axis.candidates)
                if old != axis.pos_mm:
                    adjustments.append({"axis": axis.dir.value, "id": axis.id, "from_m": old/1000.0, "to_m": axis.pos_mm/1000.0})
        description = "%d column positions" % housing_layout["column_stack_count"]
        search = model.meta.get("frame_placement", {}).get("metrics", {}).get("housing_search", {})
        if search:
            rank = search.get("selected_rank")
            description += "; bounded wall-supported search: %d generated, %d distinct placement candidates" % (
                search.get("generated_candidate_count", 0), search.get("distinct_layout_count", 0),
            )
            if rank is not None:
                description += "; spacing-objective rank %d" % (rank + 1)
        if adjustments:
            description += "; " + "; ".join("wall guide %s: %.3f to %.3f m" % (a["axis"], a["from_m"], a["to_m"]) for a in adjustments)
        elif not search and opts.housing_column_variant == "balanced":
            description += "; combined wall guides and balanced optional spans"
        elif not search:
            description += "; alternative optional wall-support positions considered"
        housing_layout.update({
            "variant": opts.housing_column_variant, "requested_max_span_m": opts.max_span_m,
            "physical_max_span_m": None, "eligible": False, "reasons": ["full_design_required"],
            "axis_adjustments": adjustments, "summary": description + ".",
        })
        head["housing_layout"] = housing_layout
    return head


def _finish_housing_layout(entry: Dict[str, Any], model: StructuralModel, opts: _Resolved) -> None:
    """Final, post-referral eligibility. Geometry alone never earns a badge."""
    if opts.housing_column_variant is None:
        return
    layout = entry["housing_layout"]
    layout.update(_assess_housing_layout(model, opts.min_span_m))
    physical = entry.get("analysis", {}).get("physical_max_span_m")
    design = entry.get("design", {})
    reasons = []
    if physical is None:
        reasons.append("full_design_required")
    elif physical > opts.max_span_m + 1e-6:
        reasons.append("physical_span_over_cap")
    if entry.get("status") == R.STATUS_REFUSED or entry.get("errors"):
        reasons.append("hard_error")
    if design.get("failed_count", 0):
        reasons.append("member_design_failure")
    if design.get("undesigned_count", 0):
        reasons.append("required_element_undesigned")
    if design.get("referrals_outstanding"):
        reasons.append("unresolved_referral")
    if layout["confirmed_room_intrusion_count"]:
        reasons.append("housing_room_intrusion")
    if layout["off_wall_column_count"]:
        reasons.append("housing_off_wall_columns")
    if layout["room_assessment"] != "assessed":
        reasons.append("housing_room_assessment_incomplete")
    if entry.get("comparison_validity") is not None:
        reasons.extend(_housing_comparison_reasons(entry, opts))
    layout.update(physical_max_span_m=physical, eligible=not reasons, reasons=sorted(set(reasons)))
    comparison = entry.get("comparison_validity")
    if comparison is None:
        entry["comparison_validity"] = {
            "feasible_for_ranking": False, "valid_for_relative_cost_comparison": False,
            "valid_for_absolute_cost": False, "reasons": layout["reasons"], "not_for_construction": True,
        }
    elif reasons:
        comparison.update(feasible_for_ranking=False, valid_for_relative_cost_comparison=False, valid_for_absolute_cost=False)
        comparison["reasons"] = sorted(set(comparison.get("reasons", []) + reasons))
        comparison["claim"] = "not eligible for candidate ranking; see comparison reasons; no optimum is claimed"


def _split_ladder(log: DisclosureLog) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """(errors, warnings) as wire dicts; a NOTE rides with the warnings."""
    errors = []  # type: List[Dict[str, Any]]
    warnings = []  # type: List[Dict[str, Any]]
    for entry in log.sorted_entries():
        row = entry.to_dict()
        if Severity(entry.severity) == Severity.ERROR:
            errors.append(row)
        else:
            warnings.append(row)
    return (errors, warnings)


def _entry_status(
    placement: _Placement,
    errors: Sequence[Dict[str, Any]],
    warnings: Sequence[Dict[str, Any]],
) -> str:
    """`refused` only when no valid model came back (spec 4.1), else labeled.

    An ERROR on the ladder blocks the elements it names; it makes the whole
    entry a refusal only when placement could not produce a valid model, which
    is what "status is ERROR only when no valid model can be produced" means.
    """
    if not placement.valid:
        return R.STATUS_REFUSED
    if errors or warnings:
        return R.STATUS_OK_WITH_WARNINGS
    return R.STATUS_OK


def _dedupe_model_ladder(model: StructuralModel, log: DisclosureLog) -> None:
    """Fold the run's ladder onto the model and collapse repeats to one entry."""
    merged = DisclosureLog()
    merged.extend(model.warnings)
    merged.extend(log.entries)
    model.warnings = merged.sorted_entries()


# ---------------------------------------------------------------------------
# run_layout
# ---------------------------------------------------------------------------


def run_layout(payload: Any, **options: Any) -> Dict[str, Any]:
    """Placement only: grid, columns, beams, slabs, walls, bands, unsized footings.

    Fast and pure: the same adapt / validate / place prefix `run_design` runs,
    stopping before the load model, so the two can never disagree on geometry.
    No footing is sized here (finding 18).
    """
    from .adapters._geom import AdapterError

    try:
        request = _unwrap_request(payload)
        _check_schema_version(request)
        source = _check_source(request, ("plan", "building", "housing"))
        opts = _Resolved(request, dict(options))
        models = _adapt(request, source, opts)
    except StructuralValidationError as error:
        return _error_envelope(error.message, field=error.field, details=error.details)
    except AdapterError as error:
        return _error_envelope(error.message, code=error.code, details=error.details)

    ref = payload_hash(request)
    entries = []  # type: List[Dict[str, Any]]
    status = "SUCCESS"
    for model in models:
        log = DisclosureLog()
        try:
            _check_rooms_per_floor(model)
            placement = _place(model, opts, log)
        except StructuralValidationError as error:
            return _error_envelope(error.message, field=error.field, details=error.details)
        except AdapterError as error:
            return _error_envelope(error.message, code=error.code, details=error.details)
        except Exception as error:  # a placer that cannot run says so, in the envelope
            entries.append(_pipeline_failure(model, source, request, opts, ref, error))
            status = "ERROR"
            continue

        model.footings = _footing_markers(model)
        _dedupe_model_ladder(model, log)
        errors, warnings = _split_ladder(model.disclosure_log())
        entry = _entry_head(model, source, request, opts, placement, ref)
        entry["structural_model"] = model.to_dict()
        entry["footings_sized"] = False
        entry["errors"] = errors
        entry["warnings"] = warnings
        entry["status"] = _entry_status(placement, errors, warnings)
        entry["partial"] = entry["status"] == R.STATUS_REFUSED
        entry["disclaimer"] = R.DISCLAIMER
        if entry["partial"]:
            status = "ERROR"
        entries.append(entry)

    lead = entries[0] if entries else {}
    message = "structural layout: %s, %d storeys, score %s" % (
        lead.get("system", "unknown"),
        len(models[0].storeys) if models else 0,
        lead.get("layout_score", {}).get("score"),
    )
    return _envelope(status, message, entries)


# ---------------------------------------------------------------------------
# run_design
# ---------------------------------------------------------------------------


def _design_once(
    model: StructuralModel,
    opts: _Resolved,
    log: DisclosureLog,
    placement: _Placement,
    place_foundations: bool = True,
) -> Dict[str, Any]:
    """One full pass of loads, takedown, foundations, diaphragm and design.

    Called at most twice per model: once for the design proper, and once more
    after the single bounded referral re-pass (finding 19). ``run_check`` sets
    ``place_foundations`` false so posted footing identities and dimensions are
    designed as given rather than replaced by a fresh foundation layout.
    """
    from .analysis import diaphragm, takedown

    if opts.housing_column_variant is not None:
        room_audit = _assess_housing_layout(model, opts.min_span_m)
        if room_audit["confirmed_room_intrusion_count"]:
            raise takedown.AnalysisError(
                "E_HOUSING_ROOM_INTRUSION",
                "Housing alternatives require columns outside known enclosed room interiors; %d stack(s) remain farther than 0.30 m from a finite architectural wall" % room_audit["confirmed_room_intrusion_count"],
                room_audit["room_intrusion_column_ids"],
            )
        if room_audit["off_wall_column_count"]:
            raise takedown.AnalysisError(
                "E_HOUSING_COLUMN_OFF_WALL",
                "Housing alternatives require every column center within 0.30 m of a finite architectural wall on its own storey; %d column(s) remain off wall" % room_audit["off_wall_column_count"],
                room_audit["off_wall_column_ids"],
            )

    ledger = {} if opts.analysis_mode == "gravity_only" else _gravity_ledger(model, opts)
    loadmodel, seismic, wind, lateral_cases = _build_loads(model, opts, log, ledger)

    result = takedown.run(model, loadmodel)
    if result.log is not None:
        log.extend(result.log.entries)

    # Placement fragments are drawing conveniences; the analysis supports
    # define the physical spans.  A requested span cap therefore has to be
    # checked against BeamRun spans after takedown, before foundations, member
    # design, quantities or cost ranking can make the option look acceptable.
    long_runs = []  # type: List[Tuple[str, float, List[str]]]
    long_overhangs = []  # type: List[Tuple[str, str, float, List[str]]]
    straddling = []  # type: List[str]
    for record in getattr(result, "beam_runs", ()) or ():
        straddling.extend(
            str(value)
            for value in record.get("fragments_straddling_supports", ()) or ()
        )
        if record.get("plinth"):
            # A plinth beam ties two ground columns across whatever lies
            # between them, open floor included, and carries wall load only;
            # the requested cap governs the floor beams that carry slabs. With
            # wall-aligned columns a plinth tie between two mid-wall stations
            # on opposite walls is routinely longer than a tight cap. The
            # 7.5 m hard cap still applies to every beam in run_check.
            continue
        longest = max(
            (float(hi) - float(lo) for lo, hi in record.get("spans", ()) or ()),
            default=0.0,
        )
        if longest > opts.max_span_m + 1e-6:
            long_runs.append(
                (
                    str(record.get("run_id", "beam-run")),
                    longest,
                    [str(value) for value in record.get("beam_ids", ()) or ()],
                )
            )
        for overhang in record.get("overhangs", ()) or ():
            length = float(overhang.get("length_m", 0.0))
            if length > opts.cantilever_m + 1e-6:
                long_overhangs.append(
                    (
                        str(record.get("run_id", "beam-run")),
                        str(overhang.get("side", "overhang")),
                        length,
                        [str(value) for value in record.get("beam_ids", ()) or ()],
                    )
                )
    straddling = sorted(set(straddling))
    if straddling:
        message = (
            "%d drawn beam fragment(s) cross an internal physical support; the member "
            "topology must be split at that support before its station forces can be designed"
            % len(straddling)
        )
        if opts.analysis_mode == "gravity_only":
            from .analysis.takedown import AnalysisError

            raise AnalysisError("E_MEMBER_TOPOLOGY", message, straddling)
        log.append(
            make_disclosure(
                "W_RELEASED_CAP",
                message + "; the legacy code_complete route continues with the conservative "
                "largest containing analysis span and is not eligible for cost-option ranking",
                straddling,
                stage="api.analysis.member_topology",
            )
        )
    if long_runs:
        worst = max(long_runs, key=lambda row: (row[1], row[0]))
        element_ids = sorted({element for _, _, ids in long_runs for element in ids})
        message = (
            "%d physical support-to-support beam run(s) exceed the requested %.3f m cap; "
            "worst is %s at %.3f m"
            % (len(long_runs), opts.max_span_m, worst[0], worst[1])
        )
        if opts.analysis_mode == "gravity_only":
            from .analysis.takedown import AnalysisError

            raise AnalysisError("E_SPAN_OVER_MAX", message, element_ids)
        log.append(
            make_disclosure(
                "W_RELEASED_CAP",
                message + "; the legacy code_complete route continues to member checks, "
                "but this layout is not eligible for cost-option ranking",
                element_ids,
                stage="api.analysis.physical_spans",
            )
        )
    if long_overhangs:
        worst = max(long_overhangs, key=lambda row: (row[2], row[0], row[1]))
        element_ids = sorted({element for _, _, _, ids in long_overhangs for element in ids})
        message = (
            "%d physical beam overhang(s) exceed the requested %.3f m cantilever cap; "
            "worst is %s %s at %.3f m"
            % (len(long_overhangs), opts.cantilever_m, worst[0], worst[1], worst[2])
        )
        if opts.analysis_mode == "gravity_only":
            from .analysis.takedown import AnalysisError

            raise AnalysisError("E_CANTILEVER_SPAN", message, element_ids)
        log.append(
            make_disclosure(
                "E_CANTILEVER_SPAN",
                message + "; the legacy code_complete route continues to member checks, "
                "but this layout is not eligible for cost-option ranking",
                element_ids,
                stage="api.analysis.physical_overhangs",
            )
        )

    plan = None  # type: Any
    if place_foundations:
        column_loads, wall_loads = _foundation_loads(result)
        footing_ledger = getattr(result, "footing_loads", {}) or {}
        non_positive_dead_columns = sorted(
            str(key)
            for key, row in (footing_ledger.get("columns") or {}).items()
            if _num(row.get("p_dl_kn")) <= 1e-9
        )
        non_positive_dead_walls = sorted(
            str(key)
            for key, row in (footing_ledger.get("walls") or {}).items()
            if _num(row.get("n_dl_kn_m")) <= 1e-9
        )
        non_positive_service_columns = sorted(
            key for key, value in column_loads.items() if float(value) <= 1e-9
        )
        non_positive_service_walls = sorted(
            key for key, value in wall_loads.items() if float(value) <= 1e-9
        )
        non_positive = sorted(set(
            non_positive_dead_columns
            + non_positive_dead_walls
            + non_positive_service_columns
            + non_positive_service_walls
        ))
        if non_positive:
            message = (
                "%d base support(s) have a non-positive dead-load or DL + reduced "
                "imposed-load foundation reaction; a compression-only pad, combined, or strip footing cannot "
                "be sized until the grid or support model is revised: %s"
                % (len(non_positive), ", ".join(non_positive[:10]))
            )
            if opts.analysis_mode == "gravity_only":
                from .analysis.takedown import AnalysisError

                raise AnalysisError("E_GRAVITY_UPLIFT", message, non_positive)
            log.append(
                make_disclosure(
                    "W_RELEASED_CAP",
                    message + "; the legacy code_complete route emits only the geometric-minimum "
                    "foundation and the footing designer must reject it",
                    non_positive,
                    stage="api.foundation.gravity_reaction",
                )
            )
            # Foundation placement itself rejects non-positive demand.  The
            # legacy route therefore treats these explicitly disclosed stacks
            # as missing and emits geometric-minimum markers; the footing
            # designer still receives the unmodified takedown envelope and
            # fails it.  Gravity-only comparisons stop above and never enter
            # this compatibility path.
            column_loads = {
                key: value for key, value in column_loads.items() if float(value) > 1e-9
            }
            wall_loads = {
                key: value for key, value in wall_loads.items() if float(value) > 1e-9
            }
        bearing = sorted(
            wall.id
            for wall in model.walls
            if wall.bearing and wall.storey == min((w.storey for w in model.walls), default=0)
        )
        ground = min((column.storey for column in model.columns), default=0)
        column_ids = sorted(column.id for column in model.columns if column.storey == ground)
        plan = _foundations.layout_foundations(
            model,
            bearing_wall_ids=bearing,
            column_ids=column_ids,
            wall_loads=wall_loads,
            column_loads=column_loads,
            soil=opts.soil,
        )
        log.extend(plan.warnings)
    elif model.footings:
        footing_ids = sorted(str(footing.id) for footing in model.footings)
        log.append(
            make_disclosure(
                "N_CHECK_FOOTINGS_AS_GIVEN",
                "%d posted footing(s) were taken as given for this check; foundation placement "
                "did not run and any required design resize is reported on the element check row"
                % len(footing_ids),
                footing_ids,
                stage="api.check.foundation",
            )
        )

    lateral = None
    lateral_block = None  # type: Optional[Dict[str, Any]]
    shears = _storey_shears(lateral_cases)
    if shears["x"] or shears["y"]:
        try:
            lateral = diaphragm.run(
                model,
                shears,
                ctx=diaphragm.LateralContext(fck_mpa=opts.fck_mpa()),
                centres_of_mass=_centres_of_mass(model),
                cm_source="slab-area CM",
                log=log,
            )
            lateral_block = _plain(lateral.to_dict())
        except (ValueError, KeyError) as error:
            log.append(
                make_disclosure(
                    "W_RELEASED_CAP",
                    "the diaphragm distribution could not run on this model ("
                    + str(error)
                    + "); the lateral shares are not reported",
                    (),
                    stage="api.analysis",
                )
            )

    results = _design_members(
        model,
        result,
        lateral,
        opts,
        placement.system,
        log,
        loadmodel=loadmodel,
    )

    return {
        "loadmodel": loadmodel,
        "seismic": seismic,
        "wind": wind,
        "lateral_cases": lateral_cases,
        "takedown": result,
        "foundations": plan,
        "lateral": lateral_block,
        "design": results,
        "storey_shears": {
            direction: dict((str(k), v) for k, v in sorted(shears[direction].items()))
            for direction in ("x", "y")
        },
    }


def _analysis_block(pass_out: Dict[str, Any], opts: _Resolved, re_passes: int) -> Dict[str, Any]:
    """The wire `analysis` block, serialized from the stage outputs verbatim."""
    loadmodel = pass_out["loadmodel"]
    lateral = pass_out["lateral"]
    takedown = pass_out["takedown"]
    beam_runs = list(getattr(takedown, "beam_runs", ()) or ())
    # Floor beams carry the slabs and answer to the requested cap; plinth ties
    # run column to column at ground across open floor and are reported apart.
    physical_spans = [
        float(hi) - float(lo)
        for record in beam_runs
        if not record.get("plinth")
        for lo, hi in record.get("spans", ()) or ()
    ]
    plinth_spans = [
        float(hi) - float(lo)
        for record in beam_runs
        if record.get("plinth")
        for lo, hi in record.get("spans", ()) or ()
    ]
    physical_overhangs = [
        float(overhang.get("length_m", 0.0))
        for record in beam_runs
        for overhang in record.get("overhangs", ()) or ()
    ]
    straddling_fragments = sorted(
        {
            str(element_id)
            for record in beam_runs
            for element_id in record.get("fragments_straddling_supports", ()) or ()
        }
    )
    if opts.compact:
        lateral = _compact_lateral(lateral)
    out = {
        "method": (
            "tributary_takedown_v1_gravity_only"
            if opts.analysis_mode == "gravity_only"
            else "tributary_takedown_v1"
        ),
        "storey_weight_source": (
            "not required: earthquake actions were intentionally excluded"
            if opts.analysis_mode == "gravity_only"
            else "gravity takedown pass 1 (the seismic weights come from the takedown "
            "ledger, which is why the takedown runs twice)"
        ),
        "referral_re_passes": int(re_passes),
        "combos_used": [combo.name for combo in loadmodel.combos],
        "combos": [combo.to_dict() for combo in loadmodel.combos],
        "cases_used": sorted(loadmodel.cases),
        "seismic": pass_out["seismic"],
        "wind": pass_out["wind"],
        "storey_shears": pass_out["storey_shears"],
        "lateral": lateral,
        "foundations": (
            None
            if pass_out["foundations"] is None
            else pass_out["foundations"].to_dict()
        ),
        # These audit values remain available at compact detail even though the
        # full BeamRun records are elided from structural_model.analysis.  A UI
        # or report must compare the physical support-to-support span, never a
        # short drawing fragment split at an architectural wall intersection.
        "physical_max_span_m": _num(max(physical_spans, default=0.0)),
        "physical_span_count": len(physical_spans),
        "plinth_max_span_m": _num(max(plinth_spans, default=0.0)),
        "plinth_span_count": len(plinth_spans),
        "physical_max_overhang_m": _num(max(physical_overhangs, default=0.0)),
        "physical_overhang_count": len(physical_overhangs),
        "drawn_fragments_straddling_supports": straddling_fragments,
        "support_face_span_basis": (
            "BeamRun centreline support stations; member clear-span design applies the "
            "v1 generic support-width convention"
        ),
        "foundation_reaction_scope": (
            "single all-spans-loaded DL plus reduced LL/LLR service state; a patterned "
            "minimum-reaction/uplift envelope is not implemented"
        ),
        # The bulky blocks live once, where findings 6 and 14 put them: the
        # unfactored cases on `structural_model.loads`, the takedown on
        # `structural_model.analysis`. These names say where, so nothing is
        # serialized twice into one response.
        "loads_ref": "structural_model.loads",
        "takedown_ref": "structural_model.analysis",
    }  # type: Dict[str, Any]
    if opts.compact:
        # The combination table here is the SAME object `structural_model.loads`
        # carries, byte for byte. Two copies of one block is duplication; the
        # pointer is the disclosure, and `combos_used` keeps the roster this run
        # actually built readable in place. `seismic` stays: it is small, and it
        # is the block a reader opens this section for.
        out["combos"] = []
        out["combos_ref"] = "structural_model.loads.combos"
        out["combos_total"] = len(loadmodel.combos)
        out["combos_elided"] = True
        out["combos_elided_reason"] = _ELIDED_FOR_DETAIL
    return out


def run_design(payload: Any, **options: Any) -> Dict[str, Any]:
    """The single orchestrator, running finding 18's sequence and no other.

    adapt, validate, place, load model, gravity takedown, `layout_foundations`,
    diaphragm, member design, at most one bounded referral re-pass, quantities,
    report. Every stage appends to one DisclosureLog, and every response carries
    the verbatim disclaimer whatever the outcome.
    """
    from .adapters._geom import AdapterError

    try:
        request = _unwrap_request(payload)
        _check_schema_version(request)
        source = _check_source(request, ("plan", "building", "housing"))
        opts = _Resolved(request, dict(options))
        models = _adapt(request, source, opts)
    except StructuralValidationError as error:
        return _error_envelope(error.message, field=error.field, details=error.details)
    except AdapterError as error:
        return _error_envelope(error.message, code=error.code, details=error.details)

    if opts.validate_only:
        return _envelope(
            "SUCCESS",
            "structural design request validated; %d model(s) would be built" % len(models),
            [
                {
                    "schema_version": STRUCTURAL_SCHEMA_VERSION,
                    "engine_fingerprint": structural_fingerprint(),
                    "units": units_block(),
                    "source": source,
                    "validate_only": True,
                    "status": R.STATUS_OK,
                    "input_ref": {"source": source, "hash": payload_hash(request)},
                    "options_echo": opts.echo(),
                    "disclaimer": R.DISCLAIMER,
                }
                for _ in models
            ],
        )

    ref = payload_hash(request)
    entries = []  # type: List[Dict[str, Any]]
    status = "SUCCESS"
    failures = 0
    for model in models:
        try:
            entry = _design_one(model, source, request, opts, ref)
        except StructuralValidationError as error:
            return _error_envelope(error.message, field=error.field, details=error.details)
        except AdapterError as error:
            return _error_envelope(error.message, code=error.code, details=error.details)
        except Exception as error:  # a stage that cannot run says so, in the envelope
            entry = _pipeline_failure(model, source, request, opts, ref, error)
        _finish_housing_layout(entry, model, opts)
        if entry["status"] == R.STATUS_REFUSED:
            status = "ERROR"
        failures += int(entry.get("design", {}).get("failed_count", 0))
        entries.append(entry)

    lead = entries[0] if entries else {}
    message = "structural design: %s, %d entr%s, %d member design failure(s)" % (
        lead.get("system", "unknown"),
        len(entries),
        "y" if len(entries) == 1 else "ies",
        failures,
    )
    return _envelope(status, message, entries)


def _pipeline_failure(
    model: StructuralModel,
    source: str,
    request: Dict[str, Any],
    opts: _Resolved,
    ref: str,
    error: Exception,
) -> Dict[str, Any]:
    """A stage that could not run, reported as a partial rather than a traceback.

    The model as far as it got still ships, so the UI has something to draw and
    the reader can see which storey the pipeline reached. `E_ANA_CONSERVATION`
    is the takedown's own refusal code; anything else is reported under
    `E_BAD_ENVELOPE`, the registry's "self-inconsistent input" ERROR, because no
    code exists for "a stage raised".
    """
    code = str(getattr(error, "code", "")) or "E_BAD_ENVELOPE"
    if code not in REGISTRY or REGISTRY[code][0] != Severity.ERROR:
        code = "E_BAD_ENVELOPE"
    message = "%s: %s" % (type(error).__name__, error)
    log = DisclosureLog()
    element_ids = list(getattr(error, "element_ids", ()) or ())
    log.append(
        make_disclosure(
            code,
            "the design pipeline stopped on model " + repr(model.id) + " (" + message + "); "
            "the geometry placed before the stop is returned as a partial",
            element_ids,
            stage="api.design",
        )
    )
    _dedupe_model_ladder(model, log)
    errors, warnings = _split_ladder(model.disclosure_log())
    placement = _Placement()
    placement.system = str(getattr(model.system, "value", model.system))
    placement.valid = False
    entry = _entry_head(model, source, request, opts, placement, ref)
    entry["structural_model"] = model.to_dict()
    entry["footings_sized"] = False
    entry["errors"] = errors
    entry["warnings"] = warnings
    entry["status"] = R.STATUS_REFUSED
    entry["partial"] = True
    entry["stopped_at"] = message
    entry["design"] = {
        "code_set": [],
        "results_ref": "structural_model.design",
        "results_count": 0,
        "failed": [],
        "failed_count": 0,
        "referral_re_passes": 0,
    }
    entry["disclaimer"] = R.DISCLAIMER
    return entry


def _housing_design_pass(
    model: StructuralModel,
    opts: _Resolved,
    log: DisclosureLog,
    placement: _Placement,
    request: Dict[str, Any],
    referral: bool = False,
) -> Dict[str, Any]:
    """Deduplicate exact engineering after final framing and referral repairs.

    Layout pictures are insufficient keys. The internal cache retains all
    architectural, topological, resolved option and engine context, and only
    replays pass results and their mutations. Quantities, report, option echo,
    request hash, selected variant and every response are constructed afresh.
    Legacy Housing, Building and plan requests bypass reuse entirely.
    """
    if opts.housing_column_variant is None:
        return _design_once(model, opts, log, placement)
    from .design_reuse import engineering_signature, reuse_design_pass

    key = engineering_signature(
        model, request, vars(opts), placement.system, placement.valid,
        structural_fingerprint(), referral=referral,
    )
    return reuse_design_pass(
        key, model, opts, log,
        lambda pass_log: _design_once(model, opts, pass_log, placement),
        referral=referral,
    )


def _housing_comparison_reasons(entry: Dict[str, Any], opts: _Resolved) -> List[str]:
    """Comparison blockers that also invalidate a complete Housing candidate.

    The Housing geometry audit alone does not cover designed footing overlap,
    quantity sanity or every analysis-topology disclosure. All comparison
    blockers apply. Explicitly omitting pricing is the sole exception: another
    column recipe cannot supply an output the caller chose not to compute.
    """
    comparison = entry.get("comparison_validity", {})
    comparison_reasons = set(comparison.get("reasons", ()))
    intentionally_unpriced = not opts.include_boq and comparison_reasons == {"cost_not_computed"}
    if not opts.include_boq:
        comparison_reasons.discard("cost_not_computed")
    if (not comparison.get("feasible_for_ranking") or not comparison.get("valid_for_relative_cost_comparison")) and not comparison_reasons and not intentionally_unpriced:
        comparison_reasons.add("comparison_checks_incomplete")
    return sorted(comparison_reasons)


def _housing_attempt_reasons(entry: Dict[str, Any], opts: _Resolved) -> List[str]:
    """Full candidate gate, including foundation topology and quantity checks."""
    housing = entry.get("housing_layout", {})
    reasons = set(housing.get("reasons", ()))
    if not housing.get("eligible") and not reasons:
        reasons.add("housing_assessment_incomplete")
    reasons.update(_housing_comparison_reasons(entry, opts))
    return sorted(reasons)


def _design_one(
    model: StructuralModel,
    source: str,
    request: Dict[str, Any],
    opts: _Resolved,
    ref: str,
) -> Dict[str, Any]:
    """One selected candidate, plus one checked legacy seed only if it fails.

    Placement preflight cannot establish member design or clear referrals.
    Housing therefore has at most TWO candidate attempts, each retaining the
    existing one referral re-pass: at most FOUR expensive passes before reuse.
    No alternate can overwrite a successful initial result. A failed fallback
    leaves the initial refusal available with both attempt records.
    """
    if opts.housing_column_variant is None:
        return _design_one_attempt(model, source, request, opts, ref)
    import copy
    from .adapters._geom import AdapterError

    pristine_model, pristine_opts = copy.deepcopy(model), copy.deepcopy(opts)

    def attempt(current_model, current_opts, recipe=None):
        try:
            entry = _design_one_attempt(current_model, source, request, current_opts, ref, recipe)
        except (StructuralValidationError, AdapterError):
            raise
        except Exception as error:
            entry = _pipeline_failure(current_model, source, request, current_opts, ref, error)
        _finish_housing_layout(entry, current_model, current_opts)
        return entry

    first = attempt(model, opts)
    first_reasons = _housing_attempt_reasons(first, opts)
    attempts = [{"kind": "selected_search", "eligible": not first_reasons,
                 "geometry_fingerprint": first["housing_layout"]["geometry_fingerprint"],
                 "reasons": first_reasons}]
    selected, fallback_used = first, False
    if first_reasons:
        initial_search = copy.deepcopy(model.meta.get("frame_placement", {}).get("metrics", {}).get("housing_search", {}))
        recipe = {"seed": opts.housing_column_variant, "removed": [], "added": [],
                  "operation": "legacy_seed_fallback", "search": initial_search}
        fallback = attempt(pristine_model, pristine_opts, recipe)
        fallback_reasons = _housing_attempt_reasons(fallback, pristine_opts)
        attempts.append({"kind": "legacy_seed_fallback", "eligible": not fallback_reasons,
                         "geometry_fingerprint": fallback["housing_layout"]["geometry_fingerprint"],
                         "reasons": fallback_reasons})
        if not fallback_reasons:
            selected, fallback_used = fallback, True
            vars(model).clear()
            vars(model).update(vars(pristine_model))
            vars(opts).clear()
            vars(opts).update(vars(pristine_opts))
    search = model.meta.setdefault("frame_placement", {}).setdefault("metrics", {}).setdefault("housing_search", {})
    search.update(
        full_design_candidate_attempt_count=len(attempts), full_design_candidate_limit=2,
        full_design_distinct_layout_count=len({row["geometry_fingerprint"] for row in attempts}),
        full_design_distinct_eligible_layout_count=len({row["geometry_fingerprint"] for row in attempts if row["eligible"]}),
        expensive_pass_limit_before_reuse=4, checked_legacy_fallback_used=fallback_used,
        full_design_attempts=attempts,
        final_geometry_fingerprint=selected["housing_layout"]["geometry_fingerprint"],
    )
    # These are existing mirrors of placement metrics, not a second wire
    # contract. Keep every mirror tied to the actually returned model.
    for block in (selected.get("layout_score", {}),
                  selected.get("placement", {}).get("layout_score", {}),
                  selected.get("report", {}).get("layout_metrics", {}),
                  selected.get("structural_model", {}).get("meta", {}).get("frame_placement", {})):
        block.setdefault("metrics", {})["housing_search"] = copy.deepcopy(search)
    if fallback_used:
        selected["housing_layout"]["summary"] += " Checked legacy wall-supported seed used after the search candidate failed final design: %s." % ", ".join(attempts[0]["reasons"])
    elif len(attempts) > 1:
        selected["housing_layout"]["summary"] += " Both bounded candidate attempts remain ineligible."
    return selected


def _clear_replaced_housing_span_warnings(model: StructuralModel, log: DisclosureLog) -> None:
    """A repaired Housing frame replaces its old adjacent-column warnings.

    Grid gaps are separate evidence and retain their own disclosures. The
    replacement FrameResult immediately writes its recomputed final pairs.
    """
    def retained(row):
        return not (row.code == "W_SHORT_SPAN" and row.stage == _frame._STAGE_COLS)

    model.warnings = [row for row in model.warnings if retained(row)]
    log.entries[:] = [row for row in log.entries if retained(row)]


def _design_one_attempt(
    model: StructuralModel,
    source: str,
    request: Dict[str, Any],
    opts: _Resolved,
    ref: str,
    housing_recipe: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """The fixed sequence for one model. Never raises for a modelling refusal."""
    log = DisclosureLog()
    _check_rooms_per_floor(model)
    placement = (_place(model, opts, log) if housing_recipe is None
                 else _place(model, opts, log, housing_recipe=housing_recipe))

    pass_out = _housing_design_pass(model, opts, log, placement, request)
    referrals = _referrals(pass_out["design"])
    re_passes = 0
    applied = []  # type: List[Dict[str, Any]]

    actionable = [
        item
        for action in ACTIONABLE_REFERRALS
        for item in referrals.get(action, ())
    ]
    if actionable:
        # Finding 19: ONE bounded re-pass. Whatever is still referred after it
        # is disclosed, never chased round the loop a second time.
        panels = _panel_ids_from(referrals.get("add_secondary_beams", ()))
        conversions = referrals.get("confined_masonry_conversion", ())
        if panels and placement.system not in _MASONRY_SYSTEMS:
            result = _frame.insert_secondary_beams(
                model, opts.frame_params(placement.system), panel_ids=panels
            )
            if opts.housing_column_variant is not None:
                _clear_replaced_housing_span_warnings(model, log)
            result.write_back(model)
            _frame.place_lintels_for_infill(model)
            placement.frame = result
            placement.valid = bool(result.valid)
            log.extend(result.log.entries)
            placement.layout_score.update(_score_block(result))
            placement.layout_score.pop("basis", None)
            applied.append({"action": "add_secondary_beams", "panels": panels})
        if conversions:
            params = opts.masonry_params(System.CONFINED_MASONRY.value)
            placer = _masonry.MasonryPlacer(params)
            converted = placer.place(model, params)
            converted.write_back(model)
            placement.masonry = converted
            placement.system = converted.system.system
            placement.decision = converted.system
            log.extend(converted.warnings)
            applied.append(
                {
                    "action": "confined_masonry_conversion",
                    "walls": sorted({str(item["element_id"]) for item in conversions}),
                }
            )
        if applied:
            re_passes = 1
            pass_out = _housing_design_pass(model, opts, log, placement, request, referral=True)
            referrals = _referrals(pass_out["design"])

    outstanding = sorted(
        (action, len(referrals[action]))
        for action in referrals
        if action in ACTIONABLE_REFERRALS
    )
    outstanding_ids = sorted(
        {
            str(item["element_id"])
            for action in ACTIONABLE_REFERRALS
            for item in referrals.get(action, ())
        }
    )
    if outstanding and re_passes:
        log.append(
            make_disclosure(
                "W_COARSE_ITER",
                "the one bounded referral re-pass (finding 19) has run; these referrals "
                "are still open and are reported rather than chased: "
                + ", ".join("%s x%d" % (action, count) for action, count in outstanding),
                outstanding_ids,
                stage="api.design",
            )
        )

    if opts.housing_column_variant is not None and placement.frame is not None:
        search = placement.frame.metrics.get("housing_search")
        if search is not None:
            search["objective"] = list(_frame._housing_objective(
                placement.frame.columns, placement.frame.beams, opts.min_span_m,
            )[:5])
            search["objective_stage"] = "final_after_referrals"
            search["final_geometry_fingerprint"] = _assess_housing_layout(model, opts.min_span_m)["geometry_fingerprint"]
            placement.layout_score.update(_score_block(placement.frame))
    results = pass_out["design"]
    takedown_result = pass_out["takedown"]
    _audit_designed_foundation_geometry(model, results, log)
    undesigned = _disclose_undesigned(model, results, placement.system, log)

    blocked = sorted(
        {
            element_id
            for entry in log.entries
            if Severity(entry.severity) == Severity.ERROR
            for element_id in entry.element_ids
        }
    )
    quantity_options = {
        "founding_depth_m": _num(opts.soil.get("founding_depth_m"), 1.5),
        "default_concrete_grade": opts.concrete_grade,
        "default_steel_grade": opts.steel_grade,
        "blocked_element_ids": tuple(blocked),
        "detail": opts.detail,
    }
    takeoff = Q.take_off(model, results, quantity_options)
    log.extend(takeoff.disclosures.entries)
    bbs = Q.build_bbs(results, quantity_options)
    boq = Q.price(takeoff, None, quantity_options, bbs=bbs) if opts.include_boq else None
    if boq is not None:
        log.extend(getattr(boq, "disclosures", DisclosureLog()).entries)

    model.loads = pass_out["loadmodel"].to_dict()
    model.seismic = pass_out["seismic"]
    model.analysis = takedown_result.to_dict()
    if not opts.trace:
        # `output.trace` gates every clause trace, wherever it rides
        model.loads["trace"] = []
        model.analysis["trace"] = []
    if opts.compact:
        model.loads = _compact_loads(model.loads)
        model.analysis = _compact_takedown(model.analysis)
    # The rows are built whole once. The report reads THOSE, so a card is
    # rendered off the same numbers whatever the level, and only the copy that
    # rides on the model is abbreviated.
    full_rows = _design_wire(results, opts.trace)
    code_set = _design_code_set(full_rows, pass_out["loadmodel"].to_dict(), pass_out["seismic"])
    _dedupe_model_ladder(model, log)
    ladder = model.disclosure_log()
    model.design = _project_design_rows(
        full_rows, opts.detail, _codes_by_element(ladder), blocked
    )
    model.quantities = {
        "takeoff": takeoff.to_dict(),
        "bbs": bbs.to_dict(),
        "boq": None if boq is None else boq.to_dict(),
    }

    report = R.build_report(
        model=model,
        placement=placement.to_dict(),
        analysis=takedown_result,
        # the wire dicts, so the report reads the same rows the response ships
        # (and pays for their traces exactly once, when tracing was asked for)
        design_results=full_rows,
        # WHOLE schedules, whatever the level: the report subtracts a blocked
        # element's mass back out of the aggregates, and it can only do that row
        # by row. It elides afterwards, from its own `detail` option, so the
        # level changes what is shown and never what `summary.totals` says.
        takeoff=takeoff.to_dict(Q.DETAIL_FULL),
        bbs=bbs.to_dict(Q.DETAIL_FULL),
        boq=boq,
        layout_score=placement.layout_score,
        disclosures=model.disclosure_log(),
        options={
            "trace": opts.trace,
            "include_trace": opts.trace,
            "generated_at": opts.generated_at,
            "detail": opts.detail,
            # `trace_available` reports what was KEPT, so the load trace only
            # reaches the report when tracing was asked for; a run with tracing
            # off says so and the client knows to re-post with it on
            "trace_entries": pass_out["loadmodel"].trace if opts.trace else [],
        },
    )

    errors, warnings = _split_ladder(model.disclosure_log())
    failed = []  # type: List[Dict[str, Any]]
    for item in results:
        if str(getattr(item, "status", "")) != "fail":
            continue
        texts = list(getattr(item, "warnings", ()) or ())
        row = {
            "element_id": str(getattr(item, "element_id", "")),
            "element_type": str(getattr(item, "element_type", "")),
            "check": str(getattr(item, "governing_check", "")),
            "utilization": _num(getattr(item, "utilization_max", 0.0)),
            "warnings_total": len(texts),
        }  # type: Dict[str, Any]
        # A failed member's own row is never abbreviated, so its warnings are in
        # the response whole either way; repeating them here as well is a third
        # copy of the same sentences. The pointer is stated once for the block,
        # in `failed_warnings_ref`, rather than 69 times here.
        if not opts.compact:
            row["warnings"] = texts[:3]
        failed.append(row)

    entry = _entry_head(model, source, request, opts, placement, ref)
    entry["structural_model"] = _compact_model_wire(model.to_dict(), opts)
    entry["footings_sized"] = True
    entry["detail"] = _detail_block(opts, model.design, warnings)
    entry["analysis"] = _analysis_block(pass_out, opts, re_passes)
    entry["design"] = {
        "code_set": code_set,
        "materials": {
            "concrete": opts.concrete_grade,
            "steel": opts.steel_grade,
            "mortar": opts.mortar_grade,
        },
        "results_ref": "structural_model.design",
        "results_count": len(results),
        "trace_included": bool(opts.trace),
        "failed": failed,
        "failed_count": len(failed),
        # said once for the block, never per row: a failed member's own design
        # result is whole at every level, and its warnings are on it
        "failed_warnings_ref": "structural_model.design (a failed row is never abbreviated)",
        "coverage": _design_coverage(model, results, placement.system),
        "undesigned": undesigned[:100],
        "undesigned_count": len(undesigned),
        "referrals": _referrals_wire(referrals, opts.compact),
        "referral_re_passes": re_passes,
        "referrals_applied": applied,
        # the authoritative record of what the one re-pass left open: the ladder
        # merges by code, so another producer's W_COARSE_ITER can carry the
        # message, but this block always says exactly what is outstanding
        "referrals_outstanding": [
            {"action": action, "count": count} for action, count in outstanding
        ],
        "referrals_outstanding_ids": outstanding_ids[:100],
    }
    boq_wire = None if boq is None else boq.to_dict()
    boq_total = _num(boq_wire.get("total")) if boq_wire is not None else 0.0
    cost_computed = bool(
        boq_wire is not None
        and math.isfinite(boq_total)
        and boq_total > 0.0
        and str(boq_wire.get("currency") or "").strip()
        and str(boq_wire.get("schedule") or "").strip()
    )
    ranking_reasons = []  # type: List[str]
    if errors:
        ranking_reasons.append("hard_error")
    if failed:
        ranking_reasons.append("member_design_failure")
    if outstanding:
        ranking_reasons.append("unresolved_referral")
    if undesigned:
        # `_disclose_undesigned` lists only placed elements owned by the active
        # design route (not intentionally out-of-scope lintels/bands). A BOQ
        # may still quantify such geometry, but it is not a fully checked
        # candidate and must never receive a cost-ranking badge.
        ranking_reasons.append("required_element_undesigned")
    if not cost_computed:
        ranking_reasons.append("cost_not_computed")
    invalid_stages = {
        "api.analysis.physical_spans",
        "api.analysis.member_topology",
        "api.analysis.physical_overhangs",
        "api.foundation.gravity_reaction",
    }
    if any(str(row.get("stage", "")) in invalid_stages for row in warnings):
        ranking_reasons.append("invalid_analysis_or_foundation_topology")
    if any(
        str(row.get("stage", "")) in {
            "placement.foundations",
            "api.design.foundation_geometry",
        }
        and str(row.get("code", "")) in {"W_FOOTING_OVERLAP", "W_ECCENTRIC_COLUMN"}
        for row in warnings
    ):
        ranking_reasons.append("unresolved_foundation_topology")
    density_warning_codes = {
        "W_STEEL_DENSITY_BAND",
        "W_CONCRETE_DENSITY_BAND",
        "W_MASONRY_DENSITY_BAND",
    }
    if any(str(row.get("code", "")) in density_warning_codes for row in warnings):
        # A quantity sanity warning literally asks the reader to check the
        # take-off before trusting cost.  Calling that same option eligible for
        # a cost ranking was contradictory.  The broad, system-specific bands
        # remain heuristics, but crossing one now blocks the badge until the
        # quantity anomaly has been resolved or independently accepted.
        ranking_reasons.append("quantity_sanity_check_failed")
    placeholder_rates = bool(
        cost_computed
        and (
            boq_wire.get("placeholder_rates")
            or any(row.get("code") == "W_PLACEHOLDER_RATES" for row in warnings)
        )
    )
    if opts.housing_column_variant is not None:
        housing_audit = _assess_housing_layout(model, opts.min_span_m)
        if housing_audit["confirmed_room_intrusion_count"]:
            ranking_reasons.append("housing_room_intrusion")
        if housing_audit["off_wall_column_count"]:
            ranking_reasons.append("housing_off_wall_columns")
        if housing_audit["room_assessment"] != "assessed":
            ranking_reasons.append("housing_room_assessment_incomplete")
    feasible_for_ranking = not ranking_reasons
    comparison_claim = (
        "eligible for like-for-like comparison among checked candidates; no global optimum is claimed"
        if feasible_for_ranking
        else "not eligible for candidate ranking; see comparison reasons; no optimum is claimed"
    )
    entry["comparison_validity"] = {
        "analysis_scope": (
            "preliminary_gravity_comparison"
            if opts.analysis_mode == "gravity_only"
            else "code_complete_route"
        ),
        "feasible_for_ranking": feasible_for_ranking,
        "valid_for_relative_cost_comparison": feasible_for_ranking,
        "valid_for_absolute_cost": feasible_for_ranking and not placeholder_rates,
        "cost_basis": (
            "not_computed"
            if not cost_computed
            else "indicative_placeholder_rates"
            if placeholder_rates
            else "versioned_rate_pack"
        ),
        "reasons": sorted(set(ranking_reasons)),
        "claim": comparison_claim,
        "not_for_construction": True,
    }
    if opts.include_quantities:
        entry["quantities"] = {
            "takeoff_ref": "structural_model.quantities.takeoff",
            "bbs_ref": "structural_model.quantities.bbs",
            "boq_ref": "structural_model.quantities.boq",
            "totals": takeoff.to_dict()["totals"],
            "builtup_area_m2": takeoff.to_dict()["builtup_area_m2"],
            "bbs_total_with_wastage_kg": bbs.to_dict().get("total_with_wastage_kg"),
            "boq_total": None if boq_wire is None else boq_wire.get("total"),
            "currency": None if boq_wire is None else boq_wire.get("currency"),
            "boq_subtotals": None if boq_wire is None else boq_wire.get("subtotals"),
            "cost_per_m2": None if boq_wire is None else boq_wire.get("cost_per_m2"),
            "rate_schedule": None if boq_wire is None else boq_wire.get("schedule"),
            "placeholder_rates": None if boq_wire is None else boq_wire.get("placeholder_rates"),
        }
    if opts.include_report:
        entry["report"] = report
    entry["errors"] = errors
    entry["warnings"] = warnings
    entry["status"] = _entry_status(placement, errors, warnings)
    entry["report_status"] = report["summary"]["status"]
    entry["partial"] = entry["status"] == R.STATUS_REFUSED
    entry["disclaimer"] = R.DISCLAIMER
    return entry


# ---------------------------------------------------------------------------
# run_check
# ---------------------------------------------------------------------------

#: Two column stacks closer than this in plan are the same stack (spec 5.8).
DEDUPE_FT = 0.5

#: How far a column may sit from the nearest grid axis before it is off it.
AXIS_TOL_M = ft_to_m(DEDUPE_FT)


def _hard_violations(model: StructuralModel) -> List[Disclosure]:
    """The hard rules `run_check` re-tests on an edited model. Nothing moves.

    Model invariants come from `StructuralModel.validate`; the rest are the
    placement rules a hand edit can break: a column off its grid axis, a span
    past the hard cap, a cantilever past the refusal length, and a column stack
    that loses its support on the way down.
    """
    entries = list(model.validate())

    xs = sorted(axis.pos_m for axis in model.axes if axis.dir == AxisDir.X)
    ys = sorted(axis.pos_m for axis in model.axes if axis.dir == AxisDir.Y)
    off_axis = []  # type: List[str]
    if xs and ys:
        for column in sorted(model.columns, key=lambda c: c.id):
            dx = min(abs(column.x_m - pos) for pos in xs)
            dy = min(abs(column.y_m - pos) for pos in ys)
            if dx > AXIS_TOL_M or dy > AXIS_TOL_M:
                off_axis.append(column.id)
    if off_axis:
        entries.append(
            make_disclosure(
                "W_ECCENTRIC_COLUMN",
                "%d column(s) stand more than %.2f m from the nearest grid axis: %s"
                % (len(off_axis), AXIS_TOL_M, ", ".join(off_axis[:10])),
                off_axis,
                clause="IS 1893 (Part 1):2016 Cl 7.1",
                stage="api.check",
            )
        )

    long_spans = sorted(
        beam.id
        for beam in model.beams
        if beam.span_m() > HARD_MAX_SPAN_M + 1e-6
    )
    if long_spans:
        entries.append(
            make_disclosure(
                "E_SPAN_OVER_MAX",
                "%d beam(s) span past the %.2f m hard cap: %s"
                % (len(long_spans), HARD_MAX_SPAN_M, ", ".join(long_spans[:10])),
                long_spans,
                stage="api.check",
            )
        )

    cantilevers = sorted(
        beam.id
        for beam in model.beams
        if str(getattr(beam.kind, "value", beam.kind)) == "cantilever"
        and beam.span_m() > REFUSE_CANTILEVER_M + 1e-6
    )
    if cantilevers:
        entries.append(
            make_disclosure(
                "E_CANTILEVER_SPAN",
                "%d cantilever(s) reach past the %.2f m refusal length: %s"
                % (len(cantilevers), REFUSE_CANTILEVER_M, ", ".join(cantilevers[:10])),
                cantilevers,
                stage="api.check",
            )
        )

    stacks = {}  # type: Dict[str, List[int]]
    for column in model.columns:
        stacks.setdefault(column.stack_id or column.id, []).append(int(column.storey))
    floating = []  # type: List[str]
    for stack in sorted(stacks):
        levels = sorted(stacks[stack])
        if levels and levels != list(range(min(levels), min(levels) + len(levels))):
            floating.append(stack)
    if floating:
        entries.append(
            make_disclosure(
                "E_TRANSFER_REQUIRED",
                "%d column stack(s) skip a storey, which needs a transfer structure: %s"
                % (len(floating), ", ".join(floating[:10])),
                floating,
                clause="IS 1893 Cl 7.1",
                stage="api.check",
            )
        )
    return entries


def _check_score(model: StructuralModel, violations: Sequence[Disclosure]) -> Dict[str, Any]:
    """The layout score of an edited model: the placed block plus what is re-checkable.

    Nothing is re-placed and nothing is invented. The score the placer computed
    is carried forward under `placed`, and the metrics that CAN be recomputed
    from the model alone are recomputed under `recomputed`, so a reader can see
    whether the edit moved them.
    """
    placed = {}  # type: Dict[str, Any]
    frame_meta = (model.meta or {}).get("frame_placement")
    if isinstance(frame_meta, dict) and isinstance(frame_meta.get("metrics"), dict):
        placed = dict(frame_meta["metrics"])

    spans = sorted(beam.span_m() for beam in model.beams if beam.span_m() > 0.0)
    area_m2 = 0.0
    for slab in model.slabs:
        rect = polygon_rect(slab.polygon)
        area_m2 += rect[2] * rect[3]
    under_wall = sum(1 for beam in model.beams if beam.supports_wall_id)
    recomputed = {
        "axis_count": len(model.axes),
        "column_count": len(model.columns),
        "beam_count": len(model.beams),
        "columns_per_100m2": round(100.0 * len(model.columns) / area_m2, 3) if area_m2 > 0.0 else None,
        "beams_under_walls_pct": round(100.0 * under_wall / len(model.beams), 1) if model.beams else None,
        "span_min_m": round(spans[0], 4) if spans else None,
        "span_max_m": round(spans[-1], 4) if spans else None,
    }
    return {
        "score": placed.get("score"),
        "score_version": placed.get("score_version", R.UNVERSIONED_SCORE),
        "placed": _plain(placed),
        "recomputed": recomputed,
        "hard_violation_count": len(violations),
        "basis": (
            "the composite score is placement-frame's and is carried forward, never "
            "recomputed here: run_check never moves an element, so it cannot re-place "
            "the model the score was measured on"
        ),
    }


def run_check(payload: Any, **options: Any) -> Dict[str, Any]:
    """Re-validate a returned `structural_model`, possibly hand-edited.

    Finding 32: this is a re-check of a model, not a pre-generation feasibility
    question. Nothing here moves an element. `scope: "placement"` runs the hard
    rules and the score; `scope: "full"` adds the loads, the gravity takedown
    and the per-member checks against the EDITED geometry, returning per-element
    pass or fail with the clause each verdict came from.
    """
    from .adapters._geom import AdapterError

    try:
        request = _unwrap_request(payload)
        _check_schema_version(request)
        _check_source(request, ("model",))
        opts = _Resolved(request, dict(options))
        wire = _mapping(request.get("model"), "model")
        problems = validate_wire(wire)
        if problems:
            raise StructuralValidationError("model", "; ".join(problems[:5]))
        scope = opts.scope
        if scope not in SCOPES:
            raise StructuralValidationError(
                "scope", "must be one of " + ", ".join(SCOPES) + ", got " + repr(scope)
            )
        model = StructuralModel.from_dict(wire)
    except StructuralValidationError as error:
        return _error_envelope(error.message, field=error.field, details=error.details)
    except (AdapterError, KeyError, TypeError, ValueError) as error:
        return _error_envelope(
            "the model block could not be parsed: " + str(error), field="model"
        )

    ref = payload_hash(request)
    log = DisclosureLog()
    violations = _hard_violations(model)
    log.extend(violations)

    element_checks = []  # type: List[Dict[str, Any]]
    analysis_block = None  # type: Optional[Dict[str, Any]]
    if scope == "full":
        try:
            placement = _Placement()
            placement.system = str(getattr(model.system, "value", model.system))
            pass_out = _design_once(model, opts, log, placement, place_foundations=False)
            analysis_block = {
                "method": "tributary_takedown_v1",
                "combos_used": [combo.name for combo in pass_out["loadmodel"].combos],
                "seismic": _plain(pass_out["seismic"]),
                "storey_shears": _plain(pass_out["storey_shears"]),
            }
            for result in pass_out["design"]:
                # the clause reported is the governing check's own, so the row a
                # reader sees and the clause beside it are the same check
                governing = str(getattr(result, "governing_check", ""))
                worst = None
                for row in getattr(result, "checks", ()) or ():
                    if governing and str(getattr(row, "name", "")) == governing:
                        worst = row
                        break
                    if worst is None or float(getattr(row, "ratio", 0.0)) > float(
                        getattr(worst, "ratio", 0.0)
                    ):
                        worst = row
                status = str(getattr(result, "status", ""))
                resize_history = _plain(getattr(result, "resize_history", ()) or ())
                geometry_changed = status == "resized" or bool(resize_history)
                element_checks.append(
                    {
                        "element_id": str(getattr(result, "element_id", "")),
                        "element_type": str(getattr(result, "element_type", "")),
                        "status": status,
                        "pass": status == "pass" and not geometry_changed,
                        "check": str(getattr(result, "governing_check", "")),
                        "clause": str(getattr(worst, "clause", "")) if worst is not None else "",
                        "utilization": _num(getattr(result, "utilization_max", 0.0)),
                        "geometry_changed": geometry_changed,
                        "resize_history": resize_history,
                    }
                )
        except Exception as error:  # a check must report, never explode
            log.append(
                make_disclosure(
                    "W_RELEASED_CAP",
                    "the full-scope check could not complete on this edited model ("
                    + type(error).__name__
                    + ": "
                    + str(error)
                    + "); the hard rules above still stand",
                    (),
                    stage="api.check",
                )
            )

    hard = [
        entry.to_dict()
        for entry in log.sorted_entries()
        if Severity(entry.severity) == Severity.ERROR or entry.stage == "api.check"
    ]
    verdict = "PASS" if not hard else "FAIL"
    errors, warnings = _split_ladder(log)

    documents = {
        "schema_version": STRUCTURAL_SCHEMA_VERSION,
        "engine_fingerprint": structural_fingerprint(),
        "units": units_block(),
        "source": "model",
        "system": str(getattr(model.system, "value", model.system)),
        "scope": scope,
        "verdict": verdict,
        "hard_violations": hard,
        "layout_score": _check_score(model, violations),
        "element_checks": element_checks,
        "element_check_count": len(element_checks),
        "element_checks_failed": sum(1 for row in element_checks if not row["pass"]),
        "changed_hint": sorted(
            row["element_id"] for row in element_checks if row["geometry_changed"]
        ),
        "analysis": analysis_block,
        "options_echo": opts.echo(),
        "input_ref": {"source": "model", "model_id": model.id, "hash": ref},
        "errors": errors,
        "warnings": warnings,
        "status": R.STATUS_REFUSED if verdict == "FAIL" else R.STATUS_OK,
        "disclaimer": R.DISCLAIMER,
    }
    message = "structural check: %s, %d hard violation(s), %d element check(s)" % (
        verdict,
        len(hard),
        len(element_checks),
    )
    return _envelope("SUCCESS", message, [documents])
