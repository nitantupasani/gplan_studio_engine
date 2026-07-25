# dim-08: `GPLAN/source/polygonal/limits.py`

Target file: `C:\Users\nitant\Documents\GPLAN_Revamp\GPLAN\GPLAN\source\polygonal\limits.py` (446 lines, 31 KB). Read in full.

---

## Purpose

**It does not compute per-room min/max widths and heights, and it does not produce bounds for any LP.** The name is misleading relative to the rest of the `dimensioning/` chain.

What it actually computes: given (a) one selected room, (b) one of that room's four walls, and (c) a requested shift direction and shift distance, it returns **how far that single wall can be translated before it collides with a vertex or an edge of the selected room or of its graph-adjacent neighbour rooms**. It is a wall-drag reachability check for the interactive "Modify Room" feature in the Tkinter desktop GUI.

The class then compares the user's requested shift against that reachable distance and sets a boolean gate `self.proceed` (`limits.py:12`, `limits.py:28`) plus a human-readable `self.errorMessage` (`limits.py:13`). The caller uses `proceed` to decide whether to recompute room coordinates.

Concretely the returned pair is:
- `opti in {0,1}` (left/right wall, vertical): `(max(answer_left), max(answer_right))` (`limits.py:427`)
- `opti in {2,3}` (top/bottom wall, horizontal): `(max(answer_bottom), max(answer_top))` (`limits.py:431`)

Units are the same units as the floorplan coordinates (`room_x`/`room_y`/`room_width`/`room_height` from `InputGraph`).

---

## Where It Sits In The Pipeline

It sits in the **polygonal / irregular interactive-editing branch**, downstream of a floorplan that has already been generated and dimensioned. It is **not** part of the dimensioning solve at all.

```
gui "Modify Room" button            GPLAN/pythongui/gui.py:1487
  -> gui_class.change_limits()      GPLAN/pythongui/gui.py:2093   (opens the Toplevel dialog)
  -> "Apply" button                 GPLAN/pythongui/gui.py:2175
  -> gui_class.change_limits_ender()GPLAN/pythongui/gui.py:2178
       sets self.room_limits        GPLAN/pythongui/gui.py:2187
       sets self.side  (= opti)     GPLAN/pythongui/gui.py:2188
       sets *_shift_value           GPLAN/pythongui/gui.py:2192-2195
       sets *_dropdown_value        GPLAN/pythongui/gui.py:2197-2200
       sets command = "limits"      GPLAN/pythongui/gui.py:2208-2209
  -> main.run() dispatch            main.py:57
  -> handle_limits(...)             main.py:58  ->  GPLAN/handlers.py:1509
       reads ./saved_files/input_to_limits.json   GPLAN/handlers.py:1513-1519
       builds adj_matrix from edgeset             GPLAN/handlers.py:1541-1547
       builds poly.Room list with 4 coords each   GPLAN/handlers.py:1564-1586
       picks s_dir / dist from gclass.side        GPLAN/handlers.py:1588-1601
  -> lim.LimitsAlgorithm(...)       GPLAN/handlers.py:1603
       -> LimitsAlgorithm.__init__  GPLAN/source/polygonal/limits.py:11
       -> self.wall_input()         GPLAN/source/polygonal/limits.py:20 -> :62
       -> self.run()                GPLAN/source/polygonal/limits.py:27 -> :105
  -> if limits_instance.proceed == 1                       GPLAN/handlers.py:1605
       -> nc.NewCoordinateAlgorithm(..., limits_instance.coords_input1,
                                     limits_instance.coords_input2, ...)
                                                           GPLAN/handlers.py:1615
                                     (GPLAN/source/polygonal/newcoord.py:9)
       -> new InputGraph + final_traversal rebuild          GPLAN/handlers.py:1618-1633
       -> drawFunction                                      GPLAN/handlers.py:1681
     else: print("Limit Exceeded")                          GPLAN/handlers.py:1682-1683
```

The `input_to_limits.json` file that `handle_limits` reads is written by the single-rectangular-floorplan handler at `GPLAN/handlers.py:1114-1117`.

**Reachability caveat:** this path runs only through `main.py` (the Tkinter desktop app). `handle_limits` has exactly one caller, `main.py:58`. `GPLAN/api.py` (the deployed FastAPI service) never calls `handle_limits`; the only `limits` token in `api.py` is the unrelated local variable `limits = caps if enforce else None` at `GPLAN/api.py:729`, used by `_span_limit` for area caps. So **for the web/production deployment this whole module is unreachable**.

---

## Entry Points (file:line)

### Top-level definitions

| Symbol | file:line | Kind |
|---|---|---|
| `LimitsAlgorithm` | `limits.py:9` | class (the only top-level definition in the file) |
| `if __name__ == "__main__":` block | `limits.py:444-446` | prints an empty line; the only statement is `print()` at `limits.py:445`. The `LimitsAlgorithm().find_limits(Null,Null)` line is commented out (`limits.py:446`). Effectively a no-op stub. |

There are **zero top-level functions**. Everything is a method of `LimitsAlgorithm`.

### Methods and their callers

| Method | file:line | Callers (grep over `C:\Users\nitant\Documents\GPLAN_Revamp\GPLAN`) |
|---|---|---|
| `__init__(self, opti, room_input, rooms, adj_mat, shiftDirection, shiftValue)` | `limits.py:11` | `GPLAN/handlers.py:1603` (`lim.LimitsAlgorithm(gclass.side, gclass.room_limits, rooms, adj_matrix, s_dir, dist)`). One caller. |
| `slope(self, x, y)` | `limits.py:51` | Internal only: `limits.py:77`, `:153`, `:154`, `:221`, `:222`, `:282`, `:297`, `:298`, `:345`, `:346`. No external callers. |
| `distance(self, x, y)` | `limits.py:58` | Internal only: `limits.py:85`, `:92`, `:99`. No external callers. |
| `wall_input(self)` | `limits.py:62` | Internal only: `limits.py:20`. No external callers (the other hit, `limits.py:441`, is inside a commented-out block). |
| `IsInRegion(self, x, ci1, ci2)` | `limits.py:76` | Internal only: `limits.py:148`, `:151`, `:219`. No external callers. |
| `run(self)` | `limits.py:105` | Internal only: `limits.py:27`. No external callers. |

### Attributes read from outside the class

| Attribute | Set at | Read at |
|---|---|---|
| `self.proceed` | `limits.py:12`, `:28`, `:33`, `:38`, `:43`, `:48` | `GPLAN/handlers.py:1605` |
| `self.coords_input1` | `limits.py:18`, `:64`, `:67`, `:70`, `:73` | `GPLAN/handlers.py:1615` |
| `self.coords_input2` | `limits.py:19`, `:65`, `:68`, `:71`, `:74`, `:128`, `:134` | `GPLAN/handlers.py:1615` |
| `self.errorMessage` | `limits.py:13`, `:31`, `:36`, `:41`, `:46` | Read only inside the class, by the four `print(self.errorMessage)` calls at `limits.py:32`, `:37`, `:42`, `:47`, each immediately after its own write. **No caller outside the class reads it.** The only would-be external consumer is commented out at `GPLAN/handlers.py:1684` (`# show_warning(newCoordsInstance.error_message)`), and even that names a different object's attribute. The string reaches stdout, never the UI. |

### Dead code inside the file

- `find_limits(self, adj_mat, rooms)`: **entirely commented out**, `limits.py:433-442`. Two other files still reference it, both in comments: `GPLAN/source/polygonal/poly.py:6` (`# from GPLAN.source.polygonal.limits import find_limits`), `GPLAN/source/polygonal/poly.py:54`, and `GPLAN/pythongui/drawing.py:147`. It does not exist as callable code.
- `import networkx as nx` (`limits.py:1`), `import matplotlib.pyplot as plt` (`limits.py:2`), `import numpy as np` (`limits.py:3`, duplicated at `limits.py:5`), `import tkinter as tk` (`limits.py:4`), `import re` (`limits.py:6`): **none of `nx`, `plt`, `np`, `tk`, `re` is used anywhere in the file**. Only `math` (`limits.py:7`) is used, at `limits.py:403` and `:410`. Five unused imports plus one exact duplicate.

---

## Data Structures

### Inputs to `__init__` (`limits.py:11`)

| Param | Type | Source | Notes |
|---|---|---|---|
| `opti` | `int` in `{0,1,2,3}` | `gclass.side`, an `IntVar` from the radio group (`gui.py:131`, `gui.py:2188`) | Wall selector: `0` = left wall, `1` = right wall, `2` = top wall, `3` = bottom wall. Mapping established by `wall_input` (`limits.py:62-74`) against the vertex order built in `handlers.py:1581`. |
| `room_input` | `int` | `gclass.room_limits`, an `IntVar` (`gui.py:106`, `gui.py:2187`) | Index into `rooms`. Used raw, no 1-based -> 0-based conversion (the conversion is commented out at `limits.py:107-110`). |
| `rooms` | `list[poly.Room]` | built at `handlers.py:1561`, `1577`, `1586` | `poly.Room` (`GPLAN/source/polygonal/poly.py:10`) holds `self.coords = []` (`poly.py:12`), accessed via `.coord()` (`poly.py:17-18`). |
| `adj_mat` | `numpy.ndarray[int]`, shape `(nodecnt, nodecnt)`, symmetric 0/1 | `handlers.py:1541-1547` | The comment at `limits.py:104` demands: "remember to make the self.adj_mat in the same order of self.rooms, very very important". This ordering contract is unchecked. |
| `shiftDirection` | `str`, one of `"Left"`, `"Right"`, `"Up"`, `"Down"` | Combobox values (`gui.py:2130`, `gui.py:2156`, `gui.py:2166`); routed by side at `handlers.py:1590-1601` | For `opti` 0/1 the dropdown offers only `["Left","Right"]`; for `opti` 2/3 only `["Up","Down"]`. |
| `shiftValue` | `float` | `tk.DoubleVar` (`gui.py:108-115`), routed at `handlers.py:1590-1601` | |

### Polygon representation

**Vertex list, not edge list and not a grid.** Each room is an ordered list of 2-tuples `(x, y)` in `Room.coords`. Edges are implicit between consecutive entries and between the last and the first (wrap handled explicitly at `limits.py:127-128`, `:219`, `:221`, `:345`).

For the only live construction site (`handlers.py:1564-1586`), each room is an axis-aligned rectangle with exactly **4** vertices, and the winding is set at `handlers.py:1581`:

```
temp2 = [temp[0]] + temp[1:][::-1]
```

which yields `coords = [ (x, y), (x, y+h), (x+w, y+h), (x+w, y) ]`, i.e. bottom-left, top-left, top-right, bottom-right. Under that order `wall_input` (`limits.py:62-74`) resolves to: `opti=0` -> left edge (vertical), `opti=1` -> right edge (vertical), `opti=2` -> top edge (horizontal), `opti=3` -> bottom edge (horizontal). Coordinates are `numpy.float64` scalars, because `handlers.py:1524` wraps the JSON lists in `np.array(...)` and `InputGraph.room_x` is created with `np.zeros(...)` (`GPLAN/source/inputgraph.py:128`, `:131`).

### Internal structures in `run()` (`limits.py:105`)

| Name | file:line | Type | Meaning |
|---|---|---|---|
| `n` | `limits.py:114` | `int` | `len(self.rooms[self.room_input].coords)`. Shadowed and corrupted later at `limits.py:294`. |
| `nbd_rooms` | `limits.py:116-124` | `list[int]` | The selected room index plus every room `k` with `adj_mat[room_input][k] == 1`. |
| `pts` | `limits.py:141` | `dict[(float,float) -> float]` | key = a candidate collision point, value = a distance. **Because it is a dict, two candidate points with identical coordinates collide and the later one silently overwrites the earlier.** |
| `dts` | `limits.py:142` | `list` | Declared and **never used anywhere**. Dead. |
| `answer_left`, `answer_right`, `answer_top`, `answer_bottom` | `limits.py:396-399` | `list[float]` | Distance candidates on each side of the selected wall. |

### Output

- Return of `run()`: a 2-tuple of floats (`limits.py:427` or `limits.py:431`), or **`None`** if `opti` is not in `{0,1,2,3}` (no `else` branch after `limits.py:428`).
- Public state after construction: `self.proceed` (`int`, 0 or 1), `self.errorMessage` (`str`, printed in-class at `limits.py:32`, `:37`, `:42`, `:47` and read by no external caller), `self.coords_input1` / `self.coords_input2` (the two endpoint tuples of the chosen wall).

---

## Algorithm Walkthrough

1. **`__init__` (`limits.py:11-48`)** stores inputs, calls `wall_input()` (`limits.py:20`), prints the adjacency matrix and every room's coords (`limits.py:21-26`), then calls `run()` and unpacks into `(x_max, y_max)` (`limits.py:27`). Sets `proceed = 1` (`limits.py:28`), then downgrades it to `0` if the requested shift exceeds the computed limit (`limits.py:29-48`).

2. **`wall_input` (`limits.py:62-74`)** maps `opti` onto a vertex pair:
   - `opti==0` -> `coords[0], coords[1]` (`limits.py:64-65`)
   - `opti==1` -> `coords[2], coords[3]` (`limits.py:67-68`)
   - `opti==2` -> `coords[1], coords[2]` (`limits.py:70-71`)
   - `opti==3` -> `coords[3], coords[0]` (`limits.py:73-74`)

3. **`run()` neighbour collection (`limits.py:114-124`)**: `nbd_rooms = [room_input] + [k for k where adj_mat[room_input][k]==1]`.

4. **Redundant re-derivation of `coords_input2` (`limits.py:126-138`)**: scans the selected room's vertex list for the vertex equal to `coords_input1` and takes the successor (wrapping at index `n-1` to index `0`). For the 4-vertex rectangles built by `handlers.py:1581` this always reproduces what `wall_input` already set. It would diverge only if the polygon contained duplicated vertices.

5. **Case 1, "one vertex in the band, its predecessor out" (`limits.py:146-278`)**: for every room in `nbd_rooms` and every vertex `j`, if `IsInRegion(coords[j])` is true but `IsInRegion(coords[j-1])` is false (or `coords[-1]` for `j==0`, `limits.py:219`), the polygon edge `(j-1, j)` crosses the band boundary. The code computes the crossing point and stores it in `pts` with a distance. Four slope sub-cases are enumerated (`limits.py:162`, `:163`, `:175`, `:185`, `:194`, `:195`, `:207`) and duplicated verbatim for the `j==0` wrap branch (`limits.py:223-278`).

6. **Case 2, "vertex in the band" (`limits.py:280-288`)**: this block is nested inside `if check == True:` (`limits.py:149`), so it runs for every in-band vertex regardless of case 1. It records the vertex itself as a candidate point with its perpendicular distance to the wall line. It is one of three sources of real, geometry-dependent values in the axis-aligned live path; case 1 and case 3 also contribute (see the identity proof below).

7. **Case 3, "both out" (`limits.py:292-391`)**: a second full pass over rooms and vertices. It is guarded by `limits.py:295`, a condition that is a tautology (see below), so it runs unconditionally for every vertex. For a vertical wall it is not noise: `limits.py:339`, `:343`, `:387`, `:391` write `|vertex_x - wall_x|`, a real distance, and those values compete in the same `max()` as case 2's.

8. **Side classification (`limits.py:401-414`)**: values in `pts` are bucketed by the sign of the key's offset from `coords_input1`:
   - `opti in {0,1}`: `key[0] - coords_input1[0] < 0` -> `answer_left` (`limits.py:404-405`); `> 0` -> `answer_right` (`limits.py:406-407`). Exactly `0` falls in neither bucket.
   - `opti in {2,3}`: `key[1] - coords_input1[1] < 0` -> `answer_bottom` (`limits.py:411-412`); `> 0` -> `answer_top` (`limits.py:413-414`).
   Every value is gated by `isinstance(pts[i], float) and not math.isinf(...) and not math.isnan(...)` (`limits.py:403`, `:410`).

9. **Empty-bucket defaults (`limits.py:415-422`)**: any empty list gets a single `0` appended.

10. **Return (`limits.py:424-431`)**: prints `min(...)` of each bucket but returns `max(...)` of each bucket. The printed number and the returned number are different quantities.

---

## The Actual Constraints Or Formulas

All formulas transcribed literally. `c1 = coords_input1`, `c2 = coords_input2`, `P = rooms[i].coords`.

### Slope (`limits.py:51-56`)
```
limits.py:53   m = (y[1] - x[1]) / (y[0] - x[0])            if y[0] - x[0] != 0
limits.py:55   m = "NOT DEFINED"                            otherwise
```
Guarded by `limits.py:52`. The vertical case is signalled by a sentinel **string**, not by `inf` or `None`.

### Euclidean distance (`limits.py:58-60`)
```
limits.py:59   d = ((y[1] - x[1])**2 + (y[0] - x[0])**2) ** 0.5
```

### Band membership test, `IsInRegion` (`limits.py:76-102`)

Oblique wall (`m1` defined and non-zero), `limits.py:80-85`:
```
limits.py:80   m2 = -(1 / m1)                                       # perpendicular slope
limits.py:83   d1 = |m2*x[0] - x[1] + (c1[1] - m2*c1[0])| / (m2**2 + 1)**0.5
limits.py:84   d2 = |m2*x[0] - x[1] + (c2[1] - m2*c2[0])| / (m2**2 + 1)**0.5
limits.py:85   return (d1 <= distance(c1,c2)) and (d2 <= distance(c1,c2))
```
`d1` and `d2` are the point-to-line distances from `x` to the two lines of slope `m2` through `c1` and `c2` respectively (the two perpendicular "caps" of the wall).

Horizontal wall (`m1 == 0`), `limits.py:90-92`:
```
limits.py:90   d1 = |x[0] - c1[0]|
limits.py:91   d2 = |x[0] - c2[0]|
limits.py:92   return (d1 <= distance(c1,c2)) and (d2 <= distance(c1,c2))
```

Vertical wall (`m1 == "NOT DEFINED"`), `limits.py:97-99`:
```
limits.py:97   d1 = |x[1] - c1[1]|
limits.py:98   d2 = |x[1] - c2[1]|
limits.py:99   return (d1 <= distance(c1,c2)) and (d2 <= distance(c1,c2))
```

**The test bounds only one of the two directions, and it is the wall's own direction.** For a point strictly between the caps, `d1 + d2 == distance(c1,c2)`, and the written test `d1 <= L and d2 <= L` accepts exactly the strip whose projection onto the wall direction lies between the two caps. Points at exactly a cap give `d1 = 0, d2 = L` and pass; a point one full wall length beyond `c2` gives `d1 = 2L` and fails. What the test never looks at is the **perpendicular offset from the wall**:

- Vertical wall (`limits.py:96-99`): only `x[1]`, the y-coordinate, is tested. That is the wall's own direction. `x[0]`, the normal direction, is never tested.
- Horizontal wall (`limits.py:89-92`): only `x[0]` is tested, again the wall direction. `x[1]` is never tested.
- Oblique wall (`limits.py:80-85`): `d1` and `d2` are distances to the two lines of perpendicular slope `m2` through `c1` and `c2`, which cap the projection along the wall and say nothing about the perpendicular offset.

The band is therefore a slab bounded along the wall direction and **unbounded in the wall-normal direction**. That is why a vertex of a distant room is accepted as a collision candidate whenever its along-wall projection falls between the caps, however far from the wall it actually sits.

### Case 1 crossing points

Oblique wall, oblique edge (`limits.py:163-173`), after `m_ = -1/m_` at `limits.py:164` (so `m_` becomes the wall's perpendicular slope):
```
limits.py:166   X = (c1[1] - P[j-1][1] - (m_*c1[0] - m*P[j-1][0])) / (m - m_)
limits.py:167   Y = m_*(X - c1[0]) + c1[1]
limits.py:169   pts[(X,Y)] = |m_*X - Y + (c1[1] - m_*c1[0])| / (m_**2 + 1)**0.5
```
and the `c2` variant:
```
limits.py:171   X = (c2[1] - P[j-1][1] - (m_*c2[0] - m*P[j-1][0])) / (m - m_)
limits.py:172   Y = m_*(X - c2[0]) + c2[1]
limits.py:173   pts[(X,Y)] = |m_*X - Y + (c1[1] - m_*c1[0])| / (m_**2 + 1)**0.5
```

**Identity: line 169 is provably always `0.0`.** Substituting `limits.py:167` into `limits.py:169`:
`m_*X - (m_*X - m_*c1[0] + c1[1]) + c1[1] - m_*c1[0] = 0` exactly. The same cancellation happens wherever the point construction and the line equation use the **same** endpoint. Sixteen `pts` entries are identically zero on that argument: the `c1`/`c1` pairs at `limits.py:169`, `:201`, `:230`, `:262`, `:304`, `:313`, `:331`, `:352`, `:361`, `:379`, and the `c2`/`c2` pairs at `limits.py:308`, `:317`, `:335`, `:356`, `:365`, `:383`. For the latter group, `limits.py:307` sets `Y = m_*(X - c2[0]) + c2[1]` and `limits.py:308` measures that point against the line through `c2`, so `m_*X - m_*X + m_*c2[0] - c2[1] + c2[1] - m_*c2[0] = 0`; `:316-317`, `:334-335`, `:355-356`, `:364-365` and `:382-383` have the identical structure. All sixteen are the distance from a point to the very line it was just constructed to lie on, identically zero up to floating-point noise. They contribute only `0` to the answer buckets, which is irrelevant since `max()` is taken.

**Identity: line 173 is the wall length.** `(X,Y)` from `limits.py:172` lies on the `c2` perpendicular line, but `limits.py:173` measures it against the `c1` perpendicular line; the distance between those two parallel lines is `distance(c1,c2)`. Only four sites mix a `c2`-derived point with the `c1` line equation this way: `limits.py:173`, `:205`, `:234`, `:266`, all in case 1. These four are constants, not geometry-dependent limits.

Horizontal wall (`m_ == 0`, note `m_` is **not** inverted in this branch), `limits.py:176-183`:
```
limits.py:177   X = c1[0]
limits.py:178   Y = m*(c1[0] - P[j-1][0]) + P[j-1][1]
limits.py:179   pts[(X,Y)] = |m_*X - Y + (c1[1] - m_*c1[0])| / (m_**2 + 1)**0.5
                            = |c1[1] - Y|     (since m_ == 0)
```
This one is meaningful: the vertical gap between the wall's y and the polygon edge's y at `x = c1[0]`.

Vertical wall (`m_ == "NOT DEFINED"`), `limits.py:186-193`:
```
limits.py:187   X = (c1[1] - P[j-1][1]) / m + P[j-1][0]
limits.py:188   Y = c1[1]
limits.py:189   pts[(X,Y)] = |X - c1[0]|
```
Horizontal gap between the wall's x and the polygon edge's x at `y = c1[1]`.

Vertical polygon edge (`m == "NOT DEFINED"`) with vertical wall, `limits.py:210-212`:
```
limits.py:210   X = P[j][0]
limits.py:211   Y = c1[1]
limits.py:212   pts[(X,Y)] = |X - c1[0]|
```

The `j == 0` wrap branch (`limits.py:219-278`) repeats all of the above with `P[len(P)-1]` / `P[n-1]` substituted for `P[j-1]`, at `limits.py:227`, `:232`, `:239`, `:243`, `:248`, `:252`.

### Case 2, in-band vertex to wall line (`limits.py:282-288`)

```
limits.py:282   m = slope(c1, c2)
limits.py:283   temp = P[j]
limits.py:286   pts[(temp[0], temp[1])] = |m*temp[0] - temp[1] + (c1[1] - m*c1[0])| / (m**2 + 1)**0.5     # m defined
limits.py:288   pts[(temp[0], temp[1])] = |temp[0] - c1[0]|                                                # m == "NOT DEFINED"
```

This formula yields a real, geometry-dependent limit:
- Vertical wall (`opti` 0 or 1): `m == "NOT DEFINED"` -> value = `|vertex_x - wall_x|` (`limits.py:288`).
- Horizontal wall (`opti` 2 or 3): `m == 0` -> `limits.py:286` reduces to `|0*temp[0] - temp[1] + c1[1] - 0| / 1 = |c1[1] - vertex_y|`.

**It is not the only such source in the live axis-aligned path.** Two other blocks write real distances into the same `pts` dict, and therefore into the same `max()`:

- **Case 1.** For a horizontal wall (`m_ == 0`) the `elif` at `limits.py:175` reaches `limits.py:179` and `:183`, and the wrap branch reaches `limits.py:240` and `:244`; all four evaluate to `|wall_y - edge_y|`. For a vertical wall (`m_ == "NOT DEFINED"`) with a vertical polygon edge (`m == "NOT DEFINED"`), the `elif` at `limits.py:207` reaches `limits.py:212` and `:217`, and the wrap branch at `limits.py:268` reaches `:273` and `:278`; all four evaluate to `|vertex_x - wall_x|`.
- **Case 3, vertical walls.** With `m_ == "NOT DEFINED"` and a vertical polygon edge, the flow is `limits.py:299` (`m == 'NOT DEFINED'`) -> the `else` at `:326` -> `:327` false -> the `elif` at `:336` -> `limits.py:338-339` (`X = self.rooms[i].coords[j][0]; pts[(X,Y)] = abs(X - self.coords_input1[0])`) and `:342-343` for `coords_input2`, with the same pattern at `:386-387` and `:390-391` in the `j == 0` branch. These keys are `(vertex_x, wall_y)`, so the `key[0]` test at `limits.py:404`/`:406` files them into `answer_left`/`answer_right` exactly like case 2's values.

Case 3 is the one to watch, because unlike case 1 it has no in-band precondition: its guard at `limits.py:295` is a tautology, so it runs for every vertex of rooms `0 .. len(nbd_rooms)-1` (the wrong room set, see below) and can dominate the returned limit. Treating case 3 as pure noise leads to misdiagnosing the number the module returns.

For a **horizontal** wall, case 3 contributes nothing real: `m_ == 0` sends non-vertical edges to `limits.py:309-317` (both writes identically zero), and vertical edges (`m == "NOT DEFINED"`) fall through `:327` and `:336` without writing at all.

### Case 3, unconditional crossing enumeration (`limits.py:292-391`)

Guard at `limits.py:295`:
```
limits.py:295   if P[j] != c1 or P[j] != c2:
```
`P[j]` cannot equal both `c1` and `c2` simultaneously (they are distinct wall endpoints), so **at least one disjunct is always true and this guard is a tautology**. The block runs for every vertex.

Line index corruption at `limits.py:293-294`:
```
limits.py:292   for i in range(len(nbd_rooms)):
limits.py:293       for j in range(len(self.rooms[i].coords)):
limits.py:294           n = len(self.rooms[i].coords[j])
```
- `limits.py:293` indexes `self.rooms[i]` where `i` is a **position in `nbd_rooms`**, not `nbd_rooms[i]`. Case 3 therefore examines rooms `0 .. len(nbd_rooms)-1`, an arbitrary set unrelated to the actual neighbourhood. (Case 1 at `limits.py:146` correctly writes `for i in nbd_rooms`.)
- `limits.py:294` sets `n = len(coords[j])`, the length of a **2-tuple**, so `n == 2` always. Every subsequent `self.rooms[i].coords[n-1]` (`limits.py:350`, `:354`, `:368`, `:372`, `:377`, `:381`) reads `coords[1]`, not the last vertex. The `n` computed at `limits.py:114` (the real vertex count) is destroyed by this assignment.

Case 3 writes 20 `pts` entries. Twelve of them (`limits.py:304`, `:308`, `:313`, `:317`, `:331`, `:335`, `:352`, `:356`, `:361`, `:365`, `:379`, `:383`) are zero by the identity above. The other eight (`limits.py:321`, `:325`, `:339`, `:343`, `:369`, `:373`, `:387`, `:391`) are real distances. Representative formulas:
```
limits.py:302   X = (c1[1] - P[j-1][1] - (m_*c1[0] - m*P[j-1][0])) / (m - m_)
limits.py:303   Y = m_*(X - c1[0]) + c1[1]
limits.py:304   pts[(X,Y)] = |m_*X - Y + (c1[1] - m_*c1[0])| / (m_**2 + 1)**0.5        # == 0 identically
limits.py:308   pts[(X,Y)] = |m_*X - Y + (c2[1] - m_*c2[0])| / (m_**2 + 1)**0.5        # == 0 identically (c2 point vs c2 line)
limits.py:320   X = (Y - P[j-1][1]) / m + P[j-1][0];  Y = c1[1]
limits.py:321   pts[(X,Y)] = |X - c1[0]|                                               # real; unreachable in the axis-aligned path (m == 0 -> inf, filtered)
limits.py:338   X = P[j][0];  Y = c1[1]
limits.py:339   pts[(X,Y)] = |X - c1[0]|                                               # real AND live for vertical walls
```

### Numeric hygiene filter (`limits.py:401-414`)

```
limits.py:403   if isinstance(pts[i], float) and not math.isinf(pts[i]) and not math.isnan(pts[i]):
limits.py:410   (identical condition for the top/bottom axis)
```
This is the only defence against the 16 unguarded division sites: `/(m - m_)` at `limits.py:166`, `:171`, `:227`, `:232`, `:302`, `:306`, `:350`, `:354` (nothing rules out `m == m_`), and `/m` at `limits.py:187`, `:191`, `:248`, `:252`, `:320`, `:324`, `:368`, `:372` (`m == 0` for any axis-aligned horizontal edge, which is the common case). Because operands are `numpy.float64`, those divisions produce `inf`/`nan` with a `RuntimeWarning` rather than raising, and the filter then discards them.

The four `/m_` divisions at `limits.py:199`, `:204`, `:260`, `:265` are **not** in this set. Each is preceded by the guard pair `if m_ != "NOT DEFINED" and m_ != 0:` followed by `m_ = -1/m_` (`limits.py:195-196` for `:199`/`:204`, `limits.py:256-257` for `:260`/`:265`), so `m_` is the reciprocal of a non-zero finite float and cannot itself be zero. Those sites are structurally safe.

**`isinstance(pts[i], float)` is fragile.** `numpy.float64` is a subclass of `float`, so the live path survives. If any coordinate ever arrives as `numpy.int64` or Python `int` (for example a floorplan whose `room_x` array is integer-typed), every derived distance becomes an integer type, `isinstance(..., float)` is `False`, all buckets empty out, `limits.py:415-422` fills them with `0`, and the function returns `(0, 0)` -> every shift is rejected as "Exceeding beyond the limits".

### The limit comparison (`limits.py:29-48`)

```
limits.py:30   if shiftDirection == "Left"  and shiftValue >= x_max:  proceed = 0
limits.py:35   if shiftDirection == "Right" and shiftValue >= y_max:  proceed = 0
limits.py:40   if shiftDirection == "Up"    and shiftValue >  x_max:  proceed = 0
limits.py:45   if shiftDirection == "Down"  and shiftValue >  y_max:  proceed = 0
```

**Two defects here.**
1. **Axis/name mismatch.** For `opti in {2,3}` the return at `limits.py:431` is `(max(answer_bottom), max(answer_top))`, so `x_max` is the *bottom* limit and `y_max` is the *top* limit. But `"Up"` is checked against `x_max` (`limits.py:40`), i.e. against the bottom limit, and `"Down"` against `y_max`, i.e. the top limit. The two vertical directions are swapped.
2. **Inconsistent strictness.** Left/Right use `>=` (`limits.py:30`, `:35`); Up/Down use `>` (`limits.py:40`, `:45`). A shift exactly equal to the limit is rejected horizontally and accepted vertically.

---

## Invariants And Preconditions

Stated or implied, none of them enforced in code:

1. **`adj_mat` row/column order must match `rooms` list order.** Explicitly demanded by the comment at `limits.py:104`. Unchecked. `handlers.py:1541-1547` builds `adj_matrix` from the graph edgeset while `handlers.py:1564-1586` builds `rooms` by iterating `room_x` positions; the two happen to agree only because `InputGraph` keeps node index == room index.
2. **Every room must have at least 4 vertices** for `wall_input` (`limits.py:62-74`) to index `coords[0..3]`. Unchecked.
3. **`opti` must be in `{0,1,2,3}`.** Otherwise `coords_input1`/`coords_input2` stay as the empty tuples set at `limits.py:18-19` and `run()` returns `None`. Unchecked.
4. **`room_input` must be a valid 0-based index into `rooms`.** The 1-based conversion was deliberately commented out at `limits.py:107-110`. Unchecked; the GUI feeds a raw `IntVar` (`gui.py:2187`).
5. **`shiftDirection` must match the wall orientation** (`"Left"/"Right"` for `opti` 0/1, `"Up"/"Down"` for `opti` 2/3). If it does not, none of the four branches at `limits.py:29-48` fires and `proceed` stays `1` from `limits.py:28`, i.e. **the shift is silently allowed with no limit check at all**. This is the default when `shiftDirection` is `""` (which is what `handlers.py:1588` initialises `s_dir` to).
6. **All coordinate scalars must be `float` or a `float` subclass** for the filter at `limits.py:403`/`:410` to keep them.
7. `run()` must not be called before `wall_input()`; `__init__` guarantees this by ordering (`limits.py:20` before `limits.py:27`).

---

## Failure Modes

### Degenerate polygon

| Degeneracy | Handling |
|---|---|
| Room with fewer than 4 vertices | **No handling.** `IndexError` inside `wall_input` at `limits.py:64`/`:67`/`:70`/`:73`. |
| Room with an empty `coords` list | **No handling.** Same `IndexError`; also `limits.py:114` would return `0` and the loop at `limits.py:126` would not execute. |
| Two coincident consecutive vertices (zero-length edge) | Partially handled: `slope` returns `"NOT DEFINED"` (`limits.py:55`) and `distance` returns `0` (`limits.py:59`). `IsInRegion` then requires `d1 <= 0 and d2 <= 0` (`limits.py:85`), so only exactly-coincident points are accepted, and the band collapses. No error, silently produces empty answer buckets -> `(0,0)`. |
| Duplicate vertices elsewhere in the ring | The re-scan at `limits.py:127`/`:133` may bind `coords_input2` to the wrong successor, silently selecting a different wall than `wall_input` chose. |
| Polygon edge parallel to the wall's perpendicular (`m == m_`) | Division by zero at `limits.py:166`, `:171`, `:227`, `:232`, `:302`, `:306`, `:350`, `:354`. With `numpy.float64` operands this yields `inf`/`nan` and a `RuntimeWarning`; the results are then discarded by `limits.py:403`/`:410`. With plain Python floats it would raise `ZeroDivisionError` uncaught. |
| Horizontal polygon edge (`m == 0`) in a `/m` branch | Division by zero at `limits.py:187`, `:191`, `:248`, `:252`, `:320`, `:324`, `:368`, `:372`. Same `inf`/`nan` -> filtered path. The `/m_` divisions at `limits.py:199`, `:204`, `:260`, `:265` are not affected: the guards at `limits.py:195` and `:256` make `m_` non-zero and finite before the reciprocal. |
| Rooms with more than 4 vertices | Case 3 will misbehave because `n` is clobbered to `2` at `limits.py:294`; `wall_input` will still only consider the first four vertices. No error, wrong answer. |

### Room that cannot fit / no room to move

- If no candidate point lands on a given side, the bucket is empty and `limits.py:415-422` appends `0`. `max([0]) == 0`, so the limit is `0` and any positive shift is rejected (`limits.py:30`, `:35`) with `proceed = 0`. `handle_limits` then prints `"Limit Exceeded"` (`handlers.py:1683`) and **nothing is redrawn and no dialog is shown** (the `show_warning` call is commented out at `handlers.py:1684`). From the user's point of view the "Apply" button does nothing and the reason is only visible on stdout.
- `self.errorMessage` (`limits.py:31`, `:36`, `:41`, `:46`) is echoed to stdout by the `print(self.errorMessage)` call that follows each write (`limits.py:32`, `:37`, `:42`, `:47`) and is consumed by nothing else in the repo. The diagnostic string reaches a terminal the desktop user is not necessarily looking at, and never reaches the UI.

### Contradiction with user-supplied minimum dimensions

**There is no handling, because there is no interaction.** `limits.py` contains **zero** references to `min_width`, `max_width`, `min_height`, `max_height`, aspect ratio, area, or plot dimensions. It never reads `ui.min_dim_inputs`, never imports anything from `GPLAN/source/dimensioning/`, and is never given the constraint payload that `input_for_min_dim.floorplan` builds (`handlers.py:379`, `:807`, `:1230`, `:1382`, `:1870`, ...).

Consequence: a wall shift approved by `LimitsAlgorithm` can shrink a room below the `min_width`/`min_height` the user supplied to `minimum_dimensioning.main`, and nothing detects it. The check that `limits.py` performs is purely "does the wall hit a neighbouring vertex", not "is the resulting room still legal". After `proceed == 1`, `handle_limits` goes straight to `NewCoordinateAlgorithm` (`handlers.py:1615`) and a fresh `InputGraph` (`handlers.py:1618`) without re-running any dimensioning solve.

### Missing file

`handle_limits` wraps the read of `./saved_files/input_to_limits.json` in a bare `try/except` (`handlers.py:1515-1519`) that shows a warning but **does not return**; execution falls through to `handlers.py:1522` with an empty `input_json`, then `KeyError: 'nodecnt'` at `handlers.py:1536`.

### Type failures from the GUI

`gclass.room_limits` comes from `tk.IntVar` (`gui.py:106`, `gui.py:2187`) and shift values from `tk.DoubleVar` (`gui.py:108-115`), so the comparisons at `limits.py:30-45` get numeric types. If a user types a non-numeric string into the entry, `DoubleVar.get()` raises `TclError` inside `change_limits_ender` (`gui.py:2192`) before `limits.py` is ever reached.

### Unconditional stdout spam

`limits.py:21-26`, `:125`, `:139`, `:140`, `:395`, `:425`, `:426`, `:429`, `:430` print unconditionally, including the whole `pts` dictionary (`limits.py:395`) which for a moderate floorplan contains hundreds of entries. There is no verbosity flag.

---

## Coupling (what breaks if you change this)

| If you change ... | ... this breaks |
|---|---|
| The vertex winding order in `handlers.py:1581` | `wall_input` (`limits.py:62-74`) silently remaps `opti` onto different walls, and the GUI radio labels (`gui.py:2133`, `:2143`, `:2153`, `:2163`) become wrong. |
| `poly.Room.coords` shape (`poly.py:12`) | Everything: `limits.py` indexes `coords[j][0]` and `coords[j][1]` in ~120 places. |
| The `"NOT DEFINED"` string sentinel from `slope` (`limits.py:55`) | Every branch at `limits.py:78`, `:162`, `:163`, `:175`, `:194`, `:195`, `:207`, `:223`, `:224`, `:236`, `:255`, `:256`, `:268`, `:284`, `:299`, `:300`, `:309`, `:326`, `:327`, `:336`, `:347`, `:348`, `:357`, `:374`, `:375`, `:384`. |
| The return arity/order of `run()` (`limits.py:427`, `:431`) | `limits.py:27` unpack, and transitively `proceed`, and therefore `handlers.py:1605`. |
| `self.coords_input1` / `self.coords_input2` semantics | `handlers.py:1615` passes both straight into `NewCoordinateAlgorithm(exact_RoomSet, adjrooms, s_dir, shift_value, x, y, opti, originalRoom)` (`GPLAN/source/polygonal/newcoord.py:9`) as its `x` and `y` arguments. |
| `self.proceed` type/meaning | `handlers.py:1605` (`if limits_instance.proceed == 1`). |
| The `input_to_limits.json` schema | Producer at `handlers.py:1092-1117`, consumer at `handlers.py:1522-1559`. The producer is the *rectangular single-floorplan* handler, so the "polygonal" limits feature actually operates on rectangular output. |
| `InputGraph.room_x` dtype (`GPLAN/source/inputgraph.py:128`) | The `isinstance(pts[i], float)` filter at `limits.py:403`/`:410`. Switch to an integer dtype and the module returns `(0,0)` for everything. |

Nothing outside `handlers.py:1603-1615` depends on this module. Deleting `limits.py` would break exactly the `command == "limits"` path in `main.py:57-58` and nothing else.

---

## Dead Or Duplicated Code

### Dead

| Item | file:line | Status |
|---|---|---|
| `find_limits` method | `limits.py:433-442` | Entirely commented out. Referenced only from other comments: `poly.py:6`, `poly.py:54`, `pythongui/drawing.py:147`. |
| `dts` list | `limits.py:142` | Declared, never read or written again. |
| `self.errorMessage` | `limits.py:13`, `:31`, `:36`, `:41`, `:46` | Written five times; read only by the four in-class `print()` calls at `limits.py:32`, `:37`, `:42`, `:47`. No external reader: the would-be one at `handlers.py:1684` is commented out and names a different object. Not dead, but the value goes to stdout only. |
| `import networkx as nx` | `limits.py:1` | `nx` never used. |
| `import matplotlib.pyplot as plt` | `limits.py:2` | `plt` never used. |
| `import numpy as np` | `limits.py:3` and `limits.py:5` | `np` never used, and the import is duplicated verbatim. |
| `import tkinter as tk` | `limits.py:4` | `tk` never used. |
| `import re` | `limits.py:6` | `re` never used. |
| `# import newcoord as newcoord` | `limits.py:8` | Commented out. |
| `__main__` block | `limits.py:444-446` | `print()` only; the call is commented out. Stub. |
| Case 3 guard `if P[j] != c1 or P[j] != c2` | `limits.py:295` | Tautology, always true. Dead condition. |
| All `pts` writes that measure a point against the line it was just placed on, i.e. `|m_*X - Y + (c[1] - m_*c[0])|/(m_**2+1)**0.5` immediately after `Y = m_*(X - c[0]) + c[1]` for the same endpoint `c` | `c1`/`c1` at `limits.py:169`, `:201`, `:230`, `:262`, `:304`, `:313`, `:331`, `:352`, `:361`, `:379`; `c2`/`c2` at `limits.py:308`, `:317`, `:335`, `:356`, `:365`, `:383` | Sixteen sites, all provably `0.0` by construction. They add nothing to `max()`. Dead arithmetic. |
| `pts` writes that pair a `c2`-derived point with the `c1` line equation | `limits.py:173`, `:205`, `:234`, `:266` | Constant `distance(c1,c2)` regardless of the polygon. Not geometry-dependent, but non-zero, so they can win a `max()`. |
| The entire module in the deployed FastAPI service | `GPLAN/api.py` | No call path. Reachable only from `main.py:58` (Tkinter desktop app). |
| The re-derivation loop for `coords_input2` | `limits.py:126-138` | Redundant with `wall_input` (`limits.py:62-74`) for well-formed 4-vertex rectangles. |

### Duplicated within the file

The `j != 0` block (`limits.py:150-217`) and the `j == 0` wrap block (`limits.py:218-278`) are the same ~65-line case analysis with `P[j-1]` replaced by `P[len(P)-1]` / `P[n-1]`. Likewise the `j != 0` block of case 3 (`limits.py:296-343`) and its `j == 0` counterpart (`limits.py:344-391`). Four near-identical copies of the same slope case analysis, which is exactly why the `n` corruption at `limits.py:294` and the `P[j-1]` leftovers at `limits.py:259` and `limits.py:264` (inside the `j==0` wrap block, where `j` is `0` so `P[j-1]` is `P[-1]`) went unnoticed.

### Duplication against `minimum_dimensioning.py` / `solve_linear.py`

**No shared constraint family. Nothing to reconcile.**

- `minimum_dimensioning.py` builds two directed constraint graphs (`construct_constraintgraphX` at `minimum_dimensioning.py:225`, `construct_constraintgraphY` at `:307`) and solves them by longest path (`pos_longest_path` at `:388`, `longest_path` at `:466`, driven from `main` at `:767`). Its per-room bounds live in `lb_width`/`ub_width`/`lb_len`/`ub_len` (`minimum_dimensioning.py:186-203`), are derived by `upper_bound` (`minimum_dimensioning.py:158-177`, using `DEFAULT_UB_FACTOR = 5` at `:148` and `SOLVER_UB_SLACK = 2.5` at `:155`), and enter the graph as edge weights at `minimum_dimensioning.py:237-238`.
- `solve_linear.py` runs two `scipy.optimize.linprog` calls (`solve_linear.py:76`, `:140`) over stacked `[-min, +max]` bound vectors (`solve_linear.py:56-62`, `:115-129`) with an aspect-ratio reconciliation step (`solve_linear.py:92-107`) and an infeasibility fallback (`solve_linear.py:110-121`).
- `limits.py` has no bound vectors, no LP, no constraint graph, no aspect ratio, no area, and no plot-size handling. Its only shared vocabulary with those files is the English word "limit".

The one conceptual echo is the "clamp to zero when nothing is available" default at `limits.py:415-422` versus the "fall back to the historical bound when the supplied maximum is unusable" default at `minimum_dimensioning.py:169-176`. They are different families (a geometric slack default versus a solver upper-bound default) and share no code. The closest real overlap in intent is `solve_linear.py:110-114` (detect `min > max` contradiction and fall back), which `limits.py` has no analogue of.

---

## Open Questions

1. **Is the `"Up"`/`"Down"` axis swap at `limits.py:40` and `limits.py:45` a bug or an intentional inversion?** As written, `"Up"` is compared against `max(answer_bottom)` and `"Down"` against `max(answer_top)` for `opti in {2,3}` (return at `limits.py:431`). Nothing in the repo documents the intended convention.
2. **Should the returned limit be `max` or `min`?** `limits.py:425-426` and `:429-430` print `min(...)` while `limits.py:427` and `:431` return `max(...)`. A collision limit should almost certainly be the *nearest* obstacle (`min`), which is what the print statements suggest was originally intended. Using `max` means the wall is allowed to pass through the nearest neighbour vertex.
3. **Is the case 3 block (`limits.py:292-391`) supposed to run at all?** Its guard is a tautology (`limits.py:295`), its room index is wrong (`limits.py:293` uses `i` rather than `nbd_rooms[i]`), and its `n` is corrupted (`limits.py:294`). Twelve of its twenty `pts` writes are provably `0`. It cannot simply be deleted as a no-op, though: the remaining eight (`limits.py:321`, `:325`, `:339`, `:343`, `:369`, `:373`, `:387`, `:391`) are real distances, and for vertical walls `:339`/`:343`/`:387`/`:391` are live and can set the returned limit. So the block looks like an abandoned draft that nevertheless changes the answer, computed over the wrong rooms.
4. **Should `IsInRegion` (`limits.py:76`) also bound the perpendicular offset from the wall?** As written it bounds only the projection along the wall direction (`limits.py:89-92`, `:96-99`), leaving the wall-normal direction unbounded, so a vertex of a far-away room is treated as a collision candidate whenever its along-wall projection falls between the caps.
5. **Why does the "polygonal" limits feature consume JSON written by the rectangular single-floorplan handler** (`handlers.py:1114-1117`) rather than by `handle_poly` (`handlers.py:1509` reads what `handlers.py:1092-1117` wrote)? Is the polygonal case simply unimplemented?
6. **Should this module consult the user's min/max dimension constraints before approving a shift?** Currently it cannot: it receives neither `ui.min_dim_inputs` nor any constraint payload. A wall shift can violate `min_width`/`min_height` with no detection.
7. **Is `handle_limits` intended to be exposed on the HTTP API?** It exists only as a Tkinter command (`main.py:57-58`); `GPLAN/api.py` has no `limits` route.
8. **Is `self.errorMessage` meant to reach the user?** Today it only reaches stdout, via the four in-class `print()` calls at `limits.py:32`, `:37`, `:42`, `:47`. The intended UI consumer at `handlers.py:1684` is commented out and refers to `newCoordsInstance.error_message`, a different object, which suggests two half-finished error channels.
