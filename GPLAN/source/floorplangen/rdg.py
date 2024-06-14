"""Rectangular Dual Generation Module

This module allows user to generate rectangular dual for a
given PTPG.

This module contains the following functions:

    * get_rectangular_coordinates - populates rectangular
                                    coordinates
    * get_direction - populates rectangular coordinates for
                      irregular rooms
    * construct_dual - constructs rectangular dual for PTPG.
    * construct_floorplan - constructs dimensioned rfloorplan for PTPG.
    * get_dimensions - returns dimension of each room.
"""
import numpy as np
from . import dual as dual


def construct_dual(matrix, nodecnt, mergednodes, irreg_nodes):
    """Constructs dual for a PTPG.

    Args:
        matrix: A matrix representing the adjacency matrix of the graph.
        nodecnt: An integer representing the node count of the graph.
        mergednodes: A list representing nodes to be merged.
        irreg_nodes: A list representing nodes for irregular rooms.

    Returns:
        room_x: A list representing the x coordinate of the rooms.
        room_y: A list representing the y coordinate of the rooms.
        room_width: A list representing the width of the rooms.
        room_height: A list representing the height of the rooms.
        room_x_bottom_left: A list representing the x coordinate of the middle left of bottom edge of the room.
        room_x_bottom_right: A list representing the x coordinate of the middle right of bottom edge of the room.
        room_x_top_left: A list representing the x coordinate of the middle left of top edge of the room.
        room_x_top_right: A list representing the x coordinate of the middle right of top edge of the room.
        room_y_left_bottom: A list representing the y coordinate of the middle bottom of left edge of the room.
        room_y_right_bottom: A list representing the y coordinate of the middle bottom of right edge of the room.
        room_y_left_top: A list representing the y coordinate of the middle top of left edge of the room.
        room_y_right_top: A list representing the y coordinate of the middle top of right edge of the room.
    """
    t1_matrix = dual.populate_t1_matrix(matrix, nodecnt)
    # print("check 1")
    t2_matrix = dual.populate_t2_matrix(matrix, nodecnt)
    # print("check 2")
    room_x, room_y, room_width, room_height = get_dimensions(matrix, nodecnt, t1_matrix, t2_matrix)
    return [room_x
        , room_y
        , room_width
        , room_height]


def get_dimensions(matrix, nodecnt, t1_matrix, t2_matrix):
    """Returns dimension of each room.

    Args:
        matrix: A matrix representing the adjacency matrix of the graph.
        nodecnt: An integer representing the node count of the graph.
        t1_matrix: A matrix representing the T1 graph.
        t2_matrix: A matrix representing the T2 graph.

    Returns:
        room_x: A list representing the x coordinate of the rooms.
        room_y: A list representing the y coordinate of the rooms.
        room_width: A list representing the width of the rooms.
        room_height: A list representing the height of the rooms.
    """
    room_x = np.zeros(nodecnt - 4)
    room_y = np.zeros(nodecnt - 4)
    room_height = np.zeros(nodecnt - 4)
    room_width = np.zeros(nodecnt - 4)
    for node in range(matrix.shape[0]):
        if node >= nodecnt - 4:
            continue
        row, col = np.where(t1_matrix[1:-1] == node)
        if row.shape[0] == 0:  # remove this later
            continue
        counts = np.bincount(row)
        max_row = np.argmax(counts)
        indexes, = np.where(row == max_row)
        room_x[node] = col[indexes[0]]
        room_width[node] = col[indexes[-1]] - col[indexes[0]] + 1
        row, col = np.where(t2_matrix[:, 1:-1] == node)
        counts = np.bincount(col)
        max_col = np.argmax(counts)
        indexes, = np.where(col == max_col)
        room_y[node] = row[indexes[0]]
        room_height[node] = row[indexes[-1]] - row[indexes[0]] + 1
    return room_x, room_y, room_width, room_height
