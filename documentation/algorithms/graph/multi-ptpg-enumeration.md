# Multi-PTPG Enumeration Path

Unit: `GPLAN/GPLAN/source/multiple_ptpg.py`, `GPLAN/GPLAN/source/multi_ptpg_pipeline.py`,
`GPLAN/GPLAN/source/ptpg_floorplanner.py`.
Contract doc cross-checked: `C:\Users\nitant\Documents\GPLAN_Revamp\GPLAN\documentation\multi_ptpg_api.md`
(the path given in the task, `GPLAN_Revamp\documentation\multi_ptpg_api.md`, does not exist; copies
also live at `gplan_backend\GPLAN\documentation\multi_ptpg_api.md` and
`gplan_backend\docs\floorplans\multi_ptpg_api.md`).

All line anchors below were read in this session. Absolute prefix for engine files:
`C:\Users\nitant\Documents\GPLAN_Revamp\GPLAN\GPLAN\`.

---

## Purpose

Turn one adjacency graph plus **exact** room widths/heights into dimensioned rectangular
floorplans for *many* topologies of that graph, rather than for the single topology
`door_connectivity` happens to produce.

Three layers:

1. `multiple_ptpg.py` enumerates alternative PTPGs (properly triangulated planar graphs) on
   the same fixed node set, by deleting boundary edges and flipping interior diagonals.
2. `ptpg_floorplanner.py` ("the PDF algorithm") places rooms at exact sizes for one graph and
   one N/E/S/W boundary split, producing a rect list, an encoded matrix, and green/red wall
   labels.
3. `multi_ptpg_pipeline.py` orchestrates: base PTPG, variants, optional interior/exterior
   filter, placer per variant, JSON envelope.

This path deliberately bypasses `InputGraph.irreg_multiple_dual` and the LP dimensioning
stack: `multi_ptpg_pipeline.py:11-19` and `multi_ptpg_api.md:31-32` both say so, and no call
to `irreg_multiple_dual`, `single_floorplan`, or `multiple_floorplan` exists anywhere in the
three files (the only `InputGraph` use is `door_connectivity` at
`source/multi_ptpg_pipeline.py:68`).

## Where It Sits In The Pipeline

Reachability, anchored (question 1):

| Layer | Anchor |
|---|---|
| Django route | `gplan_backend/gplan_apis/urls.py:7` -> `GenerateMultiPTPGFloorplanView` |
| View | `gplan_backend/gplan_apis/views.py:1319` (class), `views.py:1349` (`post`), dispatch at `views.py:1446` |
| Celery task | `gplan_backend/gplan_apis/tasks.py:826`, engine call at `tasks.py:865` |
| Engine facade | `GPLAN/GPLAN/api.py:1775` `Documents.get_multi_ptpg_floorplans`, import at `api.py:1791`, call at `api.py:1800` |
| Pipeline | `source/multi_ptpg_pipeline.py:376` `run` -> `:139` `generate_multi_ptpg_floorplans` |
| Local dev bridge | `GPLAN/local_engine_bridge.py:132-146` |

**`handlers.py` does not reach any of the three modules.** A grep for
`multiple_ptpg|multi_ptpg_pipeline|ptpg_floorplanner` across `GPLAN/GPLAN/` returns hits only
in `api.py:1779,1781,1791,1800` and inside the three modules themselves; `handlers.py` has no
hit. `handlers.py`'s imports (`handlers.py:1-31`) are the Tkinter/GUI-era path
(`inputgraph`, `polygonal`, `dimensioning.minimum_dimensioning`, `pythongui.*`). So:

- `multi_ptpg_pipeline.py` is driven by exactly one endpoint, `POST /api/generate/multi-ptpg`,
  through `api.Documents.get_multi_ptpg_floorplans` (`api.py:1800`).
- `multiple_ptpg.py` is reachable only through that pipeline
  (`multi_ptpg_pipeline.py:47, 253, 262, 277`).
- `ptpg_floorplanner.py` is reachable only through that pipeline
  (`multi_ptpg_pipeline.py:307`). Its only in-repo caller of `generate_floorplans` is that
  line; `get_boundaries` is called only from `ptpg_floorplanner.py:847`.

None of the three is unreachable, but all three hang off a single endpoint and are invisible
to the legacy `handlers.py` flow.

## Entry Points (file:line)

- `source/multi_ptpg_pipeline.py:376` `run(request_data)` (envelope; only caller is `api.py:1800`)
- `source/multi_ptpg_pipeline.py:139` `generate_multi_ptpg_floorplans(params)` (all logic)
- `source/multi_ptpg_pipeline.py:55` `build_base_ptpg(nodes, edges, deadline=None)`
- `source/multi_ptpg_pipeline.py:77` `_room_dimensions(...)`
- `source/multi_ptpg_pipeline.py:118` `_variant_payload(...)`
- `source/multiple_ptpg.py:241` `enumerate_ptpg_variants(...)` (the enumeration loop)
- `source/multiple_ptpg.py:176` `process_ptpg_recursive(G, user_needs, forbidden_cycles)` (one edit step)
- `source/multiple_ptpg.py:346` `filter_variants_by_constraints(...)`
- `source/multiple_ptpg.py:304` `planar_tutte_embedding(...)`
- `source/ptpg_floorplanner.py:819` `generate_floorplans(...)` (strictness ladder)
- `source/ptpg_floorplanner.py:181` `get_boundaries(...)`
- `source/ptpg_floorplanner.py:603` `_pdf_place(...)` (core placer)
- `GPLAN/api.py:1775` `Documents.get_multi_ptpg_floorplans`

## Data Structures

**Variant dict** (`multiple_ptpg.py:254-261` for the base, `:287-294` for children):
`{'graph': nx.Graph, 'forbidden_cycles': set[tuple4], 'depth': int, 'operation':
'base'|'remove_boundary_edge'|'flip_diagonal', 'detail': tuple|None, 'is_base': bool}`.
The pipeline adds `'outer_cycle'` at `multi_ptpg_pipeline.py:262`.

**Canonical variant identity**: `_edge_key` = `frozenset` of sorted edge tuples
(`multiple_ptpg.py:49-51`); the dedup set `seen` lives at `multiple_ptpg.py:262, 280-286`.

**`FloorplanResult`** (`ptpg_floorplanner.py:80-154`): `boundary` (4 arcs of user ids),
`encoded_matrix` (numpy, row 0 = screen top after `np.flipud`, `ptpg_floorplanner.py:809`),
`room_rects` `{nid: (x, y, w, h)}` with y = 0 at bottom, `node_ids`, `edge_labels`
`{frozenset({u,v}): 'green'|'red'|None}`, `is_relaxed`.

**Placer tables** (`ptpg_floorplanner.py:352-398`): `H[v]` = row index of v's top edge,
`Wt[v]` = column index of v's right edge; `M` is a sparse `{(row,col): room}` dict during
placement (`ptpg_floorplanner.py:642, 655-658`) and is densified to numpy at `:791-798`.

**Response payload**: `multi_ptpg_pipeline.py:338-373` (`base_ptpg`, `warnings`, `rooms`,
`variant_count`, `floorplan_count`, `variants`, `stats`).

## Algorithm Walkthrough

### 1. What `multiple_ptpg` varies that `irreg_multiple_dual` does not (question 2)

**It varies the graph itself: a different internally triangulated planar graph (a different
triangulation / adjacency set) on the same fixed, labelled node set.** Not different ST covers,
not different connectivity-repair edge additions, not different RELs.

- Enumeration loop: `multiple_ptpg.py:267-299` (BFS while-loop over `frontier`, bounded by
  `max_depth`, `max_variants`, and `deadline`).
- The varied choice per step is made in `process_ptpg_recursive`:
  - **Stage 1, which outer-cycle edge to delete**: loop `multiple_ptpg.py:191-206`; the edge is
    removed at `:199-200`, guarded by the user-protection test at `:193` and the
    "apex must be interior" test at `:197`.
  - **Stage 2, which interior diagonal to flip**: loop `multiple_ptpg.py:210-236`; the flip is
    `H.remove_edge(diag1)` + `H.add_edge(diag2)` at `:227-228`, guarded by
    `forbidden_cycles` (`:213`), user protection (`:218`), "opposite diagonal already exists"
    (`:220`), and "a,b meet only at u,v" (`:223`). Candidate quads come from
    `find_4_cycles_filtered` (`:136-149`).
- Every child is validated as a PTPG (`is_valid_ptpg`, `:152-173`: connected, biconnected,
  min degree >= 2, every edge in 1 or 2 triangles, planar, simple outer cycle >= 3) and
  deduplicated by edge set (`:280-286`).

Contrast with `InputGraph.irreg_multiple_dual` (`source/inputgraph.py:852`): it fixes the graph
first (biconnect at `inputgraph.py:886-891`, triangulate at `:899-905`) and then enumerates
(a) separating-triangle resolutions, `st.handle_STs(...)` at `inputgraph.py:929` looped at
`:932`; (b) boundaries, `generate_multiple_bdy` at `:946` (defined `:1453-1483`), looped at
`:981`; (c) RELs per boundary, `generate_multiple_rel` at `:986` (defined `:1412-1450`), which
flips **REL** edges/vertices via `flippable.get_flippable_edges` / `resolve_flippable_edge`
(`source/floorplangen/flippable.py:20, 66, 120, 147`). Those are orientation flips inside a
regular edge labeling, on a fixed underlying triangulation. `multiple_ptpg` flips *graph*
diagonals and deletes *graph* boundary edges, which changes which rooms are adjacent at all.
That dimension does not exist in `irreg_multiple_dual`.

### 2. Pipeline stage by stage (question 3)

Validation, `multi_ptpg_pipeline.py:143-183`: non-empty nodes/edges (`:146, 152`), 3..40 rooms
(`:147-150`, `MAX_NODES` at `:38`), contiguous ids `0..n-1` (`:154-160`), red edges dropped
(`:164-166`), knob parsing including `strictness` validation against `pfp.STRICTNESS_LEVELS`
(`:176-177`).

Stage 1, base PTPG: `build_base_ptpg` (`:55-74`) constructs `InputGraph` (`:66`), deep-copies it
(`:67`, because `door_connectivity` mutates and returns `self`, see
`inputgraph.py:520`), calls `door_connectivity(show_graph=False)` (`:68`), and rebuilds an
`nx.Graph` from `ptpg.matrix` (`:72-73`). Node count is taken from the matrix, not from the stale
`nodecnt` (`:196-199`). Room sizes and synthetic-room invention: `_room_dimensions` (`:77-115`).
Warnings for synthetic rooms, engine dummies, `is_ptpg == False`, and non-cycle outer face:
`:211-236`.

Stage 2, enumeration: protected-edge policy at `:243-251` (`protected_edges` wins over
`preserve_input_edges`), call at `:253-256`, per-variant outer cycle at `:261-262`, the
"only the base survived" warning at `:264-273`, the interior/exterior filter at `:275-285`.

Stage 3, batching: a plain sequential `for variant_id, var in enumerate(variants)` loop at
`:293`. There is no parallelism, no chunking. Per iteration:
Tutte positions (`:295`), payload skeleton (`:296`), a pre-flight deadline check that marks the
variant `skipped` and sets `truncated` (`:298-303`), the placer call with `already_ptpg=True`
and `limit=per_variant` (`:307-313`), `DeadlineExceeded` -> `skipped` (`:314-319`), any other
exception -> `status: "error"` for that variant only (`:320-324`), serialization and
`status` = `ok` / `no_floorplan` (`:326-336`). A per-variant failure never aborts the batch.

**Deduplication (find the comparison code)**: there is no isomorphism test anywhere in this
path. Three exact-identity dedups exist:

1. Variants, by labelled edge set: `_edge_key` `multiple_ptpg.py:49-51`, applied at `:262` and
   `:280-286`. Two graphs isomorphic but with different room labels are both kept, which is
   correct here because node ids are rooms.
2. Boundaries, by string of the arc list: `seen = {str(b) ...}` and `add()` at
   `ptpg_floorplanner.py:286-293`. Rotations and mirrors are deliberately *added* (`:294-304`),
   not collapsed.
3. Floorplans, by the exact encoded matrix: `key = str(M.tolist())` and `seen_keys` at
   `ptpg_floorplanner.py:870-873`. `seen_keys` is created inside `run_pass`
   (`ptpg_floorplanner.py:857`), so it is per pass and per variant; identical matrices produced
   for two different variants are both returned.

**Ordering / ranking**: variants come back base-first then in BFS depth order
(`multiple_ptpg.py:254-263, 287-296`), truncated to `max_variants` at `:301`; the pipeline
preserves that order and re-indexes `variant_id` after filtering (`multi_ptpg_pipeline.py:293`).
The pipeline applies **no** quality ranking across variants. Inside one variant, plans are
ranked twice: `keep_best` keeps only maximum adjacency score in the relaxed and best-effort
passes (`ptpg_floorplanner.py:944-952, 957, 960`), then all results are sorted by total area
ascending (`ptpg_floorplanner.py:962`).

### 3. `ptpg_floorplanner` inventory and duplication verdict (question 4)

Full inventory (line, symbol):

| Line | Symbol |
|---|---|
| 55-61 | imports: `opr`, `bcn`, `trng`, `gc`, `sr`, `cip_mod`, `news_mod` |
| 64 | `DEFAULT_MAX_BOUNDARIES = 48` |
| 67 | `class DeadlineExceeded` |
| 71 | `_check_deadline` |
| 80 | `class FloorplanResult` (92 `total_size`, 99 `adjacency_report`, 114 `to_dict`) |
| 157 | `_matrix_adjacencies` |
| 181 | `get_boundaries` (inner 274 `to_ids`, 288 `add`) |
| 315 | `_corners` |
| 324 | `_boundary_cycle` |
| 336 | `_shortcut_edges` |
| 352 | `_init_tables` |
| 401 | `_init_interior` |
| 422 | `_build_gprime` |
| 438 | `_find_new_BL` |
| 456 | `compact_and_resolve_overlaps` (inner 461 `check_overlap`, 466 `push_chain`, 479 `get_system_energy`) |
| 585 | `_place_block` |
| 603 | `_pdf_place` (inner 651 `commit`) |
| 816 | `STRICTNESS_LEVELS` |
| 819 | `generate_floorplans` (inner 856 `run_pass`, 944 `adj_score`, 948 `keep_best`) |

Verdict: **yes, `ptpg_floorplanner` is a second, parallel engine for the back half of the
pipeline (dual construction + dimensioning), while genuinely importing the front half
(graph repair + boundary enumeration primitives).** Function by function:

*Imported, not reimplemented:*

- `get_boundaries` uses `bcn.is_biconnected` / `bcn.biconnect` (`:214-216`), `trng.triangulate`
  (`:219`), `opr.get_trngls` / `opr.get_directed` / `opr.get_bdy` (`:229-231`),
  `sr.get_shortcut` (`:232`), `opr.ordered_bdy` (`:239`), `cip_mod.find_cip` (`:240`),
  `news_mod.find_bdy` / `multiple_corners` / `all_boundaries` / `find_multiple_boundary`
  (`:241-247`), and `gc.check_intersection` (`:206`).

*Duplicated orchestration (same sequence written twice):*

- `get_boundaries:229-247` is a near line-for-line restatement of
  `inputgraph.generate_multiple_bdy` (`source/inputgraph.py:1469-1482`), including the
  `edgecnt == 3 and nodecnt == 3` special case (`ptpg_floorplanner.py:234-237` vs
  `inputgraph.py:1473-1475`). **Duplication**, counterpart `source/inputgraph.py:1453-1483`.
- `get_boundaries:213-224` (biconnect + triangulate) duplicates the identical prologue in
  `inputgraph.irreg_multiple_dual` (`inputgraph.py:886-905`) and
  `inputgraph.door_connectivity` (`inputgraph.py:365-397`). **Duplication**, and dead on this
  path (see Dead Or Duplicated Code).

*Reimplemented primitives that already exist elsewhere:*

- `_shortcut_edges` (`:336-349`) reimplements shortcut detection that
  `source/irregular/shortcutresolver.py:14` `get_shortcut` already provides. The same file
  imports and uses `sr.get_shortcut` at `:232`, so two shortcut implementations coexist in one
  module. **Duplication**, counterpart `source/irregular/shortcutresolver.py:14`.
- `_boundary_cycle` (`:324-333`) reimplements circular boundary ordering already in
  `opr.ordered_bdy` (`source/graphoperations/operations.py:238-258`), and also in
  `multiple_ptpg.get_outer_face_cycle` (`source/multiple_ptpg.py:76-108`). **Duplication**,
  three implementations of "walk the outer face in order" across this path.
- `_corners` (`:315-321`) derives the 4 corners from arcs; the engine's corner machinery is
  `news_mod.multiple_corners` (`source/boundary/news.py:95`), which the same function imports
  and uses at `:245`. **Partial duplication.**
- Encoded-matrix construction at `_pdf_place:791-798` and again in the failsafe at
  `:917-924` reimplements `opr.get_encoded_matrix`
  (`source/graphoperations/operations.py:211-236`), and duplicates itself twice inside this one
  file. **Duplication**, counterpart `operations.py:211`.

*Whole stages replaced by parallel implementations (nothing imported):*

- `_init_tables` (`:352`), `_init_interior` (`:401`), `_build_gprime` (`:422`),
  `_find_new_BL` (`:438`), `_place_block` (`:585`), `_pdf_place` (`:603`) together replace the
  REL-and-dual chain: `news.add_news` (`source/boundary/news.py:249`),
  `contraction.degrees/goodnodes/contract` (`source/floorplangen/contraction.py:23, 35, 187`),
  `expansion.basecase/expand` (`source/floorplangen/expansion.py:29, 53`),
  `flippable.*` (`source/floorplangen/flippable.py:20-147`),
  `dual.populate_t1_matrix/populate_t2_matrix` (`source/floorplangen/dual.py:21, 139`),
  `rdg.construct_dual/get_dimensions` (`source/floorplangen/rdg.py:20, 54`). None of these
  modules are imported by `ptpg_floorplanner` (imports are only `:55-61`). **Parallel engine**,
  same purpose, different algorithm, zero code sharing.
- `compact_and_resolve_overlaps` (`:456-582`) plus the coordinate step at `:761-771` replace the
  dimensioning half: `dual.get_coordinates` (`source/floorplangen/dual.py:235`),
  `dimensioning/floorplan_to_st.py:18`, `dimensioning/solve_linear.py:16`,
  `dimensioning/minimum_dimensioning.py`. **Parallel engine**, an overlap-push plus energy
  hill-climb instead of an LP.
- `_matrix_adjacencies` (`:157-174`) and `FloorplanResult.adjacency_report` (`:99-112`) have no
  counterpart I found in `graphoperations`, `irregular`, `boundary`, or `floorplangen`.

### 4. Dimensioning flow (question 5)

**Its own, not the engine's.** `multi_ptpg_pipeline` never calls `InputGraph.single_floorplan`
(`inputgraph.py:779`) or `InputGraph.multiple_floorplan` (`inputgraph.py:1126`); the only
`InputGraph` method it touches is `door_connectivity` (`multi_ptpg_pipeline.py:68`).

Constraint flow instead:

1. Client sends per-node exact `width`/`height`; missing or non-positive is a hard error
   (`multi_ptpg_pipeline.py:86-101`). Values are rounded to ints (`:95-96`).
2. Engine-invented rooms get the smallest requested size, or `added_room_width` /
   `added_room_height` (`:105-113`, wired at `:199-202`).
3. `widths`/`heights` go straight into `pfp.generate_floorplans` (`:307-313`), which re-casts
   them to `rw`/`rh` int dicts (`ptpg_floorplanner.py:843-844`) and seeds the H/Wt tables
   (`:352-398`). Rooms are never resized; sizes are exact, never minimums
   (`ptpg_floorplanner.py:836`).
4. Plot limits are a **reject filter**: `plot_w`/`plot_h` are read at
   `multi_ptpg_pipeline.py:180-181` and used only to discard an oversized layout at
   `ptpg_floorplanner.py:783-784` and `:912-913`. The one place they steer geometry is the
   relaxed clamp in compaction phase 3 (`ptpg_floorplanner.py:545-549`).
5. `min_width/min_height/max_width/max_height/min_ar/max_ar/symm_rooms`, `block_checker`,
   `floorplan_to_st`, `solve_linear`, `minimum_dimensioning` are all absent from this path.
   The counterpart engine path uses them at `inputgraph.py:817-838`.

So aspect ratio, symmetry, min/max dimension, and the whole `dim_constraints` vocabulary of the
main API have no representation here.

### 5. Contract vs code cross-check (question 6)

**A. Strictness ladder, first pass that yields anything wins.** Doc `multi_ptpg_api.md:83-95`.
Code matches: `generate_floorplans` runs `run_pass(is_relaxed=False)` at
`ptpg_floorplanner.py:954`, then relaxed only if empty and strictness allows (`:956-957`), then
`require_all=False` only for `best_effort` (`:959-960`). The gap/extra-wall/missing-adjacency
semantics are enforced in `_pdf_place` at `:804` (`require_all_adjacencies` -> required subset
of actual) and `:806-807` (non-relaxed -> actual subset of required). **Match.**

**B. `max_boundaries_per_variant` "caps" the O(k^4) enumeration.** Doc
`multi_ptpg_api.md:238`. **Mismatch.** The 4-nested loop is not unconditional: it lives in the
`if not raw_list:` fallback at `ptpg_floorplanner.py:251`, reached only when the CIP machinery
(`news_mod.find_bdy` / `multiple_corners` / `all_boundaries` / `find_multiple_boundary` at
`:241-247`) produced nothing, that is, when the outer boundary carries no shortcuts. On the
normal CIP path `raw_list` is already populated at `:247` and the O(k^4) loop never runs. When
the fallback does fire, it enumerates every consecutive 4-split of the whole outer cycle to
completion (`ptpg_floorplanner.py:262-268`, with only a deadline probe at `:269`). In both
cases rotations and mirrors are then appended (`:294-304`) and only afterwards is the list
sliced (`:306-307`). So the knob caps how many boundaries get *placed*, not the cost of
enumerating them: the cap is a post-hoc truncation and never bounds enumeration cost. The doc
line already scopes the O(k^4) to the no-shortcut case, so the surviving defect is the words
"this caps it", not the cost model.

**C. `encoded_matrix` `-1` "only possible when `is_relaxed` is true".** Doc
`multi_ptpg_api.md:178-179`. **Mismatch (unenforced claim).** `is_relaxed` is simply the pass
flag (`ptpg_floorplanner.py:880`), and nothing checks that a compact layout tiles its bounding
box. The non-relaxed path runs only compaction phases 1 and 2
(`ptpg_floorplanner.py:496-539`; phase 3 is gated on `relaxed` at `:542`), and phase 2 is a hill
climb that stops at a local minimum (`:524-539`). The only rejections are the adjacency tests at
`:804-807`, which a hole in the middle of the plan does not necessarily trip. So an
`is_relaxed: false` plan can carry `-1` cells.

**D. `edge_labels[].wall`: green = shared vertical wall, red = shared horizontal.** Doc
`multi_ptpg_api.md:176-177`. **Partial mismatch.** `_build_gprime` implements exactly that rule
(`ptpg_floorplanner.py:431-434`: green iff bottoms `H-rh` agree). But during placement, `commit`
relabels using a different criterion, `H[u] < h_m` -> green (`ptpg_floorplanner.py:664-669`),
and the topological failsafe labels **every** edge `'red'` unconditionally
(`ptpg_floorplanner.py:932`). Labels on failsafe plans, and on rooms first labelled inside
`commit`, do not honour the documented rule.

**E. Behaviours that do match** (spot checks): 3..40 room bounds (`:147-150` vs doc `:213`);
red-only edges is an error (`:164-166` vs doc `:216`); `protected_edges` takes precedence
whenever present (`:243-247` vs doc `:105`); interior/exterior rejecting everything still
returns `ok` with `variant_count: 0` (`:275-285`, `:358` vs doc `:222`); budget exhaustion marks
variants `skipped` and sets `stats.truncated` (`:298-303, :314-319, :371` vs doc `:225`);
`already_ptpg=True` skips re-triangulation (`:311` vs `ptpg_floorplanner.py:213` and doc
`:282-283`); default `max_boundaries` 48 (`ptpg_floorplanner.py:64`, `:174` vs doc `:67`).

**F. Doc drift worth noting:** doc `:146` calls `variants[].nodes` "Tutte layout", but
`planar_tutte_embedding` silently falls back to `nx.spring_layout` when there is no outer cycle
(`multiple_ptpg.py:308-309`). Also doc `:194` shows `numpy.array(ptpg.matrix).shape[0]` as the
node-count source; the code uses the equivalent `G_base.number_of_nodes()`
(`multi_ptpg_pipeline.py:199`, graph built at `:72-73`), so the intent holds but the snippet is
not the code.

## Invariants And Preconditions

- Node ids must be exactly `0..n-1` after sorting; enforced at `multi_ptpg_pipeline.py:154-160`.
  Everything downstream indexes `widths`/`heights`/`room_names` by integer id
  (`:107-113, :348-357`).
- Every node carries a positive integer width and height; enforced `:86-101`. There is no
  minimum-dimension mode on this path.
- Red (non-adjacency) edges are dropped before `door_connectivity`
  (`multi_ptpg_pipeline.py:162-166`), so the non-adjacency branch of
  `inputgraph.door_connectivity` (`inputgraph.py:362-369, 384-388, 436-437`) is never taken.
- Variants preserve the node count: `is_valid_ptpg(H, expected_nodes)` with `expected_nodes`
  captured at `multiple_ptpg.py:251` and checked at `:156`.
- Every emitted variant is planar, connected, biconnected, min degree >= 2, every edge in 1 or 2
  triangles, and has a simple outer cycle of length >= 3 (`multiple_ptpg.py:152-173`).
- Both transformations destroy an existing adjacency, so protecting all input edges makes the
  base graph a fixed point (`multi_ptpg_pipeline.py:239-251`, warning `:264-273`).
- `already_ptpg=True` is a promise from the pipeline that the variant is internally triangulated
  with a simple-cycle outer face (`multi_ptpg_pipeline.py:311`, contract stated at
  `ptpg_floorplanner.py:186-188`). If it is violated, the boundary machinery at
  `ptpg_floorplanner.py:229-247` runs on an untriangulated graph.
- A non-relaxed plan realises exactly the required adjacency set, no more
  (`ptpg_floorplanner.py:804-807`).
- `deadline` is a `time.monotonic()` stamp, not a duration (`multi_ptpg_pipeline.py:169`,
  `ptpg_floorplanner.py:71-73`).

## Failure Modes

- **Validation errors** become `status: "error"`, `type: "ValidationError"`, HTTP 200
  (`multi_ptpg_pipeline.py:389-396`). Any other exception is wrapped with a truncated traceback
  (`:397-408`).
- **`door_connectivity` failure** (non-planar input, internal error) is re-raised as
  `MultiPTPGError("door_connectivity failed: ...")` at `multi_ptpg_pipeline.py:190-191`.
- **`is_ptpg == False`**: separating triangles survive; pipeline continues with a warning
  (`:223-228`), never falling back to `irreg_multiple_dual`.
- **Outer face is not a simple cycle**: the variant search cannot move, warning at `:229-236`;
  `boundary_nodes` falls back to `opr.get_bdy` / `opr.ordered_bdy` so the client still gets a
  boundary (`multiple_ptpg.py:121-133`).
- **Only the base variant survives**: warning at `:264-273`, with the `protected_edges` hint.
- **Interior/exterior filter rejects everything**: `variants` becomes `[]`, the stage-3 loop does
  not run, `variant_count: 0` plus warning (`:275-285`).
- **No layout at the exact sizes**: `_pdf_place` returns `None` from any of
  `ptpg_floorplanner.py:624, 633, 636, 742, 759, 765, 784, 786, 805, 807`; the variant gets
  `status: "no_floorplan"` (`multi_ptpg_pipeline.py:328-335`).
- **Plot too small**: rejected at `ptpg_floorplanner.py:783-784` (and `:912-913` for the
  failsafe), which folds into `no_floorplan`. Every candidate is built first, so a tight plot is
  the slowest case.
- **Deadline**: `DeadlineExceeded` (`ptpg_floorplanner.py:67-73`) surfaces as `status:
  "skipped"` per variant and `stats.truncated: true` (`multi_ptpg_pipeline.py:314-319, 371`).
  The enumerator checks the deadline at `multiple_ptpg.py:268, 275`.
- **Per-variant exception**: caught at `multi_ptpg_pipeline.py:320-324`, that variant is
  `status: "error"`, the batch continues.
- **Silent swallow**: `generate_floorplans` returns `[]` on any non-deadline exception from
  `get_boundaries` (`ptpg_floorplanner.py:853-854`), and `run_pass` swallows per-boundary
  exceptions (`:884-885`). A systematic bug in the placer looks identical to "no layout exists".
- **Unbounded-ish inner loops**: `compact_and_resolve_overlaps` caps iterations at 500 / 1000 /
  300 (`:497, 524, 543`) and `push_chain` recurses over rects (`:466-477`); a pathological input
  burns the whole per-variant budget here rather than erroring.

## Coupling (what breaks if you change this)

- **`door_connectivity`'s return shape.** `build_base_ptpg` assumes `(ptpg, is_ptpg)` or a bare
  object (`multi_ptpg_pipeline.py:69-70`); the current contract is `return self,
  check_ptpg(...)` at `inputgraph.py:520`. Adding a third element or returning a new object
  instead of `self` changes what the pipeline reads from `ptpg.matrix` (`:72`).
- **`ptpg.matrix` node ordering.** Everything downstream assumes matrix index == client room id
  for the first `len(nodes)` indices and that any extra index is engine-invented
  (`multi_ptpg_pipeline.py:105-113, 196-202`). If separating-triangle handling ever renumbers
  rooms, room names and sizes silently attach to the wrong rectangles.
- **`opr.get_bdy` / `opr.ordered_bdy` / `cip.find_cip` / `news.*` signatures.** Consumed at
  `ptpg_floorplanner.py:229-247` and, in a duplicate copy of the same sequence, at
  `inputgraph.py:1469-1482`. A change must be made in both places; the copies have already
  drifted (the pfp copy has a 4-split fallback and rotation/mirror expansion the inputgraph copy
  does not).
- **`sr.get_shortcut`.** Used at `ptpg_floorplanner.py:232` while `_shortcut_edges` (`:336`)
  computes the same thing differently for the placement loop. Change one and the boundary
  enumeration and the placement loop can disagree about what a shortcut is.
- **`STRICTNESS_LEVELS` / `DEFAULT_MAX_BOUNDARIES`.** Read by name from the pipeline
  (`multi_ptpg_pipeline.py:174, 176`); renaming them breaks request validation.
- **Response payload keys.** Consumed by `GPLAN/test_multi_ptpg.py`,
  `gplan_backend/smoke_test_multi_ptpg.py:161`, the Celery cache
  (`gplan_backend/gplan_apis/tasks.py:865-874`), and documented in `multi_ptpg_api.md:114-172`.
- **`np.flipud` orientation.** `encoded_matrix` is flipped at `ptpg_floorplanner.py:809` and
  `:929` so row 0 is the top, while `room_rects` keep y = 0 at the bottom
  (`:766, 770`). Any client drawing both must know this; the doc calls it out at `:180-181`.
- **Nothing else imports these three modules.** Changing them cannot break the `generate/<shape>`
  or circulation paths, which is the one upside of the parallel-engine design.

## Dead Or Duplicated Code

- **`get_boundaries(..., already_ptpg=False)` branch, `ptpg_floorplanner.py:213-224`, is dead on
  every reachable path.** The only in-repo caller of `generate_floorplans` is
  `multi_ptpg_pipeline.py:307`, which always passes `already_ptpg=True` (`:311`), and
  `get_boundaries` has no other caller (`ptpg_floorplanner.py:847` only). So the biconnectivity
  augmentation and triangulation inside the placer never execute in production.
- **`build_base_ptpg`'s `deadline` parameter is unused** (`multi_ptpg_pipeline.py:55`; the body
  `:56-74` never references it). The first stage of the pipeline is therefore not
  time-bounded even though the caller passes a deadline at `:187`.
- **`_find_new_BL`'s `orig_corners` parameter is unused** (`ptpg_floorplanner.py:438`; body
  `:439-453`). Callers still pass it at `:723` and `:750`.
- **Duplicate boundary-enumeration orchestration**: `ptpg_floorplanner.py:229-247` vs
  `inputgraph.generate_multiple_bdy` (`inputgraph.py:1469-1482`), including the identical
  3-node special case (`ptpg_floorplanner.py:234-237` vs `inputgraph.py:1473-1475`).
- **Duplicate shortcut detection**: `_shortcut_edges` (`ptpg_floorplanner.py:336-349`) vs
  `sr.get_shortcut` (`source/irregular/shortcutresolver.py:14`), both live in the same module.
- **Duplicate outer-cycle ordering, three implementations**:
  `ptpg_floorplanner._boundary_cycle` (`:324-333`), `opr.ordered_bdy`
  (`source/graphoperations/operations.py:238`), `multiple_ptpg.get_outer_face_cycle`
  (`source/multiple_ptpg.py:76-108`).
- **Duplicate encoded-matrix construction**: `ptpg_floorplanner.py:791-798` and `:917-924`
  (twice in one file) vs `opr.get_encoded_matrix`
  (`source/graphoperations/operations.py:211-236`).
- **Duplicate dual-construction and dimensioning stacks**: `_init_tables` / `_init_interior` /
  `_build_gprime` / `_pdf_place` / `compact_and_resolve_overlaps`
  (`ptpg_floorplanner.py:352, 401, 422, 603, 456`) stand in for
  `source/boundary/news.py:249`, `source/floorplangen/contraction.py:187`,
  `source/floorplangen/expansion.py:29, 53`, `source/floorplangen/dual.py:21, 139, 235`,
  `source/floorplangen/rdg.py:20, 54`, `source/dimensioning/floorplan_to_st.py:18`,
  `source/dimensioning/solve_linear.py:16`. This is the parallel engine, stated plainly.
- **Whole-tree duplication**: identical copies of all three modules exist under
  `gplan_backend/GPLAN/GPLAN/source/` (the submodule checkout), e.g.
  `gplan_backend/GPLAN/GPLAN/source/multi_ptpg_pipeline.py:5`. Edits must land in the engine repo
  and be pulled through the submodule.
- **Doc duplication**: `GPLAN/documentation/multi_ptpg_api.md`,
  `gplan_backend/GPLAN/documentation/multi_ptpg_api.md`, and
  `gplan_backend/docs/floorplans/multi_ptpg_api.md`.

## Open Questions

- Can a non-relaxed plan actually produce `-1` cells in practice, or does the adjacency firewall
  (`ptpg_floorplanner.py:804-807`) incidentally exclude every gapped compact layout? The code
  does not enforce the doc's claim (`multi_ptpg_api.md:178-179`); a targeted test would settle
  it. Until then treat `is_relaxed` as "which pass produced this", not "has holes".
- `commit`'s green/red rule (`ptpg_floorplanner.py:664-669`) uses `H[u] < h_m`, while
  `_build_gprime` (`:431-434`) uses equality of bottoms. Is the divergence intentional
  (incremental propagation) or a porting slip? The failsafe's blanket `'red'` (`:932`) is
  clearly a placeholder.
- `keep_best` (`ptpg_floorplanner.py:948-952`) is applied to the relaxed and best-effort passes
  but not to the exact pass (`:954`). Deliberate (exact plans are all score 0) or an oversight?
- `stats.variants_returned` and `variant_count` are always equal
  (`multi_ptpg_pipeline.py:358, 364`); is one of them meant to exclude `skipped` / `error`
  variants?
- `get_boundaries` mirrors and rotates every boundary (`ptpg_floorplanner.py:294-304`) and then
  truncates to `max_boundaries` (`:306-307`), so a low cap can consume the whole budget on
  rotations of one boundary before reaching a structurally different one. Was the cap intended to
  apply before the rotation expansion?
- The knowledge graph (`graphify explain "multi_ptpg_pipeline"`) lists the same symbols and line
  numbers as the source (`generate_multi_ptpg_floorplans` L139, `build_base_ptpg` L55,
  `run` L376, etc.), so there is no graph-vs-code disagreement to record for this unit.
