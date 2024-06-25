"""Shortcut Resolver Module

This module allows user to identify separating triangle (refer Documentation) in
the graph and helps in removing separating triangle if required.

This module contains the following functions:

    * sign - calculates value of (x1 - x3) * (y2 - y3) - (x2 - x3) * (y1 - y3).
    * point_in_triangle - checks if a point is inside the triangle.
    * get_edges - returns edges of a cycle.
    * add_edge_to_cover - add edge of separating triangle to edge cover.
    * generate_alternate_graph - returns transformed graph for given graph.
    * get_graph_cover - returns edge cover of a graph.
    * get_separating_edge_cover - returns separating edge cover of the input graph.
    * get_multiple_separating_edge_covers - returns smultiple eparating edge cover of the input graph.
    * remove_separating_triangles - removes separating triangles by bisecting the cover edge.
    * handle_STs - handles separating triangles in a given adjacency matrix.

"""
import networkx as nx
import numpy as np
from shapely.geometry import Point, Polygon
import random, copy

def sign(x1, y1, x2, y2, x3, y3):
    """Calculates value of (x1 - x3) * (y2 - y3) - (x2 - x3) * (y1 - y3)

    Args:
        x1, x2, x3, y1, y2, y3: Coordinates of triangle vertices.

    Returns:
        (x1 - x3) * (y2 - y3) - (x2 - x3) * (y1 - y3)
    """
    return (x1 - x3) * (y2 - y3) - (x2 - x3) * (y1 - y3)

def point_in_triangle(x1, y1, x2, y2, x3, y3, x, y):
    """Checks if a point is inside the triangle.

    Args:
        x, y: Coordinate of the point.
        x1, y1, x2, y2, x3, y3: Coordinates of triangle vertices.

    Returns:
        A boolean indicating if the point is inside triangle or not.
    """
    d1 = sign(x, y, x1, y1, x2, y2)
    d2 = sign(x, y, x2, y2, x3, y3)
    d3 = sign(x, y, x3, y3, x1, y1)
    has_neg = (d1 < 0) or (d2 < 0) or (d3 < 0)
    has_pos = (d1 > 0) or (d2 > 0) or (d3 > 0)

    return not (has_neg and has_pos)

def get_edges(cycle):
    """Returns edges of a cycle.

    Args:
        cycle: A list containing vertices in a cycle.

    Returns:
        A list of tuples containing each edge's vertices in sorted order.
    """
    return [tuple(sorted([cycle[i], cycle[(i+1)%3]])) for i in range(len(cycle))]

def add_edge_to_cover(edge, edge_cover, separating_triangles, separating_edges, separating_edge_to_triangles):
    """Add the edge of separating triangle to edge cover.

    Args:
        edge: A list representing the edge to be removed.
        edge_cover: A list containing the edge cover.
        separating_triangles: A list of separating triangles.
        separating_edges: A list of separating edges.
        separating_edge_to_triangles:  A dictionary of separating triangles and their edge.

    Returns:
        None
    """
    ## Add edge to edge_cover, update separating_triangles, separating_edges, separating_edge_to_triangles accordingly

    if(edge in edge_cover):
        return

    for triangle in separating_edge_to_triangles[edge]:
        ## Prior to removing triangle from separating_edge_to_triangles, all references to it must be handled
        for other_edge in get_edges(triangle):
            if(other_edge == edge or other_edge not in separating_edges):
                continue
            ## As triangle will no longer be an ST, other_edge forgets triangle
            separating_edge_to_triangles[other_edge].remove(triangle)
            if(separating_edge_to_triangles[other_edge] == []):
                ## If other_edge is no longer a separating edge, remove it
                del separating_edge_to_triangles[other_edge]
                separating_edges.remove(other_edge)
        ## Remove triangle from consideration
        separating_triangles.remove(triangle)
    
    ## Edge has been handles and can be removed
    separating_edges.remove(edge)
    edge_cover.append(edge)

def generate_alternate_graph(separating_triangles, separating_edges, separating_edge_to_triangles):
    """Returns transformed graph for given graph.(Check algorithm)

    Args:
        separating_triangles: A list of separating triangles.
        separating_edges: A list of separating edges.
        separating_edge_to_triangles:  A dictionary of separating triangles and their edge.

    Returns:
        alternate_graph: A NxGraph object containing the transformed graph.
    """
    ## Generate a transformed graph where edges of STs form nodes, and each ST is represented by at least 1 edge between such nodes
    ## A node cover on this graph generates a cover of separating edges

    alternate_graph = nx.Graph()
    node_edges = set([edge for edge in separating_edges if len(separating_edge_to_triangles[edge]) > 1])

    for triangle in separating_triangles:
        edges = set(get_edges(triangle))
        non_common_edges = list(edges.difference(node_edges))
        new_edges = []
        if(len(non_common_edges) == 3):
            new_edges.append(random.choice(non_common_edges))
            non_common_edges.remove(new_edges[0])
            new_edges.append(random.choice(non_common_edges))
        elif(len(non_common_edges) == 2):
            new_edges.append(random.choice(non_common_edges))
        node_edges.update(new_edges)
    
    for triangle in separating_triangles:
        relevant_edges = list(set(get_edges(triangle)).intersection(node_edges))
        if(len(relevant_edges) == 3):
            alternate_graph.add_edges_from([(relevant_edges[0], relevant_edges[1]), (relevant_edges[1], relevant_edges[2]), (relevant_edges[2], relevant_edges[0])])
        else:
            alternate_graph.add_edge(relevant_edges[0], relevant_edges[1])
    
    return alternate_graph

def get_graph_cover(graph, cover):
    """Returns edge cover of a graph.

    Args:
        graph. A NetworkX graph object representing the graph.
        cover: A list containing the cover.

    Returns:
        A list containing the edge cover.
    """
    edges = list(graph.edges())
    if(edges == []):
        return cover
    
    random_edge = random.choice(edges)
    graph.remove_nodes_from(list(random_edge))
    cover.extend(list(random_edge))
    return get_graph_cover(graph, cover)

def get_separating_edge_cover(edge_cover, separating_triangles, separating_edges, separating_edge_to_triangles):
    """Returns separating edge cover of the input graph.

    Args:
        edge_cover: A list containing the edge cover.
        separating_triangles: A list of separating triangles.
        separating_edges: A list of separating edges.
        separating_edge_to_triangles:  A dictionary of separating triangles and their edge.

    Returns:
        edge_cover: A list containing the edge cover.
    """
    ## Calls itself recursively
    ## Handles isolated STs
    ## Greedily selects separating_edge that handles the most STs, and adds it to the cover

    alternate_graph = generate_alternate_graph(separating_triangles, separating_edges, separating_edge_to_triangles)
    edge_cover = get_graph_cover(alternate_graph, [])
    return edge_cover
    
    # ## Recursive base case
    # if(separating_triangles == []):
    #     return edge_cover

    # ## Greedily find best_edge to add to cover
    # longest_length = 0
    # best_edge = separating_edges[0]
    # for edge in separating_edges:
    #     if(len(separating_edge_to_triangles[edge]) > longest_length):
    #         longest_length = len(separating_edge_to_triangles[edge])
    #         best_edge = edge
            
    # ## Add best_edge to cover
    # add_edge_to_cover(best_edge, edge_cover, separating_triangles, separating_edges, separating_edge_to_triangles)

    # ## Recursively call in order to repeat
    # get_separating_edge_cover(edge_cover, separating_triangles, separating_edges, separating_edge_to_triangles)

def get_multiple_separating_edge_covers(expected_count, separating_triangles, separating_edges, separating_edge_to_triangles):
    """Returns multiple eparating edge cover of the input graph.

    Args:
        expected_count: An integer indicating the expected number of solutions.
        separating_triangles: A list of separating triangles.
        separating_edges: A list of separating triangles.
        separating_edge_to_triangles:  A dictionary of separating triangles and their edge.

    Returns:
       covers: A list containing multiple edge covers.
    """
    covers = set()
    futility_counter = 0
    while(len(covers) < expected_count):
        separating_edge_cover = frozenset(get_separating_edge_cover([], separating_triangles, separating_edges, separating_edge_to_triangles))
        if(separating_edge_cover not in covers):
            futility_counter = 0
            covers.add(separating_edge_cover)
        if(futility_counter > expected_count/2):
            break
        futility_counter += 1
    return covers

def remove_separating_triangles(graph, separating_edges, edge_to_faces):
    """Removes separating triangles by bisecting the cover edge.

    Args:
        graph: A NetworkX object representing the graph.
        separating_edges: A list representing the separating edges.
        edge_to_faces: A dictionary mapping each edge to respective face.

    Returns:
        extra_nodes: A dictionary containing extra nodes added for removing separating triangle.
    """
    ## Remove separating triangles by bisecting each edge in the cover, separating_edges

    ## Get initial graph data
    origin_pos = nx.get_node_attributes(graph, 'pos')
    total_no_of_vertices = graph.number_of_nodes()
    extra_nodes = {}
    for edge in separating_edges:
        ## Bisect edge
        graph.remove_edge(edge[0], edge[1])
        position = ((origin_pos[edge[0]][0] + origin_pos[edge[1]][0]) /2, (origin_pos[edge[0]][1] + origin_pos[edge[1]][1]) /2)
        graph.add_node(total_no_of_vertices, pos = position)
        graph.add_edges_from([(total_no_of_vertices, edge[0]), (total_no_of_vertices, edge[1])])
        extra_nodes[total_no_of_vertices] = [edge[0],edge[1]]
        
        ## Handle triangulation and update edge_to_faces
        for triangle in edge_to_faces[edge]:
            ## Retriangulate graph after addition of new vertex total_no_of_vertices
            other_vertex = list(set(triangle).difference(edge))[0]
            graph.add_edge(total_no_of_vertices, other_vertex)

            ## Update edge_to_faces due to changes in faces caused by above bisection and triangulation
            new_triangle0 = sorted([other_vertex, edge[0], total_no_of_vertices])
            new_triangle1 = sorted([other_vertex, edge[1], total_no_of_vertices])
            edge_to_faces[tuple(sorted([other_vertex, edge[0]]))].remove(triangle)
            edge_to_faces[tuple(sorted([other_vertex, edge[1]]))].remove(triangle)
            edge_to_faces[tuple(sorted([other_vertex, edge[0]]))].append(new_triangle0)
            edge_to_faces[tuple(sorted([other_vertex, edge[1]]))].append(new_triangle1)

            ## Add edges from new vertex total_no_of_vertices to edge_to_faces
            if(tuple(sorted([other_vertex, total_no_of_vertices])) not in edge_to_faces):
                edge_to_faces[tuple(sorted([other_vertex, total_no_of_vertices]))] = []
            if(tuple(sorted([total_no_of_vertices, edge[0]])) not in edge_to_faces):
                edge_to_faces[tuple(sorted([total_no_of_vertices, edge[0]]))] = []
            if(tuple(sorted([total_no_of_vertices, edge[1]])) not in edge_to_faces):
                edge_to_faces[tuple(sorted([total_no_of_vertices, edge[1]]))] = []
            edge_to_faces[tuple(sorted([other_vertex, total_no_of_vertices]))] = [new_triangle0, new_triangle1]
            edge_to_faces[tuple(sorted([total_no_of_vertices, edge[0]]))].append(new_triangle0)
            edge_to_faces[tuple(sorted([total_no_of_vertices, edge[1]]))].append(new_triangle1)
        total_no_of_vertices += 1
    return extra_nodes

def handle_STs(adjacency, positions, num_expected_outputs):
    """Handles separating triangles in a given adjacency matrix.

    Args:
        adjacency: A matrix representing the adjacency matrix.
        positions: A list representing coordinates of each node.
        num_expected_outputs: An integer representing the expected number of solutions.

    Returns:
        adjacencies: A list containing the multiple modified adjacency matrices.
        extra_nodes_pair: A list containing the extra nodes added.
    """
    ## Remove separating triangles by finding a cover of separating edges, bisecting them and retriangulating the graph

    ## Input display
    graph = nx.Graph()
    num_nodes = len(adjacency)
    for i in range(num_nodes):
        graph.add_node(i, pos = positions[i])
    for row in range(num_nodes):
        for column in range(num_nodes):
            if(adjacency[row][column]):
                graph.add_edge(row, column)
    origin_pos = positions

    ## Get all cycles of length 3
    all_cliques = list(nx.enumerate_all_cliques(graph))
    all_triangles = [sorted(i) for i in all_cliques if len(i) == 3]
    all_triangles = [list(triangle) for triangle in np.unique(all_triangles, axis=0)]

    trianlular_faces = []
    separating_triangles = []
    separating_edges = []       ## edges of separating triangles
    separating_edge_to_triangles = dict()
    edge_to_faces = dict()

    for face in all_triangles:
        flag = False
        for NodeID in range(num_nodes):
            if NodeID in face:
                continue

            ## Search for node within triangle
            if (point_in_triangle(origin_pos[face[0]][0], origin_pos[face[0]][1], origin_pos[face[1]][0],
                                origin_pos[face[1]][1], origin_pos[face[2]][0],
                                origin_pos[face[2]][1], origin_pos[NodeID][0], origin_pos[NodeID][1])):
                flag = True
                break

        if not flag:
            ## Add face information to edge_to_faces
            trianlular_faces.append(face)
            for edge in get_edges(face):
                if(edge not in edge_to_faces):
                    edge_to_faces[edge] = []
                edge_to_faces[edge].append(face)

        else:
            ## Add ST information to separating_triangles, separating_edges and separating_edge_to_triangles
            separating_triangle = tuple(sorted([face[0], face[1], face[2]]))
            separating_triangles.append(separating_triangle)

            edges = get_edges(face)
            separating_edges.extend(edges)

            for edge in edges:
                if(edge not in separating_edge_to_triangles):
                    separating_edge_to_triangles[edge] = []
                separating_edge_to_triangles[edge].append(separating_triangle)
        
    ## Get unique separating edges, handle STs
    separating_edges = list(set(separating_edges))

    covers = list(get_multiple_separating_edge_covers(num_expected_outputs, separating_triangles, separating_edges, separating_edge_to_triangles))

    graphs = []
    extra_nodes_pair = []
    for i in range(len(covers)):
        graph_copy = graph.copy()
        extra_nodes = remove_separating_triangles(graph_copy, covers[i], copy.deepcopy(edge_to_faces))
        extra_nodes_pair.append(extra_nodes)
        graphs.append(graph_copy)

    adjacencies = [nx.to_numpy_array(graph).astype(int) for graph in graphs]
    return adjacencies, extra_nodes_pair