from itertools import cycle
import numpy as np
import copy

def labels(b):
    '''Give labels to the walls corresponds to height and width walls in the boundary'''
    b_labels = {}
    for i, w in enumerate(b):
        b_labels[tuple(w)] = "w" if i % 2 == 0 else "h"
    return b_labels

def is_reflections(b1, b2):
    """Check whether the two boundaaries are reflection of each other"""
    if len(b1) != len(b2):
        return False

    b1_labels = labels(b1)
    b2_labels = labels(b2)

    for wall in b1_labels:
        if wall not in b2_labels:
            return False
        if b1_labels[wall] != b2_labels[wall]:
            return False

    return True

def remove_reflections(p):
    """"Give the list of boundaries after filteing out the reflections"""
    unique = []
    for b in p:
        if not any(is_reflections(b, u) for u in unique):
            unique.append(b)
    return unique  

def is_circularly_connected(boundary):
    """"Circularly connects the walls after checking the eligible walls 
    for height and width corresponding to a selected boundary """
    for i, wall in enumerate(boundary):
        curr = wall
        next_wall = boundary[(i+1) % 4]
        # The second room of current must match first room of next
        if curr[-1] != next_wall[0]:
            return False
    return True


def paths_after_select_bdy(list_filtr_walls, selected_bdy, rooms, plot_wt, plot_ht, wall_possibility, threshold_ratio, count_condition):
    """Select and print paths after identifying the boundary which satisfies """
    filtr_bdys = []
    pos_bdy = []
    odd_indices = [1, 3]
    even_indices = [0, 2]

    if wall_possibility == "h":
        target_indices = odd_indices
    else:
        target_indices = even_indices

    for wall in list_filtr_walls:
        for idx_target in target_indices:
            rearr_bdy = [None] * 4
            rearr_bdy[idx_target] = wall

            # Remaining walls in selected_bdy except the current wall
            remaining = [w for w in selected_bdy if w != wall]

            # Circularly fill remaining positions
            idx = (idx_target + 1) % 4
            for w in remaining:
                while rearr_bdy[idx] is not None:
                    idx = (idx + 1) % 4
                rearr_bdy[idx] = w

            print(f"Selected boundary {wall_possibility}:", rearr_bdy)
            
            count = 0
            for ind, pth in enumerate(rearr_bdy):
                total_width = sum(rooms[r]['width'] for r in pth if r in rooms)
                total_height = sum(rooms[r]['height'] for r in pth if r in rooms)

                remaining_wt = plot_wt - total_width
                remaining_ht = plot_ht - total_height

                if ind % 2 != 0 and threshold_ratio * plot_ht >= remaining_ht >= 0:
                    count += 1
                elif ind % 2 == 0 and threshold_ratio * plot_wt >= remaining_wt >= 0:
                    count += 1

            if count_condition(count) and is_circularly_connected(rearr_bdy):
                pos_bdy.append(rearr_bdy)
            else:
                print("The selected boundary is not a good fit")

    filtr_bdys = remove_reflections(pos_bdy)

    return filtr_bdys

def dim_on_paths_bdy(all_bdy, room_w, room_h, plot_width, plot_height, bdy_edges):
    """Calculate room dimensions on paths, corresponding plot dimension 
    differences and returns the list of sorted paths."""   
    outer_rooms = []
    for i in range(len(bdy_edges)):
        r1 = bdy_edges[i][0]
        r2 = bdy_edges[i][1]
        if r1 not in outer_rooms:
            outer_rooms.append(r1)
        if r2 not in outer_rooms:
            outer_rooms.append(r2)
    print(outer_rooms)
    # Create a list of room widths and heights for the outer rooms
    new_room_w = []
    new_room_h = []
    new_indices = []
    for itr in range(len(room_w)):
        if itr in outer_rooms:
            new_room_w.append(room_w[itr])
            new_room_h.append(room_h[itr])
            new_indices.append(itr)
            print(new_indices)
    room_w = copy.deepcopy(new_room_w)
    room_h = copy.deepcopy(new_room_h)

    print("list of boundary edges widths",room_w)
    print("list of boundary edges heights",room_h)

    # Create a dictionary of the outer rooms
    rooms = {}
    for i in range(len(new_indices)):
        rooms[new_indices[i]] = {
        'width': room_w[i],
        'height': room_h[i]
         }

    print(rooms)
 
    # Iterate over each path in all boundaries

    def attempt_with_threshold(threshold_ratio, count_condition):
        sorted_bdys = []
        for bdy in all_bdy:
            print(f"\n{bdy}")
            result = []  # Reset `result` for each path
            for path in bdy:
                # Calculate the sum of widths and heights for the current path
                total_width = sum(rooms[r]['width'] for r in path if r in rooms)
                total_height = sum(rooms[r]['height'] for r in path if r in rooms)

                width_diff = plot_width - total_width
                height_diff = plot_height - total_height
                result.append([width_diff, height_diff, path])
            print(f"The matrix has pointers and corresponding path: {result}")

            # Sorting results by 'width_diff' and 'height_diff'
            sorted_result_col_i = sorted(result, key=lambda r: r[0])
            sorted_result_col_ii = sorted(result, key=lambda r: r[1])
            
            # Prepare sorted lists for width and height columns
            sorted_col_i, path_list_col_i = zip(*[(row[0], row[2]) for row in sorted_result_col_i])
            sorted_col_ii, path_list_col_ii = zip(*[(row[1], row[2]) for row in sorted_result_col_ii])        

            # Find pointers for width and height
            pointers_w = [(x, y) for x, y in zip(sorted_col_i, path_list_col_i) if 0 <= x <= 0.2 * plot_width]
            pointers_h = [(x, y) for x, y in zip(sorted_col_ii, path_list_col_ii) if 0 <= x <= 0.2 * plot_height]

            print(f"Pointers for width: {pointers_w}")
            print(f"Pointers for height: {pointers_h}")

            # Determine south and west boundaries
            width_paths, height_paths = [], []

            if pointers_h and pointers_w:
                height_paths = [y for _, y in pointers_h]  # Collect all height walls values
                print(f"Possible height walls: {height_paths}")

                width_paths = [y for _, y in pointers_w]   # Collect all width walls values
                print(f"Possible width walls: {width_paths}")

            elif pointers_h:
                height_paths = [y for _, y in pointers_h]  # Only height available
                print(f"Possible height walls: {height_paths}")

            elif pointers_w:
                width_paths = [y for _, y in pointers_w]  # Only width available
                print(f"Possible width walls: {width_paths}")

            else:
                print("No valid walls found. Path is not suitable.")

            # Call the boundary selection function
            if height_paths:
                sat_paths = paths_after_select_bdy(height_paths, bdy, rooms, plot_width, plot_height,"h", threshold_ratio, count_condition)
                for pth in sat_paths:
                    sorted_bdys.append(pth)
            if width_paths:
                sat_paths =  paths_after_select_bdy(width_paths, bdy, rooms, plot_width, plot_height, "w", threshold_ratio, count_condition)
                for pth in sat_paths:
                    sorted_bdys.append(pth)
            else:
                print("No combination of walls found such that the path satisfies the 20 percent criteria")
        return remove_reflections(sorted_bdys)

    # First attempt with 0.2 and strict count == 4
    final_sorted_bdys = attempt_with_threshold(0.2, lambda c: c == 4)

    # If empty, try 0.3 with count == 4
    if not final_sorted_bdys:
        print("No valid paths found with 20%, trying with 30% threshold and strict count.")
        final_sorted_bdys = attempt_with_threshold(0.3, lambda c: c == 4)

    # If still empty, try with relaxed count >= 3
    if not final_sorted_bdys:
        print("No valid paths found with 30% and strict count. Relaxing to count >= 3.")
        final_sorted_bdys = attempt_with_threshold(0.3, lambda c: c >= 3)

    return final_sorted_bdys




