"""
Test API with BOUNDARY input (polygonal) instead of rectangular regions.

This demonstrates the new boundary-to-regions conversion feature.
You can provide either:
1. 'regions' - Direct list of rectangles (old way)
2. 'boundary' - Polygon vertices that get auto-converted to regions (new way)
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from GPLAN.api import Documents

# Example 1: Simple rectangular boundary (4 corners)
def test_rectangular_boundary():
    """Test with a simple rectangle defined as boundary"""
    print("\n=== Test 1: Rectangular Boundary ===")
    
    request_data = {
        'request_id': 'test_rect_boundary',
        'params': {
            # Instead of regions, provide boundary as polygon vertices
            'boundary': [
                [0, 0],    # Bottom-left
                [40, 0],   # Bottom-right
                [40, 30],  # Top-right
                [0, 30]    # Top-left
            ],
            'rooms': [
                {'name': 'Living Room', 'width': 10, 'height': 8, 'max_expansion': 15},
                {'name': 'Kitchen', 'width': 8, 'height': 6, 'max_expansion': 10},
                {'name': 'Bedroom', 'width': 9, 'height': 7, 'max_expansion': 12},
                {'name': 'Bathroom', 'width': 5, 'height': 4, 'max_expansion': 5}
            ],
            'fixed_rooms': [],
            'adjacency': [
                ['Living Room', 'Kitchen'],
                ['Bedroom', 'Bathroom']
            ],
            'non_adjacency': [],
            'entrance_coords': None,
            'max_attempts': 500
        },
        'ops': ['place', 'compact', 'expand', 'score']
    }
    
    result = Documents.get_space_optimized_floorplan(request_data)
    
    print(f"Status: {result['status']}")
    if result['status'] == 'ok':
        print(f"Regions created: {len(result['data']['floor']['regions'])}")
        print(f"Floor dimensions: {result['data']['floor']['width']} x {result['data']['floor']['height']}")
        print(f"Rooms placed: {len(result['data']['placements'])}")
        metrics = result['data']['metrics']
        print(f"Adjacency score: {metrics['adjacency_score']:.2%}")
        area_util = metrics.get('area_utilization', {})
        if isinstance(area_util, dict):
            util_ratio = area_util.get('utilization_ratio', 0)
            print(f"Area utilization: {util_ratio:.2%}")
        else:
            print(f"Area utilization: N/A")
    else:
        print(f"Error: {result.get('error', {}).get('message', 'Unknown error')}")
    
    return result


# Example 2: L-shaped boundary (6 corners)
def test_lshape_boundary():
    """Test with an L-shaped boundary"""
    print("\n=== Test 2: L-Shaped Boundary ===")
    
    request_data = {
        'request_id': 'test_lshape_boundary',
        'params': {
            # L-shape boundary (6 vertices)
            'boundary': [
                [0, 0],     # Bottom-left of vertical part
                [15, 0],    # Bottom-right of vertical part
                [15, 20],   # Middle corner (inner corner)
                [30, 20],   # Bottom-right of horizontal part
                [30, 30],   # Top-right
                [0, 30]     # Top-left
            ],
            'rooms': [
                {'name': 'Living Room', 'width': 12, 'height': 10, 'max_expansion': 15},
                {'name': 'Kitchen', 'width': 10, 'height': 8, 'max_expansion': 10},
                {'name': 'Bedroom 1', 'width': 9, 'height': 8, 'max_expansion': 12},
                {'name': 'Bedroom 2', 'width': 9, 'height': 8, 'max_expansion': 12},
                {'name': 'Bathroom', 'width': 6, 'height': 5, 'max_expansion': 5}
            ],
            'fixed_rooms': [],
            'adjacency': [
                ['Living Room', 'Kitchen'],
                ['Bedroom 1', 'Bedroom 2'],
                ['Bedroom 2', 'Bathroom']
            ],
            'non_adjacency': [
                ['Living Room', 'Bathroom']
            ],
            'entrance_coords': None,
            'max_attempts': 1000
        },
        'ops': ['place', 'compact', 'expand', 'score']
    }
    
    result = Documents.get_space_optimized_floorplan(request_data)
    
    print(f"Status: {result['status']}")
    if result['status'] == 'ok':
        print(f"Regions created from L-shape: {len(result['data']['floor']['regions'])}")
        for i, region in enumerate(result['data']['floor']['regions']):
            print(f"  Region {i+1}: x={region['x']}, y={region['y']}, "
                  f"w={region['width']}, h={region['height']}")
        print(f"Floor dimensions: {result['data']['floor']['width']} x {result['data']['floor']['height']}")
        print(f"Rooms placed: {len(result['data']['placements'])}")
        metrics = result['data']['metrics']
        print(f"Adjacency score: {metrics['adjacency_score']:.2%}")
        area_util = metrics.get('area_utilization', {})
        if isinstance(area_util, dict):
            util_ratio = area_util.get('utilization_ratio', 0)
            print(f"Area utilization: {util_ratio:.2%}")
        else:
            print(f"Area utilization: N/A")
    else:
        print(f"Error: {result.get('error', {}).get('message', 'Unknown error')}")
    
    return result


# Example 3: Still works with old regions format
def test_regions_backward_compatibility():
    """Test that the old regions format still works"""
    print("\n=== Test 3: Backward Compatibility (Regions) ===")
    
    request_data = {
        'request_id': 'test_regions_compat',
        'params': {
            # Old way - direct regions (should still work)
            'regions': [
                {'x': 0, 'y': 0, 'width': 25, 'height': 20}
            ],
            'rooms': [
                {'name': 'Living Room', 'width': 10, 'height': 8, 'max_expansion': 10},
                {'name': 'Kitchen', 'width': 8, 'height': 6, 'max_expansion': 8}
            ],
            'fixed_rooms': [],
            'adjacency': [['Living Room', 'Kitchen']],
            'non_adjacency': [],
            'entrance_coords': None,
            'max_attempts': 500
        },
        'ops': ['place', 'compact', 'expand', 'score']
    }
    
    result = Documents.get_space_optimized_floorplan(request_data)
    
    print(f"Status: {result['status']}")
    if result['status'] == 'ok':
        print(f"Regions used: {len(result['data']['floor']['regions'])}")
        print(f"Floor dimensions: {result['data']['floor']['width']} x {result['data']['floor']['height']}")
        print(f"Rooms placed: {len(result['data']['placements'])}")
    else:
        print(f"Error: {result.get('error', {}).get('message', 'Unknown error')}")
    
    return result


# Example 4: Complex polygon (8 vertices)
def test_complex_boundary():
    """Test with a more complex polygon"""
    print("\n=== Test 4: Complex Polygon Boundary ===")
    
    request_data = {
        'request_id': 'test_complex_boundary',
        'params': {
            # Complex rectilinear polygon
            'boundary': [
                [0, 0],
                [20, 0],
                [20, 10],
                [30, 10],
                [30, 25],
                [15, 25],
                [15, 15],
                [0, 15]
            ],
            'rooms': [
                {'name': 'Room A', 'width': 8, 'height': 6, 'max_expansion': 10},
                {'name': 'Room B', 'width': 7, 'height': 5, 'max_expansion': 8},
                {'name': 'Room C', 'width': 6, 'height': 5, 'max_expansion': 8}
            ],
            'fixed_rooms': [],
            'adjacency': [],
            'non_adjacency': [],
            'entrance_coords': None,
            'max_attempts': 500
        },
        'ops': ['place', 'compact', 'expand', 'score']
    }
    
    result = Documents.get_space_optimized_floorplan(request_data)
    
    print(f"Status: {result['status']}")
    if result['status'] == 'ok':
        print(f"Regions created from complex polygon: {len(result['data']['floor']['regions'])}")
        print(f"Floor dimensions: {result['data']['floor']['width']} x {result['data']['floor']['height']}")
        print(f"Rooms placed: {len(result['data']['placements'])}")
        metrics = result['data']['metrics']
        area_util = metrics.get('area_utilization', {})
        if isinstance(area_util, dict):
            util_ratio = area_util.get('utilization_ratio', 0)
            print(f"Area utilization: {util_ratio:.2%}")
        else:
            print(f"Area utilization: N/A")
    else:
        print(f"Error: {result.get('error', {}).get('message', 'Unknown error')}")
    
    return result


if __name__ == "__main__":
    print("=" * 60)
    print("TESTING BOUNDARY INPUT FEATURE")
    print("=" * 60)
    
    # Run all tests
    test_rectangular_boundary()
    test_lshape_boundary()
    test_regions_backward_compatibility()
    test_complex_boundary()
    
    print("\n" + "=" * 60)
    print("ALL TESTS COMPLETED")
    print("=" * 60)
