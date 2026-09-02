# Door Connectivity API

LINK: [https://api.gplan.in/api/generate/door_connectivity](https://api.gplan.in/api/generate/door_connectivity)

Generates a floorplan based on adjacency and non adjacency of rooms represented by nodes.
The property of adjacency and non adjacency of the rooms (nodes) are depicted using edges

### Fields

/// tab | Request

`rectangular : bool (true|false)`

: remove this

`corridor : bool (true|false)`
: Used to represent if there is a corridor present in the Floorplan (to be implemented in a future version) 

`dimensioned : bool (true|false)`

: DEPRECATED 

`non_adj : bool (true|false)`

: To be set to true if there are non adjacent edges in the graph 

`dimensionedCirculation : bool (true|false)`

: Used to provide dimensions to the corridor (if present)  (to remove)

`minDimEnabled : bool (true|false)`

: Used if dimensions are to be sent. By default dimensions are **minimums only**:
  each node's `width.min` / `height.min` is enforced as a lower bound and the server
  opens the upper bound (`max` is ignored and treated as 99999) — the min-dim solver
  compacts every room toward its minimum, so rooms come out at or just above `min`.
  Do not use min = max to request exact dimensions; exact sizing is not supported on
  this path for an ordinary room. Send `maxDimEnabled: true` to also apply the
  per-node ceilings. A node explicitly marked `is_fixed: true` is the one
  exception; see **Fixed rooms** below.

`maxDimEnabled : bool (true|false) (default = false)`

: Opt in to per-room **maximum** dimensions. Without it every `width.max` /
  `height.max` is replaced by 99999 and the solver bounds each room at 5x its own
  minimum, which is what lets a small service room stretch until it is larger than a
  habitable one. With it the ceilings are applied along a deliberate degradation
  ladder, so a batch is never returned empty because the ceilings were too tight:

  1. The longest-path solve widens each supplied ceiling to at least **2.5x that
     room's minimum** (`SOLVER_UB_SLACK`). In a gapless rectangular tiling a column
     of small rooms must stack to the same total as a column of large ones, so hard
     per-room ceilings make nearly every topology infeasible.
  2. A topology that is still infeasible is retried with its ceilings stripped. When
     that happens the task message gains
     `"Room maximum dimensions were released for some floorplans."`
  3. The plot-expansion fallback (see `plot_width`) drops **only** the plot cap; the
     ceilings continue to apply inside it.
  4. The gapless fill that closes notches applies the **exact** ceilings (both the
     larger of `width.max`/`height.max` as a span cap and `width.max * height.max` as
     an area cap), expanding rooms in descending order of headroom so living rooms
     and bedrooms absorb leftover area before a bathroom or balcony does. A hole no
     capped room may absorb is then closed without ceilings, because a gapless
     rectangle is required and an oversized service room is only undesirable. When
     that happens the task message gains
     `"Room maximum dimensions were exceeded while closing gaps in some floorplans."`

  Consequence for clients: room dimensions are still not guaranteed to sit inside the
  ceilings. Treat them as a strong preference, check the returned geometry, and rank
  or flag plans accordingly. Both degradation steps announce themselves in the
  message, so a batch that carries neither warning is fully within its ceilings.

  Measured on a 5-room flat (`test_max_dimensions.py`): with ceilings at 3x each
  room's minimum the solver never needs the release, 4 of 6 plans come back entirely
  within the ceilings, and the 2 that do not are reported. With ceilings just above
  the minimums the release fires and the plans behave like the uncapped baseline.

`removeAddCirculation : bool (true|false)`

: to be implemented 

`publicEnabled : bool (true|false)`

: default false to be sent  

`normalizeConst : bool (true|false)`

: placeholder documentation

`limit : int`

: Number of floorplans to generate (same as count) 

`corridorThickness : int`

: Thickness of the corridor if present. Only considered if `corridor` is set to true

`starting_from : int`

: To be implemented with corridor 

`count : int`

: Number of floorplans to generate 

`nodes : array[node]`

: An array of node objects (structure below) representing each "node" in the graph

- `id`
    : The id of the node, used as an identifier for the edges
- `x : int (optional)`
    : The x coordinate of the node
- `y : int (optional)`
    : The y coordinate of the node
- `label : string`
    : Name of the room / area that the node represents
- `color: Hex Code (optional) (default =  #1C4C82)`
    : The HexCode of the color of the node to be used in the graph
- `width : limit`
    : The limits for the width of the room/area represented by the node. With
      `minDimEnabled`, only `min` is used (as a lower bound); `max` is ignored
- `height : limit`
    : The limits for the height of the room/area represented by the node. With
      `minDimEnabled`, only `min` is used (as a lower bound); `max` is ignored
- `ratio : limit (optional) (default = {"max" : 9999, "min" : 3})`

- `is_fixed : bool (optional) (default = false)`
    : Marks a rectangular node as a hard occupied part of the dissection, such
      as a stair or lift core. Fixed nodes require `minDimEnabled: true`, an
      equal positive `width.min == width.max`, and an equal positive
      `height.min == height.max`. Unlike an ordinary min-dimensioned room, the
      engine does not widen these maxima, release them on an infeasible solver
      rung, relax them toward allocator floors, rotate the plan, grow the fixed
      room while closing gaps, or let post-processing resize it. The engine also
      derives an exact area equality from the two spans. Invalid fixed bands are
      rejected at the API boundary.
- `fixed_anchor : string (optional with is_fixed)`
    : Hard exterior anchor for a fixed node. Supported values are `N`, `NE`,
      `E`, `SE`, `S`, `SW`, `W`, and `NW` (full direction names are accepted
      too). A corner value requires direct contact with both exterior sides;
      it is stronger than an ordinary cardinal request, which only requires an
      unobstructed strip. In the normalized floorplan coordinate system,
      `NW` therefore means the fixed room's left and top coordinates are both
      `0`. Housing defaults a newly created staircase to `SW`: left is `0` and
      bottom equals the declared plot height. For `S`/`E` anchors that declared
      extent is authoritative, so a smaller translated plan cannot pass merely
      by touching its own result bounding box.

- `limit` 
    - `max: int`
    - `min: int`

`edges : array[edge]`
: An array of edge objects (structure below) representing each "edge" in the graph

- `source : int`
: The id of the node from which the edge originates

- `target : int`
: The id of the node at which the edge terminates

- `color : string ("red" | "black")`
: The color of the edge, a "black" edge represents an adjacent edge, a "red" edge represents a non adjacent edge

`plot_width : int`

: Upper cap for the width of the overall rectangular plot. Applied only when > 0;
  send 0 for no cap (the solver minimizes the plot anyway). If no floorplan fits
  the cap, the engine retries unbounded and returns **expand-only** results: rooms
  keep their solved (minimum-satisfying) dimensions or grow to fill the plot, and
  the plot is enlarged on any overflowing axis — rooms are never scaled below
  their minimums to force a fit. The batch is ordered by required plot growth
  (least first) and the task message contains "the plot was expanded to fit",
  which clients can detect via the keyword `expanded`

`plot_height : int`

: Upper cap for the height of the overall rectangular plot (same semantics as
  `plot_width`)

`enforce_plot : bool (optional) (default = false)` *(2026-08-17)*

: Hard plot-fit mode. When true and `strict_plot_width`/`strict_plot_height`
  are both > 0, the strict pair replaces the solver's plot cap (so
  `plot_width`/`plot_height` can keep carrying a deliberately slack rejection
  cap for backward compatibility) and the engine changes behaviour three ways:
  the `dim_on_paths_bdy` boundary pre-selector is skipped (it tunes the pool
  for a slack cap and collapses it at a real one), so the FULL topology pool
  is solved under the cap; the catalogue is composed fitting-plans-first and,
  when fewer than 30 fit, topped up - each remaining topology is first solved
  against the SWAPPED plot (a rotated fit, geometry swapped back; skipped
  when cardinal constraints are present) and only then expanded via the
  legacy uncapped + scale path, appended after every fitting plan; and the
  response carries the per-plan `plot_fit` disclosure below. Zero fitting
  topologies degrade to the legacy expanded batch, labeled, never empty.
  Backends predating the flag ignore all three fields.

  *(2026-08-29, the plot-wins rule.)* Two more consequences, both scoped to
  this flag. **The fill solver's search is two-sided:** a topology that does
  not fit even at the request's band minimums first relaxes those minimums
  DOWNWARD toward the allocator's rulebook floors - never below one - and the
  bisection toward the allocated targets then runs from wherever that landed,
  so a plan a hair under its preferred room sizes INSIDE the plot is preferred
  to a labeled expanded plan outside it. **Post-processing fills the plot
  exactly:** `postprocess_options.exact_fill` is switched on for you, which
  forces the rectangle preference back on (a trim nobody can reabsorb is an
  empty notch, and the plot outranks the ceilings) and lets phase 5 keep
  releasing room limits, class by class, until the outline closes on the plot.
  Every such release is disclosed - `over_ceiling_rooms`, `fill_escalated` and
  a `phase_notes` line per plan, plus a sentence in the task message. See
  [postprocess_api.md](postprocess_api.md).

`strict_plot_width : int`, `strict_plot_height : int` *(with `enforce_plot`)*

: The REAL plot footprint to enforce, feet.

`rotation_enabled : int (0|1) (optional) (default = 1)`

: When 1 (default), every accepted floorplan is also returned as a whole-plan 90°
  rotated variant. In rotated variants each room satisfies its minimums with width
  and height swapped. Send 0 if minimum width/height must hold strictly per axis
  (also roughly halves generation time). The engine forces rotation off when
  any node is fixed, even if the client sends 1.

### Fixed rooms

A fixed room participates in the adjacency graph as a normal node, but its
geometry is an immutable obstacle. Clients should include at least one real
adjacency edge from the fixed node to the program (for example, Staircase to
Living Room or circulation) so the requested graph remains connected:

```json
{
  "id": 5,
  "label": "Staircase",
  "is_fixed": true,
  "fixed_anchor": "SW",
  "width": {"min": 7, "max": 7},
  "height": {"min": 10, "max": 10},
  "ratio": {"min": 0.5, "max": 3},
  "color": "#1C4C82"
}
```

The engine injects the anchor into every topology attempt, equality-constrains
both axes in the dimension solver, treats the room as occupied during
rectangular gap closing, and validates exact spans plus direct side contact
after rectangularization and after post-processing. Soft cardinal requests and
ordinary room maxima may still follow their documented relaxation ladders; a
fixed node never does. If the fixed dimensions/anchor cannot be realised (for
example, two overlapping rooms both demand the same corner), the response contains no
invalid fallback plan and its message says the fixed-room constraints are hard.

The returned fixed-room geometry is authoritative. A client must not uniformly
scale or centre a generated variant after the engine returns it, because that
would resize the core or move it away from the anchored plot corner. Validate
the returned fixed bounding box before accepting a variant, then render that
node as the existing stair/core rather than dressing it as an ordinary room.

///

/// tab | Response

`message : string`
: Message from the server

`response : object`

- `Documents : object`

    : A document object created on the server, can be saved for future retrival using the `documentID`

- `documentID : uuid`

    : An identifier for the floorplan document generated on the server

- `name : string`

    : Name of the document generated on the server

- `count : int`

    : Number of floorplans generated in each document

- `ptpg_graph : array[array[int]]`

    : Adjacency matrix representing the PTPG graph

- `adjacency_shortfalls : array[array[object]]` (dimensioned catalogues only, 2026-08-06)

    : Metric adjacency disclosure (E2a of `plans/VALIDITY_AND_TOPOLOGY_ENGINE_PLAN.md`),
    index-aligned with `floorPlans`. The graph guarantees each requested adjacency
    combinatorially, but the dimensioning can realise it as a corner contact or a sliver
    no door fits through; each inner array lists the requested pairs this plan realises
    with less shared wall than the request's `postprocess_options.min_door_overlap`
    (default 2 ft). An empty inner array means every requested adjacency has door-width
    wall. Absent on responses predating the field - absence must never be read as
    "all adjacencies hold". The task message names how many plans are affected.

    - `a`, `b` : node indices of the requested edge
    - `a_name`, `b_name` : the rooms' labels
    - `shared_wall_ft` : realised shared wall, feet (0 = corner contact only)

- `plot_fit : array[object]` (only when the request set `enforce_plot`, 2026-08-17)

    : Per-plan plot-fit disclosure, index-aligned with `floorPlans`, judged on the
    FINAL geometry (after post-processing) against the enforced plot. The task
    message also states "N of M floorplan(s) fit within the W x H ft plot".

    - `fits` : bool, extent inside the plot (0.05 ft epsilon)
    - `plan_width`, `plan_height` : the plan's built extent, feet
    - `plot_width`, `plot_height` : the enforced plot, feet
    - `overflow_width`, `overflow_height` : feet past the plot per axis (0 = none)

- `floorPlans : array[array[object]]`

    : A nested array of objects with the structure below representing each floorplan generated. Each element in the outer array holds one floorplan, each element in the inner array holds information about each room/area in the floorplan

    - `_id` : ID of the room/area in the generated floorplan
    - `name`: Name/Label of the room/area in the generated floorplan (same as the label passed in the request)
    - `label_coord` : [x, y] coordinates of the label in the floorplan
    - `area` 
    - `width`
    - `height`
    - `color`

    - `walls : array[object]`
        : An array of objects with the following structure representing each wall of the room in the floorplan

        - `_id` : Identifier for the wall

        - `x1` : x coordinate of the start of the wall

        - `y1` : y coordinate of the start of the wall

        - `x2` : x coordinate of the end of the wall

        - `y2` : y coordinate of the end of the wall

    - `circular_coordinates`
        : Circular coordinates [x,y] of each room

///

## Examples
/// tab | Request
<figure markdown="span">
  ![Graph Example](../assets/door_connectivity_graph.png){ width="600" }
  <figcaption>Graph Example</figcaption>
</figure>
/// tab | Python

```py
import requests

url = "https://api.gplan.in/api/generate/door_connectivity"

headers = {
    "accept" : "application/json",
    "content-type" : "application/json",
    "Authorization" : "Api-Key <YOUR_API_KEY>"
}
body ={
    "rectangular": true,
    "corridor": false,
    "dimensioned": false,
    "non_adj": true,
    "dimensionedCirculation": false,
    "minDimEnabled": true,
    "removeAddCirculation": false,
    "publicEnabled": false,
    "normalizeConst": true,
    "limit": 10,
    "corridorThickness": 0.5,
    "starting_from": 0,
    "count": 10,
    "nodes": [
        {
            "id": 0,
            "label": "1",
            "color": "#1C4C82",
            "width": {
                "max": 99999,
                "min": 3
            },
            "height": {
                "max": 99999,
                "min": 3
            }
        },
        {
            "id": 1,
            "label": "2",
            "color": "#1C4C82",
            "width": {
                "max": 99999,
                "min": 3
            },
            "height": {
                "max": 99999,
                "min": 3
            }
        },
        {
            "id": 2,
            "label": "3",
            "color": "#1C4C82",
            "width": {
                "max": 99999,
                "min": 3
            },
            "height": {
                "max": 99999,
                "min": 3
            }
        }
    ],
    "edges": [
        {
            "source": 0,
            "target": 1,
            "color": "black"
        },
        {
            "source": 2,
            "target": 0,
            "color": "black"
        },
        {
            "source": 1,
            "target": 2,
            "color": "black"
        }
    ]
} 

response = requests.post(url, headers=headers, data=body)
```

///

/// tab | cURL

```sh
curl -X POST "https://api.gplan.in/api/generate/door_connectivity" \
     -H "accept: application/json" \
     -H "content-type: application/json" \
     -H "Authorization: Api-Key <YOUR_API_KEY>" \
     -d '{
    "rectangular": true,
    "corridor": false,
    "dimensioned": false,
    "non_adj": true,
    "dimensionedCirculation": false,
    "minDimEnabled": true,
    "removeAddCirculation": false,
    "publicEnabled": false,
    "normalizeConst": true,
    "limit": 10,
    "corridorThickness": 0.5,
    "starting_from": 0,
    "count": 10,
    "nodes": [
        {
            "id": 0,
            "label": "1",
            "color": "#1C4C82",
            "width": {
                "max": 99999,
                "min": 3
            },
            "height": {
                "max": 99999,
                "min": 3
            }
        },
        {
            "id": 1,
            "label": "2",
            "color": "#1C4C82",
            "width": {
                "max": 99999,
                "min": 3
            },
            "height": {
                "max": 99999,
                "min": 3
            }
        },
        {
            "id": 2,
            "label": "3",
            "color": "#1C4C82",
            "width": {
                "max": 99999,
                "min": 3
            },
            "height": {
                "max": 99999,
                "min": 3
            }
        }
    ],
    "edges": [
        {
            "source": 0,
            "target": 1,
            "color": "black"
        },
        {
            "source": 2,
            "target": 0,
            "color": "black"
        },
        {
            "source": 1,
            "target": 2,
            "color": "black"
        }
    ]
}'

```

///



///
/// tab | Response

<figure markdown="span">
  ![Generated Floorplan](../assets/door_connectivity_floorplans.png){ width="600" }
  <figcaption>Generated Floorplan</figcaption>
</figure>

```json
{
    "message": "Generated Multiple Door connectivity floorplan.Time taken: 15.793800354003906 msTime taken: 15.800952911376953 ms",
    "response": {
        "Documents": {
            "documentID": "80a873da-aeef-4977-8d9b-c48da93f417d",
            "name": "Untitled Document",
            "count": 3,
            "ptpg_graph": [
                [0, 1, 1],
                [1, 0, 1],
                [1, 1, 0]
            ],
            "floorPlans": [
                [
                    {
                        "_id": "0e72df45-b5d5-46d8-ad8e-3cd7fa25dbed",
                        "name": "1",
                        "label_coord": [
                            1.1914907101908583,
                            1.5
                        ],
                        "area": 12.0,
                        "width": 4.0,
                        "height": 3.0,
                        "assets": [],
                        "color": "#1C4C82",
                        "walls": [
                            {
                                "_id": "8299651e-ff49-462b-a704-e6855f953626",
                                "x1": 1.0,
                                "y1": 0.0,
                                "x2": 1.0,
                                "y2": 3.0,
                                "assets": []
                            },
                            {
                                "_id": "34f808ee-eebb-4320-a470-8f17e28d7814",
                                "x1": 1.0,
                                "y1": 3.0,
                                "x2": 5.0,
                                "y2": 3.0,
                                "assets": []
                            },
                            {
                                "_id": "3768dc5a-ea54-42a0-a776-c71273fbf85d",
                                "x1": 5.0,
                                "y1": 3.0,
                                "x2": 5.0,
                                "y2": 0.0,
                                "assets": []
                            },
                            {
                                "_id": "f1c2343f-47ff-4c6b-a51f-a93a651e5cdd",
                                "x1": 5.0,
                                "y1": 0.0,
                                "x2": 1.0,
                                "y2": 0.0,
                                "assets": []
                            }
                        ],
                        "circular_coordinates": [
                            [
                                1.0,
                                0.0
                            ],
                            [
                                1.0,
                                3.0
                            ],
                            [
                                5.0,
                                3.0
                            ],
                            [
                                5.0,
                                0.0
                            ]
                        ]
                    },
                    {
                        "_id": "4c53e407-b745-491f-a5a8-797ccf6b7020",
                        "name": "2",
                        "label_coord": [
                            3.191490710190858,
                            4.5
                        ],
                        "area": 9.0,
                        "width": 3.0,
                        "height": 3.0,
                        "assets": [],
                        "color": "#1C4C82",
                        "walls": [
                            {
                                "_id": "ea68812c-9540-4ecd-bf3e-12c8e93ec98a",
                                "x1": 3.0,
                                "y1": 3.0,
                                "x2": 3.0,
                                "y2": 6.0,
                                "assets": []
                            },
                            {
                                "_id": "d9bae276-0a0e-4392-8a2d-869ccdebd9b3",
                                "x1": 3.0,
                                "y1": 6.0,
                                "x2": 6.0,
                                "y2": 6.0,
                                "assets": []
                            },
                            {
                                "_id": "263413f1-681a-4528-bd99-a85bab362bc1",
                                "x1": 6.0,
                                "y1": 6.0,
                                "x2": 6.0,
                                "y2": 3.0,
                                "assets": []
                            },
                            {
                                "_id": "e932fe99-d838-4cfe-a50f-bc6e72dce953",
                                "x1": 6.0,
                                "y1": 3.0,
                                "x2": 3.0,
                                "y2": 3.0,
                                "assets": []
                            }
                        ],
                        "circular_coordinates": [
                            [
                                3.0,
                                3.0
                            ],
                            [
                                3.0,
                                6.0
                            ],
                            [
                                6.0,
                                6.0
                            ],
                            [
                                6.0,
                                3.0
                            ]
                        ]
                    },
                    {
                        "_id": "4e7635ef-aebd-49aa-a507-cf00c76056eb",
                        "name": "3",
                        "label_coord": [
                            0.19149071019085823,
                            4.5
                        ],
                        "area": 9.0,
                        "width": 3.0,
                        "height": 3.0,
                        "assets": [],
                        "color": "#1C4C82",
                        "walls": [
                            {
                                "_id": "a78b83b7-5d13-482d-ac44-a7ad3e72c58a",
                                "x1": 0.0,
                                "y1": 3.0,
                                "x2": 0.0,
                                "y2": 6.0,
                                "assets": []
                            },
                            {
                                "_id": "1b94d27a-fe8e-4bef-a249-95edd582b111",
                                "x1": 0.0,
                                "y1": 6.0,
                                "x2": 3.0,
                                "y2": 6.0,
                                "assets": []
                            },
                            {
                                "_id": "9941c24b-a2e0-4dbc-89e2-59ddea191641",
                                "x1": 3.0,
                                "y1": 6.0,
                                "x2": 3.0,
                                "y2": 3.0,
                                "assets": []
                            },
                            {
                                "_id": "418843af-cc9c-43d2-91ca-eacbab8548fa",
                                "x1": 3.0,
                                "y1": 3.0,
                                "x2": 0.0,
                                "y2": 3.0,
                                "assets": []
                            }
                        ],
                        "circular_coordinates": [
                            [
                                0.0,
                                3.0
                            ],
                            [
                                0.0,
                                6.0
                            ],
                            [
                                3.0,
                                6.0
                            ],
                            [
                                3.0,
                                3.0
                            ]
                        ]
                    }
                ],
                [
                    {
                        "_id": "79726a85-311b-4d06-a54c-43a9f0742b27",
                        "name": "1",
                        "label_coord": [
                            0.19149071019085823,
                            1.5
                        ],
                        "area": 9.0,
                        "width": 3.0,
                        "height": 3.0,
                        "assets": [],
                        "color": "#1C4C82",
                        "walls": [
                            {
                                "_id": "301fea91-4340-4f98-ba49-f50ad9bcb312",
                                "x1": 0.0,
                                "y1": 0.0,
                                "x2": 0.0,
                                "y2": 3.0,
                                "assets": []
                            },
                            {
                                "_id": "92bc6761-f9e2-4e9c-abd8-35e24a5ce2b9",
                                "x1": 0.0,
                                "y1": 3.0,
                                "x2": 3.0,
                                "y2": 3.0,
                                "assets": []
                            },
                            {
                                "_id": "b1f7b1ea-e489-4a87-9978-33dc0bc45885",
                                "x1": 3.0,
                                "y1": 3.0,
                                "x2": 3.0,
                                "y2": 0.0,
                                "assets": []
                            },
                            {
                                "_id": "5509918a-9ab7-4d5e-b3f4-dc0f117dd84c",
                                "x1": 3.0,
                                "y1": 0.0,
                                "x2": 0.0,
                                "y2": 0.0,
                                "assets": []
                            }
                        ],
                        "circular_coordinates": [
                            [
                                0.0,
                                0.0
                            ],
                            [
                                0.0,
                                3.0
                            ],
                            [
                                3.0,
                                3.0
                            ],
                            [
                                3.0,
                                0.0
                            ]
                        ]
                    },
                    {
                        "_id": "a3319031-7ad1-47d3-8463-8e0a71617069",
                        "name": "2",
                        "label_coord": [
                            3.191490710190858,
                            3.0
                        ],
                        "area": 12.0,
                        "width": 3.0,
                        "height": 4.0,
                        "assets": [],
                        "color": "#1C4C82",
                        "walls": [
                            {
                                "_id": "2ea2aded-67a5-404a-afc0-ee7f4f6b6995",
                                "x1": 3.0,
                                "y1": 1.0,
                                "x2": 3.0,
                                "y2": 5.0,
                                "assets": []
                            },
                            {
                                "_id": "4765fdbd-200c-4556-aedb-e9370165c735",
                                "x1": 3.0,
                                "y1": 5.0,
                                "x2": 6.0,
                                "y2": 5.0,
                                "assets": []
                            },
                            {
                                "_id": "50befdfe-3d4b-4388-a101-f88185dd59e4",
                                "x1": 6.0,
                                "y1": 5.0,
                                "x2": 6.0,
                                "y2": 1.0,
                                "assets": []
                            },
                            {
                                "_id": "ade1a9ff-cdd5-4b41-9fff-a00e2e5f413a",
                                "x1": 6.0,
                                "y1": 1.0,
                                "x2": 3.0,
                                "y2": 1.0,
                                "assets": []
                            }
                        ],
                        "circular_coordinates": [
                            [
                                3.0,
                                1.0
                            ],
                            [
                                3.0,
                                5.0
                            ],
                            [
                                6.0,
                                5.0
                            ],
                            [
                                6.0,
                                1.0
                            ]
                        ]
                    },
                    {
                        "_id": "53794824-c28b-48a6-a694-891bdc4be2c5",
                        "name": "3",
                        "label_coord": [
                            0.19149071019085823,
                            4.5
                        ],
                        "area": 9.0,
                        "width": 3.0,
                        "height": 3.0,
                        "assets": [],
                        "color": "#1C4C82",
                        "walls": [
                            {
                                "_id": "b439d7be-f0a6-484e-8eec-b82ddf49670c",
                                "x1": 0.0,
                                "y1": 3.0,
                                "x2": 0.0,
                                "y2": 6.0,
                                "assets": []
                            },
                            {
                                "_id": "a8285b46-96e6-435b-863a-d46ecb369f05",
                                "x1": 0.0,
                                "y1": 6.0,
                                "x2": 3.0,
                                "y2": 6.0,
                                "assets": []
                            },
                            {
                                "_id": "14bece9b-cacb-4318-8e35-98c4f7d40baf",
                                "x1": 3.0,
                                "y1": 6.0,
                                "x2": 3.0,
                                "y2": 3.0,
                                "assets": []
                            },
                            {
                                "_id": "37195b5f-ccb5-4207-90ea-85ea4ac6e88d",
                                "x1": 3.0,
                                "y1": 3.0,
                                "x2": 0.0,
                                "y2": 3.0,
                                "assets": []
                            }
                        ],
                        "circular_coordinates": [
                            [
                                0.0,
                                3.0
                            ],
                            [
                                0.0,
                                6.0
                            ],
                            [
                                3.0,
                                6.0
                            ],
                            [
                                3.0,
                                3.0
                            ]
                        ]
                    }
                ],
                [
                    {
                        "_id": "bccff5a0-4582-4432-b593-e5f65620d94f",
                        "name": "1",
                        "label_coord": [
                            0.19149071019085823,
                            1.5
                        ],
                        "area": 9.0,
                        "width": 3.0,
                        "height": 3.0,
                        "assets": [],
                        "color": "#1C4C82",
                        "walls": [
                            {
                                "_id": "50e78366-b172-4df4-a31a-9306d68fc355",
                                "x1": 0.0,
                                "y1": 0.0,
                                "x2": 0.0,
                                "y2": 3.0,
                                "assets": []
                            },
                            {
                                "_id": "72db705b-8f47-4706-b6bc-30f597382185",
                                "x1": 0.0,
                                "y1": 3.0,
                                "x2": 3.0,
                                "y2": 3.0,
                                "assets": []
                            },
                            {
                                "_id": "48e0eed6-3b98-4fcc-8125-2b3338cb9f58",
                                "x1": 3.0,
                                "y1": 3.0,
                                "x2": 3.0,
                                "y2": 0.0,
                                "assets": []
                            },
                            {
                                "_id": "536b78e9-40b4-42c2-ac3b-74a62c940fa9",
                                "x1": 3.0,
                                "y1": 0.0,
                                "x2": 0.0,
                                "y2": 0.0,
                                "assets": []
                            }
                        ],
                        "circular_coordinates": [
                            [
                                0.0,
                                0.0
                            ],
                            [
                                0.0,
                                3.0
                            ],
                            [
                                3.0,
                                3.0
                            ],
                            [
                                3.0,
                                0.0
                            ]
                        ]
                    },
                    {
                        "_id": "feb9f23d-d22b-4efe-9542-bd05a428717c",
                        "name": "2",
                        "label_coord": [
                            3.191490710190858,
                            1.5
                        ],
                        "area": 9.0,
                        "width": 3.0,
                        "height": 3.0,
                        "assets": [],
                        "color": "#1C4C82",
                        "walls": [
                            {
                                "_id": "eac6a290-4c42-4750-938c-9b6ff7c86fd5",
                                "x1": 3.0,
                                "y1": 0.0,
                                "x2": 3.0,
                                "y2": 3.0,
                                "assets": []
                            },
                            {
                                "_id": "49e27bdd-093f-4959-bc7d-796c48936684",
                                "x1": 3.0,
                                "y1": 3.0,
                                "x2": 6.0,
                                "y2": 3.0,
                                "assets": []
                            },
                            {
                                "_id": "8176e1b2-7b2f-45a3-b54d-4d75aeb2be41",
                                "x1": 6.0,
                                "y1": 3.0,
                                "x2": 6.0,
                                "y2": 0.0,
                                "assets": []
                            },
                            {
                                "_id": "8831ef9c-11d0-42fe-8050-8a19ed2cd71d",
                                "x1": 6.0,
                                "y1": 0.0,
                                "x2": 3.0,
                                "y2": 0.0,
                                "assets": []
                            }
                        ],
                        "circular_coordinates": [
                            [
                                3.0,
                                0.0
                            ],
                            [
                                3.0,
                                3.0
                            ],
                            [
                                6.0,
                                3.0
                            ],
                            [
                                6.0,
                                0.0
                            ]
                        ]
                    },
                    {
                        "_id": "b823a20f-a18b-4a71-ae21-1f35b990db0d",
                        "name": "3",
                        "label_coord": [
                            1.1914907101908583,
                            4.5
                        ],
                        "area": 12.0,
                        "width": 4.0,
                        "height": 3.0,
                        "assets": [],
                        "color": "#1C4C82",
                        "walls": [
                            {
                                "_id": "4eefbcbd-c6ea-4107-9d66-7a0d14f6f5c5",
                                "x1": 1.0,
                                "y1": 3.0,
                                "x2": 1.0,
                                "y2": 6.0,
                                "assets": []
                            },
                            {
                                "_id": "175e55f3-0a22-4011-987b-e6fe70e0839a",
                                "x1": 1.0,
                                "y1": 6.0,
                                "x2": 5.0,
                                "y2": 6.0,
                                "assets": []
                            },
                            {
                                "_id": "bec8349a-6500-46f3-91f6-89274db28287",
                                "x1": 5.0,
                                "y1": 6.0,
                                "x2": 5.0,
                                "y2": 3.0,
                                "assets": []
                            },
                            {
                                "_id": "7a337fa4-14bf-4907-b38a-bb1065420584",
                                "x1": 5.0,
                                "y1": 3.0,
                                "x2": 1.0,
                                "y2": 3.0,
                                "assets": []
                            }
                        ],
                        "circular_coordinates": [
                            [
                                1.0,
                                3.0
                            ],
                            [
                                1.0,
                                6.0
                            ],
                            [
                                5.0,
                                6.0
                            ],
                            [
                                5.0,
                                3.0
                            ]
                        ]
                    }
                ],
            ]
        }
    }
}
```


///
