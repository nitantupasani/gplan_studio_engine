# Dossier: `source/` circulation package (`source/circulation/circulation.py`, `source/multiple_circ.py`, `source/path_map.py`)

Scope: the three files under `C:\Users\nitant\Documents\GPLAN_Revamp\GPLAN\GPLAN\source\`. The near-namesake `GPLAN\GPLAN\circulation.py` (repo root of the package) is owned by a sibling task and is NOT documented here beyond recording which module each caller imports.

All line anchors below were read in this session. Paths are absolute unless the file is named in a section header.

---

## Purpose

`source\circulation\circulation.py` is a self-contained, standalone-runnable implementation of the "spanning circulation" (corridor insertion) algorithm: it takes a room adjacency graph plus a rectangular floorplan (RFP) whose rooms already carry `(top_left, bottom_right)` coordinates, inserts corridor vertices into the graph, and then widens the seams between corridor-joined rooms by physically shifting existing room rectangle edges. It has a `main()` / `if __name__ == "__main__"` driver (`source\circulation\circulation.py:588`, `:871`) and no importers.

`source\multiple_circ.py` is an attempt to enumerate *several* circulations for one graph by branching on the order in which triangular faces are subdivided (fixed entry edge) or by varying the entry edge. It is also standalone-driven (`source\multiple_circ.py:248`, `:307`) and has no importers.

`source\path_map.py`, despite its name, has nothing to do with corridors. It is a **boundary-path dimension pre-selector**: given candidate 4-wall boundary decompositions of the outer room cycle (CIP lists) and per-room width/height plus plot width/height, it filters and de-duplicates the boundaries whose wall room-sums come within a tolerance of the plot dimensions. It is the only one of the three that is live.

The word "path" in `path_map.py` means "one wall of the boundary rectangle, expressed as an ordered list of room ids", not "corridor route". No corridor, corridor vertex, or corridor thickness appears anywhere in the file (whole file read, 221 lines).

---

## Where It Sits In The Pipeline

### `source\path_map.py`: live, on the door-connectivity / multiple-floorplan path

Full caller chain, every hop anchored:

1. `GPLAN\GPLAN\api.py:13` -> `from GPLAN.handlers import *` (this is how `api.py` reaches handlers; `api.py` contains no other handlers import).
2. `GPLAN\GPLAN\api.py:1309`, `:1353`, `:1390` -> `handle_door_connectivity(ui, graph)` / `handle_door_connectivity(ui, retry_graph)`, inside `get_floorplans` (`api.py:1215`).
3. `GPLAN\GPLAN\handlers.py:1686` -> `def handle_door_connectivity(ui, graph, drawGUI = False, gclass = None)`.
4. `GPLAN\GPLAN\handlers.py:1830`, `:1836`, `:1838`, `:2268` -> `graph.irreg_multiple_dual(input_dims)`. `input_dims` is built at `handlers.py:1810` and `:2262` as `[min_width, min_height, plot_width, plot_height]` and emptied at `handlers.py:1813` / `:2265` when `plot_width == 0 and plot_height == 0`. These are the only `irreg_multiple_dual` call sites in the package that pass `input_dims`; the other 23 call sites pass nothing.
5. `GPLAN\GPLAN\source\inputgraph.py:20` -> `from GPLAN.source.path_map import *` (star import; this is the only import of `path_map` anywhere in the tree).
6. `GPLAN\GPLAN\source\inputgraph.py:852` -> `def irreg_multiple_dual(self, input_dims = [])`; inside it, `GPLAN\GPLAN\source\inputgraph.py:972` and `GPLAN\GPLAN\source\inputgraph.py:1057` both call `dim_on_paths_bdy(cip_list, room_width, room_height, plot_width, plot_height, bdy_edges)`.
7. `GPLAN\GPLAN\source\path_map.py:99` -> `def dim_on_paths_bdy(...)`.

Guarded off in two ways: the `elif( len(input_dims) > 0):` branch at `inputgraph.py:967` / `:1052`, and, when `self.cardinal_constraints` is set, `selected_list = cip_list` is used instead (`inputgraph.py:966` with the explanatory comment at `:959-965`; second copy `inputgraph.py:1051` with comment at `:1045-1050`). If `dim_on_paths_bdy` returns an empty list the caller reverts to the unfiltered `cip_list` (`inputgraph.py:978-979`, `:1064-1065`), so `path_map` is a *narrowing optimisation*, never a hard gate.

### `source\circulation\circulation.py` and `source\multiple_circ.py`: not reachable from `handlers.py` or `api.py`

A tree-wide grep for `source.circulation`, `from ... source import circulation`, and `circulation.circulation` over every `*.py` in `C:\Users\nitant\Documents\GPLAN_Revamp` returned **zero** hits. Nothing imports `GPLAN.source.circulation`.

`source\multiple_circ.py` likewise has no importers (grep for `multiple_circ` across all `*.py` matched only its own definition file and the unrelated attribute `self.multiple_circ` inside the two circulation modules).

The live circulation module is the root one. Record of what each caller imports, as requested:

| Caller | Import line (anchored) | Which module |
|---|---|---|
| `GPLAN\GPLAN\handlers.py` | `handlers.py:31` -> `import GPLAN.circulation as cir` | **root** `GPLAN\GPLAN\circulation.py` |
| `GPLAN\GPLAN\api.py` | no circulation import; only `api.py:13` -> `from GPLAN.handlers import *` | inherits `cir` from handlers |
| `GPLAN\custom_circ_entry.py` | `custom_circ_entry.py:9` -> `import GPLAN.GPLAN.circulation as circulation` | **root** `GPLAN\GPLAN\circulation.py` |
| `GPLAN\GPLAN\source\multiple_circ.py` | `multiple_circ.py:10` -> `import circulation` | bare, unqualified; unresolvable when the file is imported as `GPLAN.source.multiple_circ` (see Failure Modes) |
| `GPLAN\GPLAN\source\inputgraph.py` | `inputgraph.py:20` -> `from GPLAN.source.path_map import *` | `path_map` only, no circulation |

`handlers.py` uses `cir.circulation(...)` at `handlers.py:104` and `cir.plot(...)` at `handlers.py:117`. Independent proof that `handlers.py:104` cannot be the `source` class: the call is `cir.circulation(g, ui.get_corridor_thickness(), rfp, gclass.rem)` (4 positional args), whereas `source\circulation\circulation.py:53` is `def __init__(self, graph: nx.Graph, rfp: RFP = None)` (2). Further, the attributes `handlers.py` reads off the object do not exist in the source class at all: `is_dimensioning_successful` (`handlers.py:299`), `room_area` (`handlers.py:261`), `dimensions` (`handlers.py:235`), `is_minimum_dimensioned` (`handlers.py:111`), `dimension_constraints` (`handlers.py:109`), `is_optimal` (`handlers.py:113`) all have **zero** occurrences in `source\circulation\circulation.py`, and `remove_corridor` (`handlers.py:160`, `:226`) occurs there only inside the commented-out line `source\circulation\circulation.py:557`.

One dangling reference worth flagging for the sibling task: `handlers.py:62` calls `circulation.BFS(dis, gclass.e1.get(), gclass.e2.get())` using a bare name `circulation`, which is bound nowhere in `handlers.py` (the only alias is `cir`, `handlers.py:31`; `handlers.py` has no star imports). Its enclosing function `make_dissection_corridor` (`handlers.py:58`) IS called: `GPLAN\main.py:20` invokes `make_dissection_corridor(gclass)` inside the `if (gclass.command == "dissection"):` branch of `run()` (`main.py:13`, `:19`), and the name resolves there through the star import at `main.py:6` (`from GPLAN.handlers import *`). The `NameError` at `handlers.py:62` is therefore reachable, not dead. `BFS` also has zero occurrences in `source\circulation\circulation.py`, so this reference is not to the source module either.

---

## Entry Points (file:line)

### `source\circulation\circulation.py` (34,828 bytes, 873 lines)

| Symbol | Line |
|---|---|
| `class Point` / `__init__` | 14 / 15 |
| `class Edge` / `__init__` | 19 / 20 |
| `class Room` / `__init__` | 25 / 26 |
| `class RFP` / `__init__` | 44 / 45 |
| `class circulation` | 52 |
| `circulation.__init__` | 53 |
| `circulation.is_subgraph` | 72 |
| `circulation.multiple_circulation_fixed_entry` | 81 |
| `circulation.multiple_circulation` | 143 |
| `circulation.circulation_algorithm` | 197 |
| `circulation.corridor_boundary_rooms` | 264 |
| `circulation.adjust_RFP_to_circulation` | 281 |
| `circulation.add_corridor_between_2_rooms` | 315 |
| `circulation.find_common_edges` | 378 |
| `circulation.find_common_neighbors` | 411 |
| `circulation.calculate_edge_move` | 511 |
| `circulation.push_edges` | 550 |
| `plot` (module level) | 571 |
| `main` | 588 |
| nested `make_graph` | 589 |
| nested `test_circ` | 600 |
| nested `test_comm_edges` | 640 |
| nested `test_comm_neighbors` | 713 |
| nested `test_move_edges` | 748 |
| nested `test_adjust_RFP_to_circ` | 790 |
| nested `test_multiple_circulation` | 838 |
| `if __name__ == "__main__"` | 871 |

Real entry point for a consumer: `circulation.circulation_algorithm(v1, v2)` (`:197`) followed by `circulation.adjust_RFP_to_circulation()` (`:281`). That is exactly the sequence the file's own test driver uses at `:826-827`.

### `source\multiple_circ.py` (11,457 bytes, 308 lines)

| Symbol | Line |
|---|---|
| `class multiple_circ` | 12 |
| `multiple_circ.__init__` | 14 |
| `multiple_circ.multiple_circulation_fixed_entry` | 25 |
| `multiple_circ.multiple_circulation` | 98 |
| `find_exterior_edges` (module level, but takes `self`) | 140 |
| `is_subgraph` (module level) | 164 |
| `wheel_graph` | 183 |
| `complete_graph` | 210 |
| `plot` | 230 |
| `main` | 248 |
| nested `test_is_subgraph` | 251 |
| nested `test_multiple_circulation` | 278 |
| `if __name__ == "__main__"` | 307 |

### `source\path_map.py` (8,600 bytes, 221 lines)

| Symbol | Line |
|---|---|
| `labels` | 5 |
| `is_reflections` | 12 |
| `remove_reflections` | 28 |
| `is_circularly_connected` | 36 |
| `paths_after_select_bdy` | 48 |
| `dim_on_paths_bdy` (the only externally-called symbol) | 99 |
| nested `attempt_with_threshold` | 139 |

---

## Data Structures

### `Room` (`source\circulation\circulation.py:25-41`)

Fields set in `__init__`: `id`, `top_left_x`, `top_left_y`, `bottom_right_x`, `bottom_right_y` (`:29-32`), derived `height = abs(br_y - tl_y)` and `width = abs(br_x - tl_x)` (`:33-34`), four accumulators `rel_push_T/B/L/R` initialised to 0 (`:35-38`), and a dict `target = {'T':0,'B':0,'L':0,'R':0}` (`:41`).

Coordinate convention, inferred from the test fixtures at `:606-624`: `top_left_y > bottom_right_y` (y increases upward), `top_left_x < bottom_right_x`. Room 1 there is `tl=(0,30), br=(10,0)`.

`rel_push_*` is the *signed displacement* applied to that one edge; `target` is a separate, per-corridor-pair record used only for the two rooms directly flanking a corridor.

### `RFP` (`:44-47`)

Two fields: `graph` (nx.Graph) and `rooms` (a `list[Room]`). Rooms are addressed positionally by graph node id throughout: `self.RFP.rooms[room1]` (`:295`), `self.RFP.rooms[neighbor_room_id]` (`:460`), `self.RFP.rooms[each_tuple[0]]` (`:374`), `self.RFP.rooms[room.id]` (`:521`).

### `circulation` state (`:53-70`)

- `self.graph`: the original room adjacency graph, never mutated (`circulation_algorithm` works on a `deepcopy`, `:205`).
- `self.circulation_graph`: the augmented graph with corridor vertices, assigned at `:258`.
- `self.adjacency`: `{corridor_vertex_id: [room_a, room_b]}`, assigned at `:259`.
- `self.corridor_thickness = 0.1`, a hardcoded literal (`:60`). There is no constructor parameter and no setter in this file.
- `self.temp_push_states`: list of *lists of 6-tuples*, `(room_id_a, dir_a, edge_a, room_id_b, dir_b, edge_b)`. Semantics documented at `:427-428`: `(room1.id,"S","T",room2.id,"N","B")` means push room1's Top edge South and room2's Bottom edge North.
- `self.multiple_circ`, `self.circulations_adjacency_list`, `self.exterior_edges`, `self.pushed_stack`, `self.count_of_multi_circ` (`:61-70`): all belong to the broken `multiple_circulation*` half of the class (see Dead Or Duplicated Code).

### `find_common_edges` return tuple (`:378-409`)

5-tuple `(x_left, y_left, x_right, y_right, (room1.id, direction))` where `direction in {"N","S","E","W","Null"}`, direction taken **with respect to room1**. Default when the rooms share no exact coordinate boundary: `(0,0,0,0,(room1.id,"Null"))` (`:390`).

### `path_map` structures

`dim_on_paths_bdy(all_bdy, room_w, room_h, plot_width, plot_height, bdy_edges)` (`:99`):
- `bdy_edges`: list of 2-element room-id pairs describing boundary edges; flattened into `outer_rooms` at `:102-109`.
- `room_w`, `room_h`: full per-room dimension lists, filtered down to boundary rooms at `:115-120` and re-indexed into a dict `rooms = {room_id: {'width': w, 'height': h}}` at `:128-133`.
- `all_bdy`: list of boundaries; each boundary is a list of paths; each path is a list of room ids (`:145-147` sums `rooms[r]['width'] for r in path`).
- Return value: `remove_reflections(sorted_bdys)` (`:201`, returned via `:204`/`:209`/`:214`/`:216`) - a list of **4-element lists**, each element a wall path (list of room ids), reflection-deduplicated.

`labels` (`:5-10`) tags even-index walls `"w"` and odd-index `"h"`; `is_reflections` (`:12-26`) declares two boundaries reflections when their wall sets and w/h labels coincide.

---

## Algorithm Walkthrough

### Q1: the core corridor algorithm does BOTH, in two clearly separated stages

**Stage 1, graph-level: insert a corridor vertex on selected edges of the room adjacency graph.** `circulation_algorithm` (`:197`) copies the graph (`:205`), records `n = m = len(graph)` (`:208-209`), seeds a queue with the 0-indexed entry edge `s = (v1-1, v2-1, -1)` (`:210`, `:217`), and then in the main loop, for a face `(s[0], s[1])` and a common neighbour `ne`:
```
graph.add_edge(s[0], n)      # :225
graph.add_edge(s[1], n)      # :226
graph.remove_edge(s[0],s[1]) # :228  <-- the edge is SUBDIVIDED
graph.add_edge(n, s[2])      # :236, only if s[2] > 0 (link to parent corridor)
graph.add_edge(n, ne)        # :237
n += 1                       # :238
```
That is textbook edge subdivision: the room-room edge is deleted and a new vertex `n` is spliced in, plus a spoke to the third vertex of the triangle and a spoke to the parent corridor vertex.

**Stage 2, geometry: it does NOT re-derive geometry from the augmented graph.** `adjust_RFP_to_circulation` (`:281`) walks the corridor vertices and mutates the pre-existing rectangles in place. The only geometric write in the whole file is `push_edges` (`:550-555`):
```
room.top_left_y     += room.rel_push_T
room.top_left_x     += room.rel_push_L
room.bottom_right_y += room.rel_push_B
room.bottom_right_x += room.rel_push_R
```
There is no call to any rectangular-dual / REL / floorplan generator anywhere in the file. So: the graph is subdivided to decide *which room pairs get a corridor*, and then corridors are carved into the existing rectangle coordinates by shifting room edges. Corridors are never emitted as rectangles of their own in this file: they exist only as the gaps left behind by the pushes.

### Q2: which rooms get connected, and what structure guides the route

Routing loop, anchored: `while (queue):` at `source\circulation\circulation.py:220`, `s = queue.pop(0)` at `:222`, expansion `for ne in list(nx.common_neighbors(graph, s[0], s[1]))` at `:223`, re-enqueue of the two child faces at `:242-243`:
```
queue.append((ne, s[0], n-1))
queue.append((ne, s[1], n-1))
```
`pop(0)` plus `append` is a FIFO, so this is **breadth-first**, but the BFS runs over the *triangular faces* of the planar room graph, not over rooms and not over a precomputed spanning tree. There is no `nx.bfs_tree`, `nx.minimum_spanning_tree`, or `nx.shortest_path` call in the file.

The corridor vertices themselves form a **tree rooted at the entry edge**: each new corridor vertex `n` is linked to its parent `s[2]` at `:234-236`, and `s[2]` is set to `n-1` for both children at `:242-243`. The root's parent sentinel is `-1` (`:210`), suppressed by the `if s[2] > 0` guard.

There is **no entry room**: the entry is an exterior **edge**, a pair of room ids `(v1, v2)` defaulting to `(1, 2)` and converted to 0-indexed at `:210`. Coverage is "every room reachable by triangular-face adjacency from that entry edge", not an explicit all-rooms guarantee: the guard `if ne < m:` at `:224` restricts expansion to original room vertices (`m` is frozen at the pre-corridor vertex count, `:209`), which prevents the recursion from subdividing corridor-to-corridor edges. `multiple_circ.py:1` calls the result a "spanning circulation", and the topology (a tree of corridor vertices touching each visited face) is consistent with that claim, but the code contains no assertion or check that every room was reached.

Bookkeeping: `adjacency[corridor_counter] = [s[0], s[1]]` (`:240`) records the room pair per corridor in insertion order; keys are then rewritten to the actual vertex ids `m, m+1, ...` at `:246-249` via `dict(zip(corridor_vertices, list(adjacency.values())))`. The key renumbering is what lets `adjust_RFP_to_circulation` iterate `range(len(self.graph), len(self.circulation_graph))` at `:292`.

### Q3: how thickness is applied geometrically

Thickness is `self.corridor_thickness = 0.1` (`:60`), and it is always applied as **half on each side**.

1. `adjust_RFP_to_circulation` (`:281`) loops corridor vertices `:292`, resolves the flanking rooms via `corridor_boundary_rooms` (`:264`, a dict lookup at `:277`), and calls `add_corridor_between_2_rooms` (`:295`).
2. `add_corridor_between_2_rooms` (`:315`) finds the shared boundary with `find_common_edges` (`:327`) and then, per direction, records both the push-state tuple and the `target` value. For the "room2 is north of room1" case (`:330-337`):
   - `room1.target['T'] = -0.5 * corridor_thickness` (`:334`), i.e. room1's top edge moves **down**.
   - `room2.target['B'] = +0.5 * corridor_thickness` (`:337`), i.e. room2's bottom edge moves **up**.
   The three other cases at `:339-364` are the S / E / W mirrors, with the same `±0.5 * thickness` magnitudes. Net gap between the two rooms = `corridor_thickness`.
3. **Preserving the adjacencies it must not break** is the job of `find_common_neighbors` (`:411`), called at `:367`. It computes the corridor axis first: if the common edge is horizontal (`common_edge[1] == common_edge[3]`) `orientation='x'`, if vertical (`common_edge[0] == common_edge[2]`) `orientation='y'` (`:438-447`). Then for every `nx.common_neighbors(self.graph, room1.id, room2.id)` (`:456`) it checks whether that neighbour touches room1 or room2 **along the corridor axis** (`:467-484`), and if so emits a push tuple that moves the neighbour's edge in the *same* direction as the room it abuts. Example `:468`: `(room.id, "N", "T", room1.id, "N", "B")`. That is what extends the corridor band sideways instead of tearing the wall: the neighbour follows the room it is attached to. It then recurses along both chains, `:501-503` for room1's side and `:507-509` for room2's side, with `last_visited` (`:457`) preventing immediate backtracking.
4. `calculate_edge_move` (`:511`) turns each tuple into an accumulator update, and this is where **repeated corridors do not compound**. Every branch clamps rather than adds. `:525`:
   ```
   room_obj.rel_push_R = max(room_obj.rel_push_R, 0.5*thickness) if room_obj.rel_push_R >= 0 else room_obj.rel_push_R
   ```
   Eastward pushes take `max` against `+0.5*t`, westward pushes take `min` against `-0.5*t`, and a sign already opposite to the requested direction is left untouched. So an edge can be displaced by at most `±0.5 * corridor_thickness` no matter how many corridors demand it, and a "first push wins the sign" rule applies.
5. `adjust_RFP_to_circulation` then overrides the accumulators with the `target` values for the directly-flanking rooms (`:299-310`) - the `target` write is unconditional and beats whatever `calculate_edge_move` computed, whenever `target != 0`.
6. Finally `push_edges` (`:550`) is applied once per room (`:312-313`), committing the four accumulators to the four coordinates.

Summary of who moves: the two corridor-flanking rooms move by `0.5 * thickness` each, away from each other; every room chained to them **along the corridor axis** moves by `0.5 * thickness` in the same direction as its anchor; all other rooms are untouched.

### Q4: `multiple_circ.py`, what is varied and the enumeration bound

Two independent enumeration mechanisms, one per branch of `multiple_circulation` (`source\multiple_circ.py:98`):

- **Fixed entry edge, varying subdivision order.** `multiple_circulation_fixed_entry` (`:25`) is the recursion. At each face it builds two queues that differ only in the order the two child faces are appended:
  ```
  queue1.append((ne,s[1],n-1)); queue1.append((ne,s[0],n-1))   # :74-75
  queue2.append((ne,s[0],n-1)); queue2.append((ne,s[1],n-1))   # :78-79
  ```
  and recurses twice on a `deepcopy`-forked graph: `self.multiple_circulation_fixed_entry(q1, graph, size)` / `(q2, graph1, size)` at `:85-86`. So the varied quantity is **which edge is subdivided next**, exactly as the docstring at `:27-28` states. This is not "different spanning trees of the room graph" and not "different entry rooms".

- **Varying entry edge.** Only when no wheel subgraph is found. The exterior edge list is built by `find_exterior_edges` (`:140`) from `bdy.Boundary(...).identify_bdy()` (`:154-155`), and the fallback branch at `:134-136` just prints them.

**The enumeration loop and its bound:** `for i in range(4, len(graph) + 1):` at `source\multiple_circ.py:112`, with the test `if(self.is_subgraph(nx.wheel_graph(i), graph, i)):` at `:117` and an unconditional `break` at `:129`. The bound is therefore `len(graph) - 3` iterations, i.e. wheel sizes 4 through the number of rooms; the loop stops at the first wheel size found. The rationale is spelled out in the comment block at `:104-109`: a wheel subgraph is what makes multiple circulations possible for a *fixed* entry edge; without one, the count is bounded by the number of exterior edges.

The recursion at `:85-86` itself has **no depth or count bound** other than the queue draining. `self.count_of_multi_circ` (`:22`, incremented at `:47`) only counts calls after the fact; the comment at `:18-21` explains the `-1` initialisation.

Critically, the branching is **defeated by aliasing**: `queue1 = queue` and `queue2 = queue` at `:70-71` bind both names to the *same list object*, so all four `append`s at `:74-79` land in one list and `queue1 is queue2 is queue`. The dedup at `:82-84` then reads
```
[q1.append(x) for x in queue1 if x not in q1]
[q2.append(x) for x in queue2 if x not in q1]
```
where the second comprehension tests membership in `q1`, not `q2` (`:84`). Net effect: `q2` ends up empty whenever `q1` has absorbed everything, so the "choice 2" branch terminates immediately. The same aliasing bug exists verbatim in `source\circulation\circulation.py:118-119`.

### Q5: `path_map.py`, what it maps and to what

It maps **candidate boundary decompositions to dimensional feasibility**, and returns the surviving decompositions. Not room pairs to corridor paths, not doors to edges.

`dim_on_paths_bdy` (`:99`):
1. Reduce the room set to boundary rooms only (`:102-133`).
2. `attempt_with_threshold(threshold_ratio, count_condition)` (`:139`) - for each candidate boundary, for each of its 4 paths, sum the widths and heights of the rooms on that path and record `width_diff = plot_width - total_width`, `height_diff = plot_height - total_height` (`:146-151`).
3. Sort by each column (`:155-156`), and keep paths whose slack lies in `[0, 0.2 * plot_dimension]` as `pointers_w` / `pointers_h` (`:163-164`).
4. Hand the surviving walls to `paths_after_select_bdy` (`:192`, `:196`).
5. `paths_after_select_bdy` (`:48`) re-seats the chosen wall into an even slot (`[0,2]`, "w") or odd slot (`[1,3]`, "h") per `:55-58`, circularly fills the remaining three walls (`:68-73`), re-counts how many of the 4 walls satisfy the slack test (`:78-88`), and accepts the arrangement only if `count_condition(count) and is_circularly_connected(rearr_bdy)` (`:90`). `is_circularly_connected` (`:36-45`) requires the last room of wall `i` to equal the first room of wall `i+1 mod 4`.
6. Reflections are stripped (`:95`, `:201`).
7. **Three-stage relaxation ladder** at `:204-214`: first `(0.2, count == 4)`, then on empty `(0.3, count == 4)`, then on still-empty `(0.3, count >= 3)`. Returns whatever the first non-empty stage produced, or `[]` (`:216`).

Consumer: `inputgraph.irreg_multiple_dual` (`inputgraph.py:972`, `:1057`) assigns the result to `selected_list`, which drives the boundary loop `for bdys in selected_list:` (`inputgraph.py:981`, `:1067`) that feeds `generate_multiple_rel(bdys, matrix, self.nodecnt, self.edgecnt)` (`inputgraph.py:986`, `:1072`; definition at `inputgraph.py:1412`). See the full chain in "Where It Sits In The Pipeline".

---

## Invariants And Preconditions

### `source\circulation\circulation.py`

1. **Rooms are already dimensioned.** `RFP.rooms[i]` must be `Room` objects with real `top_left_*`/`bottom_right_*` floats before `adjust_RFP_to_circulation` runs; the class never computes coordinates, it only adds offsets (`:550-555`).
2. **Room list index == graph node id.** Every room lookup is positional: `:295`, `:374-375`, `:460`, `:521`. A `rooms` list not in node-id order silently corrupts every corridor.
3. **Adjacency list must be consistent with geometry, to exact float equality.** `find_common_edges` (`:393`, `:397`, `:402`, `:406`) tests `room1.top_left_y == room2.bottom_right_y` and the three siblings with `==` on floats. There is no epsilon. A graph edge whose two rooms do not share a coordinate to the bit falls through to the `"Null"` sentinel from `:390`.
4. **`circulation_algorithm` must run before `adjust_RFP_to_circulation`.** The latter reads `self.circulation_graph` (`:292`) and `self.adjacency` (`:277`), which are only assigned at `:258-259`.
5. **The entry edge `(v1, v2)` must be an exterior edge of the PTPG**, and is 1-indexed on input (converted at `:210`). Enforced only reactively by the `try/except` at `:227-231`.
6. **Corridor vertex ids are contiguous from `m`.** `:246` builds `[x+m for x in range(len(adjacency))]` and `:292` iterates `range(len(self.graph), len(self.circulation_graph))`. These agree only because `m == len(self.graph)` (`:208-209`) and no corridor vertex is ever removed.
7. **Displacement is bounded to `±0.5 * corridor_thickness` per edge** by the clamping in `calculate_edge_move` (`:525-547`) - subject to the `target` override at `:299-310`, which bypasses the clamp.
8. **`self.graph` is never mutated.** `circulation_algorithm` operates on `deepcopy(self.graph)` (`:205`), and `find_common_neighbors` queries the original `self.graph` (`:456`), not the corridor-augmented one. This is deliberate: neighbour propagation must use pre-corridor adjacency.

### `source\path_map.py`

1. Every candidate boundary in `all_bdy` has exactly 4 paths. Hardcoded at `:53` (`[None]*4`), `:41` (`boundary[(i+1) % 4]`), `:50-51` (`odd_indices = [1,3]`, `even_indices = [0,2]`), `:85-88` (`ind % 2`).
2. `room_w` and `room_h` are indexed by full room id; the filter at `:115-120` assumes `len(room_w) == len(room_h)` and that `bdy_edges` ids are valid indices into them.
3. Paths are circularly connected end-to-start (`:36-45`), so consecutive walls share a corner room.
4. An empty return is legitimate and the caller must handle it (`inputgraph.py:978-979`).

---

## Failure Modes

### When a corridor cannot fit (`source\circulation\circulation.py`)

**There is no feasibility check at all in this file.** Confirmed by absence: `is_dimensioning_successful`, `dimensions`, `dimension_constraints`, `is_minimum_dimensioned`, and `is_optimal` have zero occurrences in the file, and `remove_corridor` appears only in the commented-out `:557`. Consequences:

1. **Room inversion.** If a room's width is at or below `corridor_thickness`, `push_edges` (`:552-555`) will move `top_left_x` past `bottom_right_x` (or `top_left_y` below `bottom_right_y`) and produce a negative-extent rectangle. Nothing detects or rejects this. `Room.width`/`Room.height` (`:33-34`) are computed once in `__init__` and are never recomputed after the push, so they go stale immediately.
2. **Silent corridor loss.** If the two rooms named by a corridor vertex do not share an exact coordinate boundary, `find_common_edges` returns direction `"Null"` (`:390`); `add_corridor_between_2_rooms` then matches none of the four `if/elif` branches at `:330-364`, appends no push state, and sets no `target`. The corridor simply does not exist in the output, with no error and no return value. Execution continues into `find_common_neighbors` at `:367`.
3. **Non-exterior entry edge.** `graph.remove_edge(s[0], s[1])` at `:228` raises, is swallowed by the bare `except` at `:229`, prints `"WARNING!! THE INITIAL CHOSEN ENTRY EDGE MUST BE EXTERIOR EDGE"` (`:230`), and `circulation_algorithm` returns `0` (`:231`). But by then the graph has already had `add_edge(s[0], n)` and `add_edge(s[1], n)` applied at `:225-226`, so the copy is left in a half-mutated state. `self.circulation_graph` and `self.adjacency` are never assigned on this path (`:258-259` unreachable), so a caller that ignores the `0` and proceeds to `adjust_RFP_to_circulation` hits an empty `nx.Graph()` from `:56` and the loop at `:292` runs over an empty range.

### Outright broken code paths

4. `multiple_circulation` (`:143`) cannot run. Line `:156` reads `bdy.Boundary(...)` while line `:157` writes `bdy = bdy_obj.identify_bdy()` in the same function scope, making `bdy` a local -> `UnboundLocalError` at `:156`. The module-level import that would have supplied it is commented out at `:12`. Even if bound, the call passes 3 arguments where `GPLAN\GPLAN\source\trial\bdy.py:55` defines `def __init__(self, nodecnt, edgecnt, edgeset, node_coordinates)` (4). `nx.to_numpy_matrix` at `:149` was also removed in NetworkX 3.x.
5. `multiple_circulation_fixed_entry` (`:81`) cannot complete. `adjacency = []` is a **list** at `:95`, and `:138` calls `list(adjacency.values())` -> `AttributeError`. (The sibling `multiple_circ.py:38` uses a dict, so only the `source\circulation` copy has this specific defect.)
6. `find_common_neighbors` (`:411`) recurses at `:503` and `:509` with only `last_visited` (`:457`) as a guard. There is no global visited set, so a cycle of common neighbours can recurse indefinitely. The recursion also has no depth cap.
7. `temp_push_states` (`:59`) is **never cleared**. `add_corridor_between_2_rooms` appends at `:331`/`:489`/`:493` and then replays the *entire accumulated list* at `:370-375` for every corridor. Because `calculate_edge_move` is idempotent under its clamps (`:525-547`), the geometry is not corrupted, but the work is quadratic in the number of corridors and stale states from earlier corridors are re-applied.
8. **Copy/paste bug at `:544`.** In the `direction == "S" and coordinate == "T"` branch: `room_obj.rel_push_T = min(room_obj.rel_push_L, -0.5*self.corridor_thickness) if room_obj.rel_push_T <= 0 else room_obj.rel_push_T`. It reads `rel_push_L` where every sibling branch reads its own accumulator. A room with a non-zero left push will get that value written into its top push.
9. `test_comm_edges` (`:640`), `test_comm_neighbors` (`:713`) construct `circulation(g1, rfp1, room1, room2)` with 4 args (`:655`, `:673`, `:691`, `:709`, `:745`) against the 2-arg `__init__` at `:53` -> `TypeError`. These tests were written against an older signature and never updated. `main()` at `:868` only runs `test_multiple_circulation`, which itself hits failure mode 4.
10. `source\multiple_circ.py` class is non-functional on every path: `self.graph` is read at `:100` but never assigned in `__init__` (`:14-22`); `self.find_exterior_edges` is called as a method at `:103` but `find_exterior_edges` is module-level at `:140`; `self.is_subgraph(nx.wheel_graph(i), graph, i)` at `:117` calls a method that does not exist on the class and whose module-level namesake at `:164` takes `(g1, k)`, not 3 args; `self.circulations_adjacency_list` is appended at `:93` but never initialised. `main()`'s `test_multiple_circulation` at `:300` calls `circulation(g3)` where `circulation` is the *module* imported at `:10` -> `TypeError`. `import circulation` at `:10` is a bare top-level import that resolves only if `source\` is on `sys.path`, in which case it binds the **package** `source\circulation\` (which has an empty `__init__.py`, 0 bytes), not the class.
11. Two blocking `input()` calls at `source\multiple_circ.py:124-125`. Any server-side use would hang.

### `source\path_map.py`

12. `zip(*[...])` at `:159-160` raises `ValueError` on an empty `result`, i.e. a boundary with no paths.
13. `rooms[r]` lookups are guarded by `if r in rooms` (`:79-80`, `:146-147`), so rooms missing from the boundary set are silently treated as zero-size, quietly inflating the slack and admitting a bad boundary.
14. The `else: print("No combination of walls found...")` at `:199-200` is attached to `if width_paths:` (`:195`), not to the `if height_paths:` (`:191`), so the message fires whenever only height walls were found. Cosmetic, but the log is misleading.
15. `is_circularly_connected` (`:36`) indexes `boundary[(i+1) % 4]` while iterating `enumerate(boundary)`. On a boundary with more than 4 walls it silently compares against the wrong wall.
16. The relaxation ladder (`:204-214`) can return `[]`, and the caller then reverts to the unfiltered `cip_list` (`inputgraph.py:978-979`, `:1064-1065`). This is the documented behaviour behind the batch-collapse issue recorded in project memory: when `dim_on_paths_bdy` collapses the boundary pool, the fallback reuses a pool that does not fit the plot.

---

## Coupling (what breaks if you change this)

### `source\path_map.py` (live - change with care)

- `dim_on_paths_bdy`'s 6-argument signature (`:99`) is bound at two call sites, `inputgraph.py:972` and `inputgraph.py:1057`. Both must change together.
- The import is a **star import** (`inputgraph.py:20`). Every module-level name in `path_map.py` (`labels`, `is_reflections`, `remove_reflections`, `is_circularly_connected`, `paths_after_select_bdy`, `dim_on_paths_bdy`, plus `cycle`, `np`, `copy` from `:1-3`) is injected into `inputgraph`'s namespace. Adding a generic name there can shadow an `inputgraph` symbol. There is no `__all__`.
- The return shape (list of 4-element wall lists) is consumed directly by the `for bdys in selected_list:` loop and passed straight into `generate_multiple_rel(bdys, ...)` (`inputgraph.py:981`, `:986`). Changing the element shape breaks REL generation.
- The three-stage threshold ladder (`:204-214`) is the knob that governs how aggressively the boundary pool is pruned. Tightening it increases the chance of the empty-result fallback at `inputgraph.py:978`.
- The cardinal-constraints branch (`inputgraph.py:966` and `:1051`, with rationale comments at `:959-965` and `:1045-1050`) deliberately **bypasses** `path_map`, with the comment that the pre-selector "scrambles the N/E/S/W assignment". Any change to `paths_after_select_bdy`'s slot re-seating (`:53`, `:60-73`) interacts with that decision.

### `source\circulation\circulation.py` and `source\multiple_circ.py` (unreferenced - changing them breaks nothing)

Nothing imports either module. Deleting them today would not affect `handlers.py` or `api.py`. The risk is the opposite one: someone "fixing" a corridor bug here and expecting the running system to change. The system runs `GPLAN\GPLAN\circulation.py` via `handlers.py:31`.

Internal coupling within `source\circulation\circulation.py`, should anyone revive it:
- Corridor vertex numbering (`:238`, `:246`) is coupled to the iteration range at `:292`.
- The 6-tuple layout produced at `:331`/`:468-484` is unpacked positionally at `:374-375`. Reordering the tuple breaks every push.
- The `target` override at `:299-310` silently wins over the clamped `rel_push_*` from `calculate_edge_move`. Any change to the clamping logic at `:525-547` is partially moot for flanking rooms.
- `corridor_thickness` is a hardcoded `0.1` at `:60` with no parameter. The root module's version accepts it as a constructor argument (`handlers.py:104` passes `ui.get_corridor_thickness()` as the second positional arg), so the two are not drop-in interchangeable.

---

## Dead Or Duplicated Code

**Dead (no importer anywhere in the tree, verified by grep over all `*.py` under `C:\Users\nitant\Documents\GPLAN_Revamp`):**

- `GPLAN\GPLAN\source\circulation\circulation.py` in its entirety. Zero hits for `source.circulation`, `source import circulation`, or `circulation.circulation`. `source\circulation\__init__.py` is 0 bytes and re-exports nothing. Reachable only by running the file directly (`:871`).
- `GPLAN\GPLAN\source\multiple_circ.py` in its entirety. Zero importers, and every code path inside is broken (see Failure Modes 10 and 11).

**Dead within `source\circulation\circulation.py`:**

- `class Point` (`:14`) and `class Edge` (`:19`): defined, never instantiated anywhere in the file.
- `circulation.is_subgraph` (`:72`): only caller is `multiple_circulation` at `:178`, which itself cannot run.
- `circulation.multiple_circulation_fixed_entry` (`:81`) and `circulation.multiple_circulation` (`:143`): the only external entry is the file's own `test_multiple_circulation` at `:844`, which crashes at `:156`.
- `self.pushed_stack` (`:61`): initialised, never read or written again.
- `self.count_of_multi_circ` (`:70`): initialised, never incremented (the increment is commented out at `:98`).
- Commented-out `wheel_graph` (`:559-569`) and `remove_corridor_between_2_rooms` (`:557`).
- The interactive `input()` prompts inside `multiple_circulation` are already commented out at `:184-187`.
- `from glob import glob1` (`:4`): imported, never used.
- `test_comm_edges` (`:640`), `test_comm_neighbors` (`:713`), `test_move_edges` (`:748`), `test_adjust_RFP_to_circ` (`:790`), `test_circ` (`:600`): all disabled at `:863-867`.

**Duplicated:**

- All three files exist byte-identically at `C:\Users\nitant\Documents\GPLAN_Revamp\gplan_backend\GPLAN\GPLAN\source\...` (md5 verified identical for all three pairs). That is the `gplan_backend` submodule checkout of the same engine repo, not an independent fork.
- `plot()` is defined three times with near-identical bodies: `source\circulation\circulation.py:571`, `source\multiple_circ.py:230`, and `handlers.py:474`.
- `multiple_circulation_fixed_entry` exists twice with the same aliasing bug: `source\circulation\circulation.py:81` (list-typed `adjacency`, broken at `:138`) and `source\multiple_circ.py:25` (dict-typed `adjacency`, so `:93` would work if the surrounding class were functional). `source\multiple_circ.py` is the later, partially-repaired copy: it adds the `if len(queue) > 0` guard (`:41`), the `q1`/`q2` dedup (`:82-84`), and the corridor-counter dict (`:38-39`, `:68-69`).
- `is_subgraph` exists three times with three different signatures: `source\circulation\circulation.py:72` `(self, g1, g2, k)`, `source\multiple_circ.py:164` `(g1, k)`, and `GPLAN\GPLAN\circulation.py:958` (root file, not read in this session, line number from the knowledge graph).
- `find_exterior_edges` logic is duplicated inline at `source\circulation\circulation.py:148-164` and as a function at `source\multiple_circ.py:140-162`; only the latter passes the required 4th `node_coordinates` argument to `bdy.Boundary` (`source\trial\bdy.py:55`).

**Not dead, but broken in the caller, relevant to the sibling task:** `make_dissection_corridor` (`handlers.py:58`) is reached from `GPLAN\main.py:20` whenever `gclass.command == "dissection"`, the name arriving via the star import at `main.py:6`. Its body at `handlers.py:62` references an unbound name `circulation` (only `cir` is imported, `handlers.py:31`, and `handlers.py` has no star imports), so that branch raises `NameError` in normal operation rather than failing silently.

---

## Open Questions

1. **Is the circulation produced by `circulation_algorithm` actually spanning?** The file asserts nothing. The `ne < m` guard (`:224`) plus the FIFO expansion (`:220-243`) look like they cover every triangular face reachable from the entry edge, but a room that participates in no such face would be skipped silently. The root module has `min_tree_set_cover` and `remove_redundant_corridors` methods (per the knowledge graph, `GPLAN/GPLAN/circulation.py` L341 and L384) that have no counterpart here, which suggests coverage was a known open problem addressed only in the root version. Not verifiable from the source copy alone.
2. **Why was `source\circulation\circulation.py` kept?** It is a strictly earlier and strictly smaller version of the root module (no thickness parameter, no dimension feasibility, no corridor removal, no room-area output). Whether it is intended as a reference implementation, a stalled refactor target, or simply unpruned history is not determinable from the code.
3. **Knowledge graph disagreement (recorded per instructions).** `graphify explain "circulation"` returns only the root-file node (`GPLAN/GPLAN/circulation.py L51`) with 20 method edges, and does not surface `source\circulation\circulation.py` as a separate `circulation` class node, even though `graphify query` does list the source file's methods (`.add_corridor_between_2_rooms()` L315, `.adjust_RFP_to_circulation()` L281, `.find_common_edges()` L378, `.find_common_neighbors()` L411, `.calculate_edge_move()` L511, `.corridor_boundary_rooms()` L264 - all matching the line numbers I read). The graph's `explain` view therefore under-reports the duplicate. Line numbers agree with the code; the omission is an indexing artefact, not a factual conflict. Code followed.
4. **Does `path_map`'s slot re-seating in `paths_after_select_bdy` (`:53`, `:60-73`) genuinely destroy compass orientation?** The cardinal-constraints bypass comments at `inputgraph.py:959-965` and `:1045-1050` assert it does. I confirmed the code writes the selected wall into an arbitrary even or odd index and circularly fills the rest, which is consistent with that claim, but I did not trace how the resulting index order is later interpreted as N/E/S/W. Worth confirming before touching that function.
5. **What consumes `bdy_edges`' room-id space in `dim_on_paths_bdy`?** Line `:115` iterates `range(len(room_w))` and tests `if itr in outer_rooms`, so it assumes `bdy_edges` ids and `room_w` indices share the same numbering. `bdy_edges` is produced by `generate_multiple_bdy` (called at `inputgraph.py:946` and `:1033`, defined at `inputgraph.py:1453`). If it returns ids for dummy or merged vertices beyond `len(room_w)`, those ids would be silently dropped by the `if itr in outer_rooms` filter. Not traced.
