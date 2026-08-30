"""The report assembler: it computes nothing structural, it ranks and formats.

Spec 07 section 2. Every number in here was produced upstream by placement,
loads, analysis, design or quantities; `build_report` reads those blocks, sorts
them into the human-readable face of the run, and stamps the verbatim
`DISCLAIMER` on it. The only arithmetic this module does is bookkeeping over
numbers it was handed: adding up rows when a stage supplied no total, taking a
maximum across the two seismic directions, and subtracting a blocked element's
own mass back out of the schedule aggregates it was already counted in.

Three normative rules shape the module.

Finding 29 (product-legal). `DISCLAIMER` rides on EVERY response path: ok,
ok_with_warnings, refused, and the empty-design edge case. `build_report`
returns a dict subclass that refuses to have the key deleted, cleared, popped
or overwritten with anything but the constant, so `api.py` cannot strip it by
accident and cannot strip it quietly on purpose.

Finding 7. There is exactly one clause-trace mechanism, the contextvar sink in
`codes/trace.py`. This module renders `TraceEntry` records (`render_trace`) and
reports whether any were kept (`trace_available`); it defines no second trace
machinery, and turning tracing on changes no number in the report.

Finding 33. The layout metrics block belongs to placement. It is mirrored field
for field into `report["layout_metrics"]`, never recomputed, and `score_version`
is always present: an unversioned block is stamped `"unversioned"` so a
cross-run comparison can refuse rather than compare two different formulas.

`summary.system` is the DELIVERED system and it is read from the placement
block, which carries `api._Placement.system`: `choose_system`'s answer as
corrected by whichever placer actually ran. `model.system` is the fallback, not
the source: the adapters set it from the system the caller REQUESTED, so a run
that asked for load_bearing_masonry and was escalated to an RC frame would
otherwise be reported over the wrong system. api.py writes the delivered system
back into the model on both branches, so the two now agree; the order here is
what makes the report right even if some future path forgets to.

The disclosure ladder (spec 2.2, registry codes from `model.REGISTRY`):

  ERROR   blocks. An ERROR that names element ids blocks those elements: their
          cards ship `status: "blocked"` and their per-element quantity rows go
          to zero carrying the code. An ERROR that names no element blocks the
          system: the report still ships, complete, with
          `summary.status == "refused"` and `summary.refusal_reasons`. Never an
          exception, never an empty report.
  WARNING ships, labeled.
  NOTE    informs.

`collect_disclosures` merges the per-stage ladders and dedupes by code with
merged `element_ids`, copying every entry so a merge never mutates the stage
log it came from.

Determinism. Sorted iteration throughout, a total order on the card sort with
`element_id` as the final tiebreak, and no wall clock: `meta.generated_at` is
None unless a caller injects a timestamp through `options`.

Size discipline (spec 07 section "size discipline"). `options["detail"]` picks
how much of the working the report shows. It defaults to `full`, which is what a
direct caller and the batteries get; `api.py` asks for `compact` on the wire.
`compact` changes three blocks and NOTHING else:

  - `element_cards` elides to a pointer. A card repeats a design row field for
    field -- section, reinforcement, governing check, utilization, disclosure
    codes -- and that row rides in the same response at every level, so a second
    copy is duplication, not disclosure. `element_cards_total`, `cards_elided`
    and `detail.element_cards_ref` say so, and `blocked_elements` still names
    every blocked and failed element with its codes and its reason.
  - `bbs.items` elides to its aggregates, which spec 07 already allows, and
    `disclosures` keeps the ERROR entries and points at the entry-level ladder,
    which carries every entry in full on every response path.

The disclaimer, the summary, the totals, the layout metrics, the whole BOQ,
`blocked_elements` and `warnings_summary` are the same at both levels.

Deviations from the spec body, all additive and all disclosed here:
  - `summary.layout_score` carries the compact `{score, score_version}` pair,
    not a second full copy of the 2.5 block, which lives once at
    `report["layout_metrics"]` (size discipline; the block is large).
  - `summary.refusal_reasons`, `report["blocked_elements"]`,
    `report["cards_elided"]`, `report["element_cards_total"]`,
    `report["warnings_summary"]` (named in spec 2.2) and `report["meta"]` are
    additive keys. Additive is a minor bump; clients tolerate unknown fields.
  - Severity keys in `disclosure_counts` are the lowercase `Severity` values
    the shipped `Disclosure.to_dict` already puts on the wire.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .codes.trace import TraceEntry
from .model import Disclosure, DisclosureLog, Severity
from .schema import STRUCTURAL_SCHEMA_VERSION

__all__ = [
    "DISCLAIMER",
    "DISCLAIMER_ONE_LINE",
    "REPORT_VERSION",
    "REPORT_KEYS",
    "SUMMARY_KEYS",
    "TOTALS_KEYS",
    "ELEMENT_COUNT_KEYS",
    "CARD_KEYS",
    "REVIEW_TRIGGER_CODES",
    "STATUS_OK",
    "STATUS_OK_WITH_WARNINGS",
    "STATUS_REFUSED",
    "CARD_OK",
    "CARD_WARNING",
    "CARD_BLOCKED",
    "CARD_CAP",
    "CARDS_PER_CLASS",
    "ROW_CAP",
    "DETAIL_LEVELS",
    "DETAIL_COMPACT",
    "DETAIL_FULL",
    "UNVERSIONED_SCORE",
    "ElementCard",
    "build_report",
    "build_element_card",
    "collect_disclosures",
    "disclaimer_matches",
    "render_trace",
    "with_disclaimer",
]


# ---------------------------------------------------------------------------
# the disclaimer (spec 2.7, verbatim; finding 29)
# ---------------------------------------------------------------------------

#: Product-legal notice. Verbatim, including its line breaks. It is populated
#: unconditionally on every response path and cannot be stripped downstream.
DISCLAIMER = (
    "PRELIMINARY ENGINEERING NOTICE. This structural scheme, analysis, design,\n"
    "and bill of quantities were generated automatically by GPLAN Structural for\n"
    "early-stage planning and costing. They are NOT a construction-ready design.\n"
    "All results are based on stated assumptions and simplified methods and have\n"
    "not been reviewed by a licensed professional. A licensed structural engineer\n"
    "must independently verify, adapt, and sign this design before any\n"
    "construction, regulatory submission, or procurement decision. Foundation\n"
    "results assume the stated soil parameters; a geotechnical investigation is\n"
    "required. Rates marked PLACEHOLDER are indicative only."
)

#: The same notice with its hard wraps collapsed, for renderers that reflow.
DISCLAIMER_ONE_LINE = " ".join(DISCLAIMER.split())


def disclaimer_matches(text: Any) -> bool:
    """True when `text` is the notice, whatever its line wrapping."""
    if not isinstance(text, str):
        return False
    return " ".join(text.split()) == DISCLAIMER_ONE_LINE


# ---------------------------------------------------------------------------
# vocabulary
# ---------------------------------------------------------------------------

#: Bumped when the report layout changes; the wire schema version rides beside it.
REPORT_VERSION = "report-1"

STATUS_OK = "ok"
STATUS_OK_WITH_WARNINGS = "ok_with_warnings"
STATUS_REFUSED = "refused"

CARD_OK = "ok"
CARD_WARNING = "warning"
CARD_BLOCKED = "blocked"

#: Design statuses, mirroring design/common.py (frozen wire vocabulary).
_DESIGN_PASS = "pass"
_DESIGN_RESIZED = "resized"
_DESIGN_FAIL = "fail"
_CHECK_FAIL = "fail"

#: Cards are a view, not the record: past this many designed elements only the
#: governing worst `CARDS_PER_CLASS` of each class are rendered (spec 2.4).
CARD_CAP = 200
CARDS_PER_CLASS = 50

#: Embedded schedules are capped at this many rows, aggregates kept intact.
ROW_CAP = 500

#: How much working the report shows. `full` is this module's own default, so a
#: direct caller sees everything; `api.py` asks for `compact` on the wire.
DETAIL_COMPACT = "compact"
DETAIL_FULL = "full"
DETAIL_LEVELS = (DETAIL_COMPACT, DETAIL_FULL)

#: Stamped on a layout block that carries no formula version, so a cross-run
#: comparison refuses instead of comparing two different composites.
UNVERSIONED_SCORE = "unversioned"

#: A design that came back `fail` blocks its element too, but carries no
#: registry code. Its zeroed schedule rows are marked with this instead, so a
#: row always says what blocked it. Deliberately not shaped like a REGISTRY code.
_BLOCKED_DESIGN_MARK = "design_status:fail"

#: `engineer_review_required` is true iff one of these is on the ladder
#: (spec 2.2). The spec names the conditions; these are their registry codes.
#: `E_MASONRY_LIMIT` stands in for the spec's `zone_v_masonry`: the registry
#: ships no separate zone V warning, and the masonry seismic-category refusal
#: is the closest registered condition.
REVIEW_TRIGGER_CODES = (
    "E_MASONRY_LIMIT",
    "E_TRANSFER_REQUIRED",
    "W_RELEASED_CAP",
    "W_TALL",
    "W_TORSION",
)

#: Key sets, exported so consumers and tests can assert the emitted shape.
REPORT_KEYS = (
    "meta",
    "summary",
    "element_cards",
    "element_cards_total",
    "cards_elided",
    "disclosures",
    "warnings_summary",
    "layout_metrics",
    "blocked_elements",
    "boq",
    "bbs",
    "detail",
    "disclaimer",
    "trace_available",
)

SUMMARY_KEYS = (
    "status",
    "system",
    "storeys",
    "height_m",
    "seismic",
    "totals",
    "element_counts",
    "layout_score",
    "engineer_review_required",
    "disclosure_counts",
    "blocked_element_count",
    "refusal_reasons",
)

TOTALS_KEYS = (
    "concrete_m3",
    "steel_kg",
    "masonry_m3",
    "formwork_m2",
    "excavation_m3",
    "cost",
    "currency",
    "cost_per_m2",
    "steel_kg_per_m2",
)

ELEMENT_COUNT_KEYS = (
    "columns",
    "beams",
    "slabs",
    "footings",
    "bands",
    "lintels",
    "walls_bearing",
)

CARD_KEYS = (
    "element_id",
    "element_class",
    "storey",
    "geometry_ref",
    "status",
    "design_status",
    "section",
    "reinforcement",
    "governing",
    "utilization_max",
    "checks",
    "disclosure_codes",
)

_SEISMIC_DIRECTIONS = ("x", "y")

#: How a stirrup/tie/hoop kind is spoken on a card.
_STIRRUP_WORDS = {
    "shear": "stirrups",
    "stirrup": "stirrups",
    "tie": "ties",
    "ties": "ties",
    "hoop": "hoops",
    "confinement": "hoops",
    "link": "links",
    "links": "links",
}


# ---------------------------------------------------------------------------
# the protected envelope (finding 29: api.py must not be able to strip it)
# ---------------------------------------------------------------------------


class _ProtectedReport(dict):
    """A plain JSON-serializable dict that will not give up its disclaimer.

    Deleting, popping, clearing or overwriting `disclaimer` raises. Everything
    else behaves exactly like a dict, so `json.dumps` and `dict(report)` work
    unchanged.
    """

    _GUARDED = "disclaimer"

    def _refuse(self, what: str) -> None:
        raise ValueError(
            "the structural report disclaimer is required on every response path "
            "(spec 07 section 2.7, finding 29) and cannot be " + what
        )

    def __setitem__(self, key: Any, value: Any) -> None:
        if key == self._GUARDED and not disclaimer_matches(value):
            self._refuse("replaced")
        dict.__setitem__(self, key, value)

    def __delitem__(self, key: Any) -> None:
        if key == self._GUARDED:
            self._refuse("deleted")
        dict.__delitem__(self, key)

    def pop(self, key: Any, *default: Any) -> Any:
        if key == self._GUARDED:
            self._refuse("popped")
        return dict.pop(self, key, *default)

    def popitem(self) -> Any:
        keys = list(self.keys())
        if keys and keys[-1] == self._GUARDED:
            self._refuse("popped")
        return dict.popitem(self)

    def clear(self) -> None:
        if self._GUARDED in self:
            self._refuse("cleared")
        dict.clear(self)

    def setdefault(self, key: Any, default: Any = None) -> Any:
        if key == self._GUARDED and key not in self and not disclaimer_matches(default):
            self._refuse("replaced")
        return dict.setdefault(self, key, default)

    def update(self, *args: Any, **kwargs: Any) -> None:
        incoming = dict(*args, **kwargs)
        if self._GUARDED in incoming and not disclaimer_matches(incoming[self._GUARDED]):
            self._refuse("replaced")
        dict.update(self, incoming)


def with_disclaimer(payload: Any) -> Dict[str, Any]:
    """Stamp the notice on any response envelope and protect it there.

    Finding 29: every response of every endpoint carries a top-level
    `disclaimer`, refusals and errors included. `api.py` wraps its envelope with
    this and gets a mapping that cannot lose the key afterwards.
    """
    out = _ProtectedReport()
    if isinstance(payload, Mapping):
        for key in payload:
            if key != "disclaimer":
                dict.__setitem__(out, key, payload[key])
    dict.__setitem__(out, "disclaimer", DISCLAIMER)
    return out


# ---------------------------------------------------------------------------
# small readers (every input may arrive as an object, a dict, or not at all)
# ---------------------------------------------------------------------------


def _as_dict(value: Any) -> Dict[str, Any]:
    """A dict view of a stage output: mapping, `.to_dict()`, or empty."""
    if value is None:
        return {}
    if isinstance(value, Mapping):
        return dict(value)
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        try:
            result = to_dict()
        except Exception:  # a stage that cannot serialize is not a report crash
            return {}
        if isinstance(result, Mapping):
            return dict(result)
    return {}


def _unwrap(block: Any, *names: str) -> Dict[str, Any]:
    """Accept either the block itself or a wrapper carrying it under a name."""
    data = _as_dict(block)
    for name in names:
        inner = data.get(name)
        if isinstance(inner, Mapping):
            return dict(inner)
    return data


def _num(value: Any, default: float = 0.0) -> float:
    """A float, or `default` for anything that is not a plain number."""
    if isinstance(value, bool) or value is None:
        return default
    if isinstance(value, (int, float)):
        return float(value)
    return default


def _int(value: Any, default: int = 0) -> int:
    if isinstance(value, bool) or value is None:
        return default
    if isinstance(value, (int, float)):
        return int(value)
    return default


def _r3(value: float) -> float:
    return round(float(value), 3) + 0.0


def _pick(block: Mapping[str, Any], *keys: str) -> Any:
    """The first of `keys` the block answers with something that is not None."""
    for key in keys:
        value = block.get(key)
        if value is not None:
            return value
    return None


def _rows(block: Mapping[str, Any], key: str) -> List[Any]:
    rows = block.get(key)
    return list(rows) if isinstance(rows, (list, tuple)) else []


def _sum_rows(rows: Sequence[Any], key: str) -> float:
    total = 0.0
    for row in rows:
        if isinstance(row, Mapping):
            total += _num(row.get(key))
    return total


def _total_or_sum(block: Mapping[str, Any], total_key: str, rows_key: str, row_key: str) -> float:
    """Prefer the total the producer stated; add its rows up only if it stated none."""
    totals = block.get("totals")
    if isinstance(totals, Mapping) and totals.get(total_key) is not None:
        return _r3(_num(totals.get(total_key)))
    if block.get(total_key) is not None:
        return _r3(_num(block.get(total_key)))
    return _r3(_sum_rows(_rows(block, rows_key), row_key))


class _Options(object):
    """Reader over an options dict or object; every knob has a default."""

    def __init__(self, options: Any = None):
        self._data = options

    def get(self, key: str, default: Any = None) -> Any:
        source = self._data
        if source is None:
            return default
        if isinstance(source, Mapping):
            value = source.get(key, default)
        else:
            value = getattr(source, key, default)
        return default if value is None else value

    def flag(self, key: str, default: bool = False) -> bool:
        return bool(self.get(key, default))

    def count(self, key: str, default: int) -> int:
        value = _int(self.get(key, default), default)
        return value if value > 0 else default


# ---------------------------------------------------------------------------
# collect_disclosures
# ---------------------------------------------------------------------------


def _copy_entry(entry: Disclosure) -> Disclosure:
    """A detached copy: merging must never mutate the stage log it came from."""
    return Disclosure(
        code=str(entry.code),
        severity=Severity(entry.severity),
        message=str(entry.message),
        element_ids=[str(item) for item in entry.element_ids],
        clause=entry.clause,
        stage=str(entry.stage),
    )


def _entries_from(stage: Any, seen: Optional[List[int]] = None) -> List[Disclosure]:
    """Every Disclosure a stage carries, in the stage's own order."""
    if stage is None:
        return []
    if seen is None:
        seen = []
    marker = id(stage)
    if marker in seen:
        return []
    seen.append(marker)

    if isinstance(stage, Disclosure):
        return [_copy_entry(stage)]
    if isinstance(stage, DisclosureLog):
        return [_copy_entry(entry) for entry in stage.entries]

    if isinstance(stage, Mapping):
        out = []  # type: List[Disclosure]
        for key in ("disclosures", "warnings", "log", "entries"):
            if key in stage:
                out.extend(_entries_from(stage[key], seen))
        if out:
            return out
        if "code" in stage and "severity" in stage:
            try:
                return [Disclosure.from_dict(dict(stage))]
            except Exception:
                return []
        return []

    if isinstance(stage, (list, tuple)):
        out = []
        for item in stage:
            out.extend(_entries_from(item, seen))
        return out

    out = []
    for name in ("log", "warnings", "disclosures"):
        holder = getattr(stage, name, None)
        if holder is not None:
            out.extend(_entries_from(holder, seen))
    return out


def collect_disclosures(*stages: Any) -> DisclosureLog:
    """Merge every stage ladder into one log, deduped by code.

    A stage may be a `DisclosureLog`, a `StructuralModel` (or anything else with
    `.warnings` / `.log` / `.disclosures`), a list of `Disclosure` objects or of
    their dicts, a single `Disclosure`, a stage dict carrying a `disclosures`
    key, or None. Entries are copied before merging, so the caller's logs are
    left exactly as they were; a repeated code keeps the first message and the
    union of the element ids, per spec 2.2.
    """
    log = DisclosureLog()
    for stage in stages:
        for entry in _entries_from(stage):
            log.append(entry)
    return log


# ---------------------------------------------------------------------------
# clause trace rendering (finding 7: render the one sink, define no other)
# ---------------------------------------------------------------------------


def render_trace(entries: Any) -> List[Dict[str, Any]]:
    """TraceEntry records rendered for a calc sheet, in emission order.

    Pure formatting over the `codes/trace.py` sink: symbol, inputs, output,
    units and the clause id per line, plus the latex string when the clause
    carries one. The deferred PDF phase renders this list and computes nothing.
    """
    out = []  # type: List[Dict[str, Any]]
    for entry in list(entries or []):
        if isinstance(entry, TraceEntry):
            row = entry.to_dict()
        elif isinstance(entry, Mapping):
            row = dict(entry)
        else:
            continue
        code = str(row.get("code", ""))
        ref = str(row.get("ref", ""))
        row["clause"] = (code + " " + ref).strip()
        inputs = row.get("inputs")
        row["inputs"] = dict(inputs) if isinstance(inputs, Mapping) else {}
        out.append(row)
    return out


def _trace_entry_count(design_rows: Sequence[Mapping[str, Any]], extra: Any) -> int:
    count = 0
    for row in design_rows:
        trace = row.get("trace")
        if isinstance(trace, (list, tuple)):
            count += len(trace)
    if isinstance(extra, (list, tuple)):
        count += len(extra)
    return count


# ---------------------------------------------------------------------------
# display strings
# ---------------------------------------------------------------------------


def _mm_word(value: Any) -> str:
    """A millimetre dimension without a pointless decimal tail."""
    number = _num(value)
    if abs(number - round(number)) < 1e-6:
        return str(int(round(number)))
    return ("%.1f" % number).rstrip("0").rstrip(".")


def _grade_word(materials: Mapping[str, Any]) -> str:
    for key in ("concrete_grade", "steel_grade", "mortar_grade", "material"):
        value = materials.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


def section_text(section: Mapping[str, Any], materials: Mapping[str, Any]) -> str:
    """The card's section line, for example `230x450 M25`.

    Reads whatever the designer put in `DesignResult.section`: a `b_mm x D_mm`
    rectangle, a footing `bx_mm x ly_mm x D_mm` block, or a wall/slab
    `thickness_mm`. Nothing is derived; a section with none of those reads `-`.
    """
    body = ""
    b_mm = section.get("b_mm")
    d_mm = section.get("D_mm")
    bx_mm = section.get("bx_mm")
    ly_mm = section.get("ly_mm")
    thickness = section.get("thickness_mm")
    waist = section.get("waist_mm")
    if bx_mm is not None and ly_mm is not None:
        body = _mm_word(bx_mm) + "x" + _mm_word(ly_mm)
        if d_mm is not None:
            body += "x" + _mm_word(d_mm)
    elif waist is not None and b_mm is None:
        body = _mm_word(waist) + " waist"
    elif b_mm is not None and d_mm is not None:
        body = _mm_word(b_mm) + "x" + _mm_word(d_mm)
    elif thickness is not None:
        body = _mm_word(thickness) + " thk"
    elif d_mm is not None:
        body = _mm_word(d_mm) + " thk"
    if not body:
        return "-"
    grade = _grade_word(materials)
    return (body + " " + grade).strip()


def _bar_word(count: int, dia_mm: Any, spacing_mm: Any) -> str:
    if spacing_mm is not None and _num(spacing_mm) > 0.0:
        return _mm_word(dia_mm) + "@" + _mm_word(spacing_mm)
    return str(int(count)) + "-" + _mm_word(dia_mm)


def reinforcement_text(bars: Sequence[Any], stirrups: Sequence[Any]) -> str:
    """The card's reinforcement line, for example `4-16 + 2-12, ties 8@150/100`.

    Bars of the same role, diameter and spacing are merged and their counts
    added; roles are named only when the member carries more than one, so a
    beam reads `top 2-16 + bottom 3-16` and a footing mesh reads `12@150`. The
    structured data stays in the design section; this is the display face.
    """
    groups = {}  # type: Dict[Tuple[str, float, float], int]
    for bar in bars or []:
        if not isinstance(bar, Mapping):
            continue
        dia = _num(bar.get("dia_mm"))
        if dia <= 0.0:
            continue
        spacing = _num(bar.get("spacing_mm"), -1.0)
        key = (str(bar.get("role", "")), dia, spacing)
        groups[key] = groups.get(key, 0) + max(0, _int(bar.get("count")))

    roles = sorted({key[0] for key in groups})
    name_roles = len(roles) > 1
    parts = []  # type: List[str]
    for key in sorted(groups, key=lambda k: (k[0], -k[1], k[2])):
        role, dia, spacing = key
        word = _bar_word(groups[key], dia, None if spacing < 0.0 else spacing)
        if name_roles and role:
            word = role + " " + word
        parts.append(word)
    text = " + ".join(parts)

    kinds = {}  # type: Dict[str, List[Tuple[float, float]]]
    for stirrup in stirrups or []:
        if not isinstance(stirrup, Mapping):
            continue
        dia = _num(stirrup.get("dia_mm"))
        spacing = _num(stirrup.get("spacing_mm"))
        if dia <= 0.0 or spacing <= 0.0:
            continue
        kind = str(stirrup.get("kind", "shear"))
        word = _STIRRUP_WORDS.get(kind, kind)
        pairs = kinds.setdefault(word, [])
        if (dia, spacing) not in pairs:
            pairs.append((dia, spacing))

    tails = []  # type: List[str]
    for word in sorted(kinds):
        pairs = sorted(kinds[word])
        dias = sorted({pair[0] for pair in pairs})
        if len(dias) == 1:
            spacings = "/".join(_mm_word(pair[1]) for pair in sorted(pairs, key=lambda p: -p[1]))
            tails.append(word + " " + _mm_word(dias[0]) + "@" + spacings)
        else:
            tails.append(
                word + " " + " + ".join(_mm_word(pair[0]) + "@" + _mm_word(pair[1]) for pair in pairs)
            )

    if tails:
        text = (text + ", " if text else "") + ", ".join(tails)
    return text if text else "-"


# ---------------------------------------------------------------------------
# element cards
# ---------------------------------------------------------------------------


@dataclass
class ElementCard:
    """The human-readable face of one DesignResult (spec 2.4).

    Geometry is not repeated here: `geometry_ref` points into the placement
    section of the envelope, which owns it. `utilization` is emitted even when
    it is over 1, so a blocked element shows why it was blocked.
    """

    element_id: str
    element_class: str
    storey: Optional[int] = None
    geometry_ref: str = ""
    status: str = CARD_OK
    design_status: str = _DESIGN_PASS
    section: str = "-"
    reinforcement: str = "-"
    governing: Dict[str, Any] = field(default_factory=dict)
    utilization_max: float = 0.0
    checks: List[Dict[str, Any]] = field(default_factory=list)
    disclosure_codes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "element_id": self.element_id,
            "element_class": self.element_class,
            "storey": self.storey,
            "geometry_ref": self.geometry_ref,
            "status": self.status,
            "design_status": self.design_status,
            "section": self.section,
            "reinforcement": self.reinforcement,
            "governing": dict(self.governing),
            "utilization_max": _r3(self.utilization_max),
            "checks": [dict(row) for row in self.checks],
            "disclosure_codes": list(self.disclosure_codes),
        }

    def sort_key(self) -> Tuple[Any, ...]:
        """Blocked first, then by descending utilization, then by id."""
        return (0 if self.status == CARD_BLOCKED else 1, -self.utilization_max, self.element_id)


_CLASS_COLLECTIONS = {
    "column": "columns",
    "beam": "beams",
    "slab": "slabs",
    "footing": "footings",
    "band": "bands",
    "lintel": "lintels",
    "wall": "walls",
    "stair": "slabs",
}


def _geometry_ref(element_class: str, element_id: str, storey: Optional[int]) -> str:
    fallback = (element_class + "s") if element_class else "elements"
    collection = _CLASS_COLLECTIONS.get(element_class, fallback)
    if storey is None:
        return "placement." + collection + "#" + element_id
    return "placement.storeys[" + str(int(storey)) + "]." + collection + "#" + element_id


def _check_rows(checks: Any) -> List[Dict[str, Any]]:
    """CheckRow dicts rendered into the card's wire shape."""
    out = []  # type: List[Dict[str, Any]]
    for row in list(checks or []):
        data = _as_dict(row)
        if not data:
            continue
        status = str(data.get("status", ""))
        out.append(
            {
                "check": str(_pick(data, "name", "check") or ""),
                "clause": str(data.get("clause") or ""),
                "demand": _num(data.get("demand")),
                "capacity": _num(data.get("capacity")),
                "unit": str(_pick(data, "units", "unit") or ""),
                "utilization": _num(_pick(data, "ratio", "utilization")),
                "pass": status != _CHECK_FAIL,
            }
        )
    return out


def _governing(rows: Sequence[Mapping[str, Any]], named: str, utilization_max: float) -> Dict[str, Any]:
    """The named governing check, or the worst row when the design named none."""
    chosen = None  # type: Optional[Mapping[str, Any]]
    for row in rows:
        if named and row.get("check") == named:
            chosen = row
            break
    if chosen is None:
        for row in rows:
            if chosen is None or _num(row.get("utilization")) > _num(chosen.get("utilization")):
                chosen = row
    if chosen is None:
        return {"check": named, "clause": "", "utilization": _r3(utilization_max)}
    return {
        "check": str(chosen.get("check", named)),
        "clause": str(chosen.get("clause", "")),
        "utilization": _r3(_num(chosen.get("utilization"))),
    }


def build_element_card(
    result: Any,
    storey: Optional[int] = None,
    disclosure_codes: Sequence[str] = (),
    blocked_codes: Sequence[str] = (),
) -> ElementCard:
    """One card from one DesignResult (object or dict). Formats, never computes.

    `blocked_codes` are the ERROR codes naming this element; any of them, or a
    design that came back `fail`, ships the card as `blocked`.
    """
    data = _as_dict(result)
    element_id = str(data.get("element_id") or "")
    element_class = str(_pick(data, "element_type", "element_class") or "")
    design_status = str(data.get("status") or _DESIGN_PASS)

    section = data.get("section")
    section = dict(section) if isinstance(section, Mapping) else {}
    materials = data.get("materials")
    materials = dict(materials) if isinstance(materials, Mapping) else {}
    if storey is None and section.get("storey") is not None:
        storey = _int(section.get("storey"), 0)

    rows = _check_rows(data.get("checks"))
    utilization_max = _num(data.get("utilization_max"))
    if not data.get("utilization_max") and rows:
        utilization_max = max(_num(row.get("utilization")) for row in rows)

    codes = sorted({str(code) for code in disclosure_codes})
    blocked = sorted({str(code) for code in blocked_codes})
    if blocked:
        status = CARD_BLOCKED
    elif design_status == _DESIGN_FAIL:
        status = CARD_BLOCKED
    elif design_status == _DESIGN_RESIZED or codes:
        status = CARD_WARNING
    else:
        status = CARD_OK

    return ElementCard(
        element_id=element_id,
        element_class=element_class,
        storey=storey,
        geometry_ref=_geometry_ref(element_class, element_id, storey),
        status=status,
        design_status=design_status,
        section=section_text(section, materials),
        reinforcement=reinforcement_text(data.get("bars") or [], data.get("stirrups") or []),
        governing=_governing(rows, str(data.get("governing_check", "")), utilization_max),
        utilization_max=utilization_max,
        checks=rows,
        disclosure_codes=codes,
    )


def _elide_cards(cards: List[ElementCard], cap: int, per_class: int) -> Tuple[List[ElementCard], int]:
    """Past `cap` elements keep the governing worst `per_class` of each class."""
    cards = sorted(cards, key=lambda card: card.sort_key())
    if len(cards) <= cap:
        return cards, 0
    by_class = {}  # type: Dict[str, List[ElementCard]]
    for card in cards:
        by_class.setdefault(card.element_class, []).append(card)
    kept = []  # type: List[ElementCard]
    for name in sorted(by_class):
        kept.extend(by_class[name][:per_class])
    kept.sort(key=lambda card: card.sort_key())
    return kept, len(cards) - len(kept)


def _compact_cards(cards: Sequence[ElementCard]) -> Tuple[List[ElementCard], int]:
    """No cards, and the count of what a `full` report would have rendered.

    A card repeats a design row field for field -- section, reinforcement,
    governing check, utilization, disclosure codes -- and that row rides in the
    same response at every level, so at `compact` the whole list is a pointer.
    Nothing is lost: `blocked_elements` still names every blocked and failed
    element with its codes and its reason, `summary.blocked_element_count` still
    counts them, and `detail.element_cards_ref` says where the fields are.
    """
    return [], len(cards)


# ---------------------------------------------------------------------------
# summary blocks
# ---------------------------------------------------------------------------


def _seismic_block(model: Any, analysis: Any) -> Optional[Dict[str, Any]]:
    """Summary seismic figures, mirrored from the seismic report (never recomputed).

    The report carries Ta, Ah and the base shear per direction; the summary
    scalars are the governing (larger) of the two and `by_direction` keeps both.
    """
    source = _as_dict(getattr(model, "seismic", None))
    if not source:
        source = _unwrap(analysis, "seismic")
    if not source:
        return None

    directions = source.get("directions")
    by_direction = {}  # type: Dict[str, Dict[str, Any]]
    if isinstance(directions, Mapping):
        for name in _SEISMIC_DIRECTIONS:
            block = directions.get(name)
            if isinstance(block, Mapping):
                by_direction[name] = {
                    "ta_s": _r3(_num(block.get("ta_s"))),
                    "ah": round(_num(block.get("ah")), 6) + 0.0,
                    "base_shear_kn": _r3(_num(block.get("base_shear_kn"))),
                }

    def governing(key: str, places: int = 3) -> float:
        values = [block[key] for block in by_direction.values()]
        if values:
            return max(values)
        return round(_num(source.get(key)), places) + 0.0

    return {
        "zone": str(source.get("zone", "")),
        "z": _num(_pick(source, "z", "zone_factor")),
        "i": _num(_pick(source, "i", "importance_factor")),
        "r": _num(_pick(source, "r", "response_reduction")),
        "ta_s": governing("ta_s"),
        "ah": governing("ah", 6),
        "base_shear_kn": governing("base_shear_kn"),
        "seismic_weight_kn": _r3(_num(source.get("seismic_weight_kn"))),
        "by_direction": by_direction,
    }


def _element_counts(model: Any) -> Dict[str, Any]:
    counts = {key: 0 for key in ELEMENT_COUNT_KEYS}
    if model is None:
        return counts
    for slot, key in (
        ("columns", "columns"),
        ("beams", "beams"),
        ("slabs", "slabs"),
        ("footings", "footings"),
        ("bands", "bands"),
        ("lintels", "lintels"),
    ):
        counts[key] = len(getattr(model, slot, None) or [])
    walls = getattr(model, "walls", None) or []
    counts["walls_bearing"] = sum(1 for wall in walls if getattr(wall, "bearing", None) is True)
    return counts


def _storey_block(model: Any) -> Tuple[int, float]:
    storeys = getattr(model, "storeys", None) or []
    top = 0.0
    for storey in storeys:
        top = max(top, _num(getattr(storey, "bottom_z_m", 0.0)) + _num(getattr(storey, "height_m", 0.0)))
    return len(storeys), _r3(top)


def _totals_block(takeoff: Mapping[str, Any], bbs: Mapping[str, Any], boq: Mapping[str, Any]) -> Dict[str, Any]:
    """Headline totals, read from the quantity blocks and never reinvented.

    `steel_kg` comes from the schedule AFTER blocked rows were zeroed, so it
    agrees with the embedded BBS. The class-aggregated take-off rows and the
    priced BOQ totals are passed through as their producers stated them: a row
    covering a whole class cannot be unpicked here, so an ERROR has to reach
    quantities.py for those to drop, and `blocked_elements` says which elements
    are in question.
    """
    earthwork = takeoff.get("earthwork")
    earthwork = earthwork if isinstance(earthwork, Mapping) else {}
    steel_kg = bbs.get("total_with_wastage_kg")
    if steel_kg is None:
        steel_kg = bbs.get("total_kg")
    return {
        "concrete_m3": _total_or_sum(takeoff, "concrete_m3", "concrete", "volume_m3"),
        "steel_kg": _r3(_num(steel_kg)),
        "masonry_m3": _total_or_sum(takeoff, "masonry_m3", "masonry", "volume_m3"),
        "formwork_m2": _total_or_sum(takeoff, "formwork_m2", "formwork", "area_m2"),
        "excavation_m3": _r3(_num(earthwork.get("excavation_m3"))),
        "cost": _r3(_num(boq.get("total"))),
        "currency": str(boq.get("currency", "")) if boq else "",
        "cost_per_m2": _r3(_num(boq.get("cost_per_m2"))),
        "steel_kg_per_m2": _r3(_num(boq.get("steel_kg_per_m2"))),
    }


def _layout_metrics(layout_score: Any, placement: Any) -> Dict[str, Any]:
    """Placement's block, mirrored field for field, `score_version` guaranteed."""
    block = _as_dict(layout_score)
    if not block:
        block = _unwrap(placement, "metrics")
    out = dict(block)
    version = out.get("score_version")
    if not isinstance(version, str) or not version:
        out["score_version"] = UNVERSIONED_SCORE
    return out


def _refusal_reasons(system_errors: Sequence[Disclosure], extra: Any) -> List[Dict[str, Any]]:
    """System-level ERRORs plus any refusal the orchestrator passed in."""
    reasons = []  # type: List[Dict[str, Any]]
    seen = []  # type: List[Tuple[str, str]]
    for entry in system_errors:
        key = (str(entry.code), str(entry.message))
        if key in seen:
            continue
        seen.append(key)
        reasons.append(
            {
                "code": str(entry.code),
                "clause": entry.clause,
                "message": str(entry.message),
                "stage": str(entry.stage),
            }
        )
    for item in _refusal_items(extra):
        key = (str(item.get("code", "")), str(item.get("message", "")))
        if key in seen:
            continue
        seen.append(key)
        reasons.append(item)
    return reasons


def _refusal_items(extra: Any) -> List[Dict[str, Any]]:
    if extra is None:
        return []
    if isinstance(extra, str):
        return [{"code": "", "clause": None, "message": extra, "stage": ""}]
    if isinstance(extra, Mapping) or not isinstance(extra, (list, tuple)):
        candidates = [extra]  # type: List[Any]
    else:
        candidates = list(extra)
    out = []  # type: List[Dict[str, Any]]
    for candidate in candidates:
        data = _as_dict(candidate)
        if not data:
            if isinstance(candidate, str):
                out.append({"code": "", "clause": None, "message": candidate, "stage": ""})
            continue
        out.append(
            {
                "code": str(data.get("code", "")),
                "clause": data.get("clause"),
                "message": str(data.get("reason", data.get("message", ""))),
                "stage": str(data.get("stage", "")),
            }
        )
    return out


# ---------------------------------------------------------------------------
# embedded schedules
# ---------------------------------------------------------------------------


def _cap_rows(block: Mapping[str, Any], key: str, cap: int) -> Dict[str, Any]:
    """Row cap with the aggregates kept intact and the eliding declared."""
    out = dict(block)
    rows = _rows(block, key)
    out[key] = [dict(row) if isinstance(row, Mapping) else row for row in rows[:cap]]
    out["items_total"] = len(rows)
    out["items_shown"] = len(out[key])
    out["items_elided"] = len(rows) > cap
    return out


def _zero_blocked_bbs(
    block: Dict[str, Any], blocked: Mapping[str, List[str]]
) -> Tuple[Dict[str, Any], List[str]]:
    """An ERROR blocks its element: its schedule rows go to zero, with the code.

    The aggregates the schedule already counted those rows in are corrected by
    subtraction, and what was removed is stated in `blocked_mass_kg`. With
    nothing blocked the schedule passes through untouched.

    Only per-element rows can be zeroed here. The take-off's class-aggregated
    rows carry no element id, so an ERROR has to reach quantities.py for those
    (and therefore for `summary.totals`) to be right; the report says which
    elements were blocked rather than guessing at a class row's composition.

    Returns the schedule and the ids whose rows were actually zeroed.
    """
    if not blocked:
        return block, []
    rows = _rows(block, "items")
    removed_by_dia = {}  # type: Dict[str, float]
    removed_by_class = {}  # type: Dict[str, float]
    removed = 0.0
    zeroed = []  # type: List[str]
    items = []  # type: List[Any]
    for row in rows:
        if not isinstance(row, Mapping):
            items.append(row)
            continue
        element_id = str(row.get("element_id", ""))
        codes = blocked.get(element_id)
        if not codes:
            items.append(dict(row))
            continue
        if element_id not in zeroed:
            zeroed.append(element_id)
        item = dict(row)
        mass = _num(item.get("total_mass_kg"))
        removed += mass
        dia_key = str(_int(item.get("dia_mm")))
        removed_by_dia[dia_key] = removed_by_dia.get(dia_key, 0.0) + mass
        class_key = str(item.get("element_class", ""))
        removed_by_class[class_key] = removed_by_class.get(class_key, 0.0) + mass
        item["count"] = 0
        item["total_mass_kg"] = 0.0
        item["blocked"] = True
        item["blocked_by"] = list(codes)
        notes = item.get("notes")
        notes = [str(note) for note in notes] if isinstance(notes, (list, tuple)) else []
        notes.append("blocked by " + ", ".join(codes) + "; no quantity taken")
        item["notes"] = notes
        items.append(item)

    if not zeroed:
        return block, []

    out = dict(block)
    out["items"] = items
    for field_name, removed_map in (("mass_by_dia", removed_by_dia), ("mass_by_class", removed_by_class)):
        source = out.get(field_name)
        if isinstance(source, Mapping):
            corrected = {}
            for key in sorted(source, key=str):
                corrected[key] = _r3(max(0.0, _num(source[key]) - removed_map.get(str(key), 0.0)))
            out[field_name] = corrected
    total = _num(out.get("total_kg"))
    if total:
        total = max(0.0, total - removed)
        out["total_kg"] = _r3(total)
        wastage = _num(out.get("wastage_pct"))
        out["total_with_wastage_kg"] = _r3(total * (1.0 + wastage / 100.0))
    out["blocked_mass_kg"] = _r3(removed)
    return out, sorted(zeroed)


# ---------------------------------------------------------------------------
# build_report
# ---------------------------------------------------------------------------


def build_report(
    model: Any = None,
    placement: Any = None,
    analysis: Any = None,
    design_results: Any = (),
    takeoff: Any = None,
    bbs: Any = None,
    boq: Any = None,
    layout_score: Any = None,
    disclosures: Any = None,
    options: Any = None,
) -> Dict[str, Any]:
    """Assemble the report envelope (spec 2.3). Never raises for a modelling refusal.

    Every argument is optional: an empty call still returns a complete,
    disclaimer-carrying envelope, which is what the refusal and empty-design
    paths need. `disclosures` is the merged ladder (`collect_disclosures`); when
    it is omitted the ladders on `model`, `placement` and `analysis` are merged
    here instead.

    Options: `trace` (whether tracing was requested), `include_trace` (render
    the sink entries into `report["trace"]`, default off so trace on and trace
    off differ only in `trace_available`), `detail` (`full`, the default here, or
    `compact`; see the module docstring), `card_cap`, `cards_per_class`,
    `row_cap`, `refusals`, and `generated_at` (an injected timestamp; the report
    never reads the clock itself).
    """
    opts = _Options(options)
    detail = str(opts.get("detail", DETAIL_FULL) or DETAIL_FULL).strip().lower()
    compact = detail == DETAIL_COMPACT

    if disclosures is not None:
        log = collect_disclosures(disclosures)
    else:
        log = collect_disclosures(model, placement, analysis)
    entries = log.sorted_entries()

    blocked_codes = {}  # type: Dict[str, List[str]]
    system_errors = []  # type: List[Disclosure]
    codes_by_element = {}  # type: Dict[str, List[str]]
    for entry in entries:
        severity = Severity(entry.severity)
        for element_id in entry.element_ids:
            key = str(element_id)
            bucket = codes_by_element.setdefault(key, [])
            if entry.code not in bucket:
                bucket.append(str(entry.code))
            if severity == Severity.ERROR:
                blocked = blocked_codes.setdefault(key, [])
                if entry.code not in blocked:
                    blocked.append(str(entry.code))
        if severity == Severity.ERROR and not entry.element_ids:
            system_errors.append(entry)

    design_rows = [_as_dict(item) for item in list(design_results or [])]
    design_rows = [row for row in design_rows if row]

    storey_index = _storey_index(model)
    cards = []  # type: List[ElementCard]
    blocked_elements = []  # type: List[Dict[str, Any]]
    for row in design_rows:
        element_id = str(row.get("element_id", ""))
        card = build_element_card(
            row,
            storey=storey_index.get(element_id),
            disclosure_codes=codes_by_element.get(element_id, ()),
            blocked_codes=blocked_codes.get(element_id, ()),
        )
        cards.append(card)
        if card.status == CARD_BLOCKED:
            codes = list(blocked_codes.get(element_id, ()))
            blocked_elements.append(
                {
                    "element_id": element_id,
                    "element_class": card.element_class,
                    "codes": codes,
                    "reason": _blocked_reason(codes, card),
                    "quantities_zeroed": False,
                }
            )

    blocked_lookup = {}  # type: Dict[str, List[str]]
    for item in blocked_elements:
        blocked_lookup[item["element_id"]] = list(item["codes"]) or [_BLOCKED_DESIGN_MARK]

    if compact:
        shown_cards, cards_elided = _compact_cards(cards)
    else:
        shown_cards, cards_elided = _elide_cards(
            cards, opts.count("card_cap", CARD_CAP), opts.count("cards_per_class", CARDS_PER_CLASS)
        )

    takeoff_block = _unwrap(takeoff, "takeoff")
    bbs_block = _unwrap(bbs, "bbs")
    boq_block = _unwrap(boq, "boq")

    row_cap = 0 if compact else opts.count("row_cap", ROW_CAP)
    bbs_out = {}  # type: Dict[str, Any]
    bbs_corrected = bbs_block
    if bbs_block:
        bbs_corrected, zeroed_ids = _zero_blocked_bbs(bbs_block, blocked_lookup)
        bbs_out = _cap_rows(bbs_corrected, "items", row_cap)
        if compact:
            bbs_out["items_ref"] = "structural_model.quantities.bbs"
        for item in blocked_elements:
            if item["element_id"] in zeroed_ids:
                item["quantities_zeroed"] = True
    # the BOQ is never elided: it is what a reader prices the building from
    boq_out = _cap_rows(boq_block, "items", opts.count("row_cap", ROW_CAP)) if boq_block else {}

    storeys, height_m = _storey_block(model)
    layout_metrics = _layout_metrics(layout_score, placement)
    refusal_reasons = _refusal_reasons(system_errors, opts.get("refusals"))

    counts = log.counts()
    codes_present = set(log.codes())
    review_required = bool(codes_present & set(REVIEW_TRIGGER_CODES))

    if refusal_reasons:
        status = STATUS_REFUSED
    elif counts.get(Severity.WARNING.value, 0) or counts.get(Severity.ERROR.value, 0):
        status = STATUS_OK_WITH_WARNINGS
    else:
        status = STATUS_OK

    system = _system_word(model, placement)

    summary = {
        "status": status,
        "system": system,
        "storeys": storeys,
        "height_m": height_m,
        "seismic": _seismic_block(model, analysis),
        "totals": _totals_block(takeoff_block, bbs_corrected, boq_block),
        "element_counts": _element_counts(model),
        "layout_score": {
            "score": layout_metrics.get("score"),
            "score_version": layout_metrics.get("score_version", UNVERSIONED_SCORE),
        },
        "engineer_review_required": review_required,
        "disclosure_counts": counts,
        "blocked_element_count": len(blocked_elements),
        "refusal_reasons": refusal_reasons,
    }

    trace_entries = opts.get("trace_entries")
    trace_available = _trace_entry_count(design_rows, trace_entries) > 0

    ladder = [entry.to_dict() for entry in entries]
    ladder_out = ladder
    if compact:
        # The whole ladder rides in full on the entry's `errors` + `warnings`,
        # on every response path. Repeating it here is duplication; the ERROR
        # entries stay because they are what blocks an element, and the pointer
        # says where the rest is.
        ladder_out = [row for row in ladder if str(row.get("severity", "")) == Severity.ERROR.value]

    report = _ProtectedReport()
    payload = {
        "meta": {
            "report_version": REPORT_VERSION,
            "schema_version": STRUCTURAL_SCHEMA_VERSION,
            "generated_at": opts.get("generated_at"),
        },
        "summary": summary,
        "element_cards": [card.to_dict() for card in shown_cards],
        "element_cards_total": len(cards),
        "cards_elided": cards_elided,
        "disclosures": ladder_out,
        "warnings_summary": {"counts": counts, "codes": log.codes()},
        "layout_metrics": layout_metrics,
        "blocked_elements": blocked_elements,
        "boq": boq_out,
        "bbs": bbs_out,
        "detail": {
            "level": DETAIL_COMPACT if compact else DETAIL_FULL,
            "levels": list(DETAIL_LEVELS),
            "request_flag": "output.detail",
            "element_cards_ref": "structural_model.design",
            "cards_kept": "none, see element_cards_ref" if compact else "the worst of every class",
            "blocked_elements_ref": "blocked_elements (every blocked and failed element)",
            "disclosures_total": len(ladder),
            "disclosures_elided": bool(compact and len(ladder_out) != len(ladder)),
            "disclosures_ref": "warnings (entry level: the whole ladder, in full)",
            "bbs_items_elided": bool(compact),
        },
        "disclaimer": DISCLAIMER,
        "trace_available": trace_available,
    }
    for key in REPORT_KEYS:
        dict.__setitem__(report, key, payload[key])
    if opts.flag("include_trace"):
        rendered = []  # type: List[Dict[str, Any]]
        for row in design_rows:
            rendered.extend(render_trace(row.get("trace")))
        rendered.extend(render_trace(trace_entries))
        dict.__setitem__(report, "trace", rendered)
    return report


def _blocked_reason(codes: Sequence[str], card: ElementCard) -> str:
    if codes:
        return "blocked by " + ", ".join(codes)
    check = card.governing.get("check") if card.governing else ""
    if check:
        return "design failed on " + str(check)
    return "design failed"


def _system_word(model: Any, placement: Any) -> str:
    """The DELIVERED system: the placement block first, the model only after.

    See the module docstring. The placement block carries what was actually
    placed; `model.system` starts life as what was REQUESTED and is only as
    good as the write-back that follows the placer.
    """
    block = _as_dict(placement)
    for key in ("system", "system_used"):
        candidate = block.get(key)
        if isinstance(candidate, str) and candidate:
            return candidate
    system = getattr(model, "system", None)
    value = getattr(system, "value", system)
    if isinstance(value, str) and value:
        return value
    return ""


def _storey_index(model: Any) -> Dict[str, int]:
    """element id -> storey, built once so card assembly stays linear.

    Elements that carry no storey (footings, cores) are simply absent, and a
    card for one of those reports `storey: None`.
    """
    index = {}  # type: Dict[str, int]
    elements = getattr(model, "elements", None)
    if not callable(elements):
        return index
    try:
        items = elements()
    except Exception:
        return index
    for element in items or []:
        element_id = getattr(element, "id", None)
        storey = getattr(element, "storey", None)
        if not isinstance(element_id, str) or storey is None or isinstance(storey, bool):
            continue
        if isinstance(storey, (int, float)):
            index[element_id] = int(storey)
    return index
