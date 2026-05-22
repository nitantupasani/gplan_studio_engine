"""
Simple Test API for Space Optimization
Just paste your request data and run to get output.

NEW FEATURE: BOUNDARY SUPPORT
------------------------------
You can now provide either:
1. 'regions' - Direct list of rectangles (traditional way)
2. 'boundary' - Polygon vertices that auto-convert to regions (NEW!)

Example with BOUNDARY (L-shape):
    "boundary": [
        [0, 0], [40, 0], [40, 24],  # Right side
        [20, 24], [20, 32], [0, 32]  # Left side (extension)
    ]

The API automatically converts your boundary to regions!
See more examples at the bottom of this file.
"""

import sys
import os
import pprint
import json
import matplotlib.pyplot as plt
import matplotlib.patches as patches
from matplotlib.patches import Rectangle
import numpy as np

# Add parent directory to path to allow imports
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from GPLAN.api import Documents


# ============================================================================
# VISUALIZATION FLAG
# ============================================================================
# Set to True to display ASCII visualization of the floorplan
VISUALIZE = True


# ============================================================================
# PASTE YOUR REQUEST HERE
# ============================================================================

request_data = {
    "request_id": "req-space-ce8c3c06-a7c9-467f-9976-e38a8e5f4f07",
    "engine": "FloorPlan",
    "params": {
        "boundary": [
            [
                884,
                420
            ],
            [
                884,
                440
            ],
            [
                910,
                440
            ],
            [
                910,
                420
            ]
        ],
        "rooms": [
            {
                "name": "Bedroom",
                "width": 12,
                "height": 10,
                "max_expansion": 0
            },
            {
                "name": "Kitchen",
                "width": 8,
                "height": 6,
                "max_expansion": 0
            },
            {
                "name": "Bathroom",
                "width": 4,
                "height": 6,
                "max_expansion": 0
            },
            {
                "name": "Dining Room",
                "width": 6,
                "height": 7,
                "max_expansion": 0
            }
        ],
        "adjacency": [],
        "non_adjacency": [],
        "fixed_rooms": [
            {
                "name": "Aa",
                "x": 884,
                "y": 420,
                "width": 10,
                "height": 10,
                "is_fixed": True,
                "max_expansion": 0
            }
        ],
        "max_attempts": 1000
    },
    "ops": [
        "place",
        "compact",
        "score"
    ]
}



# ============================================================================
# VISUALIZATION & ANALYSIS FUNCTIONS
# ============================================================================

def visualize_floorplan(result):
    """GUI visualization of the floorplan using matplotlib"""
    if result['status'] != 'ok':
        return
    
    floor = result['data']['floor']
    placements = result['data']['placements']
    
    width = floor['width']
    height = floor['height']
    
    # Create figure and axis
    fig, ax = plt.subplots(1, 1, figsize=(12, 8))
    
    # Set axis limits
    ax.set_xlim(-1, width + 1)
    ax.set_ylim(-1, height + 1)
    ax.set_aspect('equal')
    ax.invert_yaxis()  # Invert Y to match typical floor plan orientation
    
    # Draw regions with light background
    for region in floor['regions']:
        x = region['x']
        y = region['y']
        w = region['width']
        h = region['height']
        rect = Rectangle((x, y), w, h, linewidth=2, edgecolor='gray', 
                         facecolor='lightgray', alpha=0.3, linestyle='--')
        ax.add_patch(rect)
    
    # Color palette for rooms
    colors = plt.cm.Set3(np.linspace(0, 1, len(placements)))
    
    # Track overlaps
    overlaps = {}
    
    # Draw rooms
    for idx, room in enumerate(placements):
        x = room['x']
        y = room['y']
        w = room['width']
        h = room['height']
        
        # Use different edge style for fixed rooms
        edge_style = 'solid' if room['is_fixed'] else 'solid'
        edge_width = 3 if room['is_fixed'] else 2
        edge_color = 'darkred' if room['is_fixed'] else 'black'
        
        # Draw rectangle
        rect = Rectangle((x, y), w, h, linewidth=edge_width, 
                         edgecolor=edge_color, facecolor=colors[idx], 
                         alpha=0.7, linestyle=edge_style)
        ax.add_patch(rect)
        
        # Add label
        label = f"{room['name']}"
        if room['is_fixed']:
            label = f"🔒 {room['name']}"
        
        ax.text(x + w/2, y + h/2, label, ha='center', va='center', 
               fontsize=9, fontweight='bold', wrap=True)
        
        # Add dimensions
        ax.text(x + w/2, y - 0.5, f"{w}×{h}", ha='center', va='top', 
               fontsize=8, style='italic', color='gray')
    
    # Draw grid
    ax.grid(True, alpha=0.2, linestyle=':')
    
    # Labels and title
    ax.set_xlabel('X (width)', fontsize=11, fontweight='bold')
    ax.set_ylabel('Y (height)', fontsize=11, fontweight='bold')
    ax.set_title(f'Floorplan Visualization - {width}×{height} | {len(placements)} rooms', 
                fontsize=13, fontweight='bold')
    
    # Add legend
    legend_elements = []
    for idx, room in enumerate(placements):
        marker = '(Fixed)' if room['is_fixed'] else '(Flexible)'
        legend_elements.append(
            patches.Patch(facecolor=colors[idx], edgecolor='black', 
                         label=f"{room['name']} - {room['width']}×{room['height']} {marker}")
        )
    
    ax.legend(handles=legend_elements, loc='upper left', bbox_to_anchor=(1.02, 1), 
             fontsize=9, title='Rooms', title_fontsize=10)
    
    # Check for overlaps
    overlaps = check_overlaps_detailed(result)
    if overlaps:
        # Add overlap warning to title
        overlap_text = f"\n⚠️  WARNING: {len(overlaps)} overlap(s) detected!"
        ax.set_title(ax.get_title() + overlap_text, fontsize=13, fontweight='bold', color='red')
    
    plt.tight_layout()
    plt.show()


def check_overlaps_detailed(result):
    """Detailed overlap analysis"""
    if result['status'] != 'ok':
        return []
    
    placements = result['data']['placements']
    overlaps = []
    
    for i, room1 in enumerate(placements):
        for room2 in placements[i+1:]:
            # Check if rooms overlap
            x1_min, x1_max = room1['x'], room1['x'] + room1['width']
            y1_min, y1_max = room1['y'], room1['y'] + room1['height']
            
            x2_min, x2_max = room2['x'], room2['x'] + room2['width']
            y2_min, y2_max = room2['y'], room2['y'] + room2['height']
            
            # Check for overlap
            if not (x1_max <= x2_min or x2_max <= x1_min or 
                    y1_max <= y2_min or y2_max <= y1_min):
                # Calculate overlap area
                overlap_x = min(x1_max, x2_max) - max(x1_min, x2_min)
                overlap_y = min(y1_max, y2_max) - max(y1_min, y2_min)
                overlap_area = overlap_x * overlap_y
                
                overlaps.append({
                    'room1': room1['name'],
                    'room2': room2['name'],
                    'room1_fixed': room1['is_fixed'],
                    'room2_fixed': room2['is_fixed'],
                    'overlap_area': overlap_area,
                    'overlap_dims': (overlap_x, overlap_y)
                })
    
    return overlaps


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
        if 'boundary' in request_data['params']:
            print(f"   🔷 Boundary vertices: {len(request_data['params']['boundary'])}")
        
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
        
        # Overlap analysis
        overlaps = check_overlaps_detailed(result)
        if overlaps:
            print(f"\n⚠️  OVERLAP ANALYSIS:")
            print(f"   Found {len(overlaps)} overlap(s):")
            for overlap in overlaps:
                fixed_info = ""
                if overlap['room1_fixed'] or overlap['room2_fixed']:
                    fixed_info = " (FIXED ROOM OVERLAP!)" if overlap['room1_fixed'] or overlap['room2_fixed'] else ""
                print(f"   • {overlap['room1']} ↔ {overlap['room2']}{fixed_info}")
                print(f"     Overlap area: {overlap['overlap_area']} sq units ({overlap['overlap_dims'][0]}×{overlap['overlap_dims'][1]})")
        else:
            print(f"\n✅ No overlaps detected!")
        
        # Visualization
        if VISUALIZE:
            visualize_floorplan(result)
        
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
    
    # Check for regions OR boundary (NEW: boundary support)
    has_regions = 'regions' in params and params['regions']
    has_boundary = 'boundary' in params and params['boundary']
    
    if not has_regions and not has_boundary:
        errors.append("Missing 'regions' or 'boundary' field - at least one is required")
    
    if 'rooms' not in params or not params['rooms']:
        errors.append("Missing or empty 'rooms' field")
    
    # Check region format (if provided)
    for i, region in enumerate(params.get('regions', [])):
        required = ['x', 'y', 'width', 'height']
        for field in required:
            if field not in region:
                errors.append(f"Region {i}: missing '{field}'")
    
    # Check boundary format (if provided)
    if has_boundary:
        boundary = params['boundary']
        if not isinstance(boundary, list):
            errors.append("Boundary must be a list of coordinate pairs")
        elif len(boundary) < 3:
            errors.append("Boundary must have at least 3 points")
        else:
            for i, point in enumerate(boundary):
                if not isinstance(point, (list, tuple)) or len(point) != 2:
                    errors.append(f"Boundary point {i}: must be [x, y] coordinate pair")
    
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
} using REGIONS (old way)
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

# EXAMPLE 2B: L-shaped floor using BOUNDARY (new way - auto-converts to regions)
request_data = {
    "request_id": "lshape_boundary_001",
    "params": {
        "boundary": [
            [0, 0],    # Bottom-left
            [25, 0],   # Bottom-right of horizontal part
            [25, 20],  # Inner corner
            [15, 20],  # Top-right of vertical part
            [15, 30],  # Top-right corner
            [0, 30]    # Top-left
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

# EXAMPLE 6: Simple rectangle with BOUNDARY (easiest way)
request_data = {
    "request_id": "rect_boundary_001",
    "params": {
        "boundary": [
            [0, 0],
            [50, 0],
            [50, 30],
            [0, 30]
        ],
        "rooms": [
            {"name": "Living", "width": 18, "height": 12, "max_expansion": 8},
            {"name": "Kitchen", "width": 12, "height": 10, "max_expansion": 5},
            {"name": "Bedroom", "width": 14, "height": 11, "max_expansion": 6},
            {"name": "Bathroom", "width": 8, "height": 7, "max_expansion": 3}
        ],
        "fixed_rooms": [],
        "adjacency": [["Living", "Kitchen"], ["Bedroom", "Bathroom"]],
        "non_adjacency": [["Kitchen", "Bathroom"]],
        "entrance_coords": [[0, 12], [0, 18]]
    },
    "ops": ["place", "compact", "expand", "score"]
}

# EXAMPLE 7: T-Shape with BOUNDARY
request_data = {
    "request_id": "tshape_boundary_001",
    "params": {
        "boundary": [
            [0, 0],
            [15, 0],
            [15, 15],
            [30, 15],
            [30, 25],
            [15, 25],
            [15, 40],
            [0, 40]
        ],
        "fixed_rooms": [
            {"name": "Elevator", "x": 16, "y": 16, "width": 6, "height": 8, "is_fixed": True, "max_expansion": 0}
        ],
        "rooms": [
            {"name": "Reception", "width": 10, "height": 8, "max_expansion": 4},
            {"name": "Office1", "width": 12, "height": 10, "max_expansion": 5},
            {"name": "Office2", "width": 12, "height": 10, "max_expansion": 5},
            {"name": "Conference", "width": 14, "height": 12, "max_expansion": 6},
            {"name": "Restroom", "width": 6, "height": 6, "max_expansion": 2}
        ],
        "adjacency": [["Reception", "Conference"], ["Office1", "Office2"]],
        "non_adjacency": [["Restroom", "Conference"]],
        "entrance_coords": [[0, 18], [0, 22]],
        "max_attempts": 1500
    },
    "ops": ["place", "compact", "expand", "score"]
}
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
