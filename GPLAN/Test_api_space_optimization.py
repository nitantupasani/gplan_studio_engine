"""
Test API for Space Optimization
This file tests the space optimization functionality using the negNew FloorPlan engine.
"""

import sys
import os

# Add parent directory to path to allow imports
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from GPLAN.api import Documents
import pprint
import json


def test_space_optimization_simple():
    """Test with a simple example"""
    request_data = {
        "request_id": "test_simple_001",
        "engine": "SpaceOptimization",
        "params": {
            "regions": [
                {"x": 0, "y": 0, "width": 30, "height": 20}
            ],
            "fixed_rooms": [],
            "rooms": [
                {"name": "Living", "width": 8, "height": 6, "max_expansion": 5},
                {"name": "Kitchen", "width": 6, "height": 5, "max_expansion": 3},
                {"name": "Bedroom", "width": 7, "height": 6, "max_expansion": 4},
                {"name": "Bathroom", "width": 4, "height": 4, "max_expansion": 2}
            ],
            "adjacency": [
                ["Living", "Kitchen"],
                ["Bedroom", "Bathroom"]
            ],
            "non_adjacency": [
                ["Kitchen", "Bathroom"]
            ],
            "entrance_coords": [[0, 8], [0, 12]]
        },
        "ops": ["place", "compact", "expand", "score"]
    }
    
    print("\n" + "="*80)
    print("TEST: Simple Space Optimization")
    print("="*80)
    
    result = Documents.get_space_optimized_floorplan(request_data)
    pprint.pprint(result)
    
    return result


def test_space_optimization_with_fixed_rooms():
    """Test with fixed rooms (like stairs, lifts, etc.)"""
    request_data = {
        "request_id": "test_fixed_001",
        "engine": "SpaceOptimization",
        "params": {
            "regions": [
                {"x": 0, "y": 0, "width": 40, "height": 24},
                {"x": 40, "y": 0, "width": 12, "height": 12}
            ],
            "fixed_rooms": [
                {"name": "Staircase", "x": 44, "y": 0, "width": 8, "height": 12, "is_fixed": True, "max_expansion": 0},
                {"name": "Lift", "x": 36, "y": 0, "width": 4, "height": 6, "is_fixed": True, "max_expansion": 0}
            ],
            "rooms": [
                {"name": "Living", "width": 10, "height": 8, "max_expansion": 5},
                {"name": "Dining", "width": 8, "height": 6, "max_expansion": 3},
                {"name": "Kitchen", "width": 6, "height": 5, "max_expansion": 3},
                {"name": "Bedroom1", "width": 9, "height": 8, "max_expansion": 4},
                {"name": "Bedroom2", "width": 9, "height": 8, "max_expansion": 4},
                {"name": "Bathroom1", "width": 5, "height": 5, "max_expansion": 2},
                {"name": "Bathroom2", "width": 5, "height": 5, "max_expansion": 2}
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
    
    print("\n" + "="*80)
    print("TEST: Space Optimization with Fixed Rooms")
    print("="*80)
    
    result = Documents.get_space_optimized_floorplan(request_data)
    pprint.pprint(result)
    
    return result


def test_space_optimization_large():
    """Test with the large example from the requirements"""
    request_data = {
        "request_id": "req_big_001",
        "engine": "SpaceOptimization",
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
    
    print("\n" + "="*80)
    print("TEST: Large Space Optimization Example")
    print("="*80)
    
    result = Documents.get_space_optimized_floorplan(request_data)
    pprint.pprint(result)
    
    return result


def test_space_optimization_no_expansion():
    """Test without expansion enabled"""
    request_data = {
        "request_id": "test_no_expand_001",
        "engine": "SpaceOptimization",
        "params": {
            "regions": [
                {"x": 0, "y": 0, "width": 25, "height": 20}
            ],
            "fixed_rooms": [],
            "rooms": [
                {"name": "Room1", "width": 8, "height": 6, "max_expansion": 5},
                {"name": "Room2", "width": 7, "height": 5, "max_expansion": 4},
                {"name": "Room3", "width": 6, "height": 6, "max_expansion": 3}
            ],
            "adjacency": [
                ["Room1", "Room2"]
            ],
            "non_adjacency": [],
            "entrance_coords": None
        },
        "ops": ["place", "score"]  # No expand or compact
    }
    
    print("\n" + "="*80)
    print("TEST: Space Optimization WITHOUT Expansion")
    print("="*80)
    
    result = Documents.get_space_optimized_floorplan(request_data)
    pprint.pprint(result)
    
    return result


def test_space_optimization_l_shape():
    """Test with L-shaped region"""
    request_data = {
        "request_id": "test_lshape_001",
        "engine": "SpaceOptimization",
        "params": {
            "regions": [
                {"x": 0, "y": 0, "width": 20, "height": 15},
                {"x": 0, "y": 15, "width": 10, "height": 10}
            ],
            "fixed_rooms": [],
            "rooms": [
                {"name": "Living", "width": 10, "height": 8, "max_expansion": 5},
                {"name": "Kitchen", "width": 7, "height": 6, "max_expansion": 3},
                {"name": "Bedroom", "width": 8, "height": 7, "max_expansion": 4},
                {"name": "Bathroom", "width": 5, "height": 5, "max_expansion": 2}
            ],
            "adjacency": [
                ["Living", "Kitchen"],
                ["Bedroom", "Bathroom"]
            ],
            "non_adjacency": [
                ["Kitchen", "Bedroom"]
            ],
            "entrance_coords": [[0, 5], [0, 8]]
        },
        "ops": ["place", "compact", "expand", "score"]
    }
    
    print("\n" + "="*80)
    print("TEST: Space Optimization with L-shaped Region")
    print("="*80)
    
    result = Documents.get_space_optimized_floorplan(request_data)
    pprint.pprint(result)
    
    return result


def save_result_to_file(result, filename):
    """Save test result to a JSON file"""
    with open(filename, 'w') as f:
        json.dump(result, f, indent=2)
    print(f"\n✓ Result saved to: {filename}")


if __name__ == '__main__':
    print("\n" + "="*80)
    print("SPACE OPTIMIZATION API TEST SUITE")
    print("="*80)
    
    # Run all tests
    try:
        # Test 1: Simple
        result1 = test_space_optimization_simple()
        if result1['status'] == 'ok':
            print("\n✓ Test 1 PASSED: Simple Space Optimization")
            save_result_to_file(result1, 'test_result_simple.json')
        else:
            print("\n✗ Test 1 FAILED")
            print(f"Error: {result1.get('error', {}).get('message', 'Unknown error')}")
        
        # Test 2: With Fixed Rooms
        result2 = test_space_optimization_with_fixed_rooms()
        if result2['status'] == 'ok':
            print("\n✓ Test 2 PASSED: With Fixed Rooms")
            save_result_to_file(result2, 'test_result_fixed.json')
        else:
            print("\n✗ Test 2 FAILED")
            print(f"Error: {result2.get('error', {}).get('message', 'Unknown error')}")
        
        # Test 3: Large Example
        result3 = test_space_optimization_large()
        if result3['status'] == 'ok':
            print("\n✓ Test 3 PASSED: Large Example")
            save_result_to_file(result3, 'test_result_large.json')
        else:
            print("\n✗ Test 3 FAILED")
            print(f"Error: {result3.get('error', {}).get('message', 'Unknown error')}")
        
        # Test 4: No Expansion
        result4 = test_space_optimization_no_expansion()
        if result4['status'] == 'ok':
            print("\n✓ Test 4 PASSED: No Expansion")
            save_result_to_file(result4, 'test_result_no_expand.json')
        else:
            print("\n✗ Test 4 FAILED")
            print(f"Error: {result4.get('error', {}).get('message', 'Unknown error')}")
        
        # Test 5: L-Shape
        result5 = test_space_optimization_l_shape()
        if result5['status'] == 'ok':
            print("\n✓ Test 5 PASSED: L-shaped Region")
            save_result_to_file(result5, 'test_result_lshape.json')
        else:
            print("\n✗ Test 5 FAILED")
            print(f"Error: {result5.get('error', {}).get('message', 'Unknown error')}")
        
        print("\n" + "="*80)
        print("TEST SUITE COMPLETED")
        print("="*80)
        
    except Exception as e:
        print(f"\n✗ CRITICAL ERROR: {str(e)}")
        import traceback
        traceback.print_exc()
