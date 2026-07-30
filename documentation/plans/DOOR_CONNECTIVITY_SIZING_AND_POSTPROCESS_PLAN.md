# Room sizing and post-processing for door_connectivity: implementation plan

Status: PLAN, not implemented. Written 2026-07-30 against engine commit `b0630188`
(`nitantupasani/gplan_engine` main), designer commit `077cd42`, backend `7596a6a`.

Scope: the **`door_connectivity` + `minDimEnabled` path only**. The multi-PTPG
(alternative arrangements) endpoint is deliberately untouched by this plan. See
[Section 12](#12-out-of-scope) for what that means in practice and which pieces
become reusable there later.

---

## 0. How to read this document

You are implementing a change to a pipeline where **every stated constraint is
best-effort and several are inert**. Before you write code, read Sections 2 and
3 completely. They contain measured facts that contradict what the code's own
docstrings, the frontend comments and the older engine docs say. Six independent
reviewers were each asked to REFUTE one premise of this plan, and all six came
back "partly true": every premise needed correcting. Those corrections are folded
in below and marked **[verified]**.

Rules for working on this:

1. **Cite symbols, not line numbers.** Every line number here was accurate at the
   commits above and will drift. Find the symbol with grep before trusting a
   number. The dossiers under `documentation/algorithms/` are anchored to commit
   `a2c0baaf` and are already off by +12 or +13 lines in `handlers.py`.
2. **Never edit `gplan_backend/GPLAN/`.** It is a submodule checkout of this same
   engine. Changes go in the top-level `GPLAN` tree, which pushes to
   `nitantupasani/gplan_engine`; the backend then moves its pin.
3. **Everything in `handlers.py` exists twice.** `handle_door_connectivity` has a
   PTPG branch and an irregular/non-PTPG branch, structurally identical, about
   450 lines apart, each with its own copy of `get_max_dims`, `max_dims_released`,
   the three `solve_min_dim` call sites and the warning. A one-sided fix silently
   applies to half the requests.
4. **Verify by running, not by reading.** Almost nothing here is covered by
   tests: `test_max_dimensions.py`'s `check()` records failures and never raises,
   so under pytest the suite is vacuous. No test in the repository asserts plot
   fit, the gapless property, the repair band, or that the maximum-dimension
   ladder fires at all. Section 10 lists what to run and what to add.
5. **The engine is nondeterministic on purpose** (random shortcut selection,
   placement sampling). Diff structurally on plan counts, adjacency satisfaction
   and rule violations, never on exact coordinates. The backend's Redis cache in
   **db 1** makes repeats look deterministic for 24 hours.

---

## 1. The deliverable in one page

Four changes, in this order. Each is independently shippable and independently
verifiable.

| # | Change | Where | Why |
|---|---|---|---|
| A | **Aspect guard in post-processing** | engine `postprocessing/postprocess.py` | The trim phase can make a room more slender than it found it, and does. Two missing floor terms plus a per-room monotonicity check. Smallest change, largest immediate quality win. |
| B | **Area-budget allocator** | engine, new `source/dimensioning/allocator.py` + `POST /api/allocate` | Room size today is whatever the tiling leaves over. Decide it up front from NBC minimums, the plot area, and a priority order, so the minimal-area solution already fills the plot and nothing has to be redistributed. |
| C | **Centre-in-plot** | client `floorplanFromGraphVariant` + a new `builtBounds` field | When the plot exceeds what the program may legally occupy, stop stretching the plan to fill it. Build at maximum sizes, centre, leave the ring as open space. |
| D | **Constraints and feasibility UI** | designer `UnitEditor`, `nbcRules.ts`, `gplanApi.ts` | The graph view shows numbers that are not the numbers sent and not the numbers delivered. Show the real envelope, validate against it, and refuse to imply a size the engine will not produce. |

What does **not** change: the adjacency graph semantics, the door_connectivity
solver itself, the multi-PTPG endpoint, the cardinal-pin ladder, and the shape of
the generate request other than the additive fields in Section 8.

---

## 2. Ground truth: how a room gets its size today

Four stacked layers decide room size on the shipped path. Every one of them is
best-effort, and the layer most people assume is doing the work is doing none of
it.

### 2.1 The pipeline, in order

`POST /api/generate/door_connectivity` (`gplan_apis/urls.py`, `views.py`
`GenerateFloorplanView.post`) sorts nodes, splits black edges into adjacencies
and red into non-adjacencies, builds `dim_inputs`, then dispatches
`generate_floorplan_task` (202 + Celery + Redis dedupe). The task calls
`Documents.get_floorplans` in `GPLAN/api.py`, which for `caller ==
"door_connectivity"` splits into a `count == 1` branch and a `count > 1` branch.
**Everything below applies to `count > 1` only**; see the trap in Section 11.

1. **`graph.door_connectivity()`** (`source/inputgraph.py`) biconnects,
   triangulates, resolves separating triangles. Room rectangles first exist here,
   as an integer grid read off the T1/T2 matrices in `rdg.construct_dual`.
2. **`minimum_dimensioning.main`** via `handlers.solve_min_dim`. Not a linear
   program: two per-axis longest-path solves over difference-constraint graphs.
   Each room owns two walls per axis; a minimum is a positive forward edge, a
   maximum is a negative reverse edge. **It minimises area.** The minimums you
   send are what actually size the rooms.
3. **`api.rectangularize_output`**: drop non-rectangular or overlapping plans,
   close notches with `_fill_gaps` (first with ceilings, then without if a hole
   remains), require `_is_gapless`, then re-solve the shared coordinate lines with
   `repair_dimensions`.
4. **Optional NBC post-processing** (`postprocess_ui_output`), which is where
   ceilings and aspect are enforced for real, by giving up gaplessness.

### 2.2 Finding 1: the NBC ceilings you send are inert. 23 of 24 axes. [verified]

`minimum_dimensioning.upper_bound(supplied, low)` returns

```
min(DEFAULT_UB_FACTOR * low, max(supplied, SOLVER_UB_SLACK * low))
  = min(5 * low, max(supplied, 2.5 * low))
```

`DEFAULT_UB_FACTOR = 5` is hardcoded; `SOLVER_UB_SLACK` defaults to 2.5 and is
process-wide (`GPLAN_SOLVER_UB_SLACK`). `low` is that room's minimum **on the
same axis**. Therefore:

> A supplied ceiling binds exactly **iff** `2.5 * min <= supplied <= 5 * min`,
> that is iff `min` lies in `[supplied/5, supplied/2.5]`.
> Below that window the ceiling is replaced by `2.5 * min`; above it, by `5 * min`.

Evaluated against the shipped rulebook (`postprocessing/nbc_rules.py`), with
`min`/`max` as the NBC values:

| Room | minW | maxW | 2.5xminW | W binds | minH | maxH | 2.5xminH | H binds |
|---|---|---|---|---|---|---|---|---|
| Living Room | 10 | 22 | 25.00 | no | 11.5 | 24 | 28.75 | no |
| Dining | 9 | 16 | 22.50 | no | 10 | 16 | 25.00 | no |
| Kitchen | 7 | 12 | 17.50 | no | 8 | 13 | 20.00 | no |
| Master Bedroom | 10 | 16 | 25.00 | no | 11 | 18 | 27.50 | no |
| Bedroom | 10 | 14 | 25.00 | no | 11 | 16 | 27.50 | no |
| Study | 7 | 12 | 17.50 | no | 8 | 13 | 20.00 | no |
| Bathroom | 5 | 8 | 12.50 | no | 7 | 10 | 17.50 | no |
| Toilet | 3.5 | 6 | 8.75 | no | 5 | 8 | 12.50 | no |
| Utility | 4 | 6 | 10.00 | no | 6 | 9 | 15.00 | no |
| Store | 4 | 6 | 10.00 | no | 5 | 8 | 12.50 | no |
| Pooja | 3 | 5 | 7.50 | no | 4 | 6 | 10.00 | no |
| Balcony | 4 | 7 | 10.00 | no | 5 | **14** | 12.50 | **YES** |

**One axis out of twenty four.** The Balcony's height ceiling is the only NBC
maximum the solver can honour as given. A Bathroom sent `min_width 5, max_width 7`
is solved with an effective ceiling of 12.5 ft, a 79 percent overshoot that is
considered legal and never reported.

Worse, raising the minimum does not help: the effective ceiling is `2.5 * min`,
so a larger minimum raises the ceiling with it. **You cannot make the solver
enforce a cap by sending one.** Two consequences for the design:

- The allocator must work through the **minimums**, because the solver minimises
  and lands on them when feasible.
- Cap enforcement must be **post-solve** (`_fill_gaps` limit, `repair_dimensions`,
  post-processing), and that is where this plan puts it.

Do not "fix" this by setting `GPLAN_SOLVER_UB_SLACK=1.0`. It is process-wide, not
per request, and the in-source comment at `minimum_dimensioning.py:149-154`
records why the slack exists: in a gapless tiling a column of small rooms must
stack to the same total as a column of large ones, so hard ceilings make almost
every topology infeasible and collapse the catalogue.

### 2.3 Finding 2: the engine has no concept of area, and its area proxy is 1.04x to 1.42x too loose [verified]

`minimum_dimensioning.py` contains no area constraint and no aspect constraint.
The words appear only in comments. `input_constraints` reads exactly four numbers
per room: `min_height`, `max_height`, `min_width`, `max_width`. Area and aspect
do exist in `solve_linear.py`, but that solver is reached only from the
`dimensioned` paths and the min-dim pipeline never calls it.

Downstream, the only area cap in existence is the **product of the two per-axis
maxima**: `"maxarea": (hw * hh)` in `api._room_bounds`, `(max(w, h), w * h)` in
`api._room_size_caps`. That product exceeds the NBC `max_area` for every single
room type:

| Room | NBC max_area | maxW x maxH | product is |
|---|---|---|---|
| Living Room | 420 | 528 | 1.26x the cap |
| Dining | 210 | 256 | 1.22x |
| Kitchen | 110 | 156 | 1.42x |
| Master Bedroom | 260 | 288 | 1.11x |
| Bedroom | 190 | 224 | 1.18x |
| Study | 120 | 156 | 1.30x |
| Bathroom | 68 | 80 | 1.18x |
| Toilet | 34 | 48 | 1.41x |
| Utility | 52 | 54 | 1.04x |
| Store | 44 | 48 | 1.09x |
| Pooja | 28 | 30 | 1.07x |
| Balcony | 84 | 98 | 1.17x |

So even a perfectly binding per-axis maximum cannot enforce an NBC area cap.
**An explicit `max_area` has to travel as its own field.** Today the only code
that ever sees NBC `max_area` is `postprocess.build_bounds`.

### 2.4 Finding 3: the aspect band is dead on this path [verified]

`api.py` builds `DimParameters` for the `minDimEnabled` branch **without**
`min_ratio`/`max_ratio` (contrast the branch immediately below it, which passes
them). So `get_max_aspect_ratio()` returns `[]`, `_room_bounds` sets
`aspect = _INF` for every room, and the aspect clauses in `_axis_targets` never
fire. The client faithfully computes and sends `ratio: {min, max}` per node and
it is discarded before it reaches anything that could use it.

`_room_bounds`' own docstring says otherwise. It is wrong. The `ar_lo`/`ar_hi`
keys that `_axis_targets` supports are populated by exactly one caller in the
whole tree: the NBC post-processor.

**Plumbing the ratio through is a prerequisite for change A and change B.**

### 2.5 Finding 4: gaplessness pins the total, so the surplus must land somewhere [verified, with two corrections]

`_fill_gaps` derives the bounding box from the min-dim rects it is handed and
only pushes walls outward toward that box; `rectangularize_output` keeps a plan
only if `_is_gapless` holds. So for a surviving plan the room areas sum to the
bbox area within 0.1 percent, and the surplus over the rooms' minimum areas must
land in some room. The visit order (descending `_headroom`) decides only WHICH
room absorbs it. The code says so itself, and runs a deliberately uncapped second
pass because "A gapless rectangle is required; honouring every ceiling is only
preferred".

Two corrections an implementer must not skip:

1. **The pigeonhole argument needs every room to be capped.** A room with a
   missing, non-positive or `>= 99999` maximum has infinite headroom, absorbs
   first, and is skipped by `_exceeds_caps`. If no room has a usable maximum,
   `_room_size_caps` returns `None` and the capped pass never runs at all. That
   is exactly what the backend produces when the client omits `maxDimEnabled`.
2. **Area is sufficient but not necessary.** Because every row of the dissection
   must sum to the same width and every column to the same height, a room can be
   forced over its ceiling even when the ceilings sum to MORE than the bbox area.
   This is the same stacking argument that justifies `SOLVER_UB_SLACK`. An area
   budget alone therefore cannot guarantee compliance, which is why change A
   (post-processing) remains the enforcement layer and is not optional.

Also worth knowing before you build on it: `caps_broken` is latched from
`_exceeds_caps` **before** `repair_dimensions` runs and is never re-evaluated, so
the warning "Room maximum dimensions were exceeded while closing gaps" can fire
for a plan that repair subsequently brought back inside its ceilings.

### 2.6 Finding 5: the plot is never a target, and nothing centres anything [verified]

In the min-dim path `plot_width`/`plot_height` are installed as a single negative
sink-to-source edge per axis, guarded by `if plot_width > 0`, and `longest_path`
rejects the topology when the solved extent exceeds it. Everything else in that
path minimises or is plot-blind. **Zero code puts a lower bound on total extent.**

The expand fallback is narrower than folklore has it: it fires on
`if not floorplan_found:`, that is only when **not one topology in the whole
enumeration** satisfied the cap. While at least one plan fits, plans that exceed
the cap are silently dropped (`i = i-1; graph.graph_list.pop()`) and nothing is
scaled. When it does fire, `scale_plot_dimension` applies independent per-axis
factors clamped to `>= 1`, so any axis below the requested plot is stretched up
to exactly the plot dimension, with no reference to any room maximum.

There is no centre, translate or offset logic anywhere in `api.py`,
`handlers.py`, `source/inputgraph.py` or `source/postprocessing`. Plans are
emitted at or near the origin. **Centring is new code.** One caveat for change C:
the client already scales plans up toward the plot (`floorplanFromGraphVariant`
applies `scale = Math.max(1, Math.min(fitW, fitH))` uniformly), so a rendered
plan already touches the unit on its tighter axis and the slack sits at the right
and bottom. Centring relocates that residual, it does not introduce filling where
none exists.

### 2.7 Finding 6: post-processing is already available inside generation [verified]

This one reverses a working assumption. Post-processing is opt-in **in this
client**, not in the API:

- `GenerateFloorplanView` already reads `postProcessEnabled` (default `False`)
  and `postprocess_options` off the request and forwards both into the task
  payload.
- The engine already applies them:
  `if postProcessEnabled and minDimEnabled and caller == "door_connectivity":`
  calling `postprocess_ui_output`, after `rectangularize_output`.
- `postprocess_api.md` calls this "API surface 1: inline flag on the dimensioned
  catalogue".
- The string `postProcessEnabled` appears nowhere in the designer's `src/`
  outside a comment.

**Turning enforcement on for a whole batch needs no new endpoint and no backend
work.** It needs the flag plus the client-side relaxations in Section 6.4.

The blocker that kept it per-plan is real but smaller than recorded:
`isRectangularArrangement` requires non-overlap AND that room areas sum to the
bounding box, so a notched plan fails it. But the filter is a **preference with a
fallback**, not an unconditional drop: `pool = rectVariants.length > 0 ?
rectVariants : parsed`. The loss bites only on a MIXED batch, which is exactly
what an inline-flagged batch produces, because plans already inside their caps
come back unchanged and stay perfect rectangles. It has exactly **one call site**.

---

## 3. The four defects, with evidence

### 3.1 Post-processing can make a room worse and keep it

**The mechanism.** `_axis_ceilings` applies only the UPPER side of each room's
aspect band per axis:

```python
tw = min(cap_w, maxarea / h, bounds["ar_hi"] * h)
th = min(cap_h, maxarea / w, w / bounds["ar_lo"])
tw = max(tw, floor_w, minarea / h)     # <- no aspect term
th = max(th, floor_h, minarea / w)     # <- no aspect term
```

The two floors contain no aspect term, so nothing stops `th` being trimmed below
`w / ar_hi`. The missing terms are not hypothetical: `api._axis_targets` applies
the same band two-sidedly (`lo = max(lo, ar_lo * other_side)` and
`lo = max(lo, other_side / ar_hi)`). Phase 1 therefore cannot degrade aspect and
phase 2 can.

`_trim_pass` shrinks whichever axis has a fully exterior side available. Aspect
is `long / short`, and trimming the SHORT axis raises it monotonically.

**Measured on a live batch** (7-room program, 12 plans, `postProcessEnabled`):

- Plan 5, Bathroom **12.0 x 7.0** (84 sqft, aspect 1.714, comfortably inside its
  2.0 band; its only violation was `max_area 68`). E and W were not fully
  exterior, so the trim took 1.3 ft off the SHORT axis from S, ending
  **12.0 x 5.667** (68 sqft, aspect **2.118**). `issues_before` had no aspect
  entry for that room. `issues_after` does. **The trim created an NBC violation
  that did not exist.**
- Same plan, Toilet, identical 12.0 x 7.0 with the identical over-area
  violation, but its W side WAS fully exterior, so it was trimmed on its LONG
  axis to 4.857 x 7.0 and its aspect **improved** to 1.441.

Identical shape, identical defect, opposite outcome, decided purely by which side
happened to be fully exterior.

**Why the guard did not catch it.** The only acceptance test is plan-wide:
`if score_after > score_before:` revert everything, where score is
`10 * errors + 1 * warnings` from `nbc_rules.plan_issues`. The plan above
improved 23 to 2, so the regression shipped. The guard cannot fire when a trim
swaps one warning for another, when severity is unchanged, or when one room's
degradation is masked by another room's improvement. And `plan_issues` never
checks `max_width`/`max_height` at all, so a trim performed purely to satisfy a
span cap earns zero credit and can only be neutral or reverted.

Worked example of the guard being vacuous, from the module's own numbers: a
5 x 13 Toilet scores aspect 2.60 > 2.42 (error, 10) plus 65 sqft over the 34 cap
(warning, 1), total 11. After a width trim to 3.5 x 13 it scores aspect 3.71
(still an error, 10) plus 45.5 sqft (still a warning, 1), total 11. `11 > 11` is
false, so a **3.71:1 toilet ships**.

**Correction to the brief.** The premise that "only toilets and bathrooms are
trimmed" is **not what the code does**. There is no room-class filter anywhere in
the trim path: `build_bounds` returns bounds for every room and `_trim_pass`
iterates every index. Measured trim actions on the 12-plan batch: Toilet 8,
Bathroom 4, **Kitchen 3, Dining 2**, that is 29 percent on rooms the rulebook
calls habitable. On the 5-room regression fixture: Kitchen 4, Bathroom 4,
Balcony 2, **Living Room 1**, that is 45 percent habitable. Habitable rooms are
trimmed routinely. The impression that they are not almost certainly comes from
the regression test itself, whose only cap assertion skips every room whose
`room_class` is not `wet` or `open`.

Wet rooms do dominate, for four derivable reasons: their ceilings are 6x to 12x
smaller so they violate first; `_violation_ratio` divides overshoot by the room's
OWN ceiling, so 6 ft of excess is ratio 1.2 for a toilet and 0.25 for a living
room; `_fully_exterior` tests a strip as wide as the room's own perpendicular
span, so small rooms qualify more often; and `_absorb_pass` hands the reclaimed
void back to the largest-headroom rooms first.

**One more fact that changes the fix.** In that same batch, 19 rooms ended with a
worse aspect than they started, and **16 of the 19 were degraded by phase 1
(repair), not by trim**. All 16 stayed inside their band, so they are currently
harmless, but a guard added only to `_axis_ceilings` fixes the band crossings and
leaves the more frequent drift untouched. Guard all three phases.

### 3.2 Room size is a residue, not a decision

Nothing anywhere computes what a room SHOULD be. The chain is: client sends a
band whose minimum is `max(explicit, proportional) * scale`; the solver minimises
to that minimum; the gapless fill then pushes whatever the bbox leaves over into
whichever room can reach a notch, ordered by headroom. The documented outcome is
a 5 x 7 balcony becoming 5 x 24, and 54 sqft bathrooms.

There is no area-budget or target-area allocator in the engine tree. (An
`area_adjustment.py` with `adjust_areas(..., target_areas, ...)` exists only on
an unmerged private branch.)

### 3.3 The plot is a cap the plan cannot use

Because the plot only ever rejects, a program that legally occupies less than its
plot has no way to say so. The plan is generated as small as the minimums allow,
then the CLIENT stretches it up to touch the unit. There is no notion of "this
program should occupy 780 of these 1008 sqft and sit in the middle".

### 3.4 The graph view shows numbers that are not real

Exhaustively, every place the displayed number differs from the delivered one:

1. **Displayed** is `space.width ?? space.widthMin`. In the unit studio
   `makeSpace` spreads all of `spaceDimsFor(name)`, which includes `width`/
   `height`, so a new room shows the palette default. Note `buildProgramSpaces`
   in `nbcRules.ts` explicitly destructures those out with a comment saying
   palette dims collapse the catalogue: **the two creation paths disagree**, and
   the studio ships the failure mode the rulebook warns against.
2. **Sent on door_connectivity** is a band, not a number:
   `min = round(max(widthMin, max(width ?? 0, proportionalTarget) * minScale))`
   and `max = max(min + 2, round(widthMax))`. A 2BHK Living Room shown as
   14 x 13 is requested as width in [13, 22] and height in [12, 24].
3. **Sent on multi-PTPG** is the same displayed number, verbatim and exact. The
   Engines picker is multi-select, so one label can mean two different things in
   one batch.
4. **The ceiling can be silently destroyed**: `band()` returns
   `max = Math.max(min + MIN_SLACK, dim(hi))`, so a minimum that reaches the
   ceiling replaces the ceiling with `min + 2`.
5. **The solver widens it anyway**, per Section 2.2.
6. **The gap fill redistributes** leftover area into whoever can reach a notch.
7. **The client scales the result up** uniformly to touch the unit.
8. **`fitUnitPlansToFootprint` rescales anisotropically** on building-level
   resize and grid re-sync, with independent `sx`/`sy` and no clamp at 1, which
   is precisely what the generation path's own comment forbids. A 2:1 bedroom can
   become 2.8:1 with no note.

And the validation that exists is thin: the Inspector's only rule warning is
below-minimum, structurally incapable of firing for a room with no explicit dims
(the guard is `(width ?? widthMin) < widthMin`). No maximum is displayed, warned
about or enforced anywhere in any component. `programMinAreaSqFt` exists in
`nbcRules.ts` with **zero call sites**; `UNIT_SIZE_LIMITS.minAreaSqFt`/
`maxAreaSqFt` have zero readers; `planIssues` produces user-grade sentences that
no component ever renders. The one hard fit guard that would throw is in
`buildSpaceRequestFromUnit`, which is unreachable (`USE_SPACE_OPTIMIZED = false`).

There is one real feasibility signal today: an amber "rooms exceed unit" chip in
the top bar, computed from the DISPLAYED numbers, blocking nothing.

---

## 4. Change B: the area-budget allocator

### 4.1 What it is

A pure function, no solver, no I/O. Given a room list, a plot, and the rulebook,
it returns the size envelope every room should occupy, such that the room
rectangles sum to the plot area. It is the missing decision from Section 3.2.

It lives in the engine because the engine is the authority and because both
generators and every client should see the same answer. It is also exposed as a
synchronous endpoint so the graph view can show exactly what generation will use,
with no second implementation to drift.

```
GPLAN/source/dimensioning/allocator.py     <- new, pure, unit-testable
GPLAN/api.py    Documents.allocate_program <- thin wrapper, request in, dict out
POST /api/allocate                          <- new synchronous endpoint
```

### 4.2 Clear floor versus rectangle, and why it matters

**Decision: NBC minimums are clear-floor figures and the allocator sizes to clear
floor, adding walls on top.**

Walls are drawn centred on the room-rectangle edges (interior 0.4 ft, exterior
0.75 ft in the dresser), so a rectangle loses half of every wall it touches:
0.2 ft per interior side, 0.375 ft per exterior side. A 10 x 11.5 rectangle
therefore delivers about 9.6 x 11.1 = 107 sqft of clear floor against a 115 sqft
NBC Living Room minimum, a 7 percent shortfall that every current rule check
misses because `planIssues` and `nbc_rules.plan_issues` both measure the
rectangle.

Define one allowance constant per axis:

```python
WALL_ALLOWANCE_FT = 0.4     # two interior half-walls, 0.2 + 0.2
```

Rectangle bounds are derived from clear bounds, never the other way round:

```python
def rect_bounds(rule, a=WALL_ALLOWANCE_FT):
    """Clear NBC bounds -> rectangle bounds, walls added on top."""
    cw, ch = rule["min_width"], rule["min_height"]
    if cw * ch < rule["min_area"]:        # the area floor beats the shape floor
        ch = rule["min_area"] / cw
    lo_area = (cw + a) * (ch + a)
    Cw, Ch = rule["max_width"], rule["max_height"]
    if Cw * Ch > rule["max_area"]:        # the area cap beats the shape cap
        Ch = rule["max_area"] / Cw
    hi_area = (Cw + a) * (Ch + a)
    return (cw + a, ch + a, lo_area), (Cw + a, Ch + a, hi_area)
```

Because the rectangles tile the plot exactly under the centreline convention,
`sum(rect areas) == plot area` holds by construction and the difference between
that and `sum(clear areas)` is precisely the wall footprint. The budget must be
computed in rectangle space for this reason.

**Known residual, flagged deliberately:** rooms on the outer boundary lose
0.375 ft rather than 0.2 ft on their exterior sides, which the flat 0.4 ft
allowance under-counts by up to 0.175 ft per axis. Which rooms are exterior is
not known before layout. Ship the flat allowance, expose `wall_allowance_ft` as a
request option, and measure the residual (Section 13, open question 1).

### 4.3 The algorithm

```
INPUT   rooms[]            (name, optional per-room min/max overrides)
        plot_w, plot_h     (ft)
        tiers              (default below)
        wall_allowance_ft  (default 0.4)

1  CANONICALISE      nbc_rules.canonical_name -> rule_for; unknown -> ROOM_FALLBACK
2  RECT BOUNDS       rect_bounds(rule) per room, then intersect with any
                     per-room override; a user maximum below the NBC minimum is
                     an error, not a silent clamp
3  FLOOR TOTAL       floor = sum(lo_area)
4  FEASIBILITY       surplus = plot_w * plot_h - floor
                     if surplus < 0: see 4.5, allocate at the floor and report
5  DISTRIBUTE        for tier in 1, 2, 3:
                       members = rooms in this tier with headroom left
                       repeat until surplus exhausted or every member capped:
                         share_i = surplus * lo_area_i / sum(lo_area of members)
                         take_i  = min(share_i, hi_area_i - alloc_i)
                         alloc_i += take_i
                       surplus -= sum(take_i)
6  SHAPE             per room, turn alloc_i into (w, h) inside its rect bounds
                     and aspect band (4.4)
7  EMIT              per room: min_w, min_h, max_w, max_h, min_area, max_area,
                     ar_lo, ar_hi, target_w, target_h  (all in RECTANGLE feet)
                     plus plan level: target_bbox_w, target_bbox_h, remainder
```

Tier defaults, from the product decision:

| Tier | Rooms | Rule |
|---|---|---|
| 1 | Living Room, Master Bedroom, Bedroom(s), Kitchen | share the surplus proportionally to their rectangle minimum, each capped at its own ceiling |
| 2 | Dining, Study | take what tier 1 could not absorb |
| 3 | Bathroom, Toilet, Utility, Store, Pooja, Balcony, unknown types | stay at minimum unless tiers 1 and 2 are entirely capped |

Proportional-to-minimum, not equal shares: a Living Room and a Toilet should not
grow by the same absolute amount, and proportional-to-minimum keeps the
program's own hierarchy (which `AREA_ORDERING` already asserts) intact.

### 4.4 Shaping: turning an area into a rectangle

Area alone does not determine a rectangle, and the tiling will move walls anyway.
What must be exact is the ENVELOPE handed downstream; the target shape is a
starting point.

```python
def shape(area, lo_w, lo_h, hi_w, hi_h, ar_lo, ar_hi, plot_ar):
    target_ar = clamp(plot_ar, ar_lo, ar_hi)   # follow the plot, inside the band
    w = clamp(sqrt(area * target_ar), lo_w, hi_w)
    h = clamp(area / w, lo_h, hi_h)
    w = clamp(area / h, lo_w, hi_w)            # one re-solve after clamping
    return round_to(w, 0.5), round_to(h, 0.5)
```

Two notes. Dimensions do **not** need to be integers: nothing on the API path
coerces them (`min_dim` casts with `float()` and rounds to 4 decimals; the only
`int()` casts are in the Tk desktop GUI). The integer rule that the designer's
`dim()` enforces belongs to the older space-optimization endpoint. Rounding to
0.5 ft is a readability choice, not a constraint. Second, keep every room's span
**at or above 2.0 ft on both axes**: adjacent rooms are forced to overlap by at
least 2 units on the perpendicular axis for black adjacencies, and driving a span
below that kills the whole topology with no message beyond
`Returned false in [longest_path]`.

### 4.5 When the program does not fit

**Decision: generate at minimums, overflow the plot, and label it.** Do not
refuse.

The report must name the shortfall and its drivers, because "generation will
likely fail" is not actionable:

```json
{"fits": false,
 "program_min_area": 610.5, "plot_area": 560,
 "shortfall_sqft": 50.5,
 "smallest_plot": {"width": 28.6, "height": 21.4},
 "drivers": [{"room": "Living Room", "min_area": 123.8},
             {"room": "Master Bedroom", "min_area": 118.6}]}
```

Every plan produced from an infeasible brief carries a note through
`engineNote`, exactly as the existing relaxation notices do. The plan overflows
the plot; that is the honest outcome and it is what the current pipeline already
does silently.

### 4.6 Worked example, reproducible

Default 2BHK program on the shipped 36 x 28 ft unit. These numbers come from a
prototype of the algorithm above and should become the allocator's first unit
test.

```
plot 36 x 28 = 1008 sqft
program rectangle minimum = 610.5 sqft   (clear minimum 558 sqft)
surplus to distribute     = 397.5 sqft

room             rect min  rect max  allocated   clear   at cap
Living Room         123.8     436.6      255.7     243
Dining               97.8     221.8       97.8      90
Kitchen              62.2     118.6      118.6     110    YES
Utility              28.2      58.0       28.2      24
Master Bedroom      118.6     273.1      245.0     232
Bedroom             118.6     201.2      201.2     190    YES
Bathroom             40.0      74.8       40.0      35
Toilet               21.6      38.8       21.6      18
TOTAL               610.5    1422.9     1008.0
unallocated remainder: 0.0 sqft
```

Read this before shipping the defaults. Tier 1 absorbs the entire surplus, so the
**Dining room stays at its NBC floor of 90 sqft while the Living Room reaches
243**. That is a legitimate reading of "living, kitchen, bedrooms on priority"
and it is what was asked for, but it is a strong outcome and worth confirming.
Provide `tier_share` (default `[1.0, 1.0, 1.0]`, meaning each tier may absorb all
of what reaches it) so a product decision can cap tier 1 at, say, 0.75 without a
code change. See Section 13, open question 2.

Note also `TOTAL rect max = 1422.9`. That is the threshold for change C: this
program on any plot above roughly 1423 sqft cannot legally fill it, so a 44 x 34
unit (1496 sqft) must build at 1423 and centre.

### 4.7 How the allocator actually controls room size

This is the part to get right, and it is counter-intuitive given Section 2.2.

- **Minimums are the lever.** The solver minimises area, so it lands on the
  minimums whenever the topology allows. Send `min_width`/`min_height` as the
  ALLOCATED targets, not the NBC floors. When the allocation sums to the plot
  area, the minimal-area solution already fills the plot and the gap fill has
  nothing left to redistribute. That is the mechanism.
- **Maxima are not the lever**, per Section 2.2: whatever you send, the solver
  uses `max(supplied, 2.5 * min)` clamped to `5 * min`. Send the NBC ceilings
  anyway (they cost nothing and matter downstream), and keep `maxDimEnabled`
  true, because without it the backend rewrites every maximum to 99999 and the
  whole downstream cap chain silently disables itself.
- **Enforcement is post-solve**, in three places that all need the new fields:
  `_room_size_caps` (limits how far `_fill_gaps` may grow a room),
  `_room_bounds` plus `repair_dimensions` (can SHRINK a room while keeping the
  tiling gapless and every adjacency intact), and post-processing (can trim with
  notches when nothing else works).
- **Minimums alone cannot cap a room**, per Section 2.5 correction 2: row and
  column stacking can force a room above its ceiling even when the ceilings sum
  to more than the bbox. This is why change A is not optional.

`repair_dimensions` is the natural home for the enforcement half. It already
accepts independent `minarea`/`maxarea` and an asymmetric `ar_lo`/`ar_hi` band,
it moves only shared coordinate lines so rectangularity, gaplessness and every
adjacency survive, and it can shrink the bounding box (gap steps may be negative).
Today `_room_bounds` populates neither the area rule nor the aspect band, and the
NBC post-processor is the only caller that ever sets them.

---

## 5. Change A: fixing post-processing

Do this one first. It is small, self-contained, and immediately measurable.

### 5.1 Prerequisite: plumb the aspect band

In `api.Documents.get_floorplans`, the `minDimEnabled` branch builds
`DimParameters` without `min_ratio`/`max_ratio`. Add them, then teach
`_room_bounds` to emit `ar_lo`/`ar_hi` (it currently emits an `aspect` key that
is always `_INF` on this path). Without this, `_axis_targets`' aspect clauses
never fire and phase 1 of post-processing has no band to respect.

### 5.2 The aspect floors

In `postprocess._axis_ceilings`, add the two terms that `api._axis_targets`
already has and this function lacks:

```python
tw = max(tw, floor_w, bounds["minarea"] / h, h / bounds["ar_hi"])   # <- new term
th = max(th, floor_h, bounds["minarea"] / w, w * bounds["ar_lo"])   # <- new term
```

Effect on the documented failure: a 5 x 13 Toilet with `ar_hi = 2.2` gets
`13 / 2.2 = 5.909 > 5`, so `need_w` becomes 0 and the short-axis trim that
produced the 3.71:1 result is no longer reachable.

### 5.3 The monotonicity guard

**Decision: no phase may increase any room's aspect ratio beyond where it started
or its band, whichever is looser.** Formally, for every room:

```
aspect_after <= max(aspect_before, ar_hi) + eps
```

Apply it in three places, not one:

1. `_trim_pass`, before committing each trim. Reject the trim, try the other side
   or the other axis.
2. `_absorb_pass`, before committing each growth.
3. The phase 1 acceptance test for the `repair_dimensions` candidate. **16 of the
   19 measured aspect regressions came from phase 1**, so a guard on trim alone
   leaves most of the drift in place.

### 5.4 Replace the plan-wide integer gate

The current gate is `if score_after > score_before: revert everything`, with
`score = 10 * errors + 1 * warnings`. Section 3.1 shows it passing a
band-crossing regression because the plan total improved 23 to 2.

Replace it with a two-part test:

- **Per-room, no regression on any dimension of quality.** Build a small per-room
  vector: aspect band violated (bool), below minimum area (bool), below minimum
  width (bool), over area cap (bool), over span cap (bool). No room may go from
  false to true on any component. This is what makes "never worse" mean what it
  says.
- **Plan-wide, the existing score as a tiebreak only**, kept for the cases the
  vector does not capture (`AREA_ORDERING` breaches, which are inherently
  relational).

While you are there, fix two gaps in the objective itself:
`nbc_rules.plan_issues` never checks `max_width`/`max_height`, so a trim done
purely to satisfy a span cap earns zero credit and can only be neutral or
reverted; and the `aspect` option's tightened band is invisible to
`plan_issues`, so post-processing toward a caller-supplied band can only score
neutral-or-worse.

### 5.5 The smaller correctness fixes, all confirmed present

- **Rollback asymmetry.** If trim rolls back but absorb succeeds in the same
  round, `moved` stays true, so the next round re-attempts the identical doomed
  trim and appends a duplicate phase note.
- **`caps_broken` is latched too early** (before `repair_dimensions`), so the
  "ceilings exceeded" warning can describe a plan that ends up compliant.
  Re-evaluate after repair.
- **No interior-hole check after trim.** Phases 1 and 3 both call
  `_void_metrics`; phase 2 relies entirely on the `_fully_exterior` construction
  argument. Add the check.
- **No connectivity check.** Only explicitly protected door pairs are
  re-verified. Every other shared wall may be severed by a trim, and with the
  largest-shared-wall fallback the protected set is one edge per room, which can
  be a disconnected forest. Assert that all rooms remain mutually reachable.
- **Notches are unbounded.** `notch_area`/`notch_ratio` are computed and
  reported but never used as acceptance criteria. Add `max_notch_ratio`
  (suggest 0.12) and roll back past it. An unbounded notch is how a "plan" turns
  into a shape nobody would build.
- **Square rooms are handled asymmetrically**: at `w == h`, `cap_w = cap_long`
  but `cap_h = cap_short`, a built-in landscape preference that will trim height
  on a square room. Decide this deliberately rather than inheriting it.
- **`original_name`.** The standalone JSON adapter reads
  `room.get("original_name") or room.get("name")`, and no engine code ever emits
  `original_name`; only the designer sets it. If a caller posts
  door_connectivity's numeric labels, every room falls to `ROOM_FALLBACK` and
  `plan_issues` skips all of them, so `score_before == score_after == 0` and the
  guard is vacuous. Verify the inline path passes real room names.

---

## 6. Change C: centre the plan when the plot is too big, and enforce caps automatically

### 6.1 The rule

If `sum(rect max area) < plot area`, the program cannot legally fill the plot.
Build at the allocated maxima, centre the result, leave the ring as open space.
**The unit keeps the plot**, so nothing downstream (floor canvas, DXF, IFC,
walkthrough) has to move.

```
plot 44 x 34 = 1496 sqft, 2BHK program max = 1423 sqft
+--------------------------------------+
|            open space                |
|   +------------------------------+   |
|   |    built 42.9 x 33.2 ft      |   |
|   +------------------------------+   |
|                                      |
+--------------------------------------+
offset = ((44 - 42.9)/2, (34 - 33.2)/2)
```

### 6.2 Where it is implemented

Engine geometry stays at the origin; do not add translation to the engine. The
client does the placement, because the client is what already scales plans to the
unit:

- In `floorplanFromGraphVariant`, stop scaling past 1 when the plan already fits:
  the factor becomes `min(1, ...)` guarded, not `max(1, min(fitW, fitH))`.
- Add `builtWidth`, `builtHeight`, `builtOffsetX`, `builtOffsetY` to
  `UnitFloorplan`. Keep `floorWidth`/`floorHeight` as the PLOT so unit footprint
  sync, exports and building views are untouched.

**Trap, and it will bite.** The dresser decides windows and the entrance with
`exteriorFacing` strip tests against the plan bounds. If `floorWidth` becomes the
plot while rooms sit 0.5 ft inside it, every room reads as non-exterior and loses
its windows. `dummyPlan.ts` and anything else doing exterior tests must use the
BUILT bounds, not the plot bounds. Grep for `exteriorFacing` and
`floorWidth`/`floorHeight` together before declaring this done.

### 6.3 Interaction with the plot cap sent to the engine

The client currently sends `plot_width`/`plot_height` at `PLOT_CAP_SLACK = 1.6`
times the footprint, to stop the expand fallback firing. With an allocator the
request should send the **target bbox** with a much smaller slack, because the
allocation is designed to fit. Do not change the slack without re-measuring:
there is an unverified inference on record that 1.6 pushes the request outside
`dim_on_paths_bdy`'s acceptance window (roughly `[total, 1.25 * total]`, relaxed
to about 1.43x), converting a dangerous partial boundary-pool collapse into a
total one that the empty-selection revert catches safely. Lowering it could
re-expose the partial collapse. Section 13, open question 3.

### 6.4 Making cap enforcement automatic

Per Section 2.7 this is a client change plus a filter relaxation:

1. Send `postProcessEnabled: true` and `postprocess_options` on the
   door_connectivity generate request. No backend or endpoint work.
2. Relax `isRectangularArrangement`: keep the non-overlap test, drop the
   "areas sum to the bounding box" test (or gate it on the per-plan report's
   `doors_preserved`). One call site, in `generateFloorplansViaGraph`.
3. Re-dress after trimming. A trimmed plan's `detailedPlan` is stale: doors,
   windows and furniture were derived from the pre-trim geometry. Clear it so the
   dressing effect re-derives. The engine doc's other stated prerequisite,
   flush-bbox window placement, is already fixed and the doc is stale on it.
4. Keep the per-plan "Post-process" button. It becomes a re-run for a plan the
   user has since edited, not the only way to get compliance.

---

## 7. Change D: the constraints and feasibility UI

The goal is narrow and testable: **no number shown in the graph view may be a
number the engine will not deliver.** Either show the envelope, or show the
allocator's answer, but never a bare invented figure.

### 7.1 Prerequisite refactor

`band()` is a closure private to `buildGraphRequestFromUnit`, so no component can
show what will be sent. Extract it as an exported pure function, for example
`requestedBandFor(space, unit): {width: {min, max}, height: {min, max}}`, and
have both the request builder and the UI call it. This is the single most
important step: it makes the displayed number and the sent number the same object
by construction.

### 7.2 The panel

A third section of the existing left `<aside>` in `UnitEditor`, or a block inside
the room branch of the Inspector. It needs no type or store changes: the band
fields already exist on `Space`, `updateSpace` already takes `Partial<Space>`,
and `designSnapshot` already serializes `spaces`.

Per selected room, show four rows:

| Row | Source | Editable |
|---|---|---|
| NBC clear minimum / maximum | `ruleFor(name)` | no |
| Allocated target | `POST /api/allocate` | no |
| Will be sent as | `requestedBandFor` | no |
| Your override | `Space.width/height`, `widthMin/Max`, `heightMin/Max` | yes |

Validation that must fire, none of which exists today: maximum below minimum;
override above the NBC ceiling; override below the NBC floor (exists, but only
for width/height, and it cannot fire for a room with no explicit dims); and the
`band()` collapse where a minimum that reaches the ceiling silently replaces it
with `min + 2`.

### 7.3 Feasibility block

Above the room list, always visible:

```
Program minimum 610 sqft   Plot 1008 sqft   Surplus 398 sqft
Living Room +132   Master Bedroom +126   Bedroom +83 (at cap)   Kitchen +56 (at cap)
```

and, when infeasible, the Section 4.5 report with the smallest workable plot.
`programMinAreaSqFt` already exists in `nbcRules.ts` with zero call sites; this
is its first reader. The existing amber "rooms exceed unit" chip should be
recomputed from the SENT numbers rather than the displayed ones.

### 7.4 Render what the rulebook already knows

`planIssues` produces user-grade sentences for every generated plan and they are
discarded except for one summary folded into `engineNote`. Render them per plan.
Do not write a second validator.

### 7.5 Bugs to fix in the same pass

- `makeSpace` in `UnitEditor` spreads all of `spaceDimsFor`, including
  `width`/`height`, while `buildProgramSpaces` explicitly strips them with a
  comment saying palette dims collapse the catalogue. Align them.
- The band is stamped at creation and never recomputed on rename, while the
  proportional target, the aspect cap and the min-scale are all re-derived from
  the NEW name at request time. Rename a Toilet to a Study and the band and the
  target belong to different room types. Recompute the band on rename.
- `fitUnitPlansToFootprint` in `buildingSlice` scales with independent `sx`/`sy`
  and no clamp at 1, which is exactly what the generation path's own comment
  forbids ("never scale down", "never scale the axes differently").
- `createDefaultFloorplan` builds a placed unit's first plan from hard-coded
  footprint fractions with no rule check: the shipped 2BHK Toilet is
  `0.34w x 0.16h`, which in a 36 x 28 unit is 12.24 x 4.48 = 55 sqft against a
  34 sqft ceiling at 2.7:1 against a 2.2 limit. The first plan a user ever sees
  is rule-breaking. Build it from the allocator instead.
- `PanelMode` already contains `"constraints"` with a setter and no reader.
  Either wire it or do not reuse the name; as it stands it looks like an existing
  system that does not exist.

---

## 8. Wiring: contracts, fields and the new endpoint

### 8.1 Additive fields on the door_connectivity generate request

All additive, all optional, all defaulting to today's behaviour.

| Field | Level | Meaning |
|---|---|---|
| `min_width`, `min_height` | per node | **existing.** Now carries the ALLOCATED target, not the NBC floor. This is what actually sizes the room. |
| `max_width`, `max_height` | per node | **existing.** NBC ceilings. Understand that the solver widens them (Section 2.2); they matter to `_room_size_caps` and `repair_dimensions`. |
| `min_area`, `max_area` | per node | **new.** The real area rule. Without it the only area cap is `max_w * max_h`, which is 1.04x to 1.42x too loose for every room type. |
| `ratio: {min, max}` | per node | **existing on the wire, discarded in the engine.** Plumb it through `DimParameters` and `_room_bounds` as `ar_lo`/`ar_hi`. |
| `maxDimEnabled` | request | **existing, must stay true.** Without it the backend rewrites every maximum to 99999 and the entire downstream cap chain disables itself silently. |
| `postProcessEnabled`, `postprocess_options` | request | **existing, unused by this client.** Turning them on is how enforcement becomes automatic. |
| `target_bbox: {width, height}` | request | **new, optional.** The allocator's intended extent, for the centring path. |

Engine work to accept them: `_room_bounds` must emit `minarea`/`maxarea` from the
new fields instead of `hw * hh`, and `ar_lo`/`ar_hi` from `ratio`;
`_room_size_caps` must use the real area cap; both `handle_door_connectivity`
branches must thread them.

### 8.2 The `POST /api/allocate` endpoint

Synchronous, pure function, no Celery, no cache. `POST /api/postprocess/floorplans`
is the only existing precedent and is the template. Six files, in this order:

1. **`GPLAN/api.py`**: a `@staticmethod` on `Documents` beside
   `postprocess_floorplans`. Pick ONE return shape and keep it: the tuple
   `(response, message)` that postprocess uses, or the
   `{request_id, status, engine, data, error}` envelope that multi-PTPG uses.
   Callers are not interchangeable between the two.
2. **`gplan_backend/gplan_apis/views.py`**: an `APIView` with
   `permission_classes = [AllowAny]`. **This is mandatory, not boilerplate**: the
   project default is `HasAPIKey`, and the designer sends no Authorization
   header, so omitting it returns a permission error rather than a result. Add
   `throttle_classes = [ScopedRateThrottle]` and a new `throttle_scope`.
   Validation is hand-rolled (there is no `serializers.py` in the app at all):
   accumulate into a `problems` list and return one 400 whose
   `error.message` is `"; ".join(problems)` and `error.type` is
   `"ValidationError"`. Anything you want reported as a 400 must be checked in
   the view: a bare `except Exception` around the engine call turns engine-side
   `ValueError`s into 500s.
3. **`gplan_backend/settings.py`**: add the throttle scope to
   `DEFAULT_THROTTLE_RATES`, or `ScopedRateThrottle` has no rate to resolve.
4. **`gplan_apis/urls.py`**: one `path("allocate", ...)` line. The app is
   included under the `api/` prefix and `from .views import *` means no import
   edit.
5. **`GPLAN/local_engine_bridge.py`**: mirror the handler or local dev 404s. The
   bridge is a hand-maintained reimplementation, not a proxy. Route order
   matters: anything under an existing wildcard prefix must be declared above it.
6. **`gplan-building-designer/src/services/gplanApi.ts`**: one exported async
   function using the shared `request<T>()` helper. No `vite.config.ts` change:
   the proxy is path-prefix based on `/api`.

Do not cache it. The cache exists to dedupe minute-scale solves and to give a 202
poller a stable task id; a millisecond-scale pure function needs neither. Do not
copy the older `floorplan:`/`gaopt:` cache-key pattern either, whose two
derivations have drifted so that the task-side writes land on a key nothing reads.

Keep it fast for another reason: gunicorn runs `--timeout 120` with 2 workers and
4 threads, so a synchronous endpoint that can exceed about 120 seconds must
become a Celery endpoint instead.

### 8.3 Deployment consequence

An engine method means a two-repo change: commit and push in
`nitantupasani/gplan_engine`, then in `gplan_backend` do
`cd GPLAN && git pull origin main && cd .. && git add GPLAN && git commit`, push,
and redeploy with a full `docker-compose -f docker-compose.main.yml up -d --build`
because the image runs `pip install -e /GPLAN` at build time. Confirm with
`docker ps` that `gplan_web` and `celery-gplan` were freshly recreated: a
`cd ... && docker-compose ...` chain piped through `tail` reports exit 0 even
when it failed, and that shipped a no-op deploy once. The new engine content
changes `ENGINE_FINGERPRINT`, which invalidates the generation caches as a side
effect.

---

## 9. Work plan, with acceptance criteria

Five phases. Each ships independently and each has a number to hit. Do not
proceed to the next until the current one measures.

### Phase 1: aspect correctness in post-processing (change A)

Work: Sections 5.1 to 5.5.

Acceptance:
- On a 7-room door_connectivity batch of 12 plans with `postProcessEnabled`,
  **zero** rooms cross their aspect band as a result of post-processing.
  Baseline: 1 (plan 5's Bathroom, 1.714 to 2.118).
- **No room's aspect ratio increases** past `max(aspect_before, ar_hi)` in any
  phase. Baseline: 19 rooms ended worse, 16 of them from phase 1.
- The 5 x 13 Toilet case no longer trims its short axis; assert
  `_axis_ceilings(bounds, 5, 13) == (5.909..., 6.8)` rather than `(3.5, 6.8)`.
- Existing behaviour holds: `npm run check:postprocess` still passes, no plan
  gains an overlap, an interior hole or a broken door.

### Phase 2: the allocator, standalone (change B, part 1)

Work: Sections 4.1 to 4.6 plus the endpoint in 8.2.

Acceptance:
- Unit test reproduces the Section 4.6 table exactly, to 0.1 sqft.
- `sum(allocated) == plot_area` within 0.5 sqft whenever the program fits.
- No allocation exceeds any room's rectangle ceiling, on any input.
- The infeasible case returns `fits: false` with a shortfall and a smallest
  workable plot, and never raises.
- Property test over randomised programs and plots: allocation is monotone in
  plot area, never below a floor, never above a ceiling.
- `POST /api/allocate` answers 200 in under 50 ms for a 12-room program.

### Phase 3: allocator into generation (change B, part 2)

Work: Section 8.1 plumbing, both `handlers.py` branches, client sends allocated
minimums.

Acceptance, measured with `npm run measure:2bhk` against a bridge:
- door_connectivity returns plans with **zero hard rulebook errors**. Baseline as
  of 2026-07-30: 30 plans, **0 of them free of a hard error**, both before and
  after the 2BHK graph change. This is the headline number for the whole effort.
- No returned room exceeds its NBC `max_area`, or if one does, the response names
  the room and the plan. Per-room reporting does not exist today: `caps_broken`
  and `max_dims_released` are single batch-level booleans folded into free text.
- Plan count does not collapse: at least 20 of 30 plans survive. Watch this
  closely, since the whole reason `SOLVER_UB_SLACK` exists is that tight
  constraints kill topologies.
- 3BHK and 4BHK measured too, and reported even if worse. They still ship sparse
  graphs (10 rooms / 10 edges, 12 / 13), so the allocator cannot fix them alone.

### Phase 4: centring (change C)

Work: Section 6.1 to 6.3.

Acceptance:
- A 2BHK on 44 x 34 builds at most 1423 sqft and is centred within 0.5 ft on both
  axes.
- Every room that was exterior before centring still gets its windows: the
  dresser reads BUILT bounds, not plot bounds.
- `npm run check:walkthrough` still passes (the walkthrough flood-fills
  walkability and will catch a plate that stopped being sealed).
- Unit footprint, DXF and IFC output are byte-identical in extent to before:
  `floorWidth`/`floorHeight` still carry the plot.

### Phase 5: the UI (change D)

Work: Section 7.

Acceptance:
- For every room in the default programs, the number shown in the graph view
  equals the number in the request, verified by a test that calls
  `requestedBandFor` and the request builder and compares.
- The feasibility block matches `POST /api/allocate` exactly.
- Entering a maximum below a minimum, or an override above the NBC ceiling, is
  refused with a message naming the rule.
- `planIssues` output is rendered per plan.

---

## 10. Verification

### 10.1 What exists

| Command | Where | What it proves |
|---|---|---|
| `npm run measure:2bhk [type] [generator]` | designer | Both generators on a shipped default program through the real client: plan counts, hard rulebook errors, arrangement reach, how much of the brief each plan builds. **The primary metric for phase 3.** |
| `npm run check:postprocess` | designer | The whole client post-process path against a fixture with a corridor toilet; asserts no overlaps, no room grew, footprint held, doors kept, rulebook not worse. |
| `npm run check:generators` | designer | Request shapes and the merge for both engines against a live bridge. |
| `npm run check:walkthrough` | designer | Flood-fills walkability; catches geometry that stopped being sealed. |
| `python test_multi_ptpg.py` | engine | 73 checks on the multi-PTPG pipeline. Untouched by this plan, run it to prove you did not regress it. |
| `python local_engine_bridge.py` | engine | Port 8027, no Django or Redis. How you exercise engine changes end to end. |

### 10.2 What is missing and must be written

- **`test_max_dimensions.py` records failures and never raises**, so under pytest
  it is vacuous. Anything you rely on there must be re-asserted properly.
- There is **no test anywhere** that asserts plot fit on the min-dim path, the
  gapless property, the repair band, or that the maximum-dimension ladder fires.
  The only plot-fit assertion in the repository is on the multi-PTPG endpoint.
- New, required by this plan: allocator unit and property tests (pure, fast, no
  engine); an aspect-monotonicity test over a fixed batch; a per-room cap
  compliance test on the generated batch; a centring geometry test.

### 10.3 How to compare runs

The engine is deliberately nondeterministic. Diff structurally: plan counts,
adjacency satisfaction, per-room rule violations, aspect distribution. Never diff
coordinates. Remember Redis db 1 caches results for 24 hours keyed with the
engine fingerprint, so an engine change invalidates automatically but a pure
client change does not.

---

## 11. Traps

Every one of these was verified in the current tree. They are ordered by how
expensive they are to discover the hard way.

1. **`handlers.py` has two identical min-dim branches** (PTPG and irregular),
   about 450 lines apart. Every change goes in both.
2. **The `count == 1` door_connectivity path skips everything**:
   `rectangularize_output`, `_fill_gaps`, `repair_dimensions` and the cardinal
   filter. A single-plan request gets raw solver geometry. Everything in this
   plan applies to `count > 1`.
3. **`minimum_dimensioning.py` is not reentrant.** All state is module-level
   globals cleared by `reinitialize()`, with no lock. Two concurrent solves in
   one process corrupt each other. Do not parallelise it.
4. **`builtins.print` is monkeypatched to a no-op** for the duration of
   `get_floorplans`, restored only at the normal exits, with no try/finally. Any
   exception in between leaves the worker process with a dead `print` forever.
   This is why debugging the boundary selector needs the bridge console.
5. **Three sentinels for "no plot"**: `0` on the min-dim path, `-1` on the LP
   chain, `-1` on multi-PTPG. Sending `0` to the LP path asserts
   "total extent == 0" and kills every plan.
6. **`input_dims` is blanked only when BOTH plot dims are 0.** Sending one axis
   as 0 still runs `dim_on_paths_bdy`, where the zero axis degenerates the gate
   to `0 <= x <= 0` and rejects nearly everything.
7. **A room span below 2.0 ft kills the topology.** Adjacent rooms must overlap
   by at least 2 units on the perpendicular axis for black adjacencies. The only
   symptom is `Returned false in [longest_path]`.
8. **Dummy rooms from separating-triangle removal carry no maxima at all** and
   get 5x their grid dimension of freedom. `get_max_dims` and `_room_size_caps`
   also treat any index past the caller's list as uncapped.
9. **`_is_gapless` uses a relative tolerance of 1e-3 of the bounding area**, so
   on a 1000 sqft plan a 1 sqft hole counts as gapless. "Gapless" downstream is
   approximate.
10. **Warning strings are the API contract.** Clients detect plot expansion by
    the substring `expanded`, ceiling release by
    `Room maximum dimensions were released`, and cap breach by
    `exceeded while closing gaps`. They are concatenated with no separator, so
    match by substring, never by split. Rewording one breaks clients and loosens
    tests without failing anything loudly.
11. **Never send red (non-adjacency) edges to door_connectivity.** Confirmed
    hang: a 5-node graph with one red edge runs over 5 minutes in the non-adj
    preprocessing. Passing `non_adj_list=[]` is also wrong because the branch
    test is `is not None`; omit the argument.
12. **`apply_cardinal_ring` is skipped when any red edge is present**, and the
    designer sends `non_adj: true`, so pinned requests lose the ring and fall
    back to `nx.planar_layout`, the exact starvation the ring exists to prevent.
13. **Under cardinal pins**, `floorplan_per_bdy_limit` jumps from 20 to 500 and
    `dim_on_paths_bdy` is skipped, which is the known source of multi-minute
    door_connectivity batches.
14. **The stacked one-connected composition returns early** and bypasses
    `rectangularize_output`, `repair_dimensions`, the cardinal ladder and the
    message capture entirely. It fires whenever the graph has exactly one
    articulation point, two biconnected components, `count > 1` and no red edges.
15. **`repair_dimensions` is accepted on non-overlap plus gapless only.** It
    re-solves against the bands but nothing re-checks them, so it can return a
    room below its own minimum.
16. **The algorithm dossiers are anchored to commit `a2c0baaf`.** `handlers.py`
    anchors are +13 lines below :1743 and +12 above it. Apply the offset before
    concluding a documented claim is wrong.
17. **`postprocess_serialized_plans` regenerates every wall `_id` with uuid4**
    when anything changed. A client holding wall ids across a post-process call
    loses them.
18. **nginx on production is not in the repo.** `client_max_body_size` defaults
    to 1 MB for paths without an override, and a location block already needed
    30m for IFC payloads. Check the VM before assuming a large body is accepted.

---

## 12. Out of scope

**Multi-PTPG is not touched by this plan.** It takes exact dimensions and varies
the arrangement; it applies no gapless test, has no post-process option, and
reads `Space.width/height` verbatim. Two consequences for anyone implementing
change D: the same "Width (ft)" label means a minimum-with-a-band on
door_connectivity and an exact integer on multi-PTPG, and the Engines picker is
multi-select, so both can be true in one batch. Any constraints UI must say which
engine a number applies to. What becomes reusable later: the allocator's output
is exactly the "exact dimensions" input multi-PTPG wants, so pointing it at the
allocator is a natural follow-up, but it is a separate piece of work with its own
measurement.

**Also out of scope, deliberately:**

- Lowering `GPLAN_SOLVER_UB_SLACK`. It is process-wide, not per request, and the
  in-source comment records that hard ceilings collapse the catalogue.
- The sparse-graph root cause for 3BHK and 4BHK. Only 2BHK has a
  dissection-derived default (14 edges from the "29.7.26" saved layout); 3BHK is
  10 rooms / 10 edges and 4BHK 12 / 13, and a rectangular dual wants roughly
  twice that. Per-room tuning does not transfer between types: the 2BHK
  master-bedroom widening collapsed 3BHK to zero usable plans.
- The space-optimization and GA engines, which have no dimension concept at all
  and no test coverage.
- The `dimensioned` LP path (`solve_linear.py`, `convert_adj_equ_sym.py`). It is
  a different solver that the shipped path never calls.

**Settled, do not re-litigate.** These were decided by the product owner on
2026-07-30 and the rationale is in this document:

| Decision | Where |
|---|---|
| Allocator lives in the engine, with a preview endpoint | 4.1 |
| Plot too small: generate at minimums, overflow, label it | 4.5 |
| Surplus by tier, proportional to minimum area within a tier | 4.3 |
| Plot too big: build at maxima, centre, ring is open space, unit keeps the plot | 6.1 |
| NBC minimums are clear floor; walls are added on top | 4.2 |
| Caps and aspect are absolute; gaplessness gives way to exterior notches | 5, 6.4 |
| Aspect may never worsen; non-compliant plans rank last, offender named | 5.3 |
| door_connectivity only | this section |

---

## 13. Open questions for the implementer

Raise these; do not guess an answer and bury it in code.

1. **Exterior wall allowance.** The flat 0.4 ft under-counts a room's loss on an
   exterior side by 0.175 ft per axis, and which rooms are exterior is unknown
   before layout. Measure the delivered clear area against NBC on a real batch
   and decide whether to raise the allowance, or to apply a second pass once the
   boundary is known.
2. **Tier share.** The default tiers give the 2BHK a 243 sqft Living Room and a
   90 sqft Dining at its NBC floor (Section 4.6). Confirm that is wanted, or set
   `tier_share` so tier 1 releases some surplus to tier 2.
3. **`PLOT_CAP_SLACK`.** There is an unmeasured inference that 1.6 keeps requests
   outside `dim_on_paths_bdy`'s window and thereby avoids a partial boundary-pool
   collapse. Re-measure the fallback rate and the surviving boundary count before
   changing it.
4. **Cap breach reporting granularity.** Today the response cannot say which room
   in which plan broke a ceiling. Phase 3's acceptance needs per-room reporting;
   decide whether that rides on the existing post-process report structure or
   needs a new response field.
5. **Notch ceiling.** `max_notch_ratio` is proposed at 0.12 with no measurement
   behind it. Measure what fraction of the bounding box real trims actually open
   before fixing the number.

---

## 14. Appendix

### 14.1 Symbol index

Find these by name, not by line. Engine paths are relative to the `GPLAN` repo
root, designer paths to `gplan-building-designer`.

| Symbol | File | Role |
|---|---|---|
| `upper_bound`, `DEFAULT_UB_FACTOR`, `SOLVER_UB_SLACK` | `GPLAN/source/dimensioning/minimum_dimensioning.py` | The single choke point deciding the solver's effective per-axis ceiling. Section 2.2. |
| `input_constraints` | same | The complete list of per-room numbers the solver reads: four, all lengths. |
| `construct_constraintgraphX/Y`, `longest_path`, `pos_longest_path` | same | Constraint edges, minima by construction, maxima by fixup, plot as one negative edge. |
| `compute_rot`, `edit_placements` | same | Post-solve shrink of west and south boundary rooms toward their minima, ignoring maxima. |
| `get_max_dims`, `solve_min_dim` | `GPLAN/handlers.py` | Whether maxima reach the solver, and the per-topology release that strips them. |
| `handle_door_connectivity` | `GPLAN/handlers.py` | Two structurally identical min-dim branches. |
| `scale_plot_dimension` | `GPLAN/source/inputgraph.py` | Expand-only per-axis scale on the no-plan fallback; breaks every ceiling. |
| `_room_bounds`, `_axis_targets`, `_relax_axis`, `repair_dimensions` | `GPLAN/api.py` | The ONLY place area and aspect are real constraints. The natural host for enforcement. |
| `_room_size_caps`, `_fill_gaps`, `_is_gapless`, `rectangularize_output` | `GPLAN/api.py` | Gapless fill, headroom ordering, the uncapped second pass. |
| `build_bounds`, `_axis_ceilings`, `_trim_pass`, `_absorb_pass`, `postprocess_plan` | `GPLAN/source/postprocessing/postprocess.py` | The three phases and the missing aspect floors. |
| `NBC_RULES`, `canonical_name`, `plan_issues`, `HABITABLE_ROOMS` | `GPLAN/source/postprocessing/nbc_rules.py` | The engine's mirror of the designer rulebook. Note `HABITABLE_ROOMS` and `room_class` overlap rather than partition. |
| `GenerateFloorplanView`, `PostProcessFloorplansView`, `ENGINE_FINGERPRINT` | `gplan_backend/gplan_apis/views.py` | Request validation, the 99999 rewrite, the sync endpoint template. |
| `band`, `buildGraphRequestFromUnit`, `PLOT_CAP_SLACK`, `ENFORCE_MAX_DIMS` | `src/services/gplanApi.ts` | What is actually sent. `band` must be extracted for change D. |
| `isRectangularArrangement`, `generateFloorplansViaGraph`, `postProcessFloorplan` | `src/services/gplanApi.ts` | The filter to relax, its one call site, and the per-plan post-process call. |
| `floorplanFromGraphVariant` | `src/services/gplanApi.ts` | Uniform scale-up to the unit; where centring goes. |
| `NBC_RULES`, `spaceDimsFor`, `proportionalRoomTargets`, `buildProgramSpaces`, `planIssues`, `programMinAreaSqFt` | `src/constants/nbcRules.ts` | The designer rulebook. `programMinAreaSqFt` has zero call sites and is the feasibility block's first reader. |
| `makeSpace`, the Inspector block, the amber "rooms exceed unit" chip | `src/features/unitstudio/UnitEditor.tsx` | Where dimensions are shown and edited today. |
| `fitUnitPlansToFootprint`, `syncUnitFootprintToPlan` | `src/store/buildingSlice.ts` | Anisotropic rescale and footprint sync; both can invalidate a delivered size. |
| `exteriorFacing`, `dressRooms` | `src/features/floorplan/dummyPlan.ts` | Window and entrance placement; must read BUILT bounds after centring. |

### 14.2 Formulas worth keeping to hand

```
solver effective ceiling   min(5 * min, max(supplied_max, 2.5 * min))
a supplied max binds iff   min in [supplied_max / 5, supplied_max / 2.5]
engine area cap today      max_width * max_height          (1.04x - 1.42x over NBC max_area)
clear floor from a rect    (w - a) * (h - a),   a = 0.4 ft default
aspect                     max(w, h) / min(w, h)
postprocess score          10 * errors + 1 * warnings, plan-wide, revert iff after > before
gapless tolerance          |sum(room areas) - bbox area| <= bbox area * 1e-3
```

### 14.3 Provenance

The findings in Sections 2 and 3 come from a twelve-agent read of the engine,
backend and designer trees on 2026-07-30: six mapping the solver, the pipeline,
the post-processor, the prior art, the frontend surfaces and the API plumbing,
and six adversarial reviewers each tasked with refuting one premise. All six
premises came back "partly true" and were rewritten. The measured
post-processing numbers (the 12-plan batch, the 12.0 x 7.0 Bathroom, the trim
action counts) come from that review running the real pipeline, not from
inference. The Section 4.6 allocation table comes from a prototype of the
algorithm in Section 4.3 and should be the allocator's first unit test.
