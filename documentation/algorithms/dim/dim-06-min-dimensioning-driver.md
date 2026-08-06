# dim-06: `minimum_dimensioning.py`, the min-dimension driver

Target file: `C:\Users\nitant\Documents\GPLAN_Revamp\GPLAN\GPLAN\source\dimensioning\minimum_dimensioning.py`
(846 lines, read in full).

> **2026-08-06 (door-width overlap floor, E2b).** Three changes postdate every
> anchor below: (1) `DOOR_OVERLAP_FLOOR = 3.0` module constant +
> `adjacency_overlap_floor` global (reset in `reinitialize`, overridable via a
> new `main(..., overlap_floor=None)` kwarg); the constraint builders apply it
> to RED adjacencies - **red marks the BRIEFED door edges in this solver's
> input, black the triangulation extras** (verified live; the legacy red floor
> was 0.1 ft, the corner-sliver source). (2) `input_adjacency`'s orientation
> classifier is tolerance-based on touching walls + perpendicular overlap;
> corner-contact pairs are SKIPPED instead of defaulting to type 3 (the old
> exact `==` chain wired feasible-but-meaningless constraints - solves
> "succeeded" with the pair 8 ft apart). (3) `handlers.solve_min_dim` is now a
> four-rung ladder, each rung on a fresh deepcopy because `main` MUTATES its
> input in place (re-solving a touched dict double-bumps the 1-based ids and
> crashes `tblr_rooms`). Context and measurements:
> `documentation/plans/VALIDITY_AND_TOPOLOGY_ENGINE_PLAN.md` E2b/E6. Line
> anchors below shift ~+30 past the constants block.

## Correction to the task premise (read this first)

The task assumed this driver calls `floorplan_to_st`, `convert_adj_equ_sym` and `solve_linear`, and
that `dim_on_paths` / `dim_on_paths_bdy` live here. **None of that is true.** Verified by reading and
by repo-wide grep:

- `minimum_dimensioning.py` has exactly three imports: `collections.defaultdict`, `json`, `os`
  (lines 1-3). It imports nothing from the `dimensioning` package. There is no `import`, no
  `from .`, and no call to `floorplan_to_st`, `convert_adj_equ_sym`, `solve_linear` or
  `block_checker` anywhere in the file. It also never uses `numpy` or `scipy`.
- The LP pipeline (`floorplan_to_st` -> `convert_adj_equ_sym` -> `solve_linear`) is a **separate,
  parallel** dimensioning path. Its driver is
  `C:\Users\nitant\Documents\GPLAN_Revamp\GPLAN\GPLAN\source\dimensioning\floorplan_to_st.py:18`,
  which calls `convert_adj_equ_sym` at `floorplan_to_st.py:103` and `:105` and `solve_linear` at
  `floorplan_to_st.py:108`. Its external callers are
  `C:\Users\nitant\Documents\GPLAN_Revamp\GPLAN\GPLAN\source\inputgraph.py:821` and `:1167`
  (imported at `inputgraph.py:39`), plus `GPLAN\GPLAN\bdy.py:18` and `GPLAN\GPLAN\source\trial\bdy.py:18`.
- `dim_on_paths_bdy` lives at
  `C:\Users\nitant\Documents\GPLAN_Revamp\GPLAN\GPLAN\source\path_map.py:99`, not here.
- **There is no function named `dim_on_paths` anywhere in the repo.** Repo-wide grep for
  `dim_on_paths` returns only `dim_on_paths_bdy` hits (`inputgraph.py:972`, `inputgraph.py:1057`,
  `path_map.py:99`, `test_api_cardinal_constraints.py:177`, `documentation/cardinal_constraints.md:73`,
  plus the graphify cache). The `dim_on_paths` / `dim_on_paths_bdy` pairing in the task prompt does
  not exist in code.

So this dossier documents what the file actually is: a **shortest/longest-path constraint-graph
solver over a dual pair of s-t graphs**, no LP, no scipy. Sections 3, 4 and 5 of the task are
answered against the files where those things really live, each clearly labelled.

---

## Purpose

Given one already-chosen rectangular topology (a floorplan candidate: per-room `room_x`, `room_y`,
`room_width`, `room_height` that encode only the *arrangement*), plus per-room minimum and optional
maximum width/height and an optional plot cap, produce **actual coordinates and dimensions** that
respect every adjacency of that topology.

It does this by building two independent difference-constraint graphs (one per axis) over the
`2 * rooms + 2` vertical/horizontal wall lines, and running a longest-path relaxation on each. The
"minimum" in the name is literal: the objective is implicit, the longest-path from the source pushes
each wall to the smallest coordinate consistent with all lower bounds, so rooms come out at (near)
their minimum dimensions.

The whole module is **global-state based**: `data`, `edgesX`, `edgesY`, `placementx`, `placementy`,
`adj`, `adj_type`, `plot_width`, `plot_height` etc. are module-level globals (lines 4, 23-57, 41-46,
48-49, 51-54), reset by `reinitialize()` (line 729) at the top of every `main()` call (line 769).
It is not reentrant and not thread-safe.

## Where It Sits In The Pipeline

```
api.py  ->  handlers.py  ->  inputgraph.irreg_multiple_dual()      (topology enumeration:
                                 |                                  boundaries, RELs, graph_list_by_bdy)
                                 v
            handlers.py loops over every candidate topology
                                 |
                                 v
            input_for_min_dim.floorplan(...).get_floorplan_details(...)   (builds the json dict)
                                 |
                                 v
            handlers.solve_min_dim()  ->  min_dim.main(data, plot_width, plot_height)   <-- THIS FILE
                                 |
                                 v
            handlers writes room_x/room_y/room_width/room_height back onto graph.graph_list[i]
                                 |
                                 v
            api.rectangularize_output() -> _fill_gaps -> repair_dimensions
```

Sole importer: `C:\Users\nitant\Documents\GPLAN_Revamp\GPLAN\GPLAN\handlers.py:9`
(`import GPLAN.source.dimensioning.minimum_dimensioning as min_dim`).

`inputgraph.py` never touches this module. Repo grep for `min_dim` / `minimum_dimensioning` inside
`GPLAN/source/inputgraph.py` returns zero hits.

## Entry Points (file:line)

Every top-level `def` in the file, with signature, internal caller, and external caller.

| # | Function | Signature (line) | Called internally from | Called externally from |
|---|---|---|---|---|
| 1 | `input_adjacency` | `def input_adjacency():` (`:70`) | `input_data` `:221` | none |
| 2 | `tblr_rooms` | `def tblr_rooms():` (`:107`) | `input_data` `:216` | none |
| 3 | `upper_bound` | `def upper_bound(supplied, low):` (`:158`) | `input_constraints` `:195`, `:198` | none |
| 4 | `input_constraints` | `def input_constraints():` (`:181`) | `input_data` `:220` | none |
| 5 | `input_data` | `def input_data():` (`:207`) | `main` `:825` | none |
| 6 | `construct_constraintgraphX` | `def construct_constraintgraphX(small_positive = 2):` (`:225`) | `main` `:828` | none |
| 7 | `construct_constraintgraphY` | `def construct_constraintgraphY(small_positive = 2):` (`:307`) | `main` `:829` | none |
| 8 | `pos_longest_path` | `def pos_longest_path(placement, edge_set, edge_weights):` (`:388`) | `longest_path` `:479` | none |
| 9 | `longest_path` | `def longest_path(placement, edge_set, edge_weights):` (`:466`) | `compute_placement` `:557`, `:561` | none |
| 10 | `print_placements` | `def print_placements():` (`:536`) | **none** (only commented-out calls at `:832`, `:834`) | none -> **DEAD** |
| 11 | `compute_placement` | `def compute_placement():` (`:547`) | `main` `:831` | none |
| 12 | `print_edges` | `def print_edges():` (`:568`) | **none** (commented call at `:830`) | none -> **DEAD** |
| 13 | `compute_rot` | `def compute_rot(small_positive = 2):` (`:578`) | `main` `:835` | none |
| 14 | `print_rot` | `def print_rot():` (`:678`) | **none** (commented call at `:836`) | none -> **DEAD** |
| 15 | `print_input` | `def print_input():` (`:687`) | **none** (commented call at `:826`) | none -> **DEAD** |
| 16 | `edit_placements` | `def edit_placements():` (`:695`) | `main` `:837` | none |
| 17 | `return_output` | `def return_output():` (`:710`) | `main` `:838` | none |
| 18 | `reinitialize` | `def reinitialize():` (`:729`) | `main` `:769` | none |
| 19 | `main` | `def main(input, plot_width, plot_height):` (`:767`) | `__main__` guard `:845` (broken, see below) | **YES** |

**The single external entry point is `main` (`:767`).** External call sites, all in
`C:\Users\nitant\Documents\GPLAN_Revamp\GPLAN\GPLAN\handlers.py`:

- `handlers.py:346` and `handlers.py:352` (both inside `solve_min_dim`, `handlers.py:338`)
- `handlers.py:390` (`generate_mindim_rfp`)
- `handlers.py:834`
- `handlers.py:1250`
- `handlers.py:1394`

The grep that produced this: for each of the 18 non-`main` names, a repo-wide
`grep -rn "<name>" --include=*.py` over `C:\Users\nitant\Documents\GPLAN_Revamp\GPLAN` excluding the
file itself returned **zero** matches. No other module reaches into this one's internals.

### The `__main__` guard is broken

`minimum_dimensioning.py:844-845`:

```python
if __name__ == "__main__":
    main("input_to_min_dim.json")
```

`main` requires three positional arguments (`:767`). Running this module directly raises
`TypeError: main() missing 2 required positional arguments: 'plot_width' and 'plot_height'`.
Even if it took one argument, it would then pass the *string* `"input_to_min_dim.json"` as `data`
and immediately fail at `data['edges']` (`:774`, `:779`, `:802`). This is dead, non-functional code
left over from the file-based version whose remnants are the commented block at `:6-21` and
`:806-813`.

## Data Structures

Wall numbering is the load-bearing convention. For `rooms` rooms:

- Vertex `0` is the source (`sx` in X, `sy` in Y).
- Vertex `2*i - 1` for room `i` in `1..rooms` is the **left** wall (X graph) / **top** wall (Y graph).
- Vertex `2*i` is the **right** wall (X graph) / **bottom** wall (Y graph).
  Both aliases are set explicitly at `:250-253` and `:332-334`.
- Vertex `2*rooms + 1` is the sink (`tx` / `ty`).

| Structure | Declared | Shape / meaning |
|---|---|---|
| `rooms` | `:4`, set `:211` | `len(data['nodes'])` |
| `edgesX`, `edgesY` | `:33-34`, allocated `:213-214` | dense `2*(rooms+1)` x `2*(rooms+1)` weight matrices, initialised to `POS_INF = 1e8` (`:39`) |
| `edges_setx`, `edges_sety` | `:35-36` | **lists (not sets, despite the name) of `(a, b)` tuples** that are the live edges; duplicates are appended freely |
| `adj` | `:30` | `defaultdict(list)`, symmetric room adjacency, filled `:102-103` |
| `adj_type` | `:31` | `dict[(ri, rj)] -> 1..4`, filled `:96-100`; codes documented `:58-68` |
| `lb_width`, `ub_width`, `lb_len`, `ub_len` | `:41-44` | 1-indexed, index 0 holds a `-1` filler pushed at `:186-189` |
| `placementx`, `placementy` | `:48-49` | wall coordinates, length `2*rooms + 2`, seeded `:548-555` |
| `rotx1/rotx2/roty1/roty2` | `:51-54` | "range of tolerance" per wall, **0-indexed by `wall - 1`**, length `2*rooms`, seeded `:579-583` |
| `plot_width`, `plot_height` | `:45-46` | module globals, set from `main`'s parameters at `:822-823` |
| `irreg_nodes_map` | `:56` | `(irreg_node1, irreg_node2) -> merged dummy node`, filled `:774-776` |
| `door_connectivity_edges` | `:57` | set of `(source, target)` for red edges, filled `:788`, `:790`, `:792` |
| `num_sx/num_sy/num_tx/num_ty`, `sx_adj/sy_adj/tx_adj/ty_adj` | `:23-27` | see Dead Code: the four `*_adj` lists are **write-only** |

Input contract (`data`, assigned `:771`): `nodes` (each with `id`, optional `label`, `room_x`,
`room_y`, `room_width`, `room_height`, `min_width`, `min_height`, optional `max_width`,
`max_height`), `edges` (each `source`, `target`, `color` in `{'red','black'}`), `boundary_rooms`
with keys `north`/`east`/`south`/`west`, and optionally `mergednodes` / `irreg_nodes1` /
`irreg_nodes2` / `dummy_node_adj`.

Output contract (`return_output`, `:710-725`): `{'nodes': [{'id', 'label'?, 'room_x', 'room_y',
'width', 'height'}]}`, wrapped as `[True, out_data]` at `:839`.

## Algorithm Walkthrough

### One full successful run of `main` (`:767`)

Every hand-off line, in execution order:

1. **`:769` `reinitialize()`** wipes all module globals (`:729-763`). Note it declares
   `plot_width`/`plot_height` global at `:730` and zeroes them at `:751-752`.
2. **`:771` `data = input`** binds the module-level `data` global.
3. **`:774-776`** build `irreg_nodes_map` from `mergednodes` / `irreg_nodes1` / `irreg_nodes2`.
4. **`:779-800` (dummy-node branch)** or **`:801-804` (plain branch)** normalise the edge list to
   1-based room ids. In the dummy branch, red (door) edges are collected into
   `door_connectivity_edges` (`:783-792`), the original edge list is *cleared* (`:793`), and it is
   rebuilt from `data['dummy_node_adj']` with `source = a[0] + 1`, `target = a[1] + 1` and colour
   `'red'` if the pair carried door connectivity, else `'black'` (`:796-800`). In the plain branch
   each `source`/`target` is bumped by 1 in place (`:802-804`).
5. **`:814-821`** bump every entry of `boundary_rooms['north'|'south'|'east'|'west']` by 1 (same
   1-based shift).
6. **`:822-823`** `globals()['plot_width'] = plot_width` / `globals()['plot_height'] = plot_height`.
   The `globals()[...]` form is required because `main`'s parameter names (`:767`) shadow the module
   globals of the same name.
7. **`:825` `input_data()`** (`:207`):
   - `:211` `rooms = len(data['nodes'])`
   - `:213-214` allocate `edgesX` / `edgesY` filled with `POS_INF`
   - `:216` `tblr_rooms()` -> boundary-to-source/sink zero edges (see formulas)
   - `:218-219` reset `adj`
   - `:220` `input_constraints()` -> fills `lb_*` / `ub_*` via `upper_bound` (`:195`, `:198`)
   - `:221` `input_adjacency()` -> derives `adj_type` from the candidate geometry (`:84-91`)
8. **`:828` `construct_constraintgraphX()`** (`:225`): X plot cap, per-room width bounds, X equality
   edges for type-1/2 adjacencies, **and the Y overlap edges those adjacencies imply** (`:277-285`,
   `:295-303`).
9. **`:829` `construct_constraintgraphY()`** (`:307`): Y plot cap, per-room height bounds, Y equality
   edges for type-3/4 adjacencies, **and the X overlap edges those imply** (`:358-366`, `:376-384`).
   Note the cross-writes: each "axis" builder writes into *both* matrices, so **the order
   `X then Y` at `:828-829` matters** and neither builder is self-contained.
10. **`:831` `compute_placement()`** (`:547`): the two solves.
11. **`:835` `compute_rot()`** (`:578`): range-of-tolerance pass.
12. **`:837` `edit_placements()`** (`:695`): shrink west/south rooms to minimise area.
13. **`:838` `out_data = return_output()`** (`:710`), then **`:839` `return [True, out_data]`**.

### Are horizontal and vertical two separate solves? Yes.

`compute_placement` (`:547-565`):

- `:548-555` seed both vectors: index 0 = `0` (the source), indices `1 .. 2*rooms+1` = `-1`.
- **`:557` `if not longest_path(placementx, edges_setx, edgesX): return False`** - horizontal solve.
- **`:561` `if not longest_path(placementy, edges_sety, edgesY): return False`** - vertical solve.
- `:565` `return True`.

They are fully independent runs of the same relaxation over disjoint state. There is no shared
variable, no coupling term, no iteration between them. All cross-axis coupling was already baked in
at graph-construction time (steps 8 and 9 above): a horizontal adjacency writes *vertical* overlap
edges and vice versa, so by the time `longest_path` runs, each axis is a pure 1-D difference system.

Consequence: X can succeed and Y fail (`:561` returns `False` after `:557` already mutated
`placementx`). The partially-solved `placementx` is discarded because `main` returns
`[False, None]` at `:833`.

### How the two solution vectors combine into width/height/x/y

`return_output` (`:710-725`), per 0-based room index `i` (so room number `r = i + 1`, left/top wall
`2r-1 = 2i+1`, right/bottom wall `2r = 2i+2`):

```python
:718  dic['room_x'] = float(round(placementx[2*i+1], 4))                              # LEFT wall
:719  dic['room_y'] = float(round(placementy[2*i+2], 4))                              # BOTTOM wall
:720  dic['width']  = float(round(placementx[2*i+2],4) - round(placementx[2*i+1],4))  # right - left
:721  dic['height'] = float(round(placementy[2*i+1],4) - round(placementy[2*i+2],4))  # top - bottom
```

So: `placementx` supplies both `room_x` and `width`; `placementy` supplies both `room_y` and
`height`. **Y is oriented upward** in the solved vector (the Y source `sy` connects to *south*
rooms' bottom walls, `:127-128`, and *north* rooms' top walls connect to `ty`, `:143-144`), hence
`height = placementy[top] - placementy[bottom]` with `top` at the odd index.

**The input Y grows upward too. There is no axis inversion across the driver; what changes is which
wall `room_y` names.** On input, `room_y` is the room's **top** (max-y) wall and the height extends
downward from it. That is forced by `input_adjacency:88`
(`data['nodes'][ri-1]['room_y'] - room_height == data['nodes'][rj-1]['room_y']` -> `adj_type 4`)
read against the code table at `:64-68`, where type 4 means "the first room in the pair is to the
top side": subtracting `ri`'s height from `ri.room_y` has to land on `ri`'s bottom wall for `rj` to
be the room below it. On output, `room_y` is the **bottom** wall, `placementy[2i+2]` (`:719`), with
`height = top - bottom` (`:721`). The producer confirms the anchor convention rather than a sign
flip: `GPLAN\GPLAN\input\input_for_min_dim.py:36` and `:46` set the node's
`room_y = room_y + room_height` before handing it to the solver, and
`GPLAN\GPLAN\input\input_template.py:136-138` classifies a raw `room_y == 0.0` room as **south**,
i.e. the raw coordinates are bottom-anchored and upward-growing. A genuine inversion would be
`y -> H - y`, not `y -> y + h`.

Rounding is applied *before* subtraction at `:720-721`, so `width` is exactly the difference of the
two rounded coordinates and adjacent rooms' `room_x + width` line up bit-for-bit. That is deliberate
and load-bearing for `api._is_gapless`.

### `longest_path` (`:466-531`) and `pos_longest_path` (`:388-462`)

- `:469` `total_neg = sum(1 for a, b in edge_set if edge_weights[a][b] < 0)` bounds the outer loop.
- `:473-475` `adj_s` = every head `b` of an edge whose tail is the source.
- `:478` `while not done and ctr <= total_neg:`
  - `:479` `pos_longest_path(...)`; `False` propagates out immediately (`:480`).
  - `:487-492` **source-contact check**: at least one `x in adj_s` must still satisfy
    `placement[x] == 0`, else `done = False; break`.
  - `:495-497` **plot-cap check**:
    `if (2*rooms+1, 0) in edge_set and placement[2*rooms+1] > abs(edge_weights[2*rooms+1][0])`
    -> `done = False; break`. This is where the plot cap actually rejects a plan.
  - `:499-527` negative-edge relaxation with a nested re-propagation of positive edges (`:506-526`);
    the special case at `:519-521` rewrites `edge_weights[a][0] = -1 * placement[a]` when the head is
    the source.
- `:529-530` prints `"Returned false in [longest_path]"` on failure (unconditional `print`, not
  behind a debug flag).

`pos_longest_path` is a hand-optimised rewrite of an O(V*E*deg) triple loop; the docstring at
`:389-407` records the measurement that motivated it (202 ms per call, 45.8 s of a 46.2 s 2BHK run).
It precomputes, per edge, whether that edge *blocks* its head (`:421-430`), keeps a per-wall
`blocking_in` counter, and returns `False` at `:458-461` if any wall was never pushed. Note
`is_pushed` has length `n_walls = 2*rooms+1` (`:408`, `:433`), i.e. indices `0..2*rooms`, so **the
sink `2*rooms+1` is never included in the reachability check**.

## The Actual Constraints Or Formulas

Edge semantics throughout: an edge `(a, b)` with weight `w` means
**`placement[b] - placement[a] >= w`**.

### Upper bound (`upper_bound`, `:158-177`)

```
low     = float(low)
open_ub = DEFAULT_UB_FACTOR * low          # DEFAULT_UB_FACTOR = 5   (:148, :168)

supplied is None                    -> open_ub                       (:169-170)
float(supplied) raises              -> open_ub                       (:171-174)
value <= 0 or value >= 99999        -> open_ub                       (:175-176)
otherwise                           -> min(open_ub, max(value, SOLVER_UB_SLACK * low))   (:177)
                                    == min(5*low, max(value, 2.5*low))
```

`SOLVER_UB_SLACK = float(os.environ.get("GPLAN_SOLVER_UB_SLACK", "2.5"))` (`:155`).

Applied at `:195` (`up_len = upper_bound(node.get('max_height'), low_len)`) and `:198`
(`up_width = upper_bound(node.get('max_width'), low_width)`), with
`low_len = float(node['min_height'])` (`:194`) and `low_width = float(node['min_width'])` (`:197`).

**A supplied maximum below `2.5 x min` is silently widened to `2.5 x min`.** The rationale is in the
comment at `:149-154`: in a gapless tiling a column of small rooms must stack to the same total as a
column of large ones, so hard per-room ceilings make almost every topology infeasible; the exact
ceiling is instead enforced downstream in `api._fill_gaps`.

### Source / sink boundary edges (`tblr_rooms`, `:107-144`)

```
west  room a:  edgesX[0][2a-1]              = 0    (:117-118)   left wall of a  at x >= 0
south room a:  edgesY[0][2a]                = 0    (:127-128)   bottom wall of a at y >= 0
east  room a:  edgesX[2a][2n+1]             = 0    (:135-136)   tx >= right wall of a
north room a:  edgesY[2a-1][2n+1]           = 0    (:143-144)   ty >= top wall of a
```
where `n = len(data['nodes'])`.

### Plot caps

```
X (:229-231):  if plot_width  > 0:  edgesX[2*rooms+1][0] = -1 * plot_width
Y (:311-313):  if plot_height > 0:  edgesY[2*rooms+1][0] = -1 * plot_height
```
Read literally: `placement[0] - placement[2*rooms+1] >= -plot_width`, i.e.
`placement[tx] <= plot_width`. Enforced at `:495-497`.
**`plot_width == 0` means "no cap"**, which is exactly how the expansion fallback disables it.

### Per-room size bounds

```
X (:237-238):  edgesX[2i-1][2i] =      lb_width[i]     ->  right_i - left_i   >=   min_width_i
               edgesX[2i][2i-1] = -1 * ub_width[i]     ->  left_i  - right_i  >= -max'_width_i
                                                       ->  width_i <= max'_width_i
Y (:319-320):  edgesY[2i][2i-1] =      lb_len[i]       ->  top_i    - bottom_i >=  min_height_i
               edgesY[2i-1][2i] = -1 * ub_len[i]       ->  bottom_i - top_i    >= -max'_height_i
                                                       ->  height_i <= max'_height_i
```
`max'` is the widened bound from `upper_bound`, not the caller's raw value.

### Adjacency equalities

`adj_type` codes (`:58-68`): 1 = first room is to the right, 2 = to the left, 3 = to the bottom,
4 = to the top. Derived from candidate geometry at `:84-91`; the reverse pair is `t+1` for odd `t`
and `t-1` for even `t` (`:97-100`).

```
type 1, i right of x  (:271-274):  edgesX[2x][2i-1] = 0  and  edgesX[2i-1][2x] = 0
                                   -> left_i == right_x   (equality via two 0-weight arcs)
type 2, i left of x   (:289-292):  edgesX[2x-1][2i] = 0  and  edgesX[2i][2x-1] = 0
                                   -> right_i == left_x
type 3, i below x     (:352-355):  edgesY[2i-1][2x] = 0  and  edgesY[2x][2i-1] = 0
                                   -> top_i == bottom_x
type 4, x below i     (:370-373):  edgesY[2x-1][2i] = 0  and  edgesY[2i][2x-1] = 0
                                   -> top_x == bottom_i
```

### Cross-axis minimum wall overlap (`small_positive`)

For a horizontally adjacent pair `(i, x)` (types 1 and 2), the *vertical* overlap is forced
(`:277-285` for type 1, `:295-303` for type 2, identical bodies):

```
edgesY[2i-1][2x]  = NEG_INF (= -1e8, :38)   -> vacuous
edgesY[2x][2i-1]  = small_positive          -> top_i    - bottom_x >= small_positive
edgesY[2x-1][2i]  = NEG_INF                 -> vacuous
edgesY[2i][2x-1]  = small_positive          -> top_x    - bottom_i >= small_positive
```
Together: the vertical spans of `i` and `x` overlap by at least `small_positive` on both sides.

Symmetrically for a vertically adjacent pair (types 3 and 4), the *horizontal* overlap
(`:358-366`, `:376-384`):

```
edgesX[2x-1][2i] = small_positive           -> right_i - left_x >= small_positive
edgesX[2i][2x-1] = NEG_INF                  -> vacuous
edgesX[2i-1][2x] = small_positive           -> right_x - left_i >= small_positive
edgesX[2x][2i-1] = NEG_INF                  -> vacuous
```

`small_positive` value (`:256-260` in X, `:337-341` in Y):

```
color = edge_color_map.get((x, i)) or edge_color_map.get((i, x))
if color == 'red':   small_positive = 0.1
elif color == 'black': small_positive = 2
# otherwise: keeps whatever value it had from the previous iteration
```

Per `GPLAN\documentation\door_connectivity.md:205` a black edge is a required adjacency and a red
edge is a non-required one, which makes `red -> 0.1` (barely touching is enough) and
`black -> 2` (a real 2-unit shared wall) consistent. Note the naming inside `main` (`:782`,
`:786-792`) calls the red set `door_connectivity_edges`, which reads the other way round; see Open
Questions.

### Range of tolerance (`compute_rot`, `:578-670`)

`rotx1/rotx2/roty1/roty2` are **0-indexed by `wall - 1`** and seeded (`:579-583`) as
`rotx1[k] = 0`, `rotx2[k] = placementx[2*rooms+1]`, `roty1[k] = 0`,
`roty2[k] = placementy[2*rooms+1]`.

Own-size pass (`:585-589`), for room `i`:
```
rotx2[2i-2] = min(rotx2[2i-2], placementx[2i]   - min_width_i)     # how far left wall may slide right
rotx1[2i-1] = max(rotx1[2i-1], placementx[2i-1] + min_width_i)     # how far right wall may slide left
roty1[2i-2] = max(roty1[2i-2], placementy[2i]   + min_height_i)
roty2[2i-1] = min(roty2[2i-1], placementy[2i-1] - min_height_i)
```

Neighbour pass (`:592-609`):
```
type 1: rotx1[2i-2] = max(rotx1[2i-2], min_width_x  + placementx[2x-1])
type 2: rotx2[2i-1] = min(rotx2[2i-1], placementx[2x] - min_width_x)
type 3: roty2[2i-2] = min(roty2[2i-2], placementy[2x-1] - min_height_x)
type 4: roty1[2i-1] = max(roty1[2i-1], placementy[2x]   + min_height_x)
```

`small_positive` pass (`:612-638`):
```
type 1 or 2:  a = placementy[2x] + small_positive ; b = placementy[2x-1] - small_positive
              roty1[2i-2] = max(roty1[2i-2], a)   ; roty2[2i-1] = min(roty2[2i-1], b)
type 3 or 4:  a = placementx[2x-1] + small_positive ; b = placementx[2x] - small_positive
              rotx1[2i-1] = max(rotx1[2i-1], a)   ; rotx2[2i-2] = min(rotx2[2i-2], b)
```

Shared-wall reconciliation (`:640-670`): for each adjacency the two wall indices that denote the
*same* physical wall get `rot1 = max(...)` and `rot2 = min(...)` copied to both, e.g. type 1
(`:643-649`) reconciles indices `2i-2` and `2x-1`.

### Area minimisation (`edit_placements`, `:695-706`)

```
for each west room j (:696-700):
    if rotx2[2j-2] > placementx[2j-1]:  placementx[2j-1] = rotx2[2j-2]
for each south room j (:702-706):
    if roty2[2j-1] > placementy[2j]:    placementy[2j] = roty2[2j-1]
```

Only west and south boundary rooms, and only their outer wall, are moved. Because that wall has no
neighbour on the far side (it sits on the plot boundary), moving it inward does not violate any
adjacency equality, but it **does** open a strip of empty space along the west/south edge. Closing
that strip is exactly the job of `api._fill_gaps`
(`C:\Users\nitant\Documents\GPLAN_Revamp\GPLAN\GPLAN\api.py:710`).

Note `rotx1` and `roty1` are computed exhaustively across `:585-670` and are then **never read** by
`edit_placements`; their only other reader is the dead `print_rot` (`:678`).

## Invariants And Preconditions

1. **1-based room ids after `main`'s normalisation.** `main` bumps every `edges` `source`/`target`
   (`:800`, `:802-804`) and every `boundary_rooms` entry (`:814-821`) by 1. `main` **mutates the
   caller's dict in place** in the non-dummy branch (`:802-804` writes `a['source']` back). Calling
   `main` twice on the same dict double-shifts the ids. `handlers.solve_min_dim` sidesteps this with
   `copy.deepcopy` at `handlers.py:345` before the retry.
2. **`data['nodes'][i]` must expose `min_width` and `min_height`.** Missing keys raise `KeyError`
   at `:194`, `:197`; `max_width`/`max_height` are optional (`.get`, `:195`, `:198`).
3. **The candidate geometry must be a genuine rectangular arrangement.** `input_adjacency` derives
   `adj_type` from coordinates (`:84-91`) with a bare `else: adj_type_input = 3` at `:90-91`. Any
   pair that matches none of the three tested alignments is *silently* declared type 3
   ("first room is at the bottom"). The `if adj_type_input < 1 or adj_type_input > 4: exit(1)` guard
   at `:92-94` can therefore never fire, and note it would call `exit(1)` (process kill), not raise.
4. **`construct_constraintgraphX` must run before `construct_constraintgraphY`** (`:828-829`) because
   each writes edges into the *other* matrix.
5. **`reinitialize()` must run before any state is touched** (`:769`), and `plot_width`/`plot_height`
   globals must be set *after* it (`:822-823`), since `reinitialize` zeroes them (`:751-752`).
6. `edges_setx` / `edges_sety` are lists and may contain duplicate `(a, b)` pairs; the algorithms
   tolerate that because the weight lookup is by matrix, not by list position.
7. `total_neg > 0` is required for `longest_path` to run at all (`:469`, `:478`); with zero negative
   edges the `while` body never executes, `done` stays `False`, and the function returns `False`.
   In practice `total_neg >= rooms` because every room contributes `-ub_width[i]` (`:238`).

## Failure Modes

### What the driver returns on total failure

`main` has exactly two return statements:

- **`:833` `return [False, None]`** when `compute_placement()` (`:831`) is falsy.
- `:839` `return [True, out_data]` on success.

`compute_placement` returns `False` from `:559` (horizontal solve failed) or `:563` (vertical solve
failed). `longest_path` returns `False` from `:480` (a wall was unreachable in `pos_longest_path`) or
`:531` with `done == False` (source-contact check `:487-492`, plot-cap check `:495-497`, or the
`ctr <= total_neg` budget exhausted). Every failure prints `"Returned false in [longest_path]"`
(`:530`). There are no exceptions raised for infeasibility, and no diagnostic beyond that one string.

### How the caller reacts

**`inputgraph.py` is not the caller.** It contains zero references to `min_dim` /
`minimum_dimensioning`. The real caller chain:

1. `handlers.solve_min_dim` (`handlers.py:338-353`):
   ```
   :345  retry_data = copy.deepcopy(floorplan_data) if capped else None
   :346  status, out_data = min_dim.main(floorplan_data, plot_width, plot_height)
   :347  if status or retry_data is None: return status, out_data, False
   :349-351  for node in retry_data['nodes']: node.pop('max_width', None); node.pop('max_height', None)
   :352  status, out_data = min_dim.main(retry_data, plot_width, plot_height)
   :353  return status, out_data, bool(status)
   ```
   So `[False, None]` triggers exactly one retry, with every per-room ceiling stripped, and the third
   tuple element (`released`) records that it happened.
2. The topology loops (`handlers.py:1894-1898`, `:2004-2007`, `:2120-2123`, `:2322-2325`,
   `:2435-2438`, `:2567-2569`) gate on `if status == True:` and otherwise simply **drop that
   candidate topology and move on**. `floorplan_found` stays `False`.
3. `max_dims_released` is OR-accumulated (`:1897` etc.) and surfaces as
   `"Warning: Room maximum dimensions were released for some floorplans."`
   (`handlers.py:2202-2203`, `:2650-2651`).
4. If *no* candidate succeeded, `handlers.py:2069-2079` (and `:2510` in the sibling flow) prints
   `"No floorplan found which satisfies the minimum dimensions input by user."` and warns
   `"No floorplan fits the given plot dimensions; room dimensions were kept and the plot was
   expanded to fit."`, then re-runs every candidate with the plot cap removed:
   `handlers.py:2120-2121  solve_min_dim(floorplan_data, 0, 0, max_width is not None or max_height is not None)`.
   Zeros disable the cap edges at `minimum_dimensioning.py:229` and `:311`.
5. `generate_mindim_rfp` (`handlers.py:390-391`) calls `min_dim.main` directly with no retry at all;
   a `False` there just skips the floorplan.

### Other failure modes

- `exit(1)` at `:94` would terminate the host process rather than raise. Unreachable in practice
  (see Invariant 3), but it is a live `exit` call in a library module.
- `adj_type[(i, x)]` at `:268`, `:349`, `:594`, `:622`, `:642` is a bare `dict` lookup; a room in
  `adj` without a matching `adj_type` entry raises `KeyError`. `pos_longest_path` deliberately uses
  `adj_type.get(...)` instead (`:425`) with the reason spelled out at `:417-420`.
- `small_positive` leakage: it is a *function parameter* reassigned inside the neighbour loop
  (`:258`, `:260`, `:339`, `:341`, `:618`, `:620`). When an edge's colour is neither `'red'` nor
  `'black'`, or when `edge_color_map.get` returns `None`, the value from the **previous neighbour of
  the previous room** persists. Order-dependent, silent.
- `:256` uses `or` for the fallback: `edge_color_map.get((x, i)) or edge_color_map.get((i, x))`.
  A colour that is falsy (empty string) falls through to the reverse lookup. Harmless with the two
  real values but fragile.
- Y-solve failure after a successful X-solve leaves `placementx` fully populated and `placementy`
  partially relaxed; both are discarded by the `[False, None]` return, and `reinitialize` clears them
  on the next call.

## Coupling (what breaks if you change this)

| Change here | What breaks |
|---|---|
| Wall numbering (`2i-1` / `2i`) | Everything: `tblr_rooms` (`:117-144`), both graph builders, `compute_rot` index arithmetic (`:585-670`), `edit_placements` (`:698`, `:704`), `return_output` (`:718-721`). The `rot*` arrays use a *different* base (`wall - 1`) than the `placement*` arrays, so the two conventions must be changed together. |
| Y anchor convention | Both sides use an upward-growing Y, but `input_adjacency:88` reads the input `room_y` as the room's **top** wall (height extends downward) while `return_output:719`/`:721` emit `room_y` as the **bottom** wall. The `room_y = room_y + room_height` shift at `input_for_min_dim.py:36`/`:46` is what bridges the two. Changing either anchor without the other silently offsets every room by its own height; a real axis flip (`y -> H - y`) on one side alone would mirror every plan. |
| `upper_bound` (`:158-177`) | `handlers.solve_min_dim` retry semantics (`handlers.py:349-352`) and `api._room_size_caps` / `_fill_gaps` (`api.py:640`, `:710`) assume the solver honours only a *widened* ceiling and the exact ceiling is applied later. Tightening `upper_bound` to honour the raw max would collapse the catalogue (the comment at `:149-154` says this is measured, not theoretical). |
| `SOLVER_UB_SLACK` default (`:155`) | Overridable via `GPLAN_SOLVER_UB_SLACK`. Lowering it toward 1.0 restores the pre-fix collapse; raising it above `DEFAULT_UB_FACTOR = 5` makes the `min(open_ub, ...)` at `:177` clamp it back to `5*low`, so values above 5 are a no-op. |
| The `plot_width > 0` / `plot_height > 0` guards (`:229`, `:311`) | The plot-expansion fallback at `handlers.py:2120-2121` passes literal `0, 0` to mean "no cap". Treating 0 as a real cap would make that fallback always fail. |
| `[False, None]` return shape (`:833`) | Unpacked as a 2-tuple at `handlers.py:346`, `:352`, `:390`, `:834`, `:1250`, `:1394`. |
| `out_data['nodes'][k]` key names (`:715-721`) | Read at `handlers.py:1906-1911` (`room_x`, `room_y`, `width`, `height`) and equivalents at `:398-403`, `:2131-2134`. |
| `edit_placements` (`:695-706`) | Deliberately introduces west/south gaps. `api.rectangularize_output` (`api.py:801`) *requires* `_is_gapless` (`api.py:787`) and only passes because `_fill_gaps` (`api.py:710`) closes them. Removing `_fill_gaps` would drop most plans; removing `edit_placements` would change every plan's bounding box and the `min_area` selection at `handlers.py:2062-2064`. |
| Module globals | Any concurrency. A second `main` on another thread would corrupt `edgesX` / `placementx` mid-solve. `reinitialize` (`:729`) is the only defence and it is call-scoped, not lock-scoped. |

## Dead Or Duplicated Code

**Dead functions (no caller anywhere, internal or external):**
- `print_placements` (`:536-543`) - the only call sites are the comments at `:832` and `:834`.
- `print_edges` (`:568-575`) - comment at `:830`.
- `print_rot` (`:678-684`) - comment at `:836`.
- `print_input` (`:687-692`) - comment at `:826`.

**Broken entry point:** `if __name__ == "__main__": main("input_to_min_dim.json")` (`:844-845`) -
wrong arity and wrong argument type. See the Entry Points section.

**Write-only state:**
- `sx_adj` (appended `:116`), `sy_adj` (`:126`), `tx_adj` (`:134`), `ty_adj` (`:142`) are never read
  by any function. `edit_placements` re-reads `data['boundary_rooms']['west'|'south']` directly
  (`:696-697`, `:702-703`) instead of using them.
- `num_sx` / `num_sy` / `num_tx` / `num_ty` (`:111`, `:121`, `:130`, `:138`) are used only as the
  bounds of the loops that immediately follow.
- `rotx1` and `roty1` are computed throughout `:585-670` but read only inside `compute_rot`'s own
  reconciliation pass and by the dead `print_rot`. `edit_placements` uses only `rotx2` (`:698`) and
  `roty2` (`:704`).

**Duplicated code:**
- The four `small_positive` overlap blocks are byte-identical pairs: `:277-285` == `:295-303`
  (X builder, types 1 and 2) and `:358-366` == `:376-384` (Y builder, types 3 and 4). The `type_val`
  branch changes only the equality edges, never the overlap edges, so the `if`/`elif` could be
  hoisted.
- The edge-colour lookup map is built twice, once per builder: `:243-246` (`edge_color_map`) and
  `:325-328` (`edge_color_map_y`), from the same `data['edges']`.
- `compute_rot` re-derives the colour with an O(rooms * deg * |edges|) linear scan (`:615-620`)
  instead of reusing either map.

**Stale merge markers / abandoned file-based path:**
- `:770` `# <<<<<<< main`, `:805` `# =======`, `:813` `# >>>>>>> Door_connectivity_cleanup` -
  commented-out conflict markers wrapping the dead file-reading branch at `:806-812`.
- `:6-21` the original `open('input.json')` / `open('output.json')` block.
- `:842` `# main(file_path)`.

**Unreachable guard:** `:92-94` (see Invariant 3).

---

## Section 3 answered: `dim_on_paths_bdy` (NOT in this file)

File: `C:\Users\nitant\Documents\GPLAN_Revamp\GPLAN\GPLAN\source\path_map.py`.

### There is no `dim_on_paths`

Verified by repo-wide grep. Only `dim_on_paths_bdy` exists, defined once at `path_map.py:99`:

```python
def dim_on_paths_bdy(all_bdy, room_w, room_h, plot_width, plot_height, bdy_edges):
```

Called from `inputgraph.py:972` and `inputgraph.py:1057` (imported via the star-import at
`inputgraph.py:20`, `from GPLAN.source.path_map import *`). `room_w` / `room_h` are the **minimum**
width/height lists: `handlers.py:1810` builds `input_dims = [min_width, min_height, plot_width,
plot_height]` and `inputgraph.py:968-971` / `:1053-1056` unpack them in that order.

It runs **only when plot dimensions were given and no cardinal constraints are set**:
`handlers.py:1812-1813` sets `input_dims = []` when `plot_width == 0 and plot_height == 0`, and
`inputgraph.py:959-966` / `:1045-1051` short-circuit to `selected_list = cip_list` under cardinal
constraints.

### The boundary pool it builds

Built **once**, at the top of the function, outside every retry:

```
:102-110   outer_rooms = every distinct endpoint of every edge in bdy_edges
:112-120   keep only room indices itr with itr in outer_rooms; collect new_room_w / new_room_h /
           new_indices    (note: the `print(new_indices)` at :120 is inside the loop, O(n^2) output)
:121-122   room_w / room_h are REBOUND to those filtered lists
:128-133   rooms = { original_index: {'width': ..., 'height': ...} }   for the survivors only
```

`rooms` is the pool. Every later measurement uses it, and any room **not** in it silently
contributes zero:

```
:146  total_width  = sum(rooms[r]['width']  for r in path if r in rooms)
:147  total_height = sum(rooms[r]['height'] for r in path if r in rooms)
```

### The "cardinal" search: it is NOT exhaustive over N/E/S/W

`paths_after_select_bdy` (`path_map.py:48-97`) is what rearranges the four paths:

```
:52-58   target_indices = [1, 3] when wall_possibility == "h", else [0, 2]
:60      for wall in list_filtr_walls:
:61          for idx_target in target_indices:
:62-63           rearr_bdy = [None]*4 ; rearr_bdy[idx_target] = wall
:66              remaining = [w for w in selected_bdy if w != wall]
:69-73           idx = (idx_target + 1) % 4
                 for w in remaining:  place at the next free slot, cycling
```

`remaining` (`:66`) is the original list order with `wall` deleted, so it is the elements *before*
`wall` followed by the elements *after* it. Writing that into the free slots starting at
`idx_target + 1` therefore produces the cyclic order `wall`, `[before-wall]`, `[after-wall]`, which
is **not** the original cyclic order except in special cases. **The output is an arbitrary cyclic
re-fill, not a rotation.** Running the exact loop body over `selected_bdy = [A,B,C,D]`:

```
wall=B, idx_target=3  ->  [A, C, D, B]      not a rotation of [A,B,C,D]
wall=B, idx_target=1  ->  [D, B, A, C]      not a rotation
wall=C, idx_target=0  ->  [C, A, B, D]      not a rotation
wall=A, idx_target=1  ->  [D, A, B, C]      a rotation (wall sits at index 0)
wall=D, idx_target=2  ->  [B, C, D, A]      a rotation (wall sits at index 3)
```

The result is a rotation only when the chosen wall sits at index `0` or index `3` of
`selected_bdy`, i.e. 8 of the 16 `(wall, idx_target)` pairs, and only 4 of the 8 pairs that either
target set actually reaches. What the function never produces is a **reversal**: no arrangement in
the enumeration is the reverse of `selected_bdy`, so the "no reflections" half of the picture
stands.

That makes `is_circularly_connected(rearr_bdy)` at `:90` (defined `:36-45`) **load-bearing, not
vestigial**. It is the primary filter that discards the re-fills which break the shared-corner
invariant `curr[-1] == next_wall[0]` (`:43`), and most of the non-rotational arrangements above do
break it.

Acceptance test (`:77-90`), per rearranged boundary, counting how many of the 4 paths fit:

```
:79-80   total_width  = sum of widths  of the rooms on this path that are in the pool
         total_height = sum of heights of the rooms on this path that are in the pool
:82-83   remaining_wt = plot_wt - total_width ; remaining_ht = plot_ht - total_height
:85      odd  index (ind % 2 != 0):  count += 1 if threshold_ratio * plot_ht >= remaining_ht >= 0
:87      even index:                 count += 1 if threshold_ratio * plot_wt >= remaining_wt >= 0
:90      accept iff count_condition(count) and is_circularly_connected(rearr_bdy)
:95      filtr_bdys = remove_reflections(pos_bdy)
```

Search-space size, exactly:

```
outer:   for bdy in all_bdy                                     (:141)  -> |all_bdy| = |cip_list|
inner:   pointers_w / pointers_h  <= 4 paths each               (:163-164)
calls:   at most 2 calls to paths_after_select_bdy per bdy      (:192, :196)
each:    |list_filtr_walls| (<=4)  x  2 target indices          (:60-61)
```
so **at most `|cip_list| x 2 x 4 x 2 = 16 |cip_list|` rearrangements evaluated**: up to
`|list_filtr_walls| x 2 <= 8` per call to `paths_after_select_bdy`, and up to 16 per boundary across
the `"h"` call (`:192`) and the `"w"` call (`:196`). Enumerating the loop body over a 4-element
`selected_bdy` gives **12 distinct arrangements** out of the 16 pairs, so the search reaches more
than 4 of the 24 permutations but still not all of them, and never a reversal. `:90` then rejects
the ones that are not circularly connected, and `remove_reflections` (`:201`, and `:95` inside the
inner function) dedupes what survives. Repeated up to 3 times by the retry ladder (`:204`, `:209`,
`:214`).

The conclusion that the search is **not exhaustive over N/E/S/W** survives, but the reason is the
`:90` connectivity filter plus the restricted `target_indices` (`:52-58`), not a rotation-only
enumeration.

For contrast, the **actual** exhaustive cardinal search is elsewhere:
`inputgraph.filter_boundaries_by_cardinal` (`inputgraph.py:1365-1409`), which does try all 8
symmetries of the rectangle:

```
:1400  reflected = [list(reversed(path)) for path in reversed(bdys)]
:1401  for candidate in (bdys, reflected):
:1402      for rot in range(4):
:1403          rotated = candidate[rot:] + candidate[:rot]
:1404          if all(node in rotated[dir_idx] for node, dir_idx in cardinal_constraints):
```
Space: `8 x |cip_list|`, deduped by the `seen` set (`:1390`, `:1405-1408`). And under cardinal
constraints `dim_on_paths_bdy` is deliberately **skipped** (`inputgraph.py:959-966`, `:1045-1051`),
with the stated reason that it "narrows the space and scrambles the N/E/S/W path order".

---

## Section 4 answered: the collapse hypothesis

**Verdict: the code SUPPORTS the observation, and the mechanism is sharper than stated. Two
independent things reuse the collapsed pool, and one of the three "fallback" rungs is a provable
no-op.**

### 1. Pool construction: `path_map.py:102-135`

`outer_rooms` is derived **only** from `bdy_edges` (`:103-109`), not from the room list. `rooms`
(`:128-133`) contains only rooms whose index appears in `bdy_edges`. Built once, before
`attempt_with_threshold` is defined (`:139`), and therefore **shared by all three retry rungs**.

### 2. The filtering step that collapses it: `path_map.py:115-122`

```python
for itr in range(len(room_w)):
    if itr in outer_rooms:
        new_room_w.append(room_w[itr]); new_room_h.append(room_h[itr]); new_indices.append(itr)
room_w = copy.deepcopy(new_room_w)
room_h = copy.deepcopy(new_room_h)
```

If `bdy_edges` is short (or its indexing base disagrees with `room_w`'s), the pool shrinks or
empties. The failure is **silent** because of the `if r in rooms` guards at `:146-147` and `:79-80`:
missing rooms contribute **0**, not an error.

### 3. Why "nothing fits inside the plot": `path_map.py:149-164`

With a collapsed pool, `total_width -> 0`, so:

```
:149  width_diff  = plot_width  - 0 = plot_width
:150  height_diff = plot_height - 0 = plot_height
:163  pointers_w = [... if 0 <= x <= 0.2 * plot_width ]
:164  pointers_h = [... if 0 <= x <= 0.2 * plot_height]
```

`plot_width <= 0.2 * plot_width` is false for any `plot_width > 0`. **Every** path fails the pointer
gate, `width_paths` and `height_paths` stay empty (`:170`, `:187-188`), neither
`paths_after_select_bdy` call fires (`:191`, `:195`), and `sorted_bdys` is empty. This is exactly
"the boundary pool collapses so that nothing fits inside the plot".

### 4. The expand-only fallback: `path_map.py:203-216`

```python
:204  final_sorted_bdys = attempt_with_threshold(0.2, lambda c: c == 4)
:207  if not final_sorted_bdys:
:209      final_sorted_bdys = attempt_with_threshold(0.3, lambda c: c == 4)
:212  if not final_sorted_bdys:
:214      final_sorted_bdys = attempt_with_threshold(0.3, lambda c: c >= 3)
```

Three rungs, each expanding a tolerance (0.2 -> 0.3, then count `== 4` -> `>= 3`). **Nothing is
rebuilt.** `rooms`, `room_w`, `room_h`, `new_indices` and `all_bdy` are all closed over from
`:102-135`; `attempt_with_threshold` takes only `threshold_ratio` and `count_condition` (`:139`).
So all three rungs run against the identical collapsed pool. **The observation is confirmed
verbatim at these lines.**

### 5. The sharper finding: rung 2 cannot help

`threshold_ratio` is threaded into `paths_after_select_bdy` (`:192`, `:196` -> parameter at `:48`)
and used **only** at `:85` and `:87`. The pointer gate at `:163-164` is **hard-coded to `0.2`** and
is not parameterised at all. It runs *before* `paths_after_select_bdy` is ever called.

Therefore, if the pool is collapsed hard enough that `pointers_w` and `pointers_h` are empty for
every boundary, **all three rungs produce the identical empty result** and rungs 2 and 3 are pure
wasted work (plus three full passes of the very chatty `print`s at `:142`, `:152`, `:166-167`,
`:174`, `:177`, `:181`, `:185`, `:188`, `:200`, and `:75`, `:93`). The "expand" in
"expand-only fallback" never reaches the gate that actually rejected everything.

### 6. Two consumers reuse the collapsed result

- `inputgraph.py:978-979` and `:1064-1065`:
  ```python
  if len(selected_list) == 0:
      selected_list = cip_list
  ```
  A **total** collapse is caught here and the full boundary list is restored. A **partial** collapse
  (pool missing some rooms but still yielding some boundaries) is not caught: `selected_list` is
  non-empty but selected against wrong totals, and the good boundaries are gone for good.
- The plot-expansion fallback at `handlers.py:2069-2122` iterates
  `for bdy_itr in range(len(graph.graph_list_by_bdy))` (`handlers.py:2092`) over the **already-built**
  `graph_list_by_bdy`, which was populated from `selected_list` at `inputgraph.py:1013-1014`.
  It does **not** re-run boundary generation, so it re-tries min-dim on exactly the same (possibly
  partial-collapse) set of topologies, only with the plot cap dropped
  (`handlers.py:2120-2121  solve_min_dim(floorplan_data, 0, 0, ...)`).

**Summary of the verdict:** pool construction `path_map.py:102-135`; collapsing filter
`path_map.py:115-122`; the silent zero-contribution that hides it `path_map.py:79-80`, `:146-147`;
the "nothing fits" gate `path_map.py:163-164`; the expand-only fallback `path_map.py:203-216`
(reuses the pool, and its first expansion cannot reach the gate that failed); and the second reuse
of the resulting topology set at `handlers.py:2092-2121`. Supported, with the extra finding that
rung 2 is a no-op in precisely the collapse scenario it was added for.

Two more latent defects found while reading, both in `paths_after_select_bdy`:
- `:66 remaining = [w for w in selected_bdy if w != wall]` removes **all** copies. If two of the four
  paths are equal lists, `remaining` has 2 entries, one slot of `rearr_bdy` stays `None`, and
  `:79 for r in pth` raises `TypeError: 'NoneType' is not iterable`.
- `:199` the `else: print("No combination of walls found ...")` is attached to `if width_paths:`
  (`:195`), not to the height branch, so it fires whenever `width_paths` is empty even if the height
  branch already succeeded. Cosmetic, but the log is misleading during exactly this investigation.

---

## Section 5 answered: the Maximum-Dimension Degradation Ladder

**Only rung 1 is in this file.** The rest is in `handlers.py` and `api.py`. The documented version is
`gplan_backend\docs\floorplans\door_connectivity.md:128-141` (and the summary at
`gplan-building-designer\CLAUDE.md:36`).

| Rung | Where | What is relaxed, exactly |
|---|---|---|
| 0 | `minimum_dimensioning.py:229`, `:311` | Plot cap applied only when `plot_width > 0` / `plot_height > 0`: `edgesX[2*rooms+1][0] = -1 * plot_width`, `edgesY[2*rooms+1][0] = -1 * plot_height`. |
| **1** | **`minimum_dimensioning.py:158-177`** | The caller's per-room ceiling is **widened before the solve**: `ub = min(5 * min, max(supplied_max, 2.5 * min))`. If `supplied` is `None`, unparseable, `<= 0`, or `>= 99999`, it becomes `5 * min` outright (`:169-176`). Applied at `:195`, `:198`; consumed at `:238` (`edgesX[2i][2i-1] = -1 * ub_width[i]`) and `:320` (`edgesY[2i-1][2i] = -1 * ub_len[i]`). |
| 2 | `handlers.py:349-352` | Per-room ceilings **removed entirely** for this topology: `node.pop('max_width', None)`, `node.pop('max_height', None)`, then `min_dim.main` re-run. Reported via the third return value (`:353`) and the warning at `:2202-2203` / `:2650-2651`. |
| 3 | `handlers.py:2069-2121` (and `:2510` in the sibling flow) | **Plot cap only** is dropped: `solve_min_dim(floorplan_data, 0, 0, max_width is not None or max_height is not None)` (`:2120-2121`). Room ceilings still apply and are still released per topology by rung 2. Comment at `:2072-2073` and `:2117-2119` states this explicitly. Warning text at `:2074-2075`. |
| 4 | `api.py:834-836` | Post-solve gap fill **with the exact ceilings enforced**: `_fill_gaps(rects, eps, caps)` (`enforce=True` default, `api.py:710`). Span limit `_span_limit` (`api.py:687`) and area headroom `_headroom` (`api.py:697`, `caps[i][1] - (x1-x0)*(y1-y0)`) applied at `api.py:745-746`, `:756-757`, `:767-768`, `:778-779`. |
| 5 | `api.py:837-847` | If still not gapless, `_fill_gaps(rects, eps, caps, enforce=False)` (`:840`): `limits = caps if enforce else None` (`api.py:729`) so **all span/area ceilings are dropped**, priority ordering by headroom retained. Breach detected by `_exceeds_caps` (`api.py:675`) and reported via `caps_broken` (`:846-847`). |
| 6 | `api.py:856` | `repair_dimensions(rects, _room_bounds(ui, len(rects)))` (`api.py:621`, `:453`) re-solves the coordinate lines against the full min/max band; accepted only if it stays non-overlapping and gapless (`:857-858`). |

Note rung 1 is a **pre-emptive** relaxation, not a retry: it fires on the first solve, unconditionally,
whenever a maximum was supplied. The rationale is recorded in the comment at
`minimum_dimensioning.py:149-154`.

---

## Section 6 answered: `SOLVER_UB_SLACK`, the 99999 sentinel, `plot_width` / `plot_height` in this file

**`SOLVER_UB_SLACK`** - 2 occurrences:
- `:155` definition: `SOLVER_UB_SLACK = float(os.environ.get("GPLAN_SOLVER_UB_SLACK", "2.5"))`.
  Env-overridable. This is the only use of the `os` import (`:3`).
- `:177` sole use: `return min(open_ub, max(value, SOLVER_UB_SLACK * low))` - raises a
  caller-supplied ceiling to at least `2.5 x` that room's minimum, then clamps to `5 x` the minimum.
- (`:147-154` is the block comment explaining why, and `:163` mentions it in the docstring.)

**99999 sentinel** - 2 occurrences:
- `:164` docstring text ("when it is the 99999 'open' sentinel").
- `:175` the only executable use: `if value <= 0 or value >= 99999: return open_ub`, i.e. a supplied
  max of 99999 or more is treated as "no ceiling" and replaced by `5 x min`.
- The same sentinel is recognised outside this file at `handlers.py:329`
  (`if 0 < float(value) < 99999`, inside `get_max_dims`'s `usable`) and produced at
  `api.py:480-481`, `:495`, `:499-501`, `:665`, `:991-993`.

**`plot_width` / `plot_height`** - occurrences in this file:
- `:45-46` module-global declaration, both initialised to `0`.
- `:229` `if plot_width > 0:` guard; `:230` `edgesX[2 * rooms + 1][0] = -1 * plot_width`;
  `:231` `edges_setx.append((2 * rooms + 1, 0))` - installs the X plot cap arc.
- `:311` `if plot_height > 0:` guard; `:312` `edgesY[2 * rooms + 1][0] = -1 * plot_height`;
  `:313` `edges_sety.append((2 * rooms + 1, 0))` - installs the Y plot cap arc.
- `:730` both named in `reinitialize`'s `global` statement; `:751-752` both reset to `0`.
- `:767` both are **parameters of `main`**, shadowing the globals inside that function.
- `:822-823` `globals()['plot_width'] = plot_width` / `globals()['plot_height'] = plot_height` -
  the write that makes the parameters visible to the graph builders.
- The cap is *enforced* (not just installed) at `:495-497` inside `longest_path`:
  `if (2*rooms+1, 0) in edge_set and placement[2*rooms+1] > abs(edge_weights[2*rooms+1][0]): done = False; break`.
  Note this uses the generic `edge_set` / `edge_weights` parameters, so the same code enforces the X
  cap on the X pass and the Y cap on the Y pass.

There is **no** `plot_width`/`plot_height` use in `compute_rot`, `edit_placements` or
`return_output`; the plot only ever acts through that one sink-to-source arc.

## Open Questions

1. **`small_positive` colour polarity.** `minimum_dimensioning.py:257-260` gives red edges `0.1` and
   black edges `2`. `GPLAN\documentation\door_connectivity.md:205` says black = adjacent edge,
   red = non-adjacent edge, which makes those values correct. But `main:782` labels the red set
   `door_connectivity_edges` and `:786` calls them "edges with door connectivity", implying red =
   has a door, which would want the *larger* overlap. One of the two namings is wrong. Which?
2. **`small_positive` leakage across neighbours.** At `:256-260`, `:337-341` and `:615-620` the
   variable is a parameter reassigned in a loop and never reset, so a room whose edge colour is
   missing inherits the previous room's value. Is that intentional (a "last seen wins" heuristic) or
   a bug? It makes the output order-dependent.
3. **`input_adjacency`'s silent `else: adj_type_input = 3`** (`:90-91`). Every non-matching pair
   becomes "below". Should a genuinely non-adjacent pair in `data['edges']` be an error instead?
   The `exit(1)` at `:94` suggests someone once thought so but the guard is unreachable.
4. **Is `edit_placements` (`:695-706`) still wanted?** It shrinks west/south rooms to their minimum,
   guaranteeing a non-gapless plan, which `api._fill_gaps` then has to undo. The two passes may be
   fighting each other; measuring `min_area` before and after with `_fill_gaps` in place would settle it.
5. **`pos_longest_path` never checks the sink.** `is_pushed` has length `2*rooms+1` (`:408`, `:433`),
   so index `2*rooms+1` is out of range and the sink's reachability is never asserted at `:458-461`.
   Deliberate (the sink is checked separately by the plot-cap test at `:495`) or an off-by-one?
6. **`total_neg == 0` returns `False`** (`:469`, `:478`, `:529-531`). Unreachable given the
   `-ub_width[i]` edges, but it means a hypothetical all-non-negative system is reported infeasible
   rather than trivially feasible.
7. **`path_map.py:163-164` hard-codes `0.2`** while the surrounding ladder parameterises the
   threshold. Was the intent for rungs 2 and 3 to widen this gate too? If so, that is a one-line fix
   for the collapse in Section 4.
8. **`path_map.py` indexing base.** `outer_rooms` comes from `bdy_edges`, `room_w` is indexed by
   position. Whether both are 0-based over the same node set (post-dummy-node insertion) is not
   asserted anywhere. If they ever diverge, `:116 if itr in outer_rooms` silently keeps the wrong
   rooms and the collapse in Section 4 becomes systematic rather than occasional.
9. `gplan_backend\GPLAN\...` contains a byte-identical second copy of `path_map.py` and
   `inputgraph.py` (it consumes GPLAN as a submodule). Confirm that only one is on the import path
   before patching either.
