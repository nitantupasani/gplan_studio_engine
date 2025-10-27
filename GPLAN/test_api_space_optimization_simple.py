"""
Simple Test API for Space Optimization
Just paste your request data and run to get output.
"""

import sys
import os
import pprint
import json

# Add parent directory to path to allow imports
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from GPLAN.api import Documents


# ============================================================================
# PASTE YOUR REQUEST HERE
# ============================================================================

request_data = {
  "request_id": "req_big_001",
  "engine": "FloorPlan",
  "params": {
    "regions": [
      { "x": 0,  "y": 0,  "width": 40, "height": 24 },
      { "x": 40, "y": 0,  "width": 12, "height": 12 },
      { "x": 0,  "y": 24, "width": 20, "height": 8 }
    ],

    "fixed_rooms": [
      { "name": "Staircase", "x": 44, "y": 0,  "width": 8, "height": 12, "is_fixed": True, "max_expansion": 0 },
      { "name": "Lift",      "x": 32, "y": 0,  "width": 4, "height": 6,  "is_fixed": True, "max_expansion": 0 },
      { "name": "Duct",      "x": 0,  "y": 24, "width": 4, "height": 8,  "is_fixed": True, "max_expansion": 0 }
    ],

    "rooms": [
      { "name": "Living",    "width": 16, "height": 10, "max_expansion": 6 },
      { "name": "Dining",    "width": 10, "height": 8,  "max_expansion": 4 },
      { "name": "Kitchen",   "width": 8,  "height": 7,  "max_expansion": 3 },
      { "name": "Bedroom1",  "width": 12, "height": 10, "max_expansion": 5 },
      { "name": "Bedroom2",  "width": 12, "height": 10, "max_expansion": 5 },
      { "name": "Bathroom1", "width": 6,  "height": 6,  "max_expansion": 2 },
      { "name": "Bathroom2", "width": 6,  "height": 6,  "max_expansion": 2 },
      { "name": "Utility",   "width": 6,  "height": 6,  "max_expansion": 2 },
      { "name": "Balcony",   "width": 8,  "height": 4,  "max_expansion": 2 }
    ],

    "adjacency": [
      ["Living", "Dining"],
      ["Dining", "Kitchen"],
      ["Bedroom1", "Bathroom1"],
      ["Bedroom2", "Bathroom2"]
    ],

    "non_adjacency": [
      ["Bedroom1", "Lift"],
      ["Bedroom2", "Lift"],
      ["Kitchen", "Bathroom2"]
    ],

    "entrance_coords": [
      [0, 10], [0, 14]
    ]
  },

  "ops": ["place", "compact", "expand", "score"]
}


# ============================================================================
# RUN THE TEST
# ============================================================================

def run_test():
    """Run the space optimization test"""
    print("\n" + "="*80)
    print("SPACE OPTIMIZATION TEST")
    print("="*80)
    
    print("\n📥 INPUT REQUEST:")
    print("-"*80)
    pprint.pprint(request_data)
    
    print("\n⚙️  PROCESSING...")
    print("-"*80)
    
    # Call the API
    result = Documents.get_space_optimized_floorplan(request_data)
    
    print("\n📤 OUTPUT RESULT:")
    print("-"*80)
    
    if result['status'] == 'ok':
        print("✅ SUCCESS!")
        print("\n" + "="*80)
        print("FULL RESULT:")
        print("="*80)
        pprint.pprint(result)
        
        print("\n" + "="*80)
        print("SUMMARY:")
        print("="*80)
        
        # Floor info
        floor = result['data']['floor']
        print(f"\n🏢 Floor: {floor['width']} × {floor['height']}")
        print(f"   Regions: {len(floor['regions'])}")
        
        # Placements
        placements = result['data']['placements']
        print(f"\n📦 Placements: {len(placements)} rooms")
        for room in placements:
            fixed_marker = "🔒" if room['is_fixed'] else "  "
            rotation_marker = "↻" if room['rotated'] else " "
            print(f"   {fixed_marker} {room['name']:15s} @ ({room['x']:3d}, {room['y']:3d}) "
                  f"[{room['width']:3d} × {room['height']:3d}] {rotation_marker} "
                  f"Area: {room['area']}")
        
        # Metrics
        metrics = result['data']['metrics']
        print(f"\n📊 Metrics:")
        print(f"   Adjacency Score: {metrics['adjacency_score']:.2%}")
        print(f"   Satisfied Pairs: {len(metrics['satisfied_pairs'])}/{len(request_data['params']['adjacency'])}")
        for pair in metrics['satisfied_pairs']:
            print(f"      ✓ {pair[0]} ↔ {pair[1]}")
        
        if metrics['non_adjacency_violations']:
            print(f"   ⚠️  Non-adjacency Violations: {len(metrics['non_adjacency_violations'])}")
            for pair in metrics['non_adjacency_violations']:
                print(f"      ✗ {pair[0]} ↔ {pair[1]}")
        else:
            print(f"   ✓ No non-adjacency violations")
        
        # Area utilization
        area_util = metrics['area_utilization']
        print(f"\n🔢 Area Utilization:")
        print(f"   Total Region Area: {area_util['total_region_area']}")
        print(f"   Occupied (Rooms):  {area_util['occupied_room_area']}")
        print(f"   Occupied (Fixed):  {area_util['occupied_fixed_area']}")
        print(f"   Total Occupied:    {area_util['occupied_total_area']}")
        print(f"   Remaining:         {area_util['remaining_area']}")
        print(f"   Utilization:       {area_util['utilization_ratio']:.2%}")
        
        # Entrance adjacency
        if metrics.get('entrance_adjacent_rooms'):
            print(f"\n🚪 Entrance Adjacent Rooms:")
            for room_name in metrics['entrance_adjacent_rooms']:
                print(f"   • {room_name}")
        
    else:
        print("❌ FAILED!")
        print(f"\nError: {result.get('error', {}).get('message', 'Unknown error')}")
        pprint.pprint(result)
    
    print("\n" + "="*80)
    print("TEST COMPLETE")
    print("="*80 + "\n")
    
    return result


# ============================================================================
# HELPER FUNCTION: Validate request before running
# ============================================================================

def validate_request(req):
    """Validate request data has required fields"""
    errors = []
    
    if 'params' not in req:
        errors.append("Missing 'params' field")
        return errors
    
    params = req['params']
    
    if 'regions' not in params or not params['regions']:
        errors.append("Missing or empty 'regions' field")
    
    if 'rooms' not in params or not params['rooms']:
        errors.append("Missing or empty 'rooms' field")
    
    # Check region format
    for i, region in enumerate(params.get('regions', [])):
        required = ['x', 'y', 'width', 'height']
        for field in required:
            if field not in region:
                errors.append(f"Region {i}: missing '{field}'")
    
    # Check room format
    for i, room in enumerate(params.get('rooms', [])):
        required = ['name', 'width', 'height']
        for field in required:
            if field not in room:
                errors.append(f"Room {i}: missing '{field}'")
    
    # Check fixed room format
    for i, room in enumerate(params.get('fixed_rooms', [])):
        required = ['name', 'x', 'y', 'width', 'height']
        for field in required:
            if field not in room:
                errors.append(f"Fixed room {i}: missing '{field}'")
    
    return errors


# ============================================================================
# MAIN EXECUTION
# ============================================================================

if __name__ == '__main__':
    print("\n" + "="*80)
    print("SPACE OPTIMIZATION - SIMPLE TEST RUNNER")
    print("="*80)
    print("\nInstructions:")
    print("1. Paste your request data in the 'request_data' variable above")
    print("2. Run: python test_api_space_optimization_simple.py")
    print("3. Get your results!")
    print("="*80)
    
    # Validate request
    print("\n🔍 Validating request...")
    errors = validate_request(request_data)
    
    if errors:
        print("❌ Validation failed:")
        for error in errors:
            print(f"   • {error}")
        print("\nPlease fix the errors and try again.")
    else:
        print("✓ Request is valid\n")
        
        # Run the test
        try:
            result = run_test()
        except Exception as e:
            print(f"\n❌ ERROR: {str(e)}")
            import traceback
            traceback.print_exc()


# ============================================================================
# EXAMPLE REQUESTS - Uncomment and use these as templates
# ============================================================================

"""
# EXAMPLE 1: Simple rectangular floor with 3 rooms
request_data = {
    "request_id": "simple_001",
    "params": {
        "regions": [
            {"x": 0, "y": 0, "width": 30, "height": 20}
        ],
        "rooms": [
            {"name": "Living", "width": 10, "height": 8, "max_expansion": 5},
            {"name": "Kitchen", "width": 8, "height": 6, "max_expansion": 3},
            {"name": "Bedroom", "width": 8, "height": 7, "max_expansion": 4}
        ],
        "fixed_rooms": [],
        "adjacency": [["Living", "Kitchen"]],
        "non_adjacency": [],
        "entrance_coords": None
    },
    "ops": ["place", "compact", "expand", "score"]
}

# EXAMPLE 2: L-shaped floor
request_data = {
    "request_id": "lshape_001",
    "params": {
        "regions": [
            {"x": 0, "y": 0, "width": 25, "height": 20},
            {"x": 0, "y": 20, "width": 15, "height": 10}
        ],
        "rooms": [
            {"name": "Living", "width": 10, "height": 8, "max_expansion": 5},
            {"name": "Kitchen", "width": 7, "height": 6, "max_expansion": 3},
            {"name": "Bedroom", "width": 8, "height": 7, "max_expansion": 4},
            {"name": "Bathroom", "width": 5, "height": 5, "max_expansion": 2}
        ],
        "fixed_rooms": [],
        "adjacency": [["Living", "Kitchen"], ["Bedroom", "Bathroom"]],
        "non_adjacency": [["Kitchen", "Bedroom"]],
        "entrance_coords": [[0, 8], [0, 12]]
    },
    "ops": ["place", "compact", "expand", "score"]
}

# EXAMPLE 3: With fixed rooms (stairs, lift)
request_data = {
    "request_id": "fixed_001",
    "params": {
        "regions": [
            {"x": 0, "y": 0, "width": 40, "height": 24}
        ],
        "fixed_rooms": [
            {"name": "Staircase", "x": 32, "y": 0, "width": 8, "height": 12, "is_fixed": True, "max_expansion": 0},
            {"name": "Lift", "x": 32, "y": 12, "width": 4, "height": 6, "is_fixed": True, "max_expansion": 0}
        ],
        "rooms": [
            {"name": "Living", "width": 12, "height": 10, "max_expansion": 5},
            {"name": "Kitchen", "width": 8, "height": 6, "max_expansion": 3},
            {"name": "Bedroom1", "width": 10, "height": 8, "max_expansion": 4},
            {"name": "Bedroom2", "width": 10, "height": 8, "max_expansion": 4},
            {"name": "Bathroom1", "width": 6, "height": 6, "max_expansion": 2},
            {"name": "Bathroom2", "width": 6, "height": 6, "max_expansion": 2}
        ],
        "adjacency": [
            ["Living", "Kitchen"],
            ["Bedroom1", "Bathroom1"],
            ["Bedroom2", "Bathroom2"]
        ],
        "non_adjacency": [
            ["Bedroom1", "Lift"],
            ["Bedroom2", "Lift"]
        ],
        "entrance_coords": [[0, 10], [0, 14]]
    },
    "ops": ["place", "compact", "expand", "score"]
}

# EXAMPLE 4: No expansion
request_data = {
    "request_id": "no_expand_001",
    "params": {
        "regions": [
            {"x": 0, "y": 0, "width": 25, "height": 20}
        ],
        "rooms": [
            {"name": "Room1", "width": 8, "height": 6, "max_expansion": 0},
            {"name": "Room2", "width": 7, "height": 5, "max_expansion": 0},
            {"name": "Room3", "width": 6, "height": 6, "max_expansion": 0}
        ],
        "fixed_rooms": [],
        "adjacency": [],
        "non_adjacency": [],
        "entrance_coords": None
    },
    "ops": ["place", "score"]  # No expand or compact
}

# EXAMPLE 5: Complex with all features
request_data = {
    "request_id": "complex_001",
    "params": {
        "regions": [
            {"x": 0, "y": 0, "width": 40, "height": 24},
            {"x": 40, "y": 0, "width": 12, "height": 12},
            {"x": 0, "y": 24, "width": 20, "height": 8}
        ],
        "fixed_rooms": [
            {"name": "Staircase", "x": 44, "y": 0, "width": 8, "height": 12, "is_fixed": True, "max_expansion": 0},
            {"name": "Lift", "x": 32, "y": 0, "width": 4, "height": 6, "is_fixed": True, "max_expansion": 0},
            {"name": "Duct", "x": 0, "y": 24, "width": 4, "height": 8, "is_fixed": True, "max_expansion": 0}
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
            ["Bedroom2", "Bathroom2"]
        ],
        "non_adjacency": [
            ["Bedroom1", "Lift"],
            ["Bedroom2", "Lift"],
            ["Kitchen", "Bathroom2"]
        ],
        "entrance_coords": [[0, 10], [0, 14]]
    },
    "ops": ["place", "compact", "expand", "score"]
}
"""
