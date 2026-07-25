# dim-13: GA "sizing" core (ga_current.py, part 1)

Target file: `C:\Users\nitant\Documents\GPLAN_Revamp\GPLAN\Space_Optimization\ga_current.py`
(A byte-for-symbol identical second copy exists at `C:\Users\nitant\Documents\GPLAN_Revamp\gplan_backend\GPLAN\Space_Optimization\ga_current.py`: every symbol reported by grep sits on the same line number in both, consistent with `GPLAN/` being vendored into `gplan_backend/` as a submodule. All cites below are against the `GPLAN\Space_Optimization` path.)

Scope of this dossier: encoding, fitness, selection, crossover, mutation, evolution loop. The C libraries (`bfs`, `corridor_creator`, `boundary_accessible_corridors`), their ctypes loading, and `handle_ga_optimization` are dim-14's; ctypes call sites are only pointed at here.

## Headline finding, read this first

**This engine does not size rooms. It translates them.** A room's cell set is frozen at parse time (`parse_json_floorplan` fills each room's bounding box into `coords`, ga_current.py:548-557) and every GA operator only adds an integer `(dr, dc)` offset to every cell of that set (`apply_chromosome`, ga_current.py:651-659). No gene encodes width, height, or area. There is no min/max dimension input anywhere in the module: grep for `min_width|max_width|min_height|max_height|min_dim|max_dim` over the whole file returns nothing, and the only `room_dimensions` argument (`run_ga` signature, ga_current.py:1213) is forwarded untouched to `visualize_layout` (ga_current.py:1405-1406) where it is used solely to print `"{w}x{h}"` under the room label on a matplotlib PNG (ga_current.py:1547-1549). Calling this a "sizing engine" is a misnomer: it is a rigid-body placement plus corridor-carving search.

## Purpose

Given an already-dimensioned set of rectangular rooms laid on an integer grid, find integer (row, column) displacements for each room such that the corridor network auto-carved between the displaced rooms is one connected component, touches every room, occupies roughly 20 percent of used area, and does not leak to the plot boundary, with room-room overlap heavily penalized.

## Where It Sits In The Pipeline

1. `api.py` accepts `engine: "GA_FloorPlan"`, pulls `corridor_width` and `ga_config` from the request params (`GPLAN\GPLAN\api.py:1693-1694`) and calls `handle_ga_optimization` (`GPLAN\GPLAN\api.py:1701-1705`).
2. `handle_ga_optimization` (`GPLAN\GPLAN\handlers.py:2845`) overwrites the GA's module-level globals from `ga_config` (handlers.py:2873-2885), parses the payload into a grid (`parse_json_floorplan`, handlers.py:2914), monkey-patches `ga_current.visualize_layout` to a no-op (handlers.py:2921-2926), calls `run_ga` (handlers.py:2935-2941), then decodes the winning chromosome itself via `apply_chromosome` (handlers.py:2953) and `corridor_creator` (handlers.py:2973). Detail belongs to dim-14.
3. Inside `run_ga`, fitness evaluation calls out to the three C shared libraries loaded at ga_current.py:83-93. dim-14 owns those.

The second in-repo caller is `negNew.py:1673` (`GeneratorClass.ga_runner`), the desktop/legacy path; it passes `room_dimensions` built at negNew.py:1655-1663 as actual `(room.width, room.height)`, again label-only.

## Entry Points (file:line)

| Symbol | Line | Note |
|---|---|---|
| `run_ga` | ga_current.py:1210 | the whole evolution loop; returns best chromosome or `None` |
| `calculate_fitness` | ga_current.py:1026 | the objective |
| `calculate_fitness_cached` | ga_current.py:1161 | memoizing wrapper, the one actually called |
| `selection` | ga_current.py:1174 | tournament |
| `crossover` | ga_current.py:1180 | uniform |
| `mutation` | ga_current.py:1190 | clamped creep |
| `apply_chromosome` | ga_current.py:651 | decoder, also called by the handler |
| `compute_valid_displacements` | ga_current.py:622 | gene domain |
| `_init_worker` / `_fitness_worker` | ga_current.py:132 / 138 | multiprocess path only |

### Full symbol map (grep `^def `, `^class `)

```
19   class Wall                              (dataclass)
28   class Label                             (dataclass)
35   class Room                              (dataclass)
42   class Floorplan                         (dataclass)
51   def parse_floorplan_json
72   def get_lib_extension
132  def _init_worker
138  def _fitness_worker
150  class RoomGA                            (dataclass; __post_init__ at 163)
408  def corridor_creator                    (ctypes shim -> dim-14)
429  def parse_floor_plan
460  def parse_json_floorplan
567  def floorplan_to_json
622  def compute_valid_displacements
651  def apply_chromosome
662  def ga_solution_to_floorplan_json
789  def calculate_corridor_connectivity     (ctypes -> dim-14)
797  def count_rooms_adjacent_to_corridor
818  def count_isolated_rooms
920  def count_boundary_accessible_corridors  (ctypes -> dim-14)
999  def build_room_adjacency_graph
1026 def calculate_fitness
1161 def calculate_fitness_cached
1174 def selection
1180 def crossover
1190 def mutation
1210 def run_ga
1409 def visualize_layout
1634 if __name__ == "__main__":
```
Lines 170-407 and 843-997 are large blocks of commented-out previous implementations of `corridor_creator` and `count_boundary_accessible_corridors` (two dead copies each: 170, 282, 843, 936). Not read line by line, identified by the leading `# def` markers.

## Data Structures

### RoomGA (ga_current.py:150-168)
`id: int`, `coords: List[(row, col)]` (explicit cell list, not a rect), `block: bool`, `sub_coords: Optional[Dict[int, coords]]` for composite rooms, `name`, `original_data` (the raw JSON room dict, used later by the handler to transform walls), plus `min_r/max_r/min_c/max_c/area` derived in `__post_init__` (ga_current.py:163-168). `area` is `len(coords)`, fixed forever.

### The chromosome
`Sequence[Tuple[int, int]]`. Length equals number of rooms. Position `i` corresponds to `sorted_room_ids[i]` where `sorted_room_ids = sorted(initial_rooms.keys())` (ga_current.py:1226), and the decoder independently re-sorts (`sorted(rooms.keys())`, ga_current.py:654). There is no room id stored in the gene; the ordering convention is the only link.

### Working matrices
- `region_matrix`: numpy `<U1` array, `'#'` = unusable, `' '` = usable. Built in `parse_json_floorplan` at ga_current.py:472, then **the whole plot is stamped usable** at ga_current.py:560 (`region_matrix[:, :] = ' '`), so in the API path there are no `'#'` cells at all.
- `layout_matrix`: int array; `0` empty, `-1` unusable, `>0` room id, `99` = `CORRIDOR_FINAL` corridor (ga_current.py:145), `-2` overlap marker (visualization only, ga_current.py:1483).

## Answers

### 1. CHROMOSOME: what an individual encodes

An individual is a flat list of one gene per room, each gene a 2-tuple of integer grid displacements:

```
gene[i] = (dr, dc)   applied to sorted_room_ids[i]
```

Construction of a random individual, ga_current.py:1243-1251:
```python
population = []
for _ in range(POPULATION_SIZE):
    chromosome = []
    for room_id in sorted_room_ids:
        dr_range, dc_range = valid_displacements[room_id]
        dr = random.randint(dr_range[0], dr_range[1])
        dc = random.randint(dc_range[0], dc_range[1])
        chromosome.append((dr, dc))
    population.append(chromosome)
```

Gene enumeration:

| Gene index | Meaning | Value range | Set by |
|---|---|---|---|
| `i`, first element `dr` | whole-room vertical shift, in grid cells, positive = down | `[-room.min_r, (region_height - 1) - room.max_r]` | ga_current.py:641-646 |
| `i`, second element `dc` | whole-room horizontal shift, positive = right | `[-room.min_c, (region_width - 1) - room.max_c]` | ga_current.py:643-646 |
| any gene of a room listed in `fixed_room_ids` | pinned | exactly `((0,0),(0,0))` | ga_current.py:631-633 |

Decoding is pure translation, ga_current.py:654-657: `new_coords = [(r + dr, c + dc) for r, c in rooms[room_id].coords]`.

So: **no widths, no heights, no rotation, no grid of occupancy, no ordering/slicing tree.** Position only, and only rigid position. The `optimized_bounds` the API returns (handlers.py:3000-3016) are just the translated original bounding box.

Note the doc mismatch: `ga_optimization_api.md:110` and `:438` describe `solution_chromosome` as a digit string like `"0123213021"`. The real payload field is `ga_solution`, a list of `(dr, dc)` int pairs (handlers.py:3021-3026, 3036). The documented shape does not exist in code.

### 2. FITNESS: term by term

`calculate_fitness(chromosome, initial_rooms, region_matrix, fixed_room_ids)` at ga_current.py:1026-1159. Weight table at ga_current.py:116-125:

```python
WEIGHTS = {
    "area": 1.0,                            # 117
    "overlap": 50000,                       # 118
    "corridor_ratio": 10000,                # 119
    "corridor_conn": 25000,                 # 120
    "boundary_corridor": 0,                 # 121
    "boundary_accessible_corridor": 3300,   # 122
    "room_corridor_adj": 50000,             # 123
    "isolated_rooms": 5000,                 # 124
}
```
All eight are hardcoded magic numbers; none is reachable from the request payload (the handler only overrides `POPULATION_SIZE`, `NUM_GENERATIONS`, `INITIAL_MUTATION_RATE`, `TOURNAMENT_SIZE`, handlers.py:2874-2885).

The final formula, ga_current.py:1130-1137:
```python
base_reward   = WEIGHTS["corridor_conn"] + WEIGHTS["room_corridor_adj"]      # 1130  = 75000, constant
total_penalties = (area + overlap + corridor_ratio + boundary_corridor +
                   boundary_accessible_corridor + isolated_rooms +
                   corridor_conn + room_corridor_adj + movable_fixed_overlap) # 1132-1135
fitness = base_reward - total_penalties                                       # 1137
```
`base_reward` is a constant 75000 offset. It changes the sign of reported fitness, not the ranking of individuals. Everything that actually discriminates is a penalty.

Term by term:

1. **Area penalty**, ga_current.py:1111. `area_penalty = actual_used_area * 1.0`, where `actual_used_area = total_room_cells + corridor_cells` (ga_current.py:1088-1090). Since rooms are rigid, `total_room_cells` is identical for every individual, so this term is effectively "1 point per corridor cell": a weak pressure toward less corridor.

2. **Overlap penalty**, ga_current.py:1112. `overlap_count * 50000`. `overlap_count` is incremented per cell, ga_current.py:1073-1081: once when a movable room's cell lands on a `'#'` unusable cell (line 1073-1074), and once when it lands on a cell already holding a *different* positive room id (line 1080-1081). Note the whole-plot-usable stamp at ga_current.py:560 makes the `'#'` branch unreachable in the API path.

3. **Movable-vs-fixed overlap penalty**, ga_current.py:1128. `movable_fixed_overlap * 10000`, an inline magic number not in `WEIGHTS`. `movable_fixed_overlap` counts cells where a movable room lands on a cell precomputed as belonging to a fixed room (ga_current.py:1044-1048, 1066-1070). Note it is *cheaper per cell* than plain overlap (10000 vs 50000) despite the comment "Add HUGE penalty".

4. **Corridor ratio penalty**, ga_current.py:1116-1117. `abs(corridor_ratio - dynamic_target_ratio) * 10000`, where `corridor_ratio = corridor_cells / (actual_used_area + 1e-6)` (ga_current.py:1091). Target is `TARGET_CORRIDOR_RATIO = 0.2` (ga_current.py:146) unless the plan is more than 75 percent full, in which case the target collapses to whatever empty fraction remains: ga_current.py:1098-1101.

5. **Boundary corridor penalty**, ga_current.py:1103-1106 and 1113. Counts corridor cells on the four outer rows/columns, multiplied by `WEIGHTS["boundary_corridor"] = 0`. **Dead term**: computed on every evaluation, always contributes exactly 0. Kept only for the `boundary_corridors` stat (ga_current.py:1151).

6. **Boundary-accessible corridor penalty**, ga_current.py:1109 and 1114. `count_boundary_accessible_corridors(...) * 3300`. Counts "entry points" where the corridor network leaks to the plot exterior; implementation is a ctypes call into `boundary_accessible_corridors` (ga_current.py:929-933, dim-14).

7. **Isolated rooms penalty**, ga_current.py:1108 and 1118. `count_isolated_rooms(...) * 5000`. `count_isolated_rooms` (ga_current.py:818-841) counts rooms with no orthogonally adjacent *other room* cell, i.e. rooms floating in corridor/empty space.

8. **Corridor connectivity penalty**, ga_current.py:1120-1121. `(num_corridor_components - 1) * 25000` when more than one component, else 0. `num_corridor_components` is the ctypes `bfs` call (ga_current.py:789-795, dim-14). This is the "corridor_conn reward" named in the weight comment, implemented as a penalty against the constant `base_reward`.

9. **Room-corridor adjacency penalty**, ga_current.py:1123-1125. `(1 - adj_ratio) * 50000` where `adj_ratio = num_adj_rooms / len(initial_rooms)` and `num_adj_rooms = count_rooms_adjacent_to_corridor(...)` (ga_current.py:797-816): a room counts if any of its cells has an orthogonal neighbor equal to `CORRIDOR_FINAL`. This is the closest thing to an "accessibility" term.

**What is NOT in the fitness function:**
- No room-to-room adjacency-requirement satisfaction. `build_room_adjacency_graph` (ga_current.py:999-1023) computes exactly that graph and **is never called** (see Dead Code). The API doc's "Wall-Based Adjacency ... rooms sharing walls are automatically considered adjacent" (`ga_optimization_api.md:12`, `:710`) is not enforced by any fitness term; shared walls only shrink the initial bounding boxes at parse time (ga_current.py:509-534).
- No dimension violation term of any kind.
- No boundary-of-plot containment term: containment is structural, via the gene domain (see 3).
- No aspect-ratio, no daylight, no door term.

The returned `stats` dict (ga_current.py:1139-1157) mirrors these values and is what the console printing and the halfway-restart check consume.

### 3. How user min/max room dimensions constrain evolution

**They do not. There is no mechanism.** Concretely:

- No parameter named min/max width/height/dimension exists in the module (grep over the file: only `room_dimensions` at ga_current.py:1213, 1406, 1409, 1547-1549, and 1568-1569 inside a commented block).
- `run_ga`'s `room_dimensions` argument (ga_current.py:1213) is never used inside the loop; it is forwarded once to `visualize_layout` (ga_current.py:1405-1406) and there only rendered as text (ga_current.py:1547-1549).
- The handler never passes it at all (handlers.py:2935-2941 passes only `initial_grid`, `region_matrix`, `corridor_width`, `room_names`, `max_workers`), so on the API path it is `None`.
- Room extents come from the payload wall geometry and are frozen at ga_current.py:548-557; nothing in `mutation` (ga_current.py:1190-1208), `crossover` (1180-1188) or fitness can change a room's cell count.

What clamping *does* exist is positional, not dimensional: `mutation` clamps the mutated displacement into the per-room valid range (ga_current.py:1203-1204, `dr = max(dr_range[0], min(dr_range[1], dr))`), and that range (ga_current.py:641-646) is exactly "the room's bounding box stays inside the region rectangle". So plot containment is a hard structural invariant; room size is simply not a decision variable.

If a caller wants min/max room dimensions honoured, that has to happen upstream, before `parse_json_floorplan`.

### 4. The evolution loop

`run_ga`, ga_current.py:1210-1408.

| Knob | Value | Set at | Payload-controllable? |
|---|---|---|---|
| `POPULATION_SIZE` | 10 | ga_current.py:95 | yes, `ga_config.population_size` overwrites the module global at handlers.py:2874-2875 |
| `NUM_GENERATIONS` | 30 | ga_current.py:96 | yes, handlers.py:2876-2877 |
| `INITIAL_MUTATION_RATE` | 0.1 | ga_current.py:97 | yes, handlers.py:2878-2879 |
| `TOURNAMENT_SIZE` | 8 | ga_current.py:99 | derived, `min(8, max(2, POPULATION_SIZE // 4))` at handlers.py:2885, never from payload directly |
| `MUTATION_STRENGTH` | 6 | ga_current.py:98 | no, hardcoded |
| `ENABLE_ADAPTIVE_MUTATION` | True | ga_current.py:102 | no |
| `STAGNATION_THRESHOLD` | 10 generations | ga_current.py:103 | no |
| `MUTATION_RATE_INCREASE` | +0.04 | ga_current.py:104 | no |
| `MAX_MUTATION_RATE` | 0.65 | ga_current.py:105 | no |
| `max_restarts` | 10 | ga_current.py:1231 | no |
| `CORRIDOR_WIDTH` | 3 default, overwritten per run | ga_current.py:107, reassigned ga_current.py:1221-1222 | yes, `params.corridor_width` -> api.py:1693 -> handlers.py:2938 |
| `max_workers` | 1 | `run_ga` default ga_current.py:1216 | yes, `ga_config.max_workers`, handlers.py:2880-2881 |

Note the defaults are 10 and 30. `ga_optimization_api.md:80-82` documents defaults of 200 and 600, and the examples at `:192-194` and `:351-353` send those. The doc is wrong about the code defaults, and true 200x600 only happens when the client actually sends `ga_config`.

Loop shape:
- Outer restart loop `while restart_count <= max_restarts` (ga_current.py:1234), so up to 11 attempts.
- Population seeding: random within gene domain (ga_current.py:1243-1251), or, on a restart that has a stored good chromosome, that chromosome plus mutants of it at double the initial rate (ga_current.py:1236-1241).
- Executor: `SerialExecutor` closure when `max_workers == 1` (ga_current.py:1264-1273), otherwise `ProcessPoolExecutor` with `_init_worker` seeding worker globals (ga_current.py:1275-1277). The serial `map` deliberately ignores the passed function (ga_current.py:1267-1271).
- Generation body, `for generation in range(NUM_GENERATIONS)` (ga_current.py:1282): evaluate all (1284), `np.argmax` best (1288), update global best with deepcopy (1291-1296).
- **Termination: fixed generation count only.** There is no fitness-convergence or target-satisfied early exit. The only early exit is the restart `break` at ga_current.py:1344, and the outer `break` at ga_current.py:1369-1370 once a run finishes without restarting.
- **Restart trigger (a mid-run quality gate, hardcoded thresholds)** at ga_current.py:1321-1344: at `generation + 1 == NUM_GENERATIONS // 2` (halfway_point, ga_current.py:1260), restart if `components > 2` or `adj_ratio != 1.0` or `corridor_ratio < 0.10` or `entry_points != 0` or `overlap > 5`. A "good" chromosome is stashed before halfway when `components == 1 and adj_ratio == 1.0 and corridor_ratio >= 0.10` (ga_current.py:1311-1318).
- **Elitism: exactly one individual**, `new_population.append(population[best_idx])` (ga_current.py:1352-1353), inserted by reference, not a copy. The remaining `POPULATION_SIZE - 1` children are selection + crossover + mutation (ga_current.py:1355-1361).
- Adaptive mutation: after `STAGNATION_THRESHOLD` generations with no improvement, rate += 0.04 up to 0.65 (ga_current.py:1347-1349).

Operators:
- `selection` (ga_current.py:1174-1178): tournament of `TOURNAMENT_SIZE` sampled without replacement, best fitness wins deterministically.
- `crossover` (ga_current.py:1180-1188): uniform, per-gene coin flip. Safe because index i means the same room in both parents.
- `mutation` (ga_current.py:1190-1208): per gene, with probability `mutation_rate`, add `randint(-6, 6)` to each of dr and dc (ga_current.py:1200-1201), then clamp into the room's valid range (1203-1204).

### 5. What a finished run outputs, and who consumes it

`run_ga` returns `best_chromosome_overall` (ga_current.py:1408): a `List[Tuple[int, int]]`, or `None` if the loop never improved on `-inf` (possible only if the population was empty). It is the raw chromosome. No floorplan, no matrix, no JSON. Before returning it prints stats (ga_current.py:1380-1402) and calls `visualize_layout` to write a PNG under `mine/ga_outputs/` (ga_current.py:1405-1406, filename at 1619-1622) and to call `plt.show()` (ga_current.py:1632). The API path neutralizes that by monkey-patching `visualize_layout` (handlers.py:2921-2926).

Consumption site: **`handle_ga_optimization`** in `C:\Users\nitant\Documents\GPLAN_Revamp\GPLAN\GPLAN\handlers.py:2845`, which receives it at handlers.py:2935 and decodes it itself (`apply_chromosome` at handlers.py:2953, `corridor_creator` at handlers.py:2973, per-room wall translation at handlers.py:2988-2998, output dict at handlers.py:3028-3038). Detail is dim-14's.

Also `negNew.py:1673` (`ga_runner`) calls `run_ga` and **discards the return value entirely**: it is invoked purely for the printed stats and the PNG side effect.

### 6. Functions with no callers (dead code) in scope

Verified by grep over the whole repository for each name; the only hits outside the definition are inside `graphify-out\graph.json.bak-20260725`, which is a generated graph artifact, not a caller.

- **`build_room_adjacency_graph`** (ga_current.py:999-1023): **dead.** No caller anywhere. This is the room-to-room adjacency computation that a "satisfy the requested adjacencies" fitness term would need. It is the clearest evidence that adjacency satisfaction is unimplemented in this engine.
- **`ga_solution_to_floorplan_json`** (ga_current.py:662-787): **dead.** No caller. It is the well-formed chromosome-to-floorplan-JSON converter (wall derivation at ga_current.py:723-750, labels at 767-775). The handler reimplements a different, ad-hoc version of the same job (handlers.py:2983-3038). Duplicated logic, and the live copy is the worse one.
- **`floorplan_to_json`** (ga_current.py:567-620): reachable only from `ga_solution_to_floorplan_json` (ga_current.py:787), therefore **transitively dead.**
- **`Wall` / `Label` / `Room` / `Floorplan` dataclasses** (ga_current.py:19, 28, 35, 42) and **`parse_floorplan_json`** (ga_current.py:51): used only by the dead converter above and by the `__main__` demo block (ga_current.py:1649). Not on any production path.
- **`get_lib_extension`** (ga_current.py:72-79): live, used at ga_current.py:81. Note a near-identical duplicate exists at `GPLAN\build_dlls.py:26`.
- **Dead constants:** `CORRIDOR_ID = 0` (ga_current.py:144) and `MINIMUM_RATIO = 0.05` (ga_current.py:147) are never referenced anywhere in the file.
- **Dead weight:** `WEIGHTS["boundary_corridor"] = 0` (ga_current.py:121) zeroes out the term at ga_current.py:1113, so the four boundary scans at ga_current.py:1103-1106 are pure cost.
- **Unused parameters:** `mutation`'s `initial_rooms` (ga_current.py:1190) is never read in the body (1192-1208). Same for `initial_rooms` in `count_rooms_adjacent_to_corridor` (ga_current.py:797, body 799-816) and `count_isolated_rooms` (ga_current.py:818, body 820-841).
- **Commented-out corpses:** two dead copies of `corridor_creator` starting at ga_current.py:170 and 282, and two of `count_boundary_accessible_corridors` at ga_current.py:843 and 936, plus commented alternate rendering blocks at ga_current.py:1453-1459, 1554-1572, 1606-1612, 1624-1629.
- **Script-only tail:** grep shows a second driver block inside `__main__` at ga_current.py:1729-1822 (`parse_json_floorplan`, `run_ga`, `apply_chromosome`, `corridor_creator`, `visualize_layout`). Not read; it is `__main__`-guarded and unreachable from the API.

## Algorithm Walkthrough

1. `run_ga` overwrites the module global `CORRIDOR_WIDTH` from its argument (ga_current.py:1221-1222). This is process-global state, not per-call state.
2. `parse_floor_plan(initial_grid)` (ga_current.py:1224, definition 429-458) re-derives `RoomGA` objects **from the grid**, not from the `rooms` dict the caller already has. Room ids are the positive cell values.
3. `sorted_room_ids` and `compute_valid_displacements` fix the gene order and gene domain (ga_current.py:1226-1227).
4. Population seeded (ga_current.py:1236-1251).
5. Each generation: fitness for all, track best, maybe stash a restart seed, maybe restart at halfway, maybe bump mutation rate, then elite + (selection, uniform crossover, clamped creep mutation) x (POPULATION_SIZE - 1).
6. Fitness per individual: translate all rooms (`apply_chromosome`), paint them into a fresh int matrix counting overlaps, carve corridors via the C `corridor_creator` (ga_current.py:1086), then measure corridor ratio, boundary leaks, isolated rooms, corridor components, and room-corridor adjacency, and sum the weighted penalties.
7. On completion, print, visualize, return the chromosome.

## The Actual Constraints Or Formulas

Hard constraints (structural, cannot be violated):
- `min_r + dr >= 0`, `max_r + dr <= region_height - 1`, and column equivalents. Enforced by the gene domain at ga_current.py:641-646 and re-enforced by the mutation clamp at ga_current.py:1203-1204.
- Fixed rooms have displacement identically `(0, 0)` (ga_current.py:631-633).

Soft constraints (fitness penalties), in descending strength per unit:
```
overlap cell                     -50000   (1112)
missing room-corridor adjacency  -50000 * (fraction of rooms not touching a corridor)   (1125)
extra corridor component         -25000 each beyond the first   (1121)
movable room on a fixed room     -10000 per cell   (1128)
corridor ratio deviation         -10000 * |ratio - target|, target 0.2 or dynamic   (1099-1101, 1117)
isolated room                     -5000 each   (1118)
boundary entry point              -3300 each   (1114)
corridor cell                        -1 each (via area)   (1111)
boundary corridor cell                0  (disabled weight)   (1113)
constant offset                  +75000   (1130)
```
Restart gate thresholds (hardcoded, ga_current.py:1329-1330): `components <= 2`, `adj_ratio == 1.0`, `corridor_ratio >= 0.10`, `entry_points == 0`, `overlap <= 5`.

## Invariants And Preconditions

- `len(chromosome) == len(initial_rooms)`, and gene `i` belongs to `sorted(initial_rooms.keys())[i]`. Nothing checks this inside the GA; only the dead converter validates it (ga_current.py:675-676).
- Every room's translated bounding box stays inside the region rectangle (see hard constraints). Therefore `layout_matrix[r, c]` indexing in fitness cannot go out of range for genes produced by this module's own operators.
- `TOURNAMENT_SIZE <= POPULATION_SIZE`, otherwise `random.sample` raises. The handler enforces it (handlers.py:2885); a direct importer does not, and the module defaults are 8 out of 10, which is close to deterministic best-of-population selection.
- `region_matrix` must be a numpy char array whose entries are single characters, because `calculate_corridor_connectivity` maps every cell through `ord()` (ga_current.py:792).
- `run_ga` mutates process globals (`CORRIDOR_WIDTH`), and the handler mutates `POPULATION_SIZE`, `NUM_GENERATIONS`, `INITIAL_MUTATION_RATE`, `TOURNAMENT_SIZE`, `visualize_layout`. Concurrent GA requests in one process would interfere.

## Failure Modes

1. **The fitness cache is global and never keyed by the floorplan.** `_fitness_cache` at ga_current.py:130, lookup at ga_current.py:1166-1168 keyed on `tuple(chromosome)` alone. Two different requests in the same process whose chromosomes coincide (very likely: short int tuples, and every all-zeros chromosome collides) will read the previous plan's fitness. It is also never cleared, so it grows for the process lifetime. This is a correctness bug on a long-lived API worker, not just a memory leak.
2. **Restarts throw away the previous attempt's best.** `best_chromosome_overall` is reset to `None` at the top of every restart iteration (ga_current.py:1254-1255). A restart triggered at the halfway point discards a solution that may have been better than what the restarted run finds.
3. **`run_ga` can return `None`** (ga_current.py:1408 with the guard at 1380). The handler treats falsy as failure (handlers.py:2946-2948). Note an all-`(0,0)`-displacement chromosome is truthy since it is a non-empty list, so that is not a false negative; an empty room set would be.
4. **Room identity mismatch between the two parses.** The handler builds `rooms` with `parse_json_floorplan` (handlers.py:2914) but `run_ga` rebuilds its own room set with `parse_floor_plan(initial_grid)` (ga_current.py:1224). If two payload rooms overlap in the grid, the later id overwrites the earlier, so `parse_floor_plan` can yield fewer rooms and different `coords` than the handler's `rooms`. The chromosome length then does not match the handler's `sorted_room_ids`, producing wrong room-to-gene mapping or an `IndexError` at handlers.py:2988.
5. **Painting order affects the layout matrix under overlap.** In the fitness loop, both movable and fixed rooms write into `layout_matrix` and the last writer wins (ga_current.py:1069, 1082, 1060). Overlap *counting* is order-independent because `fixed_room_cells` is precomputed (ga_current.py:1044-1048), but the corridor carving that follows sees an arbitrary winner.
6. **`plt.show()` blocks.** `visualize_layout` calls `plt.show()` at ga_current.py:1632. Anyone importing `run_ga` without the handler's monkey-patch (for example `negNew.ga_runner`) hangs on a GUI window at the end of the run. It also `os.makedirs('mine/ga_outputs')` relative to the process CWD (ga_current.py:1619).
7. **`ctypes.CDLL` at import time** (ga_current.py:83, 87, 91). A missing `.dll`/`.so` makes `import ga_current` itself fail, taking down the handler import at handlers.py:2868. dim-14 owns the detail.
8. **Runtime scales as population x generations x (grid area + C calls).** With the documented 200 x 600 config that is 120000 evaluations per attempt, up to 11 attempts. The doc's "2-3 minutes" (`ga_optimization_api.md:13`) is an assertion, not something the code bounds; there is no wall-clock timeout anywhere in `run_ga`.

## Coupling (what breaks if you change this)

- **Gene ordering.** `sorted(room_ids)` is assumed in three independent places: ga_current.py:1226 (run_ga), ga_current.py:654 (apply_chromosome), handlers.py:2980-2981 (the handler's own index map). Change the ordering in one and rooms silently swap positions in the output.
- **Gene shape `(dr, dc)`.** The handler unpacks it directly (handlers.py:2988) and serializes it as `ga_solution` (handlers.py:3021-3026). Adding a third gene component (say a size scalar) breaks both, plus the dead converter at ga_current.py:663-676.
- **`CORRIDOR_FINAL = 99`** (ga_current.py:145) is passed as the corridor sentinel into all three C libraries (ga_current.py:423, 795, 932) and is assumed by `count_rooms_adjacent_to_corridor`, `count_isolated_rooms`, `build_room_adjacency_graph` and the renderer. Changing it requires touching the C side too.
- **Module globals as configuration.** `handle_ga_optimization` sets `ga_current.POPULATION_SIZE` etc. by attribute assignment (handlers.py:2874-2885). Converting those constants into `run_ga` parameters silently disables all payload configuration unless the handler is updated in the same change.
- **`WEIGHTS`.** Changing any weight changes the fitness scale, which changes whether the hardcoded halfway restart thresholds (ga_current.py:1329-1330) still discriminate, since those read stats rather than fitness but the search that produces them is weight-driven.
- **`region_matrix` semantics.** `parse_json_floorplan` currently marks the entire plot usable (ga_current.py:560). Re-introducing `'#'` cells activates the currently-unreachable `'#'` overlap branch (ga_current.py:1073-1074) and changes `total_usable_space` (ga_current.py:1093-1096), hence the dynamic corridor target.
- **`room_dimensions`.** Positional argument 4 of `run_ga` (ga_current.py:1213) and `negNew.ga_runner` passes it positionally (negNew.py:1673). Reordering the signature breaks that caller silently since the types are all optional dicts.

## Dead Or Duplicated Code

Listed in full under answer 6. Summary of what to delete or wire up:
- Delete: `build_room_adjacency_graph` (999), `ga_solution_to_floorplan_json` (662) plus `floorplan_to_json` (567) plus the four dataclasses (19-49) plus `parse_floorplan_json` (51), the `boundary_corridor` weight and its scan (121, 1103-1106, 1113), `CORRIDOR_ID` (144), `MINIMUM_RATIO` (147), the unused `initial_rooms` parameters (797, 818, 1190), and the four commented-out function corpses (170, 282, 843, 936).
- Duplicated: `get_lib_extension` exists twice (ga_current.py:72 and build_dlls.py:26). Chromosome-to-JSON export exists twice (ga_current.py:662, dead vs handlers.py:2983-3038, live). The whole file exists twice on disk (`GPLAN\` and `gplan_backend\GPLAN\`).

## Open Questions

1. Is the `_fitness_cache` collision across requests actually observed in production, or does the deployment fork a fresh process per request? Needs the WSGI/worker config, not in this file.
2. Was a dimension-constraint term ever intended? `WEIGHTS` has no slot for it and `build_room_adjacency_graph` is stranded, which suggests the fitness function was cut down at some point. Git history would settle it (this checkout is not a git repo at the top level).
3. `ga_optimization_api.md:80-82` promises defaults of 200/600 while the code says 10/30 (ga_current.py:95-96). Which is the intended contract? If clients rely on the doc and omit `ga_config`, they get a 10x30 search, which for any non-trivial plan will fail the halfway gate repeatedly and burn all 11 restarts.
4. `ga_optimization_api.md:110` documents `solution_chromosome` as a digit string; the code emits `ga_solution` as a list of int pairs. Is there an API-layer transform between `handlers.py:3036` and the HTTP response that renames and reformats it, or is the doc simply stale? Answering needs api.py, which is dim-14 territory.
5. `count_isolated_rooms` flags a room as isolated when it touches no other *room*. In a corridor-based plan that is the normal, desired state, yet it costs 5000 per room while the corridor-adjacency term rewards exactly that configuration. Are these two terms fighting each other by design?
