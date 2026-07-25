# dim-10: negNew.py core placement and sizing algorithm

Target file: `C:\Users\nitant\Documents\GPLAN_Revamp\GPLAN\Space_Optimization\negNew.py` (1832 lines)

Mirror copy (identical line numbers, byte-for-byte per grep): `C:\Users\nitant\Documents\GPLAN_Revamp\gplan_backend\GPLAN\Space_Optimization\negNew.py`. All cites below use the `GPLAN\Space_Optimization\` path.

## Purpose

negNew.py is a randomized constructive packer. It takes a set of rectangular floor regions and a set of rooms whose width and height are already decided by the caller, then searches for x/y positions for those rooms such that no two overlap, all cells stay inside the region union, requested adjacencies are satisfied and requested non-adjacencies are not. Sizing is a small afterthought layered on top of placement: rooms may be transposed (rotate) and grown by whole units up to a per-room additive budget called `max_expansion`. There is no width or height solver, no area target, no linear program. This is not the LP dimensioning path.

## Where It Sits In The Pipeline

Call chain, verified:

- `GPLAN\GPLAN\api.py:1566` `handle_space_optimization(...)` invoked by the `space_optimization` API op.
- `GPLAN\GPLAN\handlers.py:2659` `handle_space_optimization` definition.
- `handlers.py:2689` `from negNew import FloorPlan`.
- `handlers.py:2696` `floor_plan = FloorPlan(region_specs=regions, fixed_rooms=None)`.
- `handlers.py:2713` `floor_plan.add_room(name, width, height, max_expansion=room.get('max_expansion', 20))`.
- `handlers.py:2731` `floor_plan.add_fixed_room(...)` for pre-placed rooms.
- `handlers.py:2751` `success = floor_plan.generate_layout(max_attempts=..., enable_expansion=..., enable_space_optimization=enable_compaction)` <- **the true entry point for a sizing run**.
- `handlers.py:2763` optional second `floor_plan.compact_rooms()` after `generate_layout` already ran compaction internally.
- `handlers.py:2796-2809` output serialization (x, y, width, height, rotated, area) -> dim-11 scope.

Regions arrive from `boundary_utils.boundary_to_regions`, imported at `api.py:23` and called at `api.py:1526`. Boundary parsing, Y-flipping of fixed rooms (`handlers.py:2724-2730`), and the output/metrics block (`handlers.py:2776-2833`) are dim-11 scope and are only noted here, not documented.

## Map Of The File

Only two top-level definitions exist. `grep -n '^def \|^class '`:

```
11:   class Room
219:  class FloorPlan
```

Method map (`grep -n '^    def '`), with in-scope / out-of-scope marking:

| Line | Member | Scope |
|---|---|---|
| 12 | `Room.__init__` | IN (data structure) |
| 34 | `Room.rotate` | IN (sizing) |
| 38 | `Room.reset_to_original_size` | IN (sizing) |
| 46 | `Room.get_area` | IN |
| 49 | `Room.get_effective_area` | IN |
| 56 | `Room.__repr__` | out (debug) |
| 68 | `Room.get_boundaries` | IN |
| 73 | `Room.get_occupied_cells` | IN |
| 88 | `Room._segments_from_cells` | out (entrance geometry) |
| 106 | `Room._segments_touch` | out (entrance geometry) |
| 141 | `Room.has_shared_wall_with` | IN (adjacency test) |
| 168 | `Room.is_adjacent_to_entrance` | out (dim-11, entrance) |
| 220 | `FloorPlan.__init__` | IN (region consumption) |
| 245 | `compact_rooms` | IN |
| 291 | `_check_overlap_at` | IN, dead |
| 314 | `get_room_by_name` | IN |
| 324 | `_check_non_adjacency_violation_at` | IN |
| 347 | `_total_expansion_used` | IN (sizing budget) |
| 361 | `compact_rooms_up_conditional` | IN |
| 439 | `compact_rooms_right_conditional` | IN |
| 495 | `set_entrance_location` | out |
| 498 | `_get_grid_cells` | IN (spatial hash) |
| 510 | `_rect_cells` | IN |
| 522 | `_point_inside_polygon` | out (fixed-room polygons) |
| 540 | `_polygon_to_cells` | out (fixed-room polygons) |
| 558 | `_add_to_spatial_grid` | IN |
| 568 | `_remove_from_spatial_grid` | IN |
| 578 | `check_overlap_optimized` | IN |
| 597 | `get_valid_positions` | IN (candidate generator) |
| 630 | `add_non_adjacency` | out (input) |
| 634 | `check_non_adjacency_violation` | IN |
| 644 | `add_room` | out (input, dim-11) |
| 691 | `register_special_entity` | out, dead |
| 697 | `_generate_fixed_name` | out |
| 704 | `add_fixed_room` | out (input, dim-11) |
| 733 | `add_adjacency` | out (input) |
| 737 | `is_within_floor` | IN (boundary test) |
| 743 | `point_in_floor` | IN (region consumption) |
| 750 | `check_overlap` | IN |
| 786 | `evaluate_adjacency_score` | IN (the objective) |
| 809 | `_capture_layout_snapshot` | IN |
| 837 | `_restore_layout_snapshot` | IN |
| 875 | `enforce_minimum_adjacency` | IN |
| 955 | `can_expand_room` | IN, dead |
| 999 | `expand_rooms` | IN, dead |
| 1036 | `place_rooms_with_constraints_optimized` | IN (main loop) |
| 1172 | `expand_rooms_optimized` | IN (the only live sizing code) |
| 1238 | `can_expand_room_optimized` | IN, dead |
| 1280 | `visualize` | out (matplotlib) |
| 1465 | `print_statistics` | out |
| 1502 | `to_matrix` | out (dim-11 serialization) |
| 1557 | `floorplan_to_ga_input` | out (dim-11 serialization) |
| 1671 | `ga_runner` | out (GA bridge) |
| 1675 | `generate_layout` | IN (entry point) |

`negNew.py:1772-1832` is an `if __name__ == "__main__"` demo, never executed under the API.

## Entry Points (file:line)

- `negNew.py:1675` `FloorPlan.generate_layout(max_attempts=1000, enable_expansion=True, enable_space_optimization=True)`. Called from `handlers.py:2751` and from the Tk GUI at `GPLAN\Space_Optimization\uinegNew.py:5985`. This is the only production entry.
- `negNew.py:1036` `place_rooms_with_constraints_optimized` is the placement engine. It has a second, non-production caller in the `__main__` demo at `negNew.py:1806`.
- `negNew.py:220` `FloorPlan.__init__` is where regions become the plot model.

## Data Structures

A candidate layout is **a list of mutable rectangle objects, not a grid**. There is no occupancy matrix during search.

- `Room` (`negNew.py:11-30`): `name`, `original_width`/`original_height` (`:14-15`), the live `width`/`height` (`:16-17`), `x`/`y` initialized to `None` meaning unplaced (`:18-19`), `rotated` flag (`:20`), `max_expansion` coerced to int (`:22-25`), `is_fixed` (`:26`), and optional `polygon_coords` / `occupied_cells` for non-rectangular fixed rooms (`:29-30`).
- `FloorPlan.rooms` (`negNew.py:221`) is the single list holding every room, fixed and free alike. `FloorPlan.fixed_rooms` (`:222`) is a separate list that **is always empty on the API path** because `handlers.py:2696` passes `fixed_rooms=None`; fixed rooms instead land in `self.rooms` with `is_fixed=True` via `add_room` at `negNew.py:660-671`. Several methods concatenate `self.fixed_rooms` onto the scan list (`:382`, `:455`, `:759`) and on the API path that concatenation contributes nothing.
- `FloorPlan.floor_regions` (`negNew.py:228-238`): list of dicts `{'x','y','width','height'}`, built either from `(w, h)` tuples stacked vertically (`:229-233`) or copied from region dicts (`:234-238`).
- `FloorPlan.spatial_grid` (`negNew.py:242`, reset at `:1041` and `:1065`): a dict keyed by coarse bucket `(gx, gy)` at `grid_size = 2` (`:243`), value is a list of rooms. Buckets computed at `_get_grid_cells` `negNew.py:498-507`, populated at `_add_to_spatial_grid` `negNew.py:558-566`. This is a broad-phase index only, not the layout itself.
- Unit cell sets: `Room.get_occupied_cells` `negNew.py:73-85` and `FloorPlan._rect_cells` `negNew.py:509-519` materialize 1x1 integer cells, used only to handle non-rectangular fixed rooms in the overlap tests (`:586-589`, `:776-781`).
- A **snapshot** is the serialized candidate layout used by the search: `_capture_layout_snapshot` `negNew.py:809-835` produces `{"rooms": [ {name,x,y,width,height,rotated,original_width,original_height,is_fixed} ], "placed_count", "total_rooms"}`. `_restore_layout_snapshot` `negNew.py:837-873` writes it back onto the live `Room` objects and rebuilds `spatial_grid`.
- `self.last_layout_result` (`negNew.py:1682-1690`, rewritten at `:1145-1153`, `:1161-1169`, `:1744-1751`, `:1756-1766`) carries success / partial / placed_count / best_score out of the run.

## Algorithm Walkthrough

**Paradigm: randomized restart constructive placement with greedy first-fit, followed by deterministic local-repair passes. It is not constraint propagation, not exhaustive search, and there is no neighborhood search over complete layouts.** The only search is "try up to `max_attempts` independent random constructions and keep the best one".

### The main loop

`negNew.py:1064` `for attempt in range(max_attempts):` inside `place_rooms_with_constraints_optimized`. This is the true main loop of the engine. Everything else is a repair pass.

Per attempt:

1. `negNew.py:1065` wipe `spatial_grid`.
2. `negNew.py:1066-1074` for every non-fixed room, clear `x`/`y`, `reset_to_original_size()`, then **rotate with probability 0.5**: `if random.random() > 0.5: room.rotate()`.
3. `negNew.py:1077-1079` insert already-positioned (fixed) rooms into the spatial grid.
4. `negNew.py:1082-1116` iterate rooms in a fixed priority order and place each greedily:
   - candidates from `get_valid_positions(room, max_positions=100)` (`:1091`);
   - **take the first candidate unconditionally**: `x, y = valid_positions[0]` (`:1094`), no scoring among candidates;
   - if none, `room.rotate()` and retry with `max_positions=30` (`:1103-1109`);
   - if still none, mark `placement_successful = False` and `break` out of the room loop (`:1111-1116`).
5. `negNew.py:1119-1121` snapshot the attempt (even if partial) and score it.
6. `negNew.py:1123-1128` keep it as `best_placement` under a lexicographic rule (see formula section).
7. `negNew.py:1130-1133` if all rooms placed, set `full_success = True`; break out of the attempt loop early only if the adjacency score already equals the number of adjacency edges.

Room priority order, `negNew.py:1054-1057`:

```python
room_constraints = {r.name: len(list(self.adjacency_graph.neighbors(r.name))) for r in self.rooms}
sorted_rooms = sorted(self.rooms,
                      key=lambda r: (getattr(r, "is_fixed", False), room_constraints[r.name], r.get_area()),
                      reverse=True)
```

Descending by (is_fixed, adjacency degree, area). Fixed rooms sort first but are then skipped at `:1084`, so effectively: most-constrained-first, ties broken by largest area.

Candidate generation, `get_valid_positions` `negNew.py:597-628`, is two-phase:

- Phase A (`:605-614`): for each already-placed adjacency neighbor, propose the four flush-abutting positions `(adj.x + adj.width, adj.y)`, `(adj.x - room.width, adj.y)`, `(adj.x, adj.y + adj.height)`, `(adj.x, adj.y - room.height)` (`:607-608`). Each is accepted only if `is_within_floor` and not `check_overlap_optimized` and not `check_non_adjacency_violation` (`:610-612`).
- Phase B (`:616-627`): up to 500 uniform random draws `x = random.randint(0, self.floor_width - room.width)`, `y = random.randint(0, self.floor_height - room.height)` (`:620-621`), same three filters plus a duplicate check.

Because the caller takes `valid_positions[0]`, a room with a placed adjacency neighbor gets a flush-abutting position; a room without one gets a **uniformly random legal position**. That randomness is the entire diversity mechanism of the restart loop.

### After a successful construction

`generate_layout` `negNew.py:1675`:

1. `:1692-1699` reset all non-fixed rooms to unplaced original size; reset fixed rooms' size.
2. `:1702-1706` call `place_rooms_with_constraints_optimized(max_attempts=..., enable_expansion=False, use_compact_mode=enable_space_optimization)`. Note `enable_expansion=False` is hardcoded here, so expansion never happens inside the placement loop on this path.
3. `:1711` `for i in range(5):` repeat the repair block five times:
   - `:1713` `compact_rooms()` (down-and-left gravity),
   - `:1717` `compact_rooms_right_conditional()`,
   - `:1720` `compact_rooms_up_conditional()`,
   - `:1724` `enforce_minimum_adjacency()`,
   - `:1737-1740` if `enable_expansion`, `expand_rooms_optimized()`.
   The loop counter `i` is unused inside the body; the five iterations are pure repetition of the same deterministic passes, which converge quickly.
4. `:1744-1751` mark result success.
5. `:1768` `return success`.

Repair passes in detail:

- `compact_rooms` `negNew.py:245-287`: fixpoint `while moved`. Rooms sorted by `(x, y)` ascending (`:269`), fixed rooms skipped (`:270-271`). Each room is walked one unit at a time toward `x = 0` (`:273-279`) then toward `y = 0` (`:281-287`), backing off one step on the first violation of "every unit cell inside some region" (`is_within_any_floor_region`, `:254-264`) or bounding-box overlap with any other room (`overlaps`, `:246-252`).
- `compact_rooms_right_conditional` `negNew.py:439-493`: for each room, find the nearest room to its right that overlaps in Y (`:457-468`), compute `target_x_position = target_room.x - room.width` (`:473`), skip if not a rightward move (`:475-476`), then all-or-nothing accept if `check_overlap(..., ignore_room=room)` is clear, `is_within_floor` holds, and no non-adjacency violation (`:479-486`). Jumps flush against the neighbor in one move.
- `compact_rooms_up_conditional` `negNew.py:361-436`: same shape on the Y axis, `target_y_position = target_room.y - room.height` (`:408`), and it maintains the spatial grid on the move (`:428-430`), which the right variant does not.
- `enforce_minimum_adjacency` `negNew.py:875-953`: bounded fixpoint, `max_loops = len(self.rooms) * 2` (`:884`). For each adjacency edge whose rooms do not already share a wall (`:897-898`), pick the non-fixed one as the mover (`:900-908`), and try the four flush positions around the stationary room (`:910-915`), verifying true edge contact with the `touches_x / y_range_overlap` test at `:918-928`, then boundary, overlap and non-adjacency safety (`:933-940`), then commit and restart the whole scan (`:945-951`).

## The Actual Constraints Or Formulas

### 1. How width and height are fixed

There is no formula that computes a width or height from an area or an aspect ratio. Room dimensions are the caller's numbers, transformed by exactly three operations:

**(a) Assignment from input**, `negNew.py:14-17`:

```python
self.original_width = width
self.original_height = height
self.width = width
self.height = height
```

Fed from `handlers.py:2713-2718` with `room['width']`, `room['height']`.

**(b) Transposition**, `Room.rotate` `negNew.py:34-36`:

```python
self.width, self.height = self.height, self.width
self.rotated = not self.rotated
```

Applied with probability 0.5 per room per attempt at `negNew.py:1073-1074`, and again as a fallback when first-fit fails at `negNew.py:1103`. Area is invariant under rotation. `reset_to_original_size` `negNew.py:38-44` restores dimensions honoring the current `rotated` flag.

**(c) Unit growth**, `expand_rooms_optimized` `negNew.py:1172-1236`, the only live sizing code. Per pass, rooms are shuffled (`:1181`, reshuffled at `:1236`), and for each room in each direction from `['right','up','left','down']` (`:1178`) it proposes a **one-unit** change (`:1204-1213`):

```python
if direction == 'right':   new_width  += 1
elif direction == 'left':  new_x -= 1; new_width  += 1
elif direction == 'up':    new_height += 1
elif direction == 'down':  new_y -= 1; new_height += 1
```

and commits at `:1230-1233` only if all three guards pass:

- budget: `self._total_expansion_used(room) >= max_allowed` breaks the direction loop (`:1199`), and the redundant `self._total_expansion_used(room) + 1 > max_allowed` continues (`:1215`). Both evaluate the same pre-move value, so `:1215` is a duplicate of `:1199`.
- boundary: `self.is_within_floor(new_x, new_y, new_width, new_height)` (`:1219`).
- collision: `not self.check_overlap(new_x, new_y, new_width, new_height, ignore_room=room)` (`:1223`).
- separation: `not self._check_non_adjacency_violation_at(room, new_x, new_y)` (`:1227`). Note this helper builds its temp room from `room.width`/`room.height`, the **pre-expansion** size (`negNew.py:332-334`), so the non-adjacency check for an expansion tests the old footprint at the new origin, not the grown rectangle.

The outer `while can_expand_any:` at `:1184` repeats until a full pass grows nothing, so growth is a greedy fixpoint, one unit at a time, in shuffled room order. Fixed rooms and unplaced rooms are skipped at `:1187`.

**The expansion budget formula**, `_total_expansion_used` `negNew.py:346-359`:

```python
if not room.rotated:
    extra_w = room.width  - room.original_width
    extra_h = room.height - room.original_height
else:
    extra_w = room.width  - room.original_height
    extra_h = room.height - room.original_width
return max(0, extra_w) + max(0, extra_h)
```

So the budget is on the **sum of the width delta and the height delta in grid units**, not on either dimension separately and not on area. A room with `max_expansion = 20` and starting size 10x8 could legally become 30x8, 10x28, or 20x18. Nothing caps the resulting aspect ratio.

### 2. The objective function

`evaluate_adjacency_score` `negNew.py:786-807` returns `(score, adjacent_pairs, violations)`. Term by term:

- `negNew.py:793` `score += 1` for each edge of `adjacency_graph` whose two rooms both exist, are both placed, and satisfy `room1.has_shared_wall_with(room2)`.
- `negNew.py:798` `score += 1` for each adjacency edge where one endpoint is not a real room (an entrance pseudo-node) and the surviving room satisfies `is_adjacent_to_entrance(self.entrance_coords)` (`:795-797`).
- `negNew.py:805` `score -= 2` for each edge of `non_adjacency_graph` whose two placed rooms do share a wall.

Area, compactness, utilization and aspect ratio do **not** appear in the objective. Area utilization is computed only for reporting, at `handlers.py:2789-2830`, after the fact.

Shared-wall predicate, `has_shared_wall_with` `negNew.py:141-166`: for cell-based rooms, 4-neighborhood cell contact (`:152-155`); for rectangles, exact coordinate equality of opposing edges plus strictly positive overlap of the perpendicular interval, for example `if right1 == left2: return max(bottom1, bottom2) < min(top1, top2)` (`:158-159`). Corner-only touching does not count.

### 3. The selection rule between attempts

`negNew.py:1123-1128`:

```python
if (current_placed_count > best_placed_count) or (
    current_placed_count == best_placed_count and score > best_score
):
```

Lexicographic: maximize number of rooms placed first, then maximize adjacency score. Early exit at `:1132`: `if score == len(self.adjacency_graph.edges): break`. Note this compares against the raw edge count while `score` can be inflated by entrance credits (`:798`) and deflated by non-adjacency penalties (`:805`), so the early exit is a heuristic, not an optimality proof.

### 4. Overlap and boundary predicates

- `is_within_floor` `negNew.py:737-741`: brute force over every unit cell `(x+dx, y+dy)` of the rectangle, each must satisfy `point_in_floor`. O(w*h) per query.
- `point_in_floor` `negNew.py:743-748`: true if the point falls in **any** region's half-open box `region['x'] <= x < region['x'] + region['width']` and likewise in Y.
- `check_overlap` `negNew.py:750-784`: linear scan over `[r for r in self.rooms if r.x is not None] + self.fixed_rooms` (`:759`), bounding-box test at `:769-772`, refined to cell-set intersection when the other room has `occupied_cells` (`:776-781`).
- `check_overlap_optimized` `negNew.py:578-595`: same semantics but restricted to rooms found in the `grid_size = 2` spatial hash buckets of the candidate rectangle.

## Invariants And Preconditions

- Every room is a single axis-aligned rectangle with integer-valued `x, y, width, height`, except fixed rooms carrying explicit `occupied_cells` or `polygon_coords`.
- `x is None` (or `y is None`) means "not placed". Every scan guards on this (`:1078`, `:762` via the comprehension at `:759`, `:894`, `:1187`).
- Rooms with `is_fixed = True` are never moved, never rotated and never expanded: skipped at `:1046-1047`, `:1067-1068`, `:1084-1085`, `:270-271`, `:374`, `:450`, `:901-908`, `:1187`.
- The plot is the **union** of regions, not their disjunction: a room may straddle two regions as long as every one of its unit cells lies in some region (`is_within_any_floor_region` `:254-264`, `is_within_floor` `:737-741`).
- `region_specs` must be non-empty; `FloorPlan.__init__` indexes `region_specs[0]` at `:229` and calls `max(...)` over the regions at `:240-241` with no empty guard.
- `floor_width` / `floor_height` (`:240-241`) are the bounding box of the region union, so random sampling at `:620-621` can propose points outside the union; `is_within_floor` filters them.
- `spatial_grid` is only trustworthy where it is maintained. `place_rooms_with_constraints_optimized` and `_restore_layout_snapshot` maintain it, and `compact_rooms_up_conditional` maintains it (`:428-430`), but `compact_rooms` (`:245-287`), `compact_rooms_right_conditional` (`:489`), `enforce_minimum_adjacency` (`:945-946`) and `expand_rooms_optimized` (`:1232`) mutate coordinates without updating it. The repair passes therefore deliberately use the non-indexed `check_overlap` rather than `check_overlap_optimized`.
- `add_adjacency` / `add_non_adjacency` silently drop edges naming an unknown room (`:733-735`, `:630-632`), so an adjacency to a not-yet-added room vanishes.

## Failure Modes

**Definition of failure**: a single room for which `get_valid_positions` returns empty in both the normal and the rotated orientation. Set at `negNew.py:1111-1116`:

```python
if not placed:
    placement_successful = False
    ...
    break
```

That aborts the current attempt. `full_success` stays False unless some attempt places everything (`:1130-1131`).

Failure return path:

- `negNew.py:1135-1154`: because `_capture_layout_snapshot` always returns a truthy dict and the first attempt always beats `best_placed_count = -1` (`:1061`, `:1123`), `best_placement` is set on attempt 0. The function restores the best partial layout, **skips expansion** (`:1142` requires `full_success`), writes `last_layout_result` with `"success": False, "partial": True` (`:1145-1153`) and returns `bool(full_success)` = `False` at `:1154`.
- `negNew.py:1156-1170` is the "no snapshot at all" path. It is **unreachable for any `max_attempts >= 1`**, for the reason just given. It would only run if `max_attempts <= 0`.
- `generate_layout` takes the else branch at `:1753-1766`, re-restores the best partial snapshot (`:1759`) and records `partial` / `placed_count`, then returns `False` at `:1768`.
- `handlers.py:2757-2759`: `ui.set_message("Failed to generate space-optimized layout"); return False`.
- `api.py:1580-1584` converts that into an error response.
- Note the partial layout is left on the `FloorPlan` object and in `last_layout_result`, but `handle_space_optimization` returns before reading either, so **on the API path the partial best layout is computed and then discarded**.

Other ways a run dies:

- `random.randint(0, self.floor_width - room.width)` at `negNew.py:620` raises `ValueError` when a room is wider than the region bounding box (empty range). Same for height at `:621`. This escapes to the blanket `except Exception` at `handlers.py:2838-2843`, which returns False with the exception text.
- `is_within_floor` at `:738-739` calls `range(width)`, so non-integer widths raise `TypeError`, caught by the same handler.
- Infinite-loop risk: `compact_rooms` (`:266-268`), `compact_rooms_up_conditional` (`:370`), `compact_rooms_right_conditional` (`:447`) and `expand_rooms_optimized` (`:1184`) are unbounded `while` fixpoints with no iteration cap. They terminate because each pass is strictly monotone (coordinates decrease, or sizes increase against a finite budget), but there is no guard if that monotonicity is ever broken. `enforce_minimum_adjacency` is the only pass with an explicit cap (`:884`).
- Cost: `is_within_floor` is O(w*h) with a Python loop and is called inside the innermost candidate loops (`:610`, `:622`, `:1219`), so large plots get slow fast.

**Suspected defect in `enforce_minimum_adjacency`**, `negNew.py:936-937`:

```python
is_safe_overlap = not self.check_overlap(new_x, new_y, room_to_move.width, room_to_move.height,
                                         ignore_room=stationary_room)
```

The ignored room is the stationary one, not the mover. `room_to_move` is still parked at its old coordinates and is still in `self.rooms`, so any target position whose rectangle intersects the mover's own current rectangle is rejected as an overlap with itself. Short adjacency repairs (the common case, since the mover is usually already close) are therefore silently refused. Ignoring `stationary_room` is also unnecessary: the four candidate positions at `:910-915` are flush by construction, so they cannot overlap it. Compare the correct usage in the two conditional compactors (`:416-417`, `:479-480`) and in the expander (`:1223`), all of which pass `ignore_room=room`.

## Coupling (what breaks if you change this)

- **Room dict shape** is a hard contract with `handlers.py:2713-2718` and `handlers.py:2731-2740` (`name`, `width`, `height`, `max_expansion`, plus `x`, `y`, `polygon`, `occupied_cells` for fixed rooms) and with the output block at `handlers.py:2796-2809` which reads `room.x/y/width/height/rotated/is_fixed/original_width/original_height/get_area()`. Renaming any `Room` attribute breaks serialization.
- **Region dict shape** `{'x','y','width','height'}` is consumed at `negNew.py:235-241` and `:743-748`, produced by `boundary_utils.boundary_to_regions` via `api.py:1526`, and echoed back verbatim into the response as `floor_regions` at `handlers.py:2778`. Changing the region schema breaks all three at once.
- **`self.fixed_rooms` vs `is_fixed`**: the dual representation is a trap. Passing a real list into the `FloorPlan(region_specs, fixed_rooms=...)` constructor would make those rooms appear in the `+ self.fixed_rooms` scans at `:382`, `:455`, `:759` but not in `self.rooms`, so they would be invisible to `compact_rooms` (`:276`), to `_check_overlap_at` (`:296`), to `check_overlap_optimized` (which only sees the spatial grid), and to `evaluate_adjacency_score` (`:789-790` and `:801-802` search `self.rooms` only). Keep passing `None`.
- **`grid_size = 2`** (`negNew.py:243`) couples `_get_grid_cells` to `_add_to_spatial_grid` and `check_overlap_optimized`. Changing it changes only performance, not correctness, as long as `_get_grid_cells` stays the single bucket function.
- **`max_expansion` semantics** (a summed delta budget, `:346-359`) is assumed by `expand_rooms_optimized` (`:1199`, `:1215`), by the dead `can_expand_room` (`:970`) and `can_expand_room_optimized` (`:1253`), and by the statistics printer at `:1497`. The GUI surfaces it as a "Max Expansion" tree column (`uinegNew.py:4453`, `:5396`). Redefining it as a maximum dimension would need all six sites changed.
- **Snapshot schema** (`:818-828`) is read back field by field at `:861-867`. Adding a `Room` attribute that matters to placement without adding it to the snapshot means that attribute silently reverts on every restore, including the restore that runs at `:1137` before the caller ever sees the result.
- **`generate_layout` also compacts internally** (`:1713`). `handlers.py:2763` runs `compact_rooms()` a seventh time afterwards, which per the comment at `negNew.py:1727-1731` is exactly the call the author removed from `generate_layout` because it undoes the conditional right-shift. The handler reintroduces that undo whenever `enable_compaction` is true.
- `import ga_current as ga` at `negNew.py:8` is a module-level import, so a broken `ga_current.py` prevents the placement engine from importing at all even though the GA path (`:1671`) is unrelated to sizing.

## Dead Or Duplicated Code

Verified by grepping the whole repo for each name (`*.py`), counting only call sites, not definitions.

Dead within scope:

- `negNew.py:999` `expand_rooms` - no callers anywhere in the repo. **Dead code.** Superseded by `expand_rooms_optimized` (`:1172`).
- `negNew.py:955` `can_expand_room` - the only call site is inside the dead `expand_rooms` at `:1019`. **Transitively dead.**
- `negNew.py:1238` `can_expand_room_optimized` - no callers anywhere. **Dead code.** Note it is not a drop-in replacement for the inline logic in `expand_rooms_optimized`: it compares against `room.max_expansion` directly (`:1253`) instead of the coerced `max_allowed`, and it omits the non-adjacency check.
- `negNew.py:291` `_check_overlap_at` - no callers anywhere. **Dead code.** Functionally duplicates `check_overlap` (`:750`) minus the `occupied_cells` refinement and minus the `self.fixed_rooms` scan.
- `negNew.py:1036` parameter `use_compact_mode` - accepted in the signature, passed real values from `:1705` and defaulted at `:1806`, but **never read anywhere in the function body** (`:1036-1170`). It is a no-op parameter, so `enable_compaction=False` at the API level does not disable compaction inside `generate_layout`; only the extra call at `handlers.py:2762-2763` is gated.
- `negNew.py:1156-1170` - the second `return False` block. **Unreachable** for `max_attempts >= 1` because `best_placement` is always assigned on the first attempt (`:1061` initializes `best_placed_count = -1`, `:1123` compares `> -1` against a non-negative count).
- `negNew.py:1044`, `:1113-1114` - loop counter `i` initialized then printed and incremented only in the failure branch. Debug vestige, no effect on the algorithm.
- `negNew.py:1711` `for i in range(5)` - `i` unused; the block is repeated five times unconditionally with no convergence check and no early break.

Dead adjacent to scope:

- `negNew.py:691` `register_special_entity` - no callers anywhere in the repo. **Dead code.** It exists to let an entrance node join the adjacency graph, which is what `evaluate_adjacency_score:795-799` expects, so the entrance-credit branch of the objective can only fire if some caller adds such a node by another route.

Duplication:

- `negNew.py` and `gplan_backend\GPLAN\Space_Optimization\negNew.py` are the same file at the same line numbers (submodule checkout). Edits must land in the `GPLAN` submodule, per the repo memory note that the engine source of truth is `nitantupasani/gplan_engine`.
- Expansion-limit arithmetic is written three times: `:961-967` (dead), `:1245-1251` (dead), `:352-357` (live). The live one differs by clamping each term with `max(0, ...)`; the two dead copies do not clamp, so a shrunk dimension would credit budget back.
- Overlap testing exists in three forms: `check_overlap` (`:750`, live), `check_overlap_optimized` (`:578`, live, spatial-hash), `_check_overlap_at` (`:291`, dead).
- `negNew.py:1772-1832` `__main__` demo block: never executed by the API or the GUI, and it calls `place_rooms_with_constraints_optimized` directly (`:1806`) rather than `generate_layout`, so it exercises a different sequence than production.

## Open Questions

1. Where do `width` and `height` reaching `handlers.py:2713` come from, and do they represent minimum room dimensions or target dimensions? The engine treats them as an exact starting size, never as a floor to be enforced. This is dim-11 / caller scope.
2. **Are user minimum and maximum dimensions honored at all?** Plainly: negNew.py has no concept of a minimum or a maximum room dimension. A repo-wide grep for `min_width|max_width|min_height|max_height|min_area|max_area|min_dim|max_dim` inside `negNew.py` returns only `:1387-1390`, which are matplotlib axis limits in `visualize`. `handle_space_optimization` (`handlers.py:2659-2843`) reads only `name`, `width`, `height`, `max_expansion`, `x`, `y`, `polygon`, `occupied_cells`. **Minimums are expressed implicitly, as the supplied `width`/`height`, and are guaranteed only because nothing ever shrinks a room. Maximums are not modeled: the only cap is `max_expansion`, a budget on `(Δwidth + Δheight)` in grid units (`negNew.py:346-359`), enforced at `:1199` and `:1215`. A caller who wants "bedroom no wider than 14" cannot express it.** The API default when a room omits the field is `20` (`handlers.py:2717`), which is generous, and `add_room`'s own default is `3` (`negNew.py:644`).
3. The `enforce_minimum_adjacency` `ignore_room=stationary_room` argument (`:936-937`) looks wrong for the reason given under Failure Modes. Was it intentional? A quick experiment (move a room whose target rect overlaps its current rect) would settle it.
4. Why five iterations at `:1711`? No convergence criterion, no measurement. Whether iterations 2 through 5 ever change anything is untested.
5. `compact_rooms_right_conditional` does not update `spatial_grid` on its move (`:489`) while `compact_rooms_up_conditional` does (`:428-430`). Since only `check_overlap_optimized` and `get_valid_positions` read the grid, and neither runs after placement, this is probably harmless today, but it is an inconsistency waiting to bite if expansion is ever switched to the optimized checker.
6. The entrance-adjacency credit at `:795-799` requires an adjacency edge with a non-room endpoint. With `register_special_entity` dead and `add_adjacency` dropping unknown names (`:733-735`), it is unclear whether that branch can ever execute on the API path.
