import sys
import time
import copy
import random
import datetime
import os
import json
import contextlib
# ProcessPoolExecutor import moved to run_ga for conditional usage
from collections import deque, defaultdict
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
from dataclasses import dataclass, field
from typing import List, Tuple, Dict, Any, Optional, Sequence, Set
import ctypes

@dataclass
class Wall:
    id: str
    roomIds: List[str]
    x1: float
    y1: float
    x2: float
    y2: float

@dataclass
class Label:
    x: float
    y: float
    text: str
    roomId: str

@dataclass
class Room:
    id: str
    name: str
    color: str
    walls: List[str]  # wall ids

@dataclass
class Floorplan:
    rooms: List[Room]
    walls: List[Wall]
    labels: List[Label]
    windows: List[dict]  # keep as dict for now
    doors: List[dict]
    plot_width: int
    plot_height: int

def parse_floorplan_json(json_data: dict) -> Floorplan:
    walls = [Wall(**wall) for wall in json_data['walls']]
    labels = [Label(**label) for label in json_data['labels']]
    rooms = [Room(id=room['id'], name=room['name'], color=room['color'], walls=[w['id'] for w in room['walls']]) for room in json_data['rooms']]
    return Floorplan(
        rooms=rooms,
        walls=walls,
        labels=labels,
        windows=json_data.get('windows', []),
        doors=json_data.get('doors', []),
        plot_width=json_data['plot_width'],
        plot_height=json_data['plot_height']
    )

# Get absolute path to shared library files
import platform

script_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(script_dir)

# Determine library extension based on platform
def get_lib_extension():
    system = platform.system()
    if system == 'Windows':
        return '.dll'
    elif system == 'Darwin':  # macOS
        return '.so'
    else:  # Linux and others
        return '.so'

lib_ext = get_lib_extension()

lib = ctypes.CDLL(os.path.join(parent_dir, f'bfs{lib_ext}'))
lib.count_corridor_components.argtypes = [ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int), ctypes.c_int, ctypes.c_int, ctypes.c_int]
lib.count_corridor_components.restype = ctypes.c_int

corridor_lib = ctypes.CDLL(os.path.join(parent_dir, f'corridor_creator{lib_ext}'))
corridor_lib.corridor_creator.argtypes = [ctypes.POINTER(ctypes.c_int), ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int]
corridor_lib.corridor_creator.restype = None

boundary_lib = ctypes.CDLL(os.path.join(parent_dir, f'boundary_accessible_corridors{lib_ext}'))
boundary_lib.count_boundary_accessible_corridors.argtypes = [ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int), ctypes.c_int, ctypes.c_int, ctypes.c_int]
boundary_lib.count_boundary_accessible_corridors.restype = ctypes.c_int

POPULATION_SIZE = 10
NUM_GENERATIONS = 30
INITIAL_MUTATION_RATE = 0.1
MUTATION_STRENGTH = 6 
TOURNAMENT_SIZE = 8

#adaptive mutation params
ENABLE_ADAPTIVE_MUTATION = True
STAGNATION_THRESHOLD = 10
MUTATION_RATE_INCREASE = 0.04
MAX_MUTATION_RATE = 0.65

CORRIDOR_WIDTH = 3
NEIGHBOR_OFFSETS = [(0, 1), (0, -1), (1, 0), (-1, 0)]

DEFAULT_ROOM_COLORS = [
    "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd",
    "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf"
]


WEIGHTS = {
    "area": 1.0,  #area penalty 
    "overlap": 3250, #overlap penalty
    "corridor_ratio": 10000, #penalty for deviation from ratio target 
    "corridor_conn": 25000, #corridor connectivity reward
    "boundary_corridor": 0, #penalty for boundary corridor cells 
    "boundary_accessible_corridor": 3300, #penalty for boundary entry points (holes where corridors leak to outside)
    "room_corridor_adj": 50000, #reward for rooms adjacent to corridors
    "isolated_rooms": 5000, #penalty for rooms completely surrounded by corridors 
}

_initial_rooms: Optional[Dict[int, "RoomGA"]] = None
_region_matrix: Optional[np.ndarray] = None
_fixed_room_ids: Optional[List[int]] = None 
_fitness_cache: Dict[Tuple[Tuple[int, int], ...], Tuple[float, Dict[str, Any]]] = {}

def _init_worker(initial_rooms: Dict[int, "RoomGA"], region_matrix: np.ndarray, fixed_room_ids: Optional[List[int]] = None) -> None:
    global _initial_rooms, _region_matrix, _fixed_room_ids
    _initial_rooms = initial_rooms
    _region_matrix = region_matrix
    _fixed_room_ids = fixed_room_ids

def _fitness_worker(chrom: Sequence[Tuple[int, int]]) -> Tuple[float, Dict[str, Any]]:
    # _initial_rooms and _region_matrix are set via initializer in worker
    assert _initial_rooms is not None and _region_matrix is not None
    return calculate_fitness_cached(list(chrom), _initial_rooms, _region_matrix, _fixed_room_ids)


CORRIDOR_ID = 0
CORRIDOR_FINAL = 99
TARGET_CORRIDOR_RATIO = 0.2  
MINIMUM_RATIO = 0.05

@dataclass
class RoomGA:
    id: int
    coords: List[Tuple[int, int]]  # List of (row, col) tuples
    block: bool = field(default=False)
    sub_coords: Optional[Dict[int, List[Tuple[int, int]]]] = field(default=None)
    name: str = ""
    original_data: dict = field(default_factory=dict)
    min_r: int = field(init=False)
    max_r: int = field(init=False)
    min_c: int = field(init=False)
    max_c: int = field(init=False)
    area: int = field(init=False)
    
    def __post_init__(self):
        self.min_r = min(r for r, c in self.coords)
        self.max_r = max(r for r, c in self.coords)
        self.min_c = min(c for r, c in self.coords)
        self.max_c = max(c for r, c in self.coords)
        self.area = len(self.coords)

# def corridor_creator(matrix: List[List[int]], corridor_width: int = 2) -> np.ndarray:
#     # corridor generation rules
#     if not matrix or not matrix[0]:
#         return np.array([])

#     rows: int = len(matrix)
#     cols: int = len(matrix[0])
#     new_matrix: np.ndarray = np.array(matrix, dtype=int)

#     EMPTY: int = 0
#     CORRIDOR_FINAL: int = 99

#     room_ids = set()
#     for r in range(rows):
#         for c in range(cols):
#             if new_matrix[r, c] > 0:
#                 room_ids.add(new_matrix[r, c])

#     for room_id in room_ids:

#         coords = [(r, c) for r in range(rows) for c in range(cols) if new_matrix[r, c] == room_id]
#         if not coords:
#             continue
#         min_r = min(r for r, c in coords)
#         max_r = max(r for r, c in coords)
#         min_c = min(c for r, c in coords)
#         max_c = max(c for r, c in coords)

#         for c in range(min_c, max_c + 1):
#             r = min_r
#             for dr in range(1, corridor_width + 2):
#                 nr = r - dr
#                 if nr < 0:
#                     break
#                 if new_matrix[nr, c] > 0 and new_matrix[nr, c] != room_id:
#                     for rr in range(nr + 1, r):
#                         if new_matrix[rr, c] == EMPTY:
#                             new_matrix[rr, c] = CORRIDOR_FINAL
#                     # break

#         for c in range(min_c, max_c + 1):
#             r = max_r
#             for dr in range(1, corridor_width + 2):
#                 nr = r + dr
#                 if nr >= rows:
#                     break
#                 if new_matrix[nr, c] > 0 and new_matrix[nr, c] != room_id:
#                     for rr in range(r + 1, nr):
#                         if new_matrix[rr, c] == EMPTY:
#                             new_matrix[rr, c] = CORRIDOR_FINAL
#                     # break

#         for r in range(min_r, max_r + 1):
#             c = min_c
#             for dc in range(1, corridor_width + 2):
#                 nc = c - dc
#                 if nc < 0:
#                     break
#                 if new_matrix[r, nc] > 0 and new_matrix[r, nc] != room_id:
#                     for cc in range(nc + 1, c):
#                         if new_matrix[r, cc] == EMPTY:
#                             new_matrix[r, cc] = CORRIDOR_FINAL
#                     # break

#         for r in range(min_r, max_r + 1):
#             c = max_c
#             for dc in range(1, corridor_width + 2):
#                 nc = c + dc
#                 if nc >= cols:
#                     break
#                 if new_matrix[r, nc] > 0 and new_matrix[r, nc] != room_id:
#                     for cc in range(c + 1, nc):
#                         if new_matrix[r, cc] == EMPTY:
#                             new_matrix[r, cc] = CORRIDOR_FINAL
#                     # break
#     # new_matrix[0, :] = np.where(new_matrix[0, :] == CORRIDOR_FINAL, EMPTY, new_matrix[0, :])
#     # new_matrix[-1, :] = np.where(new_matrix[-1, :] == CORRIDOR_FINAL, EMPTY, new_matrix[-1, :])
#     # new_matrix[:, 0] = np.where(new_matrix[:, 0] == CORRIDOR_FINAL, EMPTY, new_matrix[:, 0])
#     # new_matrix[:, -1] = np.where(new_matrix[:, -1] == CORRIDOR_FINAL, EMPTY, new_matrix[:, -1])

#     # Clear boundary corridors ONLY if they have no adjacent room
#     def has_room_neighbor(r: int, c: int) -> bool:
#         for dr, dc in [(1,0),(-1,0),(0,1),(0,-1)]:
#             nr, nc = r + dr, c + dc
#             if 0 <= nr < rows and 0 <= nc < cols:
#                 if new_matrix[nr, nc] > 0 and new_matrix[nr, nc] != CORRIDOR_FINAL:
#                     return True
#         return False

#     # Top row
#     for c in range(cols):
#         if new_matrix[0, c] == CORRIDOR_FINAL and not has_room_neighbor(0, c):
#             new_matrix[0, c] = EMPTY

#     # Bottom row
#     for c in range(cols):
#         if new_matrix[rows-1, c] == CORRIDOR_FINAL and not has_room_neighbor(rows-1, c):
#             new_matrix[rows-1, c] = EMPTY

#     # Left column
#     for r in range(rows):
#         if new_matrix[r, 0] == CORRIDOR_FINAL and not has_room_neighbor(r, 0):
#             new_matrix[r, 0] = EMPTY

#     # Right column
#     for r in range(rows):
#         if new_matrix[r, cols-1] == CORRIDOR_FINAL and not has_room_neighbor(r, cols-1):
#             new_matrix[r, cols-1] = EMPTY


#     return new_matrix

# def corridor_creator(matrix: List[List[int]], corridor_width: int = 2) -> np.ndarray:
#     """
#     Generate corridors by filling gaps between adjacent rooms.
#     Scans all empty cells and fills them if they lie between two different room IDs.
#     """
#     if not matrix or not matrix[0]:
#         return np.array([])
#     
#     rows: int = len(matrix)
#     cols: int = len(matrix[0])
#     new_matrix: np.ndarray = np.array(matrix, dtype=int)
#     EMPTY: int = 0
#     CORRIDOR_FINAL: int = 99
#     UNUSABLE: int = -1

#     def has_unusable_neighbor(r: int, c: int) -> bool:
#         """Check if a cell is adjacent to unusable space."""
#         for dr, dc in [(0, 1), (0, -1), (1, 0), (-1, 0)]:
#             nr, nc = r + dr, c + dc
#             if 0 <= nr < rows and 0 <= nc < cols:
#                 if new_matrix[nr, nc] == UNUSABLE:
#                     return True
#         return False

#     # Horizontal scan: fill gaps between rooms in same row
#     for r in range(rows):
#         c = 0
#         while c < cols:
#             # Find start of potential gap (first room cell)
#             if new_matrix[r, c] > 0:
#                 left_room = new_matrix[r, c]
#                 start_c = c
#                 # Skip over this room
#                 while c < cols and new_matrix[r, c] == left_room:
#                     c += 1
#                 # Now c points to first non-left_room cell
#                 # Scan for empty cells followed by a different room
#                 gap_start = c
#                 while c < cols and new_matrix[r, c] == EMPTY:
#                     c += 1
#                 gap_end = c
#                 gap_len = gap_end - gap_start
                
#                 # Check if we found a different room at the end
#                 if c < cols and new_matrix[r, c] > 0 and new_matrix[r, c] != left_room:
#                     # Gap is between two different rooms
#                     if 2 <= gap_len:
#                         all_valid = True
#                         for cc in range(gap_start, gap_end):
#                             if has_unusable_neighbor(r, cc):
#                                 all_valid = False
#                                 break

#                         if all_valid:
#                             for cc in range(gap_start, gap_end):
#                                 new_matrix[r, cc] = CORRIDOR_FINAL
#             else:
#                 c += 1
    
#     # Vertical scan: fill gaps between rooms in same column
#     for c in range(cols):
#         r = 0
#         while r < rows:
#             # Find start of potential gap (first room cell)
#             if new_matrix[r, c] > 0:
#                 top_room = new_matrix[r, c]
#                 start_r = r
#                 # Skip over this room
#                 while r < rows and new_matrix[r, c] == top_room:
#                     r += 1
#                 # Now r points to first non-top_room cell
#                 # Scan for empty cells followed by a different room
#                 gap_start = r
#                 while r < rows and new_matrix[r, c] == EMPTY:
#                     r += 1
#                 gap_end = r
#                 gap_len = gap_end - gap_start
                
#                 # Check if we found a different room at the end
#                 if r < rows and new_matrix[r, c] > 0 and new_matrix[r, c] != top_room:
#                     # Gap is between two different rooms
#                     if 2 <= gap_len <= corridor_width:
#                         all_valid = True
#                         for rr in range(gap_start, gap_end):
#                             if has_unusable_neighbor(rr, c):
#                                 all_valid = False
#                                 break
                        
#                         if all_valid:
#                             for rr in range(gap_start, gap_end):
#                                 new_matrix[rr, c] = CORRIDOR_FINAL
#             else:
#                 r += 1
    
#     # Conditional boundary clearing: only clear edge corridors with no room neighbors
#     def has_room_neighbor(r: int, c: int) -> bool:
#         for dr, dc in [(1,0),(-1,0),(0,1),(0,-1)]:
#             nr, nc = r + dr, c + dc
#             if 0 <= nr < rows and 0 <= nc < cols:
#                 if new_matrix[nr, nc] > 0 and new_matrix[nr, nc] != CORRIDOR_FINAL:
#                     return True
#         return False
    
#     # Top row
#     for c in range(cols):
#         if new_matrix[0, c] == CORRIDOR_FINAL and not has_room_neighbor(0, c):
#             new_matrix[0, c] = EMPTY
    
#     # Bottom row
#     for c in range(cols):
#         if new_matrix[rows-1, c] == CORRIDOR_FINAL and not has_room_neighbor(rows-1, c):
#             new_matrix[rows-1, c] = EMPTY
    
#     # Left column
#     for r in range(rows):
#         if new_matrix[r, 0] == CORRIDOR_FINAL and not has_room_neighbor(r, 0):
#             new_matrix[r, 0] = EMPTY
    
#     # Right column
#     for r in range(rows):
#         if new_matrix[r, cols-1] == CORRIDOR_FINAL and not has_room_neighbor(r, cols-1):
#             new_matrix[r, cols-1] = EMPTY
    
#     return new_matrix


def corridor_creator(matrix: List[List[int]], corridor_width: int = 2) -> np.ndarray:
    """
    Generate corridors by filling gaps between adjacent rooms.
    Calls the C implementation for better performance.
    """
    if not matrix or not matrix[0]:
        return np.array([])

    rows = len(matrix)
    cols = len(matrix[0])
    new_matrix = np.array(matrix, dtype=np.int32).flatten()

    # Call the C function
    corridor_lib.corridor_creator(
        new_matrix.ctypes.data_as(ctypes.POINTER(ctypes.c_int)),
        rows, cols, corridor_width, 99, -1, 0
    )

    return new_matrix.reshape((rows, cols))


def parse_floor_plan(grid, blocks: Optional[Dict[int, List[int]]] = None):
    rooms = {}
    for r in range(grid.shape[0]):
        for c in range(grid.shape[1]):
            value = grid[r, c]
            if isinstance(value, (int, np.integer)) and value > 0:
                if value not in rooms:
                    rooms[value] = []
                rooms[value].append((r, c))
            elif isinstance(value, str) and value.isdigit() and int(value) > 0:
                room_id = int(value)
                if room_id not in rooms:
                    rooms[room_id] = []
                rooms[room_id].append((r, c))
    
    room_objects = {room_id: RoomGA(room_id, coords) for room_id, coords in rooms.items()}
    
    if blocks:
        for block_id, room_ids in blocks.items():
            combined_coords = []
            sub_coords = {}
            for room_id in room_ids:
                if room_id in room_objects:
                    combined_coords.extend(room_objects[room_id].coords)
                    sub_coords[room_id] = room_objects[room_id].coords
                    del room_objects[room_id]
            if combined_coords:
                room_objects[block_id] = RoomGA(block_id, combined_coords, block=True, sub_coords=sub_coords)
    
    return room_objects

def parse_json_floorplan(json_data: dict) -> Tuple[Dict[int, "RoomGA"], np.ndarray, np.ndarray, Dict[int, str]]:
    """
    Parse JSON floorplan data and return:
    - rooms: Dict[int, RoomGA] - RoomGA objects with coordinates
    - initial_grid: np.ndarray - Initial placement matrix with room IDs
    - region_matrix: np.ndarray - Region matrix with '#' for unusable areas, usable area is the min rectangle enclosing all rooms
    - room_names: Dict[int, str] - Mapping from room ID to room name
    """
    plot_width = json_data['plot_width']
    plot_height = json_data['plot_height']
    
    # Initialize region_matrix with '#' (unusable)
    region_matrix = np.full((plot_height, plot_width), '#', dtype=str)
    
    # Initialize initial_grid with 0s
    initial_grid = np.zeros((plot_height, plot_width), dtype=int)
    
    rooms = {}
    
    # First pass: collect all walls for reference
    all_walls = {wall['id']: wall for wall in json_data['walls']}
    
    # Track overall bounds
    overall_min_r = plot_height
    overall_max_r = 0
    overall_min_c = plot_width
    overall_max_c = 0
    
    for room_data in json_data['rooms']:
        room_id = int(room_data['name'])  # Use name as ID (1, 2, 3, etc.)
        
        # Collect all wall coordinates to find initial bounding box
        all_x = []
        all_y = []
        for wall_id in [w['id'] for w in room_data['walls']]:
            wall = all_walls[wall_id]
            all_x.extend([wall['x1'], wall['x2']])
            all_y.extend([wall['y1'], wall['y2']])
        
        if not all_x or not all_y:
            continue
            
        # Initial bounding box (round to integers)
        min_c = int(min(all_x))
        max_c = int(max(all_x))
        min_r = int(min(all_y))
        max_r = int(max(all_y))
        
        # Adjust for shared walls
        for wall_data in room_data['walls']:
            wall = all_walls[wall_data['id']]
            room_ids = wall_data['roomIds']
            if len(room_ids) > 1:  # Shared wall
                x1, y1, x2, y2 = wall['x1'], wall['y1'], wall['x2'], wall['y2']
                if x1 == x2:  # Vertical wall
                    x = int(x1)
                    # Determine if this room is left or right of the wall
                    # For simplicity, check if room's center is left or right
                    room_center_c = (min_c + max_c) / 2
                    if room_center_c < x:
                        # Room is left of wall, so max_c should be x-1
                        max_c = min(max_c, x - 1)
                    else:
                        # Room is right of wall, so min_c should be x
                        min_c = max(min_c, x)
                elif y1 == y2:  # Horizontal wall
                    y = int(y1)
                    # Determine if this room is above or below the wall
                    room_center_r = (min_r + max_r) / 2
                    if room_center_r < y:
                        # Room is below wall, so max_r should be y-1
                        max_r = min(max_r, y - 1)
                    else:
                        # Room is above wall, so min_r should be y
                        min_r = max(min_r, y)
        
        # Ensure valid ranges
        min_r = max(0, min_r)
        max_r = min(plot_height - 1, max_r)
        min_c = max(0, min_c)
        max_c = min(plot_width - 1, max_c)
        
        # Update overall bounds
        overall_min_r = min(overall_min_r, min_r)
        overall_max_r = max(overall_max_r, max_r)
        overall_min_c = min(overall_min_c, min_c)
        overall_max_c = max(overall_max_c, max_c)
        
        # Create coordinates for the room (fill the adjusted bounding box)
        coords = []
        for r in range(min_r, max_r + 1):
            for c in range(min_c, max_c + 1):
                if 0 <= r < plot_height and 0 <= c < plot_width:
                    coords.append((r, c))
                    # Place in initial_grid
                    initial_grid[r, c] = room_id
        
        rooms[room_id] = RoomGA(room_id, coords, name=room_data['name'], original_data=room_data)
    
    # Mark the entire plot as usable (not just the bounding rectangle)
    region_matrix[:, :] = ' '
    
    room_names = {room_id: room.name for room_id, room in rooms.items()}
    
    return rooms, initial_grid, region_matrix, room_names


def floorplan_to_json(floorplan: Floorplan) -> Dict[str, Any]:
    """Serialize a :class:`Floorplan` into the JSON schema consumed by ``parse_floorplan_json``."""
    wall_lookup = {wall.id: wall for wall in floorplan.walls}

    rooms_payload = []
    for room in floorplan.rooms:
        room_walls = []
        for wall_id in room.walls:
            wall = wall_lookup.get(wall_id)
            room_walls.append({
                "id": wall_id,
                "roomIds": wall.roomIds[:] if wall else []
            })
        rooms_payload.append({
            "id": room.id,
            "name": room.name,
            "color": room.color,
            "walls": room_walls
        })

    walls_payload = [
        {
            "id": wall.id,
            "roomIds": wall.roomIds,
            "x1": wall.x1,
            "y1": wall.y1,
            "x2": wall.x2,
            "y2": wall.y2
        }
        for wall in floorplan.walls
    ]

    labels_payload = [
        {
            "x": label.x,
            "y": label.y,
            "text": label.text,
            "roomId": label.roomId
        }
        for label in floorplan.labels
    ]

    windows_payload = [dict(window) for window in floorplan.windows]
    doors_payload = [dict(door) for door in floorplan.doors]

    return {
        "rooms": rooms_payload,
        "walls": walls_payload,
        "labels": labels_payload,
        "windows": windows_payload,
        "doors": doors_payload,
        "plot_width": floorplan.plot_width,
        "plot_height": floorplan.plot_height
    }

def compute_valid_displacements(rooms: Dict[int, "RoomGA"], region_matrix: np.ndarray, fixed_room_ids: Optional[List[int]] = None) -> Dict[int, Tuple[Tuple[int, int], Tuple[int, int]]]:
    region_height, region_width = region_matrix.shape
    valid_ranges = {}
    
    if fixed_room_ids is None:
        fixed_room_ids = []
    
    for room_id, room in rooms.items():
        # Fixed rooms can't move - displacement is always (0, 0)
        if room_id in fixed_room_ids:
            valid_ranges[room_id] = ((0, 0), (0, 0))
            continue
        
        # Movable rooms - calculate valid displacement range
        room_min_r = room.min_r
        room_max_r = room.max_r
        room_min_c = room.min_c
        room_max_c = room.max_c
        
        max_dr_up = room_min_r
        max_dr_down = (region_height - 1) - room_max_r
        max_dc_left = room_min_c
        max_dc_right = (region_width - 1) - room_max_c
        
        valid_ranges[room_id] = ((-max_dr_up, max_dr_down), (-max_dc_left, max_dc_right))
    
    return valid_ranges


def apply_chromosome(rooms: Dict[int, "RoomGA"], chromosome: Sequence[Tuple[int, int]]) -> Dict[int, List[Tuple[int, int]]]:
    new_room_coords: Dict[int, List[Tuple[int, int]]] = {}

    for i, room_id in enumerate(sorted(rooms.keys())):
        dr, dc = chromosome[i]
        new_coords = [(r + dr, c + dc) for r, c in rooms[room_id].coords]
        new_room_coords[room_id] = new_coords

    return new_room_coords


def ga_solution_to_floorplan_json(
    chromosome: Sequence[Tuple[int, int]],
    initial_rooms: Dict[int, "RoomGA"],
    region_matrix: np.ndarray,
    room_names: Optional[Dict[int, str]] = None,
    windows: Optional[List[Dict[str, Any]]] = None,
    doors: Optional[List[Dict[str, Any]]] = None,
    room_colors: Optional[Dict[int, str]] = None
) -> Dict[str, Any]:
    """Convert a GA chromosome into the JSON format consumed by ``parse_floorplan_json``."""
    if not chromosome:
        raise ValueError("chromosome must contain at least one gene")

    if len(chromosome) != len(initial_rooms):
        raise ValueError("chromosome length must match the number of rooms used by the GA")

    displaced_coords = apply_chromosome(initial_rooms, chromosome)

    # Expand composite rooms (blocks) back into their constituent rooms to keep IDs consistent.
    drawable_rooms: Dict[int, List[Tuple[int, int]]] = {}
    for room in initial_rooms.values():
        coords = displaced_coords.get(room.id, room.coords)
        if room.block:
            if not coords or not room.sub_coords:
                continue
            old_min_r = room.min_r
            old_min_c = room.min_c
            new_min_r = min(r for r, _ in coords)
            new_min_c = min(c for _, c in coords)
            dr = new_min_r - old_min_r
            dc = new_min_c - old_min_c
            for sub_id, sub_coords in room.sub_coords.items():
                displaced_sub = [(r + dr, c + dc) for r, c in sub_coords]
                drawable_rooms[sub_id] = displaced_sub
        else:
            drawable_rooms[room.id] = coords

    if not drawable_rooms:
        raise ValueError("no drawable rooms were produced from the supplied chromosome")

    cell_to_room: Dict[Tuple[int, int], int] = {}
    for room_id, coords in drawable_rooms.items():
        for coord in coords:
            cell_to_room[coord] = room_id

    room_names_map = {room_id: str(room_id) for room_id in drawable_rooms.keys()}
    if room_names:
        for room_id, name in room_names.items():
            if room_id in room_names_map:
                room_names_map[room_id] = name

    color_map: Dict[int, str] = {}
    if room_colors:
        color_map.update(room_colors)
    for idx, room_id in enumerate(sorted(drawable_rooms.keys())):
        if room_id not in color_map:
            color_map[room_id] = DEFAULT_ROOM_COLORS[idx % len(DEFAULT_ROOM_COLORS)]

    edge_room_map: Dict[Tuple[Tuple[int, int], Tuple[int, int]], Set[int]] = {}
    room_edge_map: Dict[int, Set[Tuple[Tuple[int, int], Tuple[int, int]]]] = defaultdict(set)

    edge_specs = [
        ((-1, 0), lambda r, c: ((c, r), (c + 1, r))),
        ((1, 0), lambda r, c: ((c, r + 1), (c + 1, r + 1))),
        ((0, -1), lambda r, c: ((c, r), (c, r + 1))),
        ((0, 1), lambda r, c: ((c + 1, r), (c + 1, r + 1)))
    ]

    for room_id, coords in drawable_rooms.items():
        if not coords:
            continue
        for r, c in coords:
            for (dr, dc), edge_factory in edge_specs:
                neighbor = (r + dr, c + dc)
                if cell_to_room.get(neighbor) == room_id:
                    continue
                start, end = edge_factory(r, c)
                normalized_edge = tuple(sorted((start, end)))
                edge_room_map.setdefault(normalized_edge, set()).add(room_id)
                room_edge_map[room_id].add(normalized_edge)

    walls: List[Wall] = []
    edge_to_wall_id: Dict[Tuple[Tuple[int, int], Tuple[int, int]], str] = {}
    for idx, (edge, room_set) in enumerate(sorted(edge_room_map.items()), start=1):
        (x1, y1), (x2, y2) = edge
        wall_id = f"wall_{idx}"
        wall_room_names = [room_names_map[rid] for rid in sorted(room_set)]
        walls.append(Wall(id=wall_id, roomIds=wall_room_names, x1=x1, y1=y1, x2=x2, y2=y2))
        edge_to_wall_id[edge] = wall_id

    rooms_payload: List[Room] = []
    for room_id in sorted(drawable_rooms.keys()):
        wall_ids = [
            edge_to_wall_id[edge]
            for edge in sorted(room_edge_map.get(room_id, ()), key=lambda e: edge_to_wall_id[e])
        ]
        rooms_payload.append(
            Room(
                id=str(room_id),
                name=room_names_map[room_id],
                color=color_map[room_id],
                walls=wall_ids
            )
        )

    labels: List[Label] = []
    for room_id, coords in drawable_rooms.items():
        if not coords:
            continue
        avg_r = sum(r for r, _ in coords) / len(coords)
        avg_c = sum(c for _, c in coords) / len(coords)
        labels.append(
            Label(x=avg_c + 0.5, y=avg_r + 0.5, text=room_names_map[room_id], roomId=str(room_id))
        )

    floorplan = Floorplan(
        rooms=rooms_payload,
        walls=walls,
        labels=labels,
        windows=windows[:] if windows else [],
        doors=doors[:] if doors else [],
        plot_width=int(region_matrix.shape[1]),
        plot_height=int(region_matrix.shape[0])
    )

    return floorplan_to_json(floorplan)

def calculate_corridor_connectivity(layout_matrix: np.ndarray, region_matrix: np.ndarray) -> int:
    height, width = layout_matrix.shape
    layout_flat = layout_matrix.flatten()
    region_flat = np.array([ord(c) for row in region_matrix for c in row], dtype=np.int32)
    layout_ptr = layout_flat.ctypes.data_as(ctypes.POINTER(ctypes.c_int))
    region_ptr = region_flat.ctypes.data_as(ctypes.POINTER(ctypes.c_int))
    return lib.count_corridor_components(layout_ptr, region_ptr, height, width, CORRIDOR_FINAL)

def count_rooms_adjacent_to_corridor(layout_matrix: np.ndarray, initial_rooms: Dict[int, "RoomGA"], region_matrix: np.ndarray,) -> int:
    # counts number of rooms adjacent to corridors in full matrix
    rooms_adjacent = set()
    region_height, region_width = region_matrix.shape

    for r in range(region_height):
        for c in range(region_width):
            if layout_matrix[r, c] > 0 and layout_matrix[r, c] != CORRIDOR_FINAL:
                room_id = layout_matrix[r, c]
                if room_id in rooms_adjacent:
                    continue
                
                for dr, dc in NEIGHBOR_OFFSETS:
                    nr, nc = r + dr, c + dc
                    if (0 <= nr < region_height and 0 <= nc < region_width and 
                        layout_matrix[nr, nc] == CORRIDOR_FINAL and 
                        region_matrix[nr, nc] != '#'):
                        rooms_adjacent.add(room_id)
                        break # found adjacency, no need to check further
    return len(rooms_adjacent)

def count_isolated_rooms(layout_matrix: np.ndarray, initial_rooms: Dict[int, "RoomGA"], region_matrix: np.ndarray) -> int:
    # counts number of rooms that are completely surrounded by corridors (no adjacent rooms)
    isolated_rooms = set()
    region_height, region_width = region_matrix.shape

    for r in range(region_height):
        for c in range(region_width):
            if layout_matrix[r, c] > 0 and layout_matrix[r, c] != CORRIDOR_FINAL:
                room_id = layout_matrix[r, c]
                if room_id in isolated_rooms:
                    continue
                has_adjacent_room = False
                for dr, dc in NEIGHBOR_OFFSETS:
                    nr, nc = r + dr, c + dc
                    if (0 <= nr < region_height and 0 <= nc < region_width):
                        neighbor_val = layout_matrix[nr, nc]
                        if neighbor_val > 0 and neighbor_val != CORRIDOR_FINAL:
                            has_adjacent_room = True
                            break
                
                if not has_adjacent_room:
                    isolated_rooms.add(room_id)
    
    return len(isolated_rooms)

# def count_boundary_accessible_corridors(layout_matrix: np.ndarray, region_matrix: np.ndarray) -> int:
#     """
#     Counts corridors that are accessible from the outer boundary.
#     This includes:
#     1. Corridor cells directly on the boundary
#     2. Empty cells on/near boundary that are adjacent to corridors
#     """
#     region_height, region_width = region_matrix.shape
#     
#     entry_points = 0
#     
#     # Count corridor cells directly on the boundary
#     for r in range(region_height):
#         for c in range(region_width):
#             if layout_matrix[r, c] == CORRIDOR_FINAL and region_matrix[r, c] != '#':
#                 is_boundary = r == 0 or r == region_height - 1 or c == 0 or c == region_width - 1
#                 if is_boundary:
#                     entry_points += 1
#     
#     # Find boundary-accessible empty cells
#     boundary_empty = []
#     boundary_accessible = set()
#     
#     for r in range(region_height):
#         for c in range(region_width):
#             if region_matrix[r, c] != '#' and layout_matrix[r, c] == 0:  # Empty and usable
#                 is_boundary = r == 0 or r == region_height - 1 or c == 0 or c == region_width - 1
#                 is_adjacent_to_unusable = False
#                 
#                 for dr, dc in NEIGHBOR_OFFSETS:
#                     nr, nc = r + dr, c + dc
#                     if (0 <= nr < region_height and 0 <= nc < region_width and 
#                         region_matrix[nr, nc] == '#'):
#                         is_adjacent_to_unusable = True
#                         break
#                 
#                 if is_boundary or is_adjacent_to_unusable:
#                     boundary_empty.append((r, c))
#     
#     if boundary_empty:
#         visited = set()
#         q = deque(boundary_empty)
#         for cell in boundary_empty:
#             visited.add(cell)
#             boundary_accessible.add(cell)
#         
#         while q:
#             r, c = q.popleft()
#             for dr, dc in NEIGHBOR_OFFSETS:
#                 nr, nc = r + dr, c + dc
#                 if (0 <= nr < region_height and 0 <= nc < region_width and
#                     (nr, nc) not in visited and region_matrix[nr, nc] != '#' and
#                     layout_matrix[nr, nc] == 0):  
#                     visited.add((nr, nc))
#                     boundary_accessible.add((nr, nc))
#                     q.append((nr, nc))
#         
#         # Count empty cells adjacent to corridors
#         checked_empty_spaces = set()
#         for r in range(region_height):
#             for c in range(region_width):
#                 if (r, c) in boundary_accessible and (r, c) not in checked_empty_spaces:
#                     checked_empty_spaces.add((r, c))
#                     has_corridor_neighbor = False
#                     for dr, dc in NEIGHBOR_OFFSETS:
#                         nr, nc = r + dr, c + dc
#                         if (0 <= nr < region_height and 0 <= nc < region_width and
#                             layout_matrix[nr, nc] == CORRIDOR_FINAL and region_matrix[nr, nc] != '#'):
#                             has_corridor_neighbor = True
#                             break
#                     
#                     if has_corridor_neighbor:
#                         entry_points += 1
#     
#     return entry_points


def count_boundary_accessible_corridors(layout_matrix: np.ndarray, region_matrix: np.ndarray) -> int:
    """
    Counts corridors that are accessible from the outer boundary.
    Calls the C implementation for better performance.
    """
    height, width = layout_matrix.shape
    layout_flat = layout_matrix.flatten()
    region_flat = np.array([ord(c) for row in region_matrix for c in row], dtype=np.int32)

    return boundary_lib.count_boundary_accessible_corridors(
        layout_flat.ctypes.data_as(ctypes.POINTER(ctypes.c_int)),
        region_flat.ctypes.data_as(ctypes.POINTER(ctypes.c_int)),
        height, width, CORRIDOR_FINAL
    )


# def count_boundary_accessible_corridors(layout_matrix: np.ndarray, region_matrix: np.ndarray) -> int:
#     # counts corridors that are adjacent to empty spaces accessible from outer boundary
#     region_height, region_width = region_matrix.shape

#     boundary_empty = []
#     boundary_accessible = set()

#     for r in range(region_height):
#         for c in range(region_width):
#             if region_matrix[r, c] != '#' and layout_matrix[r, c] == 0:  # Empty and usable
#                 is_boundary = r == 0 or r == region_height - 1 or c == 0 or c == region_width - 1
#                 is_adjacent_to_unusable = False
                
#                 for dr, dc in NEIGHBOR_OFFSETS:
#                     nr, nc = r + dr, c + dc
#                     if (0 <= nr < region_height and 0 <= nc < region_width and 
#                         region_matrix[nr, nc] == '#'):
#                         is_adjacent_to_unusable = True
#                         break
                
#                 if is_boundary or is_adjacent_to_unusable:
#                     boundary_empty.append((r, c))

#     if not boundary_empty:
#         return 0

#     visited = set()
#     q = deque(boundary_empty)
#     for cell in boundary_empty:
#         visited.add(cell)
#         boundary_accessible.add(cell)

#     while q:
#         r, c = q.popleft()
#         for dr, dc in NEIGHBOR_OFFSETS:
#             nr, nc = r + dr, c + dc
#             if (0 <= nr < region_height and 0 <= nc < region_width and
#                 (nr, nc) not in visited and region_matrix[nr, nc] != '#' and
#                 layout_matrix[nr, nc] == 0):  
#                 visited.add((nr, nc))
#                 boundary_accessible.add((nr, nc))
#                 q.append((nr, nc))

#     entry_points = 0
#     checked_empty_spaces = set()

#     for r in range(region_height):
#         for c in range(region_width):
#             if (r, c) in boundary_accessible and (r, c) not in checked_empty_spaces:
#                 checked_empty_spaces.add((r, c))
#                 has_corridor_neighbor = False
#                 for dr, dc in NEIGHBOR_OFFSETS:
#                     nr, nc = r + dr, c + dc
#                     if (0 <= nr < region_height and 0 <= nc < region_width and
#                         layout_matrix[nr, nc] == CORRIDOR_FINAL and region_matrix[nr, nc] != '#'):
#                         has_corridor_neighbor = True
#                         break

#                 if has_corridor_neighbor:
#                     entry_points += 1

#     return entry_points

def build_room_adjacency_graph(layout_matrix: np.ndarray, initial_rooms: Dict[int, "RoomGA"], region_matrix: np.ndarray) -> Dict[int, set]:
    adj = {room_id: set() for room_id in initial_rooms}
    region_height, region_width = region_matrix.shape
    processed_pairs = set()
    
    for r in range(region_height):
        for c in range(region_width):
            if layout_matrix[r, c] <= 0 or layout_matrix[r, c] == CORRIDOR_FINAL:
                continue
                
            room_id = layout_matrix[r, c]
            
            for dr, dc in NEIGHBOR_OFFSETS:
                nr, nc = r + dr, c + dc
                if (0 <= nr < region_height and 0 <= nc < region_width):
                    neighbor_val = layout_matrix[nr, nc]
                    if (neighbor_val > 0 and neighbor_val != CORRIDOR_FINAL and 
                        neighbor_val != room_id):
                        pair = frozenset([room_id, neighbor_val])
                        if pair not in processed_pairs:
                            processed_pairs.add(pair)
                            adj[room_id].add(neighbor_val)
                            adj[neighbor_val].add(room_id)  
    
    return adj


def calculate_fitness(chromosome: Sequence[Tuple[int, int]], 
                     initial_rooms: Dict[int, "RoomGA"], 
                     region_matrix: np.ndarray,
                     fixed_room_ids: Optional[List[int]] = None) -> Tuple[float, Dict[str, Any]]:
    
    if not initial_rooms:
        return 0, {}
    
    displaced_coords = apply_chromosome(initial_rooms, chromosome)
    
    region_height, region_width = region_matrix.shape
    layout_matrix = np.zeros((region_height, region_width), dtype=int)
    layout_matrix[region_matrix == '#'] = -1
    
    # Track fixed room positions FIRST, before placing any rooms
    if fixed_room_ids is None:
        fixed_room_ids = []
    
    fixed_room_cells = {}  # Maps (r,c) -> room_id for fixed rooms
    for room_id in fixed_room_ids:
        if room_id in displaced_coords:
            for r, c in displaced_coords[room_id]:
                fixed_room_cells[(r, c)] = room_id
    
    # Now place rooms and check for overlaps
    overlap_count = 0
    movable_fixed_overlap = 0
    
    for room_id, coords in displaced_coords.items():
        is_fixed = room_id in fixed_room_ids

        if is_fixed:
            # Place fixed rooms without any overlap checks
            for r, c in coords:
                layout_matrix[r, c] = room_id
            continue  # Skip to next room

        # Movable rooms: enforce no-entry into fixed room cells
        for r, c in coords:
            # Hard block: movable room may not occupy fixed-room cells
            if (r, c) in fixed_room_cells:
                movable_fixed_overlap += 1
                # Still write the id so downstream code has a consistent matrix
                layout_matrix[r, c] = room_id
                continue

            # Regular overlap/placement logic for movable rooms only
            if region_matrix[r, c] == '#':
                overlap_count += 1
            elif layout_matrix[r, c] == 0:
                layout_matrix[r, c] = room_id
            else:
                existing_room = layout_matrix[r, c]
                # Count as overlap only if colliding with a different room
                if existing_room != room_id and existing_room > 0:
                    overlap_count += 1
                layout_matrix[r, c] = room_id

    
    # Rest of the function remains the same...
    layout_matrix = corridor_creator(layout_matrix.tolist(), CORRIDOR_WIDTH)
    
    total_room_cells = sum(len(coords) for coords in displaced_coords.values())
    corridor_cells = np.sum(layout_matrix == CORRIDOR_FINAL)
    actual_used_area = total_room_cells + corridor_cells
    corridor_ratio = corridor_cells / (actual_used_area + 1e-6)
    
    total_cells = region_height * region_width
    unusable_cells = np.sum(region_matrix == '#')
    total_usable_space = total_cells - unusable_cells
    remaining_empty_space = total_usable_space - total_room_cells
    
    if remaining_empty_space < 0.25 * total_usable_space:
        dynamic_target_ratio = remaining_empty_space / total_usable_space if total_usable_space > 0 else TARGET_CORRIDOR_RATIO
    else:
        dynamic_target_ratio = TARGET_CORRIDOR_RATIO
    
    boundary_corridor_count = np.sum(layout_matrix[0, :] == CORRIDOR_FINAL) + \
                             np.sum(layout_matrix[-1, :] == CORRIDOR_FINAL) + \
                             np.sum(layout_matrix[:, 0] == CORRIDOR_FINAL) + \
                             np.sum(layout_matrix[:, -1] == CORRIDOR_FINAL)
    
    isolated_room_count = count_isolated_rooms(layout_matrix, initial_rooms, region_matrix)
    boundary_accessible_corridor_count = count_boundary_accessible_corridors(layout_matrix, region_matrix)
    
    area_penalty = actual_used_area * WEIGHTS["area"]
    overlap_penalty = overlap_count * WEIGHTS["overlap"]
    boundary_corridor_penalty = boundary_corridor_count * WEIGHTS["boundary_corridor"]
    boundary_accessible_corridor_penalty = boundary_accessible_corridor_count * WEIGHTS["boundary_accessible_corridor"]
    
    corridor_ratio_deviation = abs(corridor_ratio - dynamic_target_ratio)
    corridor_ratio_penalty = corridor_ratio_deviation * WEIGHTS["corridor_ratio"]
    isolated_rooms_penalty = isolated_room_count * WEIGHTS["isolated_rooms"]
    
    num_corridor_components = calculate_corridor_connectivity(layout_matrix, region_matrix)
    corridor_conn_penalty = (num_corridor_components - 1) * WEIGHTS["corridor_conn"] if num_corridor_components > 1 else 0
    
    num_adj_rooms = count_rooms_adjacent_to_corridor(layout_matrix, initial_rooms, region_matrix)
    adj_ratio = num_adj_rooms / len(initial_rooms) if initial_rooms else 0
    room_corridor_adj_penalty = (1 - adj_ratio) * WEIGHTS["room_corridor_adj"]
    
    # Add HUGE penalty for movable-fixed room overlap
    movable_fixed_overlap_penalty = movable_fixed_overlap * 10000
    
    base_reward = WEIGHTS["corridor_conn"] + WEIGHTS["room_corridor_adj"]
    
    total_penalties = (area_penalty + overlap_penalty + corridor_ratio_penalty + 
                      boundary_corridor_penalty + boundary_accessible_corridor_penalty + 
                      isolated_rooms_penalty + corridor_conn_penalty + 
                      room_corridor_adj_penalty + movable_fixed_overlap_penalty)
    
    fitness = base_reward - total_penalties
    
    stats = {
        "base_reward": base_reward,
        "total_penalties": total_penalties,
        "corridor_connectivity_penalty": corridor_conn_penalty,
        "num_corridor_components": num_corridor_components,
        "overlap": overlap_count,
        "movable_fixed_overlap": movable_fixed_overlap,
        "movable_fixed_overlap_penalty": movable_fixed_overlap_penalty,
        "corridor_ratio": corridor_ratio,
        "corridor_ratio_deviation": corridor_ratio_deviation,
        "target_ratio": dynamic_target_ratio,
        "actual_area": actual_used_area,
        "boundary_corridors": boundary_corridor_count,
        "boundary_entry_points": boundary_accessible_corridor_count,
        "rooms_adjacent_to_corridor": num_adj_rooms,
        "room_corridor_adjacency_ratio": adj_ratio,
        "room_corridor_adj_penalty": room_corridor_adj_penalty,
        "isolated_rooms": isolated_room_count,
    }
    
    return fitness, stats

def calculate_fitness_cached(chromosome: Sequence[Tuple[int, int]], 
                            initial_rooms: Dict[int, "RoomGA"], 
                            region_matrix: np.ndarray,
                            fixed_room_ids: Optional[List[int]] = None) -> Tuple[float, Dict[str, Any]]:
    """Cached version of calculate_fitness to avoid redundant calculations."""
    key = tuple(chromosome)
    if key in _fitness_cache:
        return _fitness_cache[key]
    val = calculate_fitness(chromosome, initial_rooms, region_matrix, fixed_room_ids)
    _fitness_cache[key] = val
    return val


def selection(population: List[Sequence[Tuple[int, int]]], fitnesses: List[float]) -> Sequence[Tuple[int, int]]:
    # Tournament selection
    tournament = random.sample(list(zip(population, fitnesses)), TOURNAMENT_SIZE)
    tournament.sort(key=lambda x: x[1], reverse=True)
    return tournament[0][0]

def crossover(parent1: Sequence[Tuple[int, int]], parent2: Sequence[Tuple[int, int]]) -> List[Tuple[int, int]]:
    # Uniform crossover
    child: List[Tuple[int, int]] = []
    for i in range(len(parent1)):
        if random.random() < 0.5:
            child.append(parent1[i])
        else:
            child.append(parent2[i])
    return child

def mutation(chromosome: Sequence[Tuple[int, int]], mutation_rate: float, valid_displacements: Dict[int, Tuple[Tuple[int, int], Tuple[int, int]]], initial_rooms: Dict[int, "RoomGA"], sorted_room_ids: List[int]) -> List[Tuple[int, int]]:
    # Creep mutation with valid range constraints
    mutated_chromosome: List[Tuple[int, int]] = []
    
    for i, gene in enumerate(chromosome):
        room_id = sorted_room_ids[i]
        dr_range, dc_range = valid_displacements[room_id]
        
        if random.random() < mutation_rate:
            dr, dc = gene
            dr += random.randint(-MUTATION_STRENGTH, MUTATION_STRENGTH)
            dc += random.randint(-MUTATION_STRENGTH, MUTATION_STRENGTH)
            # Constrain to valid ranges
            dr = max(dr_range[0], min(dr_range[1], dr))
            dc = max(dc_range[0], min(dc_range[1], dc))
            mutated_chromosome.append((dr, dc))
        else:
            mutated_chromosome.append(gene)
    return mutated_chromosome

def run_ga(initial_grid: np.ndarray, 
           region_matrix: np.ndarray, 
           room_names: Optional[Dict[int, str]] = None, 
           room_dimensions: Optional[Dict[int, Tuple[int, int]]] = None, 
           corridor_width: int = 2, 
           fixed_room_ids: Optional[List[int]] = None,
           max_workers: int = 1) -> Optional[List[Tuple[int, int]]]:
    """
    Run genetic algorithm to optimize room layout with corridor generation.
    Optimized for larger grid sizes with adaptive parameters.
    """
    global CORRIDOR_WIDTH
    CORRIDOR_WIDTH = corridor_width
    
    initial_rooms = parse_floor_plan(initial_grid)
    num_genes = len(initial_rooms)
    sorted_room_ids = sorted(initial_rooms.keys())
    valid_displacements = compute_valid_displacements(initial_rooms, region_matrix, fixed_room_ids)
    
    start_time = time.time()
    restart_count = 0
    max_restarts = 10
    good_restart_chromosome = None
    
    while restart_count <= max_restarts:
        # Initialize population - either from good chromosome or random
        if good_restart_chromosome is not None and restart_count > 0:
            population = [good_restart_chromosome.copy()]
            while len(population) < POPULATION_SIZE:
                mutated = mutation(good_restart_chromosome, INITIAL_MUTATION_RATE * 2, 
                                 valid_displacements, initial_rooms, sorted_room_ids)
                population.append(mutated)
        else:
            population = []
            for _ in range(POPULATION_SIZE):
                chromosome = []
                for room_id in sorted_room_ids:
                    dr_range, dc_range = valid_displacements[room_id]
                    dr = random.randint(dr_range[0], dr_range[1])
                    dc = random.randint(dc_range[0], dc_range[1])
                    chromosome.append((dr, dc))
                population.append(chromosome)
        
        # Initialize tracking variables
        best_chromosome_overall = None
        best_fitness_overall = -float('inf')
        best_stats_overall = {}  # ADD THIS - store stats with best chromosome
        best_gen_found = 0       # ADD THIS - track which generation found best
        current_mutation_rate = INITIAL_MUTATION_RATE
        generations_since_improvement = 0
        halfway_point = NUM_GENERATIONS // 2
        should_restart = False
        
        # Execution context setup
        if max_workers == 1:
            # Simple serial execution - no globals, no multitasking overhead
            class SerialExecutor:
                def map(self, _ignored_func, items):
                    # We ignore the passed worker function (which uses globals)
                    # and call the logic directly using local variables from closure
                    return [calculate_fitness_cached(list(item), initial_rooms, region_matrix, fixed_room_ids) 
                            for item in items]
            
            executor_ctx = contextlib.nullcontext(SerialExecutor())
        else:
            from concurrent.futures import ProcessPoolExecutor
            executor_ctx = ProcessPoolExecutor(max_workers=max_workers, initializer=_init_worker, 
                                            initargs=(initial_rooms, region_matrix, fixed_room_ids))

        # Run optimization
        with executor_ctx as executor:
            
            for generation in range(NUM_GENERATIONS):
                # Evaluate fitness for all individuals
                fitnesses_with_stats = list(executor.map(_fitness_worker, population))
                fitness_scores = [f[0] for f in fitnesses_with_stats]
                
                # Track best individual
                best_idx = np.argmax(fitness_scores)
                best_fitness_gen = fitness_scores[best_idx]
                
                if best_fitness_gen > best_fitness_overall:
                    best_fitness_overall = best_fitness_gen
                    best_chromosome_overall = copy.deepcopy(population[best_idx])
                    best_stats_overall = copy.deepcopy(fitnesses_with_stats[best_idx][1])  # STORE STATS
                    best_gen_found = generation  # TRACK GENERATION
                    generations_since_improvement = 0
                    
                    # Get stats for printing
                    best_stats = fitnesses_with_stats[best_idx][1]
                    print(f"\nGen {generation+1:3d}: New Best! Fitness={best_fitness_overall:.2f} | "
                          f"Room-Corr Adj={best_stats['rooms_adjacent_to_corridor']}/{len(initial_rooms)} | "
                          f"Corridor Ratio={best_stats['corridor_ratio']:.3f} (target: {best_stats['target_ratio']:.3f}) | "
                          f"Overlaps={best_stats['overlap']} | "
                          f"Corridor Components={best_stats['num_corridor_components']} | "
                          f"Boundary Entry Points={best_stats['boundary_entry_points']} | "
                          f"Isolated Rooms={best_stats['isolated_rooms']}")
                else:
                    generations_since_improvement += 1
                
                # Check for good restart chromosome before halfway
                if generation + 1 < halfway_point:
                    current_best_stats = fitnesses_with_stats[best_idx][1]
                    num_corridor_components = current_best_stats['num_corridor_components']
                    adj_ratio = current_best_stats['room_corridor_adjacency_ratio']
                    corridor_ratio = current_best_stats['corridor_ratio']
                    
                    if num_corridor_components == 1 and adj_ratio == 1.0 and corridor_ratio >= 0.10:
                        good_restart_chromosome = population[best_idx].copy()
                
                # Halfway point check - restart if criteria not met
                if generation + 1 == halfway_point:
                    current_best_stats = fitnesses_with_stats[best_idx][1]
                    num_corridor_components = current_best_stats['num_corridor_components']
                    adj_ratio = current_best_stats['room_corridor_adjacency_ratio']
                    corridor_ratio = current_best_stats['corridor_ratio']
                    num_entry_points = current_best_stats['boundary_entry_points']
                    overlap_count = current_best_stats['overlap']
                    
                    if (num_corridor_components > 2 or adj_ratio != 1.0 or 
                        corridor_ratio < 0.10 or num_entry_points != 0 or overlap_count > 5):
                        
                        if good_restart_chromosome is not None:
                            print(f"\nHalfway check failed: Components={num_corridor_components} (max 2), "
                                  f"Room-Corr Ratio={adj_ratio:.3f} (need 1.0), "
                                  f"Corridor Ratio={corridor_ratio:.3f} (min 0.10), "
                                  f"Entry Points={num_entry_points} (should be 0), "
                                  f"Overlaps={overlap_count} (max 5)")
                            print("Restarting GA with stored good chromosome...")
                        else:
                            print(f"\nHalfway check failed - restarting with random population...")
                        
                        should_restart = True
                        restart_count += 1
                        break
                
                # Adaptive mutation - increase rate if stagnating
                if ENABLE_ADAPTIVE_MUTATION and generations_since_improvement >= STAGNATION_THRESHOLD:
                    current_mutation_rate = min(current_mutation_rate + MUTATION_RATE_INCREASE, MAX_MUTATION_RATE)
                    generations_since_improvement = 0
                
                # Create new population
                new_population = []
                new_population.append(population[best_idx])  # Elitism
                
                while len(new_population) < POPULATION_SIZE:
                    parent1 = selection(population, fitness_scores)
                    parent2 = selection(population, fitness_scores)
                    child = crossover(parent1, parent2)
                    child = mutation(child, current_mutation_rate, valid_displacements, 
                                   initial_rooms, sorted_room_ids)
                    new_population.append(child)
                
                population = new_population
                
                # Progress indicator
                sys.stdout.write(f"\rGeneration {generation+1}/{NUM_GENERATIONS}")
                sys.stdout.flush()
            
            if not should_restart:
                break
    
    # Report completion time
    taken_time = time.time() - start_time
    if restart_count > 0:
        print(f"\nGA completed in {taken_time:.2f} seconds after {restart_count} restart(s)")
    else:
        print(f"\nGA completed in {taken_time:.2f} seconds")
    
    # Display final stats using STORED values
    if best_chromosome_overall:
        print(f"\n\n=== DISPLAYING BEST SOLUTION ===")
        print(f"Found at Generation {best_gen_found + 1}")
        print(f"Overall Best Fitness: {best_fitness_overall:.2f}\n")
        
        print("--- Final Stats ---")
        print(f"Fitness: {best_fitness_overall:.2f} "
              f"(Base Reward: {best_stats_overall['base_reward']} - "
              f"Total Penalties: {best_stats_overall['total_penalties']})")
        
        # Print detailed stats using STORED stats (not recalculated)
        for key, value in best_stats_overall.items():
            if key in ['base_reward', 'total_penalties', 'target_ratio']:
                continue 
            elif key == 'corridor_ratio':
                target = best_stats_overall.get('target_ratio', 0)
                print(f"{key.replace('_', ' ').title()}: {value*100:.1f}% (target: {target*100:.1f}%)")
            elif key == 'corridor_ratio_deviation':
                print(f"{key.replace('_', ' ').title()}: {value*100:.1f}%")
            elif isinstance(value, float):
                print(f"{key.replace('_', ' ').title()}: {value:.3f}")
            else:
                print(f"{key.replace('_', ' ').title()}: {value}")
        
        # Visualize the best solution
        visualize_layout(best_chromosome_overall, initial_rooms, region_matrix, 
                        sorted_room_ids, room_names, room_dimensions, fixed_room_ids)
    
    return best_chromosome_overall
def visualize_layout(chromosome: Sequence[Tuple[int, int]], initial_rooms: Dict[int, "RoomGA"], region_matrix: np.ndarray, sorted_room_ids: List[int], room_names: Optional[Dict[int, str]] = None, room_dimensions: Optional[Dict[int, Tuple[int, int]]] = None, fixed_room_ids: Optional[List[int]] = None) -> None:
    """
    ga output placed in the region matrix with corridors generated by apply_rules
    """
    # --- 1. Generate the full layout matrix from the chromosome ---
    if not initial_rooms:
        print("No rooms to visualize.")
        return

    displaced_coords = apply_chromosome(initial_rooms, chromosome)
    
    # Collect all drawable room ids (expand blocks to sub rooms)
    drawable_rooms = {}  # room_id -> displaced_coords
    for room in initial_rooms.values():
        if room.block:
            # Compute displacement
            old_min_r = room.min_r
            old_min_c = room.min_c
            new_coords = displaced_coords[room.id]
            if new_coords:
                new_min_r = min(r for r, c in new_coords)
                new_min_c = min(c for r, c in new_coords)
                dr = new_min_r - old_min_r
                dc = new_min_c - old_min_c
                for sub_id, sub_coords in room.sub_coords.items():
                    displaced_sub = [(r + dr, c + dc) for r, c in sub_coords]
                    drawable_rooms[sub_id] = displaced_sub
        else:
            drawable_rooms[room.id] = displaced_coords[room.id]
    
    # Update displaced_coords to drawable_rooms
    displaced_coords = drawable_rooms
    
    # Create full region matrix for placing rooms and generating corridors
    region_height, region_width = region_matrix.shape
    layout_matrix = np.zeros((region_height, region_width), dtype=int)
    
    # Mark unusable areas
    for r in range(region_height):
        for c in range(region_width):
            if region_matrix[r, c] == '#':
                layout_matrix[r, c] = -1  # Unusable
    
    # Place rooms
    # for room_id, coords in displaced_coords.items():
    #     for r, c in coords:
    #         if 0 <= r < region_height and 0 <= c < region_width:
    #             if region_matrix[r, c] != '#' and layout_matrix[r, c] == 0:
    #                 layout_matrix[r, c] = room_id
    #             elif layout_matrix[r, c] != 0:
    #                 layout_matrix[r, c] = -2  # Overlap marker
    # Place rooms - fixed rooms first, then movable rooms
    if fixed_room_ids is None:
        fixed_room_ids = []

    # Place fixed rooms first (no overlap checking)
    for room_id in fixed_room_ids:
        if room_id in displaced_coords:
            coords = displaced_coords[room_id]
            for r, c in coords:
                if 0 <= r < region_height and 0 <= c < region_width:
                    layout_matrix[r, c] = room_id

    # Place movable rooms (with overlap checking)
    for room_id, coords in displaced_coords.items():
        if room_id in fixed_room_ids:
            continue  # Skip fixed rooms, already placed
        
        for r, c in coords:
            if 0 <= r < region_height and 0 <= c < region_width:
                if region_matrix[r, c] != '#' and layout_matrix[r, c] == 0:
                    layout_matrix[r, c] = room_id
                elif layout_matrix[r, c] != 0 and layout_matrix[r, c] not in fixed_room_ids:
                    # Only mark overlap if not colliding with fixed room
                    layout_matrix[r, c] = -2  # Overlap marker


    
    # Apply rules to generate corridors
    layout_matrix = corridor_creator(layout_matrix.tolist(), CORRIDOR_WIDTH)

    # --- 2. Setup the plot ---
    fig, ax = plt.subplots(1, 1, figsize=(15, 15))
    fig.suptitle('GA Floor Plan Layout with Generated Corridors', fontsize=16)

    # --- 3. Draw the layout ---
    unique_room_ids = sorted(displaced_coords.keys())
    # Use same color scheme as uinegNew: tab20 colormap with linear spacing
    colors = plt.cm.tab20(np.linspace(0, 1, len(unique_room_ids)))
    room_colors = {room_id: colors[i] for i, room_id in enumerate(unique_room_ids)}

    # Draw floor regions (allowed areas) first - light gray with dashed borders
    for r in range(region_height):
        for c in range(region_width):
            if region_matrix[r, c] != '#':  # Valid region
                rect = Rectangle(
                    (c, r), 1, 1,  # (x, y) = (column, row)
                    linewidth=0.5,
                    edgecolor='black',
                    facecolor='lightgray',
                    alpha=0.2,
                    linestyle='--'
                )
                ax.add_patch(rect)

    # Draw unusable regions - dark gray
    for r in range(region_height):
        for c in range(region_width):
            if region_matrix[r, c] == '#':
                ax.add_patch(Rectangle((c, r), 1, 1, facecolor='#404040', edgecolor='none', linewidth=0))

    # Draw rooms as individual cells for arbitrary shapes
    for room_id, coords in displaced_coords.items():
        if coords:
            is_fixed = room_id in fixed_room_ids if fixed_room_ids else False
            
            for r, c in coords:
                # Use different edge style for fixed rooms
                edge_color = 'darkred' if is_fixed else 'black'
                edge_width = 2 if is_fixed else 1
                
                ax.add_patch(Rectangle((c, r), 1, 1,
                                      facecolor=room_colors.get(room_id, 'gray'),
                                      edgecolor=edge_color,
                                      linewidth=edge_width))
            
            # Calculate centroid for text placement
            avg_r = sum(r for r, c in coords) / len(coords)
            avg_c = sum(c for r, c in coords) / len(coords)
            
            # Add room name/ID text at centroid
            if room_id in initial_rooms and initial_rooms[room_id].name:
                display_text = initial_rooms[room_id].name
            else:
                display_text = room_names.get(room_id, str(room_id)) if room_names else str(room_id)
            if is_fixed:
                display_text += " (FIXED)"
            
            if room_dimensions and room_id in room_dimensions:
                w, h = room_dimensions[room_id]
                display_text = f"{display_text}\n{w}x{h}"
            
            ax.text(avg_c + 0.5, avg_r + 0.5, display_text,
                   ha='center', va='center', fontsize=10,
                   color='white', weight='bold')
    # for room_id, coords in displaced_coords.items():
    #     if coords:
    #         # Draw each cell of the room individually
    #         for r, c in coords:
    #             ax.add_patch(Rectangle((c, r), 1, 1, 
    #                                  facecolor=room_colors.get(room_id, 'gray'), 
    #                                  edgecolor='black', linewidth=1))
            
    #         # Calculate centroid for text placement
    #         avg_r = sum(r for r, c in coords) / len(coords)
    #         avg_c = sum(c for r, c in coords) / len(coords)
            
    #         # Add room name/ID text at centroid
    #         display_text = room_names.get(room_id, str(room_id)) if room_names else str(room_id)
    #         if room_dimensions and room_id in room_dimensions:
    #             w, h = room_dimensions[room_id]
    #             display_text += f"\n{w}x{h}"
    #         ax.text(avg_c + 0.5, avg_r + 0.5, display_text, 
    #                ha='center', va='center', fontsize=10, color='white', weight='bold')

    # Draw corridors and overlaps
    for r in range(region_height):
        for c in range(region_width):
            val = layout_matrix[r, c]
            if val == CORRIDOR_FINAL and region_matrix[r, c] != '#':
                ax.add_patch(Rectangle((c, r), 1, 1, facecolor='gray', edgecolor='dimgray', linewidth=1))
            elif val == -2:  # Overlap
                ax.add_patch(Rectangle((c, r), 1, 1, facecolor='red', edgecolor='darkred', linewidth=1))

    # Configure axis with integer labels
    ax.set_xticks(range(region_width))
    ax.set_yticks(range(region_height))
    ax.set_xticklabels([str(i) for i in range(region_width)])
    ax.set_yticklabels([str(i) for i in range(region_height)])
    ax.set_xlabel('X Position (Columns)')
    ax.set_ylabel('Y Position (Rows)')
    ax.set_xlim(0, region_width)
    ax.set_ylim(0, region_height)
    ax.set_aspect('equal')
    # Remove the y-axis inversion to match uinegNew.py coordinate system
    # ax.invert_yaxis()
    
    # Add legend
    legend_elements = [
    Rectangle((0, 0), 1, 1, facecolor='lightgray', alpha=0.2, edgecolor='black', linestyle='--', label='Allowed Region'),
    Rectangle((0, 0), 1, 1, facecolor='#404040', label='Unusable Area'),
    Rectangle((0, 0), 1, 1, facecolor='tab:blue', edgecolor='black', label='Movable Room'),
    Rectangle((0, 0), 1, 1, facecolor='tab:blue', edgecolor='darkred', linewidth=2, label='Fixed Room'),
    Rectangle((0, 0), 1, 1, facecolor='gray', edgecolor='dimgray', label='Corridor'),
    Rectangle((0, 0), 1, 1, facecolor='red', edgecolor='darkred', label='Overlap')
    ]

    # legend_elements = [
    #     Rectangle((0, 0), 1, 1, facecolor='lightgray', alpha=0.2, edgecolor='black', linestyle='--', label='Allowed Region'),
    #     Rectangle((0, 0), 1, 1, facecolor='#404040', label='Unusable Area'),
    #     Rectangle((0, 0), 1, 1, facecolor='tab:blue', label='Room'),
    #     Rectangle((0, 0), 1, 1, facecolor='gray', edgecolor='dimgray', label='Corridor'),
    #     Rectangle((0, 0), 1, 1, facecolor='red', edgecolor='darkred', label='Overlap')
    # ]
    ax.legend(handles=legend_elements, loc='upper right', bbox_to_anchor=(1.15, 1))
    
    plt.tight_layout(rect=[0, 0, 1, 0.96])
    
    # Save with timestamp
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    os.makedirs('mine/ga_outputs', exist_ok=True)
    filename = f"mine/ga_outputs/floor_plan_visualization_{timestamp}.png"
    plt.savefig(filename, dpi=300, bbox_inches='tight')
    print(f"Visualization saved to '{filename}'")

    # # Save with timestamp
    # timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    # os.makedirs('ga_outputs', exist_ok=True)
    # filename = f"Python1/ga_outputs/floor_plan_visualization_{timestamp}.png"
    # plt.savefig(filename, dpi=300, bbox_inches='tight')
    # print(f"Visualization saved to '{filename}'")
    
    # Also display the plot
    plt.show()

if __name__ == "__main__":
    # Test JSON import and export
    json_file_path = r"floorplan_data.json"
    
    try:
        with open(json_file_path, 'r') as f:
            json_data = json.load(f)
        
        print("--- Original JSON Data ---")
        print(f"Plot size: {json_data['plot_width']}x{json_data['plot_height']}")
        print(f"Number of rooms: {len(json_data['rooms'])}")
        print(f"Number of walls: {len(json_data['walls'])}")
        print(f"Number of labels: {len(json_data['labels'])}")
        
        # Parse using the Floorplan dataclass
        floorplan = parse_floorplan_json(json_data)
        print(f"\n--- Parsed Floorplan ---")
        print(f"Rooms: {[r.name for r in floorplan.rooms]}")
        print(f"Plot size: {floorplan.plot_width}x{floorplan.plot_height}")
        
        # Parse using the GA parser
        rooms, initial_grid, region_matrix, room_names = parse_json_floorplan(json_data)
        print(f"\n--- GA Parser Results ---")
        print(f"Parsed {len(rooms)} rooms:")
        for room_id, room in rooms.items():
            print(f"  Room {room_id} ({room.name}): {len(room.coords)} cells, bounds: r({room.min_r}-{room.max_r}), c({room.min_c}-{room.max_c})")
        
        # Export back to JSON to verify round-trip
        export_data = {
            "plot_width": floorplan.plot_width,
            "plot_height": floorplan.plot_height,
            "rooms": [
                {
                    "id": room.id,
                    "name": room.name,
                    "color": room.color,
                    "walls": room.walls
                } for room in floorplan.rooms
            ],
            "walls": [
                {
                    "id": wall.id,
                    "roomIds": wall.roomIds,
                    "x1": wall.x1,
                    "y1": wall.y1,
                    "x2": wall.x2,
                    "y2": wall.y2
                } for wall in floorplan.walls
            ],
            "labels": [
                {
                    "x": label.x,
                    "y": label.y,
                    "text": label.text,
                    "roomId": label.roomId
                } for label in floorplan.labels
            ],
            "windows": floorplan.windows,
            "doors": floorplan.doors
        }
        
        # Save exported JSON
        export_file_path = r"floorplan_data_exported.json"
        with open(export_file_path, 'w') as f:
            json.dump(export_data, f, indent=2)
        
        print(f"\n--- Exported JSON saved to: {export_file_path} ---")
        
        # Compare original and exported
        print("\n--- Comparison ---")
        print(f"Original rooms: {len(json_data['rooms'])}")
        print(f"Exported rooms: {len(export_data['rooms'])}")
        print(f"Original walls: {len(json_data['walls'])}")
        print(f"Exported walls: {len(export_data['walls'])}")
        print(f"Original labels: {len(json_data['labels'])}")
        print(f"Exported labels: {len(export_data['labels'])}")
        
        print("\nJSON parsing and export test completed successfully!")

    except FileNotFoundError:
        print(f"JSON file not found at {json_file_path}")
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    # Test JSON import and GA run
    json_file_path = r"floorplan_data.json"
    
    try:
        with open(json_file_path, 'r') as f:
            json_data = json.load(f)
        
        print("--- Parsing JSON Floorplan ---")
        rooms, initial_grid, region_matrix, room_names = parse_json_floorplan(json_data)
        
        print(f"Parsed {len(rooms)} rooms:")
        for room_id, room in rooms.items():
            print(f"  Room {room_id} ({room.name}): {len(room.coords)} cells, bounds: r({room.min_r}-{room.max_r}), c({room.min_c}-{room.max_c})")
        
        print("\n--- Running Genetic Algorithm ---")
        # Run the GA
        best_solution = run_ga(initial_grid, region_matrix, corridor_width=CORRIDOR_WIDTH, room_names=room_names)
        
        if best_solution:
            print(f"\n--- GA completed successfully! Best solution: {best_solution} ---")
            
            # Now save the optimized layout back to JSON format
            displaced_coords = apply_chromosome(rooms, best_solution)
            
            # Create layout matrix for corridors
            region_height, region_width = region_matrix.shape
            layout_matrix = np.zeros((region_height, region_width), dtype=int)
            layout_matrix[region_matrix == '#'] = -1
            
            # Place rooms
            for room_id, coords in displaced_coords.items():
                for r, c in coords:
                    if 0 <= r < region_height and 0 <= c < region_width:
                        if region_matrix[r, c] != '#':
                            layout_matrix[r, c] = room_id
            
            # Generate corridors
            layout_matrix = corridor_creator(layout_matrix.tolist(), CORRIDOR_WIDTH)
            
            # Convert back to JSON format
            # Create mapping from room ID to chromosome index
            sorted_room_ids = sorted(rooms.keys())
            room_id_to_chromosome_idx = {room_id: idx for idx, room_id in enumerate(sorted_room_ids)}
            
            optimized_rooms = []
            for room_idx, coords in displaced_coords.items():
                if room_idx in rooms:
                    room = rooms[room_idx]
                    # Get the chromosome index for this room
                    chromosome_idx = room_id_to_chromosome_idx[room_idx]
                    dr, dc = best_solution[chromosome_idx]
                    
                    # Transform wall coordinates by applying displacement
                    transformed_walls = []
                    for wall_data in room.original_data["walls"]:
                        wall = wall_data.copy()
                        # Apply displacement: dc to x-coordinates, dr to y-coordinates
                        wall["x1"] += dc
                        wall["x2"] += dc
                        wall["y1"] += dr
                        wall["y2"] += dr
                        transformed_walls.append(wall)
                    
                    # Convert grid coordinates back to continuous coordinates (approximate)
                    # This is a simplified conversion - in practice you'd need proper coordinate transformation
                    min_r, min_c = min(r for r, c in coords), min(c for r, c in coords)
                    max_r, max_c = max(r for r, c in coords), max(c for r, c in coords)
                    
                    optimized_rooms.append({
                        "id": room.original_data["id"],
                        "name": room.name,
                        "color": room.original_data["color"],
                        "walls": transformed_walls,  # Use transformed walls
                        "optimized_bounds": {
                            "min_r": int(min_r),
                            "max_r": int(max_r),
                            "min_c": int(min_c),
                            "max_c": int(max_c)
                        }
                    })
            
            optimized_data = {
                "plot_width": json_data["plot_width"],
                "plot_height": json_data["plot_height"],
                "rooms": optimized_rooms,
                "walls": json_data["walls"],  # Keep original walls
                "labels": json_data["labels"],  # Keep original labels
                "windows": json_data.get("windows", []),
                "doors": json_data.get("doors", []),
                "ga_solution": best_solution,
                "layout_matrix": layout_matrix.tolist()
            }
            
            # Save optimized JSON
            optimized_file_path = r"floorplan_optimized.json"
            with open(optimized_file_path, 'w') as f:
                json.dump(optimized_data, f, indent=2)
            
            print(f"Optimized floorplan saved to: {optimized_file_path}")
            
            # Also visualize the result
            visualize_layout(best_solution, rooms, region_matrix, sorted(rooms.keys()), room_names=room_names)
        else:
            print("GA failed to find a solution")

    except FileNotFoundError:
        print(f"JSON file not found at {json_file_path}")
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
    
