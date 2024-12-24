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
from networkx import simple_cycles
from networkx import adjacency_matrix
from shapely.geometry import Point, MultiPoint, LineString, GeometryCollection
import numpy as np
import matplotlib.path as mplPath
import matplotlib.pyplot as plt
from . import earclipping as ec


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

def check_if_present(list_of_tuples, list_of_list_of_tuples):
    # Convert each tuple in the list_of_tuples into a frozenset
    set_of_tuples = {frozenset(t) for t in list_of_tuples}

    # Convert each list of tuples in the list_of_list_of_tuples into a set of frozensets
    set_of_list_of_tuples = [{frozenset(t) for t in lst} for lst in list_of_list_of_tuples]

    # Check if the set of tuples is a subset of any set of list of tuples
    return any(set_of_tuples == s for s in set_of_list_of_tuples)


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
    # adding first edge to path
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

    
    for face in faces:
        edgeset = set()
        for edge in face: 
            edge = list(edge)
            edgeset |= set([(edge[0],edge[1]),(edge[1],edge[0])])
        
        face_vertices = find_face_node(face)
        
        for i in face_vertices:
            for j in face_vertices:
                path = []
                if tuple([i,j]) in edges:
                    if tuple([i,j]) not in face and tuple([j,i]) not in face:
                        edge = tuple([i,j])
                        path.append(edge)
                        edgeset -= set([edge])
                            
                        while (len(edgeset) > 0):
                            neighbors = embedding[path[-1][-1]]
                            neighbors = [node for node in neighbors if node in face_vertices]
                            next_node = neighbors[(neighbors.index(path[-1][-2])+1)%(len(neighbors))]
                            tup = (path[-1][-1],next_node)

                            if tup == path[0] :
                                if face != path and len(path)>0:
                                    if not check_if_present(path, faces):
                                        faces.append(path)
                                break
                            else:
                                path.append(tup)
                                edgeset -= set([tup])
                                if(len(edgeset)==0):
                                    break
                        

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
    if len(faces) == 2:
        faces = [faces[0]]
    non_tri_faces = [face for face in faces if len(face) > 3]
    non_tri_faces = sorted(non_tri_faces ,  key=lambda x: len(x), reverse = True)
    outer_face = []
    for face in non_tri_faces:
        outer_face_found = False
        face_vertices = find_face_node(face)
        face_coordinates = [positions[node] for node in face_vertices]
        for node in G.nodes:
            bbPath = mplPath.Path(np.array(face_coordinates))
            if bbPath.contains_point((positions[node][0],positions[node][1])) and node not in face_vertices:
                outer_face_found = True
                break
            if node in face_vertices:
                for node2 in face_vertices:
                    if G.has_edge(node,node2) and ((node,node2) not in face and (node2,node) not in face)and bbPath.contains_point(((positions[node][0]+positions[node2][0])/2,(positions[node][1]+positions[node2][1])/2)):
                        outer_face_found = True
                        break
                if outer_face_found:
                    break
        if outer_face_found == True:
            outer_face.append(face)
            break
    non_tri_faces = [item for item in non_tri_faces if item not in outer_face]
    return non_tri_faces


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

def get_tri_edges(non_tri_faces, positions, non_adj_list):
    """Finds edges to make non-triangular faces triangular using 
       ear-clipping algorithm.

    Args:
        non_tri_faces: A list containing the non-triangular interior faces.
        positions: A dictionary containing the node as key and
                   its coordinate as value.
        non_adj_list: A list containing edges that should not be added.

    Returns:
        tri_edges: A list containing the edges to be added.
    """
    tri_edges = []
    for face in non_tri_faces:
        face_vertices = find_face_node(face)
        face_coordinates = np.array([positions[node]
                                     for node in face_vertices])

        def add_edge(a, c, face, i):
            tri_edges.append((a, c))
            if (a, b) in face:
                face.remove((a, b))
            if (b, c) in face:
                face.remove((b, c))
            face.insert(i, (a, c))
            # Update face_vertices and face_coordinates
            face_vertices = find_face_node(face)
            face_coordinates = np.array([positions[node] for node in face_vertices])
            return face_vertices, face_coordinates

        i = 0
        edge_added = False
        while i < len(face_vertices):
            a = face_vertices[i]
            b = face_vertices[(i + 1) % len(face_vertices)]
            c = face_vertices[(i + 2) % len(face_vertices)]

            [x1, y1] = positions[a]
            [x2, y2] = positions[b]
            [x3, y3] = positions[c]
            node = [(x1 + x3) / 2, (y1 + y3) / 2]
            bbPath = mplPath.Path(np.array(face_coordinates))

            from shapely.geometry import LineString, Point, Polygon

            point_a = Point(positions[a])
            point_b = Point(positions[c])

            segment = LineString([point_a, point_b])
            polygon = Polygon(face_coordinates)
            polygon_ext = LineString(list(polygon.exterior.coords))
            intersections = polygon_ext.intersection(segment)
            if isinstance(intersections, Point):
                inter_points = [(intersections.x, intersections.y)]
            elif isinstance(intersections, MultiPoint):
                inter_points = [(pt.x, pt.y) for pt in intersections.geoms]
            elif isinstance(intersections, LineString):
                # Extract points along the LineString
                inter_points = list(intersections.coords)
            elif isinstance(intersections, GeometryCollection):
                # Filter only Point or MultiPoint geometries from the collection
                inter_points = []
                for geom in intersections.geoms:
                    if isinstance(geom, Point):
                        inter_points.append((geom.x, geom.y))
                    elif isinstance(geom, MultiPoint):
                        inter_points.extend([(pt.x, pt.y) for pt in geom.geoms])

            flag = True

            for pt in inter_points:
                if pt != point_a and pt != point_b:
                    flag = False

            if (abs((y3 - y2) * (x2 - x1) - (y2 - y1) * (x3 - x2))<1e-9):
                i += 1
                continue

            if len(inter_points) <= 2 and bbPath.contains_point((node[0], node[1])) and polygon.contains(Point(node)):
                if (a, c) in non_adj_list or (c, a) in non_adj_list:
                    i += 1
                    continue

                face_vertices, face_coordinates = add_edge(a, c, face, i)
                edge_added = True 

                i = 0
                if len(face_vertices) == 3:
                    break
                continue

            i += 1
            if len(face_vertices) == 3:
                break

        # If no valid edges were added, ignore the non-adjacency list and add edges as before
        #if len(face_vertices) > 3:
        if not edge_added and len(face_vertices) > 3:
            i = 0
            while i < len(face_vertices):
                a = face_vertices[i]
                b = face_vertices[(i + 1) % len(face_vertices)]
                c = face_vertices[(i + 2) % len(face_vertices)]

                [x1, y1] = positions[a]
                [x2, y2] = positions[b]
                [x3, y3] = positions[c]
                node = [(x1 + x3) / 2, (y1 + y3) / 2]
                bbPath = mplPath.Path(np.array(face_coordinates))

                from shapely.geometry import LineString, Point, Polygon

                point_a = Point(positions[a])
                point_b = Point(positions[c])

                segment = LineString([point_a, point_b])
                polygon = Polygon(face_coordinates)
                polygon_ext = LineString(list(polygon.exterior.coords))
                intersections = polygon_ext.intersection(segment)
                if isinstance(intersections, Point):
                    inter_points = [(intersections.x, intersections.y)]
                elif isinstance(intersections, MultiPoint):
                    inter_points = [(pt.x, pt.y) for pt in intersections.geoms]
                elif isinstance(intersections, LineString):
                    # Extract points along the LineString
                    inter_points = list(intersections.coords)
                elif isinstance(intersections, GeometryCollection):
                    # Filter only Point or MultiPoint geometries from the collection
                    inter_points = []
                    for geom in intersections.geoms:
                        if isinstance(geom, Point):
                            inter_points.append((geom.x, geom.y))
                        elif isinstance(geom, MultiPoint):
                            inter_points.extend([(pt.x, pt.y) for pt in geom.geoms])

                flag = True

                for pt in inter_points:
                    if pt != point_a and pt != point_b:
                        flag = False

                if (abs((y3 - y2) * (x2 - x1) - (y2 - y1) * (x3 - x2))<1e-9):
                    i += 1
                    continue

                if len(inter_points) <= 2 and bbPath.contains_point((node[0], node[1])) and polygon.contains(Point(node)):
                    face_vertices, face_coordinates = add_edge(a, c, face, i)

                    i = 0
                    if len(face_vertices) == 3:
                        break
                    continue

                i += 1
                if len(face_vertices) == 3:
                    break

    return tri_edges


def triangulate(matrix, bcn_edges_added, pos, non_adj_list):
    """Find edges to be added to make graph triangulated.

    Args:
        matrix: A matrix representing the adjacency matrix of the graph.
        bcn_edges_Added: A boolean representing whether edges are added
                         by biconnectivity.
        pos: A dictionary containing coordinates of planar embedding.
        non_adj_list: A list containing edges that should not be added.

    Returns:
        tri_edges: A list containing the edges to be added.
        positions: A dictionary containing coordinates of planar embedding.

    """
    nxgraph = nx.from_numpy_array(matrix)
    print("Non-Adjacency List Applied in Triangularity:", non_adj_list)

    if(not bcn_edges_added):
        positions = {i:pos[i] for i in range(len(pos))}
    else:
        positions = nx.planar_layout(nxgraph)
    nx.draw_networkx(nxgraph,positions, label=None,node_size=400 ,node_color='#4b8bc8',font_size=12, font_color='k', font_family='sans-serif', font_weight='normal', alpha=1, bbox=None, ax=None)
    plt.show()

    non_tri_faces = get_nontriangular_face(positions, nxgraph)

    tri_edges = get_tri_edges(non_tri_faces, positions, non_adj_list)
    nxgraph = nx.Graph(list(nxgraph.edges) + tri_edges)

    tri_cycles = nx.chordless_cycles(nxgraph)
    tri_faces = []
    for cycle in tri_cycles:
        tri_face = []
        for i in range(len(cycle)):
            tri_face.append(tuple([cycle[i], cycle[(i+1)%len(cycle)]]))

        if len(cycle) == 3:
            tri_faces.append(tri_face)

    return tri_edges, positions, tri_faces

