from itertools import cycle
import numpy as np
import copy

def room_dim(rows, room_w, room_h):
    """Create a matrix containing room dimensions."""
    # Initialize the matrix with rows containing [width, height]
    return [[room_w[i], room_h[i]] for i in range(rows)]


def paths_after_select_bdy(bdy, path, room_wt, room_ht, plot_wt, plot_ht):
    """Select and print paths after identifying the boundary which satisfies """
    pos_bdy = []
    for b in bdy:
        selected_bdy = [0, 0, 0, 0]
        for i, p in enumerate(path):
            if p == b:
                ind_b = i
                selected_bdy[3] = p

                # Use modulo to ensure circular indexing for the next 3 elements
                selected_bdy[0] = path[(ind_b + 1) % len(path)]
                selected_bdy[1] = path[(ind_b + 2) % len(path)]
                selected_bdy[2] = path[(ind_b + 3) % len(path)]
                break  # Stop after finding the boundary

        print("Selected Path:", selected_bdy)
        count = 0
        for ind, pth in enumerate(selected_bdy):
            # Ensure pth is a valid index before accessing room_wt or room_ht
            remaining_wt = plot_wt - sum(room_wt[i] for i in pth if 0 <= i < len(room_wt))
            remaining_ht = plot_ht - sum(room_ht[i] for i in pth if 0 <= i < len(room_ht))
            if ind % 2 != 0 and 0.2 * plot_ht >= abs(remaining_ht):
                    count +=1
            elif 0.2 * plot_wt >= abs(remaining_wt):
                    count += 1
        if count >= 3:
            print(f"The number of path satisfied is: {count}")
            pos_bdy.append(selected_bdy)
        else:
            print("The selected path is not a good fit")

    return pos_bdy

def dim_on_paths_bdy(all_bdy, room_w, room_h, plot_width, plot_height,bdy_edges):
    """Calculate room dimensions on paths, corresponding plot dimension differences and returns the list of sorted paths."""
    outer_rooms = []
    for i in range(len(bdy_edges)):
        r1 = bdy_edges[i][0]
        r2 = bdy_edges[i][1]
        if r1 not in outer_rooms:
            outer_rooms.append(r1)
        if r2 not in outer_rooms:
            outer_rooms.append(r2)
    # Create a list of room widths and heights for the outer rooms
    new_room_w = []
    new_room_h = []
    for itr in range(len(room_w)):
        if itr in outer_rooms:
            new_room_w.append(room_w[itr])
            new_room_h.append(room_h[itr])
    room_w = copy.deepcopy(new_room_w)
    room_h = copy.deepcopy(new_room_h)


    sorted_bdys = []

    # Iterate over each path in all boundaries
    for path in all_bdy:
        print(f"\n{path}")
        result = []  # Reset `result` for each path
        for sub_path in path:
            # Calculate the sum of widths and heights for the current path
            width_sum = plot_width - sum(room_w[i] for i in sub_path if i < len(room_w))
            height_sum = plot_height - sum(room_h[i] for i in sub_path if i < len(room_h))
            result.append([width_sum, height_sum, sub_path])
        print(f"The matrix has pointers and corresponding path: {result}")

        # Sorting results by width and height
        sorted_result_col_i = sorted(result, key=lambda r: r[0])
        sorted_result_col_ii = sorted(result, key=lambda r: r[1])

        # Prepare sorted lists for width and height columns
        sorted_col_i, path_list_col_i = zip(*[(row[0], row[2]) for row in sorted_result_col_i])
        sorted_col_ii, path_list_col_ii = zip(*[(row[1], row[2]) for row in sorted_result_col_ii])

        # Print sorted lists
        print(f"Sorted list for width column: {sorted_col_i}")
        # print(f"Sorted path list for width column: {path_list_col_i}")
        print(f"Sorted list for height column: {sorted_col_ii}")
        # print(f"Sorted path list for height column: {path_list_col_ii}")

        # Find pointers for width and height
        pointers_w = {x: y for x, y in zip(sorted_col_i, path_list_col_i) if abs(x) <= 0.2 * plot_width}
        pointers_h = {x: y for x, y in zip(sorted_col_ii, path_list_col_ii) if abs(x) <= 0.2 * plot_height}

        print(f"Pointers for width: {pointers_w}")
        print(f"Pointers for height: {pointers_h}")

        # Determine south and west boundaries
        south_paths, west_paths = [], []

        if pointers_h and pointers_w:
            west_paths = list(pointers_h.values())  # Collect all west boundary values
            print(f"Possible West boundaries: {west_paths}")

            south_paths = list(pointers_w.values())  # Collect all south boundary values
            print(f"Possible South boundaries: {south_paths}")

        elif pointers_h:
            west_paths = list(pointers_h.values())  # Only west boundary available
            print(f"Possible West boundaries: {west_paths}")

        elif pointers_w:
            south_paths = list(pointers_w.values())  # Only south boundary available
            print(f"Possible South boundaries: {south_paths}")

        else:
            print("No valid boundaries found. Path is not suitable.")

        # Call the path selection function
        if west_paths != [] and south_paths != []:
            sat_paths = paths_after_select_bdy(west_paths, path, room_w, room_h, plot_width, plot_height)
            for s_bdy in sat_paths:
                sorted_bdys.append(s_bdy)
            sats_paths = paths_after_select_bdy(south_paths, path, room_w, room_h, plot_width, plot_height)
            for s_bdy in sats_paths:
                sorted_bdys.append(s_bdy)
        elif west_paths:
            sat_paths = paths_after_select_bdy(west_paths, path, room_w, room_h, plot_width, plot_height)
            for s_bdy in sat_paths:
                sorted_bdys.append(s_bdy)
        elif south_paths:
            sat_paths =  paths_after_select_bdy(south_paths, path, room_w, room_h, plot_width, plot_height)
            for s_bdy in sat_paths:
                sorted_bdys.append(s_bdy)
        else:
            print("The path not satisfied the 20 percent criteria")
            
    return sorted_bdys





