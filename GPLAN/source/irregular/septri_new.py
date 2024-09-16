import networkx as nx
import numpy as np
import copy
import matplotlib.pyplot as plt

def sign(x1, y1, x2, y2, x3, y3):
    """Calculates value of (x1 - x3) * (y2 - y3) - (x2 - x3) * (y1 - y3)

    Args:
        x1, x2, x3, y1, y2, y3: Coordinates of triangle vertices.

    Returns:
        (x1 - x3) * (y2 - y3) - (x2 - x3) * (y1 - y3)
    """
    return (x1 - x3) * (y2 - y3) - (x2 - x3) * (y1 - y3)

def point_in_triangle(x1, y1, x2, y2, x3, y3, x, y, nodeId, face, adjacency):
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

    interior_pos = not (has_neg and has_pos)

    if((adjacency[nodeId][face[0]] == 1) and (adjacency[nodeId][face[1]] == 1) and (adjacency[nodeId][face[2]] == 1) ):     
        if interior_pos:
            return True

    return False

def get_edges(cycle):
    """Returns edges of a cycle.

    Args:
        cycle: A list containing vertices in a cycle.

    Returns:
        A list of tuples containing each edge's vertices in sorted order.
    """
    return [tuple(sorted([cycle[i], cycle[(i+1)%len(cycle)]])) for i in range(len(cycle))]

def calc_all_triangles(graph):
    all_cliques = list(nx.enumerate_all_cliques(graph))
    all_triangles = [sorted(i) for i in all_cliques if len(i) == 3]
    all_triangles = [list(triangle) for triangle in np.unique(all_triangles, axis=0)]
    return all_triangles

def get_sep_triangles_and_edges(all_triangles, num_nodes, origin_pos, adjacency):
    triangular_faces = []
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
                                origin_pos[face[2]][1], origin_pos[NodeID][0], origin_pos[NodeID][1], NodeID, face, adjacency)):
                flag = True


        if not flag:
            ## Add face information to edge_to_faces
            triangular_faces.append(face)
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
    separating_edges = list(set(separating_edges))

    return separating_triangles, separating_edges, separating_edge_to_triangles, edge_to_faces


def remove_st_edge_selection(st_with_internal_node, graph, total_STs, not_user_ST_flag, one_connected, all_triangles, num_nodes, non_adj_list):
    for i in st_with_internal_node.keys():
        for triangle in st_with_internal_node[i]:
            flag = False  # false if the edge is not an exterior edge
            edges = get_edges(triangle)
            
            # Attempt to remove an exterior edge
            for edge in edges:
                if not_user_ST_flag and (one_connected[edge[0]][edge[1]] == 1):
                    continue

                # Check if edge is exterior
                nbrs = list(nx.common_neighbors(graph, edge[0], edge[1]))
                points = list(triangle)
                points.remove(edge[0])
                points.remove(edge[1])
                third_node = points[0]

                if len(nbrs) == 2 and (i in nbrs) and (third_node in nbrs):
                    graph.remove_edge(edge[0], edge[1])
                    print("edge-removed1:", tuple([edge[0], edge[1]]), "from triangle:", triangle)
                    
                    # Update the separating triangle lists
                    for j in st_with_internal_node.keys():
                        for trngl in st_with_internal_node[j]:
                            edge_set = {(edge[0], edge[1]), (edge[1], edge[0])}
                            triangle_set = {(trngl[0], trngl[1]), (trngl[1], trngl[2]), (trngl[2], trngl[0]), (trngl[2], j), (j, trngl[0]), (j, trngl[1])}
                            if any(edge in edge_set for edge in triangle_set):
                                st_with_internal_node[j].remove(trngl)
                                if list(trngl) in all_triangles:
                                    all_triangles.remove(list(trngl))

                    total_STs -= 1
                    flag = True
                    break
            
            # If no exterior edge was removed, try removing non-exterior edges
            if not flag:
                print("No exterior edge found.")
                edge_found = False  # Track if a valid edge is found
                for edge in edges:
                    if not_user_ST_flag and (one_connected[edge[0]][edge[1]] == 1):
                        continue

                    for nbr in nx.common_neighbors(graph, edge[0], edge[1]):
                        if (nbr != i) and (nbr not in triangle) and (not graph.has_edge(nbr, i)) and (graph.has_edge(edge[0], edge[1])):
                            new_edge = (nbr, i)
                            
                            if new_edge in non_adj_list or (new_edge[1], new_edge[0]) in non_adj_list:
                                continue  # Skip if the new edge is in the non-adjacency list

                            graph_copy = copy.deepcopy(graph)
                            graph_copy.add_edge(nbr, i)
                            print("edge-added2:", new_edge, "from triangle:", triangle)
                            graph_copy.remove_edge(edge[0], edge[1])
                            print("edge-removed2:", tuple([edge[0], edge[1]]), "from triangle:", triangle)

                            # Validate the modification
                            all_triangles = calc_all_triangles(graph_copy)
                            planar = nx.is_planar(graph_copy)
                            if planar:
                                origin_pos = nx.planar_layout(graph_copy)
                                adjacency = nx.adjacency_matrix(graph_copy).toarray()
                                separating_triangles, separating_edges, separating_edge_to_triangles, edge_to_faces = get_sep_triangles_and_edges(all_triangles, num_nodes, origin_pos, adjacency)

                            if (not planar) or (len(separating_triangles) > total_STs - 1):
                                graph_copy.add_edge(edge[0], edge[1])
                                graph_copy.remove_edge(nbr, i)
                                all_triangles = calc_all_triangles(graph_copy)
                                print("changes revoked")
                                continue

                            # Update the separating triangle lists
                            for j in st_with_internal_node.keys():
                                for trngl in st_with_internal_node[j]:
                                    edge_set = {(edge[0], edge[1]), (edge[1], edge[0])}
                                    triangle_set = {(trngl[0], trngl[1]), (trngl[1], trngl[2]), (trngl[2], trngl[0]), (trngl[2], j), (j, trngl[0]), (j, trngl[1])}
                                    if any(edge in edge_set for edge in triangle_set):
                                        st_with_internal_node[j].remove(trngl)
                                        if list(trngl) in all_triangles:
                                            all_triangles.remove(list(trngl))

                            print("edge-removed2:", tuple([edge[0], edge[1]]), "from triangle:", triangle)
                            origin_pos = nx.planar_layout(graph_copy)
                            final_positions = origin_pos
                            adjacency = nx.adjacency_matrix(graph_copy).toarray()
                            separating_triangles, separating_edges, separating_edge_to_triangles, edge_to_faces = get_sep_triangles_and_edges(all_triangles, num_nodes, origin_pos, adjacency)
                            print("post sep_tri:", separating_triangles)
                            print("st_with_internal_node:", st_with_internal_node)
                            total_STs = len(separating_triangles)
                            graph = graph_copy
                            edge_found = True
                            break

                    if edge_found:
                        break
                
                # If no valid edge was found, try ignoring non-adjacency list for type 3 edges
                if not edge_found:
                    for edge in edges:
                        if not_user_ST_flag and (one_connected[edge[0]][edge[1]] == 1):
                            continue
                        for nbr in nx.common_neighbors(graph, edge[0], edge[1]):
                            if (nbr != i) and (nbr not in triangle) and (not graph.has_edge(nbr, i)) and (graph.has_edge(edge[0], edge[1])):
                                graph_copy = copy.deepcopy(graph)
                                graph_copy.add_edge(nbr, i)
                                print("edge-added3:", tuple([nbr, i]), "from triangle:", triangle)
                                graph_copy.remove_edge(edge[0], edge[1])
                                print("edge-removed3:", tuple([edge[0], edge[1]]), "from triangle:", triangle)

                                # Validate the modification
                                all_triangles = calc_all_triangles(graph_copy)
                                planar = nx.is_planar(graph_copy)
                                if planar:
                                    origin_pos = nx.planar_layout(graph_copy)
                                    adjacency = nx.adjacency_matrix(graph_copy).toarray()
                                    separating_triangles, separating_edges, separating_edge_to_triangles, edge_to_faces = get_sep_triangles_and_edges(all_triangles, num_nodes, origin_pos, adjacency)

                                if (not planar) or (len(separating_triangles) > total_STs - 1):
                                    graph_copy.add_edge(edge[0], edge[1])
                                    graph_copy.remove_edge(nbr, i)
                                    all_triangles = calc_all_triangles(graph_copy)
                                    print("changes revoked")
                                    continue

                                # Update the separating triangle lists
                                for j in st_with_internal_node.keys():
                                    for trngl in st_with_internal_node[j]:
                                        edge_set = {(edge[0], edge[1]), (edge[1], edge[0])}
                                        triangle_set = {(trngl[0], trngl[1]), (trngl[1], trngl[2]), (trngl[2], trngl[0]), (trngl[2], j), (j, trngl[0]), (j, trngl[1])}
                                        if any(edge in edge_set for edge in triangle_set):
                                            st_with_internal_node[j].remove(trngl)
                                            if list(trngl) in all_triangles:
                                                all_triangles.remove(list(trngl))

                                print("edge-removed3:", tuple([edge[0], edge[1]]), "from triangle:", triangle)
                                origin_pos = nx.planar_layout(graph_copy)
                                final_positions = origin_pos
                                adjacency = nx.adjacency_matrix(graph_copy).toarray()
                                separating_triangles, separating_edges, separating_edge_to_triangles, edge_to_faces = get_sep_triangles_and_edges(all_triangles, num_nodes, origin_pos, adjacency)
                                print("post sep_tri:", separating_triangles)
                                print("st_with_internal_node:", st_with_internal_node)
                                total_STs = len(separating_triangles)
                                graph = graph_copy
                                break

    return total_STs, graph



def handle_STs_with_edge_selection(one_connected, adjacency, positions, non_adj_list):
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
    # origin_pos = positions
    origin_pos = nx.planar_layout(graph)

    #printing the graph 
    pos=nx.spring_layout(graph) # positions for all nodes
    
    ## Get all cycles of length 3
    all_triangles = calc_all_triangles(graph)
    st_with_internal_node = dict()

    for face in all_triangles:
        for NodeID in range(num_nodes):
            if NodeID in face: 
                continue
            ## Search for node within triangle, storing the separating traingles wrt the internal node
            if (point_in_triangle(origin_pos[face[0]][0], origin_pos[face[0]][1], origin_pos[face[1]][0],
                                origin_pos[face[1]][1], origin_pos[face[2]][0],
                                origin_pos[face[2]][1], origin_pos[NodeID][0], origin_pos[NodeID][1], NodeID, face, adjacency )):
                if NodeID not in st_with_internal_node :
                    st_with_internal_node[NodeID] = [tuple(sorted([face[0], face[1], face[2]]))]
                else:
                    st_with_internal_node[NodeID].append(tuple(sorted([face[0], face[1], face[2]])))


    # number of separating traingles in the graph
    total_STs = len(st_with_internal_node)
    print("separating trngs", st_with_internal_node)
    
    #nx.draw_networkx(graph)
    total_STs, graph = remove_st_edge_selection(st_with_internal_node, graph, total_STs, False, one_connected, all_triangles, num_nodes, non_adj_list)
    

    adjacency=nx.adjacency_matrix(graph).toarray()
    if total_STs > 0:
        total_STs, graph = remove_st_edge_selection(st_with_internal_node, graph, total_STs, True, one_connected, all_triangles, num_nodes, non_adj_list)
    
    adjacencies = [nx.to_numpy_array(graph).astype(int)]

    return adjacencies, []
