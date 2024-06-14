"""
Dimensioning Module
This module allows user to obtain optimised dimensions for height and width of each room from their inputs. This module handles symmetry constraints,
aspect ratio constraints as well as plot size constraints.

This module contains the following functions stored in seperate files:
    * floorplan_to_st - Takes user inputs and converts them into encoded matrix form of horizontal and vertical st graphs. Calls solve_linear and
    					convert_adj_equ_sym.
	* convert_adj_equ_sym - Converts encoded st graphs into linear equations.
    * solve_linear - Takes few user inputs along with the encoded horizontal and vertical st graphs to give optimized dimensions .

"""
import numpy as np

def convert_adj_equ_sym(DGPH, room_list, plot_dimension):
    """
       Args:
           DGPH: Encoded matrix form of vertical/horizontal adjacencies including the north/west node
    	   room_list: List of symmetric room constraints i.e. list of rooms that form the widths and heights of the
    	              symmetric rooms
    	   plot_dimesnion: The total plot width/height
       Attributes:
    	   LINEQ: Matrix showing an edge, where 1 denotes the starting node and -1 denotes the ending node.
       Returns:
           f: The coefficients of the linear objective function to be minimized.
           A: The inequality constraint matrix. Each row of A specifies the coefficients of a linear
              inequality constraints on widths/heights.
           Aeq: The equality constraint matrix. Each row of Aeq specifies the coefficients of a
                equality constraint on widths/heights.
           Beq: The equality constraint vector. Each element of Aeq @ width/height must equal
                the corresponding element of Beq.
       """
    N = len(DGPH)
    lineq_temp = np.zeros([N, N ** 2])
    room_num = len(room_list)

    # starting Liner equalities as a matrix; 1 indicates starting vertex and -1 indicates the end vertex of an edge.
    for i in range(0, N):
        for j in range(0, N):
            if DGPH[i][j] == 1:
                lineq_temp[i][N * i + j] = 1
                lineq_temp[j][N * i + j] = -1

    # starting removing extra variables from matrix
    LINEQ = []
    count = 0
    LINEQ = np.array(LINEQ)
    for i in range(0, N):
        for j in range(0, N):
            if DGPH[i][j] == 1:
                LINEQ = np.append(LINEQ,lineq_temp[:, (N*i)+j])
                count = count+1

    LINEQ = np.reshape(LINEQ,(count,N))
    LINEQ = np.transpose(LINEQ)

    # Starting Objective function
    n = len(LINEQ[0])
    f = np.zeros([1, n])
    z = np.sum(DGPH[0], dtype=int)

    for i in range(0, z):
        f[0][i] = 1
        #need explanation, if we want to minimise inflow why dont we take all vertices adj to northor west

    # print(f)

    # Linear inequalities (Dimensional Constraints)
    def ismember(d, k):
        return [1 if (i == k) else 0 for i in d]

    A = []
    for i in range(0, N):
        A.append(ismember(LINEQ[i], -1))
    A = np.array(A)
    A_min = np.dot(A, -1)
    A_max = A
    A_min = np.delete(A_min, 0, 0)
    A_max = np.delete(A_max, 0, 0)
    A = np.vstack((A_min, A_max))

    #symm
    symm_eq_mat = np.zeros((int(room_num/2),n))

    for i in range(0,int(room_num/2)):
        temp1 = room_list[2 * i]
        temp1_sz = len(temp1)
        add_mat = np.zeros((int(room_num/ 2), n))
        for j in range(0, temp1_sz):
            add_mat[i] = add_mat[i] + A[temp1[j]]

        temp2 = room_list[2 *i + 1]
        temp2_sz = len(temp2)
        subt_mat = np.zeros((int(room_num/2),n))
        for k in range(0, temp2_sz):
            subt_mat[i] = subt_mat[i] + A[temp2[k]]

        symm_eq_mat[i] = add_mat[i] - subt_mat[i]

    def any(M):
        for i in M:
            if i == 1:
                return 1
        return 0
    #Linear Equality Constraints (Network flow)
    Aeq = []
    for i in range(0, N):
        if any(ismember(LINEQ[i], 1)) != 0 and any(ismember(LINEQ[i], -1)) != 0:
            Aeq.append(LINEQ[i])

    #symm
    for i in range(0,int(room_num / 2)):
       Aeq = np.vstack((Aeq,symm_eq_mat[i]));

    Aeq = np.array(Aeq)
    Beq = np.zeros([1, len(Aeq)])
    if(plot_dimension!=-1):
        plt_dim_equ = f
        Aeq = np.vstack((plt_dim_equ, Aeq))
        dim = np.zeros([1, 1])
        dim[0][0] = plot_dimension
        Beq = np.hstack((dim, Beq))

    return [f, A, Aeq, Beq]