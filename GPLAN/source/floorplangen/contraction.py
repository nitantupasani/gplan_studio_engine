"""Contraction Module

This module allows user to perform contraction on a Proper Triangulated
Planar Graph (PTPG) to transform it into a trivial Regular Edge
Labelling (REL).

This module contains the following functions:

    * degrees - returns degree of each node in the graph.
    * goodnodes - returns good vertices in the graph.
    * is_goodvertex - finds if a vertex is a good vertex.
    * cntr_nbr - finds contractible neighbour of given vertex.
    * update_adjmat - updates adjacency matrix post contraction.
    * update_degrees - updates degree post contraction.
    * check - checks if a vertex is good vertex post contraction.
    * contract - performs contraction on the graph.

"""

import numpy as np 

def degrees(matrix):
    """Returns degree of each node of the graph.

    Args:
        matrix: A matrix representing the adjacency matrix of the graph.

    Returns:
        A list containing degree of each node.
    """
    return [np.count_nonzero(matrix[node])
     for node in range(matrix.shape[0])]

def goodnodes(matrix, degrees):
    """Returns good vertices of the graph.

    Args:
        matrix: A matrix representing the adjacency matrix of the graph.
        degrees: A list representing the degree of each node.

    Returns:
        goodnodes: A list containing good vertices of the graph.
    """
    goodnodes = []
    #Considering interior vertex only
    for node in range(matrix.shape[0] - 4): 
        if is_goodvertex(matrix, degrees, node):
            goodnodes.append(node)
    return goodnodes

def is_goodvertex(matrix, degrees, node):
    """Checks if the given vertex is a good vertex.

    Args:
        matrix: A matrix representing the adjacency matrix of the graph.
        degrees: A list containing degree of each node.
        node: An integer representing the vertex to be checked.

    Returns:
        boolean: A boolean indicating if given vertex is a good vertex.
    """
    if node < matrix.shape[0] - 4:
        if degrees[node] == 5:
            heavy_nbrcnt = 0
            nbrs, = np.where(matrix[node] == 1)
            for nbr in nbrs:  
                if degrees[nbr] >= 20:
                    heavy_nbrcnt += 1
            if heavy_nbrcnt <= 1:
                return True
        elif degrees[node] == 4:
            heavynbr = []
            nbrs, = np.where(matrix[node] == 1)
            for nbr in nbrs: 
                if degrees[nbr] >= 20:
                    heavynbr.append(nbr)
            if (len(heavynbr) <= 1) \
            or (len(heavynbr) == 2 
                and matrix[heavynbr[0]][heavynbr[1]] != 1):
                return True
    return False

def cntr_nbr(matrix, node):
    """Finds contractible neghbour of a given vertex.

    Args:
        matrix: A matrix representing the adjacency matrix of the graph.
        node: An integer representing vertex.

    Returns:
        nbr: An integer representing contractible neighbour of vertex.
        mut_nbrs: A list containiing mutual neighbours of node and nbr.
    """
    nbrs, = np.where(matrix[node] == 1)
    for nbr in nbrs:
        if nbr > matrix.shape[0]-5:
            continue
        contractible = True
        node_nbrs, = np.where(matrix[nbr] == 1)
        mut_nbrs = np.intersect1d(nbrs
            , node_nbrs
            , assume_unique=True)
        if len(mut_nbrs) != 2:
            print("Input graph might contain a complex triangle.")
        for vertex in nbrs:
            if vertex in mut_nbrs or vertex == nbr:
                continue
            vertex_nbr, = np.where(matrix[vertex] == 1)
            intersection = np.intersect1d(vertex_nbr
                , node_nbrs
                , assume_unique=True)
            for vertex_int in intersection:
                if vertex_int not in mut_nbrs\
                 and vertex_int != node:
                    contractible = False
                    break
            if not contractible:
                break
        if contractible:
            return nbr, mut_nbrs
    return -1, []

def update_adjmat(matrix, node, nbr):
    """Updates adjacency matrix post contraction.

    Args:
        matrix: A matrix representing the adjacency matrix of the graph.
        node: An integer representing vertex.
        nbr: An integer representing contractible neighbour of node.

    Returns:
        None
    """
    node_nbrs, = np.where(matrix[node] == 1)
    for vertex in node_nbrs:
        matrix[node][vertex] = 0
        matrix[vertex][node] = 0
        if vertex != nbr:
            matrix[vertex][nbr] = 1
            matrix[nbr][vertex] = 1

def update_degrees(degrees, node, nbr, mut_nbrs):
    """Updates degrees of nodes post contraction.

    Args:
        degrees: A list containing degree of each node.
        node: An integer representing vertex.
        nbr: An integer representing contractible neighbour of node.
        mut_nbrs: A list containing mutual neighbours of node and nbr.

    Returns:
        None
    """
    degrees[nbr] += degrees[node] - 4
    degrees[mut_nbrs[0]] -= 1
    degrees[mut_nbrs[1]] -= 1
    degrees[node] = 0
    
def check(matrix, degrees, goodnodes, node):
    """Checks if given node is good vertex post contraction.

    Args:
        matrix: A matrix representing the adjacency matrix of the graph.
        degrees: A list representing the degrees of each node.
        goodnodes: A list containing good nodes.
        node: An integer representing vertex.

    Returns:
        None
    """
    if is_goodvertex(matrix,degrees,node)\
     and (node not in goodnodes):
        goodnodes.append(node)
    elif (not is_goodvertex(matrix,degrees,node))\
     and (node in goodnodes):
        goodnodes.remove(node)
    
def contract(matrix, goodnodes, degrees):
    """Performs contraction on the graph.

    Args:
        matrix: A matrix representing the adjacency matrix of the graph.
        degrees: A list representing the degrees of each node.
        goodnodes: A list containing good nodes.

    Returns:
        matrix: An updated matrix representing the adjacency matrix of the graph.
        degrees: An updated list representing the degrees of each node.
        goodnodes: An updated list containing good nodes.
        cntrs: A list containing contractions in their order of occurence.
    """
    cntrs = []
    attempts = len(goodnodes)
    while attempts > 0:
        node = goodnodes.pop(0)
        nbr, mut_nbrs = cntr_nbr(matrix,node)
        if(nbr == -1):
            goodnodes.append(node)
            attempts -= 1
            continue
        cntrs.append({'node': node
            , 'nbr': nbr
            , 'mut_nbrs': mut_nbrs
            , 'node_nbrs': np.where(matrix[node] == 1)[0]})
        update_adjmat(matrix, node,nbr)
        update_degrees(degrees, node, nbr, mut_nbrs)
        check(matrix, degrees, goodnodes, nbr)
        check(matrix, degrees, goodnodes, mut_nbrs[0])
        check(matrix, degrees, goodnodes, mut_nbrs[1])
        attempts = len(goodnodes)
    return matrix, degrees, goodnodes, cntrs





