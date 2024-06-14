"""Biconnectivity Augmentation Module

This module allows the user to check if the graph is biconnected and can
make it biconnected.

This module contains the following functions:
    * is_biconnected - returns a boolean representing whether the graph is biconnected or not.
    * get_cutvertices - returns a list of cut vertices(a.k.a articulation points) present in the graph.
    * get_biconnected_components - Returns a generator of sets of vertices, one set for each biconnected component present in the graph. 
        (Advised to be converted to list for any other operations)
    * same_component - returns a boolean representing whether the given 2 nodes are in the same biconnected component or not.
    * biconnect - returns the edges to be added to make graph biconnected.
"""
from os import remove
import numpy as np
import networkx as nx

def is_biconnected(matrix):
    """Returns a boolean representing whether the graph 
    is vertex biconnected or not.
    
    Args:
        matrix: A matrix representing the adjacency matrix of the graph.
    
    Returns:
        boolean: A boolean indicating TRUE if biconnected, FALSE otherwise.
    """
    nxgraph = nx.from_numpy_array(matrix)
    return nx.is_biconnected(nxgraph)

def get_cutvertices(nxgraph):
    """Returns list of cutvertices in the graph.
    Args:
        nxgraph: an instance of NetworkX graph object.
    
    Returns:
        articulation_list: A list of all articulation points in the graph.
    """
    articulation_list = list(nx.articulation_points(nxgraph))
    return articulation_list

def get_biconnected_components(nxgraph):
    """Returns list of biconnected components in the graph.
    Args:
        nxgraph: An instance of NetworkX graph object.
    
    Returns:
        components: A set of biconnected components.
    """
    components = nx.biconnected_components(nxgraph)
    return components

def same_component(nxgraph, node1, node2):
    """Returns list of biconnected components in the graph.
    Args: 
        nxgraph: An instance of Networkx graph object
        node1: An integer representing the first vertex to be checked.
        node2: An integer representing the second vertex to be checked.
    
    Returns:
        boolean: TRUE if vertices are in the same biconnected component else FALSE.
    """
    components = list(get_biconnected_components(nxgraph))
    for itr in range(len(components)):
        if (node1 in components[itr]) and (node2 in components[itr]):
            return True
    return False

def sort_list(nxgraph, neighbors):
    """Sorts the neighbors list such that neigbours in same components appear consecutively
    Args:
        nxgraph: An instance of Networkx graph object
        neighbors: List containing neighbors of an articulation point.
    
    Returns:
        neighbors_sorted: Required list with neighbors in same components appearing consecutively.
    """
    neighbors_sorted = []
    components = list(get_biconnected_components(nxgraph))
    for component in range(len(components)):
        temp_list = []
        for vertex in neighbors:
            if vertex in components[component]:
                if (vertex not in neighbors_sorted) and (vertex not in temp_list):
                    temp_list.append(vertex)
        neighbors_sorted.extend(temp_list)
    return neighbors_sorted

def biconnect(matrix):
    """Returns the edges to be added to make graph biconnected.
    Args:
        matrix: Adjacency matrix of the said graph.
    
    Returns:
        bicon_edges: A list of edges to be added to make the graph biconnected.
    """
    nxgraph = nx.from_numpy_array(matrix)
    articulation_points = get_cutvertices(nxgraph)
    bicon_edges = set()
    added_edges = set()
    removed_edges = set()
    for i in range(len(articulation_points)): 
        neighbors = list(nx.neighbors(nxgraph,articulation_points[i]))
        neighbors = sort_list(nxgraph, neighbors)
        for j in range(0,len(neighbors)-1):
            if not same_component(nxgraph,neighbors[j],neighbors[j+1]):
                added_edges.add((neighbors[j],neighbors[j+1]))
                if(articulation_points[i], neighbors[j]) in added_edges\
                    or (neighbors[j],articulation_points[i]) in added_edges:
                    removed_edges.add((articulation_points[i],neighbors[j]))
                    removed_edges.add((neighbors[j],articulation_points[i]))
                if (articulation_points[i],neighbors[j+1]) in added_edges\
                    or (neighbors[j+1],articulation_points[i]) in added_edges:
                    removed_edges.add((articulation_points[i],neighbors[j+1]))
                    removed_edges.add((neighbors[j+1],articulation_points[i]))
    bicon_edges = added_edges - removed_edges
    return bicon_edges
