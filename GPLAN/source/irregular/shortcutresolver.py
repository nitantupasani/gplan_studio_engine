"""Shortcut Resolver Module

This module allows user to identify shortcuts (refer Documentation) in
the graph and helps in removing shortcuts if required.

This module contains the following functions:

    * get_shortcut - returns shortcuts in the graph.
    * remove_shortcut - removes a shortcut from the graph.
"""
import numpy as np
import networkx as nx 

def get_shortcut(matrix, bdy_nodes, bdy_edges):
    """Returns shortcuts in the input graph.

    Args:
        matrix: A matrix representing the adjacency matrix of the graph.
        bdy_nodes: A list containing the boundary nodes of the graph.
        bdy_edges: A list containing the boundary edges of the graph.

    Returns:
        shortcuts: A list containing shortcuts of the input graph.
    """
    shortcuts = []
    for node1 in range(0, len(bdy_nodes)):
        for node2 in range(0, len(bdy_nodes)):
            if(matrix[bdy_nodes[node1]][bdy_nodes[node2]] == 1 
                and (bdy_nodes[node1], bdy_nodes[node2]) not in bdy_edges 
                and [bdy_nodes[node2], bdy_nodes[node1]] not in shortcuts):
                shortcuts.append([bdy_nodes[node1], bdy_nodes[node2]])
    return shortcuts

def remove_shortcut(shortcut, trngls, matrix):
    """Removes particular shortcut from the input graph.

    Args:
        shortcut: A list containing vertices of shortcut to be removed.
        trngls: A list containing the triangular cycles in a graph.
        matrix: A matrix representing the adjacency matrix of the graph.

    Returns:
        adjmatrix: A matrix representing the modified adjacency matrix.
    """
    nbr_nodes = []
    for trngl in trngls:
        if(shortcut[0] in trngl and shortcut[1] in trngl):
            for node in trngl:
                if(node not in shortcut and node not in nbr_nodes):
                    nbr_nodes.append(node)
    adjmatrix = np.zeros([matrix.shape[0]+1, matrix.shape[0]+1], int)
    adjmatrix[0:matrix.shape[0], 0:matrix.shape[0]] = matrix
    
    adjmatrix[shortcut[0]][shortcut[1]] = 0
    adjmatrix[shortcut[1]][shortcut[0]] = 0
    adjmatrix[matrix.shape[0]][shortcut[0]] = 1
    adjmatrix[matrix.shape[0]][shortcut[1]] = 1
    adjmatrix[matrix.shape[0]][nbr_nodes[0]] = 1
    adjmatrix[matrix.shape[0]][nbr_nodes[1]] = 1
    adjmatrix[shortcut[0]][matrix.shape[0]] = 1
    adjmatrix[shortcut[1]][matrix.shape[0]] = 1
    adjmatrix[nbr_nodes[0]][matrix.shape[0]] = 1
    adjmatrix[nbr_nodes[1]][matrix.shape[0]] = 1
    return adjmatrix
    