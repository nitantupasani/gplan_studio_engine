"""
Simple Test API for GA Optimization
Just paste your request data and run to get output.

NOTE: GA optimization takes 2-3 minutes to complete.
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
        "name": "1",
        "color": "#FFE5B4",
        "walls": [
          {
            "id": "wall-001",
            "roomIds": ["room-living-001"],
            "x1": 0,
            "y1": 0,
            "x2": 0,
            "y2": 10
          },
          {
            "id": "wall-002",
            "roomIds": ["room-living-001"],
            "x1": 0,
            "y1": 10,
            "x2": 12,
            "y2": 10
          },
          {
            "id": "wall-003",
            "roomIds": ["room-living-001", "room-kitchen-002"],
            "x1": 12,
            "y1": 10,
            "x2": 12,
            "y2": 4
          },
          {
            "id": "wall-004",
            "roomIds": ["room-living-001"],
            "x1": 12,
            "y1": 4,
            "x2": 0,
            "y2": 4
          },
          {
            "id": "wall-005",
            "roomIds": ["room-living-001"],
            "x1": 0,
            "y1": 4,
            "x2": 0,
            "y2": 0
          }
        ]
      },
      {
        "id": "room-kitchen-002",
        "name": "2",
        "color": "#B4D7FF",
        "walls": [
          {
            "id": "wall-003",
            "roomIds": ["room-living-001", "room-kitchen-002"],
            "x1": 12,
            "y1": 10,
            "x2": 12,
            "y2": 4
          },
          {
            "id": "wall-006",
            "roomIds": ["room-kitchen-002"],
            "x1": 12,
            "y1": 4,
            "x2": 20,
            "y2": 4
          },
          {
            "id": "wall-007",
            "roomIds": ["room-kitchen-002"],
            "x1": 20,
            "y1": 4,
            "x2": 20,
            "y2": 10
          },
          {
            "id": "wall-008",
            "roomIds": ["room-kitchen-002"],
            "x1": 20,
            "y1": 10,
            "x2": 12,
            "y2": 10
          }
        ]
      },
      {
        "id": "room-bedroom1-003",
        "name": "3",
        "color": "#FFB4E5",
        "walls": [
          {
            "id": "wall-009",
            "roomIds": ["room-bedroom1-003"],
            "x1": 0,
            "y1": 10,
            "x2": 0,
            "y2": 20
          },
          {
            "id": "wall-010",
            "roomIds": ["room-bedroom1-003"],
            "x1": 0,
            "y1": 20,
            "x2": 10,
            "y2": 20
          },
          {
            "id": "wall-011",
            "roomIds": ["room-bedroom1-003"],
            "x1": 10,
            "y1": 20,
            "x2": 10,
            "y2": 10
          },
          {
            "id": "wall-012",
            "roomIds": ["room-bedroom1-003"],
            "x1": 10,
            "y1": 10,
            "x2": 0,
            "y2": 10
          }
        ]
      },
      {
        "id": "room-bathroom-004",
        "name": "4",
        "color": "#B4FFE5",
        "walls": [
          {
            "id": "wall-013",
            "roomIds": ["room-bathroom-004"],
            "x1": 10,
            "y1": 10,
            "x2": 10,
            "y2": 16
          },
          {
            "id": "wall-014",
            "roomIds": ["room-bathroom-004"],
            "x1": 10,
            "y1": 16,
            "x2": 16,
            "y2": 16
          },
          {
            "id": "wall-015",
            "roomIds": ["room-bathroom-004"],
            "x1": 16,
            "y1": 16,
            "x2": 16,
            "y2": 10
          },
          {
            "id": "wall-016",
            "roomIds": ["room-bathroom-004"],
            "x1": 16,
            "y1": 10,
            "x2": 10,
            "y2": 10
          }
        ]
      }
    ],
    "walls": [
      {
        "id": "wall-001",
        "roomIds": ["room-living-001"],
        "x1": 0,
        "y1": 0,
        "x2": 0,
        "y2": 10
      },
      {
        "id": "wall-002",
        "roomIds": ["room-living-001"],
        "x1": 0,
        "y1": 10,
        "x2": 12,
        "y2": 10
      },
      {
        "id": "wall-003",
        "roomIds": ["room-living-001", "room-kitchen-002"],
        "x1": 12,
        "y1": 10,
        "x2": 12,
        "y2": 4
      },
      {
        "id": "wall-004",
        "roomIds": ["room-living-001"],
        "x1": 12,
        "y1": 4,
        "x2": 0,
        "y2": 4
      }
    ],
    "labels": [
      {
        "x": 6,
        "y": 7,
        "text": "1",
        "roomId": "room-living-001"
      },
      {
        "x": 16,
        "y": 7,
        "text": "2",
        "roomId": "room-kitchen-002"
      },
      {
        "x": 5,
        "y": 15,
        "text": "3",
        "roomId": "room-bedroom1-003"
      },
      {
        "x": 13,
        "y": 13,
        "text": "4",
        "roomId": "room-bathroom-004"
      }
    ],
    "windows": [],
    "doors": []
  }
}


# ============================================================================
# RUN THE TEST
# ============================================================================

def run_test():
    """Run the GA optimization test"""
    print("\n" + "="*80)
    print("GA OPTIMIZATION TEST")
    print("="*80)
    print("\n⚠️  NOTE: This will take approximately 2-3 minutes to complete.")
    print("="*80)
    
    print("\n📥 INPUT REQUEST:")
    print("-"*80)
    pprint.pprint(request_data, width=120)
    
    print("\n⚙️  PROCESSING GA OPTIMIZATION...")
    print("-"*80)
    print("Starting genetic algorithm with 600 generations...")
    print("This may take a while. Please wait...\n")
    
    # Call the API
    result = Documents.get_ga_optimized_floorplan(request_data)
    
    print("\n📤 OUTPUT RESULT:")
    print("-"*80)
    
    if result['status'] == 'success':
        print("✅ SUCCESS!")
        print("\n" + "="*80)
        print("FULL RESULT:")
        print("="*80)
        pprint.pprint(result, width=120)
        
        # Display key metrics
        print("\n" + "="*80)
        print("KEY METRICS:")
        print("="*80)
        if 'data' in result and 'ga_optimization' in result['data']:
            ga_info = result['data']['ga_optimization']
            print(f"  Status: {ga_info.get('status', 'N/A')}")
            print(f"  Solution Chromosome: {ga_info.get('solution_chromosome', 'N/A')}")
        
        if 'data' in result and 'rooms' in result['data']:
            print(f"\n  Optimized Rooms: {len(result['data']['rooms'])}")
            for room in result['data']['rooms']:
                bounds = room.get('optimized_bounds', {})
                print(f"    - {room['name']}: bounds={bounds}")
        
        print("\n" + "="*80)
        print("✅ TEST COMPLETED SUCCESSFULLY")
        print("="*80)
        
    else:
        print("❌ FAILED!")
        print("\n" + "="*80)
        print("ERROR DETAILS:")
        print("="*80)
        pprint.pprint(result, width=120)
        
        if 'error' in result:
            print("\n⚠️  Error Message:")
            print(f"   {result['error'].get('message', 'Unknown error')}")
        
        print("\n" + "="*80)
        print("❌ TEST FAILED")
        print("="*80)


def validate_request(req_data):
    """Validate the request format"""
    required_fields = ['request_id', 'engine', 'params']
    for field in required_fields:
        if field not in req_data:
            print(f"❌ Missing required field: {field}")
            return False
    
    params = req_data['params']
    required_params = ['plot_width', 'plot_height', 'rooms', 'walls']
    for param in required_params:
        if param not in params:
            print(f"❌ Missing required param: {param}")
            return False
    
    print("✅ Request validation passed")
    return True


if __name__ == "__main__":
    print("\n" + "="*80)
    print("SIMPLE GA OPTIMIZATION TEST")
    print("="*80)
    print("\nValidating request format...")
    
    if validate_request(request_data):
        print("\n🚀 Starting test...\n")
        run_test()
    else:
        print("\n❌ Request validation failed. Please fix the request format.")
