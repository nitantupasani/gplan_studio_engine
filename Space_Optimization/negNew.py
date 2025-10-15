import matplotlib.pyplot as plt
import matplotlib.patches as patches
import networkx as nx
import numpy as np
import random
import heapq
from collections import defaultdict, deque


class Room:
        def __init__(self, name, width, height, max_expansion=20):
            self.name = name
            self.original_width = width
            self.original_height = height
            self.width = width
            self.height = height
            self.x = None
            self.y = None
            self.rotated = False
            self.max_expansion = max_expansion

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
        self.entrance_coords = None # For entrance adjacency

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

    def add_room(self, name, width, height, max_expansion=20, fixed_x=None, fixed_y=None):
        room = Room(name, width, height, max_expansion)
        if fixed_x is not None and fixed_y is not None:
            room.x, room.y = fixed_x, fixed_y
            room.is_fixed = True
            room.max_expansion = 0
            room.rotated = False
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

    def add_fixed_room(self, width, height, fixed_x, fixed_y, name=None, max_expansion=0, ui=None):
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
        return self.add_room(chosen_name, width, height, max_expansion=max_expansion, fixed_x=fixed_x, fixed_y=fixed_y)

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

    def check_overlap(self, room, x, y, width, height):
        for existing_room in self.rooms:
            if existing_room.x is not None and existing_room != room:
                if (x < existing_room.x + existing_room.width and
                        x + width > existing_room.x and
                        y < existing_room.y + existing_room.height and
                        y + height > existing_room.y):
                    return True
        return False

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
        Ensure every room is adjacent to at least one other room.
        If a room has no adjacencies, try to move it next to another room.
        """
        for room in self.rooms:
            if getattr(room, "is_fixed", False):
                continue
            if room.x is None or room.y is None:
                continue

            # Check if this room shares a wall with any other room
            has_adjacency = any(
                room.has_shared_wall_with(other)
                for other in self.rooms
                if other != room and other.x is not None and other.y is not None
            )
            if not has_adjacency:
                # Try to move the room next to another room
                found = False
                for candidate in self.rooms:
                    if candidate == room or candidate.x is None or candidate.y is None:
                        continue

                    # Try all four sides of the candidate room
                    possible_positions = [
                        (candidate.x - room.width, candidate.y),  # left
                        (candidate.x + candidate.width, candidate.y),  # right
                        (candidate.x, candidate.y + candidate.height),  # above
                        (candidate.x, candidate.y - room.height),  # below
                    ]
                for new_x, new_y in possible_positions:
                    # Check if the new position would create a non-adjacency violation
                    is_non_adjacent_violation = False
                    for existing_room in self.rooms:
                        if existing_room != room and existing_room.x is not None and existing_room.y is not None:
                            if self.non_adjacency_graph.has_edge(room.name, existing_room.name):
                                # Temporarily set room's position to check for wall sharing
                                original_x, original_y = room.x, room.y
                                room.x, room.y = new_x, new_y
                                if room.has_shared_wall_with(existing_room):
                                    is_non_adjacent_violation = True
                                room.x, room.y = original_x, original_y  # Restore original position
                                if is_non_adjacent_violation:
                                    break
                    if is_non_adjacent_violation:
                        continue

                    if self.is_within_floor(new_x, new_y, room.width, room.height) and \
                            not self.check_overlap(room, new_x, new_y, room.width, room.height):
                        # Move room here
                        room.x = new_x
                        room.y = new_y
                        # Double-check if this now shares a wall with any room
                        if any(
                                room.has_shared_wall_with(other)
                                for other in self.rooms
                                if other != room and other.x is not None and other.y is not None
                        ):
                            found = True
                            break
                if found:
                    break

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

        if self.check_overlap(room, new_x, new_y, new_width, new_height):
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
        for room in self.rooms:
            if getattr(room, "is_fixed", False):
                continue
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
                if not getattr(room, "is_fixed", False):
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
                if room.x is not None and room.y is not None:
                    continue

                placed = False
                valid_positions = self.get_valid_positions(room, max_positions=30)
                if valid_positions:
                    x, y = random.choice(valid_positions)
                    room.x, room.y = x, y
                    self._add_to_spatial_grid(room)
                    placed = True

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
            if enable_expansion:
                self.expand_rooms_optimized()

            return True

        return False

    def expand_rooms_optimized(self):
        """Optimized room expansion using spatial grid"""
        for room in self.rooms:
            if getattr(room, "is_fixed", False):
                continue

            if room.x is None or room.y is None:
                continue

            # Remove from spatial grid temporarily
            self._remove_from_spatial_grid(room)

            # Try expansion in each direction
            directions = ['right', 'down', 'left', 'up']
            random.shuffle(directions)

            for direction in directions:
                # Try expanding in larger increments first, then smaller
                for increment in [5,4,3,2,1]:
                    while self.can_expand_room_optimized(room, direction, increment):
                        # Apply expansion
                        if direction == 'right':
                            room.width += increment
                        elif direction == 'left':
                            room.x -= increment
                            room.width += increment
                        elif direction == 'up':
                            room.height += increment
                        elif direction == 'down':
                            room.y -= increment
                            room.height += increment

            # Add back to spatial grid
            self._add_to_spatial_grid(room)

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

    def generate_layout(self, max_attempts=1000, enable_expansion=True, enable_space_optimization=True):
        # """
        # Generate a floor plan layout by placing rooms within the boundary.

        # Parameters:
        # - max_attempts (int): Maximum number of attempts to place rooms.
        # - enable_expansion (bool): Allow rooms to expand up to their max_expansion limit.
        # - enable_space_optimization (bool): Optimize space usage by minimizing unused areas.

        # Returns:
        # - bool: True if layout generation is successful, False otherwise.
        # """
        success = self.place_rooms_with_constraints_optimized(
            max_attempts=max_attempts,
            enable_expansion=enable_expansion,
            use_compact_mode=enable_space_optimization
        )
        print("After placement:", [(r.name, r.x, r.y) for r in self.rooms if getattr(r, "is_fixed", False)])
        if success:
            # Enforce minimum adjacency and compact rooms, as in the example usage
            self.compact_rooms()

            print("After compact:",[(r.name, r.x, r.y) for r in self.rooms if getattr(r, "is_fixed", False)])
            self.enforce_minimum_adjacency()
            self.compact_rooms()

            print("After enforce+final compact:",
                  [(r.name, r.x, r.y) for r in self.rooms if getattr(r, "is_fixed", False)])
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
    else:
        print("Failed to place all rooms. You may need to adjust room or floor dimensions.")

    # Print room placements and sizes
    for room in floor_plan.rooms:
        print(room)

    # Visualize the floor plan
    floor_plan.visualize()