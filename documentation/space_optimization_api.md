# Space Optimization API

LINK: [https://api.gplan.in/api/generate/space-optimized](https://api.gplan.in/api/generate/space-optimized)

Generates an optimized floorplan by placing rooms within a given boundary or set of regions, while satisfying adjacency and non-adjacency requirements.

### Features

- **Boundary Support**: Provide a polygonal boundary that automatically converts to rectangular regions
- **Region-Based Layout**: Define rectangular regions for flexible floor shapes (L-shapes, irregular plots)
- **Fixed Rooms**: Place immovable rooms (staircases, lifts, ducts) that other rooms work around
- **Adjacency Constraints**: Ensure specific rooms are adjacent (e.g., Bedroom-Bathroom)
- **Non-Adjacency Constraints**: Prevent specific rooms from being adjacent
- **Room Expansion**: Automatically expand rooms to utilize available space
- **Compaction**: Remove gaps between rooms for efficient layouts

### Fields

/// tab | Request

`request_id : string`

: Unique identifier for the request

`engine : string`

: Must be set to `"FloorPlan"` for space optimization

`params : object`

: Parameters object containing:

- `boundary : array[[x, y]] (optional)`
  : List of [x, y] coordinate pairs defining a polygonal boundary. The API automatically converts this to rectangular regions. Use this OR `regions`, not both.

  Example: `[[0, 0], [40, 0], [40, 24], [20, 24], [20, 32], [0, 32]]` for an L-shape

- `regions : array[region] (optional)`
  : List of rectangular region objects. Use this OR `boundary`, not both.

  Each region:

  - `x : int` - X coordinate of region
  - `y : int` - Y coordinate of region
  - `width : int` - Width of region
  - `height : int` - Height of region

- `rooms : array[room]`
  : List of room objects to place in the floorplan

  Each room:

  - `name : string` - Name/label of the room
  - `width : int` - Minimum width of the room
  - `height : int` - Minimum height of the room
  - `max_expansion : int` - Maximum units the room can expand (optional, default: 0)

- `fixed_rooms : array[fixed_room] (optional)`
  : List of fixed (immovable) room objects

  Each fixed room:

  - `name : string` - Name of the fixed room
  - `x : int` - X coordinate
  - `y : int` - Y coordinate
  - `width : int` - Width
  - `height : int` - Height
  - `is_fixed : bool` - Must be `true`
  - `max_expansion : int` - Usually `0` for fixed rooms

- `adjacency : array[[room1, room2]] (optional)`
  : List of room pairs that should be adjacent

  Example: `[["Living", "Dining"], ["Bedroom1", "Bathroom1"]]`

- `non_adjacency : array[[room1, room2]] (optional)`
  : List of room pairs that should NOT be adjacent

  Example: `[["Kitchen", "Bathroom"], ["Living", "Bedroom"]]`

- `entrance_coords : array[[x1, y1], [x2, y2]] (optional)`
  : Entrance location as two coordinate points defining a line segment

- `max_attempts : int (optional)`
  : Maximum placement attempts (default: 100)

`ops : array[string]`

: Operations to perform, can include:

- `"place"` - Place rooms in the layout
- `"compact"` - Remove gaps between rooms
- `"expand"` - Expand rooms to fill available space
- `"score"` - Calculate adjacency scores and metrics

///

/// tab | Response

`request_id : string`
: Echo of the request identifier

`status : string`
: Status of the request: `"ok"` for success, `"error"` for failure

`data : object`

- `floor : object`
  : Information about the floor layout

  - `width : int` - Total width of the floor
  - `height : int` - Total height of the floor
  - `regions : array[region]` - List of rectangular regions
  - `entrance_coords : array` - Entrance coordinates

- `placements : array[placement]`
  : List of placed room objects

  Each placement:

  - `name : string` - Room name
  - `x : int` - X coordinate of placed room
  - `y : int` - Y coordinate of placed room
  - `width : int` - Final width of room (after expansion)
  - `height : int` - Final height of room (after expansion)
  - `area : int` - Total area of the room
  - `is_fixed : bool` - Whether the room is fixed
  - `rotated : bool` - Whether the room was rotated during placement

- `metrics : object`
  : Performance metrics for the generated layout
  - `ops_run : array[string]` - Operations that were executed
  - `adjacency_score : float` - Percentage of adjacency constraints satisfied (0.0 to 1.0)
  - `satisfied_pairs : array[[room1, room2]]` - Adjacency pairs that were satisfied
  - `non_adjacency_violations : array[[room1, room2]]` - Non-adjacency violations
  - `entrance_adjacent_rooms : array[string]` - Rooms adjacent to entrance
  - `area_utilization : object`
    - `total_region_area : int` - Total area of all regions
    - `occupied_room_area : int` - Area occupied by movable rooms
    - `occupied_fixed_area : int` - Area occupied by fixed rooms
    - `occupied_total_area : int` - Total occupied area
    - `remaining_area : int` - Remaining unused area
    - `utilization_ratio : float` - Percentage of area utilized (0.0 to 1.0)
  - `integrity : object`
    - `overlaps : array` - List of overlapping rooms (should be empty)
    - `out_of_bounds : array` - Rooms outside regions (should be empty)
    - `invalid_adjacent_edges : array` - Invalid adjacencies

`error : object`
: Error details if status is "error"

- `message : string` - Error message

///

## Examples

/// tab | Request (L-Shape with Boundary)

**L-Shaped Apartment Floor Plan**

This example uses a boundary polygon to define an L-shaped plot:

```
   40 units wide
   ┌─────────────────────┐
   │                     │ 24 units
   │     Main Area       │
   │                     │
 0 └──────┬──────────────┘
   │      │
   │ Ext  │ 8 units (extension)
   │      │
   └──────┘
   20 units wide
   Total height: 32 units
```

The boundary automatically converts to rectangular regions.

///

/// tab | Python

```python
import requests

url = "https://api.gplan.in/api/generate/space_optimization"

headers = {
    "accept": "application/json",
    "content-type": "application/json",
    "Authorization": "Api-Key <YOUR_API_KEY>"
}

body = {
    "request_id": "req_lshape_apartment_001",
    "engine": "FloorPlan",
    "params": {
        "boundary": [
            [0, 0],
            [40, 0],
            [40, 24],
            [20, 24],
            [20, 32],
            [0, 32]
        ],
        "fixed_rooms": [
            {
                "name": "Staircase",
                "x": 32,
                "y": 0,
                "width": 8,
                "height": 12,
                "is_fixed": True,
                "max_expansion": 0
            },
            {
                "name": "Lift",
                "x": 28,
                "y": 0,
                "width": 4,
                "height": 6,
                "is_fixed": True,
                "max_expansion": 0
            },
            {
                "name": "Duct",
                "x": 0,
                "y": 24,
                "width": 4,
                "height": 8,
                "is_fixed": True,
                "max_expansion": 0
            }
        ],
        "rooms": [
            {"name": "Living", "width": 16, "height": 10, "max_expansion": 6},
            {"name": "Dining", "width": 10, "height": 8, "max_expansion": 4},
            {"name": "Kitchen", "width": 8, "height": 7, "max_expansion": 3},
            {"name": "Bedroom1", "width": 12, "height": 10, "max_expansion": 5},
            {"name": "Bedroom2", "width": 12, "height": 10, "max_expansion": 5},
            {"name": "Bathroom1", "width": 6, "height": 6, "max_expansion": 2},
            {"name": "Bathroom2", "width": 6, "height": 6, "max_expansion": 2},
            {"name": "Utility", "width": 6, "height": 6, "max_expansion": 2},
            {"name": "Balcony", "width": 8, "height": 4, "max_expansion": 2}
        ],
        "adjacency": [
            ["Living", "Dining"],
            ["Dining", "Kitchen"],
            ["Bedroom1", "Bathroom1"],
            ["Bedroom2", "Bathroom2"],
            ["Kitchen", "Utility"]
        ],
        "non_adjacency": [
            ["Bedroom1", "Lift"],
            ["Bedroom2", "Lift"],
            ["Kitchen", "Bathroom2"],
            ["Living", "Bathroom1"]
        ],
        "entrance_coords": [
            [0, 10],
            [0, 14]
        ],
        "max_attempts": 1000
    },
    "ops": ["place", "compact", "expand", "score"]
}

response = requests.post(url, headers=headers, json=body)
print(response.json())
```

///

/// tab | cURL

```sh
curl -X POST "https://api.gplan.in/api/generate/space_optimization" \
     -H "accept: application/json" \
     -H "content-type: application/json" \
     -H "Authorization: Api-Key <YOUR_API_KEY>" \
     -d '{
  "request_id": "req_lshape_apartment_001",
  "engine": "FloorPlan",
  "params": {
    "boundary": [
      [0, 0],
      [40, 0],
      [40, 24],
      [20, 24],
      [20, 32],
      [0, 32]
    ],
    "fixed_rooms": [
      {
        "name": "Staircase",
        "x": 32,
        "y": 0,
        "width": 8,
        "height": 12,
        "is_fixed": true,
        "max_expansion": 0
      },
      {
        "name": "Lift",
        "x": 28,
        "y": 0,
        "width": 4,
        "height": 6,
        "is_fixed": true,
        "max_expansion": 0
      },
      {
        "name": "Duct",
        "x": 0,
        "y": 24,
        "width": 4,
        "height": 8,
        "is_fixed": true,
        "max_expansion": 0
      }
    ],
    "rooms": [
      {"name": "Living", "width": 16, "height": 10, "max_expansion": 6},
      {"name": "Dining", "width": 10, "height": 8, "max_expansion": 4},
      {"name": "Kitchen", "width": 8, "height": 7, "max_expansion": 3},
      {"name": "Bedroom1", "width": 12, "height": 10, "max_expansion": 5},
      {"name": "Bedroom2", "width": 12, "height": 10, "max_expansion": 5},
      {"name": "Bathroom1", "width": 6, "height": 6, "max_expansion": 2},
      {"name": "Bathroom2", "width": 6, "height": 6, "max_expansion": 2},
      {"name": "Utility", "width": 6, "height": 6, "max_expansion": 2},
      {"name": "Balcony", "width": 8, "height": 4, "max_expansion": 2}
    ],
    "adjacency": [
      ["Living", "Dining"],
      ["Dining", "Kitchen"],
      ["Bedroom1", "Bathroom1"],
      ["Bedroom2", "Bathroom2"],
      ["Kitchen", "Utility"]
    ],
    "non_adjacency": [
      ["Bedroom1", "Lift"],
      ["Bedroom2", "Lift"],
      ["Kitchen", "Bathroom2"],
      ["Living", "Bathroom1"]
    ],
    "entrance_coords": [
      [0, 10],
      [0, 14]
    ],
    "max_attempts": 1000
  },
  "ops": ["place", "compact", "expand", "score"]
}'
```

///

/// tab | Response

```json
{
  "request_id": "req_lshape_apartment_001",
  "status": "ok",
  "data": {
    "floor": {
      "width": 40,
      "height": 32,
      "regions": [
        {
          "x": 0,
          "y": 0,
          "width": 40,
          "height": 24
        },
        {
          "x": 0,
          "y": 24,
          "width": 20,
          "height": 8
        }
      ],
      "entrance_coords": [
        [0, 10],
        [0, 14]
      ]
    },
    "placements": [
      {
        "name": "Staircase",
        "x": 32,
        "y": 0,
        "width": 8,
        "height": 12,
        "area": 96,
        "is_fixed": true,
        "rotated": false
      },
      {
        "name": "Lift",
        "x": 28,
        "y": 0,
        "width": 4,
        "height": 6,
        "area": 24,
        "is_fixed": true,
        "rotated": false
      },
      {
        "name": "Duct",
        "x": 0,
        "y": 24,
        "width": 4,
        "height": 8,
        "area": 32,
        "is_fixed": true,
        "rotated": false
      },
      {
        "name": "Living",
        "x": 0,
        "y": 0,
        "width": 20,
        "height": 12,
        "area": 240,
        "is_fixed": false,
        "rotated": false
      },
      {
        "name": "Dining",
        "x": 20,
        "y": 0,
        "width": 8,
        "height": 12,
        "area": 96,
        "is_fixed": false,
        "rotated": false
      },
      {
        "name": "Kitchen",
        "x": 20,
        "y": 12,
        "width": 8,
        "height": 12,
        "area": 96,
        "is_fixed": false,
        "rotated": false
      },
      {
        "name": "Bedroom1",
        "x": 0,
        "y": 12,
        "width": 12,
        "height": 12,
        "area": 144,
        "is_fixed": false,
        "rotated": false
      },
      {
        "name": "Bathroom1",
        "x": 12,
        "y": 12,
        "width": 8,
        "height": 8,
        "area": 64,
        "is_fixed": false,
        "rotated": false
      },
      {
        "name": "Bedroom2",
        "x": 4,
        "y": 24,
        "width": 12,
        "height": 8,
        "area": 96,
        "is_fixed": false,
        "rotated": false
      },
      {
        "name": "Bathroom2",
        "x": 16,
        "y": 24,
        "width": 4,
        "height": 8,
        "area": 32,
        "is_fixed": false,
        "rotated": false
      },
      {
        "name": "Utility",
        "x": 12,
        "y": 20,
        "width": 8,
        "height": 4,
        "area": 32,
        "is_fixed": false,
        "rotated": false
      },
      {
        "name": "Balcony",
        "x": 28,
        "y": 12,
        "width": 4,
        "height": 12,
        "area": 48,
        "is_fixed": false,
        "rotated": false
      }
    ],
    "metrics": {
      "ops_run": ["place", "compact", "expand", "score"],
      "adjacency_score": 1.0,
      "satisfied_pairs": [
        ["Living", "Dining"],
        ["Dining", "Kitchen"],
        ["Bedroom1", "Bathroom1"],
        ["Bedroom2", "Bathroom2"],
        ["Kitchen", "Utility"]
      ],
      "non_adjacency_violations": [],
      "entrance_adjacent_rooms": ["Living"],
      "area_utilization": {
        "total_region_area": 1120,
        "occupied_room_area": 848,
        "occupied_fixed_area": 152,
        "occupied_total_area": 1000,
        "remaining_area": 120,
        "utilization_ratio": 0.893
      },
      "integrity": {
        "overlaps": [],
        "out_of_bounds": [],
        "invalid_adjacent_edges": []
      }
    }
  },
  "error": {}
}
```

///

## Additional Examples

### Simple Rectangular Plot

For a simple rectangular plot, you can use boundary:

```python
"boundary": [
    [0, 0],
    [30, 0],
    [30, 20],
    [0, 20]
]
```

Or use regions directly:

```python
"regions": [
    {"x": 0, "y": 0, "width": 30, "height": 20}
]
```

### Complex Irregular Shape

For complex shapes, define the boundary as a polygon:

```python
"boundary": [
    [0, 0], [50, 0], [50, 30],
    [30, 30], [30, 40], [0, 40]
]
```

The API automatically decomposes it into optimal rectangular regions.

## Notes

- **Boundary vs Regions**: Use `boundary` for irregular plots (the API auto-converts to regions). Use `regions` for precise control over region placement.
- **Fixed Rooms**: Always set `is_fixed: true` and typically `max_expansion: 0` for immovable elements like staircases, lifts, and ducts.
- **Adjacency**: The algorithm attempts to satisfy adjacency constraints but may not always achieve 100% depending on room sizes and plot shape.
- **Expansion**: Rooms with `max_expansion > 0` will automatically grow to fill available space after initial placement.
- **Operations Order**: The recommended ops order is `["place", "compact", "expand", "score"]` for optimal results.
