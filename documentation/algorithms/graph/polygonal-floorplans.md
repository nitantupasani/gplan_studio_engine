# Dossier: polygonal floorplan package (`GPLAN/GPLAN/source/polygonal/`)

Scope: `poly.py`, `lshape.py`, `newcoord.py`. `canonical.py` internals are owned by the sibling
`canonical-order-family` task; only its call surface is documented here, with anchors.

All paths are absolute. All line numbers were read in this session from
`C:\Users\nitant\Documents\GPLAN_Revamp\GPLAN\...` (the `gplan_backend\GPLAN\...` tree is a
byte-identical second copy of the same files at the same line numbers, see Dead Or Duplicated Code).

---

## Purpose

The polygonal package generates floorplans whose **outer boundary is a non-rectangular polygon**
(pentagon, hexagon, or a user-drawn custom outline) instead of the axis-aligned rectangle produced by
the mainline `floorplangen` / `dual.py` pipeline.

It does this by a **canonical-order incremental dissection**: a canonical ordering of the input planar
graph is computed (`polygonal/canonical.py`), and then rooms are carved out of the polygon one at a
time, in canonical order, by cutting the current active front. Rooms are stored as explicit corner
lists (`Room.coords`), not as `(x, y, w, h)` rectangles.

Two auxiliary pieces live in the same package:

- `newcoord.py` (`NewCoordinateAlgorithm`, `C:\Users\nitant\Documents\GPLAN_Revamp\GPLAN\GPLAN\source\polygonal\newcoord.py:8`): a **post-hoc wall-move / "Limits"** algorithm. It is not a floorplan generator and does not consume a canonical order. It takes an already-drawn floorplan, a chosen room, a chosen wall, a direction and a shift distance, and rewrites the polygon vertex lists of that room and every adjacent room.
- `lshape.py` (`C:\Users\nitant\Documents\GPLAN_Revamp\GPLAN\GPLAN\source\polygonal\lshape.py:26`): **dead code**. See Dead Or Duplicated Code.

---

## Where It Sits In The Pipeline

### The `poly` command chain (Tkinter desktop only)

```
main.py:55-56          gclass.command == "poly"  ->  handle_poly(ui, graph, True, gclass)
handlers.py:1499       def handle_poly(ui, graph, drawGUI=False, gclass=None)
handlers.py:1502-1503    graph.polyonalinput(gclass.canonicalObject, gclass.v1, gclass.v2,
                                             gclass.vn, gclass.po, ui.get_edges(), gclass.debugcano)
inputgraph.py:849-850    def polyonalinput(...): cano.runWithArguments(self.nodecnt, v1, v2, vn,
                                                                      priority_order, self, edge_set, debug_cano)
polygonal/canonical.py:95  def runWithArguments(...)  -> fills self.graph_data, calls canonical_order()

handlers.py:1505-1506    if drawGUI: drawFunction(ui, graph, origin, ui.get_roomNames(), isPoly=True, gclass=gclass)
handlers.py:41,50-56       drawFunction -> draw.draw_poly(gclass.canonicalObject.graph_data, ...,
                                                          gclass.outer_boundary, gclass.shape, graph.matrix)
pythongui/drawing.py:273   def draw_poly(...)
pythongui/drawing.py:291     db = poly.dissected(graph_data, pen, color_list, shape, adj_mat, innerBoundary)
polygonal/poly.py:20/22      class dissected.__init__  -> the geometry construction
```

**Answer to question 1, precisely:**

- `InputGraph.polyonalinput` is at `C:\Users\nitant\Documents\GPLAN_Revamp\GPLAN\GPLAN\source\inputgraph.py:849` with exactly the stated parameters (verified by reading). Its **entire body is one line**, `inputgraph.py:850`, which calls `cano.runWithArguments(...)`.
- **`polyonalinput` does NOT call into `poly.py`.** `poly.py` is reached only through the *drawing* side of `handle_poly`: `handlers.py:1506` -> `handlers.py:51` (`draw.draw_poly`) -> `drawing.py:291` (`poly.dissected`). `handlers.py:1` imports `GPLAN.source.polygonal.poly as poly`, but the only `poly.` use in `handlers.py` is `poly.Room()` at `handlers.py:1577` inside `handle_limits`, not `poly.dissected`.
- **`polyonalinput` is called from `handlers.py:1502`, inside `handle_poly`.** It is NOT called from `api.py`.
- **`handle_poly` itself is called from exactly one place: `C:\Users\nitant\Documents\GPLAN_Revamp\GPLAN\main.py:56`.** A repo-wide grep for `handle_poly` outside `gplan_backend/` returns only the definition (`handlers.py:1499`) and that one call site. `api.py` dispatches `handle_letter_shape`, `handle_multiple_l`, `handle_staircase_shaped`, `handle_single_oc`, `handle_single`, `handle_door_connectivity`, `handle_multiple_oc`, `handle_multiple`, `handle_space_optimization`, `handle_ga_optimization` (grep of `handle_` in `api.py`), and **never `handle_poly` or `handle_limits`**.

**Net reachability verdict:** the whole polygonal package is reachable **only from the legacy Tkinter
desktop entry point `main.py`**, never from the HTTP `api.py` surface. From the deployed backend's
point of view (`api.py`), `poly.py`, `polygui.py`, `newcoord.py`, `limits.py`, `draw.py` and
`polygonal/canonical.py` are all dead. They are not orphan files (main.py wires them), so I am not
calling `poly.py`/`newcoord.py` dead outright, but they are **API-dead**.

### The `limits` command chain (also Tkinter desktop only)

```
main.py:57-58          gclass.command == "limits"  ->  handle_limits(ui, graph, True, gclass)
handlers.py:1509       def handle_limits(...)
handlers.py:1516-1517    reads ./saved_files/input_to_limits.json  (rectangular floorplan dumped earlier)
handlers.py:1577-1586    rebuilds each rectangle as a poly.Room() with 4 corner tuples
handlers.py:1603         lim.LimitsAlgorithm(gclass.side, gclass.room_limits, rooms, adj_matrix, s_dir, dist)
handlers.py:1615         nc.NewCoordinateAlgorithm(exact_RoomSet, newRoomSet, s_dir, dist,
                                                   limits_instance.coords_input1, limits_instance.coords_input2,
                                                   gclass.side, rooms[gclass.room_limits])
handlers.py:1626,1631    consumes newCoordsInstance.circularTraversalOfSelectedRoomForMain()
                         and newCoordsInstance.adjrooms[k].coord()
```

Note this chain **never touches `poly.dissected`**. `handle_limits` reuses only the `poly.Room`
container class (`poly.py:10`). So `newcoord.py` operates on **rectangular** floorplans produced by
the mainline dual pipeline, not on `dissected` output.

---

## Entry Points (file:line)

| Anchor | Symbol | Role |
| --- | --- | --- |
| `GPLAN\main.py:56` | `handle_poly(ui, graph, True, gclass)` | only caller of the polygonal generator |
| `GPLAN\main.py:58` | `handle_limits(ui, graph, True, gclass)` | only caller of the limits/newcoord path |
| `GPLAN\GPLAN\handlers.py:1499` | `handle_poly` | orchestrates canonical order + polygonal draw |
| `GPLAN\GPLAN\handlers.py:1502` | `graph.polyonalinput(...)` | canonical order only |
| `GPLAN\GPLAN\handlers.py:1509` | `handle_limits` | wall-move entry |
| `GPLAN\GPLAN\handlers.py:1615` | `nc.NewCoordinateAlgorithm(...)` | only construction site of `newcoord.py` |
| `GPLAN\GPLAN\source\inputgraph.py:849` | `InputGraph.polyonalinput` | thin delegator, body is line 850 only |
| `GPLAN\GPLAN\pythongui\drawing.py:273` | `draw_poly` | builds `innerBoundary` from `gclass.outer_boundary` |
| `GPLAN\GPLAN\pythongui\drawing.py:291` | `poly.dissected(...)` | only construction site of `poly.dissected` |
| `GPLAN\GPLAN\source\polygonal\poly.py:20` | `class dissected` | the polygonal construction itself |
| `GPLAN\GPLAN\source\polygonal\newcoord.py:8` | `class NewCoordinateAlgorithm` | wall-move / coordinate rewrite |
| `GPLAN\GPLAN\source\polygonal\lshape.py:26` | `LShapedFloorplan` | **no callers anywhere; module does not import** |
| `GPLAN\GPLAN\pythongui\gui.py:1703` | `gui_class.polygonal` | sets `v1/v2/vn/po/shape/outer_boundary`, `command="poly"` |
| `GPLAN\GPLAN\pythongui\gui.py:1837` | `gui_class.polygonal_inputbox` | builds `canonicalObject`, priority-order entry, debug checkbox |

---

## Data Structures

### `poly.Room` (`poly.py:10-18`)

```python
class Room:                      # poly.py:10
    def __init__(self):          # poly.py:11
        self.coords = []         # poly.py:12   ordered polygon corner list
        self.leftDisecDone  = False   # poly.py:13
        self.rightDisecDone = False   # poly.py:14
        self.disecAllowed   = True    # poly.py:15
        self.noOfSides = 0            # poly.py:16
    def coord(self):             # poly.py:17
        return self.coords
```

Invariant maintained by the construction (see Algorithm Walkthrough): **`coords[0]` is the left end
of the room's current active front and `coords[1]` is the right end**; the remaining entries walk the
rest of the polygon. This is what the left/right disambiguation at `poly.py:196-205` relies on
(`if Room0.coords[1] == Room1.coords[0]: leftRoom = Room0`).

Flag status:
- `disecAllowed` is set `False` on the two initial flanking rooms (`poly.py:66,75,94,105,125,135`) and read at `poly.py:211`.
- `rightDisecDone` is written at `poly.py:273` and read at `poly.py:211`.
- `leftDisecDone` is written at `poly.py:330` and **never read anywhere** (repo-wide grep).
- `noOfSides` is **never written or read outside `__init__`** (repo-wide grep). Dead field.

### `dissected` instance state (`poly.py:22-53`)

| Anchor | Field | Meaning |
| --- | --- | --- |
| `poly.py:28` | `self.adj_mat` | stored, **only consumer is the commented-out `find_limits` call at `poly.py:54`**; effectively unused |
| `poly.py:31` | `self.noOfNodes` | `len(graph_data['iteration'])`, i.e. `InputGraph.nodecnt` |
| `poly.py:32` | `self.scale` | `0.5 * noOfNodes / 10`, drawing scale |
| `poly.py:33-34` | `divFactor_num=4, divFactor_den=5` | cut depth fraction: a horizontal cut goes 4/5 of the way from the active front down to the deepest usable y |
| `poly.py:35` | `self.correctCanonicalOrder` | `graph_data['currentCanonicalOrder'][noOfNodes-1]`, the final row = map original-vertex-index -> canonical position |
| `poly.py:36` | `self.coordinatepoints` | dict of polygon vertex coords, only populated for Pentagon/Hexagon |
| `poly.py:37` | `self.innerBoundary` | the user polygon; **default value is a hard-coded hexagon literal in the signature** (`poly.py:22`) |
| `poly.py:38` | `self.outerBoundary` | offset ring built by `polygui.createCustom` (`polygui.py:213-251`) |
| `poly.py:39` | `self.lowestPointIndex` | index of the lowest inner-boundary point, returned by `createCustom` (`polygui.py:251`) |
| `poly.py:40` | `self.rooms` | `list[Room]`, **indexed by canonical position**, shared by reference with `PolyGUI` (`poly.py:43`) |
| `poly.py:41` | `self.outerPath` | `[0, 2, 1]` initially: the left-to-right sequence of canonical positions currently on the active outer front |

### `graph_data` (produced by `polygonal/canonical.py`, consumed by `poly.py` and `polygui.py`)

Created at `canonical.py:178-180`; keys `iteration`, `marked`, `neighbors`,
`currentCanonicalOrder` (n x n), `indexToCanOrd`.

Consumption points in the three files under review:
- `poly.py:31` `graph_data['iteration']` -> node count
- `poly.py:35` `graph_data['currentCanonicalOrder'][n-1]` -> final canonical order array
- `poly.py:162-163` `graph_data['neighbors'][i]` -> neighbor list of the vertex at canonical position `i`
- `polygui.py:39` `graph_data['indexToCanOrd'][room]` -> colour lookup

`graph_data['neighbors']` is built by appending one list per canonical iteration
(`canonical.py:298`, inside `updateGraphData`), then appending `[0]` (`canonical.py:266`) and `[]`
(`canonical.py:267`) and reversing (`canonical.py:268`), so that after the reverse `neighbors[k]` is
the neighbor list of canonical position `k`. `poly.py:160` starts at `i = 3`, skipping the three
preplaced rooms.

### `NewCoordinateAlgorithm` state (`newcoord.py:9-16`)

| Anchor | Field | Supplied by `handlers.py:1615` |
| --- | --- | --- |
| `newcoord.py:10` | `exact_RoomSet` | list of adjacent room **indices** (labels for printing only) |
| `newcoord.py:11` | `s_dir` | `"Left"/"Right"/"Up"/"Down"` from the direction dropdown |
| `newcoord.py:12` | `shift_value` | shift distance |
| `newcoord.py:13` | `adjrooms` | `list[poly.Room]` of rooms adjacent to the selected room |
| `newcoord.py:14` | `opti` | `gclass.side` (0..3), which wall of the selected room was picked |
| `newcoord.py:15` | `originalRoom` | `rooms[gclass.room_limits]`, the selected room, **mutated in place** |
| `newcoord.py:16` | `self.run(adjrooms, x, y)` | runs immediately from `__init__` |

`x`, `y` are `limits_instance.coords_input1/2` (`limits.py:64-74`), the two endpoints of the chosen
wall.

---

## Algorithm Walkthrough

### `poly.py` function inventory, in file order

| Line | Symbol | One-line role |
| --- | --- | --- |
| `poly.py:10` | `class Room` | polygon container: corner list + dissection flags |
| `poly.py:11` | `Room.__init__` | initialises `coords` and the four flags |
| `poly.py:17` | `Room.coord` | accessor returning `self.coords` (used by `newcoord.py` and `limits.py`) |
| `poly.py:20` | `class dissected` | the whole polygonal generator; has no public methods beyond the two below |
| `poly.py:22` | `dissected.__init__` | seeds boundary geometry via `PolyGUI`, runs `mainDisectionFunction`, then draws |
| `poly.py:57` | `createDefaultDisectionsforPentagon` | hard-codes rooms 0,1,2 from `coordinatepoints[1..11]` |
| `poly.py:85` | `createDefaultDisectionsforHexagon` | hard-codes rooms 0,1,2 from `coordinatepoints[1..13]` |
| `poly.py:116` | `createDefaultDisectionsforCustom` | builds rooms 0,1,2 from `innerBoundary`/`outerBoundary` and `lowestPointIndex` |
| `poly.py:150` | `mainDisectionFunction` | the incremental placement loop for canonical positions 3..n-1 |

That is the complete list; `poly.py` defines nothing else.

### Main construction, step by step

**Step 0 (`poly.py:44-51`).** Boundary seeding is delegated to `PolyGUI`
(`polygui.py:7`). For `shape == "Pentagon"` / `"Hexagon"` the polygon vertices are generated by turtle
walks (`polygui.py:77`, `polygui.py:145`). Otherwise `polygui.createCustom` (`polygui.py:213`) takes
the user's `innerBoundary` and produces an `outerBoundary` ring offset by a hard-coded 50 units
(`polygui.py:237,241,246`), returning `lowestPointIndex` (`polygui.py:251`).

**Step 1 (`poly.py:150-156`).** Three rooms are always preplaced, matching canonical positions 0
(= `v1`, left band), 1 (= `v2`, right band) and 2 (the interior). In the custom case
(`poly.py:116-147`) Room1 is the left strip between inner and outer boundary, Room2 the right strip,
Room3 the whole inner polygon. Rooms 0 and 1 get `disecAllowed = False`.

**Step 2, the loop (`poly.py:160-417`).** For each canonical position `i` from 3 to `n-1`:

1. **Read the neighbours** (`poly.py:162-168`). `neighborListIndex = graph_data['neighbors'][i]` is in
   *original* vertex indices; each is mapped through `correctCanonicalOrder` into a canonical position
   (`poly.py:167`). Because `self.rooms` is indexed by canonical position, `self.rooms[j]` is directly
   the room of neighbour `j`.
2. **Locate them on the active front** (`poly.py:170-174`). Each neighbour's position in
   `self.outerPath` is collected; `l = min(...)`, `r = max(...)`. This is the classic canonical-order
   invariant: the neighbours of the next vertex form a contiguous run on the current outer path.
3. **Update the outer path** (`poly.py:176-186`). `newPath = outerPath[0..l] + [i] + outerPath[r..end]`.
   The consumed interval `(l, r)` is replaced by the single new vertex. `leftCanOrd = outerPath[l]`,
   `rightCanOrd = outerPath[r]` (`poly.py:183-184`) are captured **before** the replacement.
   This list, plus each room's `coords[0]`/`coords[1]` active-front pair, is the entirety of the
   "growing outer boundary" state. There is no separate boundary polygon object.
4. **Branch on degree** (`poly.py:187` vs `poly.py:332`).

   - **Degree exactly 2 (`poly.py:187-330`).** The new vertex sits between two consecutive boundary
     vertices, so it cannot span an edge; it must be *carved out of one existing room*. Left/right is
     decided by shared-corner matching (`poly.py:196-205`). Preference is a right-dissection of the
     left room if `disecAllowed and not rightDisecDone` (`poly.py:211`), otherwise a left-dissection
     of the right room (`poly.py:275-330`). Geometry:
     - `newActivePoint` is the **midpoint of the active front** at the same y (`poly.py:217`).
     - The cut depth `newYCoord` is `(initY*(den-num) + finalY*num)/den` = 4/5 of the way from the
       front down to `finalYCoord` (`poly.py:242-244`), where `finalYCoord` is the shallower of the
       two rooms' descending runs (`poly.py:227-242`).
     - `Point1 = (midX, newYCoord)`, `Point2 = (interpolatedX, newYCoord)` (`poly.py:254-255`). The
       interpolated x is a **linear interpolation along the existing polygon edge** at
       `poly.py:252`, which is what lets the cut land on a slanted boundary edge.
     - The donor room's `coords` are rebuilt (`poly.py:256-262`) and the new `Room` is appended
       (`poly.py:264-271`). `rightDisecDone` / `leftDisecDone` is then set.
   - **Degree >= 3 (`poly.py:332-417`).** The new vertex spans several boundary edges. A single
     horizontal cut at `newYCoord` (again 4/5 of the way down, `poly.py:348`) is applied. Every
     *strictly interior* neighbour (`j != leftCanOrd and j != rightCanOrd`, `poly.py:351`) is
     **truncated**: its polygon is replaced by only the part below `newYCoord`, with two new
     interpolated corners at the cut (`poly.py:353-376`). The new room is then assembled from
     `leftTop = rooms[leftCanOrd].coords[1]`, `rightTop = rooms[rightCanOrd].coords[0]`
     (`poly.py:379-382`), the right room's trailing corners, the two interpolated bottom corners
     `rightBot`/`leftBot` (`poly.py:402-405`), and the left room's corners (`poly.py:407-414`).

**Step 3 (`poly.py:53`).** `polygui.startDisection()` (`polygui.py:19-75`) walks `self.rooms` with the
turtle pen, filling each with `color_list[graph_data['indexToCanOrd'][room]]` (`polygui.py:39`).

### What makes the result polygonal rather than rectangular

Three things, all anchored:

1. The **seed boundary is a non-rectangle**: pentagon (`polygui.py:77`), hexagon (`polygui.py:145`),
   or an arbitrary user polygon (`polygui.py:213`); the default in the `dissected` signature is
   itself a 6-point hexagon literal (`poly.py:22`).
2. Every cut endpoint that lands on the boundary is produced by **linear interpolation along an
   existing, possibly slanted, polygon edge** (`poly.py:252`, `poly.py:308`, `poly.py:359`,
   `poly.py:366`, `poly.py:402`, `poly.py:403`). A rectangular pipeline would snap to an axis; this
   one inherits the boundary's slope.
3. Rooms are stored as **variable-length corner lists** (`poly.py:12`) and truncation appends
   arbitrarily many inherited corners (`poly.py:261-262`, `poly.py:373-375`, `poly.py:407-414`), so a
   room routinely ends with 5, 6 or more sides. Contrast the mainline dual pipeline, which emits four
   parallel arrays `room_x, room_y, room_width, room_height` (`inputgraph.py:833-838`).

### `priority_order` (question 3)

`priority_order` is a free-text string typed into the Tkinter entry bound to
`gui_class.priority_order` (`gui.py:178-179`, widget at `gui.py:1854`), read into `gclass.po` at
`gui.py:1709`, passed as the 5th positional argument at `handlers.py:1502`, forwarded verbatim by
`inputgraph.py:850`, and consumed **entirely inside `polygonal/canonical.py`**:

- `canonical.py:135-140`: if non-empty, it is parsed with `re.findall(r'\d+', priority_order)` into an
  int list, then `v1` and `v2` are removed from it if present.
- `canonical.py:231-237`: at every canonical-order step, the set of legal next vertices `poss_vertex`
  is computed; **if the head of `priority_order` is legal it is chosen as `vk` and popped**, otherwise
  the default `poss_vertex[0]` is chosen and `vk` is removed from `priority_order` if it appears
  there.

So `priority_order` is a **tie-breaking preference over the canonical order**, not a hard constraint:
an illegal preference is silently skipped. `poly.py` never sees `priority_order`; it only sees the
resulting order through `graph_data`. Its influence on the geometry is therefore entirely indirect:
a different canonical order means a different `outerPath` evolution and a different room-carving
sequence.

### `debug_cano` (question 3)

`gclass.debugcano` is a `tk.IntVar` created at `gui.py:180` and bound to the "Show Canonical Order"
checkbutton at `gui.py:1884`. It flows `handlers.py:1503` -> `inputgraph.py:850` -> `canonical.py:95`,
is stored at `canonical.py:124` (`self.debugCano = debugCano`, overwriting the default `tk.IntVar`
from `canonical.py:22`), and is read at **exactly one place**: `canonical.py:290`,

```python
plt.savefig("./source/polygonal/lastcanonicalorder.png")   # canonical.py:289  -- unconditional
if self.debugCano.get() == 1:                              # canonical.py:290
    plt.show()                                             # canonical.py:291
```

**Verdict: debug output only.** It changes no data structure and no geometry. The PNG is written
unconditionally; the flag only decides whether a blocking matplotlib window is opened. The one
non-cosmetic side effect is that `plt.show()` blocks the Tk main loop until the window is closed, and
the `savefig` path is **relative to the process cwd** (`"./source/polygonal/..."`), which is wrong
whenever the process is not started from `GPLAN/GPLAN/`.

### `newcoord.py` (question 5)

**It does not implement a canonical-order coordinate assignment.** It implements an *incremental wall
move* on an existing floorplan. Input, from `handlers.py:1615`:

- `originalRoom`: the selected room, as a `poly.Room` rebuilt from the mainline rectangular output
  (`handlers.py:1577-1586`).
- `adjrooms`: the rooms adjacent to it, selected from the adjacency matrix (`handlers.py:1608-1611`).
- `x`, `y`: the two endpoints of the chosen wall, computed from `gclass.side` by
  `LimitsAlgorithm.wall_input` (`limits.py:62-74`).
- `s_dir`, `shift_value`: direction and distance; `opti = gclass.side`.

Flow: `__init__` calls `run` immediately (`newcoord.py:16`); `run` (`newcoord.py:177-189`) maps
`"Left"/"Right"/"Up"/"Down"` to lowercase (`newcoord.py:179-186`), calls
`shiftAndUpdateCoordinates` (`newcoord.py:167-175`) which delegates to
`updateAdjacentRoomCoordinates` (`newcoord.py:106-165`), then rewrites the selected room's own
corners via `chosenRoomNewCoords` (`newcoord.py:191-196`).

`updateAdjacentRoomCoordinates` is the substance. For each adjacent room it:
- tests side-adjacency with the moved wall, branching on `self.opti` (`sideAdjacent`, `newcoord.py:58-79`);
- tests whether `x` (and separately `y`) lies on that room's perimeter using a **perimeter-equality
  trick**: it recomputes the perimeter with `x` spliced in and compares against the plain perimeter
  (`isInPerimeter`, `newcoord.py:45-56`);
- if the endpoint coincides with an existing corner, that corner is translated (`moveCoordinate`,
  `newcoord.py:98-99`); if it lies strictly inside an axis-aligned edge, **two new corners are
  inserted** (`insertCoordinate`, `newcoord.py:101-104`, called at `newcoord.py:119-120`, `125-126`,
  `143-144`, `149-150`), one shifted and one not, which is exactly how a straight wall becomes a step;
- any corner lying strictly between `x` and `y` on the moved wall is translated
  (`newcoord.py:128-133`, `152-157`, `158-164`).

**Outputs, and how they differ from `floorplangen/dual.py`:**

- `dual.get_coordinates` (`dual.py:235`, returns at `dual.py:322`) returns `room_x, room_y`: two flat
  arrays of **rectangle origins**, derived from the encoded REL matrix plus precomputed
  `room_width`/`room_height`. Rooms are implicitly 4-sided and axis-aligned; the caller rounds and
  stores them at `inputgraph.py:838-842`.
- `NewCoordinateAlgorithm` returns nothing. It **mutates polygon corner lists in place**:
  `self.adjrooms[j].coords` (rebound at `newcoord.py:168` from the deep copy made at
  `newcoord.py:107`) and `self.originalRoom.coords` (`newcoord.py:194,196`). Rooms can gain corners
  and become L-shaped or stepped. The consumer reads them back as `newCoordsInstance.adjrooms[k].coord()`
  at `handlers.py:1631` and stores them into `new_graph.final_traversal` (`handlers.py:1633`), which
  is a **circular-traversal representation**, not `(x, y, w, h)`.
- The one derived accessor, `circularTraversalOfSelectedRoomForMain` (`newcoord.py:18-39`, called at
  `handlers.py:1626`), is inconsistent with the rest: it rebuilds a **rectangle** from
  `originalRoom.coords[0]`, `[3]`, `[1]` (`newcoord.py:28-31`) and returns that four-corner list
  (`newcoord.py:39`), discarding any extra corners the wall move just created. The `return` sits at the
  same indentation as the `for` at `newcoord.py:33`, so it runs after the loop, not inside it. See
  Failure Modes.

---

## Invariants And Preconditions

Question 6, answered from what is checked and what is conspicuously absent.

**Checked:**

1. **Planarity** of the raw input graph: `canonical.py:85` (`nx.check_planarity`) inside
   `displayInputGraph`, which is called at `gui.py:1841` before the command is dispatched. Note the
   check `return False`s but the caller at `gui.py:1841` **ignores the return value**, so a non-planar
   graph proceeds anyway. `gui.py:1889-1890` contains a commented-out error dialog and a `# TODO NOt
   working if error`.
2. **Connectivity**: `main.py:34-35` runs `connect_graph.one_connected(graph.matrix)` before dispatch,
   for every command including `poly`.
3. **CIP count <= 5** in `lshape.py:27-29` (dead code, see below).
4. **Wall-move legality** in `limits.py`: `LimitsAlgorithm.proceed` (`limits.py:12`, set at
   `limits.py:28`, cleared at `limits.py:33,38,43,48`) gates the whole `newcoord.py` call at
   `handlers.py:1605`.

**Assumed but never checked (this is the load-bearing part):**

1. **Triangulation / maximal planarity.** `polyonalinput` (`inputgraph.py:849-850`) does **no**
   triangulation. Compare `irreg_multiple_dual` in the same class, which explicitly biconnects
   (`inputgraph.py:886-891`), triangulates (`inputgraph.py:899-905`) and eliminates separating
   triangles (`inputgraph.py:915-929`). None of that runs on the polygonal path. The intent was there:
   `canonical.py:21` declares `self.vertex_added_to_triangulate = False  # for dealing with the
   not-fully triangulated constraint! - not implemented so far`, and the whole edge-count test
   `if (self.G.number_of_edges() != (3*noOfNodes - 6))` with its `isFTPG = False` fallback is
   **commented out** at `canonical.py:146-148`. So: the algorithm needs a fully triangulated planar
   graph, and nothing enforces it.
2. **Biconnectivity.** Never checked on this path. `main.py:34` only guarantees 1-connectivity.
3. **Separating triangles.** Never checked. `st.handle_STs` is called on the letter-shape path
   (`Lshaped.py:26-28`) and the mainline path (`inputgraph.py:929`) but **not** on the polygonal path.
4. **`v1`, `v2`, `vn` are a valid outer face.** They are typed by the user into three raw Tk entries
   (`gui.py:1848-1853`) and used unvalidated (`canonical.py:115-121` indexes `self.node_coordinate[v1]`
   and `[v2]` directly). All the code that would have *derived* or *augmented* them is commented out
   (`canonical.py:126-176`).
5. **Contiguity of the neighbour run on the outer path.** `poly.py:173-174` takes only `min` and `max`
   of the neighbour indices in `outerPath` and assumes everything between them is also a neighbour.
   If the input is not properly triangulated / the order is not a true canonical order, this silently
   swallows non-neighbour rooms into the cut.
6. **Room 0/1/2 seeding matches the canonical order.** `poly.py:160` starts at `i = 3`, assuming
   `canonical.py` assigned `canord[v1] = 0` (`canonical.py:190`) and `canord[vn] = n-1`
   (`canonical.py:220`), and that `self.rooms` index == canonical position.
7. **`coords[0]`/`coords[1]` is the active front, left-then-right.** Never asserted; relied on at
   `poly.py:196-205`, `213-214`, `278-279`, `336`, `379-380`.
8. **Monotone descent from the active front.** The `finalYCoord` scans (`poly.py:227-240`,
   `poly.py:341-345`) stop at the first non-decreasing y, i.e. they assume each room descends
   monotonically from its front.
9. **`newcoord.py` assumes rectilinear rooms.** `sideAdjacent` (`newcoord.py:58-79`) and
   `isInPerimeter` (`newcoord.py:49`) only ever compare `x`-equal or `y`-equal, so a slanted edge is
   invisible to them. This is consistent with `newcoord.py` only ever being fed the rectangular
   floorplan rebuilt at `handlers.py:1577-1586`, and is a reason it must **not** be pointed at
   `dissected` output.

---

## Failure Modes

1. **`newCoordtoConsider2` can be unbound.** `poly.py:353` initialises `newCoordtoConsider1 = 0`
   before its scan, but the mirrored scan at `poly.py:361-364` has **no initialisation**; if no corner
   satisfies `coords[k][1] < newYCoord`, `poly.py:365` (`print(newCoordtoConsider2)`) raises
   `UnboundLocalError`, or worse reuses a stale value from a previous loop iteration of `j`.
2. **`newCoordtoConsider1` silently defaults to 0.** At `poly.py:384-388` and `poly.py:353-357`, a
   scan that finds nothing leaves the index at 0, and `poly.py:403` then indexes
   `coords[newCoordtoConsider2 - 1]` which wraps to `coords[-1]`. No exception, wrong geometry.
3. **No `status` / failure return.** `dissected.__init__` returns nothing and `handle_poly`
   (`handlers.py:1499-1506`) has no error path. `handle_poly` measures `start`/`end`
   (`handlers.py:1500,1504`) and never uses them.
4. **Non-triangulated input degrades silently.** Per Invariants item 1, `min`/`max` over
   `indexInPathArray` (`poly.py:173-174`) will happily span non-neighbour rooms.
5. **Turtle/Tk hard dependency.** `dissected` requires a live turtle `pen` (`poly.py:23-24`) and
   `polygui.startDisection` drives it directly (`polygui.py:36-50`). There is no headless path, which
   is a large part of why this is not exposed through `api.py`.
6. **`circularTraversalOfSelectedRoomForMain` returns the wrong thing.** It reconstructs an
   axis-aligned **rectangle** from `coords[0]/[3]/[1]` (`newcoord.py:28-31`) even though
   `chosenRoomNewCoords` (`newcoord.py:191-196`) may have just turned the selected room into a
   non-rectangle, and it is called at `handlers.py:1626` for exactly the room that was just modified.
   Any step or inserted corner produced by the wall move is therefore dropped from what the caller
   stores. The loop at `newcoord.py:33-38` is not the problem: `return list_` at `newcoord.py:39` is a
   sibling of the `for` (both at indent 8), so it runs after the loop finishes. The only latent issue
   there is that `list_` is bound inside the loop, so an empty `graph['room_x']` would raise
   `UnboundLocalError`; `newcoord.py:28` always appends exactly one element, so the loop always runs
   exactly once and the binding always exists.
7. **`plt.savefig` uses a cwd-relative path.** `canonical.py:289` writes
   `"./source/polygonal/lastcanonicalorder.png"`; running from any other directory raises or writes to
   the wrong place, on **every** polygonal run, not just debug runs.
8. **`handle_limits` reads a file that may not exist.** `handlers.py:1516-1519` wraps the read in a
   bare `except` that only shows a warning and then falls through into `input_json.items()` at
   `handlers.py:1522` with an empty dict, leading to a `KeyError` at `handlers.py:1536`.

---

## Coupling (what breaks if you change this)

- **`graph_data` schema.** `poly.py:31,35,162` and `polygui.py:12,39` index `iteration`,
  `currentCanonicalOrder`, `neighbors`, `indexToCanOrd` by exact key and by exact layout (final row of
  `currentCanonicalOrder`; `neighbors` reversed and offset by 2). Any change to `updateGraphData`
  (`canonical.py:293-300`) or to the post-loop `neighbors` fixup in `canonical_order` breaks `poly.py`
  silently, with a wrong-but-plausible drawing.
- **`Room` corner ordering.** `poly.py:196-205` and `poly.py:379-380` depend on `coords[0]`/`coords[1]`
  being the active front. `handlers.py:1581` deliberately reverses the corner list
  (`temp2 = [temp[0]] + temp[1:][::-1]`) to satisfy this same convention before handing rooms to
  `limits.py`/`newcoord.py`. Change one, you must change both.
- **`poly.Room` is a shared vocabulary type.** It is constructed in `handlers.py:1577` and consumed by
  `limits.py:64-74`, `newcoord.py:48,59,82,99,104`. Renaming `coord()` or `coords` breaks the Limits
  feature even though that feature never touches `dissected`.
- **`self.rooms` is shared by reference** between `dissected` and `PolyGUI` (`poly.py:40,43`); `PolyGUI`
  reads the list after `mainDisectionFunction` mutated it (`poly.py:52-53`). Replacing the list rather
  than mutating it would silently draw nothing.
- **`priority_order` string format.** Parsed with `re.findall(r'\d+', ...)` at `canonical.py:136`, so
  any delimiter works but negative numbers and multi-digit-with-separator inputs behave surprisingly.
- **`gclass` attribute surface.** `handle_poly` reads `canonicalObject`, `v1`, `v2`, `vn`, `po`,
  `debugcano` (`handlers.py:1502-1503`), `pen`, `outer_boundary`, `shape` (`handlers.py:51-56`).
  `handle_limits` additionally reads `side`, `room_limits` and eight dropdown/shift fields
  (`handlers.py:1590-1601`). These are set only by the Tk GUI (`gui.py:1703-1713`), which is why
  wiring either handler into `api.py` would require synthesising a `gclass`.
- **Two-tree duplication.** Every anchor above exists identically under
  `C:\Users\nitant\Documents\GPLAN_Revamp\gplan_backend\GPLAN\GPLAN\...`. Editing one tree without the
  other diverges the deployed backend from the engine source.

---

## Dead Or Duplicated Code

### `polygonal/lshape.py` is dead. Plainly. (Question 4)

**It cannot even be imported.** Its imports at `lshape.py:6-15` are bare top-level module names:
`cip`, `operations as opr`, `news`, `shortcutresolver as sr`, `contraction as cntr`,
`expansion as exp`, `drawing as draw`, `ptpg`, `flip`. In the current package layout these live at
`GPLAN/source/boundary/cip.py`, `GPLAN/source/graphoperations/operations.py`,
`GPLAN/source/boundary/news.py`, `GPLAN/source/irregular/shortcutresolver.py`,
`GPLAN/source/floorplangen/contraction.py`, `GPLAN/source/floorplangen/expansion.py`. There is **no
`ptpg.py` and no `flip.py` anywhere in the repo** (verified by `find`). So `import
GPLAN.source.polygonal.lshape` raises `ModuleNotFoundError` immediately.

**Nothing imports it.** A repo-wide grep for `lshape` outside `lettershape/` matches only a commented
line in `polygui.py:283`, unrelated marketing/test strings, and `api.py:1257,1314` where `'lshape'` is
a *caller string tag*, not a module reference. The project knowledge graph has no node for
`polygonal/lshape.py` at all (`graphify explain "polygonal/lshape.py"` -> "No node matching ... found").

**It also targets a dead object model.** It uses `graph.node_count` (`lshape.py:210,216,222,227`),
`graph.matrix[i][j]` with `graph.node_count`-sized loops, `opr.get_outer_boundary_vertices`
(`lshape.py:99,321`), `opr.ordered_outer_boundary` (`lshape.py:54,362,370`), `news.find_boundary_single`
(`lshape.py:362,370`), `cip.find_cip(graph)` (`lshape.py:45`), `sr.get_shortcut(graph)`
(`lshape.py:364`), `cntr.initialize_degrees/initialize_good_vertices` (`lshape.py:288-289`),
`exp.get_trivial_rel` (`lshape.py:293`) and `draw.construct_rdg` (`lshape.py:316`). The live code uses
`graph.nodecnt` (`Lshaped.py:407,414,421,426`), `opr.get_bdy` / `opr.ordered_bdy`
(`Lshaped.py:244,250`), `news.find_bdy` (`Lshaped.py:604,622`), `cip.find_cip(ordered_boundary,
shortcuts)` (`Lshaped.py:253`), `sr.get_shortcut(graph.matrix, graph.bdy_nodes, graph.bdy_edges)`
(`Lshaped.py:247`), `cntr.degrees`/`cntr.goodnodes` (`Lshaped.py:501,504`), `exp.basecase`
(`Lshaped.py:512`) and `rdg.construct_dual` (`Lshaped.py:536`). `polygonal/lshape.py` is a snapshot of
an **older API generation**.

### Conceptual diff: `polygonal/lshape.py` vs `lettershape/lshape/Lshaped.py`

They are **not two independent implementations**. `polygonal/lshape.py` is an **ancestor** of
`Lshaped.py`: same function names, same order, same algorithm skeleton, same comments in places. The
size gap (11.7 KB vs 24.5 KB) is what the live file added.

Functions present in **both**, essentially the same logic:

| `polygonal/lshape.py` | `lettershape/lshape/Lshaped.py` | Note |
| --- | --- | --- |
| `LShapedFloorplan` :26 | `LShapedFloorplan` :24 | live version adds ST elimination (:26-35), `trivialL` fallback (:45-47), and the canonical/`Canonical_L_Shaped` REL step (:64-71) |
| `find_cips` :44 | `find_cips` :236 | dead version calls `cip.find_cip(graph)`; live version computes triangles/boundary/shortcuts first |
| `find_triplet` :50 | `find_triplet` :258 | near-identical; dead version has the bug `(v,c) in H.edges` (missing call parens) at :80, fixed to `H.edges()` at Lshaped.py:290 |
| `find_paths` :94 | `find_paths` :305 | dead version builds the clockwise boundary by BFS over `outer_boundary_adj_mat` (:111-132); live version rotates `ordered_bdy` (:323-328). Dead version's :178 `path1.insert(list, 0)` has the insert arguments swapped |
| `path1_conditions` :194 | `path1_conditions` :389 | dead version's final test compares a **list** to 1 (`rightofB == 1`, :228); live version fixes it to `rightofB[i] == 1` (:427) |
| `connect_northeast` :235 | `connect_northeast` :434 | identical except `node_count` -> `nodecnt` |
| `add_edges` :250 | `add_edges` :454 | identical except `edge_count` -> `edgecnt` |
| `new_matrix` :256 | `new_matrix` :462 | identical (dead version is tab-indented) |
| `boundary_path_single` :262 | `boundary_path_single` :470 | live version adds the `ne not in path` guard (:472-475) |
| `get_rel` :286 | `get_rel` :498 | rewritten for the new contraction/expansion API |
| `get_floorplan` :308 | `get_floorplan` :531 | dead version calls `draw.construct_rdg`; live version calls `rdg.construct_dual` |
| `add_NESW` :318 | `add_NESW` :541 | same NESW-insertion logic, different boundary helpers |
| `find_cips_L_shaped` :354 | `find_cips_L_shaped` :593 | same structure, different helper signatures |
| `connect_news` :375 | `connect_news` :631 | **byte-for-byte the same 8 assignments** |

Present only in the **live** file: `trivialL` (:77), `multipleLshapedFloorplans` (:113),
`find_multiple_triplet` (:197). Present only in the **dead** file: nothing.

**Which one is reachable:** only `lettershape/lshape/Lshaped.py`. It is imported at `handlers.py:10`
and used at `handlers.py:945`, `handlers.py:969` (`LShapedFloorplan`) and `handlers.py:1019`
(`multipleLshapedFloorplans`). Those handlers are called from `api.py:1262,1268,1274,1280`
(`handle_letter_shape`) and `api.py:1320,1408` (`handle_multiple_l`). So **the L-shape endpoint uses
`lettershape/lshape/Lshaped.py`; `polygonal/lshape.py` has no endpoint and never runs.**

### Other dead / unused items in the three files

- `poly.py:2` `import tkinter as tk` -- unused.
- `poly.py:1,3,4,6` -- four commented-out imports, including a `find_limits` integration.
- `poly.py:28` `self.adj_mat` -- stored, only consumer is the commented `find_limits(self.adj_mat, self.rooms)` at `poly.py:54`.
- `poly.py:16` `Room.noOfSides` -- never read or written elsewhere.
- `poly.py:330` `rightRoom.leftDisecDone = True` -- written, never read.
- `poly.py:418-431` -- 14 lines of commented-out per-room turtle drawing, superseded by `polygui.startDisection`.
- `newcoord.py:1-5` -- `networkx`, `matplotlib.pyplot`, `tkinter`, `numpy`, `re` are all imported and none is used.
- `newcoord.py:18` `circularTraversalOfSelectedRoomForMain` builds a full `graph` dict of 8 keys and uses only 4 of them.
- `handlers.py:1684` references `newCoordsInstance.error_message` in a commented line; no such attribute exists on `NewCoordinateAlgorithm`.
- **Whole-tree duplication:** `C:\Users\nitant\Documents\GPLAN_Revamp\gplan_backend\GPLAN\GPLAN\source\polygonal\{poly,lshape,newcoord}.py` and `gplan_backend\GPLAN\GPLAN\handlers.py` are a second copy at identical line numbers (`gplan_backend/.../handlers.py:1502` and `:1615` match `GPLAN/.../handlers.py:1502` and `:1615`). Consistent with the recorded fact that `gplan_backend` consumes the engine as a submodule.

---

## Open Questions

1. **Is the `poly` command reachable in the shipped desktop build at all?** `main.py:56` is the only
   call site, and `main.py:80-83` is the `__main__` block. I did not verify whether the Tkinter
   "Polygonal Floorplans" button (`gui.py:1480`) is enabled in any shipped configuration, only that
   the wiring exists.
2. **Was `polygonal/canonical.py` ever meant to handle non-triangulated input?**
   `canonical.py:21` and the commented `isFTPG` block at `canonical.py:146-148` say yes in intent. I
   could not find any live code path that sets `vertex_added_to_triangulate` to `True`. Owner of the
   `canonical-order-family` dossier should confirm.
3. **Why does `dissected` accept `adj_mat` at all?** The only use is the commented `find_limits` at
   `poly.py:54`, suggesting a planned limits-on-polygonal-floorplans feature that was never finished.
   `limits.py` and `newcoord.py` both currently assume rectilinear rooms (`newcoord.py:58-79`), so
   that feature would need real work, not just uncommenting.
4. **`graphify` graph disagreement (minor).** The knowledge graph has nodes for `dissected`
   (`poly.py:20`) and `PolyGUI` (`polygui.py:7`) but **no node for `polygonal/lshape.py`**, and it
   places `dissected`/`PolyGUI` in community 74 with no edge to any `api.py` node. The code agrees
   with the second point (API-dead) and the graph's omission of `lshape.py` is consistent with that
   file being unimportable. No substantive conflict found; recording the omission for completeness.
5. **Is `poly.py`'s degree-2 branch correct when both candidate rooms are exhausted?**
   `poly.py:211` falls through to the right-room dissection without re-checking
   `rightRoom.disecAllowed` or `rightRoom.leftDisecDone`. I did not construct an input that reaches
   that state, so I cannot say whether it is unreachable by construction or a latent bug.
