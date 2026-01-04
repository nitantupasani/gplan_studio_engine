# GA Optimization API (Genetic Algorithm)

LINK: [https://api.gplan.in/api/generate/ga-optimized](https://api.gplan.in/api/generate/ga-optimized)

Generates an optimized floorplan using a genetic algorithm (GA) that automatically creates corridors to connect rooms. This engine is ideal for complex floorplans where rooms need to maintain their adjacency relationships through a corridor system.

### Features

- **Genetic Algorithm Optimization**: Uses evolutionary algorithms to find optimal room arrangements
- **Automatic Corridor Generation**: Creates corridors to connect rooms based on adjacency defined by shared walls
- **Customizable GA Parameters**: Control population size, generations, and mutation rate
- **Wall-Based Adjacency**: Rooms sharing walls are automatically considered adjacent through corridors
- **2-3 Minute Execution Time**: Complex optimization runs in 2-3 minutes

### Fields

/// tab | Request

`request_id : string`

: Unique identifier for the request

`engine : string`

: Must be set to `"GA_FloorPlan"` for genetic algorithm optimization

`params : object`

: Parameters object containing:

- `plot_width : int`
  : Width of the overall rectangular plot

- `plot_height : int`
  : Height of the overall rectangular plot

- `corridor_width : int (optional)`
  : Width of corridors to be generated (default: 3)

- `rooms : array[room]`
  : List of room objects with their wall definitions

  Each room:

  - `id : string` - Unique room identifier
  - `name : string` - Room name/label
  - `color : string` - Hex color code for visualization (e.g., "#FFE5B4")
  - `walls : array[wall]` - List of walls defining the room boundary

  Each wall:

  - `id : string` - Unique wall identifier
  - `roomIds : array[string]` - IDs of rooms sharing this wall (1 room = exterior wall, 2 rooms = shared wall)
  - `x1 : number` - X coordinate of wall start point
  - `y1 : number` - Y coordinate of wall start point
  - `x2 : number` - X coordinate of wall end point
  - `y2 : number` - Y coordinate of wall end point

- `walls : array[wall]`
  : Complete list of all walls in the floorplan (flattened from all rooms)

- `labels : array[label] (optional)`
  : List of label objects for room names

  Each label:

  - `x : number` - X coordinate of label
  - `y : number` - Y coordinate of label
  - `text : string` - Label text (room name)
  - `roomId : string` - ID of the room this label belongs to

- `windows : array[window] (optional)`
  : List of window objects (optional, default: [])

- `doors : array[door] (optional)`
  : List of door objects (optional, default: [])

- `ga_config : object (optional)`
  : Genetic algorithm configuration
  - `population_size : int` - Size of population per generation (default: 200)
  - `num_generations : int` - Number of generations to evolve (default: 600)
  - `mutation_rate : float` - Probability of mutation (default: 0.1)

///

/// tab | Response

`request_id : string`
: Echo of the request identifier

`status : string`
: Status of the request: `"success"` for success, `"error"` for failure

`engine : string`
: Echo of the engine used: `"GA_FloorPlan"`

`data : object`

- `floor : object`
  : Information about the floor plot

  - `plot_width : int` - Width of the plot
  - `plot_height : int` - Height of the plot

- `ga_optimization : object`
  : Information about the genetic algorithm optimization

  - `status : string` - Optimization status (e.g., "converged")
  - `solution_chromosome : string` - The chromosome representing the best solution found

- `rooms : array[room]`
  : List of optimized room objects with their bounds

  Each room:

  - `id : string` - Room identifier
  - `name : string` - Room name
  - `color : string` - Room color
  - `optimized_bounds : object` - Optimized position and dimensions
    - `x : number` - X coordinate
    - `y : number` - Y coordinate
    - `width : number` - Width
    - `height : number` - Height
  - `walls : array[wall]` - Updated wall positions

- `walls : array[wall]`
  : Complete list of all walls with optimized positions

- `labels : array[label]`
  : Updated label positions

- `windows : array[window]`
  : Window objects (if provided in request)

- `doors : array[door]`
  : Door objects (if provided in request)

- `layout_matrix : array[array[int]]`
  : 2D matrix representation of the layout where:
  - `0` = empty/corridor space
  - `1` = room 1 boundary
  - `2` = room 2 boundary
  - `3` = room 3 boundary
  - etc.

`error : object`
: Error details if status is "error"

- `message : string` - Error message

///

## Examples

/// tab | Request (4-Room Apartment)

**4-Room Apartment with Shared Walls**

This example defines 4 rooms:

- Living Room (12×6) - adjacent to Kitchen
- Kitchen (8×6) - adjacent to Living and Bathroom
- Bedroom (10×10)
- Bathroom (6×6) - adjacent to Kitchen

Rooms sharing walls (e.g., Living-Kitchen wall "wall-003") will be connected via corridors.

///

/// tab | Python

```python
import requests

url = "https://api.gplan.in/api/generate/ga_optimization"

headers = {
    "accept": "application/json",
    "content-type": "application/json",
    "Authorization": "Api-Key <YOUR_API_KEY>"
}

body = {
    "request_id": "req_ga_001",
    "engine": "GA_FloorPlan",
    "params": {
        "plot_width": 40,
        "plot_height": 30,
        "corridor_width": 3,
        "ga_config": {
            "population_size": 200,
            "num_generations": 600,
            "mutation_rate": 0.1
        },
        "rooms": [
            {
                "id": "room-living-001",
                "name": "Living Room",
                "color": "#FFE5B4",
                "walls": [
                    {
                        "id": "wall-001",
                        "roomIds": ["room-living-001"],
                        "x1": 0, "y1": 0, "x2": 0, "y2": 10
                    },
                    {
                        "id": "wall-002",
                        "roomIds": ["room-living-001"],
                        "x1": 0, "y1": 10, "x2": 12, "y2": 10
                    },
                    {
                        "id": "wall-003",
                        "roomIds": ["room-living-001", "room-kitchen-002"],
                        "x1": 12, "y1": 10, "x2": 12, "y2": 4
                    },
                    {
                        "id": "wall-004",
                        "roomIds": ["room-living-001"],
                        "x1": 12, "y1": 4, "x2": 0, "y2": 4
                    },
                    {
                        "id": "wall-005",
                        "roomIds": ["room-living-001"],
                        "x1": 0, "y1": 4, "x2": 0, "y2": 0
                    }
                ]
            },
            {
                "id": "room-kitchen-002",
                "name": "Kitchen",
                "color": "#B4D7FF",
                "walls": [
                    {
                        "id": "wall-003",
                        "roomIds": ["room-living-001", "room-kitchen-002"],
                        "x1": 12, "y1": 10, "x2": 12, "y2": 4
                    },
                    {
                        "id": "wall-006",
                        "roomIds": ["room-kitchen-002"],
                        "x1": 12, "y1": 4, "x2": 20, "y2": 4
                    },
                    {
                        "id": "wall-007",
                        "roomIds": ["room-kitchen-002"],
                        "x1": 20, "y1": 4, "x2": 20, "y2": 10
                    },
                    {
                        "id": "wall-008",
                        "roomIds": ["room-kitchen-002"],
                        "x1": 20, "y1": 10, "x2": 12, "y2": 10
                    }
                ]
            },
            {
                "id": "room-bedroom-003",
                "name": "Bedroom",
                "color": "#FFB4E5",
                "walls": [
                    {
                        "id": "wall-009",
                        "roomIds": ["room-bedroom-003"],
                        "x1": 0, "y1": 10, "x2": 0, "y2": 20
                    },
                    {
                        "id": "wall-010",
                        "roomIds": ["room-bedroom-003"],
                        "x1": 0, "y1": 20, "x2": 10, "y2": 20
                    },
                    {
                        "id": "wall-011",
                        "roomIds": ["room-bedroom-003"],
                        "x1": 10, "y1": 20, "x2": 10, "y2": 10
                    },
                    {
                        "id": "wall-012",
                        "roomIds": ["room-bedroom-003"],
                        "x1": 10, "y1": 10, "x2": 0, "y2": 10
                    }
                ]
            },
            {
                "id": "room-bathroom-004",
                "name": "Bathroom",
                "color": "#B4FFE5",
                "walls": [
                    {
                        "id": "wall-013",
                        "roomIds": ["room-bathroom-004"],
                        "x1": 10, "y1": 10, "x2": 10, "y2": 16
                    },
                    {
                        "id": "wall-014",
                        "roomIds": ["room-bathroom-004"],
                        "x1": 10, "y1": 16, "x2": 16, "y2": 16
                    },
                    {
                        "id": "wall-015",
                        "roomIds": ["room-bathroom-004"],
                        "x1": 16, "y1": 16, "x2": 16, "y2": 10
                    },
                    {
                        "id": "wall-016",
                        "roomIds": ["room-bathroom-004"],
                        "x1": 16, "y1": 10, "x2": 10, "y2": 10
                    }
                ]
            }
        ],
        "walls": [
            {"id": "wall-001", "roomIds": ["room-living-001"], "x1": 0, "y1": 0, "x2": 0, "y2": 10},
            {"id": "wall-002", "roomIds": ["room-living-001"], "x1": 0, "y1": 10, "x2": 12, "y2": 10},
            {"id": "wall-003", "roomIds": ["room-living-001", "room-kitchen-002"], "x1": 12, "y1": 10, "x2": 12, "y2": 4},
            {"id": "wall-004", "roomIds": ["room-living-001"], "x1": 12, "y1": 4, "x2": 0, "y2": 4}
        ],
        "labels": [
            {"x": 6, "y": 7, "text": "Living Room", "roomId": "room-living-001"},
            {"x": 16, "y": 7, "text": "Kitchen", "roomId": "room-kitchen-002"},
            {"x": 5, "y": 15, "text": "Bedroom", "roomId": "room-bedroom-003"},
            {"x": 13, "y": 13, "text": "Bathroom", "roomId": "room-bathroom-004"}
        ],
        "windows": [],
        "doors": []
    }
}

response = requests.post(url, headers=headers, json=body)
print(response.json())

# Note: This API takes 2-3 minutes to complete due to GA optimization
```

///

/// tab | cURL

```sh
curl -X POST "https://api.gplan.in/api/generate/ga_optimization" \
     -H "accept: application/json" \
     -H "content-type: application/json" \
     -H "Authorization: Api-Key <YOUR_API_KEY>" \
     -d '{
  "request_id": "req_ga_001",
  "engine": "GA_FloorPlan",
  "params": {
    "plot_width": 40,
    "plot_height": 30,
    "corridor_width": 3,
    "ga_config": {
      "population_size": 200,
      "num_generations": 600,
      "mutation_rate": 0.1
    },
    "rooms": [
      {
        "id": "room-living-001",
        "name": "Living Room",
        "color": "#FFE5B4",
        "walls": [
          {"id": "wall-001", "roomIds": ["room-living-001"], "x1": 0, "y1": 0, "x2": 0, "y2": 10},
          {"id": "wall-002", "roomIds": ["room-living-001"], "x1": 0, "y1": 10, "x2": 12, "y2": 10},
          {"id": "wall-003", "roomIds": ["room-living-001", "room-kitchen-002"], "x1": 12, "y1": 10, "x2": 12, "y2": 4},
          {"id": "wall-004", "roomIds": ["room-living-001"], "x1": 12, "y1": 4, "x2": 0, "y2": 4},
          {"id": "wall-005", "roomIds": ["room-living-001"], "x1": 0, "y1": 4, "x2": 0, "y2": 0}
        ]
      },
      {
        "id": "room-kitchen-002",
        "name": "Kitchen",
        "color": "#B4D7FF",
        "walls": [
          {"id": "wall-003", "roomIds": ["room-living-001", "room-kitchen-002"], "x1": 12, "y1": 10, "x2": 12, "y2": 4},
          {"id": "wall-006", "roomIds": ["room-kitchen-002"], "x1": 12, "y1": 4, "x2": 20, "y2": 4},
          {"id": "wall-007", "roomIds": ["room-kitchen-002"], "x1": 20, "y1": 4, "x2": 20, "y2": 10},
          {"id": "wall-008", "roomIds": ["room-kitchen-002"], "x1": 20, "y1": 10, "x2": 12, "y2": 10}
        ]
      },
      {
        "id": "room-bedroom-003",
        "name": "Bedroom",
        "color": "#FFB4E5",
        "walls": [
          {"id": "wall-009", "roomIds": ["room-bedroom-003"], "x1": 0, "y1": 10, "x2": 0, "y2": 20},
          {"id": "wall-010", "roomIds": ["room-bedroom-003"], "x1": 0, "y1": 20, "x2": 10, "y2": 20},
          {"id": "wall-011", "roomIds": ["room-bedroom-003"], "x1": 10, "y1": 20, "x2": 10, "y2": 10},
          {"id": "wall-012", "roomIds": ["room-bedroom-003"], "x1": 10, "y1": 10, "x2": 0, "y2": 10}
        ]
      },
      {
        "id": "room-bathroom-004",
        "name": "Bathroom",
        "color": "#B4FFE5",
        "walls": [
          {"id": "wall-013", "roomIds": ["room-bathroom-004"], "x1": 10, "y1": 10, "x2": 10, "y2": 16},
          {"id": "wall-014", "roomIds": ["room-bathroom-004"], "x1": 10, "y1": 16, "x2": 16, "y2": 16},
          {"id": "wall-015", "roomIds": ["room-bathroom-004"], "x1": 16, "y1": 16, "x2": 16, "y2": 10},
          {"id": "wall-016", "roomIds": ["room-bathroom-004"], "x1": 16, "y1": 10, "x2": 10, "y2": 10}
        ]
      }
    ],
    "walls": [
      {"id": "wall-001", "roomIds": ["room-living-001"], "x1": 0, "y1": 0, "x2": 0, "y2": 10},
      {"id": "wall-002", "roomIds": ["room-living-001"], "x1": 0, "y1": 10, "x2": 12, "y2": 10},
      {"id": "wall-003", "roomIds": ["room-living-001", "room-kitchen-002"], "x1": 12, "y1": 10, "x2": 12, "y2": 4},
      {"id": "wall-004", "roomIds": ["room-living-001"], "x1": 12, "y1": 4, "x2": 0, "y2": 4}
    ],
    "labels": [
      {"x": 6, "y": 7, "text": "Living Room", "roomId": "room-living-001"},
      {"x": 16, "y": 7, "text": "Kitchen", "roomId": "room-kitchen-002"},
      {"x": 5, "y": 15, "text": "Bedroom", "roomId": "room-bedroom-003"},
      {"x": 13, "y": 13, "text": "Bathroom", "roomId": "room-bathroom-004"}
    ],
    "windows": [],
    "doors": []
  }
}'

# Note: This API takes 2-3 minutes to complete due to GA optimization
```

///

/// tab | Response

```json
{
  "request_id": "req_ga_001",
  "status": "success",
  "engine": "GA_FloorPlan",
  "data": {
    "floor": {
      "plot_width": 40,
      "plot_height": 30
    },
    "ga_optimization": {
      "status": "converged",
      "solution_chromosome": "0123213021"
    },
    "rooms": [
      {
        "id": "room-living-001",
        "name": "Living Room",
        "color": "#FFE5B4",
        "optimized_bounds": {
          "x": 5,
          "y": 3,
          "width": 12,
          "height": 8
        },
        "walls": [
          {
            "id": "wall-001",
            "roomIds": ["room-living-001"],
            "x1": 5,
            "y1": 3,
            "x2": 5,
            "y2": 11
          },
          {
            "id": "wall-002",
            "roomIds": ["room-living-001"],
            "x1": 5,
            "y1": 11,
            "x2": 17,
            "y2": 11
          },
          {
            "id": "wall-003",
            "roomIds": ["room-living-001", "room-kitchen-002"],
            "x1": 17,
            "y1": 11,
            "x2": 17,
            "y2": 3
          },
          {
            "id": "wall-004",
            "roomIds": ["room-living-001"],
            "x1": 17,
            "y1": 3,
            "x2": 5,
            "y2": 3
          }
        ]
      },
      {
        "id": "room-kitchen-002",
        "name": "Kitchen",
        "color": "#B4D7FF",
        "optimized_bounds": {
          "x": 20,
          "y": 3,
          "width": 8,
          "height": 8
        },
        "walls": [
          {
            "id": "wall-006",
            "roomIds": ["room-kitchen-002"],
            "x1": 20,
            "y1": 3,
            "x2": 20,
            "y2": 11
          },
          {
            "id": "wall-007",
            "roomIds": ["room-kitchen-002"],
            "x1": 20,
            "y1": 11,
            "x2": 28,
            "y2": 11
          },
          {
            "id": "wall-008",
            "roomIds": ["room-kitchen-002"],
            "x1": 28,
            "y1": 11,
            "x2": 28,
            "y2": 3
          },
          {
            "id": "wall-009",
            "roomIds": ["room-kitchen-002"],
            "x1": 28,
            "y1": 3,
            "x2": 20,
            "y2": 3
          }
        ]
      },
      {
        "id": "room-bedroom-003",
        "name": "Bedroom",
        "color": "#FFB4E5",
        "optimized_bounds": {
          "x": 5,
          "y": 14,
          "width": 10,
          "height": 10
        },
        "walls": [
          {
            "id": "wall-010",
            "roomIds": ["room-bedroom-003"],
            "x1": 5,
            "y1": 14,
            "x2": 5,
            "y2": 24
          },
          {
            "id": "wall-011",
            "roomIds": ["room-bedroom-003"],
            "x1": 5,
            "y1": 24,
            "x2": 15,
            "y2": 24
          },
          {
            "id": "wall-012",
            "roomIds": ["room-bedroom-003"],
            "x1": 15,
            "y1": 24,
            "x2": 15,
            "y2": 14
          },
          {
            "id": "wall-013",
            "roomIds": ["room-bedroom-003"],
            "x1": 15,
            "y1": 14,
            "x2": 5,
            "y2": 14
          }
        ]
      },
      {
        "id": "room-bathroom-004",
        "name": "Bathroom",
        "color": "#B4FFE5",
        "optimized_bounds": {
          "x": 18,
          "y": 14,
          "width": 6,
          "height": 6
        },
        "walls": [
          {
            "id": "wall-014",
            "roomIds": ["room-bathroom-004"],
            "x1": 18,
            "y1": 14,
            "x2": 18,
            "y2": 20
          },
          {
            "id": "wall-015",
            "roomIds": ["room-bathroom-004"],
            "x1": 18,
            "y1": 20,
            "x2": 24,
            "y2": 20
          },
          {
            "id": "wall-016",
            "roomIds": ["room-bathroom-004"],
            "x1": 24,
            "y1": 20,
            "x2": 24,
            "y2": 14
          },
          {
            "id": "wall-017",
            "roomIds": ["room-bathroom-004"],
            "x1": 24,
            "y1": 14,
            "x2": 18,
            "y2": 14
          }
        ]
      }
    ],
    "walls": [
      {
        "id": "wall-001",
        "roomIds": ["room-living-001"],
        "x1": 5,
        "y1": 3,
        "x2": 5,
        "y2": 11
      },
      {
        "id": "wall-002",
        "roomIds": ["room-living-001"],
        "x1": 5,
        "y1": 11,
        "x2": 17,
        "y2": 11
      },
      {
        "id": "wall-003",
        "roomIds": ["room-living-001", "room-kitchen-002"],
        "x1": 17,
        "y1": 11,
        "x2": 17,
        "y2": 3
      },
      {
        "id": "wall-004",
        "roomIds": ["room-living-001"],
        "x1": 17,
        "y1": 3,
        "x2": 5,
        "y2": 3
      }
    ],
    "labels": [
      { "x": 11, "y": 7, "text": "Living Room", "roomId": "room-living-001" },
      { "x": 24, "y": 7, "text": "Kitchen", "roomId": "room-kitchen-002" },
      { "x": 10, "y": 19, "text": "Bedroom", "roomId": "room-bedroom-003" },
      { "x": 21, "y": 17, "text": "Bathroom", "roomId": "room-bathroom-004" }
    ],
    "windows": [],
    "doors": [],
    "layout_matrix": [
      [
        0, 0, 0, 0, 0, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0, 0, 0, 2, 2, 2, 2,
        2, 2, 2, 2, 0, 0
      ],
      [
        0, 0, 0, 0, 0, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0, 0, 0, 2, 2, 2, 2,
        2, 2, 2, 2, 0, 0
      ],
      [
        0, 0, 0, 0, 0, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0, 0, 0, 2, 2, 2, 2,
        2, 2, 2, 2, 0, 0
      ],
      [
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 0, 0, 0, 0
      ],
      [
        0, 0, 0, 0, 0, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 0, 0, 0, 4, 4, 4, 4, 4, 4,
        0, 0, 0, 0, 0, 0
      ],
      [
        0, 0, 0, 0, 0, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 0, 0, 0, 4, 4, 4, 4, 4, 4,
        0, 0, 0, 0, 0, 0
      ]
    ]
  },
  "error": {}
}
```

**Layout Matrix Explanation:**

- `0` represents corridor space
- `1` represents Living Room boundaries
- `2` represents Kitchen boundaries
- `3` represents Bedroom boundaries
- `4` represents Bathroom boundaries

The genetic algorithm optimizes room placements to minimize corridor area while maintaining adjacencies defined by shared walls.

///

## Notes

- **Execution Time**: GA optimization takes approximately 2-3 minutes due to the evolutionary algorithm running through multiple generations
- **Wall Adjacency**: Rooms are considered adjacent if they share a wall (i.e., a wall with 2 room IDs in `roomIds`)
- **Corridor Generation**: Corridors are automatically generated to connect non-adjacent rooms based on the GA chromosome solution
- **GA Configuration**:
  - Higher `population_size` and `num_generations` can find better solutions but take longer
  - `mutation_rate` controls exploration vs exploitation (0.1 = 10% mutation rate)
- **Layout Matrix**: Provides a grid representation useful for visualization and corridor analysis
- **Solution Chromosome**: The chromosome string represents the optimal arrangement found by the GA (e.g., "0123213021")

## When to Use This API

Use the GA Optimization API when:

- You have predefined room shapes and positions
- You need automatic corridor generation
- Room adjacencies are defined by shared walls
- You want to optimize the overall layout through evolutionary algorithms
- You can wait 2-3 minutes for complex optimization
