"""Expansion Module

This module allows user to perform expansion on a trivial 
Regular Edge Labelling (REL) to transform it into a
complete Regular Edge Labelling (REL).

This module contains the following functions:

    * basecase - obtains the base case of the expansion step.
    * expand - performs the expansion step.
    * get_case - returns the case of expansion.
    * handle_orig_nbrs - handles the original neighbours.
    * case_a - handles case A of expansion.
    * case_b - handles case B of expansion.
    * case_c - handles case C of expansion.
    * case_d - handles case D of expansion.
    * case_e - handles case E of expansion.
    * case_f - handles case F of expansion.
    * case_g - handles case G of expansion.
    * case_h - handles case H of expansion.
    * case_i - handles case I of expansion.
    * case_j - handles case J of expansion.

"""

from ..graphoperations import operations as opr


def basecase(matrix, nodecnt):
    """Resolves the base case of expansion step.

    Args:
        matrix: A matrix representing the adjacency matrix of the graph.
        nodecnt: An integer representing the node count of the graph.

    Returns:
        matrix: An updated matrix representing the adjacency matrix of the graph.
    """
    for node in range(matrix.shape[0]):
        if matrix[nodecnt - 4][node] == 1\
                and node not in [nodecnt - 3, nodecnt - 1]:
            matrix[node][nodecnt - 4] = 2
            matrix[nodecnt - 4][node] = 0
            matrix[nodecnt - 2][node] = 2
            matrix[node][nodecnt - 2] = 0
            matrix[node][nodecnt - 3] = 3
            matrix[nodecnt - 3][node] = 0
            matrix[nodecnt - 1][node] = 3
            matrix[node][nodecnt - 1] = 0
    return matrix


def expand(matrix, nodecnt, cntrs):
    """Expands a given contraction.

    Args:
        matrix: A matrix representing the adjacency matrix of the graph.
        nodecnt: An integer representing nodecount of the graph.
        cntrs: A list representing the contractions.

    Returns:
        matrix: An updated adjacency matrix.
    """
    cntr = cntrs.pop()
    case = get_case(matrix, nodecnt, cntr)
    nbr = cntr['nbr']
    node = cntr['node']
    matrix = case(matrix, nodecnt, nbr, node,
                  cntr['mut_nbrs'][0], cntr['mut_nbrs'][1], cntr['node_nbrs'])
    return matrix


def get_case(matrix, nodecnt, cntr):
    """Identifies the case of expansion (Refer documentation).

    Args:
        matrix: A matrix representing the adjacency matrix of the graph.
        nodecnt: An integer representing node count of the graph.
        cntr: A dictionary representing the contraction.

    Returns:
        case: A function representing the case of the contraction.
    """
    nbr = cntr['nbr']
    mut_nbrs = cntr['mut_nbrs']
    mut_nbr1 = mut_nbrs[0]
    mut_nbr2 = mut_nbrs[1]
    if matrix[nbr][mut_nbr1] == 2:
        if matrix[nbr][mut_nbr2] == 3:
            return case_a
        elif matrix[nbr][mut_nbr2] == 2:
            vertex = mut_nbr1
            while(vertex != mut_nbr2):
                label, vertex = opr.ordered_nbr_label(
                    matrix, nodecnt, nbr, vertex, cw=False)
                if(label == 3):
                    mut_nbrs[0], mut_nbrs[1] = mut_nbrs[1], mut_nbrs[0]
                    break
            return case_b
        elif matrix[mut_nbr2][nbr] == 3:
            return case_d
        elif matrix[mut_nbr2][nbr] == 2:
            return case_f
        else:
            print("ERROR")

    if matrix[mut_nbr1][nbr] == 2:
        if matrix[nbr][mut_nbr2] == 3:
            mut_nbrs[0], mut_nbrs[1] = mut_nbrs[1], mut_nbrs[0]
            return case_e
        elif matrix[nbr][mut_nbr2] == 2:
            mut_nbrs[0], mut_nbrs[1] = mut_nbrs[1], mut_nbrs[0]
            return case_f
        elif matrix[mut_nbr2][nbr] == 3:
            return case_h
        elif matrix[mut_nbr2][nbr] == 2:
            vertex = mut_nbr1
            while(vertex != mut_nbr2):
                label, vertex = opr.ordered_nbr_label(
                    matrix, nodecnt, nbr, vertex, cw=False)
                if(label == 3):
                    mut_nbrs[0], mut_nbrs[1] = mut_nbrs[1], mut_nbrs[0]
                    break
            return case_i
        else:
            print("ERROR")

    if matrix[nbr][mut_nbr1] == 3:
        if matrix[nbr][mut_nbr2] == 3:
            vertex = mut_nbr1
            while(vertex != mut_nbr2):
                label, vertex = opr.ordered_nbr_label(
                    matrix, nodecnt, nbr, vertex, cw=False)
                if(label == 2):
                    mut_nbrs[0], mut_nbrs[1] = mut_nbrs[1], mut_nbrs[0]
                    break
            return case_c
        elif matrix[nbr][mut_nbr2] == 2:
            mut_nbrs[0], mut_nbrs[1] = mut_nbrs[1], mut_nbrs[0]
            return case_a
        elif matrix[mut_nbr2][nbr] == 3:
            return case_g
        elif matrix[mut_nbr2][nbr] == 2:
            return case_e
        else:
            print("ERROR")

    if matrix[mut_nbr1][nbr] == 3:
        if matrix[nbr][mut_nbr2] == 3:
            mut_nbrs[0], mut_nbrs[1] = mut_nbrs[1], mut_nbrs[0]
            return case_g
        elif matrix[nbr][mut_nbr2] == 2:
            mut_nbrs[0], mut_nbrs[1] = mut_nbrs[1], mut_nbrs[0]
            return case_d
        elif matrix[mut_nbr2][nbr] == 3:
            vertex = mut_nbr1
            while(vertex != mut_nbr2):
                label, vertex = opr.ordered_nbr_label(
                    matrix, nodecnt, nbr, vertex, cw=False)
                if(label == 2):
                    mut_nbrs[0], mut_nbrs[1] = mut_nbrs[1], mut_nbrs[0]
                    break
            return case_j
        elif matrix[mut_nbr2][nbr] == 2:
            mut_nbrs[0], mut_nbrs[1] = mut_nbrs[1], mut_nbrs[0]
            return case_h
        else:
            print("ERROR")


def handle_orig_nbrs(matrix, nbr, node, mut_nbr1, mut_nbr2, node_nbrs):
    """Handles original neighbours in contraction.

    Args:
        matrix: A matrix representing the adjacency matrix of the graph.
        nbr: An integer representing neighbour in contraction.
        node: An integer representing node in contraction.
        mut_nbr1: An integer representing mut_nbr1 in contraction.
        mut_nbr2: An integer representing mut_nbr2 in contraction.
        node_nbrs: A list representing node_nbrs in contraction.

    Returns:
        matrix: An updated matrix representing the adjacency matrix of the graph.
    """
    for alpha in node_nbrs:
        if alpha != mut_nbr1 and alpha != mut_nbr2 and alpha != nbr:
            if matrix[nbr][alpha] != 0:
                matrix[node][alpha] = matrix[nbr][alpha]
                matrix[nbr][alpha] = 0
            if matrix[alpha][nbr] != 0:
                matrix[alpha][node] = matrix[alpha][nbr]
                matrix[alpha][nbr] = 0
    return matrix


def case_a(matrix, nodecnt, nbr, node, mut_nbr1, mut_nbr2, node_nbrs):
    """Resolves Case A of expansion.

    Args:
        matrix: A matrix representing the adjacency matrix of the graph.
        nodecnt: An integer representing node count of the graph.
        nbr: An integer representing neighbour in contraction.
        node: An integer representing node in contraction.
        mut_nbr1: An integer representing mut_nbr1 in contraction.
        mut_nbr2: An integer representing mut_nbr2 in contraction.
        node_nbrs: A list representing node_nbrs in contraction

    Returns:
        matrix: An updated matrix representing the adjacency matrix of the graph.
    """
    ordered_nbr_label, ordered_nbr = opr.ordered_nbr_label(
        matrix, nodecnt, nbr, mut_nbr1, cw=True)
    if ordered_nbr_label == 2:
        if ordered_nbr in node_nbrs:
            matrix = handle_orig_nbrs(
                matrix, nbr, node, mut_nbr1, mut_nbr2, node_nbrs)
            matrix[mut_nbr1][node] = 3
            matrix[node][mut_nbr2] = 3
            matrix[nbr][node] = 2
        else:
            matrix = handle_orig_nbrs(
                matrix, nbr, node, mut_nbr1, mut_nbr2, node_nbrs)
            matrix[node][mut_nbr1] = 2
            matrix[node][mut_nbr2] = 3
            matrix[node][nbr] = 2
            matrix[nbr][mut_nbr1] = 0
            matrix[mut_nbr1][nbr] = 3
    else:
        if ordered_nbr in node_nbrs:
            matrix = handle_orig_nbrs(
                matrix, nbr, node, mut_nbr1, mut_nbr2, node_nbrs)
            matrix[node][mut_nbr1] = 2
            matrix[mut_nbr2][node] = 2
            matrix[nbr][node] = 3
        else:
            matrix = handle_orig_nbrs(
                matrix, nbr, node, mut_nbr1, mut_nbr2, node_nbrs)
            matrix[nbr][mut_nbr2] = 0
            matrix[mut_nbr2][nbr] = 2
            matrix[node][nbr] = 3
            matrix[node][mut_nbr1] = 2
            matrix[node][mut_nbr2] = 3
    return matrix


def case_b(matrix, nodecnt, nbr, node, mut_nbr1, mut_nbr2, node_nbrs):
    """Resolves Case B of expansion.

    Args:
        matrix: A matrix representing the adjacency matrix of the graph.
        nodecnt: An integer representing node count of the graph.
        nbr: An integer representing neighbour in contraction.
        node: An integer representing node in contraction.
        mut_nbr1: An integer representing mut_nbr1 in contraction.
        mut_nbr2: An integer representing mut_nbr2 in contraction.
        node_nbrs: A list representing node_nbrs in contraction

    Returns:
        matrix: An updated matrix representing the adjacency matrix of the graph.
    """
    matrix = handle_orig_nbrs(matrix, nbr, node, mut_nbr1, mut_nbr2, node_nbrs)
    matrix[mut_nbr2][node] = 3
    matrix[node][mut_nbr1] = 3
    matrix[nbr][node] = 2
    return matrix


def case_c(matrix, nodecnt, nbr, node, mut_nbr1, mut_nbr2, node_nbrs):
    """Resolves Case C of expansion.

    Args:
        matrix: A matrix representing the adjacency matrix of the graph.
        nodecnt: An integer representing node count of the graph.
        nbr: An integer representing neighbour in contraction.
        node: An integer representing node in contraction.
        mut_nbr1: An integer representing mut_nbr1 in contraction.
        mut_nbr2: An integer representing mut_nbr2 in contraction.
        node_nbrs: A list representing node_nbrs in contraction

    Returns:
        matrix: An updated matrix representing the adjacency matrix of the graph.
    """
    matrix = handle_orig_nbrs(matrix, nbr, node, mut_nbr1, mut_nbr2, node_nbrs)
    matrix[mut_nbr1][node] = 2
    matrix[node][mut_nbr2] = 2
    matrix[nbr][node] = 3
    return matrix


def case_d(matrix, nodecnt, nbr, node, mut_nbr1, mut_nbr2, node_nbrs):
    """Resolves Case D of expansion.

    Args:
        matrix: A matrix representing the adjacency matrix of the graph.
        nodecnt: An integer representing node count of the graph.
        nbr: An integer representing neighbour in contraction.
        node: An integer representing node in contraction.
        mut_nbr1: An integer representing mut_nbr1 in contraction.
        mut_nbr2: An integer representing mut_nbr2 in contraction.
        node_nbrs: A list representing node_nbrs in contraction

    Returns:
        matrix: An updated matrix representing the adjacency matrix of the graph.
    """
    ordered_nbr_label, ordered_nbr = opr.ordered_nbr_label(
        matrix, nodecnt, nbr, mut_nbr1, False)
    if ordered_nbr_label == 2:
        if ordered_nbr in node_nbrs:
            matrix = handle_orig_nbrs(
                matrix, nbr, node, mut_nbr1, mut_nbr2, node_nbrs)
            matrix[node][mut_nbr1] = 3
            matrix[mut_nbr2][node] = 3
            matrix[nbr][node] = 2
        else:
            matrix = handle_orig_nbrs(
                matrix, nbr, node, mut_nbr1, mut_nbr2, node_nbrs)
            matrix[nbr][mut_nbr1] = 3
            matrix[node][mut_nbr1] = 2
            matrix[mut_nbr2][node] = 3
            matrix[node][nbr] = 2
    else:
        if ordered_nbr in node_nbrs:
            matrix = handle_orig_nbrs(
                matrix, nbr, node, mut_nbr1, mut_nbr2, node_nbrs)
            matrix[node][mut_nbr1] = 2
            matrix[mut_nbr2][node] = 2
            matrix[node][nbr] = 3
        else:
            matrix = handle_orig_nbrs(
                matrix, nbr, node, mut_nbr1, mut_nbr2, node_nbrs)
            matrix[mut_nbr2][nbr] = 2
            matrix[mut_nbr2][node] = 3
            matrix[node][mut_nbr1] = 2
            matrix[nbr][node] = 3
    return matrix


def case_e(matrix, nodecnt, nbr, node, mut_nbr1, mut_nbr2, node_nbrs):
    """Resolves Case E of expansion.

    Args:
        matrix: A matrix representing the adjacency matrix of the graph.
        nodecnt: An integer representing node count of the graph.
        nbr: An integer representing neighbour in contraction.
        node: An integer representing node in contraction.
        mut_nbr1: An integer representing mut_nbr1 in contraction.
        mut_nbr2: An integer representing mut_nbr2 in contraction.
        node_nbrs: A list representing node_nbrs in contraction

    Returns:
        matrix: An updated matrix representing the adjacency matrix of the graph.
    """
    ordered_nbr_label, ordered_nbr = opr.ordered_nbr_label(
        matrix, nodecnt, nbr, mut_nbr1, cw=True)
    if ordered_nbr_label == 2:
        if ordered_nbr in node_nbrs:
            matrix = handle_orig_nbrs(
                matrix, nbr, node, mut_nbr1, mut_nbr2, node_nbrs)
            matrix[node][mut_nbr1] = 3
            matrix[mut_nbr2][node] = 3
            matrix[node][nbr] = 2
        else:
            matrix = handle_orig_nbrs(
                matrix, nbr, node, mut_nbr1, mut_nbr2, node_nbrs)
            matrix[mut_nbr2][nbr] = 3
            matrix[mut_nbr2][node] = 2
            matrix[node][mut_nbr1] = 3
            matrix[nbr][node] = 2
    else:
        if ordered_nbr in node_nbrs:
            matrix = handle_orig_nbrs(
                matrix, nbr, node, mut_nbr1, mut_nbr2, node_nbrs)
            matrix[node][mut_nbr1] = 2
            matrix[mut_nbr2][node] = 2
            matrix[nbr][node] = 3
        else:
            matrix = handle_orig_nbrs(
                matrix, nbr, node, mut_nbr1, mut_nbr2, node_nbrs)
            matrix[nbr][mut_nbr1] = 2
            matrix[node][nbr] = 3
            matrix[node][mut_nbr1] = 3
            matrix[mut_nbr2][node] = 2
    return matrix


def case_f(matrix, nodecnt, nbr, node, mut_nbr1, mut_nbr2, node_nbrs):
    """Resolves Case F of expansion.

    Args:
        matrix: A matrix representing the adjacency matrix of the graph.
        nodecnt: An integer representing node count of the graph.
        nbr: An integer representing neighbour in contraction.
        node: An integer representing node in contraction.
        mut_nbr1: An integer representing mut_nbr1 in contraction.
        mut_nbr2: An integer representing mut_nbr2 in contraction.
        node_nbrs: A list representing node_nbrs in contraction

    Returns:
        matrix: An updated matrix representing the adjacency matrix of the graph.
    """
    ordered_nbr = opr.ordered_nbr(matrix, nodecnt, nbr, mut_nbr1, cw=True)
    if ordered_nbr in node_nbrs:
        matrix = handle_orig_nbrs(
            matrix, nbr, node, mut_nbr1, mut_nbr2, node_nbrs)
        matrix[node][mut_nbr1] = 2
        matrix[mut_nbr2][node] = 2
        matrix[nbr][node] = 3
    else:
        matrix = handle_orig_nbrs(
            matrix, nbr, node, mut_nbr1, mut_nbr2, node_nbrs)
        matrix[node][mut_nbr1] = 2
        matrix[mut_nbr2][node] = 2
        matrix[node][nbr] = 3
    return matrix


def case_g(matrix, nodecnt, nbr, node, mut_nbr1, mut_nbr2, node_nbrs):
    """Resolves Case G of expansion.

    Args:
        matrix: A matrix representing the adjacency matrix of the graph.
        nodecnt: An integer representing node count of the graph.
        nbr: An integer representing neighbour in contraction.
        node: An integer representing node in contraction.
        mut_nbr1: An integer representing mut_nbr1 in contraction.
        mut_nbr2: An integer representing mut_nbr2 in contraction.
        node_nbrs: A list representing node_nbrs in contraction

    Returns:
        matrix: An updated matrix representing the adjacency matrix of the graph.
    """
    ordered_nbr = opr.ordered_nbr_label(
        matrix, nodecnt, nbr, mut_nbr1, cw=True)[1]
    if ordered_nbr in node_nbrs:
        matrix = handle_orig_nbrs(
            matrix, nbr, node, mut_nbr1, mut_nbr2, node_nbrs)
        matrix[node][mut_nbr1] = 3
        matrix[mut_nbr2][node] = 3
        matrix[node][nbr] = 2
    else:
        matrix = handle_orig_nbrs(
            matrix, nbr, node, mut_nbr1, mut_nbr2, node_nbrs)
        matrix[node][mut_nbr1] = 3
        matrix[mut_nbr2][node] = 3
        matrix[nbr][node] = 2
    return matrix


def case_h(matrix, nodecnt, nbr, node, mut_nbr1, mut_nbr2, node_nbrs):
    """Resolves Case H of expansion.

    Args:
        matrix: A matrix representing the adjacency matrix of the graph.
        nodecnt: An integer representing node count of the graph.
        nbr: An integer representing neighbour in contraction.
        node: An integer representing node in contraction.
        mut_nbr1: An integer representing mut_nbr1 in contraction.
        mut_nbr2: An integer representing mut_nbr2 in contraction.
        node_nbrs: A list representing node_nbrs in contraction

    Returns:
        matrix: An updated matrix representing the adjacency matrix of the graph.
    """
    ordered_nbr_label, ordered_nbr = opr.ordered_nbr_label(
        matrix, nodecnt, nbr, mut_nbr1, cw=True)
    if ordered_nbr_label == 2:
        if ordered_nbr in node_nbrs:
            matrix = handle_orig_nbrs(
                matrix, nbr, node, mut_nbr1, mut_nbr2, node_nbrs)
            matrix[node][mut_nbr1] = 3
            matrix[mut_nbr2][node] = 3
            matrix[node][nbr] = 2
        else:
            matrix = handle_orig_nbrs(
                matrix, nbr, node, mut_nbr1, mut_nbr2, node_nbrs)
            matrix[mut_nbr1][nbr] = 0
            matrix[nbr][mut_nbr1] = 3
            matrix[mut_nbr1][node] = 2
            matrix[mut_nbr2][node] = 3
            matrix[nbr][node] = 2
    else:
        if ordered_nbr in node_nbrs:
            matrix = handle_orig_nbrs(
                matrix, nbr, node, mut_nbr1, mut_nbr2, node_nbrs)
            matrix[mut_nbr1][node] = 2
            matrix[node][mut_nbr2] = 2
            matrix[node][nbr] = 3
        else:
            matrix = handle_orig_nbrs(
                matrix, nbr, node, mut_nbr1, mut_nbr2, node_nbrs)
            matrix[mut_nbr2][nbr] = 0
            matrix[nbr][mut_nbr2] = 2
            matrix[mut_nbr1][node] = 2
            matrix[mut_nbr2][node] = 3
            matrix[nbr][node] = 3
    return matrix


def case_i(matrix, nodecnt, nbr, node, mut_nbr1, mut_nbr2, node_nbrs):
    """Resolves Case I of expansion.

    Args:
        matrix: A matrix representing the adjacency matrix of the graph.
        nodecnt: An integer representing node count of the graph.
        nbr: An integer representing neighbour in contraction.
        node: An integer representing node in contraction.
        mut_nbr1: An integer representing mut_nbr1 in contraction.
        mut_nbr2: An integer representing mut_nbr2 in contraction.
        node_nbrs: A list representing node_nbrs in contraction

    Returns:
        matrix: An updated matrix representing the adjacency matrix of the graph.
    """
    matrix = handle_orig_nbrs(matrix, nbr, node, mut_nbr1, mut_nbr2, node_nbrs)
    matrix[mut_nbr1][node] = 3
    matrix[node][mut_nbr2] = 3
    matrix[node][nbr] = 2
    return matrix


def case_j(matrix, nodecnt, nbr, node, mut_nbr1, mut_nbr2, node_nbrs):
    """Resolves Case J of expansion.

    Args:
        matrix: A matrix representing the adjacency matrix of the graph.
        nodecnt: An integer representing node count of the graph.
        nbr: An integer representing neighbour in contraction.
        node: An integer representing node in contraction.
        mut_nbr1: An integer representing mut_nbr1 in contraction.
        mut_nbr2: An integer representing mut_nbr2 in contraction.
        node_nbrs: A list representing node_nbrs in contraction

    Returns:
        matrix: An updated matrix representing the adjacency matrix of the graph.
    """
    matrix = handle_orig_nbrs(matrix, nbr, node, mut_nbr1, mut_nbr2, node_nbrs)
    matrix[node][mut_nbr1] = 2
    matrix[mut_nbr2][node] = 2
    matrix[node][nbr] = 3
    return matrix
