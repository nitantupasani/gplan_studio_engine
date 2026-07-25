# dim-12: `uinegNew.py` - live code or legacy?

Target: `C:\Users\nitant\Documents\GPLAN_Revamp\GPLAN\Space_Optimization\uinegNew.py` (6859 lines, ~314KB)
Comparison file: `C:\Users\nitant\Documents\GPLAN_Revamp\GPLAN\Space_Optimization\negNew.py` (class `Room` at :11, class `FloorPlan` at :219)

## Purpose

**Verdict: LEGACY for the deployed API. Runnable standalone as a desktop GUI.**

`uinegNew.py` is not a fork of `negNew.py`. It is a Tkinter desktop front end that **imports** the production engine:

- `C:\Users\nitant\Documents\GPLAN_Revamp\GPLAN\Space_Optimization\uinegNew.py:6` - `from negNew import FloorPlan  # Import from your original file`

The dependency arrow points GUI -> engine, never engine -> GUI.

### Import evidence (step 1, exhaustive)

Repo-wide case-insensitive grep for `uineg` across `C:\Users\nitant\Documents\GPLAN_Revamp\GPLAN` returned exactly 8 hits, and **zero of them are an import**:

| file:line | kind |
|---|---|
| `GPLAN\documentation\contribution_workflow.md:79` | doc link |
| `GPLAN\documentation\contribution_workflow.md:91` | doc prose ("Inspect the changes in `negNew.py` and `uinegNew.py` first") |
| `GPLAN\documentation\contribution_workflow.md:154` | doc prose ("updating `negNew.py` but forgetting `uinegNew.py`") |
| `GPLAN\Space_Optimization\ga_current.py:1496` | comment only ("Use same color scheme as uinegNew") |
| `GPLAN\Space_Optimization\ga_current.py:1593` | comment only ("match uinegNew.py coordinate system") |
| `GPLAN\Space_Optimization\uinegNew.py:72` | stale patch instruction comment inside the file |
| `GPLAN\Space_Optimization\uinegNew.py:4049`, `:4052` | stale patch instruction comments inside the file |

No `import uinegNew`, no `from uinegNew import ...`, anywhere in the tree.

What the API actually imports:

- `C:\Users\nitant\Documents\GPLAN_Revamp\GPLAN\GPLAN\handlers.py:2689` - `from negNew import FloorPlan`, inside `handle_space_optimization` (defined at `handlers.py:2659`), after a runtime `sys.path.insert` of the `Space_Optimization` directory at `handlers.py:2685-2687`.
- `C:\Users\nitant\Documents\GPLAN_Revamp\GPLAN\GPLAN\api.py:1461` is the docstring of the space-optimization API surface, describing "the negNew FloorPlan engine".
- `C:\Users\nitant\Documents\GPLAN_Revamp\GPLAN\GPLAN\api.py:23` - `from boundary_utils import boundary_to_regions as convert_boundary_to_regions`, the API's own boundary decomposition, also in `Space_Optimization`.

So the deployed API touches exactly three files in `Space_Optimization`: `negNew.py`, `boundary_utils.py`, and `ga_current.py` (imported by `negNew.py:8` as `import ga_current as ga`). `uinegNew.py` is reachable from none of them.

Packaging confirms it: `Space_Optimization` contains no `__init__.py` (directory listing: `boundary_utils.py`, `ga_current.py`, `negNew.py`, `uinegNew.py`, `.c/.h/.so` corridor artifacts, `floorplan_data.json`, `__pycache__`), so `find_packages()` in `C:\Users\nitant\Documents\GPLAN_Revamp\GPLAN\setup.py:24` does not collect it and `setup.py` declares no `py_modules`, `scripts`, or `entry_points`. The engine is only importable because `handlers.py` mutates `sys.path` at call time.

**Standalone runnability (step 5):** it has a `__main__` block.

- `uinegNew.py:6847-6855` - `def main(): root = tk.Tk(); root.withdraw(); app = FloorPlanGUI(root); app.launch_cad_tool(); root.mainloop()`
- `uinegNew.py:6858-6859` - `if __name__ == "__main__": main()`

So `python uinegNew.py` still launches a working CAD + floorplan desktop tool against the current engine. It is legacy with respect to the API, not abandoned with respect to a human operator. `negNew.py` also has its own `if __name__ == "__main__":` at `negNew.py:1772`, which is likewise not executed under API import.

## Where It Sits In The Pipeline

Two disjoint consumers of one engine:

```
Deployed path:   HTTP -> GPLAN\GPLAN\api.py (:1461 area)
                      -> handlers.handle_space_optimization (handlers.py:2659)
                      -> sys.path hack (handlers.py:2685)
                      -> negNew.FloorPlan (handlers.py:2689, negNew.py:219)
                      -> ga_current (negNew.py:8)
                 boundary polygons -> boundary_utils.boundary_to_regions (api.py:23, boundary_utils.py:162)

Legacy path:     python uinegNew.py (uinegNew.py:6858)
                      -> FloorPlanGUI (uinegNew.py:2811) + CADApp (uinegNew.py:68)
                      -> negNew.FloorPlan (uinegNew.py:6)
```

The GUI performs, in Tkinter, the same role `api.py` + `handlers.py` perform over HTTP: collect regions, rooms, fixed rooms, adjacency, non-adjacency, entrance, then call the engine.

## Entry Points (file:line)

Top-level surface of `uinegNew.py` is tiny; nearly everything is methods on two classes.

- `uinegNew.py:21` `def _normalize_polygon_points(points)`
- `uinegNew.py:31` `def _point_inside_polygon(x, y, polygon)`
- `uinegNew.py:50` `def _polygon_to_occupied_cells(polygon_points)`
- `uinegNew.py:68` `class CADApp` (boundary drawing tool; ~2740 lines, ~110 methods)
- `uinegNew.py:2811` `class FloorPlanGUI` (main app; ~4030 lines, ~120 methods)
- `uinegNew.py:6847` `def main()`
- `uinegNew.py:6858` `if __name__ == "__main__":`

Counts: 3 module-level functions plus `main()`, 2 classes, 18 import lines (`uinegNew.py:1-18`).

GUI toolkit imports (this file is unambiguously a desktop GUI):

- `uinegNew.py:1` `import tkinter as tk`
- `uinegNew.py:2` `from tkinter import ttk, messagebox, scrolledtext`
- `uinegNew.py:4` `from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg`
- `uinegNew.py:8` `from tkinter import filedialog`
- `uinegNew.py:12` `from tkinter import simpledialog`

By contrast `negNew.py:1-8` imports only `matplotlib.pyplot`, `matplotlib.patches`, `networkx`, `numpy`, `random`, `heapq`, `collections`, and `ga_current`. No Tk. This is why the engine is import-safe on a headless VM and the GUI is not: importing `uinegNew` on the server would require a Tk runtime.

Key GUI-side driver methods:

- `uinegNew.py:5819` `FloorPlanGUI.generate_floor_plan` - builds `FloorPlan` and calls `self.floor_plan.generate_layout(...)` at `uinegNew.py:5985`
- `uinegNew.py:6049` `FloorPlanGUI.visualize_floor_plan` - GUI renderer, parallel to `negNew.FloorPlan.visualize` (`negNew.py:1280`)
- `uinegNew.py:4288` `FloorPlanGUI.restore_floor_plan_from_results` - rebuilds a `FloorPlan` from saved JSON (`uinegNew.py:4294`)
- `uinegNew.py:6826` `FloorPlanGUI.run_genetic_algorithm` - GA hand-off, engine side is `negNew.py:1557` `floorplan_to_ga_input` and `negNew.py:1671` `ga_runner`

## Data Structures

The GUI owns Tk state, the engine owns geometry state.

- `CADApp` (`uinegNew.py:68`): canvas points/lines, `self.regions` (list of `{x, y, width, height}` dicts, built at `uinegNew.py:2597`), `self.scaled_coordinates` (main boundary polygon, `uinegNew.py:2599`), `self.scaled_final_area` (fixed-shape polygons to exclude, `uinegNew.py:2605-2607`).
- `FloorPlanGUI` (`uinegNew.py:2811`): `self.floor_plan` (a `negNew.FloorPlan`), `self.rooms_tree` (ttk Treeview as the room table and the source of truth for used area, `uinegNew.py:3583-3586`), Tk vars `self.total_area`, `self.only_rooms_area`, `self.remaining_area`, `self.remaining_percent` (`uinegNew.py:3574`, `:3595-3597`).
- Engine side: `Room` (`negNew.py:12` constructor with `name, width, height, max_expansion=3`), with `occupied_cells`, `x/y`, `original_width/original_height`, `rotated`; `FloorPlan` (`negNew.py:220`, `region_specs`, `fixed_rooms`).

Cell representation is shared and identical in both: integer `(cx, cy)` tuples, half-open ranges, cell membership tested at the cell **center** (`+0.5`). See `negNew.py:550-555` and `uinegNew.py:61-64`.

## Algorithm Walkthrough (divergence check, step 3)

Because `uinegNew` imports the engine rather than copying it, the shared-name surface is small. The three shared, sizing-relevant pairs:

### 1. `_point_inside_polygon` - IDENTICAL

- `uinegNew.py:31-47` (module-level function)
- `negNew.py:521-538` (`@staticmethod` on `FloorPlan`)

Same even-odd ray cast, same `n < 3` guard, same `denom != 0` guard, same `x < x_at_y` strict comparison, same `j = n - 1` seeding. Character-for-character equal apart from indentation and the decorator. No algorithmic divergence.

This is only the module-level helper. `uinegNew.py` also carries a second, differently written point-in-polygon method on `CADApp` (`uinegNew.py:264`), which uses the inclusive min-max form and is what the CAD-side region decomposition calls (`uinegNew.py:2626`, `:2633`). The two forms classify on-edge points differently. See Dead Or Duplicated Code.

### 2. Polygon rasterization - TRIVIALLY DIFFERENT (rename + container type + one extra guard)

- `uinegNew.py:50` `_polygon_to_occupied_cells(polygon_points)` vs `negNew.py:540` `_polygon_to_cells(self, polygon_coords)` - **RENAMED**, not duplicated logic.

Body comparison:

| aspect | uinegNew | negNew |
|---|---|---|
| pre-normalization | `uinegNew.py:51` calls `_normalize_polygon_points`, which strips a repeated closing vertex (`uinegNew.py:26-27`) | none; polygon used raw (`negNew.py:544`) |
| degenerate guard | `len(poly) < 3 -> []` (`uinegNew.py:52-53`) | `not polygon_coords or len < 3 -> set()` (`negNew.py:541-542`) |
| bbox | `int(min/max)` over x and y (`uinegNew.py:55-58`) | same (`negNew.py:544-547`) |
| scan | `for cy in range(min_y, max_y): for cx in range(min_x, max_x)` (`uinegNew.py:61-62`) | same (`negNew.py:550-551`) |
| membership test | `_point_inside_polygon(cx + 0.5, cy + 0.5, poly)` (`uinegNew.py:63`) | `self._point_inside_polygon(center_x, center_y, ...)` (`negNew.py:552-554`) |
| return type | **`list`** (`uinegNew.py:60`, `:64-65`) | **`set`** (`negNew.py:549`, `:555-556`) |

The list cannot contain duplicates: the two nested `range` loops at `uinegNew.py:61-62` append `(cx, cy)` at most once per iteration, so every emitted pair is distinct by construction. List vs set is a container-type difference only, with no effect on `len()`.

Numerically the same raster. The only behavioural deltas are the return container (list vs set) and the closing-vertex normalization, which matters only if a caller passes a closed ring: the engine's raw version would still rasterize correctly (a duplicate final vertex is a zero-length edge, and `(yi > y) != (yj > y)` is false for it), so this is defensive, not corrective.

### 3. Room area / occupied cells - ALGORITHMICALLY EQUIVALENT, INDEPENDENTLY REIMPLEMENTED

- Engine: `negNew.py:46-47` `get_area()` delegates to `get_effective_area()`; `negNew.py:49-54` `get_effective_area()` returns `len(cells)` when `get_occupied_cells()` is non-empty, else `self.width * self.height`; `negNew.py:73-85` `get_occupied_cells()` returns the stored polygon cells as a set of tuples, else rasterizes the rectangle `[x, x+width) x [y, y+height)`.
- GUI: `uinegNew.py:3524-3549` `_occupied_cells_count()` calls `room_obj.get_occupied_cells()` behind `hasattr`/`try`, falls back to the raw `occupied_cells` attribute or a `room_data` dict key, dedupes into a set of `(int, int)` and returns `None` when empty; `uinegNew.py:3551-3555` `_scaled_room_area_value()` then applies the **same rule as the engine**: occupied-cell count if available, else `width * height`, rounded to int.

Same formula, two implementations. The GUI version exists so it can also work on plain dicts loaded from JSON (`uinegNew.py:3535-3536`), which the engine's method cannot. Not a divergence in the sizing rule.

### The engine call the GUI actually makes

`uinegNew.py:5985` - `success = self.floor_plan.generate_layout(max_attempts=max_attempts, enable_expansion=enable_expansion)`, which is `negNew.py:1675`. All placement, expansion, compaction, adjacency scoring and non-adjacency enforcement therefore live in `negNew.py` (`:1036` `place_rooms_with_constraints_optimized`, `:1172` `expand_rooms_optimized`, `:245`/`:361`/`:439` compaction, `:786` `evaluate_adjacency_score`, `:875` `enforce_minimum_adjacency`). The GUI contains none of it.

## The Actual Constraints Or Formulas

Only the formulas that live in `uinegNew.py` itself (everything else is the engine's).

- Cell occupancy test: a unit cell `(cx, cy)` belongs to a polygon iff `_point_inside_polygon(cx + 0.5, cy + 0.5, poly)` (`uinegNew.py:63`). Half-open scan `range(min_y, max_y)` x `range(min_x, max_x)` (`uinegNew.py:61-62`), so a polygon of width `W` yields `W` columns, not `W+1`.
- Room area shown in the UI: `area = round(len(unique_occupied_cells))` if any, else `round(width * height)` (`uinegNew.py:3553-3555`).
- Area budget: `remaining = max(0, total_region_area - used_area)`, `remaining_pct = remaining / total_region_area * 100` guarded by `total_region_area > 0` (`uinegNew.py:3591-3592`). `used_area` is summed from the Treeview `Area` column, not from the engine (`uinegNew.py:3583-3586`).
- `_unit_spacing_factor` returns `spacing ** 2` (`uinegNew.py:3516-3522`) but `_scaled_room_area_value` deliberately does **not** apply it - the docstring at `uinegNew.py:3552` says "independent of grid spacing". The helper is computed and, for area purposes, unused.
- Region decomposition (`uinegNew.py:2593-2640+`): collect unique X and Y from boundary plus fixed shapes (`uinegNew.py:2609-2610`), form the slab grid, keep a cell if its midpoint `(x_start + w/2, y_start + h/2)` is inside the boundary (`uinegNew.py:2623-2627`) and outside every excluded fixed area (`uinegNew.py:2629-2632`).

## Invariants And Preconditions

1. `uinegNew.py` requires a display and a Tk runtime. Importing it executes `import tkinter` at `uinegNew.py:1`; running it calls `tk.Tk()` at `uinegNew.py:6848`. Any server-side import would be a new hard dependency.
2. `uinegNew.py` requires `negNew.py` to be importable as a **top-level module** named `negNew` (`uinegNew.py:6`), that is, run with `Space_Optimization` as CWD or on `sys.path`. Same flat-module assumption the API satisfies manually at `handlers.py:2685-2687`.
3. `FloorPlan.generate_layout` is the single contract point (`uinegNew.py:5985` -> `negNew.py:1675`). The GUI also relies on `add_room` (`negNew.py:644`), `add_fixed_room` (`negNew.py:704`), `add_adjacency` (`negNew.py:733`), `add_non_adjacency` (`negNew.py:630`), `evaluate_adjacency_score` (`negNew.py:786`), and the public attributes `rooms`, `floor_regions`, `adjacency_graph`, `floor_width`, `floor_height` (used at `uinegNew.py:3626`, `:3646`, `:4482`, `:4518`, `:6059`, `:6068`; the `adjacency_graph` read at `:6023` is inside the dead nested block described in Dead Or Duplicated Code and does not count).
4. Cell coordinates are integers in both files; non-integer polygon vertices are truncated by `int(min(...))` (`uinegNew.py:55-58`, `negNew.py:544-547`), so sub-unit boundaries silently snap inward.

## Failure Modes

- **Headless import crash.** Any attempt to make this file API-reachable fails at `uinegNew.py:1` / `:6848` without an X display.
- **Silent area disagreement inside the GUI.** `_scaled_room_area_value` uses occupied cells (`uinegNew.py:3553-3554`) but `get_floor_plan_results` (`uinegNew.py:4478`) computes used area as plain `width * height` at `uinegNew.py:4483` (`used_area = sum(room.width * room.height for room in self.floor_plan.rooms if room.x is not None)`). For non-rectilinear rooms the two disagree, so the exported JSON stats can differ from the room table. That is the only live site: the identical expression at `uinegNew.py:6014` sits inside a dead nested function (see Dead Or Duplicated Code), and the on-screen stats path actually runs `FloorPlanGUI.update_output_display` at `uinegNew.py:3605`, which sums `_scaled_room_area_value` (`uinegNew.py:3625-3629`) and therefore agrees with the room table.
- **Broad `except Exception` swallowing.** `_occupied_cells_count` returns `None` on any error (`uinegNew.py:3548-3549`), which silently downgrades area to `w*h`; `update_area_stats` catches everything and only prints (`uinegNew.py:3602-3603`).
- **Debug prints in the hot path.** `uinegNew.py:3576` and `uinegNew.py:3599-3600` print on every area update. Harmless in a GUI, noisy if this code were ever lifted server-side.

## Coupling (what breaks if you change this)

- Changing `negNew.py` breaks `uinegNew.py` silently. The GUI calls the engine by name and attribute across ~40 call sites (`uinegNew.py:3613`, `:4294`, `:4312`, `:4327`, `:4338`, `:4344`, `:5840`, `:5881`, `:5889`, `:5902`, `:5932`, `:5946`, `:5956`, `:5977`, `:5980`, `:5985`, `:6058`, `:6059`, `:6068`, among others; the engine reads at `:6014`, `:6022` and `:6023` are inside the dead nested `update_output_display` and would not break anything observable). Renaming `add_fixed_room`, `generate_layout`, or the `rooms` / `floor_regions` attributes will not break the API tests but will break the desktop tool. This is exactly the trap `GPLAN\documentation\contribution_workflow.md:154` warns about ("updating `negNew.py` but forgetting `uinegNew.py`").
- Changing `uinegNew.py` breaks nothing else. Nothing imports it (step 1). Blast radius is the desktop tool alone.
- `ga_current.py:1496` and `:1593` are comments claiming color-scheme and coordinate-system parity with `uinegNew.py`. They are documentation of intent, not a code dependency, but they mean deleting `uinegNew.py` would orphan the rationale for those two choices.

## Dead Or Duplicated Code

- **Whole-file status: legacy relative to the API.** Not dead in the strict sense (it has a working `__main__` at `uinegNew.py:6858`), but unreachable from any deployed request path.
- **Duplicate method definitions inside `class CADApp`** - the first definition of each pair is genuinely dead, silently shadowed at class-construction time:
  - `add_fixed_room_label_centered` defined at `uinegNew.py:1130` **and** at `uinegNew.py:1292`. The second wins.
  - `remove_all_fixed_room_labels` defined at `uinegNew.py:1247` **and** at `uinegNew.py:1401`. The second wins.
- **Dead nested `update_output_display` (`uinegNew.py:6000-6047`).** The `def` at `uinegNew.py:6000` is at 8-space indentation, so it is a local function inside `FloorPlanGUI.generate_floor_plan` (`uinegNew.py:5819`), placed after that method's `except` block ends at `uinegNew.py:5998` and running until the next class-level `def visualize_floor_plan` at `uinegNew.py:6049`. Nothing ever calls the local name. All three call sites (`uinegNew.py:4400`, `:5990`, `:5994`) go through `self.`, which resolves to the class-level `FloorPlanGUI.update_output_display` at `uinegNew.py:3605`. That live version reads room areas via `_scaled_room_area_value` (`uinegNew.py:3625-3629`); the dead one uses `room.width * room.height` (`uinegNew.py:6014`). ~48 lines of never-executed statistics rendering.
- **Stale patch-instruction comments** left in the source, addressed to a human editor and no longer true: `uinegNew.py:69-72` (three consecutive "replace the __init__ method with this" comments above the single `__init__` at `:74`), `uinegNew.py:4049` and `:4052` ("In FloorPlanGUI class in uinegNew.py"). Also a stray "# In FloorPlanGUI class" at `uinegNew.py:3562` inside a class body.
- **Duplicated-then-extracted algorithm.** `CADApp.decompose_into_rectangles` (`uinegNew.py:2593`) and `boundary_utils.decompose_boundary_into_rectangles` (`boundary_utils.py:41`) are the same slab-grid decomposition. `boundary_utils.py:45` states it outright: "This is the core algorithm used by both the UI (CAD tool) and the API." They have **already diverged**: the API version normalizes the polygon to a local origin at `boundary_utils.py:76-85` and scales by `unit_spacing` at `boundary_utils.py:70-74`; the GUI version does neither (`uinegNew.py:2597-2610`).
- **Two point-in-polygon families, not four copies of one.** There are four definitions but they implement two different predicates:
  - *Even-odd / strict*: `negNew.py:522-538` and `uinegNew.py:31-47`. Guard `n < 3`, crossing test `(yi > y) != (yj > y)`, `denom != 0`, strict `x < x_at_y`. Byte-identical to each other (claim 7 above).
  - *Min-max / inclusive*: `uinegNew.py:264-278` (`CADApp.point_inside_polygon`) and `boundary_utils.py:7-38`. Test `y > min(p1y, p2y) and y <= max(p1y, p2y) and x <= max(p1x, p2x)`, inclusive `x <= xinters`, plus a `p1x == p2x` vertical-edge special case.

  The two families disagree on points lying exactly on an edge or vertex, so they are not interchangeable. The two min-max copies are also not identical: `boundary_utils.py:31` resets `xinters = None` each iteration and `boundary_utils.py:34` guards `xinters is not None`, while `uinegNew.py:273-275` does neither, so when `p1y == p2y` it compares against a stale `xinters` from a previous iteration (or raises `UnboundLocalError` if that happens on the first edge). `boundary_utils.py:19` also guards `len(polygon) < 3`, which `uinegNew.py:266` lacks (it only checks `if not polygon`). The API copy is the fixed one.
- **`_unit_spacing_factor` (`uinegNew.py:3516`)** computes `spacing ** 2` that the area path intentionally ignores (`uinegNew.py:3552`). Vestigial unless another caller uses it.

## Step 4: sizing logic present in `uinegNew.py` but absent from `negNew.py`

Not lost engine functionality, but worth naming because it is GUI-only and has no API counterpart. Flagged, not deep-dived:

- `CADApp.decompose_into_rectangles` (`uinegNew.py:2593`) - **superseded**, the API has `boundary_utils.decompose_boundary_into_rectangles` (`boundary_utils.py:41`, reached via `api.py:23`, `api.py:1526`). Not lost.
- `CADApp.find_area` (`uinegNew.py:2716`), `find_area_plot` (`:2763`), `find_area_plot2` (`:2788`), `returning_rooms_area` (`:2785`) - interactive area probing. No API equivalent found.
- `FloorPlanGUI.update_area_stats` (`uinegNew.py:3563`), `_scaled_room_area_value` (`:3551`), `_occupied_cells_count` (`:3524`), `_set_room_tree_area` (`:3557`) - the **remaining-area budget** (total minus used, with percentage). The engine has `print_statistics` (`negNew.py:1465`) but no remaining-area accounting exposed the same way. Possible lost UX-level functionality if the API is meant to report space utilisation.
- `FloorPlanGUI._calculate_room_violations` (`uinegNew.py:6291`), `_calculate_constraint_stats_only` (`:6541`) - per-room constraint violation tallies for display.
- `CADApp.merge` (`uinegNew.py:1764`), `draw_cooridors` (`:1758`), `draw_pillars` (`:1794`) - geometry post-processing with no engine counterpart.
- `FloorPlanGUI.place_door` (`uinegNew.py:3822`), `place_window` (`:3918`) - door/window placement on the finished plan.
- `FloorPlanGUI.add_bulk_rooms` (`uinegNew.py:4906`), `save_floor_plan_json` (`:4002`), `load_floor_plan_json` (`:4088`), `restore_floor_plan_from_results` (`:4288`) - project persistence.

None of these are sizing *algorithms* the engine is missing; they are input authoring, reporting and persistence around the same engine.

## Open Questions

1. Is the desktop tool still used by anyone? `GPLAN\documentation\contribution_workflow.md:91` instructs contributors to inspect both files, implying it is still maintained by policy. If nobody runs it, the maintenance tax (keeping ~40 engine call sites in sync) is pure cost.
2. Should `CADApp.decompose_into_rectangles` (`uinegNew.py:2593`) be deleted in favour of importing `boundary_utils.decompose_boundary_into_rectangles` (`boundary_utils.py:41`)? They have already drifted on origin normalization (`boundary_utils.py:76-85`), so the GUI and the API can produce different regions from the same boundary today. Not verified end to end here.
3. The four `point_inside_polygon` definitions cannot simply collapse into one: they are two families with different on-edge behaviour (see Dead Or Duplicated Code). The tractable questions are narrower. (a) Should `CADApp.point_inside_polygon` (`uinegNew.py:264`) be replaced by `boundary_utils.point_inside_polygon` (`boundary_utils.py:7`), which is the same predicate with the stale/unbound `xinters` bug fixed (`boundary_utils.py:31`, `:34`) and a `len(polygon) < 3` guard added (`boundary_utils.py:19`)? Note `CADApp.decompose_into_rectangles` (`uinegNew.py:2626`, `:2633`) depends on the min-max variant's inclusive on-edge behaviour, so this swap needs checking, not assuming. (b) Should the byte-identical even-odd pair (`uinegNew.py:31`, `negNew.py:522`) be deduplicated by having the GUI import the engine's static method? Nothing currently enforces that they stay in sync.
4. Is the remaining-area budget (`uinegNew.py:3563`) something the API should expose? The engine currently has no equivalent field in its response as far as this scoped dive went.
5. The `Space_Optimization` directory has no `__init__.py`, so the API depends on the `sys.path` mutation at `handlers.py:2685-2687`. Whether that is deliberate (to keep the GUI runnable as flat scripts) or accidental was not established.
6. The duplicate `CADApp` methods (`uinegNew.py:1130` vs `:1292`, `:1247` vs `:1401`) differ in body length; whether the shadowed first versions contain behaviour someone intended to keep was not checked (bodies not read).
