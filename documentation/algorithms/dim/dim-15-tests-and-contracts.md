# dim-15: The dimensioning tests, and the multi-PTPG "exact sizes" contract

All paths absolute. Every line number below was read (or produced by a run I executed today,
2026-07-25). Nothing is inferred from file names.

Files under examination:

- `C:\Users\nitant\Documents\GPLAN_Revamp\GPLAN\test_max_dimensions.py` (236 lines)
- `C:\Users\nitant\Documents\GPLAN_Revamp\GPLAN\test_api_cardinal_constraints.py` (242 lines)
- `C:\Users\nitant\Documents\GPLAN_Revamp\GPLAN\test_multi_ptpg.py` (243 lines)
- `C:\Users\nitant\Documents\GPLAN_Revamp\GPLAN\documentation\multi_ptpg_api.md`
- `C:\Users\nitant\Documents\GPLAN_Revamp\GPLAN\documentation\cardinal_constraints.md`

---

## Purpose

These three scripts are the entire executable specification of GPLAN's dimensioning behaviour
in this repository. What they actually pin is much narrower than what the docs promise:

1. `test_max_dimensions.py` pins **reporting** of per-room ceiling breaches, not enforcement.
   It passes today with 16 rooms over their ceilings in the tight-caps run.
2. `test_api_cardinal_constraints.py` pins **direction** (a room's face is exterior), never a
   number: no width, height, area or plot-fit assertion appears anywhere in it.
3. `test_multi_ptpg.py` is the only file with a genuine exact-size assertion
   (`test_multi_ptpg.py:90`, `:94`) and the only one that checks a plan against a plot
   (`:216-218`).

---

## Where It Sits In The Pipeline

All three call the engine **in-process**. There is no server, no port, no deployed URL:

- `test_max_dimensions.py:31` `sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))`
  then `:33` `from GPLAN.api import Documents`, `:34` `from GPLAN.source.inputgraph import InputGraph`.
  The engine call is `test_max_dimensions.py:117`
  `response, message = Documents.get_floorplans(**build_request(caps))`.
- `test_api_cardinal_constraints.py:17-19` identical path insert plus
  `from GPLAN.api import Documents, normalize_cardinal_constraints, spanning_tree_edges`;
  engine call at `:49-55` and again inline at `:164-170` and `:219-225`.
- `test_multi_ptpg.py:16` path insert, `:18` `from GPLAN.api import Documents`; engine call at
  `:58-59` `Documents.get_multi_ptpg_floorplans({"request_id": request_id, "params": params})`.

A grep for `http|requests|urllib|localhost|8027|port|subprocess` across the three files returns
only the `import os/sys/time/json/math/traceback` lines. **No test hits a remote URL and none
spawns `local_engine_bridge.py`**, so the suite does pin local code behaviour: no deployment is
required. The counterpart claim is worth stating too: because nothing goes over HTTP, these tests
pin *zero* of the Django/Celery/serialization layer in `gplan_backend`, and nothing at all about
`api.scientify.in`.

The engine entry points they land on:

- `Documents.get_floorplans` at `C:\Users\nitant\Documents\GPLAN_Revamp\GPLAN\GPLAN\api.py:1215-1216`
  (the `minDimEnabled` / door-connectivity production path).
- `Documents.get_multi_ptpg_floorplans` at `...\GPLAN\api.py:1774-1802`, which delegates at
  `:1791` and `:1800` to `GPLAN.source.multi_ptpg_pipeline.run`.

---

## Entry Points (file:line)

| Symbol | Location |
|---|---|
| `build_request(caps)` | `GPLAN\test_max_dimensions.py:81-113` |
| `run(caps)` | `GPLAN\test_max_dimensions.py:116-121` |
| `main()` (T1..T5) | `GPLAN\test_max_dimensions.py:149-231` |
| `make_request(cardinal)` | `GPLAN\test_api_cardinal_constraints.py:21-36` |
| `run(cardinal, count, plot_width, plot_height)` | `GPLAN\test_api_cardinal_constraints.py:38-56` |
| `check_side(plans, room_name, side)` | `GPLAN\test_api_cardinal_constraints.py:71-103` |
| `main()` (T1..T8) | `GPLAN\test_api_cardinal_constraints.py:105-237` |
| `call(params, request_id)` | `GPLAN\test_multi_ptpg.py:58-59` |
| `test_five_room_exact` | `GPLAN\test_multi_ptpg.py:62-101` |
| `test_variants_multiply` | `GPLAN\test_multi_ptpg.py:104-130` |
| `test_protected_edges` | `GPLAN\test_multi_ptpg.py:133-151` |
| `test_strictness_ladder` | `GPLAN\test_multi_ptpg.py:154-175` |
| `test_validation_errors` | `GPLAN\test_multi_ptpg.py:178-202` |
| `test_plot_constraint` | `GPLAN\test_multi_ptpg.py:205-218` |
| `Documents.get_floorplans` | `GPLAN\GPLAN\api.py:1215` |
| `Documents.get_multi_ptpg_floorplans` | `GPLAN\GPLAN\api.py:1775` |
| `multi_ptpg_pipeline.run` | `GPLAN\GPLAN\source\multi_ptpg_pipeline.py:376-408` |
| `ptpg_floorplanner.generate_floorplans` | `GPLAN\GPLAN\source\ptpg_floorplanner.py:819-963` |

---

## Data Structures

**Min-dim request** (`test_max_dimensions.py:85-113`): a `nodes_list` of dicts carrying
`width:{min,max}`, `height:{min,max}`, `ratio:{min,max}`, plus a parallel `dim_inputs` dict of
column lists (`min_width`, `max_width`, `min_height`, `max_height`, `min_ratio`, `max_ratio`,
`plot_width`, `plot_height`, `symmetric`, `optimal_floorplan`, `rotation_enabled`) at `:94-103`,
plus an `InputGraph(nodecnt, edgecnt, edgeset, coords)` built at `:105-106`
(constructor signature `GPLAN\GPLAN\source\inputgraph.py:115`).

**Min-dim response** as the tests consume it: `response.to_dict()["Documents"]["floorPlans"]`
(`test_max_dimensions.py:118`), a list of plans, each a list of room dicts with
`name`/`width`/`height` (`:119-120`) or, in the cardinal file, `walls` with `x1,y1,x2,y2`
(`test_api_cardinal_constraints.py:60-63`). The engine returns `(Documents, message)`, a
2-tuple; `message` is the only channel for degradation notices.

**Multi-PTPG request/response** (`test_multi_ptpg.py:34-40`, `:58-59`): nodes carry flat
`width`/`height` ints, edges are `{source,target,color}`; the response is
`{status, engine, error, data{floorplan_count, variant_count, variants[], stats{}}}` and each
plan is `{rooms[{id,width,height,...}], width, height, is_relaxed, adjacency{missing,extra}}`
(shape produced by `GPLAN\GPLAN\source\ptpg_floorplanner.py:114-154`).

---

## Algorithm Walkthrough: every test and exactly what it asserts

Legend: **REAL** = the assertion constrains a number or a geometric fact.
**WEAK** = the assertion is satisfied by "something came back" or by a substring in a message,
and therefore pins nothing about sizing.

### A. `test_max_dimensions.py`

Shared input for every case (`:61-113`): 5 rooms
`Living 12x12, Kitchen 8x7, Bedroom 10x10, Bath 5x6, Balcony 5x7` (`:61-67`), 7 edges (`:68`),
`minDimEnabled: True`, `caller="door_connectivity"`, `count=6`, `limit=6` (`:108-113`),
`plot_width=0, plot_height=0` (`:101`), `rotation_enabled=1` (`:102`).
Cap sets: `TIGHT_CAPS` at `:73-74`; `LOOSE_CAPS = 3x the minimum` at `:78`; baseline sends the
`99999` open sentinel for every max (`:84`).
`fits_under` (`:124-127`) and `fits_over` (`:130-133`) both accept swapped axes, so a `(7,8)`
cap admits an `8x7` room.

Note the harness: `check()` at `:51-57` **records** a failure and prints; it never raises. The
script only signals failure via the process exit code at `:231`.

| Test | Assertion (file:line) | Expected value | Strength |
|---|---|---|---|
| T1 | `:157` `len(open_plans) > 0` | at least 1 plan | WEAK: pins nothing about sizing |
| T1 | `:163-164` `len(breaches(open_plans, TIGHT_CAPS)) > 0` | at least one baseline room overshoots the tight caps | REAL but inverted: it asserts the engine *misbehaves* without caps, so the test has a target |
| T1 | `:165-166` `not reported(open_msg)` | message contains neither `"maximum dimensions were released"` (`:41`) nor `"maximum dimensions were exceeded while closing gaps"` (`:43`) | WEAK: a string check |
| T2 | `:170` `len(loose_plans) > 0` | >= 1 plan | WEAK |
| T2 | `:177-178` `RELEASE_MARKER not in loose_msg.lower()` | no solver release at 3x caps | WEAK: string only |
| T2 | `:179-181` `len(loose_breach) <= len(breaches(open_plans, LOOSE_CAPS))` | capped run has no more breaches than the uncapped run measured against the same caps | REAL but only comparative (monotonicity, no absolute bound) |
| T2 | `:185-188` `clean = [p for p in loose_plans if not breaches([p], LOOSE_CAPS)]; len(clean) > 0` | at least one whole plan in which every room fits inside 3x its minimum on both axes (either orientation) | **REAL, and the strongest sizing assertion in the file** |
| T2 | `:189-191` `(not loose_breach) or reported(loose_msg)` | any overshoot must be accompanied by one of the two markers | WEAK: reporting, not enforcement |
| T3 | `:196-197` `len(tight_plans) > 0` | >= 1 plan | WEAK |
| T3 | `:201-203` `(not tight_breach) or reported(tight_msg)` | overshoot must be reported | WEAK |
| T3 | `:204-206` `len(tight_breach) <= len(open_breach)` | no more breaches than the uncapped baseline | REAL but comparative and very loose (see the measured run below) |
| T4 | `:208-217` for every room in the loose and tight runs, `fits_over(w, h, min_w, min_h)` | every returned room clears its own minimum in at least one orientation | **REAL: an absolute lower-bound guarantee** |
| T5 | `:220-222` `len(loose_plans) >= min(len(open_plans), 1)` | since `open_plans` had 6, `min(...) == 1`, so this reduces to `>= 1` | WEAK: the name says "keep the plan count", the code asserts "at least one plan" |
| T5 | `:223-225` same for `tight_plans` | `>= 1` | WEAK, same defect |

Measured run I executed today (`python test_max_dimensions.py`, repository root
`C:\Users\nitant\Documents\GPLAN_Revamp\GPLAN`): **14 passed, 0 failed**, with the printed
diagnostics `T1 plans=6, rooms over the tight ceilings: 19, worst: Bath 6.0x25.0 vs cap (7, 8)`;
`T2 plans=6, warned=True, rooms over ceiling: 2, 4/6 plans fully within their ceilings`;
`T3 plans=6, warned=True, rooms over ceiling: 16`. So the suite is green while 16 of 30 room
instances violate their requested ceilings.

### B. `test_api_cardinal_constraints.py`

Common input (`:21-36`, `:42-48`): 5 rooms on a circle, all `min 3x3`, all `max 99999`,
`rotation_enabled: 0`, `optimal_floorplan: 0`, `minDimEnabled: True`, `count=6`.
The verifier `check_side` (`:71-103`) is a **strip-intersection test**: it builds the rectangle
between the target room's face and the plot bound on that side (`:83-90`) and requires that no
other room's rectangle overlaps it (`:93-101`). It returns `(ok, tot)` and never inspects any
width or height.

| Test | Assertion (file:line) | Expected value | Strength |
|---|---|---|---|
| T1 Kitchen -> N | `:111` `len(plans) > 0 and ok == tot and tot > 0` | every returned plan has Kitchen's north face exterior | REAL (geometric), but about direction, not size |
| T2 Kitchen -> E | `:117` same shape for side `E` | all plans satisfy | REAL (direction only) |
| T3 impossible combo (`room 2` pinned N and S, plus four more N pins, `:120-124`) | `:126` `len(plans) > 0` | at least 1 plan | WEAK: does not even assert the documented `"Cardinal constraints could not be satisfied and were ignored."` rung (`documentation\cardinal_constraints.md:42-43`) |
| T4 no constraints | `:131` `len(plans) > 0` | >= 1 plan | WEAK |
| T5 Bed -> S, Kitchen -> N | `:138` `len(plans) > 0 and ok1 == tot1 and ok2 == tot2` | both pins hold in every plan | REAL (direction); note `tot > 0` is *not* required here, so an empty room match would vacuously pass |
| T6 wheel graph, hub -> N (`:140-171`) | `:174` `len(plans) > 0` | >= 1 plan | WEAK |
| T6 | `:175` `("relaxed" in msg) or (ok == tot and tot > 0)` | either the spanning-tree rung fired (message substring) or the hub really is north | PARTLY REAL: the disjunction lets a message string satisfy it, so the geometry can go unverified |
| T7 plot 30x20 (`:181-182`) | `:186` `len(plans) > 0` | >= 1 plan | WEAK |
| T7 | `:187-188` guarded by `if "ignored" not in msg:` then `ok1 == tot1 and ok2 == tot2 and tot1 > 0` | pins hold when the engine did not drop them | REAL but self-weakening: if the engine gives up, the only surviving assertion is "plans exist". **Nothing checks that the plans fit inside 30x20.** |
| T8 13 rooms, plot 54x40, three pins (`:190-225`) | `:232` `len(plans) > 0` | >= 1 plan | WEAK |
| T8 | `:233-235` same `"ignored"` guard, then `okW == totW and okN == totN and okE == totE and totW > 0` | all three pins hold | REAL (direction); again **no assertion that the layout respects the 54x40 plot** and none on any room's `min 4x4` |

Measured run today: all 8 pass in 3.2 s; T3 and T6 messages contained
`"No floorplan fits the given plot dimensions; room dimensions were kept and the plot was
expanded to fit."` (the string emitted at `GPLAN\GPLAN\handlers.py:2074-2075`) with no test
reacting to it at all.

### C. `test_multi_ptpg.py`

| Test | Assertion (file:line) | Expected value | Strength |
|---|---|---|---|
| T1 | `:69` `res["status"] == "ok"` | ok | WEAK |
| T1 | `:70` `res["engine"] == "MultiPTPG_FloorPlan"` | literal | WEAK |
| T1 | `:72-77` `json.dumps(res)` does not raise | serializable | WEAK (but a real regression guard for numpy leakage) |
| T1 | `:80-81` `data["floorplan_count"] > 0` | >= 1 | WEAK |
| T1 | `:82` `elapsed < 30` | seconds | WEAK (perf smoke) |
| T1 | `:84-94` for every variant, every plan, every room: `(room["width"], room["height"]) == requested[id]` where `requested` is built from the input nodes at `:84` | `R0 3x2, R1 2x3, R2 2x2, R3 3x2, R4 2x3` exactly | **REAL: the only exactness assertion in the entire suite** |
| T1 | `:96-97` at least one plan with `is_relaxed == False` | >= 1 gap-free plan | REAL (topological, not sizing) |
| T1 | `:99-101` that plan's `adjacency["missing"]` and `["extra"]` are both empty | exact dual | REAL |
| T2 | `:112` status ok | ok | WEAK |
| T2 | `:113-115` `variant_count > 1` | >1 | REAL (topology) |
| T2 | `:116-117` `floorplan_count > 0` | >=1 | WEAK |
| T2 | `:118` `variant_count <= 12` | cap honoured | REAL |
| T2 | `:119` `elapsed < 120` | budget | WEAK |
| T2 | `:121-123` variant edge sets are pairwise distinct | dedup works | REAL |
| T2 | `:125-126` exactly one `is_base` | 1 | REAL |
| T2 | `:128-129` every variant has `len(nodes) == 6` | full room set | REAL |
| T3 | `:139` status ok | ok | WEAK |
| T3 | `:141-148` `[0,1]` and `[3,4]` present in every variant's edge set | protection holds | REAL |
| T3 | `:149-151` `stats["protected_edges"] == [[0,1],[3,4]]` | echo | REAL (reporting) |
| T4 | `:164-165` all three strictness calls return `status == "ok"` | ok | WEAK |
| T4 | `:166-167` `strict["data"]["floorplan_count"] == 0` on 5 identical 4x3 rooms | exactly 0 | **REAL: pins the top rung of the strictness ladder** |
| T4 | `:168-169` `best["data"]["floorplan_count"] > 0` | >=1 | REAL (bottom rung produces something) |
| T4 | `:170-171` `best >= relaxed` count | monotone ladder | REAL but comparative |
| T4 | `:173-175` every zero-plan variant has `status == "no_floorplan"` and a non-empty `reason` | explains itself | REAL (reporting) |
| T5 | `:185` missing `width` -> `status == "error"` | error | REAL (validation) |
| T5 | `:186-187` the error message contains `"2"` | names the node | REAL |
| T5 | `:190` 2 rooms -> error | error | REAL |
| T5 | `:193` `strictness="nonsense"` -> error | error | REAL |
| T5 | `:198` id 9 in a 5-node set -> error | error | REAL |
| T5 | `:202` red-only edge list -> error | error | REAL |
| T6 | `:210` unbounded run has `floorplan_count > 0` | >=1 | WEAK |
| T6 | `:211-212` `plot_width=3, plot_height=3` gives `floorplan_count == 0` | exactly 0 | **REAL: pins the plot reject filter** |
| T6 | `:216-218` every plan from a `20x20` plot has `p["width"] <= 20 and p["height"] <= 20` | numeric bound | **REAL: the only plot-fit assertion anywhere in the three files** |

Measured run today: **34 passed, 0 failed** (T1..T6 as above).

---

## The Actual Constraints Or Formulas

### maxDimEnabled: what `test_max_dimensions.py` proves

It proves three things and no more:

1. **Reporting is honest.** Any breach is accompanied by one of two markers
   (`:41`, `:43`, checked at `:189-191` and `:201-203`). The markers are produced at
   `GPLAN\GPLAN\handlers.py:2202-2203` ("Room maximum dimensions were released for some
   floorplans", the solver-release path, duplicated at `handlers.py:2651`) and at
   `GPLAN\GPLAN\api.py:872-874` ("Room maximum dimensions were exceeded while closing gaps").
2. **Ceilings bind sometimes.** `:185-188`: at least one plan in the 3x-caps run is entirely
   within its caps.
3. **Minimums are never traded away.** `:208-217`.

It does **not** assert that returned dimensions never exceed the requested maxima. There is no
such assertion in the file. The strongest sizing assertion is:

```python
    clean = [p for p in loose_plans
             if not breaches([p], LOOSE_CAPS)]
    check("T2 ceilings actually bind on some plans", len(clean) > 0,
          "no plan respected every ceiling, so the caps did nothing")
```
(`test_max_dimensions.py:185-188`)

That is an existential ("some plan is clean"), not a universal ("no room ever exceeds its cap").
The universal case is explicitly waived at `:201-206`, which accepts arbitrary breach counts as
long as a warning string exists and the count does not exceed the uncapped baseline. Today's run
exercised exactly that escape hatch: 16 breaches, test green.

The reason the contract is stated this way is in the code the test is guarding:

- `GPLAN\GPLAN\source\dimensioning\minimum_dimensioning.py:148` `DEFAULT_UB_FACTOR = 5`,
  `:155` `SOLVER_UB_SLACK = float(os.environ.get("GPLAN_SOLVER_UB_SLACK", "2.5"))`,
  `:158-177` `upper_bound(supplied, low)` returns `min(5*low, max(value, 2.5*low))`, so a cap
  below 2.5x the minimum is deliberately widened before the solver ever sees it.
- `GPLAN\GPLAN\handlers.py:338-353` `solve_min_dim(...)` retries with `max_width`/`max_height`
  popped off every node when the capped solve fails, returning `released=True`.
- `GPLAN\GPLAN\api.py:834-847` `rectangularize_output` runs `_fill_gaps` capped (`:836`), and
  if the plan is still not gapless runs it again with `enforce=False` (`:840`), then flags
  `caps_broken` via `_exceeds_caps` (`:846`, `:675-684`).

So "cap" in this engine means "preference honoured by the solver's widened bound and by the
first gap-fill pass", and the test encodes precisely that weaker promise.

### The multi-PTPG "exact sizes, not minimums" contract

**Where the doc says it.** `documentation\multi_ptpg_api.md:76-81`:

> ### Room sizes are exact, not minimums
>
> This is the premise of the PDF algorithm and the main difference from
> `generate/<shape>` with `minDimEnabled`. Every node must carry a positive `width` and
> `height`; they are rounded to integers because the placer works on integer cells. Clients
> needing sub-unit precision should pre-scale (send centimetres rather than metres).

Reinforced at `multi_ptpg_api.md:11` ("places rooms at **exact** widths and heights on one
graph") and `:31-32` ("The PDF placer replaces the entire dual-construction and dimensioning
half of the engine, which is what keeps room sizes exact").

**The implementing code.** A grep of
`C:\Users\nitant\Documents\GPLAN_Revamp\GPLAN\GPLAN\handlers.py` for
`multi_ptpg|placer|pdf` (case-insensitive) returns **no matches**. Plainly: `handlers.py` has
nothing to do with the multi-PTPG path; the min-dim path in `handlers.py` and the PDF placer are
disjoint code. The whole of the exact-size machinery lives in three files:

1. `GPLAN\GPLAN\api.py:1774-1802` `Documents.get_multi_ptpg_floorplans`, delegating at `:1791`
   and `:1800` to `multi_ptpg_pipeline.run`.
2. `GPLAN\GPLAN\source\multi_ptpg_pipeline.py:77-115` `_room_dimensions`: it **requires** both
   dimensions (`:88-94`, raising `MultiPTPGError("... this API places rooms at exact sizes, not
   minimums")`), coerces with `w = int(round(float(w)))` / `h = int(round(float(h)))` at
   `:95-96`, rejects non-positive at `:97-100`, and invents sizes only for engine-added rooms
   at `:105-113`. The dicts are handed to the placer at `:307-313`.
3. `GPLAN\GPLAN\source\ptpg_floorplanner.py`:
   - `:843-844` `rw = {nid: int(room_widths[nid]) ...}`, `rh = {nid: int(room_heights[nid]) ...}`:
     the single source of truth for every rectangle's size.
   - `:766` `raw_rects[v] = (Wt[v] - rw.get(v, 0), H[v] - rh.get(v, 0), rw[v], rh[v])`:
     the width and height slots are literally `rw[v]`, `rh[v]`; only the origin is computed.
   - `:456-582` `compact_and_resolve_overlaps` copies rects at `:459`, mutates **only** indices
     `[0]` and `[1]` throughout phases 1-3 (`:509-516`, `:533-539`, `:548-575`), and writes back
     `rects[nid][2]`, `rects[nid][3]` unchanged at `:579-581`. **Nothing in the compactor can
     resize a room.** This is the mechanism that makes the contract true.
   - `:897-899` the topological failsafe also seeds `float(rw[nid]), float(rh[nid])`.
   - `:836` the docstring states it: "Room sizes are exact, never minimums; that is the premise
     of this algorithm."
   - Serialization at `:117-129` reports `w`, `h` straight out of `room_rects`.

   The only places a requested number can change are: the integer rounding at
   `multi_ptpg_pipeline.py:95-96`, and the `int()` casts at `ptpg_floorplanner.py:843-844`
   (a redundant second truncation, harmless because the pipeline already rounded).

**Does the test assert it?** Yes, once, in `test_multi_ptpg.py:84-94`:

```python
    requested = {n["id"]: (n["width"], n["height"]) for n in FIVE_ROOM_NODES}
    exact = True
    for variant in data["variants"]:
        for plan in variant["floorplans"]:
            for room in plan["rooms"]:
                want = requested.get(room["id"])
                if want and (room["width"], room["height"]) != want:
                    exact = False
    ...
    check("T1 every room keeps its exact requested size", exact)   # line 94
```

That is a universal quantifier over every variant, every plan and every room, comparing the
tuple of floats returned by the engine against the integers requested. It passed in today's run.
Two holes in it: the input sizes at `test_multi_ptpg.py:45-46` are already integers, so the
rounding path at `multi_ptpg_pipeline.py:95-96` is never exercised; and `requested.get` at
`:88` returns `None` for engine-added rooms, so synthetic-room sizing
(`multi_ptpg_pipeline.py:105-113`, plus `added_room_width`/`added_room_height`) is silently
skipped rather than checked.

---

## Invariants And Preconditions

1. **In-process only.** Every assertion depends on `sys.path.insert` pointing at
   `C:\Users\nitant\Documents\GPLAN_Revamp\GPLAN` so that `GPLAN.api` resolves to
   `GPLAN\GPLAN\api.py` (`test_max_dimensions.py:31`, `test_api_cardinal_constraints.py:17`,
   `test_multi_ptpg.py:16`). Running from any cwd works; running against an installed
   `GPLAN` egg would silently test the wrong code.
2. **`api.py` imports a sibling directory at import time**: `GPLAN\GPLAN\api.py:20-23` prepends
   `<repo>\Space_Optimization` to `sys.path` and imports `boundary_utils`. That directory exists
   at `C:\Users\nitant\Documents\GPLAN_Revamp\GPLAN\Space_Optimization`; if it were removed,
   all three test files would fail at import.
3. **Rotation tolerance.** `test_max_dimensions.py` sends `rotation_enabled: 1` (`:102`) and
   therefore all its size predicates accept swapped axes (`:124-133`). The cardinal file sends
   `rotation_enabled: 0` (`:47`, `:162`, `:215`) because
   `documentation\cardinal_constraints.md:67-69` says the rotation pass is disabled under pins.
   No test asserts that disabling.
4. **Min-dim ignores ratios.** `test_max_dimensions.py:99-100` and
   `test_api_cardinal_constraints.py:44` both send `min_ratio`/`max_ratio`, but
   `GPLAN\GPLAN\api.py:1227` (the `minDimEnabled` branch) constructs `DimParameters` **without**
   them, and `DimParameters.__init__` defaults `min_ratio=[]`, `max_ratio=[]`
   (`GPLAN\GPLAN\pythongui\GuiParameters.py:25`). Those payload fields are inert on this path;
   any test written against them would be testing nothing.
5. **Plot 0x0 in the max-dim suite.** `test_max_dimensions.py:101` sends `plot_width: 0,
   plot_height: 0`, so the plot-cap and plot-expansion machinery is not under test there.
6. **Failure signalling.** `check()` records rather than raises
   (`test_max_dimensions.py:51-57`, `test_multi_ptpg.py:25-31`); only the process exit code at
   `test_max_dimensions.py:231` / `test_multi_ptpg.py:238` reports failure. The cardinal file
   uses bare `assert` and aborts on the first failure.

---

## Failure Modes

- **Green suite, broken product.** `test_max_dimensions.py` T3 passes with any number of
  ceiling breaches as long as (a) a warning substring exists and (b) the count does not exceed
  the uncapped baseline (`:201-206`). Today: 16 breaches, PASS. A regression that stopped
  enforcing caps entirely but kept printing the warning would still be green, provided the
  breach count did not rise above 19.
- **Self-disabling cardinal assertions.** `test_api_cardinal_constraints.py:187` and `:233` skip
  the real check whenever the message contains `"ignored"`. An engine that always fell to the
  bottom ladder rung would leave only `len(plans) > 0` (`:186`, `:232`) in force.
- **T5 misnamed.** `test_max_dimensions.py:220-225` says "ceilings do not shrink the catalogue"
  but `min(len(open_plans), 1)` collapses the bound to `>= 1`. A regression cutting 6 plans to 1
  passes.
- **Under pytest the multi-PTPG suite cannot fail.** `test_multi_ptpg.py:62,104,133,154,178,205`
  are `test_*` functions pytest will collect, but every assertion goes through `check()`
  (`:25-31`), which never raises. Under `pytest test_multi_ptpg.py` every test reports PASS even
  when every check fails; only `python test_multi_ptpg.py` (`:241-242`) is meaningful. The other
  two files expose no `test_*` functions at all (`test_max_dimensions.py` and
  `test_api_cardinal_constraints.py` only define `main()`), so pytest collects **zero** tests
  from them. Any CI that runs `pytest` over this repo is running an empty or vacuous suite.
- **Vacuous-pass in cardinal T5.** `:138` omits the `tot > 0` guard present in T1/T2 (`:111`,
  `:117`), so if the room name lookup at `:76` ever missed, `ok == tot == 0` would pass.
- **Timing assertions are machine-dependent.** `test_multi_ptpg.py:82` (`elapsed < 30`) and
  `:119` (`elapsed < 120`) will flake on a loaded box; they are the only reason T1/T2 could fail
  on a correct engine.

---

## Coupling (what breaks if you change this)

- **Message strings are load-bearing.** `test_max_dimensions.py:41,43` hard-code
  `"maximum dimensions were released"` and `"maximum dimensions were exceeded while closing gaps"`.
  Rewording `GPLAN\GPLAN\handlers.py:2203` / `handlers.py:2651` / `GPLAN\GPLAN\api.py:873-874`
  breaks T1 (`:165-166`) and silently loosens T2/T3 (`:189-191`, `:201-203`) into
  unconditional failures. Likewise `"relaxed"` (`test_api_cardinal_constraints.py:175`) and
  `"ignored"` (`:187`, `:233`) are coupled to
  `documentation\cardinal_constraints.md:40-43` and the strings the engine emits.
- **Response shape.** `response.to_dict()["Documents"]["floorPlans"]`
  (`test_max_dimensions.py:118`, `test_api_cardinal_constraints.py:56`) and the per-room `walls`
  list (`:60-63`) are consumed positionally; any serializer change breaks both files.
- **Multi-PTPG envelope.** `test_multi_ptpg.py` reads `res["status"]`, `res["engine"]`,
  `res["error"]["message"]`, `data["variants"][].floorplans[].rooms[]`, `data["stats"]
  ["protected_edges"]`. These are produced at `multi_ptpg_pipeline.py:338-373` and `:382-408`
  and at `ptpg_floorplanner.py:131-154`.
- **Exactness depends on the compactor never touching indices 2 and 3.** If anyone teaches
  `compact_and_resolve_overlaps` (`ptpg_floorplanner.py:456-582`) to shrink a room to fit a
  plot, `test_multi_ptpg.py:94` is the only thing that will notice.
- **`SOLVER_UB_SLACK` is env-tunable** (`minimum_dimensioning.py:155`,
  `GPLAN_SOLVER_UB_SLACK`). `test_max_dimensions.py:76-78` picks `LOOSE_CAPS = 3x` precisely
  because it sits above the 2.5 default. Exporting `GPLAN_SOLVER_UB_SLACK=4` in a shell would
  change what T2 means without changing a line of test code, and nothing warns about that.

---

## Gap Analysis: documented dimensioning behaviour with no test

Each item names the missing test in one sentence.

1. **`SOLVER_UB_SLACK` widening** (`minimum_dimensioning.py:155`, `:177`). No test observes that
   a cap below 2.5x the minimum is widened for the solver and re-imposed later.
   *Missing test:* send a cap at exactly 1.2x the minimum and assert the solve still succeeds
   while the returned room ends up no larger than the first (capped) `_fill_gaps` pass allows.
2. **`DEFAULT_UB_FACTOR = 5` open-cap fallback** (`minimum_dimensioning.py:148`, `:168`). The
   baseline run at `test_max_dimensions.py:156` sends the 99999 sentinel and asserts only that
   breaches exist.
   *Missing test:* with no ceilings sent, assert every returned room is at most 5x its own
   minimum on each axis.
3. **Solver release ladder** (`handlers.py:338-353`, warning at `:2202-2203`). T2 asserts the
   marker is *absent* (`:177-178`); no test asserts it *fires* when it should.
   *Missing test:* send a cap the topology provably cannot satisfy and assert
   `"maximum dimensions were released"` appears and plans still come back.
4. **Two-pass gap fill, capped then uncapped** (`api.py:836` vs `:840`). The tests cannot tell
   which pass produced a given number.
   *Missing test:* assert that when `_is_gapless` already holds after the capped pass, no room
   exceeds `_room_size_caps`, i.e. that the uncapped pass is not run gratuitously.
5. **Distinguishing the two warning markers.** `reported()` at
   `test_max_dimensions.py:46-48` ORs them, so a solver release and a gap-fill breach are
   indistinguishable to every assertion.
   *Missing test:* assert the gap-fill marker specifically for a case where the solver succeeded
   under caps but `rectangularize_output` had to break one (`api.py:846`).
6. **`repair_dimensions` band re-solve** (`api.py:856`, machinery at `:513-534`, `:537-...`).
   Nothing asserts the final measurements land inside `[min, max]` per axis, per area.
   *Missing test:* after a capped run, assert every room's width/height/area lies within the
   band computed by `_room_bounds`.
7. **Aspect-ratio constraints.** `max_aspect_ratio` feeds `_axis_targets`
   (`api.py:503-509`, `:529-531`) but the min-dim path never receives ratios
   (`api.py:1227`, `GuiParameters.py:25`), and no test sends them on a path that reads them.
   *Missing test:* on the `dimensioned` path, assert a room with `max_ratio = 1.5` comes back
   within that aspect.
8. **Plot caps on the min-dim path.** `test_api_cardinal_constraints.py:181-182` (30x20) and
   `:214` (54x40) supply plots but assert nothing about extents; `test_max_dimensions.py:101`
   uses 0x0.
   *Missing test:* assert every plan returned under `plot_width=30, plot_height=20` has a
   bounding box within 30x20 (or that the expansion warning was emitted).
9. **Plot-expansion fallback** (`handlers.py:2069-2079`, `:2117-2122`, duplicated near `:2512`).
   Today's cardinal run emitted "the plot was expanded to fit" in T3 and T6 and no assertion
   reacted.
   *Missing test:* give an unsatisfiable plot and assert both the warning string and that room
   minimums survived the expansion.
10. **Rotation pass disabled under cardinal pins**
    (`documentation\cardinal_constraints.md:67-69`). Never asserted.
    *Missing test:* run the same graph with `rotation_enabled=1` plus a pin and assert no room's
    axes were swapped relative to the unpinned run.
11. **Gapless outline guarantee** (`api.py:787-798` `_is_gapless`, `:801-875`
    `rectangularize_output`). The cardinal tests compute bounds (`:58-63`) but never check
    coverage; `test_max_dimensions.py` never checks it either.
    *Missing test:* assert `sum(room areas) == bounding-box area` for every min-dim plan, the
    same test the designer performs client-side.
12. **Cardinal ladder rung 3** (`"Cardinal constraints could not be satisfied and were
    ignored."`, `cardinal_constraints.md:42-43`). T3 sets up exactly this case and then asserts
    only `len(plans) > 0` (`test_api_cardinal_constraints.py:126`).
    *Missing test:* assert the "ignored" notice is present for the N+S contradiction.
13. **Cardinal outer-ring augmentation** (`build_cardinal_ring` / `apply_cardinal_ring`,
    `cardinal_constraints.md:100-135`). T8 exercises the code path but asserts only direction.
    *Missing test:* assert the ring path was taken (satisfying-plan count > 0 on the 13-room
    unit) and that ring edges never appear as doors in the output.
14. **One-connected stacked composition** (`cardinal_constraints.md:161-177`, code around
    `api.py:1057`, `:1124`). No test in these three files builds a two-component graph.
    *Missing test:* assert the composed plan's cut room spans the seam and that the scaling did
    not push any room below its minimum.
15. **Multi-PTPG synthetic rooms and `added_room_width`/`added_room_height`**
    (`multi_ptpg_pipeline.py:105-113`, `documentation\multi_ptpg_api.md:187-203`).
    `test_multi_ptpg.py:88` skips unknown ids.
    *Missing test:* a graph that forces `door_connectivity` to add a room, asserting the added
    room's size equals `added_room_width x added_room_height` and `added_by_engine: true`.
16. **Multi-PTPG sub-unit rounding** (`multi_ptpg_pipeline.py:95-96`).
    *Missing test:* send `width: 3.4` and assert the room comes back at exactly 3, plus a
    documented expectation for the 0.5 case.
17. **`time_budget_seconds` truncation** (`multi_ptpg_pipeline.py:298-303`, `:314-319`,
    `stats.truncated`). T2 passes a 120 s budget it never approaches.
    *Missing test:* set a 1-second budget on the 6-room graph and assert `stats["truncated"]` is
    true with `status: "skipped"` variants.
18. **`is_relaxed` semantics.** `test_multi_ptpg.py:96` only counts non-relaxed plans.
    *Missing test:* assert a `is_relaxed: true` plan's `encoded_matrix` actually contains `-1`
    cells and a `is_relaxed: false` plan contains none (`ptpg_floorplanner.py:791`, `:806-807`).

---

## Dead Or Duplicated Code

- `test_api_cardinal_constraints.py:18` imports `normalize_cardinal_constraints` and
  `spanning_tree_edges`; neither name appears anywhere else in the file. Dead imports (they do
  resolve: `GPLAN\GPLAN\api.py:126` and `:1148`).
- `test_api_cardinal_constraints.py:21` `def make_request(cardinal)` never reads its `cardinal`
  parameter; the body (`:22-36`) builds nodes and edges only. Dead parameter, passed at `:39`.
- `test_api_cardinal_constraints.py:25`, `:143`, `:194` each re-`import math` inside a function
  scope. Duplicated import, harmless.
- `test_api_cardinal_constraints.py:65-69` `room_bounds` and `:58-63` `bounds` are near-identical
  min/max walks; the latter is `bounds` over all rooms. Mild duplication.
- `test_max_dimensions.py:143` `ratio = max(w / max(cap), h / max(cap))` divides both axes by the
  *larger* of the two caps. It affects only the sort order of the diagnostic print at `:159-162`
  and `:174-176`; no assertion depends on it. It is a smell, not a bug.
- `test_max_dimensions.py:88-91` builds `width`/`height`/`ratio` dicts on each node and then
  `:97-98` re-reads the same maxima back out to build `dim_inputs`. Duplicated data with two
  chances to diverge; the engine reads `dim_inputs` (`api.py:1227`), not the node dicts, for the
  min-dim path.
- `test_max_dimensions.py:99-100` and `test_api_cardinal_constraints.py:44`: `min_ratio` /
  `max_ratio` are dead payload on the `minDimEnabled` path (see Invariant 4).
- `test_max_dimensions.py:127`-style rotation tolerance means a `(11, 10)` cap for Kitchen is
  effectively `11x10 or 10x11`; not dead, but the caps are looser than they read.
- `_find_new_BL(cycle, placed, prev_BL, orig_corners)` at
  `GPLAN\GPLAN\source\ptpg_floorplanner.py:438-453` never uses `orig_corners`. Dead parameter in
  the code under test.
- `C:\Users\nitant\Documents\GPLAN_Revamp\GPLAN\trial.py` is a 0-byte file (empty), listed in the
  repository root next to these tests.
- The release warning at `handlers.py:2202-2203` is duplicated verbatim at `handlers.py:2651`
  (two near-identical multiple-generation code paths).

---

## Would each test file run today?

I ran all three from `C:\Users\nitant\Documents\GPLAN_Revamp\GPLAN` with the repo's Python.

| File | Verdict | Evidence |
|---|---|---|
| `GPLAN\test_multi_ptpg.py` | **Runnable, green** | Imports at `:16-18` resolve (`from GPLAN.api import Documents`); `python test_multi_ptpg.py` printed `34 passed, 0 failed`. No URL, no port. |
| `GPLAN\test_max_dimensions.py` | **Runnable, green** | Imports at `:31-34`; `python test_max_dimensions.py` printed `14 passed, 0 failed` with diagnostics `T3 plans=6, warned=True, rooms over ceiling: 16`. |
| `GPLAN\test_api_cardinal_constraints.py` | **Runnable, green** | Imports at `:17-19`, including the two unused names; `python test_api_cardinal_constraints.py` printed `ALL CARDINAL TESTS PASSED in 3.2s`, T1-T8 all satisfied. |

Cross-cutting notes on runnability:

- All three depend on `GPLAN\GPLAN\api.py:20-23` finding `<repo>\Space_Optimization\boundary_utils`;
  it is present.
- All three emit `no display found. Using :0.0` at import (Tk shim,
  `GPLAN\GPLAN\pythongui\GuiParameters.py:7-10` lazily proxies `tkinter`), which is noise, not a
  failure.
- Under `pytest` the picture reverses: `test_max_dimensions.py` and
  `test_api_cardinal_constraints.py` expose no `test_*` functions, so pytest collects nothing;
  `test_multi_ptpg.py` exposes six, all of which pass unconditionally because `check()`
  (`:25-31`) never raises. Treat all three as scripts, never as a pytest suite.

---

## Open Questions

1. Is any of this wired into CI? Nothing in the repository root ties these three scripts to a
   runner, and under pytest they are vacuous (see above). Who runs them, and when?
2. `test_max_dimensions.py` T3 tolerates any breach count at or below the uncapped baseline. Is
   the intended contract "never worse than uncapped", or is there a target absolute bound (say,
   no room above `max(cap) * 1.0` after the capped pass) that should replace it?
3. `GPLAN_SOLVER_UB_SLACK` (`minimum_dimensioning.py:155`) silently changes what T2's 3x caps
   mean. Should the test assert the env var is unset, or pin it explicitly?
4. Multi-PTPG exactness is only tested on integer inputs. What is the intended behaviour for
   `width: 3.5` (round-half-even gives 4 via Python's `round`, at
   `multi_ptpg_pipeline.py:95`)? The doc at `multi_ptpg_api.md:79-81` says "rounded" without
   specifying the tie rule.
5. `test_api_cardinal_constraints.py:187` and `:233` skip their real assertions on the substring
   `"ignored"`. Was that intended as a permanent allowance, or a temporary one from before the
   ring augmentation (`cardinal_constraints.md:100-135`) made those cases pass?
6. Should the min-dim tests assert plot containment at all? `test_multi_ptpg.py:216-218` does it
   for the PDF placer, but the min-dim path answers a plot cap with expansion
   (`handlers.py:2069-2079`) rather than rejection, so the equivalent assertion would have to be
   "either fits, or the expansion warning is present". Nobody has written that.
7. `handlers.py:2202-2203` and `:2651` duplicate the release warning across two generation
   paths. Do both paths run in production, and does `test_max_dimensions.py` reach one, the
   other, or both?
