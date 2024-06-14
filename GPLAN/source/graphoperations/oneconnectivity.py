"""One-connected Module

This module allows the user to 

This module contains the following functions:
    * 
"""
import numpy as np
import copy
import networkx as nx

def get_biconnected_components(nxgraph):
    """Returns list of biconnected components in the graph.
    Args:
        nxgraph: an instance of NetworkX graph object.
    Returns:
        components: Set of biconnected components.
    """
    components = list(nx.biconnected_components(nxgraph))
    return components

def get_adj_matrix(matrix, component):
    """
    Args:
        
    Returns:
        
    """
    l = np.array(list(component))
    a = matrix[l][:,l]
    return a

def get_dict(component):
    """
    Args:
        
    Returns:
        
    """
    dict = {}
    cmpnt_lst = list(component)
    for i in range(0,len(cmpnt_lst)):
        dict[cmpnt_lst[i]] = i
    return dict

def recurse(list, i, final, individual):
    """
    Args:
        
    Returns:
        
    """
    if i == len(list):
        final.append(individual)
        return
    temp = list[i]
    for j in range(0, len(temp)):
        temp_individual = copy.deepcopy(individual)
        temp_individual.append(temp[j])
        recurse(list, i + 1, final, temp_individual)

def merge(em_list):
    """
    Args:
        
    Returns:
        
    """

    rows_ems = [] #variable stores the no. of rows in each encoded matrix after changing its orientation
    aligned_ems = [] #stores encoded matrix in changed orientation
    merge_ems = [] #stores encoded matrix which are ready to be merged
    crnrs = []

    ems = em_list

    for i in range(len(ems)):
        row = len(ems[i])
        col = len(ems[i][0])
        if row == 1:
            ems[i] = np.append(ems[i], [ems[i][-1]], axis=0)
            row=row+1
        if col == 1:
            ems[i] = np.append(ems[i], [ems[i][:,-1]], axis=0)
            col=col+1
        tl  = ems[i][0][0]
        tr = ems[i][0][col-1]
        bl = ems[i][row-1][0]
        br = ems[i][row-1][col-1]

        crnrs.append([tl, tr, br, bl])

    em = ems.pop(0)
    crnr = crnrs.pop(0)
    if crnr[2] == crnr[3]:  # last row
        em = np.rot90(em, 1)
    elif crnr[3] == crnr[0]:  # First col
        em = np.rot90(em, 2)
    elif crnr[0] == crnr[1]:  # first row
        em = np.rot90(em, 3)
    val_right = em[0][-1]
    if(em[0][0] == em[-1][0]):
        val_left = em[0][0]
    else:
        val_left = -1
    aligned_ems.append(em)

    while ems!=[]:
        l = len(ems)
        i=0
        while i< l:
            if val_right in crnrs[i]:
                em = ems.pop(i)
                crnr = crnrs.pop(i)
                l = len(ems)
                i= 0
                if crnr[0] == crnr[1] == val_right:  # first row
                    em = np.rot90(em, 1)
                if crnr[1] == crnr[2] == val_right:  # last col
                    em = np.rot90(em, 2)
                if crnr[2] == crnr[3] == val_right:  # last row
                    em = np.rot90(em, 3)
                val_right = em[0][-1]
                aligned_ems.append(em)
            elif val_left in crnrs[i]:
                em = ems.pop(i)
                crnr = crnrs.pop(i)
                l = len(ems)
                i = 0
                if crnr[2] == crnr[3] == val_left:  # last row
                    em = np.rot90(em, 1)
                if crnr[3] == crnr[0] == val_left:  # First col
                    em = np.rot90(em, 2)
                if crnr[0] == crnr[1] == val_left:  # first row
                    em = np.rot90(em, 3)
                val_left = em[0][0]
                aligned_ems.insert(0,em)
            else:
                i = i+1

    for matrix in aligned_ems:
        rows_ems.append(len(matrix))

    max_rows = max(rows_ems)

    #loop adds extra rows in encoded matrix to make all the EMs of the same height
    for i in range(len(rows_ems)):
        em = aligned_ems[i]
        j = rows_ems[i]
        while j < max_rows:
            em = np.append(em, [em[-1]], axis=0)
            j = j+1
        merge_ems.append(em)

    #finalEncodedMatrix stores the merged EM
    final_em = merge_ems[0]

    #loop merges all the encoded matrices
    for i in range(1, len(merge_ems)):
        em = merge_ems[i]
        final_em = np.concatenate((final_em, em[:,1:]), axis=1)

    return final_em

def convert_to_rel(em,nodecnt):
    """
    Args:
        
    Returns:
        
    """
    rows = len(em)
    cols = len(em[0])
    row_start = nodecnt * np.ones(cols)
    row_end = (nodecnt + 2) * np.ones(cols)
    col_start = (nodecnt + 3) * np.ones(rows + 2)
    col_end = (nodecnt + 1) * np.ones(rows + 2)
    em = np.insert(em, 0, row_start, 0)
    em = np.insert(em, rows + 1, row_end, 0)
    em = np.insert(em, 0, col_start, 1)
    em = np.insert(em, cols + 1, col_end, 1)

    mat = np.zeros((nodecnt + 4, nodecnt + 4))

    for i in range(rows + 1, 0, -1):
        for j in range(1, cols + 1):
            if (em[i][j] != em[i - 1][j]):
                mat[em[i][j]][em[i - 1][j]] = 2

    for i in range(1, rows + 1):
        for j in range(0, cols + 1):
            if (em[i][j] != em[i][j + 1]):
                mat[em[i][j]][em[i][j + 1]] = 3

    mat[nodecnt][nodecnt + 1] = 1
    mat[nodecnt][nodecnt + 3] = 1
    mat[nodecnt + 1][nodecnt + 2] = 1
    mat[nodecnt + 1][nodecnt] = 1
    mat[nodecnt + 2][nodecnt + 1] = 1
    mat[nodecnt + 2][nodecnt + 3] = 1
    mat[nodecnt + 3][nodecnt] = 1
    mat[nodecnt + 3][nodecnt + 2] = 1

    return mat