import matplotlib.pyplot as plt
import matplotlib.patches as patches
import networkx as nx
import numpy as np
import random
import heapq
from collections import defaultdict, deque
import ga_current as ga


class Room:
    def __init__(self, name, width, height, max_expansion=3):
        self.name = name
        self.original_width = width
        self.original_height = height
        self.width = width
        self.height = height
        self.x = None
        self.y = None
        self.rotated = False
        # Ensure max_expansion is an int (defensive against UI passing strings)
        try:
            self.max_expansion = int(max_expansion)
        except Exception:
            self.max_expansion = max_expansion
        self.is_fixed = False
        self.need_corridor = True

    # Default to True, can be toggled in UI

    def rotate(self):
        self.width, self.height = self.height, self.width
        self.rotated = not self.rotated

    def reset_to_original_size(self):
        if self.rotated:
            self.width = self.original_height
            self.height = self.original_width
        else:
            self.width = self.original_width
            self.height = self.original_height

    def get_area(self):
        return self.width * self.height

    def __repr__(self):
        position = f"at ({self.x}, {self.y})" if self.x is not None else "unplaced"
        size_info = f"[{self.width}x{self.height}]"
        if self.width != self.original_width or self.height != self.original_height:
            if not self.rotated:
                size_info += f" (expanded from {self.original_width}x{self.original_height})"
            else:
                size_info += f" (expanded from {self.original_height}x{self.original_width} and rotated)"
        elif self.rotated:
            size_info += f" (rotated from {self.original_height}x{self.original_width})"
        return f"Room {self.name} {size_info} {position} (max expansion: {self.max_expansion})"

    def get_boundaries(self):
        if self.x is None or self.y is None:
            return None
        return (self.x, self.x + self.width, self.y, self.y + self.height)

    def has_shared_wall_with(self, other_room):
        if self.x is None or self.y is None or other_room.x is None or other_room.y is None:
            return False
        left1, right1, bottom1, top1 = self.get_boundaries()
        left2, right2, bottom2, top2 = other_room.get_boundaries()
        if right1 == left2:
            return max(bottom1, bottom2) < min(top1, top2)
        if right2 == left1:
            return max(bottom1, bottom2) < min(top1, top2)
        if top1 == bottom2:
            return max(left1, left2) < min(right1, right2)
        if top2 == bottom1:
            return max(left1, left2) < min(right1, right2)
        return False

    def is_adjacent_to_entrance(self, entrance_coords):
        """Check if any wall of the room touches any segment of the entrance line."""
        if self.x is None or self.y is None or not entrance_coords:
            return False

        room_left, room_right, room_bottom, room_top = self.x, self.x + self.width, self.y, self.y + self.height
        epsilon = 1e-5

        for i in range(len(entrance_coords) - 1):
            p1, p2 = entrance_coords[i], entrance_coords[i + 1]
            ex1, ey1 = p1
            ex2, ey2 = p2

            # ### FIX IS HERE: Changed < to <= in all four checks below ###

            # Check for adjacency with the room's LEFT wall
            if abs(room_left - ex1) < epsilon and abs(room_left - ex2) < epsilon:
                if max(room_bottom, min(ey1, ey2)) <= min(room_top, max(ey1, ey2)):
                    return True

            # Check for adjacency with the room's RIGHT wall
            if abs(room_right - ex1) < epsilon and abs(room_right - ex2) < epsilon:
                if max(room_bottom, min(ey1, ey2)) <= min(room_top, max(ey1, ey2)):
                    return True

            # Check for adjacency with the room's BOTTOM wall
            if abs(room_bottom - ey1) < epsilon and abs(room_bottom - ey2) < epsilon:
                if max(room_left, min(ex1, ex2)) <= min(room_right, max(ex1, ex2)):
                    return True

            # Check for adjacency with the room's TOP wall
            if abs(room_top - ey1) < epsilon and abs(room_top - ey2) < epsilon:
                if max(room_left, min(ex1, ex2)) <= min(room_right, max(ex1, ex2)):
                    return True

        return False


class FloorPlan:
    def __init__(self, region_specs, fixed_rooms=None):
        self.rooms = []
        self.fixed_rooms = fixed_rooms or []
        self.adjacency_graph = nx.Graph()
        self.non_adjacency_graph = nx.Graph()

        self.entrance_coords = None  # For entrance adjacency

        self.floor_regions = []
        if isinstance(region_specs[0], tuple):
            y_offset = 0
            for width, height in region_specs:
                self.floor_regions.append({'x': 0, 'y': y_offset, 'width': width, 'height': height})
                y_offset += height
        else:
            for region in region_specs:
                self.floor_regions.append(
                    {'x': region.get('x', 0), 'y': region.get('y', 0), 'width': region['width'],
                     'height': region['height']})

        self.floor_width = max(region['x'] + region['width'] for region in self.floor_regions)
        self.floor_height = max(region['y'] + region['height'] for region in self.floor_regions)
        self.spatial_grid = {}
        self.grid_size = 2

    def compact_rooms(self):
        def overlaps(r1, r2):
            return not (
                    r1.x + r1.width <= r2.x or
                    r2.x + r2.width <= r1.x or
                    r1.y + r1.height <= r2.y or
                    r2.y + r2.height <= r1.y
            )

        def is_within_any_floor_region(room):
            """Check if the entire room lies inside any one allowed region."""
            for region in self.floor_regions:
                rx, ry, rw, rh = region['x'], region['y'], region['width'], region['height']
                if (room.x >= rx and
                        room.y >= ry and
                        room.x + room.width <= rx + rw and
                        room.y + room.height <= ry + rh):
                    return True
            return False

        moved = True
        while moved:
            moved = False
            for room in sorted(self.rooms, key=lambda r: (r.x, r.y)):
                if getattr(room, "is_fixed", False):
                    continue  # ✅ never move fixed rooms

                while room.x > 0:
                    room.x -= 1
                    if not is_within_any_floor_region(room) or any(
                            overlaps(room, other) for other in self.rooms if other != room):
                        room.x += 1
                        break
                    moved = True

                while room.y > 0:
                    room.y -= 1
                    if not is_within_any_floor_region(room) or any(
                            overlaps(room, other) for other in self.rooms if other != room):
                        room.y += 1
                        break
                    moved = True

    # In the FloorPlan class

    def _check_overlap_at(self, room_to_move, new_x, new_y, ignore_room=None):
        """
        Checks if 'room_to_move' would overlap with ANY other room if moved to (new_x, new_y).
        'ignore_room' is used to avoid self-checking.
        """
        for other_room in self.rooms:
            if other_room == room_to_move or other_room == ignore_room:
                continue

            # Check if other_room is placed
            if other_room.x is None or other_room.y is None:
                continue

            # Standard Bounding Box check
            x_overlap = (new_x < other_room.x + other_room.width and
                         new_x + room_to_move.width > other_room.x)
            y_overlap = (new_y < other_room.y + other_room.height and
                         new_y + room_to_move.height > other_room.y)

            if x_overlap and y_overlap:
                return True  # Found an overlap
        return False  # No overlap

    def get_room_by_name(self, name):
        """Helper function to find a room object by its name."""
        for room in self.rooms:
            if room.name == name:
                return room
        for room in self.fixed_rooms:
            if room.name == name:
                return room
        return None

    def _check_non_adjacency_violation_at(self, room_to_move, new_x, new_y):
        """
        Checks if moving 'room_to_move' to (new_x, new_y) would make it
        touch a room it's not supposed to.
        """
        if room_to_move.name not in self.non_adjacency_graph:
            return False  # This room has no non-adjacency rules

        temp_room = Room(room_to_move.name, room_to_move.width, room_to_move.height)
        temp_room.x = new_x
        temp_room.y = new_y

        for other_name in self.non_adjacency_graph.neighbors(room_to_move.name):
            other_room = self.get_room_by_name(other_name)

            if not other_room or other_room.x is None:
                continue

            if temp_room.has_shared_wall_with(other_room):
                return True  # This move would violate a non-adjacency rule
        return False

    @staticmethod
    def _total_expansion_used(room):
        """Return combined expansion (width delta + height delta) respecting rotation."""
        if room is None:
            return 0

        if not room.rotated:
            extra_w = room.width - room.original_width
            extra_h = room.height - room.original_height
        else:
            extra_w = room.width - room.original_height
            extra_h = room.height - room.original_width

        return max(0, extra_w) + max(0, extra_h)

    def compact_rooms_up_conditional(self):
        """
        Shifts rooms UP to close horizontal gaps, but only if they have
        an X-overlapping neighbor above them, and the move is safe.
        Uses 'all-or-nothing' move logic.
        """
        print("--- Starting conditional up-compaction (ALL-OR-NOTHING logic) ---")

        moved_a_room_in_pass = True
        while moved_a_room_in_pass:
            moved_a_room_in_pass = False

            # Sort rooms from bottom to top
            sorted_rooms = sorted([r for r in self.rooms if not r.is_fixed and r.y is not None], key=lambda r: r.y)

            for room in sorted_rooms:

                # --- 1. Find the *closest* "target" room *above* ---
                target_room = None
                min_target_y = float('inf')

                all_placed_rooms = [r for r in self.rooms if r.x is not None] + self.fixed_rooms

                for other_room in all_placed_rooms:
                    if other_room == room:
                        continue

                    # Is 'other_room' *above* 'room'?
                    is_above = other_room.y >= room.y + room.height

                    # Do they overlap horizontally (on the X-axis)?
                    x_overlap = (room.x < other_room.x + other_room.width and
                                 room.x + room.width > other_room.x)

                    if is_above and x_overlap:
                        # This is a potential target. Is it the *closest* one?
                        if other_room.y < min_target_y:
                            min_target_y = other_room.y
                            target_room = other_room

                # --- 2. If we found no target, skip this room ---
                if not target_room:
                    continue

                # --- 3. Calculate the *final* target position ---
                # We want the room's top edge (y + height) to touch
                # the target's bottom edge (target_room.y).
                target_y_position = target_room.y - room.height

                if target_y_position <= room.y:
                    continue

                # --- 4. Check if this move is valid (all-or-nothing) ---

                # Use the optimized checker we fixed before
                is_safe_overlap = not self.check_overlap(room.x, target_y_position, room.width, room.height,
                                                                   ignore_room=room)

                is_safe_boundary = self.is_within_floor(room.x, target_y_position, room.width, room.height)

                # Use the non-adjacency checker we added before
                is_safe_non_adj = not self._check_non_adjacency_violation_at(room, room.x, target_y_position)

                # --- 5. If all checks pass, make the move ---
                if is_safe_overlap and is_safe_boundary and is_safe_non_adj:
                    print(
                        f"Moving {room.name} from y={room.y} to y={target_y_position} (aligning with {target_room.name})")
                    self._remove_from_spatial_grid(room)
                    room.y = target_y_position
                    self._add_to_spatial_grid(room)

                    moved_a_room_in_pass = True
                    # Since we moved a room, break and restart the outer loop
                    break

        print("--- Finished conditional up-compaction ---")


    def compact_rooms_right_conditional(self):
        """
        CORRECTED: Calls self.check_overlap with the correct (x, y, w, h) arguments
        and the 'ignore_room' argument.
        """
        print("--- Starting conditional right-compaction (ALL-OR-NOTHING logic) ---")

        moved_a_room_in_pass = True
        while moved_a_room_in_pass:
            moved_a_room_in_pass = False

            sorted_rooms = sorted([r for r in self.rooms if not r.is_fixed and r.x is not None], key=lambda r: r.x)

            for room in sorted_rooms:
                target_room = None
                min_target_x = float('inf')
                all_placed_rooms = [r for r in self.rooms if r.x is not None] + self.fixed_rooms

                for other_room in all_placed_rooms:
                    if other_room == room:
                        continue

                    is_to_right = other_room.x >= room.x + room.width
                    y_overlap = (room.y < other_room.y + other_room.height and
                                 room.y + room.height > other_room.y)

                    if is_to_right and y_overlap:
                        if other_room.x < min_target_x:
                            min_target_x = other_room.x
                            target_room = other_room

                if not target_room:
                    continue

                target_x_position = target_room.x - room.width

                if target_x_position <= room.x:
                    continue

                # *** THIS IS THE FIX ***
                is_safe_overlap = not self.check_overlap(target_x_position, room.y, room.width, room.height,
                                                         ignore_room=room)
                # *** END OF FIX ***

                is_safe_boundary = self.is_within_floor(target_x_position, room.y, room.width, room.height)
                is_safe_non_adj = not self._check_non_adjacency_violation_at(room, target_x_position, room.y)

                if is_safe_overlap and is_safe_boundary and is_safe_non_adj:
                    print(
                        f"Moving {room.name} from x={room.x} to x={target_x_position} (aligning with {target_room.name})")
                    room.x = target_x_position
                    moved_a_room_in_pass = True
                    break

        print("--- Finished conditional right-compaction ---")

    def set_entrance_location(self, coords):
        self.entrance_coords = coords

    def _get_grid_cells(self, x, y, width, height):
        cells = []
        start_x, end_x = x // self.grid_size, (x + width - 1) // self.grid_size
        start_y, end_y = y // self.grid_size, (y + height - 1) // self.grid_size
        for gx in range(start_x, end_x + 1):
            for gy in range(start_y, end_y + 1):
                cells.append((gx, gy))
        return cells

    def _add_to_spatial_grid(self, room):
        if room.x is None or room.y is None: return
        for cell in self._get_grid_cells(room.x, room.y, room.width, room.height):
            if cell not in self.spatial_grid: self.spatial_grid[cell] = []
            self.spatial_grid[cell].append(room)

    def _remove_from_spatial_grid(self, room):
        if room.x is None or room.y is None: return
        for cell in self._get_grid_cells(room.x, room.y, room.width, room.height):
            if cell in self.spatial_grid and room in self.spatial_grid[cell]:
                self.spatial_grid[cell].remove(room)
                if not self.spatial_grid[cell]: del self.spatial_grid[cell]

    def check_overlap_optimized(self, room, x, y, width, height):
        checked_rooms = set()
        for cell in self._get_grid_cells(x, y, width, height):
            if cell in self.spatial_grid:
                for existing_room in self.spatial_grid[cell]:
                    if existing_room != room and existing_room not in checked_rooms:
                        checked_rooms.add(existing_room)
                        if (x < existing_room.x + existing_room.width and
                                x + width > existing_room.x and
                                y < existing_room.y + existing_room.height and
                                y + height > existing_room.y):
                            return True
        return False

    def get_valid_positions(self, room, max_positions=100):
        valid_positions = []
        adjacent_rooms = []
        for neighbor in self.adjacency_graph.neighbors(room.name):
            neighbor_room = next((r for r in self.rooms if r.name == neighbor), None)
            if neighbor_room and neighbor_room.x is not None:
                adjacent_rooms.append(neighbor_room)

        if adjacent_rooms:
            for adj_room in adjacent_rooms:
                positions = [(adj_room.x + adj_room.width, adj_room.y), (adj_room.x - room.width, adj_room.y),
                             (adj_room.x, adj_room.y + adj_room.height), (adj_room.x, adj_room.y - room.height)]
                for x, y in positions:
                    if (self.is_within_floor(x, y, room.width, room.height) and
                            not self.check_overlap_optimized(room, x, y, room.width, room.height) and
                            not self.check_non_adjacency_violation(room, x, y, room.width, room.height)):
                        valid_positions.append((x, y))
                        if len(valid_positions) >= max_positions: return valid_positions

        attempts = 0
        while len(valid_positions) < max_positions and attempts < 200:
            attempts += 1
            region = random.choice(self.floor_regions)
            if region['width'] < room.width or region['height'] < room.height: continue
            max_x, max_y = region['x'] + region['width'] - room.width, region['y'] + region['height'] - room.height
            if max_x >= region['x'] and max_y >= region['y']:
                x, y = random.randint(region['x'], max_x), random.randint(region['y'], max_y)
                if (not self.check_overlap_optimized(room, x, y, room.width, room.height) and
                        not self.check_non_adjacency_violation(room, x, y, room.width, room.height) and
                        (x, y) not in valid_positions):
                    valid_positions.append((x, y))

        # print(room.name)
        # print(valid_positions)
        # print( )
        return valid_positions

    def add_non_adjacency(self, room1_name, room2_name):
        if room1_name in self.adjacency_graph.nodes and room2_name in self.adjacency_graph.nodes:
            self.non_adjacency_graph.add_edge(room1_name, room2_name)

    def check_non_adjacency_violation(self, room, x, y, width, height):
        if room.name not in self.non_adjacency_graph.nodes: return False
        for neighbor_name in self.non_adjacency_graph.neighbors(room.name):
            neighbor_room = next((r for r in self.rooms if r.name == neighbor_name), None)
            if neighbor_room and neighbor_room.x is not None:
                temp_room = Room(room.name, width, height)
                temp_room.x, temp_room.y = x, y
                if temp_room.has_shared_wall_with(neighbor_room): return True
        return False

    def add_room(self, name, width, height, max_expansion=3, fixed_x=None, fixed_y=None, need_corridor=True):
        """Create and register a room. If fixed_x/fixed_y are provided the room is treated as fixed.

        need_corridor: boolean flag stored on the Room instance (default True).
        """
        # Create Room (ensure max_expansion is passed through)
        room = Room(name, width, height, max_expansion)

        # Set need_corridor from caller (defensive)
        try:
            room.need_corridor = bool(need_corridor)
        except Exception:
            room.need_corridor = True

        # If fixed coordinates were provided, set fixed properties consistently
        if fixed_x is not None and fixed_y is not None:
            try:
                room.x, room.y = int(fixed_x), int(fixed_y)
            except Exception:
                room.x, room.y = fixed_x, fixed_y
            room.is_fixed = True
            # Preserve the passed max_expansion for fixed rooms (coerce to int if possible)
            try:
                room.max_expansion = int(max_expansion)
            except Exception:
                room.max_expansion = max_expansion
            room.rotated = False

        # Register room in lists/graphs
        self.rooms.append(room)
        self.adjacency_graph.add_node(name)
        self.non_adjacency_graph.add_node(name)
        return room

    def register_special_entity(self, name):
        if not self.adjacency_graph.has_node(name):
            self.adjacency_graph.add_node(name)
        if not self.non_adjacency_graph.has_node(name):
            self.non_adjacency_graph.add_node(name)

    def _generate_fixed_name(self):
        i = 1
        while True:
            candidate = f"Fixed{i}"
            if all(r.name != candidate for r in self.rooms): return candidate
            i += 1

    def add_fixed_room(self, width, height, fixed_x, fixed_y, name=None, max_expansion=3, ui=None, need_corridor=True):
        chosen_name = None
        if name and str(name).strip():
            chosen_name = str(name).strip()
        elif ui is not None and hasattr(ui, "last_text_name") and ui.last_text_name:
            chosen_name = ui.last_text_name
            try:
                ui.last_text_name = None
            except Exception:
                pass
        else:
            chosen_name = self._generate_fixed_name()
        base, counter = chosen_name, 1
        while any(r.name == chosen_name for r in self.rooms):
            chosen_name = f"{base}_{counter}"
            counter += 1
        return self.add_room(chosen_name, width, height, max_expansion=max_expansion, fixed_x=fixed_x, fixed_y=fixed_y, need_corridor=need_corridor)

    def add_adjacency(self, room1_name, room2_name):
        if room1_name in self.adjacency_graph.nodes and room2_name in self.adjacency_graph.nodes:
            self.adjacency_graph.add_edge(room1_name, room2_name)

    def is_within_floor(self, x, y, width, height):
        for dx in range(width):
            for dy in range(height):
                if not self.point_in_floor(x + dx, y + dy): return False
        return True

    def point_in_floor(self, x, y):
        for region in self.floor_regions:
            if (region['x'] <= x < region['x'] + region['width'] and
                    region['y'] <= y < region['y'] + region['height']):
                return True
        return False

    def check_overlap(self, x, y, width, height, ignore_room=None):
        """
        Checks if a given rectangle (x, y, width, height) overlaps
        with any *other* room.

        *** THIS IS THE CORRECTED FUNCTION ***
        Now accepts 'ignore_room' and uses a correct loop.
        """
        # Iterate over all placed rooms (non-fixed and fixed)
        all_placed_rooms = [r for r in self.rooms if r.x is not None] + self.fixed_rooms

        for room in all_placed_rooms:
            # *** THIS IS THE FIX ***
            # Skip the room we are explicitly ignoring
            if room == ignore_room:
                continue
            # *** END OF FIX ***

            # Standard bounding box check
            if not (x + width <= room.x or
                    x >= room.x + room.width or
                    y + height <= room.y or
                    y >= room.y + room.height):
                return True  # Overlap detected
        return False  # No overlap

    def evaluate_adjacency_score(self):
        score, adjacent_pairs, violations = 0, [], []
        for room1_name, room2_name in self.adjacency_graph.edges:
            room1 = next((r for r in self.rooms if r.name == room1_name), None)
            room2 = next((r for r in self.rooms if r.name == room2_name), None)
            if room1 and room2:
                if room1.x is not None and room2.x is not None and room1.has_shared_wall_with(room2):
                    score += 1
                    adjacent_pairs.append((room1_name, room2_name))
            elif self.entrance_coords and (room1 is None or room2 is None):
                room_to_check = room1 if room2 is None else room2
                if room_to_check is not None and room_to_check.is_adjacent_to_entrance(self.entrance_coords):
                    score += 1
                    adjacent_pairs.append((room1_name, room2_name))
        for room1_name, room2_name in self.non_adjacency_graph.edges:
            room1 = next((r for r in self.rooms if r.name == room1_name), None)
            room2 = next((r for r in self.rooms if r.name == room2_name), None)
            if room1 and room2:
                if room1.x is not None and room2.x is not None and room1.has_shared_wall_with(room2):
                    score -= 2
                    violations.append((room1_name, room2_name))
        return score, adjacent_pairs, violations

    def enforce_minimum_adjacency(self):
        """
        CORRECTED: Calls self.check_overlap with the correct (x, y, w, h) arguments
        and the 'ignore_room' argument.
        """
        print("Enforcing adjacency constraints...")

        moved_room_in_pass = True
        loops = 0
        max_loops = len(self.rooms) * 2

        while moved_room_in_pass and loops < max_loops:
            moved_room_in_pass = False
            loops += 1

            for room1_name, room2_name in self.adjacency_graph.edges():
                room1 = self.get_room_by_name(room1_name)
                room2 = self.get_room_by_name(room2_name)

                if not room1 or not room2 or room1.x is None or room2.x is None:
                    continue

                if room1.has_shared_wall_with(room2):
                    continue

                room_to_move, stationary_room = None, None
                if not getattr(room1, 'is_fixed', False):
                    room_to_move = room1
                    stationary_room = room2
                elif not getattr(room2, 'is_fixed', False):
                    room_to_move = room2
                    stationary_room = room1
                else:
                    continue

                possible_moves = [
                    (stationary_room.x - room_to_move.width, stationary_room.y),  # Left
                    (stationary_room.x + stationary_room.width, stationary_room.y),  # Right
                    (stationary_room.x, stationary_room.y - room_to_move.height),  # Bottom
                    (stationary_room.x, stationary_room.y + stationary_room.height)  # Top
                ]

                for new_x, new_y in possible_moves:
                    touches_x = (new_x == stationary_room.x + stationary_room.width or
                                 new_x + room_to_move.width == stationary_room.x)
                    y_range_overlap = (new_y < stationary_room.y + stationary_room.height and
                                       new_y + room_to_move.height > stationary_room.y)

                    touches_y = (new_y == stationary_room.y + stationary_room.height or
                                 new_y + room_to_move.height == stationary_room.y)
                    x_range_overlap = (new_x < stationary_room.x + stationary_room.width and
                                       new_x + room_to_move.width > stationary_room.x)

                    is_adjacent = (touches_x and y_range_overlap) or (touches_y and x_range_overlap)

                    if not is_adjacent:
                        continue

                    is_safe_boundary = self.is_within_floor(new_x, new_y, room_to_move.width, room_to_move.height)

                    # *** THIS IS THE FIX ***
                    is_safe_overlap = not self.check_overlap(new_x, new_y, room_to_move.width, room_to_move.height,
                                                             ignore_room=stationary_room)
                    # *** END OF FIX ***

                    is_safe_non_adj = not self._check_non_adjacency_violation_at(room_to_move, new_x, new_y)

                    if is_safe_boundary and is_safe_overlap and is_safe_non_adj:
                        print(
                            f"Enforcing adjacency: Moving {room_to_move.name} to ({new_x}, {new_y}) to be adjacent to {stationary_room.name}")
                        room_to_move.x = new_x
                        room_to_move.y = new_y
                        moved_room_in_pass = True
                        break

                if moved_room_in_pass:
                    break

        print("Finished enforcing adjacency.")

    def can_expand_room(self, room, direction, amount):
        """Check if a room can be expanded in the given direction by the specified amount"""
        if room.x is None or room.y is None:
            return False

        # Calculate total expansion so far
        current_expansion = 0
        if not room.rotated:
            current_expansion += room.width - room.original_width
            current_expansion += room.height - room.original_height
        else:
            current_expansion += room.width - room.original_height
            current_expansion += room.height - room.original_width

        # Check if we've reached the maximum expansion for this room
        if current_expansion + amount > room.max_expansion:
            return False

        # Calculate new dimensions and position after expansion
        new_x, new_y = room.x, room.y
        new_width, new_height = room.width, room.height

        if direction == 'right':
            new_width += amount
        elif direction == 'left':
            new_x -= amount
            new_width += amount
        elif direction == 'up':
            new_height += amount
        elif direction == 'down':
            new_y -= amount
            new_height += amount
        else:
            return False

        # Check if new position is within floor and doesn't overlap other rooms
        if not self.is_within_floor(new_x, new_y, new_width, new_height):
            return False

        if self.check_overlap(new_x, new_y, new_width, new_height, ignore_room=room):
            return False

        return True

    def expand_rooms(self):
        """
        Expand rooms to fill available space while maintaining adjacency constraints
        and ensuring no overlaps, respecting each room's max_expansion limit
        """
        # For each room, attempt expansion in each direction
        for room in self.rooms:
            if room.x is None or room.y is None:
                continue

            # Try to expand in all four directions
            directions = ['right', 'down', 'left', 'up']
            random.shuffle(directions)  # Randomize direction order for more varied results

            for direction in directions:
                # Try expanding 1 unit at a time up to max expansion
                expanded = True
                total_expansion = 0

                while expanded:
                    if self.can_expand_room(room, direction, 1):
                        # Apply 1 unit expansion
                        if direction == 'right':
                            room.width += 1
                        elif direction == 'left':
                            room.x -= 1
                            room.width += 1
                        elif direction == 'up':
                            room.height += 1
                        elif direction == 'down':
                            room.y -= 1
                            room.height += 1

                        total_expansion += 1
                    else:
                        expanded = False

    def place_rooms_with_constraints_optimized(self, max_attempts=100, enable_expansion=True, use_compact_mode=True):
        """
        Optimized room placement using constraint satisfaction and spatial indexing.
        Fixed rooms (with predefined coordinates) are anchored first.
        """
        self.spatial_grid = {}

        # Reset only unfixed rooms
        i =0
        for room in self.rooms:
            if getattr(room, "is_fixed", False):
                continue
            if room.x is None or room.y is None:  # Leave fixed ones as-is
                room.x = None
                room.y = None
                room.reset_to_original_size()

        # Sort rooms by constraint priority
        room_constraints = {r.name: len(list(self.adjacency_graph.neighbors(r.name))) for r in self.rooms}
        sorted_rooms = sorted(self.rooms,
                              key=lambda r: (getattr(r, "is_fixed", False), room_constraints[r.name], r.get_area()),
                              reverse=True)

        best_score = -1
        best_placement = None

        for attempt in range(max_attempts):
            self.spatial_grid = {}
            for room in self.rooms:
                if getattr(room, "is_fixed", False):
                    continue

                room.x = None
                room.y = None
                room.reset_to_original_size()
                if random.random() > 0.5:
                    room.rotate()

            # Add fixed rooms to spatial grid first
            for room in self.rooms:
                if room.x is not None and room.y is not None:
                    self._add_to_spatial_grid(room)

            placement_successful = True
            for room in sorted_rooms:
                # Skip fixed rooms
                if getattr(room, "is_fixed", False):
                    continue
                if room.x is not None and room.y is not None:
                    continue

                placed = False

                valid_positions = self.get_valid_positions(room, max_positions=100)
                # print("Hi1")
                if valid_positions:
                    # Very nice alternative can be used if ever a issue comes where repeated floor plans are not satisfying non adj. const. :)
                    #x, y = random.choice(valid_positions)
                    x,y = valid_positions[0]
                    room.x, room.y = x, y
                    self._add_to_spatial_grid(room)
                    placed = True
                    print(valid_positions[0])
                    print(room)
                    print("Hi")

                if not placed:
                    room.rotate()
                    valid_positions = self.get_valid_positions(room, max_positions=30)
                    if valid_positions:
                        x, y = random.choice(valid_positions)
                        room.x, room.y = x, y
                        self._add_to_spatial_grid(room)
                        placed = True

                if not placed:
                    placement_successful = False
                    print(i)
                    i += 1 
                    print(room)
                    break

            if placement_successful:
                # *** CHANGE IS HERE ***
                # Expansion is NO LONGER done inside the loop.
                # We now evaluate the score based on the unexpanded room sizes.
                score, _, _ = self.evaluate_adjacency_score()
                if score > best_score:
                    best_score = score
                    # Save the best placement found so far (with original dimensions)
                    best_placement = [
                        (r.name, r.x, r.y, r.width, r.height, r.rotated) for r in self.rooms
                    ]
                if score == len(self.adjacency_graph.edges):
                    break

        if best_placement:
            self.spatial_grid = {}
            for name, x, y, width, height, rotated in best_placement:
                room = next(r for r in self.rooms if r.name == name)
                room.x, room.y, room.width, room.height, room.rotated = x, y, width, height, rotated
                self._add_to_spatial_grid(room)

            # *** CHANGE IS HERE ***
            # After the best layout is restored, we now check if expansion is enabled
            # and only run the expansion logic if the checkbox was ticked.
            print("best_placement ", best_placement)
            if enable_expansion:
                self.expand_rooms_optimized()

            return True

        print("\n--- After placement (fixed rooms only) ---")
        for r in self.rooms:
            if getattr(r, "is_fixed", False):
                print(f"{r.name}: ({r.x}, {r.y}), size={r.width}x{r.height}")

        return False

    def expand_rooms_optimized(self, directions=None):
        """
        CORRECTED: Calls self.check_overlap with the correct (x, y, w, h) arguments
        and the 'ignore_room' argument.
        """
        if directions is None:
            directions = ['right', 'up', 'left', 'down']

        rooms_to_expand = self.rooms.copy()
        random.shuffle(rooms_to_expand)

        can_expand_any = True
        while can_expand_any:
            can_expand_any = False
            for room in rooms_to_expand:
                if room.is_fixed or room.x is None:
                    continue

                max_allowed = getattr(room, "max_expansion", 0)
                try:
                    max_allowed = int(max_allowed)
                except Exception:
                    max_allowed = 0
                if max_allowed <= 0:
                    continue

                for direction in directions:
                    if self._total_expansion_used(room) >= max_allowed:
                        break

                    new_x, new_y, new_width, new_height = room.x, room.y, room.width, room.height

                    if direction == 'right':
                        new_width += 1
                    elif direction == 'left':
                        new_x -= 1
                        new_width += 1
                    elif direction == 'up':
                        new_height += 1
                    elif direction == 'down':
                        new_y -= 1
                        new_height += 1

                    if self._total_expansion_used(room) + 1 > max_allowed:
                        continue

                    # Check 1: Boundaries
                    if not self.is_within_floor(new_x, new_y, new_width, new_height):
                        continue

                    # *** THIS IS THE FIX ***
                    is_safe_overlap = not self.check_overlap(new_x, new_y, new_width, new_height, ignore_room=room)
                    # *** END OF FIX ***

                    # Check 3: Non-adjacency
                    is_safe_non_adj = not self._check_non_adjacency_violation_at(room, new_x,
                                                                                 new_y)  # This helper is from Part 1

                    if is_safe_overlap and is_safe_non_adj:
                        # If safe, apply the expansion
                        room.x, room.y, room.width, room.height = new_x, new_y, new_width, new_height
                        can_expand_any = True  # We successfully expanded, so loop again

            # After each full pass, shuffle again to change expansion priority
            random.shuffle(rooms_to_expand)

    def can_expand_room_optimized(self, room, direction, amount):
        """Optimized room expansion check"""

        if room.x is None or room.y is None:
            return False

        # Check expansion limits
        current_expansion = 0
        if not room.rotated:
            current_expansion += room.width - room.original_width
            current_expansion += room.height - room.original_height
        else:
            current_expansion += room.width - room.original_height
            current_expansion += room.height - room.original_width

        if current_expansion + amount > room.max_expansion:
            return False

        # Calculate new dimensions
        new_x, new_y = room.x, room.y
        new_width, new_height = room.width, room.height

        if direction == 'right':
            new_width += amount
        elif direction == 'left':
            new_x -= amount
            new_width += amount
        elif direction == 'up':
            new_height += amount
        elif direction == 'down':
            new_y -= amount
            new_height += amount
        else:
            return False

        # Quick bounds check
        if not self.is_within_floor(new_x, new_y, new_width, new_height):
            return False

        # Use optimized overlap check
        return not self.check_overlap_optimized(room, new_x, new_y, new_width, new_height)

    def visualize(self):
        """Visualize the floor plan using matplotlib with non-adjacency constraints"""
        fig, ax = plt.subplots(figsize=(12, 10))

        # Draw floor shape
        for region in self.floor_regions:
            rect = patches.Rectangle(
                (region['x'], region['y']),
                region['width'],
                region['height'],
                linewidth=2,
                edgecolor='black',
                facecolor='none',
                linestyle='--'
            )
            ax.add_patch(rect)

        # Draw rooms
        colors = plt.cm.tab20(np.linspace(0, 1, len(self.rooms)))
        for i, room in enumerate(self.rooms):
            if room.x is not None and room.y is not None:
                rect = patches.Rectangle(
                    (room.x, room.y),
                    room.width,
                    room.height,
                    linewidth=1,
                    edgecolor='black',
                    facecolor=colors[i],
                    alpha=0.7
                )
                ax.add_patch(rect)

                # Add room name, size, and expansion info
                original_size = f"{room.original_width}x{room.original_height}"
                current_size = f"{room.width}x{room.height}"
                display_text = f"{room.name}\n{current_size}"

                # Add expansion info if expanded
                if room.width != room.original_width or room.height != room.original_height:
                    if room.rotated:
                        display_text += f"\n(from {room.original_height}x{room.original_width})"
                    else:
                        display_text += f"\n(from {original_size})"

                ax.text(
                    room.x + room.width / 2,
                    room.y + room.height / 2,
                    display_text,
                    ha='center',
                    va='center',
                    fontsize=8
                )

        # Add adjacency relationships as dotted lines between room centers
        for room1_name, room2_name in self.adjacency_graph.edges:
            room1 = next(r for r in self.rooms if r.name == room1_name)
            room2 = next(r for r in self.rooms if r.name == room2_name)

            if room1.x is not None and room2.x is not None:
                center1 = (room1.x + room1.width / 2, room1.y + room1.height / 2)
                center2 = (room2.x + room2.width / 2, room2.y + room2.height / 2)

                # Check if rooms share a wall
                if room1.has_shared_wall_with(room2):
                    # Satisfied adjacency - green solid line
                    ax.plot([center1[0], center2[0]], [center1[1], center2[1]], 'g-',
                            linewidth=2,
                            label='Adjacent (satisfied)' if room1_name == list(self.adjacency_graph.edges)[0][
                                0] else "")
                else:
                    # Unsatisfied adjacency - red dashed line
                    ax.plot([center1[0], center2[0]], [center1[1], center2[1]], 'r--',
                            linewidth=1.5, alpha=0.7,
                            label='Adjacent (unsatisfied)' if room1_name == list(self.adjacency_graph.edges)[0][
                                0] else "")

        # Add non-adjacency constraints visualization
        non_adjacency_satisfied = []
        non_adjacency_violated = []

        for room1_name, room2_name in self.non_adjacency_graph.edges:
            room1 = next(r for r in self.rooms if r.name == room1_name)
            room2 = next(r for r in self.rooms if r.name == room2_name)

            if room1.x is not None and room2.x is not None:
                center1 = (room1.x + room1.width / 2, room1.y + room1.height / 2)
                center2 = (room2.x + room2.width / 2, room2.y + room2.height / 2)

                # Check if rooms share a wall (this would be a violation)
                if room1.has_shared_wall_with(room2):
                    # Violation - rooms should not be adjacent but they are
                    ax.plot([center1[0], center2[0]], [center1[1], center2[1]], 'red',
                            linewidth=3, linestyle=':', alpha=0.8,
                            label='Non-adjacent (VIOLATED)' if len(non_adjacency_violated) == 0 else "")
                    non_adjacency_violated.append((room1_name, room2_name))

                    # Add warning symbols at room centers
                    ax.scatter(center1[0], center1[1], s=100, c='red', marker='X', alpha=0.8, zorder=10)
                    ax.scatter(center2[0], center2[1], s=100, c='red', marker='X', alpha=0.8, zorder=10)
                else:
                    # Satisfied - rooms are not adjacent as required
                    ax.plot([center1[0], center2[0]], [center1[1], center2[1]], 'blue',
                            linewidth=1.5, linestyle='-.', alpha=0.6,
                            label='Non-adjacent (satisfied)' if len(non_adjacency_satisfied) == 0 else "")
                    non_adjacency_satisfied.append((room1_name, room2_name))

        # Set limits and labels
        max_width = self.floor_width
        max_height = self.floor_height
        ax.set_xlim(-1, max_width + 1)
        ax.set_ylim(-1, max_height + 1)
        ax.set_aspect('equal')

        # Enhanced title with constraint satisfaction info
        score, adjacent_pairs, violations = self.evaluate_adjacency_score()
        title = f'Floor Plan - Adjacency: {len(adjacent_pairs)}/{len(self.adjacency_graph.edges)}'
        if len(self.non_adjacency_graph.edges) > 0:
            title += f', Non-Adjacency: {len(non_adjacency_satisfied)}/{len(self.non_adjacency_graph.edges)} satisfied'
        ax.set_title(title, fontsize=12, fontweight='bold')

        ax.set_xlabel('Width')
        ax.set_ylabel('Height')

        # Add legend if there are any constraint relationships
        if len(self.adjacency_graph.edges) > 0 or len(self.non_adjacency_graph.edges) > 0:
            # Create custom legend entries
            legend_elements = []

            if len(adjacent_pairs) > 0:
                legend_elements.append(plt.Line2D([0], [0], color='green', linewidth=2,
                                                  label=f'Adjacent (satisfied): {len(adjacent_pairs)}'))

            unsatisfied_adjacent = len(self.adjacency_graph.edges) - len(adjacent_pairs)
            if unsatisfied_adjacent > 0:
                legend_elements.append(plt.Line2D([0], [0], color='red', linewidth=1.5,
                                                  linestyle='--', alpha=0.7,
                                                  label=f'Adjacent (unsatisfied): {unsatisfied_adjacent}'))

            if len(non_adjacency_satisfied) > 0:
                legend_elements.append(plt.Line2D([0], [0], color='blue', linewidth=1.5,
                                                  linestyle='-.', alpha=0.6,
                                                  label=f'Non-adjacent (satisfied): {len(non_adjacency_satisfied)}'))

            if len(non_adjacency_violated) > 0:
                legend_elements.append(plt.Line2D([0], [0], color='red', linewidth=3,
                                                  linestyle=':', alpha=0.8,
                                                  label=f'Non-adjacent (VIOLATED): {len(non_adjacency_violated)}'))
                legend_elements.append(plt.Line2D([0], [0], marker='X', color='red',
                                                  linewidth=0, markersize=8, alpha=0.8,
                                                  label='Violation markers'))

            if legend_elements:
                ax.legend(handles=legend_elements, loc='upper left', bbox_to_anchor=(1.02, 1))

        # Add constraint satisfaction summary as text box
        if len(self.adjacency_graph.edges) > 0 or len(self.non_adjacency_graph.edges) > 0:
            summary_text = "Constraint Summary:\n"
            summary_text += f"• Adjacency: {len(adjacent_pairs)}/{len(self.adjacency_graph.edges)} satisfied\n"
            summary_text += f"• Non-adjacency: {len(non_adjacency_satisfied)}/{len(self.non_adjacency_graph.edges)} satisfied"

            if len(non_adjacency_violated) > 0:
                summary_text += f"\n• Violations: {len(non_adjacency_violated)} non-adjacency"

            # Add the text box
            props = dict(boxstyle='round', facecolor='wheat', alpha=0.8)
            ax.text(0.02, 0.98, summary_text, transform=ax.transAxes, fontsize=9,
                    verticalalignment='top', bbox=props)

        plt.tight_layout()
        plt.show()

        # Print detailed constraint information
        if len(self.non_adjacency_graph.edges) > 0:
            print("\n=== Non-Adjacency Constraint Details ===")
            print(f"Total non-adjacency constraints: {len(self.non_adjacency_graph.edges)}")
            print(f"Satisfied: {len(non_adjacency_satisfied)}")
            print(f"Violated: {len(non_adjacency_violated)}")

            if non_adjacency_satisfied:
                print(f"Satisfied non-adjacency pairs: {non_adjacency_satisfied}")

            if non_adjacency_violated:
                print(f"VIOLATED non-adjacency pairs: {non_adjacency_violated}")
                print("⚠️  These rooms should NOT be adjacent but currently share walls!")

    def print_statistics(self):
        """Print statistics about the floor plan"""
        total_area = sum(region['width'] * region['height'] for region in self.floor_regions)
        used_area = sum(room.width * room.height for room in self.rooms if room.x is not None)

        print(f"Floor area: {total_area} square units")
        print(f"Room area: {used_area} square units")
        print(f"Space utilization: {used_area / total_area:.2%}")

        score, adjacent_pairs, violations = self.evaluate_adjacency_score()
        print(f"Adjacency score: {score}/{len(self.adjacency_graph.edges)}")
        print(f"Adjacent pairs: {adjacent_pairs}")

        print(f"Non-adjacency constraints: {len(self.non_adjacency_graph.edges)}")
        print(f"Non-adjacency violations: {len(violations)}")
        if violations:
            print(f"Violated non-adjacent pairs: {violations}")

        # Print expansion statistics
        print("\nRoom Expansion Statistics:")
        for room in self.rooms:
            if room.x is not None:
                original_area = room.original_width * room.original_height
                current_area = room.width * room.height
                expansion_pct = (current_area - original_area) / original_area * 100 if original_area > 0 else 0

                # Calculate how much of the max expansion was used
                if not room.rotated:
                    total_expansion = (room.width - room.original_width) + (room.height - room.original_height)
                else:
                    total_expansion = (room.width - room.original_height) + (room.height - room.original_width)

                expansion_usage = f"{total_expansion}/{room.max_expansion}"

                print(f"{room.name}: {room.original_width}x{room.original_height} → {room.width}x{room.height} " +
                      f"({expansion_pct:.1f}% increase, expansion used: {expansion_usage})")

    def to_matrix(self, grid_resolution=1):

        matrix_width = int(self.floor_width / grid_resolution)
        matrix_height = int(self.floor_height / grid_resolution)

        matrix = [['#' for _ in range(matrix_width)] for _ in range(matrix_height)]

        for region in self.floor_regions:
            start_x = int(region['x'] / grid_resolution)
            start_y = int(region['y'] / grid_resolution)
            end_x = int((region['x'] + region['width']) / grid_resolution)
            end_y = int((region['y'] + region['height']) / grid_resolution)

            for y in range(start_y, min(end_y, matrix_height)):
                for x in range(start_x, min(end_x, matrix_width)):
                    matrix[y][x] = '.'

        room_symbols = []
        for i in range(10):
            room_symbols.append(str(i))
        for i in range(26):
            room_symbols.append(chr(ord('A') + i))  # Append letters A-Z

        room_legend = {}
        placed_rooms = [room for room in self.rooms if room.x is not None and room.y is not None]

        for i, room in enumerate(placed_rooms):
            if i < len(room_symbols):
                room_legend[room.name] = room_symbols[i]
            else:
                room_legend[room.name] = f"R{i}"

        for room in placed_rooms:
            if room.name in room_legend:
                symbol = room_legend[room.name]

                start_x = int(room.x / grid_resolution)
                start_y = int(room.y / grid_resolution)
                end_x = int((room.x + room.width) / grid_resolution)
                end_y = int((room.y + room.height) / grid_resolution)

                for y in range(start_y, min(end_y, matrix_height)):
                    for x in range(start_x, min(end_x, matrix_width)):
                        if 0 <= y < matrix_height and 0 <= x < matrix_width:
                            matrix[y][x] = symbol

        return matrix, room_legend

    def floorplan_to_ga_input(self):
        """Convert FloorPlan's placed rooms to GA's expected input formats"""

        # Separate movable and fixed rooms
        movable_rooms = [room for room in self.rooms if not getattr(room, "is_fixed", False)]
        fixed_rooms = [room for room in self.rooms if getattr(room, "is_fixed", False)]

        # Get matrix size from floor dimensions
        matrix_width = int(self.floor_width)
        matrix_height = int(self.floor_height)

        # Create initial_grid with BOTH movable AND fixed rooms
        initial_grid = np.zeros((matrix_height, matrix_width), dtype=int)

        # Create room_legend for ALL rooms (movable + fixed)
        room_symbols = []
        for i in range(10):
            room_symbols.append(str(i))
        for i in range(26):
            room_symbols.append(chr(ord('A') + i))

        room_legend = {}
        room_id_counter = 1

        # Process FIXED rooms FIRST (they get lower IDs and won't be moved)
        for i, room in enumerate(fixed_rooms):
            if room.x is not None and room.y is not None:
                if i < len(room_symbols):
                    symbol = room_symbols[i]
                else:
                    symbol = f"F{i}"

                room_legend[room.name] = {'symbol': symbol, 'id': room_id_counter, 'is_fixed': True}

                # Place fixed room in initial_grid
                start_x = int(room.x)
                start_y = int(room.y)
                end_x = int(room.x + room.width)
                end_y = int(room.y + room.height)

                for y in range(start_y, min(end_y, matrix_height)):
                    for x in range(start_x, min(end_x, matrix_width)):
                        if 0 <= y < matrix_height and 0 <= x < matrix_width:
                            initial_grid[y, x] = room_id_counter

                room_id_counter += 1

        # Process MOVABLE rooms AFTER fixed rooms
        for i, room in enumerate(movable_rooms):
            if room.x is not None and room.y is not None:
                idx = i + len(fixed_rooms)
                if idx < len(room_symbols):
                    symbol = room_symbols[idx]
                else:
                    symbol = f"M{i}"

                room_legend[room.name] = {'symbol': symbol, 'id': room_id_counter, 'is_fixed': False}

                # Place movable room in initial_grid
                start_x = int(room.x)
                start_y = int(room.y)
                end_x = int(room.x + room.width)
                end_y = int(room.y + room.height)

                for y in range(start_y, min(end_y, matrix_height)):
                    for x in range(start_x, min(end_x, matrix_width)):
                        if 0 <= y < matrix_height and 0 <= x < matrix_width:
                            initial_grid[y, x] = room_id_counter

                room_id_counter += 1

        # Create region_matrix from FloorPlan's floor_regions
        region_matrix = np.full((matrix_height, matrix_width), '#', dtype=object)

        for region in self.floor_regions:
            start_x, start_y = int(region['x']), int(region['y'])
            end_x = int(region['x'] + region['width'])
            end_y = int(region['y'] + region['height'])

            for y in range(start_y, min(end_y, matrix_height)):
                for x in range(start_x, min(end_x, matrix_width)):
                    region_matrix[y, x] = '0'  # Valid region

        # DON'T mark fixed rooms as '#' in region_matrix - keep them as '0' so corridors can reach them

        # Create room names mapping (ID -> name) for ALL rooms
        room_names = {info['id']: name for name, info in room_legend.items()}

        # Create room dimensions mapping (ID -> (width, height)) for ALL rooms
        room_dimensions = {}
        for name, info in room_legend.items():
            room_id = info['id']
            # Find the room object in either list
            for room in self.rooms:
                if room.name == name:
                    room_dimensions[room_id] = (room.width, room.height)
                    break

        # Create a list of fixed room IDs to pass to GA
        fixed_room_ids = [info['id'] for name, info in room_legend.items() if info.get('is_fixed', False)]

        return initial_grid, region_matrix, room_names, room_dimensions, fixed_room_ids

    @staticmethod
    def ga_runner(init_grid, region_matrix, room_names=None, room_dimensions=None, corridor_width=2,
                  fixed_room_ids=None):
        ga.run_ga(init_grid, region_matrix, room_names, room_dimensions, corridor_width, fixed_room_ids)

    def generate_layout(self, max_attempts=1000, enable_expansion=True, enable_space_optimization=True):
        """
        CORRECTED: Removes the final compact_rooms() call that undoes the right-shift.
        All functions called by this are now safe.
        """
        print("--- Starting layout generation ---")

        for room in self.rooms:
            if not getattr(room, "is_fixed", False):
                room.reset_to_original_size()
                room.x = None
                room.y = None

        for room in self.fixed_rooms:
            room.reset_to_original_size()

        # STEP 1: Place rooms (original size)
        success = self.place_rooms_with_constraints_optimized(
            max_attempts=max_attempts,
            enable_expansion=False,
            use_compact_mode=enable_space_optimization
        )

        if success:
            print("Initial placement successful.")

            for i in range(5):
                # STEP 2: "Down-and-Left" shift
                self.compact_rooms()
                print("After down-left compact:", [(r.name, r.x, r.y) for r in self.rooms if r.x is not None])

                # STEP 3: "Conditional Right-Shift" (Now safe)
                self.compact_rooms_right_conditional()
                print("After conditional-right compact:", [(r.name, r.x, r.y) for r in self.rooms if r.x is not None])

                self.compact_rooms_up_conditional()
                # self.compact_rooms()

                # STEP 4: Fix adjacencies (Now safe)
                self.enforce_minimum_adjacency()
                print("After enforcing adjacency.")

                # *** THIS IS THE LOGIC FIX ***
                # The final compact_rooms() is removed. Your logs show it was
                # undoing the right-shift from Step 3, creating the vertical stack.
                # self.compact_rooms() # <-- THIS LINE IS GONE.
                # *** END OF LOGIC FIX ***

                print("After enforce (no final compact):",
                      [(r.name, r.x, r.y) for r in self.rooms if r.x is not None])

                # STEP 5: Expand rooms to fill gaps (Now safe)
                if enable_expansion:
                    print("--- Starting final expansion to fill gaps ---")
                    self.expand_rooms_optimized()
                    print("--- Finished final expansion ---")

                print("--- Layout generation complete ---")

        else:
            print("--- Layout generation FAILED ---")

        return success


# Example usage
if __name__ == "__main__":
    # Define floor shape with explicit x and y coordinates for each region
    # This example creates an L-shaped floor plan
    region_specs = [
        {'x': 0, 'y': 0, 'width': 10, 'height': 10},  # Main square part
        {'x': 10, 'y': 0, 'width': 8, 'height': 5},  # Right extension
        {'x': 0, 'y': 10, 'width': 5, 'height': 8},  # Top extension
        {'x': 10, 'y': 5, 'width': 6, 'height': 6}
    ]

    floor_plan = FloorPlan(region_specs)

    # Add rooms with dimensions and custom max expansion limits
    floor_plan.add_room("Living Room", 8, 4, max_expansion=15)
    floor_plan.add_room("Kitchen", 6, 4, max_expansion=8)
    floor_plan.add_room("Bedroom 1", 5, 4, max_expansion=10)
    floor_plan.add_room("Bedroom 2", 5, 4, max_expansion=6)
    floor_plan.add_room("Bathroom", 3, 4, max_expansion=2)  # Limited expansion for bathroom
    floor_plan.add_room("Hallway", 2, 4, max_expansion=5)
    floor_plan.add_room("Office", 3, 3, max_expansion=0)  # No expansion allowed for office
    floor_plan.add_room("secretRoom", 3, 3, 3)

    # Add adjacency requirements
    floor_plan.add_adjacency("Living Room", "Kitchen")
    floor_plan.add_adjacency("Living Room", "Bathroom")
    floor_plan.add_adjacency("Kitchen", "Bedroom 1")
    floor_plan.add_adjacency("Bedroom 2", "Hallway")
    floor_plan.add_adjacency("Hallway", "Bathroom")
    floor_plan.add_adjacency("Office", "Bedroom 2")
    floor_plan.add_adjacency("secretRoom", "Kitchen")

    floor_plan.add_non_adjacency("Living Room", "Bedroom 1")

    # Try to place rooms with expansion enabled
    success = floor_plan.place_rooms_with_constraints_optimized(max_attempts=500, enable_expansion=True)
    print("After placement:", [(r.name, r.x, r.y) for r in floor_plan.rooms if getattr(r, "is_fixed", False)])
    if success:
        # Compact the floorplan to minimize area
        floor_plan.compact_rooms()
        print("After compact:", [(r.name, r.x, r.y) for r in floor_plan.rooms if getattr(r, "is_fixed", False)])
        floor_plan.enforce_minimum_adjacency()
        floor_plan.compact_rooms()
        print("After enforce+final compact:",
              [(r.name, r.x, r.y) for r in floor_plan.rooms if getattr(r, "is_fixed", False)])

        print("Successfully placed all rooms!")
        floor_plan.print_statistics()
        init_grid, reg_matrix, room_names, room_dimensions, fixed_rooms_ids = floor_plan.floorplan_to_ga_input()
        print(init_grid)
        print(reg_matrix)
    else:
        print("Failed to place all rooms. You may need to adjust room or floor dimensions.")

    # Print room placements and sizes
    for room in floor_plan.rooms:
        print(room)

    # Visualize the floor plan
    floor_plan.visualize()
    FloorPlan.ga_runner(init_grid, reg_matrix, room_names=room_names, room_dimensions=room_dimensions,
                        fixed_room_ids=fixed_rooms_ids)