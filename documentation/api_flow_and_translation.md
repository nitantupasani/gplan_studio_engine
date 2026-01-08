# API Flow and Translation Guide

This document explains how to chain GPLAN APIs together and provides translation functions to convert outputs from one API into inputs for another.

## API Flow Overview

### Flow Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                          Starting Point                          │
└─────────────────────────────────────────────────────────────────┘
                                 │
                 ┌───────────────┼───────────────┐
                 │               │               │
                 ▼               ▼               ▼
         ┌───────────┐   ┌──────────────┐   ┌─────────────┐
         │   Door    │   │    Space     │   │   Manual    │
         │Connectivity│   │Optimization  │   │   Design    │
         └───────────┘   └──────────────┘   └─────────────┘
                 │               │               │
                 └───────────────┼───────────────┘
                                 │
                                 ▼
                     ┌──────────────────────┐
                     │  Translation Layer   │
                     │  (Convert to GA      │
                     │   API Format)        │
                     └──────────────────────┘
                                 │
                                 ▼
                         ┌──────────────┐
                         │   GA API     │
                         │ (Corridor    │
                         │ Optimization)│
                         └──────────────┘
                                 │
                                 ▼
                     ┌──────────────────────┐
                     │  Final Optimized     │
                     │  Floorplan with      │
                     │  Corridors           │
                     └──────────────────────┘
```

## Translation Functions

### 1. Door Connectivity → GA API

Converts door connectivity floorplan output (with rooms and walls) to GA API input format.

```python
def door_connectivity_to_ga_input(door_conn_response, plot_width=40, plot_height=30, corridor_width=3):
    """
    Convert door_connectivity API response to GA API input format.

    Args:
        door_conn_response: Response from door_connectivity API
        plot_width: Width of the plot for GA optimization
        plot_height: Height of the plot for GA optimization
        corridor_width: Corridor width for GA optimization

    Returns:
        Dictionary formatted for GA API input
    """
    import uuid

    # Extract first floorplan from door_connectivity response
    documents = door_conn_response['response']['Documents']
    floorplan = documents['floorPlans'][0]  # Take first floorplan

    ga_rooms = []
    all_walls = []
    labels = []
    wall_id_map = {}  # Map wall coordinates to wall IDs

    for room in floorplan:
        room_id = room['_id']
        room_name = room['name']
        room_color = room.get('color', '#1C4C82')

        # Convert walls
        room_walls = []
        for wall in room['walls']:
            wall_id = wall['_id']
            wall_obj = {
                'id': wall_id,
                'roomIds': [room_id],  # Initially only this room
                'x1': wall['x1'],
                'y1': wall['y1'],
                'x2': wall['x2'],
                'y2': wall['y2']
            }

            # Check if this wall is shared with another room
            # (walls with same coordinates belong to adjacent rooms)
            wall_key = tuple(sorted([(wall['x1'], wall['y1']), (wall['x2'], wall['y2'])]))
            if wall_key in wall_id_map:
                # Shared wall - add second room ID
                existing_wall = wall_id_map[wall_key]
                existing_wall['roomIds'].append(room_id)
            else:
                wall_id_map[wall_key] = wall_obj
                all_walls.append(wall_obj)

            room_walls.append(wall_obj)

        # Add room
        ga_rooms.append({
            'id': room_id,
            'name': room_name,
            'color': room_color,
            'walls': room_walls
        })

        # Add label
        if 'label_coord' in room:
            labels.append({
                'x': room['label_coord'][0],
                'y': room['label_coord'][1],
                'text': room_name,
                'roomId': room_id
            })

    # Build GA API request
    ga_request = {
        'request_id': f"req_ga_{uuid.uuid4().hex[:8]}",
        'engine': 'GA_FloorPlan',
        'params': {
            'plot_width': plot_width,
            'plot_height': plot_height,
            'corridor_width': corridor_width,
            'ga_config': {
                'population_size': 200,
                'num_generations': 600,
                'mutation_rate': 0.1
            },
            'rooms': ga_rooms,
            'walls': all_walls,
            'labels': labels,
            'windows': [],
            'doors': []
        }
    }

    return ga_request


# Example usage:
"""
# Get door_connectivity response
door_conn_response = requests.post(
    "https://api.gplan.in/api/generate/door_connectivity",
    headers=headers,
    json=door_conn_request
).json()

# Convert to GA format
ga_request = door_connectivity_to_ga_input(
    door_conn_response,
    plot_width=40,
    plot_height=30,
    corridor_width=3
)

# Send to GA API
ga_response = requests.post(
    "https://api.gplan.in/api/generate/ga-optimized",
    headers=headers,
    json=ga_request
).json()
"""
```

### 2. Space Optimization → GA API

Converts space optimization output (with room placements) to GA API input format.

```python
def space_optimization_to_ga_input(space_opt_response, corridor_width=3):
    """
    Convert space_optimization API response to GA API input format.

    Args:
        space_opt_response: Response from space_optimization API
        corridor_width: Corridor width for GA optimization

    Returns:
        Dictionary formatted for GA API input
    """
    import uuid

    # Extract data
    floor = space_opt_response['data']['floor']
    placements = space_opt_response['data']['placements']

    ga_rooms = []
    all_walls = []
    labels = []

    # Create a mapping of room positions for adjacency detection
    room_positions = {}
    for placement in placements:
        room_positions[placement['name']] = placement

    # Convert each placement to room with walls
    for placement in placements:
        room_id = f"room-{placement['name'].lower().replace(' ', '-')}-{uuid.uuid4().hex[:3]}"
        room_name = placement['name']
        room_color = '#1C4C82'  # Default color

        x = placement['x']
        y = placement['y']
        w = placement['width']
        h = placement['height']

        # Create walls for the room (clockwise from top-left)
        walls = [
            {
                'id': f"wall-{room_id}-left",
                'roomIds': [room_id],
                'x1': x,
                'y1': y,
                'x2': x,
                'y2': y + h
            },
            {
                'id': f"wall-{room_id}-top",
                'roomIds': [room_id],
                'x1': x,
                'y1': y,
                'x2': x + w,
                'y2': y
            },
            {
                'id': f"wall-{room_id}-right",
                'roomIds': [room_id],
                'x1': x + w,
                'y1': y,
                'x2': x + w,
                'y2': y + h
            },
            {
                'id': f"wall-{room_id}-bottom",
                'roomIds': [room_id],
                'x1': x,
                'y1': y + h,
                'x2': x + w,
                'y2': y + h
            }
        ]

        # Detect shared walls with other rooms
        for other_placement in placements:
            if other_placement['name'] == room_name:
                continue

            other_id = f"room-{other_placement['name'].lower().replace(' ', '-')}"
            ox = other_placement['x']
            oy = other_placement['y']
            ow = other_placement['width']
            oh = other_placement['height']

            # Check for shared walls
            # Right wall shared with other's left wall
            if x + w == ox and not (y + h <= oy or y >= oy + oh):
                for wall in walls:
                    if wall['id'].endswith('-right'):
                        if other_id not in wall['roomIds']:
                            wall['roomIds'].append(other_id)

            # Bottom wall shared with other's top wall
            if y + h == oy and not (x + w <= ox or x >= ox + ow):
                for wall in walls:
                    if wall['id'].endswith('-bottom'):
                        if other_id not in wall['roomIds']:
                            wall['roomIds'].append(other_id)

        ga_rooms.append({
            'id': room_id,
            'name': room_name,
            'color': room_color,
            'walls': walls
        })

        all_walls.extend(walls)

        # Add label at center
        labels.append({
            'x': x + w / 2,
            'y': y + h / 2,
            'text': room_name,
            'roomId': room_id
        })

    # Build GA API request
    ga_request = {
        'request_id': f"req_ga_{uuid.uuid4().hex[:8]}",
        'engine': 'GA_FloorPlan',
        'params': {
            'plot_width': floor['width'],
            'plot_height': floor['height'],
            'corridor_width': corridor_width,
            'ga_config': {
                'population_size': 200,
                'num_generations': 600,
                'mutation_rate': 0.1
            },
            'rooms': ga_rooms,
            'walls': all_walls,
            'labels': labels,
            'windows': [],
            'doors': []
        }
    }

    return ga_request


# Example usage:
"""
# Get space_optimization response
space_opt_response = requests.post(
    "https://api.gplan.in/api/generate/space-optimized",
    headers=headers,
    json=space_opt_request
).json()

# Convert to GA format
ga_request = space_optimization_to_ga_input(
    space_opt_response,
    corridor_width=3
)

# Send to GA API
ga_response = requests.post(
    "https://api.gplan.in/api/generate/ga-optimized",
    headers=headers,
    json=ga_request
).json()
"""
```

## Complete Flow Example

### Scenario: Generate L-Shape Floorplan → Optimize with Corridors

```python
import requests
import uuid

API_BASE = "https://api.gplan.in/api/generate"
API_KEY = "<YOUR_API_KEY>"

headers = {
    "accept": "application/json",
    "content-type": "application/json",
    "Authorization": f"Api-Key {API_KEY}"
}

# ============================================================================
# STEP 1: Generate initial floorplan with Space Optimization
# ============================================================================

space_opt_request = {
    "request_id": "req_step1_space_opt",
    "engine": "FloorPlan",
    "params": {
        "boundary": [
            [0, 0], [40, 0], [40, 24],
            [20, 24], [20, 32], [0, 32]
        ],
        "rooms": [
            {"name": "Living", "width": 16, "height": 10, "max_expansion": 6},
            {"name": "Dining", "width": 10, "height": 8, "max_expansion": 4},
            {"name": "Kitchen", "width": 8, "height": 7, "max_expansion": 3},
            {"name": "Bedroom", "width": 12, "height": 10, "max_expansion": 5}
        ],
        "adjacency": [
            ["Living", "Dining"],
            ["Dining", "Kitchen"]
        ],
        "non_adjacency": [
            ["Bedroom", "Kitchen"]
        ]
    },
    "ops": ["place", "compact", "expand", "score"]
}

print("Step 1: Calling Space Optimization API...")
space_response = requests.post(
    f"{API_BASE}/space-optimized",
    headers=headers,
    json=space_opt_request
).json()

if space_response['status'] != 'ok':
    print(f"Error: {space_response['error']['message']}")
    exit(1)

print(f"✓ Generated {len(space_response['data']['placements'])} room placements")
print(f"  Adjacency Score: {space_response['data']['metrics']['adjacency_score']:.1%}")

# ============================================================================
# STEP 2: Convert to GA API format
# ============================================================================

print("\nStep 2: Converting to GA API format...")
ga_request = space_optimization_to_ga_input(space_response, corridor_width=3)
print(f"✓ Converted to GA format with {len(ga_request['params']['rooms'])} rooms")

# ============================================================================
# STEP 3: Optimize with GA for corridor generation
# ============================================================================

print("\nStep 3: Calling GA Optimization API (this takes 2-3 minutes)...")
ga_response = requests.post(
    f"{API_BASE}/ga-optimized",
    headers=headers,
    json=ga_request
).json()

if ga_response['status'] != 'success':
    print(f"Error: {ga_response['error']['message']}")
    exit(1)

print(f"✓ GA Optimization complete!")
print(f"  Status: {ga_response['data']['ga_optimization']['status']}")
print(f"  Solution: {ga_response['data']['ga_optimization']['solution_chromosome']}")

# ============================================================================
# STEP 4: Extract final results
# ============================================================================

print("\nFinal Results:")
for room in ga_response['data']['rooms']:
    bounds = room['optimized_bounds']
    print(f"  • {room['name']}: ({bounds['x']}, {bounds['y']}) "
          f"[{bounds['width']} × {bounds['height']}]")

print("\nLayout matrix available in response for corridor visualization")
```

## Use Cases

### Use Case 1: Graph-Based Design → Corridor Optimization

**Flow**: `door_connectivity` → `GA API`

**When to use**:

- You have room adjacency defined as a graph (nodes + edges)
- You want to generate initial layout from graph
- Then optimize with corridors for better circulation

**Steps**:

1. Design floorplan using graph (nodes = rooms, edges = adjacency)
2. Call `door_connectivity` API to generate initial floorplan
3. Convert output using `door_connectivity_to_ga_input()`
4. Call GA API to add corridors and optimize layout

### Use Case 2: Boundary-Based Design → Corridor Optimization

**Flow**: `space_optimization` → `GA API`

**When to use**:

- You have an irregular plot boundary (L-shape, T-shape, etc.)
- You want rooms placed within boundary with adjacency constraints
- Then optimize with corridors for circulation

**Steps**:

1. Define boundary polygon and room requirements
2. Call `space_optimization` API to place rooms
3. Convert output using `space_optimization_to_ga_input()`
4. Call GA API to add corridors and optimize circulation

### Use Case 3: Direct GA Optimization

**Flow**: Manual Design → `GA API`

**When to use**:

- You already have predefined room positions and walls
- You only need corridor optimization
- You want full control over initial layout

**Steps**:

1. Manually create room and wall definitions
2. Call GA API directly with your design
3. Get optimized layout with corridors

## Translation Helper Script

Save this as `translate_api_output.py`:

```python
#!/usr/bin/env python3
"""
GPLAN API Translation Helper

Usage:
    # Convert door_connectivity output
    python translate_api_output.py door_connectivity output.json > ga_input.json

    # Convert space_optimization output
    python translate_api_output.py space_optimization output.json > ga_input.json
"""

import json
import sys
import uuid


def door_connectivity_to_ga_input(door_conn_response, plot_width=40, plot_height=30, corridor_width=3):
    """Convert door_connectivity API response to GA API input format."""
    # [Implementation from above]
    pass  # Use the full function from above


def space_optimization_to_ga_input(space_opt_response, corridor_width=3):
    """Convert space_optimization API response to GA API input format."""
    # [Implementation from above]
    pass  # Use the full function from above


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)

    api_type = sys.argv[1]
    input_file = sys.argv[2]

    # Read input
    with open(input_file, 'r') as f:
        response = json.load(f)

    # Convert based on type
    if api_type == 'door_connectivity':
        ga_input = door_connectivity_to_ga_input(response)
    elif api_type == 'space_optimization':
        ga_input = space_optimization_to_ga_input(response)
    else:
        print(f"Error: Unknown API type '{api_type}'")
        print("Valid types: door_connectivity, space_optimization")
        sys.exit(1)

    # Output JSON
    print(json.dumps(ga_input, indent=2))


if __name__ == '__main__':
    main()
```

## API Compatibility Matrix

| Source API         | Target API | Supported | Translation Function               | Notes                                 |
| ------------------ | ---------- | --------- | ---------------------------------- | ------------------------------------- |
| door_connectivity  | GA API     | ✅ Yes    | `door_connectivity_to_ga_input()`  | Preserves room shapes and adjacencies |
| space_optimization | GA API     | ✅ Yes    | `space_optimization_to_ga_input()` | Converts placements to walls          |

## Best Practices

1. **Choose the Right Starting API**:

   - Use `door_connectivity` when you have a clear room adjacency graph
   - Use `space_optimization` when you have an irregular boundary or fixed rooms

2. **Translation Considerations**:

   - Some information may be lost in translation (e.g., non-adjacency constraints)
   - GA API requires walls, so rooms are converted to rectangular boundaries
   - Shared walls are detected automatically based on coordinates

3. **Error Handling**:
   - Always check response status before translating
   - Validate translated data before sending to next API
   - Log intermediate responses for debugging

## Conclusion

By chaining GPLAN APIs together with these translation functions, you can leverage the strengths of each engine:

- **door_connectivity**: Graph-based initial layouts
- **space_optimization**: Boundary-aware room placement with constraints
- **GA API**: Corridor optimization and circulation planning
