"""Transformation Module

This module allows user to transform each additional
edge into a node.

This module contains the following functions:

    * transform - transforms given edge in graph into node.
    * find_nbr - finds neigbour of the given vertex.
"""
import numpy as np

def transform_edges(matrix, edge, faces, positions):
    """Transforms edge into vertex.

    Args:
        matrix: A matrix representing the adjacency matrix of the graph.
        edge: A list representing edge to be transformed.

    Returns:
        adjmatrix: A modified matrix after edge transformation.
        edgecnt: An integer representing the increase in edgecnt (2 or 3).
    """
    reversed_edge = (edge[1],edge[0])
    nbr_faces = [face for face in faces if edge in face or reversed_edge in face]
    adjmatrix = np.zeros([matrix.shape[0]+1, matrix.shape[0]+1], int)
    adjmatrix[0:matrix.shape[0], 0:matrix.shape[1]] = matrix
    for idx in range(len(nbr_faces)):
        common_node = find_common_node(nbr_faces[idx],edge)
        extra_node = matrix.shape[0]
        adjmatrix = update_matrix(adjmatrix,edge,common_node,extra_node)
        positions[extra_node] = ((positions[edge[0]][0] + positions[edge[1]][0])/2,
                                    (positions[edge[0]][1] + positions[edge[1]][1])/2)
        new_faces = find_new_faces(edge,common_node,extra_node)
        faces.append(new_faces[0])
        faces.append(new_faces[1])
        faces.remove(nbr_faces[idx])
    if(len(nbr_faces) == 1):
        return adjmatrix, faces, positions, 2 # 2 edges are added if it was external edge
    else:
        return adjmatrix, faces, positions, 3 # 3 edges are added if it was internal edge

def find_common_node(nbr_face,edge):
    other_node = 0
    for node in nbr_face:
        if node[0]!= edge[0] and node[0]!= edge[1]:
            other_node = node[0]
    return other_node

def update_matrix(adjmatrix,edge,common_node,extra_node):
    adjmatrix[edge[0]][edge[1]] = 0
    adjmatrix[edge[1]][edge[0]] = 0
    adjmatrix[extra_node][edge[0]] = 1
    adjmatrix[extra_node][edge[1]] = 1
    adjmatrix[edge[0]][extra_node] = 1
    adjmatrix[edge[1]][extra_node] = 1
    adjmatrix[common_node][extra_node] = 1
    adjmatrix[extra_node][common_node] = 1
    return adjmatrix

def find_new_faces(edge,common_node,extra_node):
    return [[(edge[0],common_node),(common_node,extra_node),(extra_node,edge[0])],
            [(edge[1],common_node),(common_node,extra_node),(extra_node,edge[1])]]

def find_nbr(matrix, vertex):
    """Finds neighbour of the given vertex.

    Args:
        matrix: A matrix representing the adjacency matrix of the graph.
        vertex: An integer whose neighbours are to be found.

    Returns:
        nbr: A set representing neighbours of vertex.
    """
    nbr = set()
    for i in range(0,matrix.shape[0]):
        if(matrix[vertex][i]==1):
            nbr.add(i)
    return nbr