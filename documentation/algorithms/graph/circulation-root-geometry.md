# circulation-root-geometry

Scope: the geometry half of `C:\Users\nitant\Documents\GPLAN_Revamp\GPLAN\GPLAN\circulation.py`.
Covered: `Point`, `Edge`, `Room`, `RFP`, `adjust_RFP_to_circulation`, `add_corridor_between_2_rooms`,
`find_common_edges`, `find_common_neighbors`, `calculate_edge_move`, `push_edges`,
`check_dimensions_feasibility`, `check_mindim_feasibility`, the module-level helpers at lines 894-975,
and `main()` plus its nested test functions.
Not covered (sibling dossier `circulation-root-graph`): `circulation_algorithm`, `min_tree_set_cover`,
`remove_redundant_corridors`, `remove_corridor`, `donot_include`, `multiple_circulation`, i.e. lines 51-445.

All line references below were read in this session.

## Purpose

This half turns an abstract corridor list (corridor vertex -> the pair of rooms it separates, produced by
the graph half in `self.adjacency`, `circulation.py:303`) into actual rectangle coordinates: for each
corridor it opens a gap of `corridor_thickness` along the wall shared by the two rooms, works out which
further rooms must slide so the floorplan stays tiled, applies every shift in one final pass, and then
(only for dimensioned or minimum dimensioned runs) reports whether the shrunken rooms still meet their
dimensional constraints.

It does not draw anything, does not create corridor rectangles as objects, and does not verify that the
shared wall is long enough to hold a corridor. The corridor is implicit: it is the void left behind after
the two rooms retreat by half the thickness each.

## Where It Sits In The Pipeline

Live call chain (GUI only, see Failure Modes for why the API path never reaches it):

- `GPLAN/GPLAN/api.py:1309` `handle_door_connectivity(ui, graph)` (also 1353, 1390)
- `GPLAN/GPLAN/handlers.py:1747-1748` inside `handle_door_connectivity` (defined at `handlers.py:1686`):
  `if(ui.get_isCirculation() == 1): handle_circulation(ui,graph,drawGUI,gclass)`
- `GPLAN/GPLAN/handlers.py:492` `handle_circulation` picks one of six mode branches (499, 558, 595, 657, 706, 729)
- `GPLAN/GPLAN/handlers.py:79` `call_circulation_new` builds `cir.Room` objects (`handlers.py:92-99`), a
  `cir.RFP` (`handlers.py:101`), a `cir.circulation` (`handlers.py:104`), runs the graph half
  (`handlers.py:116`), then calls the geometry half at `handlers.py:230`
  (`circulation_obj.adjust_RFP_to_circulation()`), and for minimum dimensioned runs a second time at
  `handlers.py:262`.
- Results are copied back onto the floorplan at `handlers.py:282-306`; the feasibility flag is returned as
  the second tuple element (`handlers.py:299`, `handlers.py:306`).
- `GPLAN/main.py:40` also calls `handle_circulation` (desktop GUI entry).

Input contract from `handlers.py:94-95`: `cir.Room(i, room_x, room_y + room_height, room_x + room_width, room_y)`,
so `tl_y` is the larger y and `br_y` the smaller y.

## Entry Points (file:line)

- `circulation.py:446` `adjust_RFP_to_circulation(self)` - the only entry point used by production code
  (`handlers.py:122`, `handlers.py:166`, `handlers.py:230`, `handlers.py:262`).
- `circulation.py:529` `add_corridor_between_2_rooms(self, room1, room2)` - called from
  `circulation.py:483` and from the dead test `circulation.py:1171`.
- `circulation.py:616` `find_common_edges(self, room1, room2)` - called from `circulation.py:545`,
  `circulation.py:674`, `circulation.py:704-705`.
- `circulation.py:654` `find_common_neighbors(self, room1, room2, last_visited, mov1, mov2)` - called from
  `circulation.py:606` and recursively from `circulation.py:778` and `circulation.py:785`.
- `circulation.py:787` `calculate_edge_move(self, room, direction, coordinate)` - called only from
  `circulation.py:612-613`.
- `circulation.py:824` `push_edges(self, room)` - called only from `circulation.py:506`.
- `circulation.py:843` `check_dimensions_feasibility(self)` - called only from `circulation.py:511`.
- `circulation.py:869` `check_mindim_feasibility(self)` - called only from `circulation.py:519`.
- `circulation.py:941` `plot(graph, m)` - module-level, live: called from `handlers.py:103` and `handlers.py:117`.
- `circulation.py:978` `main()` - guarded by `if __name__ == "__main__":` at `circulation.py:1297-1298`, dead as an import.

## Data Structures

### `Point` (`circulation.py:14-17`)
`x`, `y` floats. Never instantiated. Grep for `Point(` over `GPLAN/` does return about 47 hits, but every
one of them resolves to a different class: `GPLAN/GPLAN/source/graphoperations/graph_crossings.py:172` and
`graph_crossings.py:256-303` use the `Point` that file defines itself at `graph_crossings.py:12`,
`graph_crossings1.py:171` and `graph_crossings1.py:285-332` use its own at `graph_crossings1.py:11`,
`triangularity_non_adj.py:315-415` and `GPLAN/GPLAN/pythongui/final.py:503` use shapely's
(`triangularity_non_adj.py:26`, `final.py:20`). None of them is `circulation.Point`. Dead.

### `Edge` (`circulation.py:19-23`)
`id`, `left: Point`, `right: Point`. Never instantiated: grep for `Edge(` over `GPLAN/` returns no hits at
all beyond this definition. Dead. In particular `find_common_edges` does not return an `Edge`; it returns
the plain 5-tuple built at `circulation.py:627`, `circulation.py:637`, `circulation.py:641`,
`circulation.py:646` and `circulation.py:650`.

### `Room` (`circulation.py:25-40`)
Constructor `Room(id, tl_x, tl_y, br_x, br_y)`.

| attribute | line | meaning |
|---|---|---|
| `id` | 27 | room index, used directly as an index into `RFP.rooms` (`circulation.py:612`, `circulation.py:701`) and as the node id in `self.graph` (`circulation.py:697`) |
| `top_left_x` | 28 | left edge x (smaller x) |
| `top_left_y` | 29 | top edge y. This is the LARGER y: `handlers.py:94` passes `room_y + room_height` here |
| `bottom_right_x` | 30 | right edge x (larger x) |
| `bottom_right_y` | 31 | bottom edge y (smaller y): `handlers.py:95` passes `room_y` |
| `height` | 32 | `abs(br_y - tl_y)`, computed once at construction and never refreshed |
| `width` | 33 | `abs(br_x - tl_x)`, computed once at construction and never refreshed |
| `rel_push_T/B/L/R` | 34-37 | signed displacement to apply to that edge, filled by `calculate_edge_move` (787-822), consumed by `push_edges` (831-834) |
| `target` | 40 | dict `{'T','B','L','R'}` of displacements for edges that are corridor walls; written only in `add_corridor_between_2_rooms` (561, 564, 574, 577, 587, 590, 600, 603) and copied over `rel_push_*` in `adjust_RFP_to_circulation` (491-502) |

Coordinate system: y grows UPWARD, not downward. Three independent confirmations:
1. `handlers.py:94` sets `tl_y = room_y + room_height` and `br_y = room_y`, so top > bottom.
2. `circulation.py:636-637`: `room1.top_left_y == room2.bottom_right_y` is commented "Room1 is below Room2"
   (`circulation.py:635`) and yields direction `"N"` with respect to room1, so north is +y.
3. `circulation.py:838` computes `height = room.top_left_y - room.bottom_right_y` with no `abs`, which is
   only positive under y-up.
Consistently, `calculate_edge_move` maps `"N"` to `+0.5*thickness` (`circulation.py:811-816`) and `"S"` to
`-0.5*thickness` (`circulation.py:818-822`), and `"E"` to `+` on x (`circulation.py:799-803`).

`Room.height` and `Room.width` are stale after any push (`push_edges` at 831-834 changes coordinates but
does not recompute them) and are never read by any caller: the post-push sizes are read from
`self.dimensions` (`circulation.py:840`) or recomputed by handlers from the coordinates
(`handlers.py:285-286`).

### `RFP` (`circulation.py:43-46`)
`graph` (nx.Graph) and `rooms` (list of `Room`, positionally indexed by room id). Built at `handlers.py:101`.
Note `RFP.graph` is a separate copy of the adjacency graph from `circulation.graph`; the geometry code
always queries `self.graph` (`circulation.py:697`), never `self.RFP.graph`.

### Mutable circulation state used by this half
- `self.temp_push_states` (`circulation.py:57`): list of lists of 6-tuples
  `(roomA_id, dirA, edgeA, roomB_id, dirB, edgeB)`. Appended at 554/567/580/593 (corridor pair) and at
  763/767 (neighbor fronts). NEVER cleared after `__init__`.
- `self.done_rooms` (`circulation.py:77`): list of `[room_id, edge, 'c']` lists (corridor walls, appended
  at 557-558, 570-571, 583-584, 596-597) and `(room_id, edge, 'n')` tuples (neighbor shifts, appended at
  715, 721, 727, 733, 740, 746, 752, 758). NEVER cleared after `__init__`.
- `self.dimensions` (`circulation.py:66`): dict `room_id -> [width, height]`, written only in `push_edges`
  (`circulation.py:840`), read by both feasibility checks (859-860, 883-884) and by `handlers.py:235-249`.
- `self.dimension_constraints` (`circulation.py:67`), set by `handlers.py:109` or `handlers.py:112`.
  Layout differs per mode: `[min_w, max_w, min_h, max_h, min_ar, max_ar]` for dimensioned
  (`circulation.py:850-855`, matching `handlers.py:633`) versus `[min_w, min_h, plot_w, plot_h]` for
  minimum dimensioned (`circulation.py:876-879`, matching `handlers.py:524`).
- `self.room_area` (`circulation.py:68`): list of display strings built at 516-517 / 523-524, consumed at
  `handlers.py:297-298`.
- `self.is_dimensioning_successful` (`circulation.py:71`): the only feasibility signal that escapes,
  set at 512 / 520, returned by `handlers.py:299` and `handlers.py:306`.

## Algorithm Walkthrough

### `adjust_RFP_to_circulation` (446-526)

1. `required_corridors = list(self.adjacency.keys())` (457); if `self.rem_red_rooms == 1` (constructor arg
   `opti`, `circulation.py:74`, supplied as `gclass.rem` at `handlers.py:104`) it is replaced by
   `remove_redundant_corridors()` (461, sibling dossier).
2. Guard `if(len(list(self.adjacency.keys())) > 0)` (466); otherwise plain `return` (526) with no
   coordinate change at all.
3. Corridor order (467-475): `start = min(keys)`, `end = max(keys)`, and the loop is
   `for corridor in range(start + 1, end + 1)`. Corridor ids are integers assigned in the graph half in
   BFS discovery order from the entry edge (`circulation.py:279-288`: `adjacency[corridor_counter]`, then
   keys remapped to `m, m+1, ...` where `m = len(graph)`). So corridors are processed in ascending vertex
   id, i.e. BFS order outward from the entry door, and the FIRST corridor (`start`, the entry corridor) is
   deliberately skipped. That skip is the entire implementation of "no entry corridor", confirmed by the
   comment at 474 and by `handlers.py:228-229`.
4. Each surviving corridor is resolved to its two rooms via `corridor_boundary_rooms` (481, defined at
   `circulation.py:307-320`, a dict lookup into `self.adjacency`) and handed to
   `add_corridor_between_2_rooms` (483).
5. After the loop, `target` overrides `rel_push_*` for corridor walls (491-502), then every room is pushed
   once (505-506), then feasibility is evaluated (510-524).

State carried between successive `add_corridor_between_2_rooms` calls:
- `self.done_rooms` accumulates `'c'` markers, so a room edge already used as a corridor wall is never
  also shifted as a neighbor for a later corridor (guards at 712, 718, 724, 730, 737, 743, 749, 755).
- `self.temp_push_states` accumulates and is never cleared, so the loop at 609-613 re-applies every tuple
  from every earlier corridor on each call. This is O(corridors^2) work but idempotent, because
  `calculate_edge_move` clamps with `max`/`min` against a constant `+/-0.5*thickness` (800-822) rather
  than accumulating.
- `room.target` per room, later promoted to `rel_push_*` at 491-502.
- The module-level `global i` (12, 478-479) is a step counter used only for print statements (538, 316).
  It is clobbered by the `for i in range(...)` loops at 514 and 522, which rebind the global because
  `global i` was declared at 478 for the whole function scope.

### `add_corridor_between_2_rooms` (529-613)

1. `common_edge = self.find_common_edges(room1, room2)` (545).
2. Orientation decision (553, 566, 579, 592) keys ONLY off `common_edge[4][1]`, the direction letter:
   - `"N"` (room2 above room1): room1's top edge moves S, room2's bottom edge moves N (554-564).
   - `"S"`: room1's bottom edge moves N, room2's top edge moves S (566-577).
   - `"E"` (room2 to the right): room1's right edge moves W, room2's left edge moves E (579-590).
   - `"W"`: room1's left edge moves E, room2's right edge moves W (592-603).
   So a shared horizontal wall (N or S) gives a horizontal corridor, and a shared vertical wall (E or W)
   gives a vertical corridor. In every case each room gives up `0.5*corridor_thickness`
   (561/564/574/577/587/590/600/603), for a total gap of `corridor_thickness`.
3. `find_common_neighbors(room1, room2, -1, dir1, dir2)` (606) propagates the shift to neighbours.
4. Everything queued in `self.temp_push_states` is converted to `rel_push_*` values (609-613).

What happens when the shared wall is shorter than the corridor needs: nothing. There is no length check
anywhere in this function or in `find_common_edges`. `common_edge[0..3]` (the segment endpoints) are used
only by `find_common_neighbors` at 684-694 to decide whether the wall is horizontal or vertical; they are
never compared against `corridor_thickness`, never against a minimum corridor length, and no fallback,
warning or rejection exists. A corridor is inserted at full thickness regardless of how short the shared
wall is, and the only downstream symptom is that some room ends up below its minimum dimension, which the
feasibility checks may or may not catch (see below).

### `find_common_edges` (616-652)

Returns a plain 5-tuple, not an `Edge`:
`(x_left_or_top, y_left_or_top, x_right_or_bottom, y_right_or_bottom, (room1.id, direction))`
with `direction` in `{"N","S","E","W","Null"}`. Default is `(0,0,0,0,(room1.id,"Null"))` (627).

- 636-637: `room1.top_left_y == room2.bottom_right_y` -> room1 below room2 -> `"N"`, segment
  `(max(tl_x), tl_y, min(br_x), br_y)`, so element 1 == element 3 (a horizontal wall).
- 640-641: `room1.bottom_right_y == room2.top_left_y` -> `"S"`, also horizontal.
- 645-646: `room1.top_left_x == room2.bottom_right_x` -> room1 right of room2 -> `"W"`, element 0 ==
  element 2 (a vertical wall).
- 649-650: `room1.bottom_right_x == room2.top_left_x` -> `"E"`, vertical.

Direction is always expressed with respect to room1. The comparisons are exact float equality and there
is no test that the two rooms actually overlap along the shared line, so two rooms touching only at a
corner satisfy the same predicate and are reported as fully adjacent.

### `find_common_neighbors` (654-785)

Signature `(room1, room2, last_visited, mov1, mov2)`. Declared `-> list` (654) but there is no `return`
statement: the body ends with the recursion loop at 782-785, so it always returns `None`. It communicates
purely by side effect on `self.temp_push_states` and `self.done_rooms`.

- `mov1` / `mov2` are the movement direction letters (N/S/E/W) that room1's side and room2's side of the
  corridor are travelling in. At the top level they are `dir1` / `dir2` from
  `add_corridor_between_2_rooms` (606). In recursion both are set to the same value taken from the tuple
  just built (`dir = neighbor1[1]` at 777, `dir = neighbor2[1]` at 784), because the whole front behind a
  room moves the same way.
- `last_visited` is the room id of the parent in the recursion tree; the loop skips it (698-699) so the
  walk does not immediately bounce back to where it came from. The top-level call passes `-1` (606), a
  sentinel that matches no room id.
- `axis` (680-694) is `('x', y_value)` when `common_edge[1] == common_edge[3]` (horizontal wall) or
  `('y', x_value)` when `common_edge[0] == common_edge[2]` (vertical wall). Only `axis[0]` is ever read
  (711, 717, 723, 729, 736, 742, 748, 754); `axis[1]` is unused.
- Iteration structure: a single `for` over `nx.common_neighbors(self.graph, room1.id, room2.id)` (697).
  For each common neighbour it computes the neighbour's direction relative to room1 (704, 707) and to
  room2 (705, 708) and, if that direction is compatible with the corridor axis and the neighbour's edge
  has not already been claimed as a corridor wall, it appends a 6-tuple to `neighbors_room1` or
  `neighbors_room2` (713, 719, 725, 731, 738, 744, 750, 756). Note the chain is one long
  `if/elif` (711-758), so a neighbour is classified against room1 OR room2, never both.
- The lists are pushed onto `self.temp_push_states` at 763 and 767.
- Recursion structure: two loops, 775-778 recursing on `(room1, neighbor_of_room1, room2.id, dir, dir)`
  and 782-785 recursing on `(room2, neighbor_of_room2, room1.id, dir, dir)`. One anchor room is kept and
  the newly found neighbour becomes the other member of the pair, so the front creeps outward one room at
  a time.
- Termination: there is no visited set, no depth limit and no explicit base case. The only brakes are
  (a) `nx.common_neighbors` returning nothing new, (b) the `last_visited` skip at 698-699, and (c) the
  `done_rooms` `'c'` guard. In practice the walk stops because in a rectangular floorplan each step must
  find a room adjacent to the anchor along the same axis, which runs out at the plan boundary. Nothing in
  the code guarantees this; see Open Questions.

### `calculate_edge_move` (787-822) and `push_edges` (824-840): who moves

Not just the two adjacent rooms. A propagating front moves:

- The two corridor rooms get their facing edges pushed via `room.target` (561-603) and promoted at
  491-502.
- Every room discovered by the recursive `find_common_neighbors` walk gets a tuple in
  `self.temp_push_states` (763, 767), and every tuple is fed to `calculate_edge_move` at 612-613, which
  moves BOTH members of the tuple: `each_tuple[0]` with `[1]`,`[2]` and `each_tuple[3]` with `[4]`,`[5]`.
- Look at the tuple shape at 713: `(room.id, mov1, "T", room1.id, mov1, "B")`. The neighbour's top edge
  and room1's bottom edge move in the same direction `mov1`, which means room1 translates (its top already
  moved by `mov1` via `target`) while the neighbour absorbs the change by shrinking, unless the recursion
  finds a further neighbour behind it, in which case the shrink is passed on again. The plan boundary is
  where the shrink finally lands.
- Magnitudes never accumulate: every branch of `calculate_edge_move` clamps to exactly
  `+/-0.5*self.corridor_thickness` with `max`/`min` (800, 803, 806, 809, 812, 816, 819, 822). So a room
  loses at most `corridor_thickness` in each axis no matter how many corridors touch it. This is exactly
  the slack the feasibility checks allow (861, 885).
- `push_edges` (824-840) is the single commit point: `top_left_y += rel_push_T`,
  `top_left_x += rel_push_L`, `bottom_right_y += rel_push_B`, `bottom_right_x += rel_push_R` (831-834),
  then it records `self.dimensions[room.id] = [width, height]` (838-840). It is called once per room from
  the loop at 505-506, so pushes are applied exactly once per `adjust_RFP_to_circulation` call.

Latent bug in `calculate_edge_move`: line 819 reads
`room_obj.rel_push_T = min(room_obj.rel_push_L, -0.5*self.corridor_thickness)`.
The "S" + "T" case clamps against `rel_push_L` (left) instead of `rel_push_T` (top). Every other branch
uses the matching field, so this reads as a copy-paste slip.

It is currently inert, and fixing it would not change any output. All four `rel_push_*` fields start at 0
(`circulation.py:34-37`), and before step 3 the only writer is `calculate_edge_move` itself, which assigns
either `max(field, +0.5*thickness)` or `min(field, -0.5*thickness)` (`circulation.py:800-822`). So when
line 819 runs, `rel_push_L` is always one of `0`, `+0.5*thickness`, `-0.5*thickness`, and
`min(rel_push_L, -0.5*thickness)` evaluates to exactly `-0.5*thickness` in all three cases, which is
precisely what `min(rel_push_T, -0.5*thickness)` would have produced from the same domain. The `target`
overrides at 491-502 run after every `calculate_edge_move` call (the corridor loop ends at 487), so they
cannot feed a value outside that set in. The bug would only start producing a geometric difference if the
clamp domain ever widened beyond `{0, +/-0.5*thickness}`.

### `check_dimensions_feasibility` (843-867)

Reads `dimension_constraints` as `[min_width, max_width, min_height, max_height, min_ar, max_ar]`
(850-855) but only `min_width`, `min_height`, `min_ar` are used (861). `max_width`, `max_height`,
`max_ar` are dead locals. For each room index `i` in `range(len(min_width))` (858) it fails if
`width < min_width[i] - corridor_thickness` or `height < min_height[i] - corridor_thickness` or
`width/height < min_ar[i]` (861). Maximum width, maximum height, maximum aspect ratio and plot bounds are
never checked. Called only from 511, only when `self.is_dimensioned` is True.

### `check_mindim_feasibility` (869-891)

Reads `[min_width, min_height, plot_width, plot_height]` (876-879); `plot_width` and `plot_height` are
dead locals, so the plot envelope is never re-validated after corridors widen the plan. It fails if
`width < min_width[i] - corridor_thickness or height < min_height[i] - corridor_thickness` (885). Called
only from 519, only when `self.is_minimum_dimensioned` is True.

### What the caller does on False (definitive)

Neither check reverts anything. Both are called at step 5 (510-524), AFTER `push_edges` has already
mutated every room's coordinates at step 4 (505-506). On False the function simply records
`self.is_dimensioning_successful = False` (512 / 520), skips populating `self.room_area`, and returns
normally. The mutated geometry stays.

In `handlers.call_circulation_new` the mutated coordinates are copied onto the caller's floorplan
unconditionally at `handlers.py:282-296`, before the flag is even looked at, and the flag is returned only
as the second element of the tuple (`handlers.py:299`, `handlers.py:306`). The branches in
`handle_circulation` then behave inconsistently:
- Dimensioned circulation: `if (success == False): return` (`handlers.py:645-646`), so nothing is drawn,
  but `graph.room_x` and friends were already overwritten inside `call_circulation_new`.
- Minimum dimensioned: `elif success == True:` (`handlers.py:544`, `handlers.py:702`) only gates the draw;
  there is no error path and no revert.
- Non-dimensioned circulation (`handlers.py:558-592`): `success` is ignored entirely
  (`handlers.py:585` is a bare `else`). In that mode `is_dimensioned` and `is_minimum_dimensioned` are
  both False, so neither check even runs and `is_dimensioning_successful` stays at its constructor value
  False (`circulation.py:71`) while the geometry is used anyway.

So: infeasible corridor geometry is never reverted and never dropped inside `circulation.py`. It would
leak to any consumer that reads the graph object rather than the boolean. The one thing that stops it
reaching the HTTP API today is that the API can never reach this code at all (next section).

### `main()` and helpers (894-1298)

Module-level helpers:
- `plot` (941-956) is LIVE: called from `handlers.py:103` and `handlers.py:117`. It ends in `plt.show()`
  (956) and no module in `GPLAN/` sets a headless matplotlib backend (only `gplan_backend/smoke_test_multi_ptpg.py:49`
  sets `MPLBACKEND=Agg`, and that is a test script).
- `wheel_graph` (894-919) and `complete_graph` (921-939) are referenced only by `test_multiple_circ`
  (1268, and commented-out lines 1275, 1282), which is itself commented out at 1294. Dead.
- `is_subgraph` (958-975) is never called. Grep for the name over `GPLAN/` hits only unrelated definitions
  and their local callers in the dead duplicates: a method at
  `GPLAN/GPLAN/source/circulation/circulation.py:72` (used at its line 178) and a second definition plus its
  test at `GPLAN/GPLAN/source/multiple_circ.py:164`, `:117`, `:251-273`. Nothing calls the one in this file.
  Dead.

`main()` (978) and every nested function inside it is test scaffolding:
`make_graph` (979), `test_circ` (990), `test_comm_edges` (1030), `test_comm_neighbors` (1103),
`test_move_edges` (1138), `test_adjust_RFP_to_circ` (1180), `test_remove_corridor` (1228),
`test_multiple_circ` (1266). At the bottom of `main()` there are seven invocation lines; six of them are
commented out (1288-1292 and 1294) and only `test_remove_corridor()` at 1293 is live. `make_graph` is a
helper called from inside the tests (992, 1032, 1050, 1068, 1086, 1104, 1139, 1181, 1229), never invoked at
the bottom. `main()` itself runs only under `if __name__ == "__main__":` (1297-1298), and the module is
always imported as `GPLAN.circulation` (`handlers.py:31`), so `main()` never executes in the application.

Confirmed by grep over `GPLAN/` and `gplan_backend/` for `cir.main`, `circulation.main`, `test_circ`,
`test_comm_edges`, `test_comm_neighbors`, `test_move_edges`, `test_adjust_RFP_to_circ`,
`test_remove_corridor`, `test_multiple_circ`, `make_graph`: inside `GPLAN/GPLAN/circulation.py` the hits are
its own definitions and internal calls (979-1294), and every hit outside it is in a dead duplicate,
`GPLAN/GPLAN/source/circulation/circulation.py` (589, 600, 602, 640, 642, 660, 678, 696, 713, 714, 748, 749,
790, 791, 838, 863-868), `GPLAN/GPLAN/source/multiple_circ.py` (278, 305) and `GPLAN/custom_circ_entry.py`
(250, 270, 279, 285, 286, 298). Neither `handlers.py` nor `api.py` contains any of these names, which is the
load-bearing part.

The scaffolding is also stale and would not run if uncommented:
- `circulation(g, rfp)` at 1022, 1170 and 1212, `circulation(g, rfp, room1, room2)` at 1045/1063/1081/1099,
  and `circulation(g, rfp, room1, room3)` at 1135 all mismatch the constructor
  `(graph, thickness=0.1, rfp=None, opti=1)` (`circulation.py:52`): the `RFP` is passed as `thickness`.
  That covers five of the seven tests: `test_circ` (1022), `test_comm_edges` (1045-1099),
  `test_comm_neighbors` (1135), `test_move_edges` (1170) and `test_adjust_RFP_to_circ` (1212).
- `find_common_neighbors(room1, room3, -1)` at 1136 omits the required `mov1` and `mov2`, so it raises
  `TypeError` against the signature at 654.
- The two that are not stale: `test_remove_corridor` (1259, `circulation(g, 0.1, rfp)`) uses the current
  signature, which is presumably why it is the one left enabled, and `test_multiple_circ` (1269,
  `circulation(g1)`) passes only the graph, so it takes the defaults.

## Invariants And Preconditions

1. `Room.id` equals the room's index in `RFP.rooms` and its node id in `self.graph`. Violated indexing
   would break `self.RFP.rooms[each_tuple[0]]` (612) and `nx.common_neighbors(self.graph, room1.id, room2.id)` (697).
2. `top_left_y > bottom_right_y` and `bottom_right_x > top_left_x` (y up, x right). Established by the
   caller at `handlers.py:94-95` and relied on by 838-839 and by the direction logic at 636-650.
3. Rooms tile exactly: shared walls must satisfy exact float equality (636, 640, 645, 649). Any rounding
   drift makes a pair look non-adjacent and `find_common_edges` returns direction `"Null"` (627).
4. Every corridor id in `self.adjacency` must resolve to a pair of geometrically adjacent rooms, otherwise
   the `"Null"` path is taken (see Failure Modes).
5. Push magnitude per edge is exactly `0.5*corridor_thickness` and never accumulates (clamps at 800-822).
   The feasibility slack at 861 and 885 assumes exactly this.
6. `adjust_RFP_to_circulation` is meant to run at most once per `circulation` object: `temp_push_states`
   (57) and `done_rooms` (77) are never reset. `handlers.py:262` violates this by calling it a second
   time on the same object after swapping in a fresh `RFP` at `handlers.py:260`.
7. `self.dimensions` must contain an entry for every index in `range(len(min_width))` before either
   feasibility check runs (858-860, 882-884). It is populated only by `push_edges` (840), which the
   `len(adjacency) == 0` early return at 526 skips entirely.

## Failure Modes

1. `UnboundLocalError` on `dir1` in `add_corridor_between_2_rooms`. If `find_common_edges` returns the
   default `"Null"` direction (627), none of the four branches at 553/566/579/592 executes, so `dir1` and
   `dir2` are never bound and line 606 raises. This happens whenever the corridor's two rooms are not
   exactly edge-adjacent (float drift, or an `adjacency` entry that does not correspond to a geometric
   wall). There is no `else` branch and no guard.
2. Wrong field in `calculate_edge_move` at 819 (`rel_push_L` read where `rel_push_T` is meant), described
   above. Latent only: because every writer clamps into `{0, +/-0.5*thickness}` (34-37, 800-822), the
   expression still evaluates to `-0.5*thickness`, the same value the correct field would give. No
   reachable state produces a geometric difference, and fixing it would not change output.
3. Corner-touching rooms are treated as sharing a full wall (no overlap test at 636-650), which can
   produce a corridor along a zero-length wall.
4. No corridor-fits check at all: neither the shared wall length nor the resulting room sizes are
   validated before the push. See the `add_corridor_between_2_rooms` walkthrough.
5. Unbounded recursion risk in `find_common_neighbors` (775-785): no visited set, only the `last_visited`
   skip (698-699). The `'n'` markers appended at 715/721/727/733/740/746/752/758 cannot suppress a revisit,
   because they are tuples while every guard tests for a LIST with the `'c'` tag
   (`if([room.id,"T",'c'] not in self.done_rooms)` at 712 etc.). So the `'n'` entries are write-only.
6. Infeasible plans are not reverted (see the definitive answer above).
7. Global counter corruption: `global i` (478) plus `for i in range(...)` at 514 and 522 overwrite the
   module-level `i` (12) used in the progress prints at 316 and 538.
8. The API path cannot reach this code. `api.py:1309` calls `handle_door_connectivity(ui, graph)` with no
   `gclass`, so `handle_circulation` receives `gclass=None` (`handlers.py:492`, `handlers.py:1748`). Then:
   - both minimum dimensioned branches dereference `gclass` before they get anywhere near a circulation
     object: `handlers.py:504` is `if gclass.open and len(ui.get_dim_constraints()) > 0:` and
     `handlers.py:661` is the identical line in the remove-corridor min-dim branch. With `gclass=None`
     that raises `AttributeError: 'NoneType' object has no attribute 'open'` at 504 / 661. The five-value
     unpack of `mindimgui.gui_fnc` at `handlers.py:512-514` and `handlers.py:669-671` is a real mismatch
     (that function returns six in both its headless branch,
     `GPLAN/GPLAN/pythongui/mindimensiongui.py:22`, and its GUI branch, same file line 157), but on the API
     path it is dead code: line 504 / 661 has already raised. The `ValueError` fires only in the GUI path,
     where `gclass` is not `None`;
   - every other branch reaches `call_circulation_new`, whose first statements are
     `entry = gclass.entry_door` (`handlers.py:83`) and `gclass.rem` (`handlers.py:104`), raising
     `AttributeError` on `None`.
   Nothing in `api.py` wraps `handle_door_connectivity` in a try/except (checked lines 1254-1470). In
   practice `circulationEnabled` defaults to 0 (`api.py:1216`, `api.py:1232`), so the branch at
   `handlers.py:1747` is simply not taken and the whole geometry half is GUI-only today.
9. `plot()` at `handlers.py:103` and `handlers.py:117` calls `plt.show()` (`circulation.py:956`) on the
   same nominally-server path. Another reason the circulation flow is not server safe as written.

## Coupling (what breaks if you change this)

- `Room` field names and the y-up convention are hard-wired into `handlers.py:92-99` (construction) and
  `handlers.py:141-144`, `handlers.py:187-191`, `handlers.py:282-286` (read back). Flipping the y
  convention would require changing 636-650, 811-822 and 838-839 together.
- `self.dimensions` layout `[width, height]` (840) is consumed by `handlers.py:235-249`, which mutates it
  in place before regenerating a minimum dimensioned floorplan. Changing the key or ordering breaks that
  block.
- `dimension_constraints` has two different layouts depending on mode (850-855 vs 876-879), matched to
  `handlers.py:633` and `handlers.py:524`. Any reordering must be done in both places at once.
- `is_dimensioning_successful` is the entire contract for feasibility, consumed at `handlers.py:299`,
  `handlers.py:306` and then `handlers.py:544`, `handlers.py:645`, `handlers.py:702`. Making the checks
  revert geometry instead of just flagging would change what those branches see.
- The corridor ordering contract (`start+1 .. end`, 475) depends on the graph half numbering corridor
  vertices in BFS order starting at `m = len(graph)` (`circulation.py:279-288`). If the graph half ever
  emits non-contiguous or non-BFS ids, the `range()` loop and the "skip the entry corridor" trick both
  break silently.
- `temp_push_states` / `done_rooms` never being reset means any code that reuses a `circulation` object
  for a second `adjust_RFP_to_circulation` (as `handlers.py:262` does) inherits stale state.
- `gplan_backend/GPLAN/GPLAN/circulation.py` is the same file consumed as a submodule; any edit here must
  land in the `nitantupasani/gplan_engine` source of truth.

## Dead Or Duplicated Code

- `Point` (14-17) and `Edge` (19-23): never instantiated. The `Point(` hits elsewhere in the tree all
  resolve to a different class (see Data Structures above); `Edge(` has no hits at all.
- `Room.height` (32) and `Room.width` (33): never read; stale after `push_edges`.
- `circulation.disp_rel_push` (80-87): defined, never called (grep over both trees returns only the two
  definitions).
- `self.pushed_stack` (59) and `self.circulations_adjacency_list` (60): assigned in `__init__` and never
  touched again.
- `self.is_optimal` (65): set by `handlers.py:113`, never read inside `circulation.py`.
- `max_width`, `max_height`, `max_ar` in `check_dimensions_feasibility` (851-855) and `plot_width`,
  `plot_height` in `check_mindim_feasibility` (878-879): unused locals, so those constraints are silently
  not re-checked after circulation.
- The `'n'` entries in `done_rooms` (715, 721, 727, 733, 740, 746, 752, 758): appended as tuples but every
  guard checks for a list tagged `'c'` (712 etc.), so they can never match. Write-only.
- `axis[1]` (694): computed at 685/690, never read.
- Commented-out step 3 of the graph half at 431-441 (adjacent to the section boundary) and the commented
  `required_corridors` line at 463.
- `wheel_graph` (894), `complete_graph` (921), `is_subgraph` (958): unreferenced by live code.
- `main()` (978) and all nested test functions (979, 990, 1030, 1103, 1138, 1180, 1228, 1266): test
  scaffolding, unreachable via import. Five of the seven tests are stale against the current constructor
  signature (1022, 1045, 1063, 1081, 1099, 1135, 1170, 1212); `make_graph` (979) is a helper, not a test.
- Duplicate module: `GPLAN/GPLAN/source/circulation/circulation.py` (872 lines) contains an older copy of
  the same class (`add_corridor_between_2_rooms` at its line 315, `find_common_edges` at 378, `push_edges`
  at 550). Its only importer is `GPLAN/GPLAN/source/multiple_circ.py:10` (`import circulation`, a bare
  top-level import that would not resolve under the `GPLAN.` package layout), and `multiple_circ` itself
  has no importers. Both are dead. `GPLAN/custom_circ_entry.py` (250, 270, 279, 285, 286, 298) is a third
  stale copy of the test scaffolding.
- Whole-tree duplication: `gplan_backend/GPLAN/GPLAN/circulation.py` is a byte-level sibling of this file
  (submodule checkout), so every finding applies twice.

## Open Questions

1. Termination of `find_common_neighbors` is not proven by the code. Is there an argument (planarity of
   the PTPG plus the axis test at 711-758) that guarantees the recursion at 775-785 cannot revisit a pair
   through a longer cycle, or has it simply never been hit in practice? A `RecursionError` here would
   surface as a 500 with no useful message.
2. Was line 819 (`rel_push_L` in the S/T branch) ever intentional? Every symmetric branch uses the
   matching field, so it reads as a copy-paste bug. Fixing it is safe today (the clamp domain
   `{0, +/-0.5*thickness}` at 34-37 and 800-822 makes both spellings evaluate to `-0.5*thickness`), so the
   only question is whether to correct it now or leave it as a trap for whoever later widens that domain.
3. Should the feasibility checks revert rather than flag? Today the geometry is committed before the
   check (505-506 then 510) and the non-dimensioned mode never checks at all, so "corridor inserted" and
   "corridor is legal" are independent outcomes.
4. Is the minimum dimensioned circulation path expected to work at all? `handlers.py:512` and
   `handlers.py:669` unpack five values from a function that returns six in both branches
   (`mindimensiongui.py:22` and `:157`). In the GUI path, where `gclass` is a real object, that is an
   unconditional `ValueError`; on the API path the branch dies earlier still, on `gclass.open`
   (`handlers.py:504`, `handlers.py:661`). Other call sites of the same helper do unpack six
   (`handlers.py:1801`, `handlers.py:2253`), so the helper grew a sixth return value and these two circulation
   call sites were never updated, or these branches are simply abandoned.
5. The knowledge graph (`graphify explain "circulation"`) lists exactly the same methods at the same line
   numbers as the source, so there is no disagreement to record. It has no opinion on liveness of
   `main()` or on the duplicate under `source/circulation/`.
