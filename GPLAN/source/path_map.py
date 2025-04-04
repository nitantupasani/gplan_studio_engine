from itertools import cycle
import numpy as np
import copy

def room_dim(rows, room_w, room_h):
    """Create a matrix containing room dimensions."""
    # Initialize the matrix with rows containing [width, height]
    return [[room_w[i], room_h[i]] for i in range(rows)]


def paths_after_select_bdy(list_filtr_walls, selected_bdy, room_wt, room_ht, plot_wt, plot_ht):
    """Select and print paths after identifying the boundary which satisfies """
    pos_bdy = []
    
    for w in list_filtr_walls:
        rearr_bdy = [None] * 4

        for i, p in enumerate(selected_bdy):
            if p == w :
                if i % 2 == 0:
                    wll = "h"
                    rearr_bdy = [p, selected_bdy[(i + 1) % len(selected_bdy)], 
                                    selected_bdy[(i + 2) % len(selected_bdy)], 
                                    selected_bdy[(i + 3) % len(selected_bdy)]]
                    

                else:
                    wll = "w"
                    rearr_bdy = [selected_bdy[(i + 3) % len(selected_bdy)], p, 
                                    selected_bdy[(i + 1) % len(selected_bdy)], 
                                    selected_bdy[(i + 2) % len(selected_bdy)]]
            else:
                continue        

            print(f"Selected boundary{wll}:", rearr_bdy)
            count = 0
            for ind, pth in enumerate(rearr_bdy):
                remaining_wt = plot_wt - sum(room_wt[i] for i in pth if 0 <= i < len(room_wt))
                remaining_ht = plot_ht - sum(room_ht[i] for i in pth if 0 <= i < len(room_ht))
                if ind % 2 != 0 and 0.2 * plot_ht >= remaining_ht and remaining_ht > 0:
                    count += 1
                elif 0.2 * plot_wt >= remaining_wt and remaining_wt > 0:
                    count += 1
            
            if count >= 3:
                print(f"The number of path satisfied is: {count}")
                pos_bdy.append(rearr_bdy)
            else:
                print("The selected boundary is not a good fit")
        
        print(f"The pos_bdy is:{pos_bdy}")

    return pos_bdy

def dim_on_paths_bdy(all_bdy, room_w, room_h, plot_width, plot_height, bdy_edges):
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

    print("list of boundary edges widths",new_room_w)
    print("list of boundary edges heights",new_room_h)

    """Calculate room dimensions on paths, corresponding plot dimension differences and returns the list of sorted paths."""
    sorted_bdys = []
    # Iterate over each path in all boundaries
    for bdy in all_bdy:
        print(f"\n{bdy}")
        result = []  # Reset `result` for each path
        for path in bdy:
            # Calculate the sum of widths and heights for the current path
            width_diff = plot_width - sum(room_w[i] for i in path if i < len(room_w))
            height_diff = plot_height - sum(room_h[i] for i in path if i < len(room_h))
            result.append([width_diff, height_diff, path])
        print(f"The matrix has pointers and corresponding path: {result}")

        # Sorting results by 'width_diff' and 'height_diff'
        sorted_result_col_i = sorted(result, key=lambda r: r[0])
        print(sorted_result_col_i)
        sorted_result_col_ii = sorted(result, key=lambda r: r[1])
        print(sorted_result_col_ii)

        # Prepare sorted lists for width and height columns
        sorted_col_i, path_list_col_i = zip(*[(row[0], row[2]) for row in sorted_result_col_i])
        sorted_col_ii, path_list_col_ii = zip(*[(row[1], row[2]) for row in sorted_result_col_ii])

        # Print sorted lists
        print(f"Sorted list for width column: {sorted_col_i}")
        # print(f"Sorted path list for width column: {path_list_col_i}")
        print(f"Sorted list for height column: {sorted_col_ii}")
        # print(f"Sorted path list for height column: {path_list_col_ii}")

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
            sat_paths = paths_after_select_bdy(height_paths, bdy, room_w, room_h, plot_width, plot_height)
            for pth in sat_paths:
                sorted_bdys.append(pth)
        if width_paths:
            sat_paths =  paths_after_select_bdy(width_paths, bdy, room_w, room_h, plot_width, plot_height)
            for pth in sat_paths:
                sorted_bdys.append(pth)
        else:
            print("No combination of walls found such that the path satisfies the 20 percent criteria")

    final_sorted_bdys = []
    seen = set()
    
    for sublist in sorted_bdys:
        frozen_sublist = tuple(map(tuple, sublist))
        if frozen_sublist not in seen:
            seen.add(frozen_sublist)
            final_sorted_bdys.append(sublist)

    return final_sorted_bdys





