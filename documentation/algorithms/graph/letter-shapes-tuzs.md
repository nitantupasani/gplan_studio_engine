# Letter Shapes T / U / Z / Staircase (non-L generators)

Scope: `tshape.py`, `ushape.py`, `zshape.py`, `staircaseshape.py`.
Every line number below was read or produced by a command in this session.

Absolute paths:

- `C:\Users\nitant\Documents\GPLAN_Revamp\GPLAN\GPLAN\source\lettershape\tshape\tshape.py` (200 lines, 7247 bytes)
- `C:\Users\nitant\Documents\GPLAN_Revamp\GPLAN\GPLAN\source\lettershape\ushape\ushape.py` (212 lines, 7246 bytes)
- `C:\Users\nitant\Documents\GPLAN_Revamp\GPLAN\GPLAN\source\lettershape\zshape\zshape.py` (200 lines, 7281 bytes)
- `C:\Users\nitant\Documents\GPLAN_Revamp\GPLAN\GPLAN\source\staircaseshape\staircaseshape.py` (193 lines, 6918 bytes)

---

## Purpose

These four modules take a triangulated planar input graph (an `InputGraph`) and try to produce a
**non-rectangular rectangular-dual floorplan**: a floorplan whose outer outline is a T, U, Z or
staircase rather than a rectangle. They do it by **adding fake rooms** (dummy exterior vertices) to
the adjacency matrix before the standard 4-completion + REL + dual pipeline, then registering those
fake rooms in `graph.extranodes` so the renderer subtracts them, leaving a notched outline.

The clone-family hypothesis in the task brief is **confirmed**. `zshape.py` is `tshape.py` with
exactly one semantic constant changed. `staircaseshape.py` and `ushape.py` are the same file with a
small structural edit plus (in `ushape.py`) an unrepaired refactor that leaves the module
non-executable.

---

## Where It Sits In The Pipeline

```
POST /api/generate/<shape>            local_engine_bridge.py:159 (local Flask stand-in)
  -> _prepare(data, shape)            local_engine_bridge.py:55, caller=shape at :108
  -> Documents.get_floorplans(...)    api.py:1215
       caller=='tshape'  -> api.py:1272-1274  handle_letter_shape(ui, graph)
       caller=='ushape'  -> api.py:1266-1268  handle_letter_shape(ui, graph)
       caller=='zshape'  -> api.py:1278-1280  handle_letter_shape(ui, graph)
       caller=='staircaseshape' -> api.py:1284-1285 handle_staircase_shaped(ui, graph)
  -> handlers.py:939 handle_letter_shape        [T/U/Z]
  -> handlers.py:1032 handle_staircase_shaped   [staircase]
       -> inputgraph.py:1496 staircaseshaped(graph)
            -> StaircaseShapedFloorplan(graph)  (resolved via `import *`, inputgraph.py:19)
  -> shape module mutates graph.matrix / nodecnt / edgecnt in place
  -> rdg.construct_dual (rdg.py:20) writes graph.room_x/room_y/room_width/room_height
  -> inputgraph.py:1580 get_final_traversal(graph) -> graph.circular_traversal
  -> api.py:1413 ui.get_output_data() -> api.py:1427-1452 Documents/Room/Wall
```

They are **on the standard dual pipeline, not beside it**: they do not compute coordinates
themselves. See Algorithm Walkthrough phase 6 and the Coupling section.

Imports into `handlers.py`:

- `handlers.py:11` `import GPLAN.source.lettershape.tshape.tshape as Tshaped`
- `handlers.py:12` `import GPLAN.source.lettershape.ushape.ushape as Ushaped`
- `handlers.py:13` `import GPLAN.source.lettershape.zshape.zshape as Zshaped`
- `staircaseshape` is not imported by `handlers.py`; it arrives via `inputgraph.py:19`
  (`from GPLAN.source.staircaseshape.staircaseshape import *`).

---

## Entry Points (file:line)

| Entry point | Anchor |
|---|---|
| `TShapedFloorplan(graph)` | `tshape.py:64` |
| `ZShapedFloorplan(graph)` | `zshape.py:64` |
| `UShapedFloorplan(graph)` | `ushape.py:67` |
| `StaircaseShapedFloorplan(graph)` | `staircaseshape.py:65` |
| Caller (T/U/Z) | `handlers.py:947`, `handlers.py:949`, `handlers.py:951` (non-dimensioned branch), `handlers.py:975` (dimensioned branch, see Failure Modes) |
| Caller (staircase) | `handlers.py:1034` -> `inputgraph.py:1497` |
| HTTP dispatch | `api.py:1266`, `api.py:1272`, `api.py:1278`, `api.py:1284` |

---

## Data Structures

Everything is carried on the mutable `InputGraph` object (`inputgraph.py:75`); the shape modules
have no classes and no return values of their own.

| Attribute | Meaning | Set at |
|---|---|---|
| `graph.matrix` | `np.int` adjacency matrix, grown in place | init `inputgraph.py:118`; regrown `tshape.py:20-22` |
| `graph.nodecnt` / `graph.edgecnt` | counters, incremented as dummies and NESW are added | init `inputgraph.py:116-117` |
| `graph.northeast` / `graph.northwest` | indices of the **dummy exterior vertices** (the shape-defining nodes) | `tshape.py:91`, `tshape.py:93` |
| `graph.north/east/south/west` | indices of the 4 outer NESW nodes | `tshape.py:149-156` |
| `graph.bdy_nodes` / `graph.bdy_edges` | boundary of the current matrix | `tshape.py:39` (and recomputed in `find_cips`, `add_NESW`) |
| `graph.cip` | list of 4 boundary paths after corner selection | `tshape.py:175` |
| `graph.extranodes` | rooms to be **erased** from the drawn output | init `inputgraph.py:134`; appended `tshape.py:84-85` |
| `graph.original_node_count`, `graph.node_count_required`, `graph.edge_count_required` | snapshots for rollback that these four modules never use | `tshape.py:90`, `tshape.py:147-148` |
| `graph.room_x/room_y/room_width/room_height` | final coordinates, length `nodecnt-4` | init `inputgraph.py:128-129`; overwritten `tshape.py:86` via `rdg.py:47`, `rdg.py:69-72` |

`paths` (the `path_lister` output, `tshape.py:41`) is a list of boundary arcs; each arc is a list of
node indices, sharing its first and last element with its neighbours.

---

## Algorithm Walkthrough

Described **once**, with `tshape.py` as the canonical copy. Per-shape deltas follow in the table.

**Phase 0 - boundary and CIP discovery.** `find_cips` (`tshape.py:120-127`): triangular cycles
(`opr.get_trngls`), directed graph (`opr.get_directed`), boundary nodes/edges (`opr.get_bdy`),
shortcuts (`sr.get_shortcut`), circular boundary (`opr.ordered_bdy`), then corner-implying paths
(`cip.find_cip`, `cip.py:11`). `cip.find_cip` is fully deterministic (no RNG, `cip.py:11-53`).

**Phase 1 - precondition gate.** `tshape.py:69-70`: `if len(cip) != 6: return "cips not equal to 6"`.
Six CIPs is the structural requirement for a two-notch outline. The returned string is a value, not
an exception (see Failure Modes).

**Phase 2 - cut the boundary into six arcs.** `path_lister` (`tshape.py:36-61`). It takes
`cip[i][1]` for `i in range(6)` as six marker vertices (`tshape.py:44-45`), filters and re-orders
them into boundary order (`tshape.py:46-49`), rotates `ordered_boundary` until it starts at
`centre_cip[0]` (`tshape.py:50-51`), moves that first vertex to the end (`tshape.py:52-54`), then
walks the boundary emitting an arc every time a marker is hit (`tshape.py:56-60`). Result:
`paths[0..5]`, arcs in boundary order.

**Phase 3 - dummy exterior vertex injection. THIS IS THE SHAPE-DEFINING BLOCK.**
`connect` (`tshape.py:89-98`) allocates one new node index per notch
(`graph.northeast = graph.nodecnt; graph.nodecnt += 1`, `tshape.py:91-92`; same for `northwest`,
`tshape.py:93-94`), grows the matrix with `new_matrix` (`tshape.py:18-22`, zero-padded copy), and
then wires **every vertex of the chosen arc** to the dummy via `add_edges1`
(`tshape.py:97`, body at `tshape.py:108-117`). A dummy glued along a whole boundary arc becomes, in
the dual, one rectangle sitting outside the useful rooms; deleting it later carves the notch.

The number of concave (reflex) corners a shape gets is therefore
`(number of dummies) + (number of dummies not pinned to a bounding-box corner)`:
a dummy pinned as a corner of the outer rectangle removes a corner rectangle and yields **1** reflex
corner; a dummy left un-pinned lands mid-side and yields **2**.

**Phase 4 - NESW 4-completion.** `add_NESW` (`tshape.py:139-167`) installs the augmented matrix
(`tshape.py:140`), recomputes the boundary (`tshape.py:141-143`), asks the per-shape corner picker
for exactly 4 boundary paths (`tshape.py:144`), snapshots the counts (`tshape.py:147-148`),
allocates `north/east/south/west` (`tshape.py:149-156`), grows the matrix again (`tshape.py:158`),
wires `cips[0..3]` to N/E/S/W (`tshape.py:160-163`), and closes the outer 4-cycle with
`connect_news` (`tshape.py:165`, body `tshape.py:25-33`).

**Phase 4b - corner pinning. THIS IS THE SECOND SHAPE-DEFINING BLOCK.**
`find_cips_T_shaped` (`tshape.py:170-177`) seeds `corner_points` with the dummy vertices that must
sit at bounding-box corners (`tshape.py:173-174`) before handing off to `boundary_path_single`
(`tshape.py:180-199`), which appends one random vertex from each CIP path (`tshape.py:181-182`),
pads to 4 random boundary vertices if needed (`tshape.py:183-187`), and slices the circular boundary
into four corner-to-corner paths (`tshape.py:194-197`). Which dummies are seeded here is what turns
the same injected topology into a T versus a staircase versus a U.

**Phase 5 - REL.** `get_rel` (`tshape.py:130-136`): `cntr.degrees` -> `cntr.goodnodes` ->
`cntr.contract` -> `exp.basecase` -> `while len(cntrs): exp.expand`. This is a **verbatim copy** of
`InputGraph.irreg_single_dual`'s block at `inputgraph.py:304-312`. `exp.expand` pops from `cntrs`
(`expansion.py:64`), so the loop terminates.

**Phase 6 - dual and hand-back.** `get_floorplan` (`tshape.py:83-86`) appends the dummies to
`graph.extranodes` (`tshape.py:84-85`) and calls `rdg.construct_dual` (`rdg.py:20`), which returns
`[room_x, room_y, room_width, room_height]` (`rdg.py:47-51`), each of length `nodecnt - 4`
(`rdg.py:69-72`, i.e. all user rooms **plus** the dummies, minus NESW). The modules stop here.

### Per-shape delta (only what differs)

| | tshape | zshape | ushape | staircaseshape |
|---|---|---|---|---|
| entry symbol | `TShapedFloorplan` `:64` | `ZShapedFloorplan` `:64` | `UShapedFloorplan` `:67` | `StaircaseShapedFloorplan` `:65` |
| dummies injected | 2: NE `:91`, NW `:93` | 2: NE `:91`, NW `:93` | **1**: NE `:96` | 2, in **two separate matrix growths** `:90` then `:99` |
| arcs the dummies attach to | `paths[0]` `:72`, `paths[2]` `:73` | `paths[0]` `:72`, **`paths[3]`** `:73` | `paths[0]` `:72`, switched to `paths[1]` `:77` | `paths[1]` `:70` (NE), `paths[0] + [NE]` `:73-74` (NW) |
| injection helper | `add_edges1` (2-dummy) `:97` / `:108-117` | `add_edges1` `:97` / `:108-117` | `add_edges1` (1-dummy) `:101` / `:116-120` | `add_edges` twice, `graph.matrix` rebased between at `:72` |
| corner picker | `find_cips_T_shaped` `:170` | `find_cips_Z_shaped` `:170` | `find_cips_U_shaped` `:181` | `find_cips_staircase_shaped` `:164` |
| dummies pinned as corners | NE **and** NW `:173-174` | NE **and** NW `:173-174` | **none** (`corner_points = []` `:183`) | **NE only** `:167` |
| implied reflex corners | 2 | 2 (diagonally opposite arcs) | 2 (one mid-side notch) | 3 (one corner notch + one mid-side notch) |
| `extranodes` registered | NE + NW `:84-85` | NE + NW `:84-85` | NE only `:89` | NE + NW `:83-84` |
| `original_matrix` snapshot | yes `:78` | yes `:78` | no | no |
| helper resolution | qualified (`opr.` / `sr.` / `cntr.` / `exp.` / `news.`) | qualified | **unqualified and undefined** (11 names) | qualified |
| relative-import depth | `...` (3 dots) `:7-14` | `...` `:6-13` | `...` `:7-14` | **`..` (2 dots)** `:8-15` |
| debug `print` statements | none | none | 12 | none |

### Exact diff results

`diff -u tshape.py zshape.py` -> **6 hunks, 8 changed lines**, all cosmetic except one:

- `zshape.py:6` a blank line replaced, `zshape.py:14` a dead comment `# import pythongui.drawing as draw` added
- `zshape.py:64` `def TShapedFloorplan` -> `def ZShapedFloorplan`
- **`zshape.py:73` `path2 = paths[2]` -> `path2 = paths[3]`  (the only semantic change in the whole file)**
- `zshape.py:144` and `zshape.py:170` `find_cips_T_shaped` -> `find_cips_Z_shaped`

`diff -u tshape.py ushape.py` -> 20 hunks. Semantic content: single dummy instead of two
(`ushape.py:94-106`), the always-true retry heuristic (`ushape.py:73-77`), `corner_points` no longer
seeded (`ushape.py:183`), `get_rel` gains an unused `path1` parameter (`ushape.py:136`), no
`original_matrix` snapshot, and **all module-qualified helper calls stripped to bare names**.

`diff -u tshape.py staircaseshape.py` -> 8 hunks. Semantic content: import depth `...` -> `..`
(`staircaseshape.py:8-15`), `connect` split into `connect`/`connect1` with `graph.matrix` rebased
between them (`staircaseshape.py:71-75`, `:88-103`), arcs `paths[1]` and `paths[0]+[NE]`,
`add_edges1` deleted entirely, only NE pinned as a corner (`staircaseshape.py:167`), no
`original_matrix` snapshot.

---

## Invariants And Preconditions

1. **Exactly 6 CIPs.** `tshape.py:69`, `zshape.py:69`, `ushape.py:69`, `staircaseshape.py:67`.
   Violation returns the string `"cips not equal to 6"`; nothing is mutated.
2. **`path_lister` must yield at least as many arcs as the shape indexes.** tshape needs
   `paths[2]` (`tshape.py:73`), zshape needs `paths[3]` (`zshape.py:73`), ushape needs `paths[1]`
   (`ushape.py:77`), staircase needs `paths[1]` (`staircaseshape.py:70`). Not checked.
3. **Every CIP must have at least 2 elements**, since `path_lister` reads `cip[i][1]`
   (`tshape.py:45`). Not checked.
4. **After corner selection there must be at least 4 distinct boundary vertices in
   `corner_points`.** `boundary_path_single` (`tshape.py:183`) pads by *list length*, not by
   distinct count, then indexes `corner_points_index[0..3]` (`tshape.py:194-197`). Not checked.
5. **No CIP handed to `boundary_path_single` may be empty.** `news.find_bdy` strips the first and
   last element of each CIP (`news.py:30-33`), so a 2-element CIP becomes `[]`, and
   `tshape.py:182` calls `randint(0, -1)`. Not checked.
6. **No minimum room count is enforced anywhere in these four files.** The only structural gate is
   the CIP count (item 1). There is no "specific corner room" requirement either; the corner rooms
   are chosen at random inside `boundary_path_single` (`tshape.py:182`, `tshape.py:184-186`), which
   makes these generators **non-deterministic across calls** even for identical input.
7. Coordinates produced by `rdg.construct_dual` have length `nodecnt - 4` (`rdg.py:69-72`), so the
   dummy rooms are present in the coordinate arrays and must be filtered by `graph.extranodes`
   downstream (`pythongui/drawing.py:210`, `:238`, `:262`).

---

## Failure Modes

**F1 - `ushape.py` cannot execute at all: 11 unbound global names.** The module strips the
`opr.` / `sr.` / `cntr.` / `exp.` / `news.` qualifiers but never adds the corresponding
`from ... import *`. Confirmed by static analysis and by running it:

```
>>> import GPLAN.source.lettershape.ushape.ushape as U
>>> U.UShapedFloorplan(g)
NameError: name 'get_trngls' is not defined
```

Unbound names and anchors: `get_trngls` `ushape.py:38`, `:124`, `:150`; `get_directed` `:39`,
`:125`, `:151`; `get_bdy` `:40`, `:126`, `:152`; `ordered_bdy` `:41`, `:128`, `:184`;
`get_shortcut` `:127`; `degrees` `:137`; `contract` `:139`; `basecase` `:140`; `expand` `:142`;
`find_bdy` `:184`. The very first statement of `UShapedFloorplan` (`ushape.py:68` -> `find_cips` ->
`ushape.py:124`) trips it, so **no U-shape floorplan has ever been produced by this file**.

**F2 - `ushape.py:138` is a second, independent crash.** `goodnodes = goodnodes(...)` makes
`goodnodes` a local name, so the call on its own right-hand side is an `UnboundLocalError` even if
F1 were fixed.

**F3 - T / U / Z are unreachable through `api.py`; they crash in the wrapper.**
`api.py:1268`, `:1274`, `:1280` call `handle_letter_shape(ui, graph)` **without** `nodes_data`
and without `gclass`. `handlers.py:941` then does
`nodes_data = nodes_data if nodes_data is not None else gclass.app.nodes_data` with `gclass = None`.
Reproduced end to end through the local bridge:

```
tshape EXC AttributeError: 'NoneType' object has no attribute 'app'
  api.py:1274 -> handlers.py:941
zshape EXC AttributeError: 'NoneType' object has no attribute 'app'
ushape EXC AttributeError: 'NoneType' object has no attribute 'app'
```

Only `caller == 'lshape'` builds `nodes_data` first (`api.py:1259-1262`). `nodes_data` is never used
by the T/U/Z branches of `handle_letter_shape`, so the crash is pure collateral from the L-shape
signature.

**F4 - the `len(cip) != 6` bail-out is silent and produces a fake success.** The returned string is
discarded at `handlers.py:947/949/951` and at `inputgraph.py:1497`. Execution then continues to
`handlers.py:954` / `handlers.py:1036` with `graph.room_x` still at its `np.zeros(nodecnt)` initial
value (`inputgraph.py:128`). Reproduced for staircase through the bridge with an 8-room graph:

```
staircaseshape -> floorplans: 0  msg: 'Generated Staircase shaped floorplan.'
staircase room_x = array([0., 0., 0., 0., 0., 0., 0., 0.])
staircase extranodes = []   nodecnt = 8   final_traversal len = 8
```

`nodecnt` unchanged at 8 and `extranodes` empty prove the early return at `staircaseshape.py:68`
fired; the caller still reported `'Generated Staircase shaped floorplan.'` (`api.py:1286`).

**F5 - `handle_letter_shape` and `handle_staircase_shaped` never publish their result.** Neither
`handlers.py:939-1013` nor `handlers.py:1032-1039` calls `ui._append_output_data`
(`pythongui/GuiParameters.py:389`). `api.py:1413` reads `ui.get_output_data()`
(`GuiParameters.py:384`, backing store initialised to `[]` at `GuiParameters.py:369`), so
`total_fp_count` at `api.py:1418` is 0 and the loop at `api.py:1427` never runs. **Even a fully
successful T/Z/staircase run returns zero floorplans through the API.** Confirmed above:
`staircaseshape -> floorplans: 0`.

**F6 - the dimensioned letter-shape branch is mis-indented.** `handlers.py:968-975`, exact
indentation measured:

```
968  8  if(ui.get_letter() == "L Shape"):
969 12      Lshaped.LShapedFloorplan(graph, gclass.app.nodes_data)
970  8  # elif(ui.get_letter() == "T Shape"):
971  8  #     Tshaped.TShapedFloorplan(graph)
972  8  # elif(ui.get_letter() == "Z Shape"):
973  8  #     Zshaped.ZShapedFloorplan(graph)
974  8  # elif(ui.get_letter() == "U Shape"):
975 12      Ushaped.UShapedFloorplan(graph)
```

Line 975 sits inside the **L Shape** branch. A dimensioned L-shape request therefore runs
`LShapedFloorplan` and then falls straight into `UShapedFloorplan`, hitting F1. Dimensioned T, Z and
U requests execute no shape code at all and fall through to `handlers.py:976`.

**F7 - `ushape.py`'s retry heuristic is a no-op that always fires.** `ushape.py:73-75` deep-copies
the graph, calls `connect(dummy_graph, path1)` and throws the returned matrix away. `connect`
(`ushape.py:94-106`) never assigns `dummy_graph.matrix`, so `find_cips(dummy_graph)` at
`ushape.py:75` re-evaluates the **unaugmented** graph, which the gate at `ushape.py:69` already
forced to have exactly 6 CIPs. Since `cip.find_cip` has no randomness (`cip.py:11-53`),
`len(newcips) > 4` at `ushape.py:76` is unconditionally true and `path1` is always replaced by
`paths[1]`. The `paths[0]` value at `ushape.py:72` is dead.

**F8 - `graph.cip` is computed against the wrong matrix and then discarded.**
`tshape.py:75` / `zshape.py:75` / `staircaseshape.py:76` assign `graph.cip = find_cips(graph)`.
In tshape and zshape, `connect` (`tshape.py:89-98`) never assigns `graph.matrix`, so this reads the
**pre-injection** matrix. In all three it is overwritten a moment later inside the corner picker
(`tshape.py:175`, `staircaseshape.py:168`). Dead work in every case.

**F9 - `staircaseshape.py:74` mutates its input.** `path2 = paths[0]` is a reference, and
`path2.append(graph.northeast)` extends `paths[0]` in place. Harmless today because `paths` is not
read again, but it is a trap for anyone adding a retry loop.

**F10 - `staircaseshape.py:98` clobbers `graph.original_node_count`** with the post-NE count,
overwriting the value `connect` set at `staircaseshape.py:89`. Nothing in these four modules reads
it, so it is currently inert.

**F11 - `api.py` leaves `print` permanently disabled on exception.** `builtins.print` is replaced at
`api.py:1222` and restored only at `api.py:1454`, after the success path. Any of F1/F3 leaves the
whole process silent. This is what hides F3 from the console.

---

## Coupling (what breaks if you change this)

- **`opr.get_trngls` / `get_directed` / `get_bdy` / `ordered_bdy`** (`operations.py:71`, `:59`,
  `:85`, `:238`) - called from `tshape.py:37-40`, `:65-67`, `:121-125`, `:141-143`, `:175`
  (and `zshape.py` / `staircaseshape.py` at the same offsets). Signature change breaks all four
  copies plus `Lshaped.py` plus `inputgraph.py`.
- **`cip.find_cip`** (`cip.py:11`) - `tshape.py:126`. Changing the CIP shape breaks the
  `len(cip) != 6` gate and `path_lister`'s `cip[i][1]` indexing (`tshape.py:45`).
- **`sr.get_shortcut`** (`shortcutresolver.py:14`) - `tshape.py:124`.
- **`news.find_bdy`** (`news.py:21`) - `tshape.py:175`. If it can return an empty path, invariant 5
  breaks.
- **`cntr.degrees` / `goodnodes` / `contract`** (`contraction.py:23`, `:35`, `:187`) and
  **`exp.basecase` / `expand`** (`expansion.py:29`, `:53`) - `tshape.py:131-136`. The 3-arg
  `contract(matrix, goodnodes, degrees)` -> 4-tuple contract is already assumed here.
- **`rdg.construct_dual`** (`rdg.py:20`) - `tshape.py:86`. The `nodecnt - 4` array length
  (`rdg.py:69-72`) is baked into `get_final_traversal` (`inputgraph.py:1586`).
- **`graph.extranodes` contract** - written at `tshape.py:84-85`, consumed at
  `pythongui/drawing.py:210`, `:238`, `:262`, `handlers.py:467`, `handlers.py:1103`,
  `operations.py:260`. If a shape stops registering its dummies, the fake rooms render as real ones.
- **`inputgraph.py:16-19` star imports.** These four `import *` statements dump ~11 helper names
  (`new_matrix`, `connect_news`, `path_lister`, `get_floorplan`, `connect`, `add_edges`,
  `find_cips`, `get_rel`, `add_NESW`, `boundary_path_single`) plus `graph`, `FALSE`, `TRUE`,
  `core_number` into `inputgraph`'s namespace. `staircaseshape` (line 19) wins every collision.
  `inputgraph.py` defines no top-level function with any of those names (its top-level defs are at
  `:65, :1365, :1412, :1453, :1496, :1502, :1512, :1535, :1554, :1572, :1580`), so nothing of
  `inputgraph`'s own is currently shadowed, but adding a top-level `def find_cips` to `inputgraph.py`
  would silently take over from the star import, or vice versa.
- **`handlers.py:1002` `graph.nodecnt -= 4`** compensates for the NESW nodes added at
  `tshape.py:149-156`. Only present in the dimensioned branch, which is broken (F6).

---

## Dead Or Duplicated Code

**Duplication (stated plainly): these are four hand-copied forks of one algorithm, and a fifth
drifted fork lives in `Lshaped.py`.** The following functions exist as near-identical copies in
`tshape.py`, `ushape.py`, `zshape.py`, `staircaseshape.py` **and** `lettershape/lshape/Lshaped.py`:

| function | tshape | ushape | zshape | staircase | Lshaped |
|---|---|---|---|---|---|
| `new_matrix` | `:18` | `:19` | `:18` | `:19` | `:462` |
| `connect_news` | `:25` | `:26` | `:25` | `:26` | `:631` |
| `add_edges` | `:101` | `:109` | `:101` | `:106` | `:454` |
| `find_cips` | `:120` | `:123` | `:120` | `:113` | `:236` |
| `get_rel` | `:130` | `:136` | `:130` | `:124` | `:498` |
| `get_floorplan` | `:83` | `:88` | `:83` | `:82` | `:531` |
| `add_NESW` | `:139` | `:148` | `:139` | `:133` | `:541` |
| `boundary_path_single` | `:180` | `:189` | `:180` | `:173` | `:470` |
| `path_lister` | `:36` | `:37` | `:36` | `:37` | (absent) |

- `get_rel` in `tshape.py:130-136`, `zshape.py:130-136`, `staircaseshape.py:124-130` is a
  **verbatim copy of pipeline logic** from `InputGraph.irreg_single_dual` (`inputgraph.py:304-312`).
- `boundary_path_single` (`tshape.py:180-199`) is a **verbatim copy of `news.bdy_path`**
  (`news.py:35-65`) with the trailing list build inlined.
- The duplication has already drifted out of sync: `Lshaped.get_rel` at `Lshaped.py:505` calls
  `cntr.contract(graph.matrix, goodnodes)` with 2 arguments and unpacks 2 return values, but
  `contraction.py:187` is `def contract(matrix, goodnodes, degrees)` returning 4. The L copy is stale
  against the API that the T/Z/staircase copies use correctly.

**Dead code inside the four files:**

- `ushape.py:116-120` `add_edges1` is byte-for-byte behaviourally identical to `add_edges` at
  `ushape.py:109-113`. Pure duplicate.
- `ushape.py:72` `path1 = paths[0]` is always overwritten (F7).
- `tshape.py:75`, `zshape.py:75`, `staircaseshape.py:76` `graph.cip = find_cips(graph)` - result
  always overwritten (F8).
- `tshape.py:78` / `zshape.py:78` `graph.original_matrix = copy.deepcopy(...)` - `original_matrix` is
  written nowhere else and read nowhere in `source/`, `handlers.py` or `api.py` (grep confirmed;
  `Lshaped.py:132/:184` uses an unrelated *local* variable of the same name).
- `staircaseshape.py:16` `import copy` - `copy` is never used in that file.
- `from pickle import FALSE, TRUE` (line 1 of all four), `from networkx.algorithms.core import
  core_number` (line 4), `from networkx.classes import graph` (line 5) - none are referenced.
  The `graph` import additionally shadows nothing only by luck, since every function parameter is
  also named `graph`.
- `ushape.py:6` and `zshape.py:14` / `ushape.py:15` are commented-out imports left behind by the
  copy (`# from LShaped import connect_news, new_matrix`, `# import pythongui.drawing as draw`).
- `ushape.py:136` `get_rel(graph, path1)` takes `path1` and never uses it (copied from
  `Lshaped.py:498`, where it is used at `Lshaped.py:523`).
- 12 stray debug `print` calls in `ushape.py` (`:56`, `:59`, `:81`, `:90`, `:103-104`, `:131-132`,
  `:144-145`, `:176-177`, `:199`, `:202-203`), including `print("sdfasdfsafaew", ...)` at
  `ushape.py:81`.
- `inputgraph.py:1485-1494` is a commented-out `lettershape(graph, node_data, letter)` dispatcher.
  The live `staircaseshaped` at `inputgraph.py:1496-1497` is a **one-line pass-through** to
  `StaircaseShapedFloorplan`; it is unrelated to any staircase logic of its own. It resolves the
  symbol only because of the star import at `inputgraph.py:19`.

**Reachability verdict per module:**

| module | verdict |
|---|---|
| `tshape.py` | **Reachable from `handlers.py:947` only via the GUI path** (`gclass` non-None). Via `api.py:1272` it is **DEAD**: the call crashes at `handlers.py:941` before any shape code runs (F3). Dimensioned path: **DEAD**, commented out at `handlers.py:970-971`. |
| `zshape.py` | Same as `tshape.py`. `handlers.py:949` GUI-only; `api.py:1278` **DEAD** (F3); dimensioned **DEAD** (`handlers.py:972-973`). |
| `ushape.py` | **DEAD everywhere.** It cannot run: `NameError` on the first call (F1). `api.py:1266` also hits F3 first. The only uncommented dimensioned call site, `handlers.py:975`, is mis-indented into the L-Shape branch (F6). |
| `staircaseshape.py` | **Reachable** from `api.py:1284` -> `handlers.py:1034` -> `inputgraph.py:1497`. It executes. But `handle_staircase_shaped` never publishes output (F5), so the endpoint returns 0 floorplans regardless. Effectively dead output-wise. |
| `inputgraph.py:1496 staircaseshaped` | **Not unrelated.** It calls `StaircaseShapedFloorplan` from `staircaseshape.py` (via the star import at `inputgraph.py:19`) and is the sole caller. |

---

## Open Questions

1. **Did T/Z ever work through the HTTP API?** F3 makes them unreachable today and F5 would return
   an empty document even if F3 were fixed. Whether these ever worked, or only in the tkinter GUI
   with a live `gclass`, is not answerable from the code alone.
2. **Is `handlers.py:975` a typo or an intentional chained call?** The indentation says
   `LShapedFloorplan` then `UShapedFloorplan` for dimensioned L requests. Given F1 that path always
   raises, so the intent cannot be inferred from behaviour.
3. **Is the reflex-corner count in the delta table the designed intent?** It is derived from the
   dummy count plus corner-pinning, not from a comment or spec. In particular staircase pins only NE
   (`staircaseshape.py:167`) while T and Z pin both (`tshape.py:173-174`), and U pins none
   (`ushape.py:183`); no comment in any file states the geometric target.
4. **Why does `ushape.py` alone use bare helper names?** It looks like an abandoned
   `from ... import *` refactor. No git history is available in this working tree (`Is directory a
   git repo: No`), so the change cannot be dated or attributed.
5. **Knowledge-graph disagreements (code wins):**
   - `graphify path "handlers.py" "tshape.py"` returns a 4-hop indirect route through
     `operations.py`; the graph has **no direct import edge** for the literal
     `import ... tshape as Tshaped` at `handlers.py:11`. Graph gap.
   - `graphify explain "ushape.py"` reports `imports_from -> operations.py` etc. These import edges
     are recorded, but `ushape.py` never uses the resulting aliases (F1). The graph models the import
     statement, not the broken name resolution, so it makes `ushape.py` look live when it is not.
   - `graphify explain "ushape"` resolves to `ushape/__init__.py` with degree 0, not to the module,
     which makes label-based queries misleading here.
6. **Does the production backend (`gplan_backend/GPLAN/...`) differ?** Grep shows identical line
   numbers for every anchor (`handlers.py:11-13/947/949/951/975/1034`, `api.py:1266-1285`,
   `inputgraph.py:16-19/1496`), so it appears to be the same submodule content, but that copy was
   not read line by line in this session.
