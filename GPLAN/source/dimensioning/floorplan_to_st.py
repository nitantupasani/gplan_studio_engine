"""
Dimensioning Module
This module allows user to obtain optimised dimensions for height and width of each room from their inputs. This module handles symmetry constraints,
aspect ratio constraints as well as plot size constraints.

This module contains the following functions stored in seperate files:
    * floorplan_to_st - Takes user inputs and converts them into encoded matrix form of horizontal and vertical st graphs.
     					Calls solve_linear and convert_adj_equ_sym.
	* convert_adj_equ_sym - Converts encoded st graphs into linear equations.
    * solve_linear - Takes few user inputs along with the encoded horizontal and vertical st graphs to give optimized dimensions .

"""
import numpy as np
from .solve_linear import solve_linear
from .convert_adj_equ_sym import convert_adj_equ_sym


def floorplan_to_st(E, min_width, min_height, max_width, max_height, ver_list, hor_list, min_ar, max_ar, plot_width, plot_height):
    """
       Args:
               E: Encoded matrix
               min_width: List of minimum width constraints of each room
               min_height: List of minimum height constraints of each room
               max_width: List of maximum width constraints of each room
               max_height: List of maximum height constraints of each room
               symm_rooms: String of symmetric room constraints
               min_ar: List of minimum aspect ratio constraints of each room
               max_ar: List of maximum aspect ratio constraints of each room
       Attributes:
               ver_dgph: Encoded matrix form of vertical adjacencies of the internal nodes
               north_adj: Encoded matrix form of vertical adjacencies of the north node
               VER: Encoded matrix form of vertical adjacencies including the north node
               hor_dgph: Encoded matrix form of horizontal adjacencies of the internal nodes
               west_adj: Encoded matrix form of horizontal adjacencies of the west node
               HOR: Encoded matrix form of horizontal adjacencies including the west node
       Returns:
           width: List of optimised widths
           height: List of optimised heights
           hor_dgph: Encoded matrix form of horizontal adjacencies of the internal nodes
           status: boolean  representing success of optimization
       """
    rows = len(E)
    columns = len(E[0])
    E = np.array(E)
    # E=[[5,5,5,5,6],[3,3,4,4,4],[0,1,1,2,2]]
    # E = np.array(E)
    rows = len(E)
    columns = len(E[0])
    for i in range(0, rows):
        for j in range(0, columns):
            E[i][j] += 1

    len_dgph = np.amax(E)
    ver_dgph = np.zeros((len_dgph, len_dgph), int)
    north_adj = np.zeros((1, len_dgph), int)

    for i in range(0, columns):
        north_adj[0][E[0][i] - 1] = 1

    for i in range(0, columns):
        for j in range(0, rows):
            if j == 0:
                temp = E[j][i]
            if E[j][i] != temp:
                ver_dgph[temp - 1][E[j][i] - 1] = 1
                temp = E[j][i]

    VER = []

    for i in north_adj:
        VER.append(i)

    for i in ver_dgph:
        VER = np.append(VER, [i], axis=0)

    VER = np.insert(VER, 0, [0], axis=1)
    N = len(VER)

    hor_dgph = np.zeros([len_dgph, len_dgph])
    west_adj = np.zeros([1, len_dgph])

    for i in range(0, rows):
        west_adj[0][E[i][0] - 1] = 1

    for i in range(0, rows):
        for j in range(0, columns):
            if j == 0:
                temp = E[i][j]
            if E[i][j] != temp:
                hor_dgph[temp - 1][E[i][j] - 1] = 1
                temp = E[i][j]

    HOR = []

    for i in west_adj:
        HOR.append(i)

    for i in hor_dgph:
        HOR = np.append(HOR, [i], axis=0)

    HOR = np.insert(HOR, 0, [0], axis=1)

    [f_VER, A_VER, Aeq_VER, Beq_VER] = convert_adj_equ_sym(
        VER, ver_list, plot_width)
    [f_HOR, A_HOR, Aeq_HOR, Beq_HOR] = convert_adj_equ_sym(
        HOR, hor_list, plot_height)

    [width, height, status] = solve_linear(f_VER, A_VER, Aeq_VER, Beq_VER, f_HOR, A_HOR,
                                           Aeq_HOR, Beq_HOR, min_width, max_width, min_height, max_height, min_ar, max_ar)

    width = np.round(width, 3)
    height = np.round(height, 3)

    return [width, height, hor_dgph, status]
