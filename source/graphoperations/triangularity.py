"""Triangularity Module

This module allows the user to triangulate a given biconnected
planar graph.

This module contains the following functions:

    * atan2: converts cartesian coordinate to angular coordinate.
    * get_new_coordinates: converts cartesian coordinates of neighbours to 
                            angular coordinates of neighbours wrt given origin
                            vertex.
    * get_faces: finds faces of a graph given set of edges and combinatorial
                 embedding.
    * find_face_node: finds nodes in a face.
    * get_nontriangular_face: finds non-triangular interior faces in a given planar embedding
                              of the graph.
    * get_tri_edges: finds edges to make non triangular faces trkangular using 
                     ear-clipping algorithm.
    * triangulate: find edges to be added to make graph triangulated.
"""

import networkx as nx
import math
import numpy as np
import matplotlib.path as mplPath
from ..graphoperations import earclipping as ec

def atan2(x,y):
    """Converts cartesian coordinate to angular coordinate.

    Args:
        x: A float representing the x-coordinate.
        y: A float representing the y-coordinate.

    Returns:
        A value between 0 and 2*pi representing the angular coordinate.
    """
    if x > 0:
        return math.atan(y/x)
    elif x < 0 and y >= 0:
        return math.atan(y/x) + math.pi
    elif x < 0 and y < 0:
        return math.atan(y/x) - math.pi
    elif x == 0 and y > 0:
        return math.pi/2
    elif x == 0 and y < 0:
        return -1*math.pi/2
    else:
        return 0

def get_new_coordinates(nbr_dict,src):
    """Converts cartesian coordinates of neighbours to 
       angular coordinates of neighbours wrt given origin'
       vertex.

    Args:
        nbr_dict: A dictionary containing the cartesian coordinate
                  of neighbours.
        src: A length two list containing cartesian coordinate of
             origin vertex.

    Returns:
        nbr_dict_polar: A dictionary containing the polar coordinates
                  of neighbours wrt origin vertex.
    """
    nbr_dict_translated = {}
    for key in nbr_dict:
        nbr_dict_translated[key] = []
        nbr_dict_translated[key].append(nbr_dict[key][0] - src[0])
        nbr_dict_translated[key].append(nbr_dict[key][1] - src[1])
    nbr_dict_polar = {}
    for key in nbr_dict:
        nbr_dict_polar[key] = atan2(nbr_dict_translated[key][0],nbr_dict_translated[key][1])
    
    return nbr_dict_polar

def get_faces(edges,embedding):
    """Finds faces of a graph given set of edges and combinatorial
       embedding.
       Source: Jose Antonio Martin H. (https://mathoverflow.net/users/15589/jose-antonio-martin-h).
               Reporting all faces in a planar graph. .

    Args:
        edges: A list containing edges of the graph.
        embedding: A dictionary containing the nodes as key and their
                   cartesian coordinates as value.

    Returns:
        faces: A list of faces of the graph based on the input planar
               embedding.

    """
    edgeset = set()
    for edge in edges: 
        edge = list(edge)
        edgeset |= set([(edge[0],edge[1]),(edge[1],edge[0])])

    faces = []
    path  = []
    for edge in edgeset:
        path.append(edge)
        edgeset -= set([edge])
        break  

    while (len(edgeset) > 0):
        neighbors = embedding[path[-1][-1]]
        next_node = neighbors[(neighbors.index(path[-1][-2])+1)%(len(neighbors))]
        tup = (path[-1][-1],next_node)
        if tup == path[0]:
            faces.append(path)
            path = []
            for edge in edgeset:
                path.append(edge)
                edgeset -= set([edge])
                break  # (Only one iteration)
        else:
            path.append(tup)
            edgeset -= set([tup])
    if (len(path) != 0): faces.append(path)
    return faces

def find_face_node(face):
    """Finds nodes in a face.

    Args:
        face: A list containing the edges of the face.

    Returns:
        nodes: A list containing the nodes of the face.

    """
    nodes = []
    for edge in face:
        nodes.append(edge[0])
    return nodes

def get_nontriangular_face(positions, G):
    """Finds non-triangular interior faces in a given planar embedding
       of the graph.

    Args:
        positions: A dictionary containing the node as key and
                   its coordinate as value.
        G: An instance of NetworkX graph object.

    Returns:
        non_tri_faces: A list containing the non-triangular interior faces.

    """
    nodes_ordered_nbr = {}
    for node in G.nodes:
        nbr_dict = {n:positions[n] for n in G[node]}
        nbr_dict_polar = get_new_coordinates(nbr_dict,positions[node])
        nbr_sorted = sorted(nbr_dict_polar.items() ,  key=lambda x: x[1], reverse = True)
        nbr_sorted = [x[0] for x in nbr_sorted]
        nodes_ordered_nbr[node] = nbr_sorted
    faces = get_faces(G.edges,nodes_ordered_nbr)
    non_tri_faces = [face for face in faces if len(face) > 3]
    non_tri_faces = sorted(non_tri_faces ,  key=lambda x: len(x), reverse = True)
    outer_face = []
    for face in non_tri_faces:
        outer_face_found = True
        face_vertices = find_face_node(face)
        face_coordinates = [positions[node] for node in face_vertices]
        for node in G.nodes:
            bbPath = mplPath.Path(np.array(face_coordinates))
            if not bbPath.contains_point((positions[node][0],positions[node][1])) and node not in face_vertices:
                outer_face_found = False
                break
        if outer_face_found == True:
            outer_face.append(face)
            break
    non_tri_faces = [item for item in non_tri_faces if item not in outer_face]
    return non_tri_faces

def get_tri_edges(non_tri_faces,positions):
    """Finds edges to make non triangular faces trkangular using 
       ear-clipping algorithm.

    Args:
        non_tri_faces: A list containing the non-triangular interior faces.
        positions: A dictionary containing the node as key and
                   its coordinate as value.

    Returns:
        tri_edges: A list containing the edges to be added.

    """
    tri_edges = []
    for face in non_tri_faces:
        face_vertices = find_face_node(face)
        face_coordinates = np.array([positions[node]
                                 for node in face_vertices])
        triangles = ec.triangulate(face_coordinates,0)
        for triangle in triangles:
            vertex1 = face_vertices[triangle[0]]
            vertex2 = face_vertices[triangle[1]]
            vertex3 = face_vertices[triangle[2]]
            if (vertex1,vertex2) not in face and\
                (vertex2,vertex1) not in face and\
                (vertex1,vertex2) not in tri_edges and\
                (vertex2,vertex1) not in tri_edges:
                tri_edges.append((vertex1,vertex2))
            if (vertex2,vertex3) not in face and\
                (vertex3,vertex2) not in face and\
                (vertex2,vertex3) not in tri_edges and\
                (vertex3,vertex2) not in tri_edges:
                tri_edges.append((vertex2,vertex3))
            if (vertex1,vertex3) not in face and\
                (vertex3,vertex1) not in face and\
                (vertex1,vertex3) not in tri_edges and\
                (vertex3,vertex1) not in tri_edges:
                tri_edges.append((vertex1,vertex3))
    return tri_edges

def get_faces_after_triangulation(tri_edges,nxgraph,positions):
    """Finds faces of the triangualated graph.

    Args:
        tri_edges: A list containing the edges to be added to make the 
                    graph triangulated.
        nxgraph: A Networkx object representing the input graph.
        positions: A dictionary containing the node as key and
                   its coordinate as value.

    Returns:
        tri_faces: A list containing the faces of triangulated graph.

    """
    trng_nxgraph = nx.Graph(list(nxgraph.edges)+tri_edges)
    nodes_ordered_nbr = {}
    for node in trng_nxgraph.nodes:
        nbr_dict = {n:positions[n] for n in trng_nxgraph[node]}
        nbr_dict_polar = get_new_coordinates(nbr_dict,positions[node])
        nbr_sorted = sorted(nbr_dict_polar.items() ,  key=lambda x: x[1], reverse = True)
        nbr_sorted = [x[0] for x in nbr_sorted]
        nodes_ordered_nbr[node] = nbr_sorted
    faces = get_faces(trng_nxgraph.edges,nodes_ordered_nbr)
    tri_faces = [face for face in faces if len(face) == 3]
    return tri_faces


def triangulate(matrix,bcn_edges_added,pos):
    """Find edges to be added to make graph triangulated.

    Args:
        matrix: A matrix representing the adjacency matrix of the graph.
        bcn_edges_Added: A boolean representing whether edges are added
                         by biconnectivity.
        pos: A list containing coordinates of planar embedding.

    Returns:
        tri_edges: A list containing the edges to be added.
        positions: A list containing coordinates of planar embedding.

    """
    nxgraph = nx.from_numpy_array(matrix)
    if(not bcn_edges_added):
        positions = {i:pos[i] for i in range(len(pos))}
    else:
        positions = nx.planar_layout(nxgraph)
    non_tri_faces = get_nontriangular_face(positions, nxgraph)
    tri_edges = get_tri_edges(non_tri_faces,positions)
    tri_faces = get_faces_after_triangulation(tri_edges,nxgraph,positions)
    return tri_edges,positions,tri_faces

    

# Old triangularity code based on chordality
# def make_chordal(nxgraph):
#     """Finds edges to be added to make graph triangulated.

#     Args:
#         nxgraph: An instance of NetworkX Graph object.

#     Returns:
#         edges: A list representing edges to be added.
#     """
#     nxgraphcopy = nxgraph.copy()
#     alpha = {node: 0 for node in nxgraphcopy}
#     if nx.is_chordal(nxgraphcopy):
#         return []
#     chords = set()
#     weight = {node: 0 for node in nxgraphcopy.nodes()}
#     unnumbered_nodes = list(nxgraphcopy.nodes())
#     for i in range(len(nxgraphcopy.nodes()), 0, -1):
#         z = max(unnumbered_nodes, key=lambda node: weight[node])
#         unnumbered_nodes.remove(z)
#         alpha[z] = i
#         update_nodes = []
#         for y in unnumbered_nodes:
#             if nxgraph.has_edge(y, z):
#                 update_nodes.append(y)
#             else:
#                 y_weight = weight[y]
#                 lower_nodes = [
#                     node for node in unnumbered_nodes if weight[node] < y_weight
#                 ]
#                 if nx.has_path(nxgraphcopy.subgraph(lower_nodes + [z, y]), y, z):
#                     update_nodes.append(y)
#                     chords.add((z, y))
#         for node in update_nodes:
#             weight[node] += 1
#     edges = chords
#     return edges

# def chk_chordality(nxgraph):
#     """Checks chordality of a given graph.

#     Args:
#         nxgraph: An instance of NetworkX Graph object.

#     Returns:
#         boolean: A boolean representing if graph requires triangulation.
#     """
#     if nx.is_chordal(nxgraph):
#         return True
#     else:
#         triad_cliques = [x for x in nx.enumerate_all_cliques(nxgraph) if len(x) == 3]
#         if len(triad_cliques) + len(nxgraph.nodes()) - len(nxgraph.edges()) == 1:
#             return True
#         return False

# def triangulate(matrix):
#     """Checks if a graph needs to be triangulated and returns
#         edges to be added to make it triangulated.

#     Args:
#         matrix: A matrix representing the adjacency matrix of the graph.

#     Returns:
#         trng_edges: A list of edges to be added to make the graph triangulated.
#     """
#     nxgraph = nx.from_numpy_array(matrix)
#     trng_edges = []
#     if not chk_chordality(nxgraph):
#         trng_edges = make_chordal(nxgraph)
#     return trng_edges