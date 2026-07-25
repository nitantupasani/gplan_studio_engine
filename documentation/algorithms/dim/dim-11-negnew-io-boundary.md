# dim-11: Space Optimization API boundary (request -> negNew.FloorPlan -> response)

Scope: the input and output surfaces only. The placement/sizing algorithm inside `negNew.py`
(`place_rooms_with_constraints_optimized`, `compact_rooms*`, `enforce_minimum_adjacency`,
`expand_rooms_optimized`) is dim-10's subject and is deliberately not described here.

Files covered:
- `C:\Users\nitant\Documents\GPLAN_Revamp\GPLAN\GPLAN\api.py` (request parse + response build)
- `C:\Users\nitant\Documents\GPLAN_Revamp\GPLAN\GPLAN\handlers.py` (handler -> engine hand-off)
- `C:\Users\nitant\Documents\GPLAN_Revamp\GPLAN\Space_Optimization\boundary_utils.py` (polygon -> regions)
- `C:\Users\nitant\Documents\GPLAN_Revamp\GPLAN\Space_Optimization\negNew.py` (input/entry/output surfaces only)
- `C:\Users\nitant\Documents\GPLAN_Revamp\GPLAN\GPLAN\test_api_space_optimization_simple.py`
- `C:\Users\nitant\Documents\GPLAN_Revamp\GPLAN\documentation\space_optimization_api.md`

---

## Purpose

Turn a JSON request (`boundary` polygon or explicit `regions`, plus a room list with per-room
minimum width/height and a per-room expansion budget) into a placed set of axis-aligned room
rectangles, and serialize them back as JSON. Three separable jobs live at this boundary:

1. **Polygon -> rectangles**: `boundary_utils.decompose_boundary_into_rectangles` converts an
   arbitrary vertex list into a merged set of axis-aligned regions
   (`boundary_utils.py:41-159`).
2. **Dict -> object graph**: `handle_space_optimization` translates plain dicts into
   `FloorPlan` / `Room` objects by imperative method calls, one call per room and per constraint
   (`handlers.py:2696-2748`).
3. **Object graph -> dict**: the same handler walks `floor_plan.rooms` back into dicts and
   stashes them on a `GuiParameters` object, which `api.py` then reshapes into the HTTP response
   (`handlers.py:2776-2833`, `api.py:1590-1636`).

There is no serialization code in `negNew.py` at all. `negNew.py` imports only
`matplotlib`, `networkx`, `numpy`, `random`, `heapq`, `collections`, `ga_current`
(`negNew.py:1-8`); the string `json` does not appear anywhere in the file. All JSON handling is
in `api.py`; all dict-to-object marshalling is in `handlers.py`.

## Where It Sits In The Pipeline

```
HTTP JSON
  -> Documents.get_space_optimized_floorplan(request_data)          api.py:1458-1647
     -> boundary_to_regions(boundary, fixed_room_polygons)          api.py:26-49  (thin wrapper)
        -> boundary_utils.boundary_to_regions                       boundary_utils.py:162-177
           -> decompose_boundary_into_rectangles                    boundary_utils.py:41-159
     -> handle_space_optimization(ui, regions, rooms, ...)          handlers.py:2659-2843
        -> from negNew import FloorPlan                             handlers.py:2689
        -> FloorPlan(region_specs=regions, fixed_rooms=None)        handlers.py:2696 / negNew.py:220
        -> set_entrance_location / add_room / add_fixed_room
           / add_adjacency / add_non_adjacency                      handlers.py:2699-2748
        -> floor_plan.generate_layout(...)                          handlers.py:2751 / negNew.py:1675
        -> floor_plan.compact_rooms()                               handlers.py:2763
        -> floor_plan.evaluate_adjacency_score()                    handlers.py:2766 / negNew.py:786
        -> ui._set_output_data([output_data])                       handlers.py:2833
     -> response dict                                               api.py:1607-1636
```

`GuiParameters` is used purely as a mailbox between handler and API layer
(`api.py:1562-1563`, `GuiParameters.py:426-430`, `GuiParameters.py:384-387`); it carries no
dimensioning state on this path.

## Entry Points (file:line)

| Entry point | Location |
| --- | --- |
| Public API method | `api.py:1458` `Documents.get_space_optimized_floorplan(request_data)` (static) |
| Boundary wrapper (api-local) | `api.py:26` `boundary_to_regions(boundary, fixed_rooms=None)` |
| Boundary wrapper (shared) | `boundary_utils.py:162` `boundary_to_regions(boundary_coords, fixed_rooms=None)` |
| Decomposition core | `boundary_utils.py:41` `decompose_boundary_into_rectangles(boundary_coords, fixed_rooms=None, unit_spacing=1)` |
| Point-in-polygon | `boundary_utils.py:7` `point_inside_polygon(x, y, polygon)` |
| Handler | `handlers.py:2659` `handle_space_optimization(ui, regions, rooms, fixed_rooms, adjacency, non_adjacency, entrance_coords=None, max_attempts=100, enable_expansion=True, enable_compaction=True, boundary_bounds=None)` |
| Engine class | `negNew.py:219` `class FloorPlan`, ctor `negNew.py:220` |
| Engine run entry | `negNew.py:1675` `FloorPlan.generate_layout(max_attempts=1000, enable_expansion=True, enable_space_optimization=True)` |
| Engine scoring entry | `negNew.py:786` `FloorPlan.evaluate_adjacency_score()` |
| Only caller of the handler | `api.py:1566` |

`negNew.py:1772-1813` is a `__main__` demo block, not part of the API path.

---

## 1. The exact hand-off contract, handler to engine

The handler does **not** call one engine function. It builds the engine state by a fixed sequence
of method calls on a `FloorPlan` instance and then calls `generate_layout`. Full contract:

| # | Engine call (file:line) | Argument | Python type as passed | Source request JSON field (api.py line) |
| --- | --- | --- | --- | --- |
| 1 | `FloorPlan(region_specs, fixed_rooms)` `handlers.py:2696`, ctor `negNew.py:220` | `region_specs=regions` | `list[dict]` each with `x,y,width,height` | `params.regions` (`api.py:1493`) **or** derived from `params.boundary` (`api.py:1494,1526`) |
| 1b | same | `fixed_rooms=None` | `None`, hardcoded | none. Comment at `handlers.py:2694-2695` says fixed rooms go through `add_room` instead |
| 2 | `set_entrance_location(coords)` `handlers.py:2709`, def `negNew.py:495` | `entrance_coords` | `list[[x,y]]` or `None`; Y-flipped and X-shifted first at `handlers.py:2702-2706` when `boundary_bounds` exists | `params.entrance_coords` (`api.py:1499`) |
| 3 | `add_room(name, width, height, max_expansion)` `handlers.py:2713-2718`, def `negNew.py:644` | `name=room['name']` | `str` | `params.rooms[i].name` (`api.py:1495`) |
| 3 | same | `width=room['width']` | `int` (min width, not clamped or cast) | `params.rooms[i].width` |
| 3 | same | `height=room['height']` | `int` (min height) | `params.rooms[i].height` |
| 3 | same | `max_expansion=room.get('max_expansion', 20)` | `int`, coerced at `negNew.py:22-25`; **default 20** | `params.rooms[i].max_expansion`, optional |
| 4 | `add_fixed_room(...)` `handlers.py:2731-2740`, def `negNew.py:704` | `width=fixed_room['width']` | `int` | `params.fixed_rooms[i].width` (`api.py:1496`) |
| 4 | same | `height=fixed_room['height']` | `int` | `params.fixed_rooms[i].height` |
| 4 | same | `fixed_x` | `int`; `= x - boundary_bounds['min_x']` when boundary given (`handlers.py:2726`), else raw `x` (`handlers.py:2723`) | `params.fixed_rooms[i].x` |
| 4 | same | `fixed_y` | `int`; `= boundary_max_y - (y + height)` when boundary given (`handlers.py:2727`), else raw `y` | `params.fixed_rooms[i].y` and `.height` |
| 4 | same | `name=fixed_room['name']` | `str`; de-duplicated at `negNew.py:717-720` | `params.fixed_rooms[i].name` |
| 4 | same | `max_expansion=fixed_room.get('max_expansion', 0)` | `int`, **default 0** here (unlike rooms) | `params.fixed_rooms[i].max_expansion` |
| 4 | same | `polygon_coords=fixed_room.get('polygon')` | `list[[x,y]]` or `None` | `params.fixed_rooms[i].polygon` (undocumented) |
| 4 | same | `occupied_cells=fixed_room.get('occupied_cells')` | `list[[cx,cy]]` or `None` | `params.fixed_rooms[i].occupied_cells` (undocumented) |
| 5 | `add_adjacency(a, b)` `handlers.py:2744`, def `negNew.py:733` | `adj_pair[0], adj_pair[1]` | `str, str` | `params.adjacency[i]` (`api.py:1497`) |
| 6 | `add_non_adjacency(a, b)` `handlers.py:2748`, def `negNew.py:630` | `pair[0], pair[1]` | `str, str` | `params.non_adjacency[i]` (`api.py:1498`) |
| 7 | `generate_layout(...)` `handlers.py:2751-2755`, def `negNew.py:1675` | `max_attempts` | `int` | `params.max_attempts`, default 100 (`api.py:1559`) |
| 7 | same | `enable_expansion` | `bool` = `'expand' in ops` (`api.py:1557`) | top-level `ops` array |
| 7 | same | `enable_space_optimization=enable_compaction` | `bool` = `'compact' in ops` (`api.py:1558`) | top-level `ops` array |
| 8 | `compact_rooms()` `handlers.py:2762-2763` | none | - | gated by `'compact' in ops` |
| 9 | `evaluate_adjacency_score()` `handlers.py:2766`, def `negNew.py:786` | none | returns `(int score, list[tuple], list[tuple])` | - |
| 10 | `room.is_adjacent_to_entrance(entrance_coords)` `handlers.py:2772`, def `negNew.py:168` | translated `entrance_coords` | `list[[x,y]]` | `params.entrance_coords` |

Fields read from the request but never forwarded to the engine:
`request_id` (`api.py:1487`, echoed only), `engine` (never read anywhere in
`get_space_optimized_floorplan`; grep for `engine` in `api.py` returns no read in 1458-1647),
`ops` entries `"place"` and `"score"` (never tested; only `expand` and `compact` are read at
`api.py:1557-1558`).

Handler parameters `enable_expansion` / `enable_compaction` default to `True`
(`handlers.py:2660`) but the API always passes explicit values, so the defaults are unreachable
from HTTP.

---

## 2. boundary_utils.py: polygon to rectangular regions

**Algorithm name**: axis-aligned *grid / slab decomposition* (also called coordinate-interval or
"vertex-projection grid" decomposition), followed by a *greedy pairwise rectangle merge*. It is
not trapezoidal decomposition and not a minimum-rectangle partition; it makes no optimality claim.
The docstring at `boundary_utils.py:55-62` states the same five steps.

Step by step (`decompose_boundary_into_rectangles`, `boundary_utils.py:41-159`):

1. **Guard**: fewer than 3 points -> return `[]` (`boundary_utils.py:64-65`). This is the only
   input validation in the file.
2. **Scale**: multiply every vertex by `unit_spacing` (`boundary_utils.py:70`); fixed-room
   polygons with fewer than 3 points are dropped (`boundary_utils.py:72-74`).
3. **Translate to local origin**: `origin_x/origin_y = min` over the main polygon, subtracted from
   the boundary and from every fixed area (`boundary_utils.py:78-85`). Region coordinates are
   therefore **local to the boundary bounding box**, not the caller's absolute canvas.
4. **Collect cut lines**: sorted unique X values and sorted unique Y values from the boundary plus
   all fixed-room polygons (`boundary_utils.py:88-93`). Fixed rooms contribute cut lines, which is
   why holes align to cell edges.
5. **Grid sweep**: for every consecutive (x_i, x_i+1) x (y_j, y_j+1) cell (`boundary_utils.py:97-100`):
   skip non-positive extents (`boundary_utils.py:103-104`); compute the cell centre
   (`boundary_utils.py:107`); keep the cell only if the centre is inside the boundary
   (`boundary_utils.py:110-111`) and inside no fixed area (`boundary_utils.py:114-118`);
   append `{'x','y','width','height'}` (`boundary_utils.py:121`).
6. **Greedy merge** (`boundary_utils.py:124-151`): repeat until a full pass makes no change; merge
   `r1` and `r2` when they share a vertical edge with identical `y` and `height`
   (`boundary_utils.py:133-139`) or a horizontal edge with identical `x` and `width`
   (`boundary_utils.py:142-148`). Each merge widens/heightens `r1` in place, removes `r2`, and
   restarts the scan.
7. **Y flip** (`boundary_utils.py:153-157`): `max_y = max(r.y + r.height)`, then
   `r.y = max_y - (r.y + r.height)`. Output is in a **Y-down** frame; the input polygon is Y-up.

`point_inside_polygon` (`boundary_utils.py:7-38`) is an even-odd ray-casting test with a
half-open `y > min` / `y <= max` rule and an explicit vertical-edge branch
(`boundary_utils.py:34`).

**Output structure, exactly**:
`list[dict]`, each dict having exactly the keys `x`, `y`, `width`, `height`
(`boundary_utils.py:121`). Values are whatever numeric type the input vertices were times
`unit_spacing` minus the origin, so ints in, ints out; floats in, floats out. Empty list when the
polygon is degenerate. The list is unordered in any meaningful sense (grid order then mutated by
merges).

**What breaks it**:

- **Holes**: the API accepts one flat vertex list only (`api.py:1494`, `boundary_utils.py:174`),
  so there is no way to pass a second ring. The only hole mechanism is `fixed_rooms`, which are
  *subtracted* (`boundary_utils.py:114-118`) after being synthesized into rectangles from
  `x,y,width,height` at `api.py:1509-1521`. A polygon whose vertex list encodes a hole via a
  keyhole slit is not rejected and not detected; even-odd parity may or may not produce the
  intended result, and the slit's zero-width cells vanish at `boundary_utils.py:103-104`.
  **There is no ring/hole validation anywhere.**
- **Non-rectilinear (diagonal) edges**: cut lines come only from vertex coordinates, so a diagonal
  edge produces axis-aligned cells that straddle it. A cell is kept whole if its *centre* is inside
  (`boundary_utils.py:110`), so regions can protrude outside the polygon and shave off area inside
  it. The result is a coarse staircase whose error is bounded only by the vertex spacing.
  **There is no rectilinearity check.** The doc explicitly advertises this case
  (`space_optimization_api.md:567-578` "Complex Irregular Shape ... automatically decomposes it
  into optimal rectangular regions") without mentioning the approximation.
- **Self-intersecting or non-simple polygons**: no check; ray casting silently applies even-odd
  parity.
- **Duplicate / collinear vertices**: harmless, they only add redundant cut lines; zero-extent
  cells are dropped (`boundary_utils.py:103-104`).
- **Winding order**: irrelevant to even-odd ray casting; no check either way.
- **Float coordinates**: pass through untouched. Downstream `FloorPlan.is_within_floor` uses
  `range(width)` (`negNew.py:738-739`), which raises `TypeError` on floats. The exception is
  swallowed and converted to `status: error` at `handlers.py:2838-2843` + `api.py:1580-1587`.
- **Fully degenerate boundary (<3 pts)**: `boundary_utils.py:64` returns `[]`, but the api-level
  wrapper raises `ValueError` first for `len < 3` (`api.py:45-46`), which is caught at
  `api.py:1528` and returned as `Failed to convert boundary to regions: ...`. A 3+ point but
  zero-area polygon returns `[]` and falls through to
  `'Either regions or boundary must be provided'` (`api.py:1547-1554`), a misleading message.

Validation that *does* exist: `api.py:45-46` (>=3 points) and the guard at
`boundary_utils.py:64-65`. Nothing else. The richer checks in
`test_api_space_optimization_simple.py:377-430` (`validate_request`) are test-script-only and are
never invoked by `api.py`.

Complexity: the merge loop is a restart-on-change double scan, so worst case is roughly
O(n^3) in the number of grid cells. `r1 == r2` at `boundary_utils.py:129` compares dict *values*,
not identity; distinct grid cells always differ in `x` or `y` so this is currently safe, but it is
a latent identity-vs-equality fragility.

---

## 3. Where room dimension inputs enter, and their scope

Room dimensions in this pipeline are **per-room, minimum-only, with a per-room expansion budget**.
There is no max width, no max height, no aspect ratio, and no area input anywhere on this path.

| Input | Meaning | Parse site | Pass-through into engine |
| --- | --- | --- | --- |
| `params.rooms[i].width` | minimum / starting width | `api.py:1495` (`rooms = params.get('rooms', [])`, no per-field parsing) | `handlers.py:2715` -> `negNew.py:651` -> `Room.__init__` sets `original_width` and `width` (`negNew.py:14,16`) |
| `params.rooms[i].height` | minimum / starting height | `api.py:1495` | `handlers.py:2716` -> `negNew.py:15,17` |
| `params.rooms[i].max_expansion` | total extra units this room may grow, summed over all four directions | `api.py:1495` | `handlers.py:2717` (default **20**) -> `negNew.py:22-25`; enforced at three sites: `can_expand_room` (`negNew.py:970`), the expansion loop (`negNew.py:1190-1200` and the per-step check at `negNew.py:1215`), and `can_expand_room_optimized` (`negNew.py:1253`); also read for display at `negNew.py:1497` |
| `params.fixed_rooms[i].width/height` | exact, immovable | `api.py:1496` | `handlers.py:2732-2733` -> `add_fixed_room` -> `add_room(fixed_x, fixed_y)` (`negNew.py:721-731`), which sets `is_fixed=True` (`negNew.py:665`) |

Note the dict is passed through opaquely: `api.py:1495-1496` never touches individual room fields,
so `KeyError` on a missing `width`/`height` surfaces only inside the handler
(`handlers.py:2715`) and is caught by the blanket `except` at `handlers.py:2838`.

`max_expansion` is the only knob that lets solved dimensions exceed the input minimums, and it is
strictly per-room. There is no global minimum-dimension parameter, no `DimParameters`
(`GuiParameters.py:13,25`) construction, and no plot-level min/max on this path. The
`max_expansion` budget is only spent when `'expand'` is in `ops` (`api.py:1557` ->
`handlers.py:2753` -> `negNew.py:1737`).

---

## 4. Response shape, and whether dimensions are solved or echoed

Built in two stages.

**Stage 1, handler** (`handlers.py:2776-2830`) writes into `ui`:

```
output_data = {
  'rooms': [ {name, x, y, width, height, rotated, is_fixed,
              original_width, original_height, area}, ... ],   handlers.py:2797-2808
  'floor_regions': regions,                                     handlers.py:2778
  'entrance_coords': entrance_coords,                           handlers.py:2779
  'metrics': { adjacency_score, satisfied_pairs,
               non_adjacency_violations, entrance_adjacent_rooms,
               area_utilization: { total_region_area, occupied_room_area,
                 occupied_fixed_area, occupied_total_area,
                 remaining_area, remaining_percent, utilization_ratio } }
                                                                handlers.py:2780-2785, 2822-2830
}
```

**Stage 2, api** (`api.py:1607-1633`):

```
{ request_id, status: 'ok',
  data: { floor: {width, height, regions, entrance_coords},   api.py:1611-1616
          placements: result['rooms'],                        api.py:1617  (verbatim, all 10 keys)
          metrics: {ops_run, adjacency_score, satisfied_pairs,
                    non_adjacency_violations, entrance_adjacent_rooms,
                    area_utilization, integrity} },            api.py:1618-1630
  error: {} }                                                  api.py:1632
```

`floor.width` / `floor.height` are computed from the **regions**, not from the boundary:
`max(r['x'] + r['width'])` and `max(r['y'] + r['height'])` (`api.py:1603-1604`).
`floor.regions` is the same list object handed to the engine (`api.py:1614`), so for a
boundary request it is in origin-normalized, Y-flipped local space, while `floor.entrance_coords`
(`api.py:1615`) echoes the caller's **absolute, unflipped** coordinates. The handler's local
translation at `handlers.py:2702-2706` rebinds a local name only and never reaches `api.py`.

**Are placement dimensions solved or echoed?** Both are present, in different keys:

- `width` / `height` are the **current solved** values: `Room.width/height` are mutated by
  `rotate()` (swap, `negNew.py:34-36`) and by expansion (`negNew.py:1202-1213` and following),
  then read at `handlers.py:2800-2801`.
- `original_width` / `original_height` are the **input minimums echoed back**, set once in
  `Room.__init__` (`negNew.py:14-15`) and never mutated; read at `handlers.py:2805-2806`.
- `area` is `Room.get_area()` (`handlers.py:2807` -> `negNew.py:46-54`), which returns the
  occupied-cell count for polygonal fixed rooms and `width * height` otherwise.

So when `max_expansion` is 0 or `'expand'` is absent from `ops`, `width`/`height` equal the input
minimums except for a possible rotation swap (`rotated: true` marks that case). When expansion
runs, `width`/`height` are strictly solved values that can exceed the inputs by up to
`max_expansion` units in total.

**Verification against the test file**: `test_api_space_optimization_simple.py` contains **no
`assert` statements at all** (grep for `assert` over the file returns nothing). It is a manual
runner: it calls `Documents.get_space_optimized_floorplan(request_data)`
(`test_api_space_optimization_simple.py:279`) and then *reads* fields, which pins the shape only by
attribute access:

- `result['status'] != 'ok'` guard: `test_api_space_optimization_simple.py:128,284`
- `result['data']['floor']` with `width`, `height`, `regions[i].{x,y,width,height}`:
  lines 131, 134-135, 147-151, 296-298
- `result['data']['placements'][i]` with `x, y, width, height, is_fixed, name, rotated, area`:
  lines 163-190, 204-207, 303-310
- `result['data']['metrics']` with `adjacency_score`, `satisfied_pairs`,
  `non_adjacency_violations`, `area_utilization.{total_region_area, occupied_room_area,
  occupied_fixed_area, occupied_total_area, remaining_area, utilization_ratio}`,
  `entrance_adjacent_rooms`: lines 313-341
- error path reads `result['error']['message']`: line 363

Every key it touches exists in the code (`api.py:1607-1633`, `handlers.py:2797-2830`), so the two
sides agree. The test never touches `original_width` / `original_height` / `remaining_percent` /
`ops_run` / `integrity`, so those response keys are unpinned by any test.

The pinned request in that file (`test_api_space_optimization_simple.py:50-118`) is the useful
regression case for the coordinate translation: `boundary` in absolute canvas coords
`[[884,420],[884,440],[910,440],[910,420]]` with a fixed room at `x=884, y=420, w=10, h=10`.
The fixed room is synthesized into a polygon at `api.py:1509-1521` and passed into the
decomposition (`api.py:1526`), so it contributes cut lines and is subtracted: running the real API
path returns two regions, `[{x:0,y:0,w:26,h:10},{x:10,y:10,w:16,h:10}]`, normalized to the local
origin (`boundary_utils.py:78-85`) and Y-flipped (`boundary_utils.py:153-157`). Without the fixed
room the same boundary would collapse to a single 26 x 20 region, so any reasoning about this
request that ignores the fixed-room subtraction is wrong.
The handler maps the fixed room to `fixed_x = 884 - 884 = 0`,
`fixed_y = 440 - (420 + 10) = 10` (`handlers.py:2726-2727`). All rooms carry
`max_expansion: 0` and `ops` omits `"expand"` (line 113-117), so in this request the response
`width`/`height` must equal the input minimums modulo rotation.

---

## 5. Shared code with the LP dimensioning chain: none

Fully independent. Evidence in both directions:

- `negNew.py:1-8` imports only `matplotlib.pyplot`, `matplotlib.patches`, `networkx`, `numpy`,
  `random`, `heapq`, `collections`, and `ga_current`. No `GPLAN.source.*` import at all.
- `boundary_utils.py` has **zero import statements** (the file is 178 lines, read in full; there is
  no `import` line anywhere).
- `handlers.py:2685-2689` reaches the engine by `sys.path` injection plus a bare
  `from negNew import FloorPlan`. It does not touch `GPLAN.source.dimensioning`.
- The dimensioning package imports only numeric libraries and its own siblings:
  `block_checker.py:1` `import numpy as np`; `convert_adj_equ_sym.py:13` `import numpy as np`;
  `floorplan_to_st.py:13-15` `numpy`, `from .solve_linear import solve_linear`,
  `from .convert_adj_equ_sym import convert_adj_equ_sym`; `minimum_dimensioning.py:1-3`
  `collections`, `json`, `os`; `solve_linear.py:13-14` `numpy`, `scipy.optimize`.
- Grep for `Space_Optimization|negNew|boundary_utils` across
  `GPLAN\GPLAN\source\` returns **no matches**, and grep for `dimensioning` across
  `GPLAN\Space_Optimization\` returns no matches either (only incidental
  `uinegNew` string hits in `ga_current.py:1496,1593` and `uinegNew.py:6`).

The only shared surfaces are `api.py` itself (both chains are methods on `Documents`) and the
`GuiParameters` mailbox class, and even there the space-optimization path never constructs
`DimParameters` (`GuiParameters.py:13,25`), which is the LP chain's min/max width/height carrier.
The two chains also disagree about geometry: space optimization has no `scipy` LP, no
`min_width/max_width` arrays, and no plot-level constraints.

The only other consumer of `boundary_utils.py` is the Tk CAD app: `uinegNew.py:6` imports
`FloorPlan` from `negNew` (grep result), and the decomposition docstring at
`boundary_utils.py:45` claims it is shared "by both the UI (CAD tool) and the API".

---

## The Actual Constraints Or Formulas

- Region cell acceptance: cell `[x_i, x_i+1) x [y_j, y_j+1)` is kept iff
  `point_inside_polygon(x_i + w/2, y_j + h/2, boundary)` and not inside any fixed area
  (`boundary_utils.py:107-120`).
- Y flip: `y_out = max_y - (y_in + height)` where `max_y = max(y + height)` over kept regions
  (`boundary_utils.py:155-157`).
- Fixed-room translation (boundary requests only):
  `x_engine = x_req - min_x(boundary)`, `y_engine = max_y(boundary) - (y_req + height_req)`
  (`handlers.py:2726-2727`). This matches the region flip only when the regions actually reach the
  boundary's top edge, that is when `max_y(regions) == max_y(boundary) - min_y(boundary)`.
- Entrance translation: `x' = x - min_x`, `y' = max_y - y` (`handlers.py:2703`). Note this is the
  *point* flip, not the *rectangle* flip used for fixed rooms, which is correct for a 0-height
  segment.
- Raw adjacency score: `+1` per satisfied adjacency edge (`negNew.py:793`), `-2` per non-adjacency
  violation (`negNew.py:805`). The `elif` branch at `negNew.py:795-799`, which would add `+1` for
  an entrance pseudo-edge whose endpoint is not a real room, is dead code on this path: every node
  in `adjacency_graph` is added by `add_room` (`negNew.py:687`) or by `register_special_entity`
  (`negNew.py:691`), and a repo-wide grep for `register_special_entity` returns the definition and
  no callers. `add_adjacency` only creates an edge when both names are already nodes
  (`negNew.py:734-735`), and `self.rooms` is assigned once (`negNew.py:221`) and never removed
  from, so both `next(...)` lookups at `negNew.py:789-790` always resolve and the `elif` is never
  reached.
- Reported adjacency score: `raw_score / len(adjacency)` if any adjacency was requested else `1.0`
  (`api.py:1620`). The positive part of the raw score is at most the number of edges in
  `adjacency_graph`, which is at most `len(adjacency)` (duplicate pairs dedupe in the graph,
  unknown names never become edges), so the reported value is **bounded above by exactly 1.0 and
  unbounded below**: only the `-2` penalty can push it outside [0, 1], and only downward.
- Area utilization: `total_region_area = sum(w*h)` over `floor_plan.floor_regions`
  (`handlers.py:2790-2791`); `remaining_area = max(0, total - occupied)` (`handlers.py:2818`);
  `utilization_ratio = occupied_total / total` guarded against divide-by-zero
  (`handlers.py:2820`).
- Floor extent: `floor_width = max(r.x + r.width)`, `floor_height = max(r.y + r.height)` over
  `regions` (`api.py:1603-1604`), computed independently of `FloorPlan.floor_width/floor_height`
  (`negNew.py:240-241`), which use the same formula, so they agree.

## Invariants And Preconditions

1. `regions` must be non-empty by the time the handler runs; enforced at `api.py:1547-1554`.
   `FloorPlan.__init__` indexes `region_specs[0]` unguarded (`negNew.py:229`), so an empty list
   would `IndexError`.
2. `FloorPlan.__init__` accepts two region formats: a list of `(width, height)` tuples stacked
   vertically (`negNew.py:229-233`) or a list of dicts with required `width`/`height` and optional
   `x`/`y` (`negNew.py:235-238`). The API only ever produces the dict form.
3. Room names must be unique across rooms and fixed rooms: `add_adjacency` and
   `add_non_adjacency` are **silent no-ops** when a name is not already a graph node
   (`negNew.py:734-735`, `negNew.py:631-632`). Ordering matters: the handler adds all rooms and
   fixed rooms (`handlers.py:2712-2740`) before any constraint (`handlers.py:2743-2748`), which is
   required for the edges to register at all.
4. Fixed room names are silently de-duplicated with a `_1`, `_2` suffix (`negNew.py:717-720`), so a
   duplicate name in `fixed_rooms` breaks any adjacency edge that references it.
5. Response placements and `floor.regions` share one coordinate frame (engine-local, Y-down);
   `floor.entrance_coords` does not.
6. `boundary_bounds` is populated only when `params.boundary` is present (`api.py:1537-1544`), so
   an explicit-`regions` request performs no fixed-room translation
   (`handlers.py:2691-2692, 2722-2730`).
7. `ui.get_output_data()` is read only after `success` is `True` (`api.py:1580-1590`), which
   protects against the class-level mutable default at `GuiParameters.py:129`.

## Failure Modes

| Symptom | Cause | Location |
| --- | --- | --- |
| `status: error`, `Failed to convert boundary to regions: ...` | fewer than 3 boundary points, or a raise inside decomposition | `api.py:45-46`, `api.py:1525-1535` |
| `status: error`, `Either regions or boundary must be provided` | genuinely missing input, **or** a 3+ vertex boundary that decomposed to `[]` (zero area, all cell centres outside) | `api.py:1547-1554`, `boundary_utils.py:64-65` |
| `status: error` with a `KeyError`-style message | a room dict missing `name`/`width`/`height`, or a fixed room missing `x`/`y`/`width`/`height`; nothing validates these before the engine | `handlers.py:2715-2716, 2722-2736`, caught `handlers.py:2838-2843` |
| `status: error`, `Failed to generate space-optimized layout` | `generate_layout` returned `False` because placement failed | `negNew.py:1753-1768`, `handlers.py:2757-2759` |
| Rooms placed outside the polygon | diagonal boundary edges approximated by cell-centre testing | `boundary_utils.py:107-111` |
| Fixed rooms land in the wrong place | Y-flip mismatch when the boundary's topmost extent is not covered by any kept region, so `max_y(regions) != max_y(boundary) - min_y(boundary)` | `boundary_utils.py:155-157` vs `handlers.py:2727` |
| `adjacency_score` below 0 | raw score subtracts 2 per non-adjacency violation, then is divided by `len(adjacency)`; nothing can push the quotient above 1.0 | `negNew.py:793,805` vs `api.py:1620` |
| Adjacency constraints silently ignored | a name in `adjacency`/`non_adjacency` that does not match any room name | `negNew.py:631-632, 734-735` |
| `integrity.overlaps` empty despite real overlaps | the field is hardcoded, never computed | `api.py:1625-1629` |
| Error message text is a concatenation of several messages | `GuiParameters.set_message` **appends** rather than assigns | `GuiParameters.py:324-327` |
| Silent exception swallowing in coordinate translation | bare `except Exception: pass` around the entrance flip and the fixed-room flip, which falls back to untranslated coordinates | `handlers.py:2707-2708`, `handlers.py:2728-2730` |
| Nothing printed during a run | `builtins.print` is globally monkeypatched to a no-op for the duration of the call | `api.py:1479-1484`, restored at 1529/1548/1581/1592/1635/1639 |

## Coupling (what breaks if you change this)

- **Change the region dict keys** (`x, y, width, height`): breaks `FloorPlan.__init__`
  (`negNew.py:235-238`), the floor-extent computation (`api.py:1603-1604`), the area total
  (`handlers.py:2790-2791`), the response `floor.regions` (`api.py:1614`), and the test's
  region drawing (`test_api_space_optimization_simple.py:147-151`).
- **Remove the Y flip** in `boundary_utils.py:153-157`: silently desynchronizes regions from the
  fixed-room translation at `handlers.py:2727` and from the entrance translation at
  `handlers.py:2703`. All three must move together.
- **Change `boundary_to_regions`**: also affects the Tk CAD tool, which the docstring at
  `boundary_utils.py:45` claims shares this function; and `api.py:26-49` is a pure pass-through
  wrapper, so its docstring is the only place documenting the contract for API users.
- **Rename any `Room` attribute** read at `handlers.py:2797-2807` (`name, x, y, width, height,
  rotated, is_fixed, original_width, original_height, get_area`): breaks the response directly.
- **Change `handle_space_optimization`'s signature**: only one caller, `api.py:1566-1578`.
- **Change `evaluate_adjacency_score`'s return tuple**: unpacked at `handlers.py:2766` and its
  three parts land in the response at `api.py:1620-1622`.
- **Change `ops` semantics**: `enable_expansion`/`enable_compaction` derive from it at
  `api.py:1557-1558`, but `ops` is also echoed verbatim as `metrics.ops_run` (`api.py:1619`), so
  the echo will keep lying about what ran.
- The engine is loaded by `sys.path` injection plus a top-level module name
  (`handlers.py:2685-2689`, `api.py:20-23`). Any module named `negNew`, `boundary_utils`, or
  `ga_current` elsewhere on `sys.path` shadows it. Moving `Space_Optimization/` breaks both.

## Dead Or Duplicated Code

- **Duplicated point-in-polygon**: `boundary_utils.point_inside_polygon` (`boundary_utils.py:7-38`)
  and `FloorPlan._point_inside_polygon` (`negNew.py:522`) are two independent implementations of
  the same test in the same request path.
- **Duplicated boundary wrapper**: `api.py:26-49` `boundary_to_regions` adds only a `<3 points`
  raise on top of `boundary_utils.py:162-177`, which itself only reformats `[x,y]` to `(x,y)`
  before calling `decompose_boundary_into_rectangles`. Three layers, one algorithm.
- **`integrity` is a stub**: `overlaps`, `out_of_bounds`, `invalid_adjacent_edges` are hardcoded
  empty lists (`api.py:1625-1629`) although the doc describes them as computed
  (`space_optimization_api.md:144-147`). The test file even reimplements overlap detection itself
  (`test_api_space_optimization_simple.py:224-258`) because the API does not provide it.
- **`FloorPlan.fixed_rooms` list is effectively dead on this path**: the handler passes
  `fixed_rooms=None` to the constructor (`handlers.py:2696`), so `self.fixed_rooms` stays empty
  (`negNew.py:222`) and the reset loop at `negNew.py:1698-1699` iterates nothing. Fixed rooms live
  in `self.rooms` with `is_fixed=True` (`negNew.py:665`).
- **Entrance pseudo-edge scoring is unreachable**: the `elif` at `negNew.py:795-799` handles an
  `adjacency_graph` edge whose endpoint is not in `self.rooms`, but nodes enter that graph only via
  `add_room` (`negNew.py:687`) or `register_special_entity` (`negNew.py:691`), and the latter has no
  callers anywhere in the repo. `add_adjacency` refuses to create an edge for an unknown name
  (`negNew.py:734-735`) and `self.rooms` is never shrunk after `negNew.py:221`, so both lookups at
  `negNew.py:789-790` always succeed and the branch never runs.
- **`ops` values `"place"` and `"score"` are inert**: never read; placement (`handlers.py:2751`)
  and scoring (`handlers.py:2766`) always run.
- **`request_data['engine']` is never read** in `get_space_optimized_floorplan`
  (`api.py:1486-1499`), unlike the GA path which both reads and echoes it (`api.py:1713, 1739`).
- **`validate_request`** (`test_api_space_optimization_simple.py:377-430`) duplicates validation
  that production code does not have, and is called only from the script's `__main__`
  (line 449).
- **`negNew.py:1772-1813`** is a `__main__` demo, not reachable from the API.
- **Malformed example block**: `test_api_space_optimization_simple.py:472-690` is one giant string
  literal of examples; Example 2A's header is spliced into Example 1 (line 491), Example 2B mixes
  boundary points with region dicts inside the same list (lines 517-526), and Example 5 is cut in
  half by Examples 6 and 7 (lines 607-664). It is documentation-by-comment and is wrong as written.
- **`GuiParameters.output_data: list = []`** (`GuiParameters.py:129`) is a class-level mutable
  default. This path assigns rather than appends (`GuiParameters.py:426-430`), so it does not leak
  here, but `_append_output_data` (`GuiParameters.py:389-396`) does share it across instances when
  `gclass` is `None`.

## 6. Doc versus code discrepancies

| # | Doc claim (space_optimization_api.md) | Code reality | Severity |
| --- | --- | --- | --- |
| 1 | `max_expansion ... (optional, default: 0)` (line 56) | `room.get('max_expansion', 20)`, so an omitted `max_expansion` gives a room **20 units of growth**, not 0 (`handlers.py:2717`). Fixed rooms do default to 0 (`handlers.py:2737`), and `Room.__init__` itself defaults to 3 (`negNew.py:12`). Three different defaults. | High |
| 2 | Placement objects have exactly `name, x, y, width, height, area, is_fixed, rotated` (lines 120-128) and the sample response shows only those (lines 390-399) | Every placement also carries `original_width` and `original_height` (`handlers.py:2805-2806`), passed through verbatim at `api.py:1617`. | Medium |
| 3 | `area_utilization` has 6 keys (lines 137-143) | 7 keys: `remaining_percent` is also emitted (`handlers.py:2828`). | Low |
| 4 | `integrity.overlaps: "List of overlapping rooms (should be empty)"`, `out_of_bounds`, `invalid_adjacent_edges` (lines 144-147) | All three are hardcoded `[]`, never computed (`api.py:1625-1629`). They are always empty regardless of the layout. | High |
| 5 | `adjacency_score : float - Percentage of adjacency constraints satisfied (0.0 to 1.0)` (line 133) | `raw / len(adjacency)` where raw is `+1` per satisfied edge (`negNew.py:793`) and `-2` per non-adjacency violation (`negNew.py:805`). The quotient can go negative, so the documented lower bound is wrong. The upper bound holds: the entrance pseudo-edge branch (`negNew.py:795-799`) is unreachable, so the score never exceeds 1.0 (`api.py:1620`). | Medium |
| 6 | Sample response `floor.regions` for the L-shape boundary is `[{0,0,40,24},{0,24,20,8}]` (lines 370-383) | Not what the code produces. The same documented request (lines 196-234) also carries three `fixed_rooms` (Staircase 32,0,8,12; Lift 28,0,4,6; Duct 0,24,4,8), which `api.py:1501-1521` synthesizes into polygons and `api.py:1526` passes into the decomposition as extra cut lines and subtracted area. Executing that real API path returns **four** regions: `[{x:0,y:8,w:28,h:24},{x:4,y:0,w:16,h:8},{x:28,y:8,w:4,h:18},{x:32,y:8,w:8,h:12}]`. The boundary alone, with no fixed rooms, returns two regions `[{x:0,y:0,w:20,h:32},{x:20,y:8,w:20,h:24}]`, which is also not the documented pair. Both were run against `boundary_utils.boundary_to_regions` (`boundary_utils.py:162`). | High |
| 7 | `boundary` and `regions`: "Use this OR `regions`, not both" (lines 34, 39) | If both are sent, `regions` silently wins (`api.py:1524` `if boundary and not regions`) **but** `boundary_bounds` is still computed from `boundary` (`api.py:1538-1544`) and then shifts and Y-flips every fixed room (`handlers.py:2726-2727`). Sending both silently corrupts fixed-room placement rather than erroring. | High |
| 8 | Response `floor.regions` implied to be in the caller's coordinate frame (sample at lines 370-383 matches the input boundary's frame) | Regions are translated to the boundary's local origin (`boundary_utils.py:78-85`) and Y-flipped (`boundary_utils.py:153-157`). The test request's boundary at x=884..910, y=420..440 (`test_api_space_optimization_simple.py:54-71`) yields, with its one fixed room subtracted, `[{x:0,y:0,w:26,h:10},{x:10,y:10,w:16,h:10}]`, that is local coordinates starting at (0,0) rather than at (884,420). Meanwhile `floor.entrance_coords` echoes the **absolute** input (`api.py:1615`). Two coordinate frames in one response object. | High |
| 9 | `ops` lists `"place"` and `"score"` as operations to perform (lines 91-94) | Only `'expand'` and `'compact'` are read (`api.py:1557-1558`). Placement (`handlers.py:2751`) and scoring (`handlers.py:2766`) run unconditionally. `metrics.ops_run` echoes the request's `ops` verbatim (`api.py:1619`) rather than what executed. | Medium |
| 10 | "Compaction: Remove gaps between rooms" listed as an opt-in op (lines 15, 92) | Compaction runs inside `generate_layout` regardless of the flag (`negNew.py:1713, 1717, 1720`); the `compact` op only adds `use_compact_mode` during placement (`negNew.py:1705`) and one extra pass afterwards (`handlers.py:2762-2763`). | Medium |
| 11 | `engine : string - Must be set to "FloorPlan"` (lines 25-27) | `get_space_optimized_floorplan` never reads `request_data['engine']` (`api.py:1486-1499`); it is neither validated nor echoed. Any value, or its absence, is accepted at this layer. | Low |
| 12 | Fixed room fields are exactly `name, x, y, width, height, is_fixed, max_expansion` (lines 63-69) | `polygon` (`api.py:1505`, `handlers.py:2738`) and `occupied_cells` (`handlers.py:2739`) are also read and enable non-rectangular fixed rooms (`negNew.py:673-683`). Also `is_fixed` is never read: a room in `fixed_rooms` is fixed regardless of the flag (`handlers.py:2721-2740`). | Medium |
| 13 | "The API automatically decomposes it into **optimal** rectangular regions" for arbitrary polygons (line 578) | The merge is a greedy, order-dependent pairwise pass (`boundary_utils.py:124-151`), not a minimum-rectangle partition, and diagonal edges are only centre-sampled (`boundary_utils.py:107-111`). Neither optimality nor rectilinearity is checked. | Medium |
| 14 | `max_attempts : int (optional) - Maximum placement attempts (default: 100)` (line 85) | Correct at the API layer (`api.py:1559`), but the handler default is 100 (`handlers.py:2660`) while `generate_layout`'s own default is 1000 (`negNew.py:1675`). Only a hazard for direct engine callers. | Low |
| 15 | Nothing documents that the response `width`/`height` are post-rotation | `rotate()` swaps `width`/`height` (`negNew.py:34-36`); the response reports the swapped values (`handlers.py:2800-2801`) with `rotated: true`, while `original_width`/`original_height` keep the request values (`negNew.py:14-15`). A client that ignores `rotated` and matches on `width` will mismatch. | Medium |

## Open Questions

1. Is anything upstream of `api.py` (a Django view outside this repo tree) validating `engine`
   or the `boundary`/`regions` mutual exclusion? Nothing in `GPLAN\GPLAN\` does.
2. `boundary_utils.py:45` claims the decomposition is shared with the CAD UI, but the UI file
   `uinegNew.py` imports only `FloorPlan` from `negNew` (line 6). Does the UI still have its own
   copy of `decompose_into_rectangles`, in which case the two can drift?
3. Is the fixed-room Y flip at `handlers.py:2727` intended to use the boundary's `max_y` rather
   than the regions' `max_y`? They coincide only when the top of the boundary bounding box is
   covered by a kept region. A boundary whose topmost slab is entirely excluded by a fixed room
   would misalign every fixed room by the height of that slab. Untested.
4. Should `remaining_percent` and `original_width`/`original_height` be removed from the response
   or added to the doc? Both are unpinned by any test.
5. Was `integrity` ever computed, or has it always been a placeholder? If clients depend on it
   being empty as a health signal, populating it is a breaking change.
6. Float boundary coordinates flow through decomposition intact but crash the engine's
   `range()`-based bounds check (`negNew.py:738-739`). Should coordinates be `int`-coerced at
   `boundary_utils.py:70` or rejected at `api.py:45`?
