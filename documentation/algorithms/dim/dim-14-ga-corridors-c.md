# dim-14: GA Corridor C Library Layer and the GA Handler

Scope: the native bridge (C sources, build, ctypes contract) and `handle_ga_optimization`.
Not covered here: GA encoding, selection, crossover, mutation, fitness weights rationale (see dim-13).

All paths absolute. All line cites read directly from source.

---

## Purpose

Three C translation units provide the corridor primitives that the GA's fitness function calls
once per individual evaluation:

1. `corridor_creator` (in `corridor_creator.c`) mutates a room-id grid in place, converting
   qualifying empty gaps between two different rooms into corridor cells.
2. `count_corridor_components` (in `bfs.c`) runs 4-connected BFS over corridor cells to count how
   many disconnected corridor components exist. The GA wants exactly one.
3. `count_boundary_accessible_corridors` (in `boundary_accessible_corridors.c`) counts "entry
   points": places where the corridor network leaks to the outside of the plot or to an unusable
   region. The GA penalises these.

A fourth pair, `corridor.c` / `corridor.h`, is **empty (0 bytes)** yet still compiled and shipped
as `corridor.so`. Nothing loads it. Details in Dead Or Duplicated Code.

---

## Where It Sits In The Pipeline

```
HTTP request
  -> GPLAN/GPLAN/api.py:1649  get_ga_optimized_floorplan(request_data)
  -> GPLAN/GPLAN/api.py:1701  handle_ga_optimization(ui, floorplan_data, corridor_width, ga_config)
  -> GPLAN/GPLAN/handlers.py:2845  handle_ga_optimization
  -> GPLAN/GPLAN/handlers.py:2914  parse_json_floorplan(floorplan_data)  [defined ga_current.py:460]
       (walls -> grid + region_matrix)
  -> ga_current.py:1210  run_ga
       -> per individual: ga_current.py:1026 calculate_fitness
            -> ga_current.py:1086  corridor_creator(...)                [C: corridor_creator.so]
            -> ga_current.py:1109  count_boundary_accessible_corridors  [C: boundary_accessible_corridors.so]
            -> ga_current.py:1120  calculate_corridor_connectivity      [C: bfs.so]
  -> handlers.py:2973  corridor_creator(...) once more on the winning chromosome
  -> handlers.py:3028  output_data dict (includes layout_matrix)
  -> api.py:1740  response['data']
```

The C layer is on the hot path. It runs `POPULATION_SIZE * NUM_GENERATIONS` times per restart
(defaults `ga_current.py:95` = 10, `ga_current.py:96` = 30), plus once more at the end.

---

## Entry Points (file:line)

### C exported symbols

`C:\Users\nitant\Documents\GPLAN_Revamp\GPLAN\Space_Optimization\bfs.c`

| Symbol | Signature | Line |
|---|---|---|
| `create_queue` | `Queue* create_queue(int capacity)` | bfs.c:3 |
| `destroy_queue` | `void destroy_queue(Queue* q)` | bfs.c:13 |
| `is_empty` | `int is_empty(Queue* q)` | bfs.c:18 |
| `enqueue` | `void enqueue(Queue* q, Point p)` | bfs.c:22 |
| `dequeue` | `Point dequeue(Queue* q)` | bfs.c:31 |
| `count_corridor_components` | `int count_corridor_components(int* layout, int* region, int height, int width, int corridor_final)` | bfs.c:38 |
| `has_unusable_neighbor` | `int has_unusable_neighbor(int* matrix, int rows, int cols, int r, int c, int unusable)` | bfs.c:79 |
| `has_room_neighbor` | `int has_room_neighbor(int* matrix, int rows, int cols, int r, int c, int corridor_final)` | bfs.c:94 |
| `corridor_creator` (6-arg variant) | `void corridor_creator(int* matrix, int height, int width, int corridor_width, int corridor_final, int unusable)` | bfs.c:110 |

Header declarations: `bfs.h:15-23`. Note `bfs.h:23` declares the **6-argument** `corridor_creator`.

`C:\Users\nitant\Documents\GPLAN_Revamp\GPLAN\Space_Optimization\corridor_creator.c`

| Symbol | Signature | Line |
|---|---|---|
| `has_unusable_neighbor` | `int has_unusable_neighbor(int* matrix, int rows, int cols, int r, int c, int unusable)` | corridor_creator.c:3 |
| `has_room_neighbor` | `int has_room_neighbor(int* matrix, int rows, int cols, int r, int c, int corridor_final)` | corridor_creator.c:18 |
| `corridor_creator` (7-arg variant) | `void corridor_creator(int* matrix, int rows, int cols, int corridor_width, int corridor_final, int unusable, int empty)` | corridor_creator.c:34 |

Header declaration: `corridor_creator.h:7` (7 arguments). This is the variant Python actually calls.

`C:\Users\nitant\Documents\GPLAN_Revamp\GPLAN\Space_Optimization\boundary_accessible_corridors.c`

| Symbol | Signature | Line |
|---|---|---|
| `create_queue` | `Queue* create_queue(int capacity)` | boundary_accessible_corridors.c:14 |
| `destroy_queue` | `void destroy_queue(Queue* q)` | boundary_accessible_corridors.c:24 |
| `is_empty` | `int is_empty(Queue* q)` | boundary_accessible_corridors.c:29 |
| `enqueue` | `void enqueue(Queue* q, Point p)` | boundary_accessible_corridors.c:33 |
| `dequeue` | `Point dequeue(Queue* q)` | boundary_accessible_corridors.c:42 |
| `count_boundary_accessible_corridors` | `int count_boundary_accessible_corridors(int* layout, int* region, int height, int width, int corridor_final)` | boundary_accessible_corridors.c:49 |

Header declaration: `boundary_accessible_corridors.h:6`.

`C:\Users\nitant\Documents\GPLAN_Revamp\GPLAN\Space_Optimization\corridor.c` and `corridor.h`:
**0 bytes each. No symbols. Empty stubs.**

### Python-side entry points

- `ga_current.py:83` `lib = ctypes.CDLL(os.path.join(parent_dir, f'bfs{lib_ext}'))`
- `ga_current.py:87` `corridor_lib = ctypes.CDLL(... f'corridor_creator{lib_ext}')`
- `ga_current.py:91` `boundary_lib = ctypes.CDLL(... f'boundary_accessible_corridors{lib_ext}')`
- `ga_current.py:408` `def corridor_creator(matrix, corridor_width=2) -> np.ndarray` (wrapper)
- `ga_current.py:789` `def calculate_corridor_connectivity(layout_matrix, region_matrix) -> int` (wrapper)
- `ga_current.py:920` `def count_boundary_accessible_corridors(layout_matrix, region_matrix) -> int` (wrapper)
- `handlers.py:2845` `def handle_ga_optimization(ui, floorplan_data, corridor_width=3, ga_config=None)`
- `api.py:1649` `get_ga_optimized_floorplan(request_data)` (static method, HTTP-facing)

`parent_dir` is set at `ga_current.py:69` to the directory **above** `Space_Optimization`, i.e.
`GPLAN/`. The `.so` files in `GPLAN/Space_Optimization/` are copies, not the ones loaded at runtime
(`build_dlls.py:112` writes to `TARGET_DIR`, `build_dlls.py:135` copies back into the source dir).

---

## Data Structures

### The layout matrix (the thing BFS traverses)

BFS does **not** traverse a room adjacency graph. It traverses a **rasterised occupancy grid**:
one integer per plot cell, row-major, flattened to 1-D `int*` of length `height * width`.

Cell value encoding (`ga_current.py:1037-1038`, `ga_current.py:1060`, `handlers.py:2957-2970`):

| Value | Meaning | Set at |
|---|---|---|
| `0` | empty / unassigned usable cell | `ga_current.py:1037`, `handlers.py:2957` |
| `-1` | unusable (region `'#'`) | `ga_current.py:1038`, `ga_current.py:1748`, `handlers.py:2963`, `ga_current.py:1450` |
| `> 0`, `!= 99` | room id | `ga_current.py:1060/1076/1082`, `handlers.py:2970` |
| `99` = `CORRIDOR_FINAL` | corridor cell | written only by the C `corridor_creator`, constant at `ga_current.py:145` |

**What defines a corridor cell**: a cell whose layout value equals `corridor_final` (99). It is not
a geometric object, it is a grid stamp. Nothing else in the system writes 99.

### The region matrix

`region_matrix` is a numpy array of single characters, `'#'` for unusable, created at
`ga_current.py:472` as `np.full((plot_height, plot_width), '#', dtype=str)`. The C layer receives
it as an `int*` of character ordinals, built by list comprehension at `ga_current.py:792` and
`ga_current.py:927`: `np.array([ord(c) for row in region_matrix for c in row], dtype=np.int32)`.
C compares against `(int)'#'` at `bfs.c:62`, `boundary_accessible_corridors.c:58/77/85/125/145`.

### Queue

Fixed-capacity circular buffer of `Point {int r, c}`, `bfs.h:6-13` and
`boundary_accessible_corridors.c:5-12` (a byte-identical duplicate). Capacity is always
`height * width` (`bfs.c:44`, `boundary_accessible_corridors.c:106`). `enqueue` silently drops on
full (`bfs.c:23-25`, `boundary_accessible_corridors.c:34-36`), no error signal.

---

## Algorithm Walkthrough

### 1. `corridor_creator` (corridor_creator.c:34): the one actually called

Three phases, all in-place on `matrix`.

**Phase A, horizontal scan (corridor_creator.c:36-79).** For each row `r`, walk `c` left to right.
Read the geometry carefully: this scan measures a **column count** between a room on the left and a
room on the right, and stamps cells `gap_start..gap_end` inside a single row
(`corridor_creator.c:69-71`). Repeated over consecutive rows it produces a strip that **runs
vertically**, whose thickness is its column count.
- `corridor_creator.c:40` if cell `> 0`, record `left_room` and consume the whole run of that id
  (`corridor_creator.c:44-46`).
- `corridor_creator.c:49-53` the gap is the maximal run of `== empty` cells starting where the room
  run ended. `gap_len = gap_end - gap_start` (line 54).
- `corridor_creator.c:57` accept only if the cell terminating the gap is `> 0` **and different from
  `left_room`**. So a corridor is only carved **between two distinct rooms**, never room-to-void and
  never room-to-itself.
- `corridor_creator.c:59` accept only if `gap_len >= 2`. **There is no upper bound in the horizontal
  branch.** `corridor_width` is not consulted here at all, so the vertically-running strips this scan
  produces can be arbitrarily thick.
- `corridor_creator.c:61-66` reject the whole gap if **any** cell in it has a 4-neighbour equal to
  `unusable` (-1). This is the "do not hug the unusable region" guard.
- `corridor_creator.c:69-71` on success, stamp every gap cell with `corridor_final`.

**Phase B, vertical scan (corridor_creator.c:82-125).** Structurally identical, transposed, with one
difference: `corridor_creator.c:105` requires `gap_len >= 2 && gap_len <= corridor_width`. This is
the **only** use of `corridor_width` in the entire C layer. Here the loop walks rows `r` down a fixed
column `c` (`corridor_creator.c:82-84`), so `gap_len` is a **row count** between a room above
(`top_room`, `corridor_creator.c:87`) and a different room below, and the stamped cells are
`gap_start..gap_end` at that one column (`corridor_creator.c:115-117`). Repeated over consecutive
columns it produces a band that **runs horizontally**, whose row-thickness is what `corridor_width`
caps.

Note phase B runs after phase A on the already-mutated matrix. Corridor cells written in phase A are
`99 > 0`, so phase B treats them as rooms. A column gap between a room and a corridor stamped in
phase A is therefore eligible for filling. This is how the network becomes connected, and it is
implicit, not stated anywhere in the code.

**Phase C, conditional boundary clearing (corridor_creator.c:129-154).** For each of the four plot
edges, erase a corridor cell back to `empty` if `has_room_neighbor` is false, i.e. if none of its 4
neighbours is a positive non-corridor value (`corridor_creator.c:26`). A boundary corridor that still
serves a room survives.

**Corridor width logic, stated plainly**: `corridor_width` caps the thickness of
**horizontally-running** corridors only, the ones produced by the vertical scan
(`corridor_creator.c:105`). **Vertically-running** corridors, produced by the horizontal scan
(`corridor_creator.c:59`), have no upper bound and can be arbitrarily thick. The naming trap is that
the capped branch is the one labelled "vertical scan" in the source comment
(`corridor_creator.c:81`), because it scans vertically but lays corridor horizontally.
The GA passes `CORRIDOR_WIDTH` (default 3,
`ga_current.py:107`; overridden per run at `ga_current.py:1222`). The Python wrapper's own default of
`2` (`ga_current.py:408`) is never used, every call site passes `CORRIDOR_WIDTH` explicitly
(`ga_current.py:1086`, `ga_current.py:1488`, `ga_current.py:1758`, `handlers.py:2973`).

### 2. `count_corridor_components` (bfs.c:38)

Standard 4-connected connected-components count over corridor cells.

- `bfs.c:39` allocate `visited` as `height * width` bytes; returns 0 on allocation failure.
- `bfs.c:42-43` the 4-neighbour offsets.
- `bfs.c:44` one queue of capacity `height * width`, reused across all components.
- `bfs.c:45-48` scan row-major; a cell seeds a new component when
  `layout[idx] == corridor_final && !visited[idx]`. **The seed test does not check `region`**, while
  the expansion test at `bfs.c:62` does (`region[nidx] != (int)'#'`). In practice unreachable: the
  layout marks `'#'` cells as -1 (`ga_current.py:1038`) and `corridor_creator` only overwrites cells
  equal to `empty`, so a `'#'` cell can never hold 99.
- `bfs.c:55-69` BFS flood, marking visited at enqueue time (correct, no double-enqueue).
- Returns `num_components`. The GA rewards 1 and penalises each extra component
  (`ga_current.py:1121`).

Floorplan meaning: "is the corridor system one walkable network, or several disconnected puddles."

### 3. `count_boundary_accessible_corridors` (boundary_accessible_corridors.c:49)

This counts *leak points*, not corridors. Two contributions summed into one `entry_points` counter.

**Contribution 1, direct boundary corridors (lines 55-65).** Every corridor cell that sits on row 0,
row `height-1`, column 0, or column `width-1`, and whose region is not `'#'`, counts 1
(`boundary_accessible_corridors.c:58-62`).

**Contribution 2, corridors reachable from outside through empty space (lines 67-157).**
- Lines 74-102 collect the seed set: cells that are usable (`region != '#'`) and empty
  (`layout == 0`) and are either on the plot boundary (line 78) or 4-adjacent to a `'#'` cell
  (lines 81-89). The seed array grows by doubling (lines 92-95).
- Lines 109-115 mark all seeds visited and enqueue them (multi-source BFS).
- Lines 118-132 flood through empty usable cells only. Rooms and corridors block the flood.
- Lines 135-157 for every cell reached by the flood, if any 4-neighbour is a usable corridor cell,
  increment `entry_points` (line 153).

**What makes a corridor boundary-accessible**, plainly: it either touches the plot edge itself, or it
touches an empty cell that is connected, through empty cells only, to the plot edge or to the
unusable region. That is, someone could walk in from outside without passing through a room.

The GA penalises this with weight 3300 (`ga_current.py:122`). Each such contact is counted
separately, so the value is a contact-count, not a corridor-count. The two contributions are also
different units (corridor cells vs adjacent empty cells) added into one number.

### 4. `corridor_creator` (bfs.c:110): compiled but never called

Identical logic to `corridor_creator.c:34` except:
- Six parameters, `empty` is hardcoded to 0 via a local (`bfs.c:113`).
- `has_room_neighbor` iterates the offsets in a different order (`bfs.c:95-96` vs
  `corridor_creator.c:19-20`), a cosmetic difference only.
- Same scan-branch `corridor_width` asymmetry (`bfs.c:138`, the horizontal scan, has no upper bound;
  `bfs.c:183`, the vertical scan, has `gap_len <= corridor_width`), so the same geometric consequence
  holds: horizontally-running corridors are capped, vertically-running ones are not.

Python never calls `lib.corridor_creator`, only `corridor_lib.corridor_creator`
(`ga_current.py:421`). This is dead code in `bfs.so`.

---

## The Actual Constraints Or Formulas

Corridor eligibility, horizontal scan (corridor_creator.c:57-66), `gap_len` is a column count and the
resulting corridor runs vertically:
```
matrix[r][gap_start-1] is room A  (A > 0)
matrix[r][gap_end]     is room B  (B > 0, B != A)
gap cells all == empty (0)
gap_len >= 2                                   <-- no upper bound
no gap cell has a 4-neighbour == unusable (-1)
```

Corridor eligibility, vertical scan (corridor_creator.c:103-112), `gap_len` is a row count and the
resulting corridor runs horizontally: same as above, plus
```
gap_len <= corridor_width
```

Boundary clearing (corridor_creator.c:130): a boundary corridor cell is erased iff
`has_room_neighbor == 0`, where a "room neighbour" is any 4-neighbour with
`val > 0 && val != corridor_final` (corridor_creator.c:26).

Constants baked into the Python call at `ga_current.py:423`: `corridor_final = 99`,
`unusable = -1`, `empty = 0`. These must stay in sync with `CORRIDOR_FINAL` at `ga_current.py:145`
and with the `-1` writes at `ga_current.py:1038`, `ga_current.py:1748`, `ga_current.py:1450`,
`handlers.py:2963`. They are hardcoded literals at the call site, not derived from the constant.

Fitness consumption of the C results (dim-13 owns the weights, listed here only for coupling):
- `ga_current.py:1121` `corridor_conn_penalty = (num_components - 1) * 25000` when `> 1`
- `ga_current.py:1114` `boundary_accessible_corridor_penalty = entry_points * 3300`
- `ga_current.py:1089-1091` `corridor_ratio = corridor_cells / (room_cells + corridor_cells + 1e-6)`
- `ga_current.py:1099-1101` target ratio is 0.2 (`ga_current.py:146`) unless remaining empty space is
  under 25% of usable space, in which case the target collapses to the remaining-empty fraction.

---

## Invariants And Preconditions

1. The buffer handed to every C function must be **C-contiguous 32-bit ints**. Satisfied by
   `np.array(matrix, dtype=np.int32).flatten()` at `ga_current.py:418`, and by the fact that
   `corridor_creator` returns an int32 array (`ga_current.py:426`) which is what lines 791 and 926
   subsequently flatten.
2. `layout` and `region` must have the same `height * width` as the scalars passed. The C code does
   zero bounds validation on the scalars; it trusts them.
3. `region_matrix` must contain exactly one character per cell, otherwise `ord(c)` at
   `ga_current.py:792` / `ga_current.py:927` raises `TypeError`. Guaranteed by
   `ga_current.py:472` (`dtype=str` -> `<U1`).
4. `layout` cells that are `'#'` in the region must be `-1`, not `0`. Otherwise `corridor_creator`
   would treat unusable cells as fillable gap. Enforced at `ga_current.py:1038` (fitness),
   `ga_current.py:1450` (visualize), `ga_current.py:1748` (main), `handlers.py:2960-2963` (handler).
   All four paths do it. This is the load-bearing invariant of the whole layer.
5. `corridor_final` must not collide with any room id. Room ids come from `int(room_data['name'])`
   at `ga_current.py:489`. **A floorplan containing a room literally named "99" would corrupt the
   corridor stamp.** Nothing checks this.
6. `enqueue` never overflows because `visited` guarantees each cell is enqueued at most once and
   capacity is `height * width`.
7. The Python-side numpy arrays passed via `.ctypes.data_as` must stay referenced for the duration of
   the call. They do: `new_matrix` (`ga_current.py:418`), `layout_flat`/`region_flat`
   (`ga_current.py:791-794`, `ga_current.py:926-931`) are all named locals.

---

## Failure Modes

**Unchecked allocations.** `create_queue` does not check either `malloc`
(`bfs.c:4-5`, `boundary_accessible_corridors.c:15-16`). `boundary_accessible_corridors.c:72` does not
check its `malloc`, and `boundary_accessible_corridors.c:94` does not check the `realloc`, which on
failure both leaks the old block and immediately NULL-derefs at line 96. On a large plot with heavy
memory pressure this is a segfault inside the worker process, which surfaces to the API as a killed
process, not as a Python exception. `bfs.c:40` is the only allocation that is checked, and it
degrades silently by returning 0 components, which the GA reads as "perfectly connected"
(`ga_current.py:1121` skips the penalty when `num_components <= 1`). That is a silent
fitness corruption on OOM.

**Room id 99 collision.** See invariant 5. Silent corruption, no diagnostic.

**Vertically-running corridors are unbounded.** `corridor_creator.c:59`, the horizontal scan, applies
no upper bound, so a corridor running vertically can be arbitrarily thick. Setting `corridor_width=1`
suppresses only the horizontally-running corridors carved by the vertical scan
(`corridor_creator.c:105`). Any request that tunes `corridor_width` (`api.py:1692`) gets asymmetric
behaviour along the two axes.

**`entry_points` double-counting.** Lines 55-65 and 135-157 both increment the same counter. A
corridor cell on the boundary that is also adjacent to a flooded empty cell contributes twice. The
penalty magnitude is therefore not a stable function of geometry.

**Symbol duplication across loaded libraries.** `bfs.so` and `boundary_accessible_corridors.so` both
define `create_queue`, `destroy_queue`, `is_empty`, `enqueue`, `dequeue`
(`bfs.c:3/13/18/22/31` vs `boundary_accessible_corridors.c:14/24/29/33/42`). `bfs.so` and
`corridor_creator.so` both define `has_unusable_neighbor`, `has_room_neighbor`, and `corridor_creator`
(`bfs.c:79/94/110` vs `corridor_creator.c:3/18/34`), with **different arities** for
`corridor_creator` (6 vs 7). This is safe only because `ctypes.CDLL` at `ga_current.py:83/87/91`
uses the default `RTLD_LOCAL` mode. Anyone who adds `mode=ctypes.RTLD_GLOBAL`, or who links these
objects into one shared library, gets whichever `corridor_creator` the loader resolves first. If the
6-argument `bfs.c` version wins while Python passes 7 arguments per `ga_current.py:88`, the extra
argument is silently discarded and `empty` becomes the uninitialised `EMPTY = 0` local. That would be
benign by luck, but the reverse (bfs.h's 6-arg prototype being called with the 7-arg definition)
leaves `empty` as garbage from the register/stack, which would make the gap test
`matrix[...] == empty` match arbitrary cells. This is a latent hazard, not a live bug today.

**Empty `corridor.so`.** See Dead Or Duplicated Code. It fails open: `gcc -shared` on a 0-byte `.c`
succeeds, so the Docker build passes and produces a shared object with no symbols.

**Broad exception swallowing in the handler.** `handlers.py:3049-3054` catches every exception,
stringifies it into `ui.set_message`, and returns `False`. `api.py:1707-1715` then turns that into a
`status: 'error'` response. A segfault in the C layer is not catchable there and kills the process
instead.

---

## The ctypes Contract, Declaration By Declaration

### `bfs.so` -> `count_corridor_components`

- Load: `ga_current.py:83`
- `argtypes` `ga_current.py:84`: `[POINTER(c_int), POINTER(c_int), c_int, c_int, c_int]`
- `restype` `ga_current.py:85`: `c_int`
- C signature: `bfs.c:38` `int count_corridor_components(int*, int*, int, int, int)`
- Buffers: `ga_current.py:791` `layout_flat = layout_matrix.flatten()`,
  `ga_current.py:792` `region_flat = np.array([ord(c) ...], dtype=np.int32)`,
  pointers taken at `ga_current.py:793-794`.
- Call: `ga_current.py:795`.
- **Verdict: signature matches. No mismatch.**

### `corridor_creator.so` -> `corridor_creator`

- Load: `ga_current.py:87`
- `argtypes` `ga_current.py:88`: `[POINTER(c_int), c_int, c_int, c_int, c_int, c_int, c_int]` (7)
- `restype` `ga_current.py:89`: `None`
- C signature: `corridor_creator.c:34`, 7 parameters, `void`
- Buffer: `ga_current.py:418` `new_matrix = np.array(matrix, dtype=np.int32).flatten()`;
  pointer at `ga_current.py:422`; result reshaped at `ga_current.py:426`. In-place mutation, the
  returned array is a view over the same buffer C wrote.
- Call: `ga_current.py:421-424` with literals `99, -1, 0`.
- **Verdict: signature matches. No mismatch.**

### `boundary_accessible_corridors.so` -> `count_boundary_accessible_corridors`

- Load: `ga_current.py:91`
- `argtypes` `ga_current.py:92`: `[POINTER(c_int), POINTER(c_int), c_int, c_int, c_int]`
- `restype` `ga_current.py:93`: `c_int`
- C signature: `boundary_accessible_corridors.c:49`
- Buffers: `ga_current.py:926-927`, pointers taken inline at `ga_current.py:930-931`.
- **Verdict: signature matches. No mismatch.**

### The one real dtype hazard

`ga_current.py:791` and `ga_current.py:926` call `.flatten()` on `layout_matrix` **without asserting
`dtype`**, then reinterpret the buffer as `c_int` (32-bit). `layout_matrix` is created as
`np.zeros(..., dtype=int)` at `ga_current.py:1037`, which is **int64 on Linux**. The only reason this
is not a live memory bug is that both call sites run *after* `ga_current.py:1086`, which replaces
`layout_matrix` with the int32 array returned by the `corridor_creator` wrapper
(`ga_current.py:418`, `ga_current.py:426`). Ordering is doing the work that a dtype assertion should
be doing.

State plainly: **if anyone reorders `calculate_fitness` so that `calculate_corridor_connectivity`
(`ga_current.py:1120`) or `count_boundary_accessible_corridors` (`ga_current.py:1109`) is called on
the pre-`corridor_creator` matrix, C reads an int64 buffer as int32.** It will not crash, it will
read half the grid at wrong values and return garbage counts, silently degrading fitness. Same
exposure for any new caller of those two wrappers. The fix is one line in each wrapper:
`layout_flat = np.ascontiguousarray(layout_matrix, dtype=np.int32).ravel()`.

`region_flat` is safe at both sites because it is explicitly built with `dtype=np.int32`
(`ga_current.py:792`, `ga_current.py:927`).

---

## Where In The GA Lifecycle Corridors Are Computed

**Per individual, inside fitness evaluation. Not once after evolution.**

- `ga_current.py:1086` inside `calculate_fitness` (`ga_current.py:1026`):
  `layout_matrix = corridor_creator(layout_matrix.tolist(), CORRIDOR_WIDTH)`
- `ga_current.py:1109` `count_boundary_accessible_corridors(layout_matrix, region_matrix)`
- `ga_current.py:1120` `calculate_corridor_connectivity(layout_matrix, region_matrix)`

So every chromosome evaluation performs: one full grid `tolist()`, one `np.array` copy, one C
corridor carve, one C connected-components BFS, one C multi-source flood BFS, plus two Python-level
`ord()` list comprehensions over the whole grid (`ga_current.py:792`, `ga_current.py:927`) that
rebuild the identical immutable `region_flat` every single time. That region conversion is pure
waste and is the most obvious optimisation in the layer: it depends only on `region_matrix`, which is
constant for an entire run.

Corridors are then recomputed **a third and fourth time** on the winning chromosome:
- `ga_current.py:1488` inside `visualize_layout` (suppressed by the handler, see below)
- `handlers.py:2973` in the handler, to build the `layout_matrix` that goes into the response

The handler's recomputation at `handlers.py:2973` uses a **different room-placement routine** from
the fitness one: `handlers.py:2966-2970` writes room ids with no overlap accounting and skips `'#'`
cells, whereas `ga_current.py:1054-1082` has fixed-room precedence, overlap counting, and writes room
ids even onto blocked cells (`ga_current.py:1069`). The two matrices can differ for a chromosome with
overlaps. **The corridors the GA scored are not guaranteed to be the corridors the client receives.**

---

## `handle_ga_optimization`: Payload To Response

`C:\Users\nitant\Documents\GPLAN_Revamp\GPLAN\GPLAN\handlers.py:2845`

1. `handlers.py:2863-2865` prepend `../Space_Optimization` to `sys.path`.
2. `handlers.py:2868-2869` import `parse_json_floorplan, run_ga, apply_chromosome, corridor_creator`
   and the module itself. The import at line 2869 is what triggers the three `CDLL` loads at
   `ga_current.py:83/87/91`. A missing or ABI-wrong `.so` throws here and is swallowed by the
   `except` at `handlers.py:3049`.
3. `handlers.py:2871-2881` mutate module globals from `ga_config`: `POPULATION_SIZE`,
   `NUM_GENERATIONS`, `INITIAL_MUTATION_RATE`, and a local `max_workers`. These are global writes on
   an imported module, so they persist across requests in a long-lived server process. There is no
   reset. A request that sets `population_size: 200` leaves it at 200 for every subsequent request
   that omits `ga_config`.
4. `handlers.py:2885` clamp `TOURNAMENT_SIZE = min(8, max(2, POPULATION_SIZE // 4))`.
5. `handlers.py:2897-2909` merge every wall referenced by any room into a single
   `floorplan_data['walls']` list, deduplicated by `wall['id']`.
6. `handlers.py:2914` `parse_json_floorplan(floorplan_data)` returns
   `(rooms, initial_grid, region_matrix, room_names)`.
7. `handlers.py:2921-2926` monkey-patch `ga_current.visualize_layout` to a no-op so matplotlib never
   opens. Restored in `finally` at `handlers.py:2942-2944`. This is what makes `ga_current.py:1488`
   dead in the server path.
8. `handlers.py:2935-2941` `run_ga(initial_grid, region_matrix, corridor_width=..., room_names=...,
   max_workers=...)`. Returns the best chromosome, a list of `(dr, dc)` integer displacements.
9. `handlers.py:2946-2948` falsy result -> `ui.set_message(...)`, `return False`.
   Note this treats an empty chromosome the same as failure.
10. `handlers.py:2953` `apply_chromosome(rooms, best_solution)` -> `displaced_coords`.
11. `handlers.py:2956-2970` build a fresh list-of-lists layout, `-1` for `'#'`, room ids elsewhere.
12. `handlers.py:2973` `corridor_creator(layout_matrix, corridor_width)` (the C call again).
13. `handlers.py:2976-2977` numpy -> plain list for JSON.
14. `handlers.py:2983-3017` per room: apply `(dr, dc)` to every wall's `x1,x2,y1,y2`
    (`handlers.py:2994-2997`), compute `optimized_bounds` from the displaced cell coords
    (`handlers.py:3001-3016`).
15. `handlers.py:3021-3026` coerce chromosome tuples to plain ints.
16. `handlers.py:3028-3038` assemble `output_data` with `plot_width`, `plot_height`, `rooms`,
    `walls`, `labels`, `windows`, `doors`, `ga_solution`, `layout_matrix`. Note
    `output_data['walls']` at `handlers.py:3032` is the **original untransformed** master wall list,
    while `optimized_rooms[i]['walls']` carries the displaced copies. Two inconsistent wall sets ship
    in the same response.
17. `handlers.py:3041-3042` `ui._set_output_data([output_data])`, success message, `return True`.
18. `api.py:1740-1757` wraps `outputData[0]` into
    `{request_id, status, engine: 'GA_FloorPlan', data: {floor, ga_optimization, rooms, walls,
    labels, windows, doors, layout_matrix}, error: {}}`. `ga_optimization.status` is hardcoded to
    `'converged'` at `api.py:1746` regardless of whether the GA actually converged or exhausted its
    restart budget.

### Where room dimension parameters enter the GA run

**They do not.**

- `api.py:1682-1688` builds `floorplan_data` from only `plot_width`, `plot_height`, `rooms`, `walls`,
  `labels`, `windows`, `doors`. No width/height/min/max per room is read.
- `parse_json_floorplan` derives each room's extent purely from its wall endpoint coordinates:
  `ga_current.py:494-506` collects `x1,x2,y1,y2` and takes min/max. Shared-wall adjustment at
  `ga_current.py:509-530`. There is no dimension parameter anywhere in that function.
- `run_ga` does declare a `room_dimensions` parameter at `ga_current.py:1213`, but
  `handlers.py:2935-2941` **never passes it**, so it is always `None`. Inside `run_ga` it is used at
  exactly one place, `ga_current.py:1405-1406`, forwarding to `visualize_layout`, where
  `ga_current.py:1547-1548` uses it only for drawing text labels. It never reaches
  `calculate_fitness` (`ga_current.py:1026`), which takes no dimension argument at all.
- The chromosome is `(dr, dc)` per room (`ga_current.py:1250`) and `apply_chromosome`
  (`ga_current.py:651-658`) only translates coordinates. **The GA cannot resize a room. Room shape is
  frozen at whatever the input walls describe.**

Plainly: `run_ga`'s `room_dimensions` parameter is dead in the API path, and no minimum or maximum
room dimension constraint exists anywhere in this GA. `corridor_width` (`api.py:1692`) is the only
dimensional knob that reaches the engine, and per the walkthrough it only bounds the thickness of
horizontally-running corridors (`corridor_creator.c:105`).

---

## Coupling: What Breaks If You Change This

- Change `CORRIDOR_FINAL` at `ga_current.py:145` and you must also change the literal `99` at
  `ga_current.py:423`. They are not linked.
- Change the unusable marker and you must update `ga_current.py:423` (`-1`), `ga_current.py:1038`,
  `ga_current.py:1450`, `ga_current.py:1748`, `handlers.py:2963`, and `bfs.c:62` /
  `boundary_accessible_corridors.c:58/77/85/125/145` (which compare region against `'#'`, a
  *different* encoding from the layout's `-1`).
- Change `corridor_creator`'s arity and you break `ga_current.py:88`, `corridor_creator.h:7`, and
  leave `bfs.c:110` / `bfs.h:23` further out of sync.
- Change `layout_matrix`'s dtype away from what `corridor_creator` returns and you silently corrupt
  `ga_current.py:791` and `ga_current.py:926`. See the dtype hazard above.
- Reorder anything in `calculate_fitness` so a C wrapper runs before `ga_current.py:1086`: same
  silent corruption.
- Add `mode=ctypes.RTLD_GLOBAL` to any of `ga_current.py:83/87/91`: symbol collisions across the
  three libraries become live.
- `build_dlls.py:112` writes artifacts to `TARGET_DIR` = `GPLAN/`, which is exactly where
  `ga_current.py:69` looks. Change either and the loads at `ga_current.py:83/87/91` fail at import
  time, surfacing as a generic error string from `handlers.py:3050`.
- `handlers.py:2874-2879` writes module globals with no reset, so GA config leaks between requests in
  a persistent server.
- Two copies of the entire tree exist (`GPLAN/...` and `gplan_backend/GPLAN/...`). Both have the same
  three `CDLL` sites (background grep: `gplan_backend/GPLAN/Space_Optimization/ga_current.py:83,87,91`)
  and both Dockerfiles compile the same four sources. Any fix must be applied to the submodule and
  re-vendored.

---

## Dead Or Duplicated Code

### `corridor.c` / `corridor.h` are empty files, and a binary is being shipped whose source has been deleted

Directory listing of `GPLAN\Space_Optimization` (verified):

```
corridor.c                             0 bytes
corridor.h                             0 bytes
corridor.so                       69,152 bytes
bfs.c                              8,272    bfs.so                       70,080
corridor_creator.c                 5,920    corridor_creator.so          69,472
boundary_accessible_corridors.c    5,423    boundary_accessible_corridors.so  70,024
```

`GPLAN\corridor.so` also exists at 69,152 bytes (the build target directory).

`corridor.c` **is still in the build list**: `build_dlls.py:18-23` lists `"corridor.c"` third, and
both Dockerfiles hardcode a fallback compile of it:
- `GPLAN/Dockerfile:22` `gcc -shared -fPIC -o ../corridor.so corridor.c -O2 -Wall`
- `gplan_backend/Dockerfile:32` (same line)
- `gplan_backend/GPLAN/Dockerfile:22` (same line)

Nothing loads it. A repo-wide grep for `corridor.so` / `corridor.dll` returns **only those three
Dockerfile lines and zero Python references**. The only three `CDLL` calls in the entire repo are
`ga_current.py:83` (bfs), `:87` (corridor_creator), `:91` (boundary_accessible_corridors), plus their
duplicates under `gplan_backend/`.

Stated plainly: **yes, a binary is being shipped whose source has been deleted.** `corridor.so` was
compiled from a version of `corridor.c` that no longer exists in the repository. The build still
"succeeds" because `gcc -shared` on a zero-byte translation unit exits 0 and emits a symbol-free
shared object. So the checked-in 69 KB `corridor.so` is an unreproducible artifact from a lost
source, and the Docker rebuild at `Dockerfile:16` (`rm -f *.so ...`) replaces it with an empty stub.
Since nothing dlopens it either way, the observable behaviour is unchanged, but the source is
unrecoverable from this repo and the build list is lying about what it produces.

### Other dead or duplicated code

- **`corridor_creator` in `bfs.c:110-233`**: complete second implementation, 6-arg, never called.
  Declared in `bfs.h:23`. Along with its helpers `bfs.c:79` and `bfs.c:94`, this duplicates
  `corridor_creator.c:3`, `:18`, `:34` almost line for line.
- **Queue implementation duplicated verbatim**: `bfs.c:3-36` vs
  `boundary_accessible_corridors.c:14-47`, plus the `Point`/`Queue` structs `bfs.h:6-13` vs
  `boundary_accessible_corridors.c:5-12`.
- **Unused locals**: `start_c` at `corridor_creator.c:42` and `start_r` at `corridor_creator.c:88`
  are assigned and never read. Both Dockerfiles compile with `-Wall`, so these emit warnings on every
  build.
- **Commented-out Python reimplementations**: `ga_current.py:170-281` and `ga_current.py:282-405`
  (two dead `corridor_creator` versions), `ga_current.py:843-918` and `ga_current.py:936-...` (two
  dead `count_boundary_accessible_corridors` versions), `ga_current.py:1453-1459` (dead room
  placement), `ga_current.py:1568-1569`. Roughly 300 commented lines shadowing live functions with
  the same names.
- **`bfs.c:48` seed test missing the region guard**: unreachable given the `-1` invariant, but it is
  an inconsistency with `bfs.c:62`.
- **`ga_current.py:1488`** (`corridor_creator` inside `visualize_layout`) is unreachable in the API
  path because `handlers.py:2926` replaces `visualize_layout` with a no-op.
- **`ga_current.py:1758`** is inside the `__main__` demo block reading a JSON file
  (`ga_current.py:1725`), not reachable from the API.
- **`run_ga`'s `room_dimensions` parameter** (`ga_current.py:1213`): never passed by
  `handlers.py:2935-2941`, so always `None` in production.
- **`WEIGHTS["boundary_corridor"] = 0`** (`ga_current.py:121`): the boundary corridor count computed
  at `ga_current.py:1103-1106` is multiplied by zero at `ga_current.py:1113`. That whole computation
  is dead arithmetic.

### Compilation summary, stated plainly

| Source | Compiled by build_dlls.py:18-23 | Loaded at runtime | Status |
|---|---|---|---|
| `bfs.c` | yes | yes, `ga_current.py:83` | live (but its `corridor_creator` half is dead) |
| `corridor_creator.c` | yes | yes, `ga_current.py:87` | live |
| `corridor.c` | yes | **no** | **empty stub, 0 bytes** |
| `boundary_accessible_corridors.c` | yes | yes, `ga_current.py:91` | live |

Orphaned artifacts: `GPLAN\corridor.so` and `GPLAN\Space_Optimization\corridor.so` (69,152 bytes
each). No loader references them.

---

## Open Questions

1. Is the scan-branch `corridor_width` asymmetry (`corridor_creator.c:59` vs `:105`) intentional, or
   is the missing `&& gap_len <= corridor_width` on the horizontal-scan branch simply a dropped
   clause? As written it leaves vertically-running corridors uncapped while capping
   horizontally-running ones. Both `bfs.c` and `corridor_creator.c` have the same asymmetry, which
   suggests it was copied, not independently authored, so it is probably an inherited bug.
2. What did the deleted `corridor.c` contain, and does any deployed image still carry the old 69 KB
   binary rather than the empty rebuild? Only a Git history search of `nitantupasani/gplan_engine`
   can answer this.
3. Is the double-counting in `count_boundary_accessible_corridors` (boundary corridor cells at
   `boundary_accessible_corridors.c:61` plus adjacent flooded empties at `:153`) intended as a
   weighted sum, or was one of the two loops meant to replace the other?
4. Was the handler meant to reuse the fitness function's layout construction rather than its own
   divergent one at `handlers.py:2956-2970`? The returned `layout_matrix` is not provably the one the
   GA scored.
5. Why does `output_data['walls']` (`handlers.py:3032`) ship untransformed walls alongside the
   transformed per-room walls (`handlers.py:2994-2997`)? Which does the frontend consume?
6. Should room dimension constraints (min/max width and height) enter this GA at all, or is the
   dimensioning responsibility entirely delegated to the separate `ptpg_floorplanner` path referenced
   at `api.py:1774-1783`? The presence of a `room_dimensions` parameter on `run_ga`
   (`ga_current.py:1213`) suggests someone once intended them to.
