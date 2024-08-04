# Import necessary modules and functions
from pickle import FALSE, TRUE
from random import randint, triangular
from networkx.algorithms.core import core_number
from networkx.classes import graph
import networkx as nx


from .modifiedCanonical import canonical
from ..lshape import canonicalTransition as Canonical_LShaped

from ...inputgraph import InputGraph as inputgraph
from ...floorplangen import rdg 
from ...boundary import cip  
from ...graphoperations import operations as opr
import numpy as np
from ...boundary import news as news
from ...irregular import shortcutresolver as sr 
from ...floorplangen import contraction as cntr
from ...floorplangen import expansion as exp
from ...irregular import septri as st

# Function to generate an L-shaped floorplan
def LShapedFloorplan(graph, nodes_data):
    # Separating Triangle Elimination (Check if the graph needs to handle separating triangles)
    if (graph.nodecnt - graph.edgecnt + len(opr.get_trngls(graph.matrix)) != 1):
        ptpg_matrices, extra_nodes = st.handle_STs(
            graph.matrix, graph.coordinates, 1)
        graph.matrix = ptpg_matrices[0]
        graph.nodecnt = graph.matrix.shape[0]
        graph.edgecnt = int(np.count_nonzero(graph.matrix == 1) / 2)
        for key in extra_nodes[0]:
            graph.mergednodes.append(key)
            graph.irreg_nodes1.append(extra_nodes[0][key][0])
            graph.irreg_nodes2.append(extra_nodes[0][key][1])

    # Find critical independent paths (CIPs)
    cip = find_cips(graph)
    if len(cip) > 5:
        return "CIPs greater than 5"
    print("Length of CIP: {}".format(len(cip)))

    # Find a triplet in the graph
    triplet = find_triplet(graph)
    if triplet == -1:
        # If no triplet is found, handle it as a trivial L-shaped floorplan
        trivialL(graph)
    else:
        # If a triplet is found, continue with the L-shaped floorplan generation
        path1 = find_paths(graph, triplet, cip)
        print("Checking path1", path1)
        new_adjacency_mat = connect_northeast(graph, path1)
        print("Checking new adjacency matrix", new_adjacency_mat)
        graph.user_matrix = new_adjacency_mat
        graph.cip = find_cips(graph)
        print("Length of CIP: {}".format(len(graph.cip)))
        new_adjacency_mat = add_NESW(graph, new_adjacency_mat, path1)
        graph.matrix = new_adjacency_mat
        graph.matrix[graph.north][graph.south] = 1
        graph.matrix[graph.south][graph.north] = 1
        print("Checking final graph matrix", graph.matrix)

        # Generate a canonical representation of the graph
        can = canonical()
        can.displayInputGraph(graph.nodecnt, graph.matrix, nodes_data)
        can.runWithArguments(graph.nodecnt, graph.west, graph.south, graph.north, triplet, graph, graph.matrix, cip)
        graph.matrix[graph.north][graph.south] = 0
        graph.matrix[graph.south][graph.north] = 0
        print(can.graph_data['indexToCanOrd'])
        my_rel = Canonical_LShaped.Canonical_L_Shaped(can.graph_data['indexToCanOrd'], graph)
        graph.matrix = my_rel

        # Generate the final floorplan
        get_floorplan(graph, triplet)

# Function to handle trivial L-shaped floorplans
def trivialL(graph):
    graph.cip = find_cips(graph)
    print(graph.cip)
    if len(graph.cip) > 0:
        cip = randint(0, len(graph.cip) - 1)
        path1 = graph.cip[cip][0:randint(2, max(2, len(graph.cip[cip]) - 2))]
        new_adjacency_mat = connect_northeast(graph, path1)
    else:
        triangular_cycles = opr.get_trngls(graph.matrix)
        digraph = opr.get_directed(graph.matrix)
        graph.bdy_nodes, graph.bdy_edges = opr.get_bdy(triangular_cycles, digraph)
        ordered_boundary = opr.ordered_bdy(graph.bdy_nodes, graph.bdy_edges)
        path1 = ordered_boundary[0:randint(2, len(ordered_boundary) - 1)]
        new_adjacency_mat = connect_northeast(graph, path1)
    
    graph.user_matrix = new_adjacency_mat
    graph.matrix = new_adjacency_mat
    graph.cip = find_cips(graph)
    print("Length of CIP: {}".format(len(graph.cip)))
    new_adjacency_mat = add_NESW(graph, new_adjacency_mat, path1)
    graph.matrix = new_adjacency_mat

    # Perform graph contraction
    degrees = cntr.degrees(graph.matrix)
    goodnodes = cntr.goodnodes(graph.matrix, degrees)
    graph.matrix, degrees, goodnodes, cntrs = cntr.contract(
        graph.matrix, goodnodes, degrees)

    # Perform graph expansion
    graph.matrix = exp.basecase(graph.matrix, graph.nodecnt)
    while len(cntrs) != 0:
        graph.matrix = exp.expand(graph.matrix, graph.nodecnt, cntrs)
    
    get_floorplan(graph, -1)

# Function to generate multiple L-shaped floorplans
def multipleLshapedFloorplans(graph, nodes_data):
    # Separating Triangle Elimination
    if (graph.nodecnt - graph.edgecnt + len(opr.get_trngls(graph.matrix)) != 1):
        ptpg_matrices, extra_nodes = st.handle_STs(
            graph.matrix, graph.coordinates, 1)
        graph.matrix = ptpg_matrices[0]
        graph.nodecnt = graph.matrix.shape[0]
        graph.edgecnt = int(np.count_nonzero(graph.matrix == 1) / 2)
        for key in extra_nodes[0]:
            graph.mergednodes.append(key)
            graph.irreg_nodes1.append(extra_nodes[0][key][0])
            graph.irreg_nodes2.append(extra_nodes[0][key][1])
    cip = find_cips(graph)
    if len(cip) > 5:
        return "CIPs greater than 5"
    
    # Find multiple triplets in the graph
    tripletSet = find_multiple_triplet(graph)
    original_nodecnt = graph.nodecnt
    original_matrix = graph.matrix

    # Process each triplet to generate multiple floorplans
    for triplet in tripletSet:
        path1 = find_paths(graph, triplet, cip)
        print("Checking path1", path1)
        new_adjacency_mat = connect_northeast(graph, path1)
        print("Checking new adjacency matrix", new_adjacency_mat)
        graph.user_matrix = new_adjacency_mat
        graph.cip = find_cips(graph)
        new_adjacency_mat = add_NESW(graph, new_adjacency_mat, path1)
        graph.matrix = new_adjacency_mat
        graph.matrix[graph.north][graph.south] = 1
        graph.matrix[graph.south][graph.north] = 1
        print("Checking final graph matrix", graph.matrix)

        # Generate a canonical representation of the graph
        can = canonical()
        can.displayInputGraph(graph.nodecnt, graph.matrix, nodes_data)
        can.runWithArguments(graph.nodecnt, graph.west, graph.south, graph.north, triplet, graph, graph.matrix, cip)
        graph.matrix[graph.north][graph.south] = 0
        graph.matrix[graph.south][graph.north] = 0
        print(can.graph_data['indexToCanOrd'])
        my_rel = Canonical_LShaped.Canonical_L_Shaped(can.graph_data['indexToCanOrd'], graph)
        # graph.rel = my_rel

        # Store the floorplan data
        g = nx.from_numpy_array(graph.matrix, create_using=nx.DiGraph)
        edgeset = g.edges()
        
        new_graph = inputgraph(graph.nodecnt, graph.edgecnt, edgeset, graph.coordinates)
        
        graph.fpcnt += 1
        graph.rel_matrix_list.append(my_rel)
        new_graph.rel_matrix_list = my_rel
        new_graph.mergednodes= []
        new_graph.irreg_nodes1 = []
        new_graph.irreg_nodes2 = []
        new_graph.extranodes= [graph.northeast]
        new_graph.nodecnt_list = graph.nodecnt
        graph.graph_list.append(new_graph)
        
        # Here there might be somethign interesting  because it might involve graph data conversion so look into it
        # graph.fpcnt += 1
        # graph.rel_matrix_list.append(my_rel)
        # graph.mergednodes.append([])
        # graph.irreg_nodes1.append([])
        # graph.irreg_nodes2.append([])
        # graph.extranodes.append([graph.northeast])
        # graph.nodecnt_list.append(graph.nodecnt)

        # Restore the original graph matrix and node count for the next iteration
        graph.matrix = original_matrix
        graph.nodecnt = original_nodecnt
    
    # Construct the dual graph for each floorplan
    for cnt in range(graph.fpcnt):
        [graph.graph_list[cnt].room_x, graph.graph_list[cnt].room_y, graph.graph_list[cnt].room_width, graph.graph_list[cnt].room_height] = rdg.construct_dual(graph.graph_list[cnt].rel_matrix_list,
                                                                        graph.graph_list[cnt].nodecnt_list,
                                                                        graph.graph_list[cnt].mergednodes,
                                                                        graph.graph_list[cnt].irreg_nodes1)

    print("Check", graph.room_x)

# Function to find multiple triplets in the graph
def find_multiple_triplet(graph):
    H = opr.get_directed(graph.matrix)

    ordered_outer_vertices = opr.ordered_bdy(graph.bdy_nodes, graph.bdy_edges)

    triplet_set = []
    triplet = False
    
    # Identify triplets by traversing the ordered boundary
    for i in range(0, len(ordered_outer_vertices) - 1):
        a = ordered_outer_vertices[i]

        if i < len(ordered_outer_vertices) - 2:
            b = ordered_outer_vertices[i + 1]
            c = ordered_outer_vertices[i + 2]
        elif i == len(ordered_outer_vertices) - 2:
            b = ordered_outer_vertices[i + 1]
            c = ordered_outer_vertices[0]
        else:
            b = ordered_outer_vertices[0]
            c = ordered_outer_vertices[1]

        # Check if a and c are not directly connected
        if (a, c) in H.edges():
            continue

        triplet = True

        # Ensure there is no intermediate vertex connecting a and c
        for v in H.nodes():
            if v != b and ((a, v) in H.edges() and (v, c) in H.edges):
                triplet = False
                break

        # If a valid triplet is found, add it to the triplet set
        if triplet:
            triplet_set.append((a, b, c))

    return triplet_set
def find_cips(graph):
    # Find triangular cycles in the graph
    triangular_cycles = opr.get_trngls(graph.matrix)
    
    # Create a directed version of the graph
    digraph = opr.get_directed(graph.matrix)
    
    # Get boundary nodes and edges from triangular cycles and directed graph
    graph.bdy_nodes, graph.bdy_edges = opr.get_bdy(triangular_cycles, digraph)
    
    # Get shortcuts based on boundary nodes and edges
    shortcuts = sr.get_shortcut(graph.matrix, graph.bdy_nodes, graph.bdy_edges)
    
    # Order the boundary nodes
    ordered_boundary = opr.ordered_bdy(graph.bdy_nodes, graph.bdy_edges)

    # Find CIPs (Critical Infrastructure Points) using ordered boundary and shortcuts
    cips = cip.find_cip(ordered_boundary, shortcuts)
    
    return cips


def find_triplet(graph):
    # Get directed graph
    H = opr.get_directed(graph.matrix)

    # Order the outer vertices of the graph boundary
    ordered_outer_vertices = opr.ordered_bdy(graph.bdy_nodes, graph.bdy_edges)

    triplet = False

    # Iterate through possible triplets in the ordered boundary
    for i in range(0, len(ordered_outer_vertices) - 1):
        a = ordered_outer_vertices[i]

        # Determine triplet (a, b, c) considering cyclic ordering
        if i < len(ordered_outer_vertices) - 2:
            b = ordered_outer_vertices[i + 1]
            c = ordered_outer_vertices[i + 2]
        elif i == len(ordered_outer_vertices) - 2:
            b = ordered_outer_vertices[i + 1]
            c = ordered_outer_vertices[0]
        else:
            b = ordered_outer_vertices[0]
            c = ordered_outer_vertices[1]

        # Check if edge (a, c) exists in the directed graph
        if (a, c) in H.edges():
            continue

        triplet = True

        # Verify if there's another vertex v that connects a to c via b
        for v in H.nodes():
            if v != b and ((a, v) in H.edges() and (v, c) in H.edges()):
                triplet = False
                break

        if triplet:
            break

    if triplet:
        print("=====triplet=====")
        print(a, b, c)
        return (a, b, c)
    else:
        return -1


def find_paths(graph, triplet, cip):
    a = triplet[0]
    b = triplet[1]
    c = triplet[2]

    # Find triangular cycles and directed graph
    triangular_cycles = opr.get_trngls(graph.matrix)
    digraph = opr.get_directed(graph.matrix)
    
    # Get boundary nodes and edges from triangular cycles and directed graph
    graph.bdy_nodes, graph.bdy_edges = opr.get_bdy(triangular_cycles, digraph)
    
    # Order the boundary nodes
    ordered_boundary = opr.ordered_bdy(graph.bdy_nodes, graph.bdy_edges)
    
    # Arrange the outer boundary in clockwise order starting from node 'a'
    clockwise_outer_boundary = []

    for i in range(len(ordered_boundary)):
        if ordered_boundary[i] == a:
            clockwise_outer_boundary.extend(ordered_boundary[i:])
            break

    clockwise_outer_boundary.extend(ordered_boundary[:i])

    print("checking for clocking outer boundary", clockwise_outer_boundary)

    tripletInCip = False
    
    # Check if the triplet (a, b, c) is present in any CIP
    for arr in cip:
        if a in arr and b in arr and c in arr:
            tripletInCip = True
            break

    print("checking triplet in CIP value", tripletInCip)

    path1 = []
    path1.append(a)
    path1.append(b)
    path1.append(c)

    possible_corners_in_cips = []

    # Gather all possible corner points from the CIPs
    for corner in cip:
        possible_corners_in_cips.extend(corner[1:len(corner) - 1])

    print("=====possible_corners======")
    print(possible_corners_in_cips)

    # Determine path1 based on specific conditions
    if len(cip) == 5 and not tripletInCip:
        for i in range(2, len(clockwise_outer_boundary)):
            print(i, " ===== ", clockwise_outer_boundary[i])
            if clockwise_outer_boundary[i] in possible_corners_in_cips:
                path1.extend(clockwise_outer_boundary[3:i + 1])
                print("checking for path1 1", path1)
                break

        if clockwise_outer_boundary[0] not in possible_corners_in_cips:
            for i in range(len(clockwise_outer_boundary) - 1, 2, -1):
                print("i", i)
                if clockwise_outer_boundary[i] in possible_corners_in_cips:
                    for j in range(i, len(clockwise_outer_boundary)):
                        path1.insert(0, clockwise_outer_boundary[len(clockwise_outer_boundary) - 1])
                        print("checking for path1 2", path1)
                    break

    if len(cip) == 4:
        for i in range(2, len(clockwise_outer_boundary)):
            print(i, " ===== ", clockwise_outer_boundary[i])
            if clockwise_outer_boundary[i] in possible_corners_in_cips:
                path1.extend(clockwise_outer_boundary[3:i + 1])
                break

    print("PATH 1 =============")
    print(path1)
    
    # Check additional conditions for path1
    if path1_conditions(graph, path1, triplet):
        return path1


def path1_conditions(graph, path1, triplet):
    a = triplet[0]
    b = triplet[1]
    c = triplet[2]
    flag = True

    # Find indices for vertices a, b, c in path1
    for i in range(0, len(path1)):
        if path1[i] == a:
            indA = i
            indB = i + 1
            indC = i + 2
            break

    leftOfB = []
    rightofB = []

    # Initialize arrays for left and right of vertex b
    for i in range(0, graph.nodecnt):
        leftOfB.append(0)
        rightofB.append(0)

    # Mark nodes and their neighbors to the left of b
    for i in range(0, indB):
        leftOfB[path1[i]] = 1
        for j in range(0, graph.nodecnt):
            if graph.matrix[path1[i]][j] == 1:
                leftOfB[j] = 1

    # Mark nodes and their neighbors to the right of b
    for i in range(indC, len(path1)):
        rightofB[path1[i]] = 1
        for j in range(0, graph.nodecnt):
            if graph.matrix[path1[i]][j] == 1:
                rightofB[j] = 1

    # Check for nodes that have connections on both sides of b
    for i in range(0, graph.nodecnt):
        if leftOfB[i] == 1 and rightofB[i] == 1:
            flag = True
            break

    return flag


def connect_northeast(graph, path1):
    # Increment node count for the graph
    graph.original_node_count = graph.nodecnt

    # Add northeast node and increment node count
    graph.northeast = graph.nodecnt
    graph.nodecnt += 1

    # Create a new adjacency matrix with updated node count
    new_adjacency_matrix = new_matrix(graph, graph.nodecnt)

    # Add edges between path1 vertices and the northeast node
    add_edges(graph, new_adjacency_matrix, path1, graph.northeast)

    print("======New Adj Mat=======")
    print(new_adjacency_matrix)

    return new_adjacency_matrix


def add_edges(graph, matrix, adj_vertices, new_vertex):
    # Add edges between adjacent vertices and new vertex in the matrix
    for vertex in adj_vertices:
        graph.edgecnt += 1
        matrix[vertex][new_vertex] = 1
        matrix[new_vertex][vertex] = 1


def new_matrix(graph, node_count):
    # Create a new adjacency matrix with specified node count
    new_adjacency_mat = np.zeros([node_count, node_count], int)
    matrix = graph.matrix.copy()
    new_adjacency_mat[0:matrix.shape[0], 0:matrix.shape[1]] = matrix
    return new_adjacency_mat


def boundary_path_single(paths, boundary, corner_points):
    # Function to determine boundary paths based on corners and boundary points
    ne = corner_points[0]
    for path in paths:
        if ne not in path:
            corner_points.append(path[randint(0, len(path) - 1)])
    while len(corner_points) < 4:
        corner_vertex = boundary[randint(0, len(boundary) - 1)]
        while corner_vertex in corner_points:
            corner_vertex = boundary[randint(0, len(boundary) - 1)]
        corner_points.append(corner_vertex)
    count = 0
    corner_points_index = []
    for i in boundary:
        if i in corner_points:
            print("corner points ")
            print(i)
            corner_points_index.append(count)
        count += 1
    boundary_paths = []
    boundary_paths.append(boundary[corner_points_index[0]:corner_points_index[1] + 1])
    boundary_paths.append(boundary[corner_points_index[1]:corner_points_index[2] + 1])
    boundary_paths.append(boundary[corner_points_index[2]:corner_points_index[3] + 1])
    boundary_paths.append(boundary[corner_points_index[3]:len(boundary)] + boundary[0:corner_points_index[0] + 1])

    return boundary_paths


def get_rel(graph, path1):
    # Initialize contraction and degrees
    graph.contraction = []
    degrees = cntr.degrees(graph.matrix)
    
    # Get good nodes for contraction
    goodnodes = cntr.goodnodes(graph.matrix, degrees)
    v, u = cntr.contract(graph.matrix, goodnodes)
    
    # Continue contracting until no more nodes can be contracted
    while v != -1:
        v, u = cntr.contract(graph.matrix, goodnodes)
    
    # Perform base case expansion
    exp.basecase(graph.matrix, graph.nodecnt)
    
    # Expand contracted nodes
    while len(graph.contractions) != 0:
        k = 1
        k = exp.expand(graph.matrix, graph.nodecnt, graph.contractions.pop())

    # If k is 0, revert to original node and edge counts and add NESW connections
    if k == 0:
        graph.nodecnt = graph.node_count_required
        graph.edgecnt = graph.edge_count_required
        new_adjacency_mat = add_NESW(graph, graph.user_matrix, path1)
        graph.matrix = new_adjacency_mat
        get_rel(graph, path1)
    
    print("REL")
    print(graph.matrix)


def get_floorplan(graph, triplet):
    # Add northeast node to extranodes
    graph.extranodes.append(graph.northeast)
    
    # Construct dual to determine floor plan dimensions
    [graph.room_x, graph.room_y, graph.room_width, graph.room_height] = rdg.construct_dual(graph.matrix, graph.nodecnt,
                                                                                           graph.mergednodes,
                                                                                           graph.irreg_nodes1)


def add_NESW(graph, new_adjacency_mat, path1):
    # Set new adjacency matrix
    graph.matrix = new_adjacency_mat
    
    # Get triangular cycles and directed graph
    triangular_cycles = opr.get_trngls(graph.matrix)
    digraph = opr.get_directed(graph.matrix)
    
    # Get boundary nodes and edges from triangular cycles and directed graph
    graph.bdy_nodes, graph.bdy_edges = opr.get_bdy(triangular_cycles, digraph)
    
    # Find CIPs for L-shaped structure
    cips = find_cips_L_shaped(graph)

    # Set required node and edge counts
    graph.node_count_required = graph.nodecnt
    graph.edge_count_required = graph.edgecnt
    
    # Add NESW nodes and edges
    graph.north = graph.nodecnt
    graph.nodecnt += 1
    graph.east = graph.nodecnt
    graph.nodecnt += 1
    graph.south = graph.nodecnt
    graph.nodecnt += 1
    graph.west = graph.nodecnt
    graph.nodecnt += 1

    # Create new adjacency matrix with updated node count
    new_adjacency_matrix = new_matrix(graph, graph.nodecnt)

    # Add edges between CIPs and NESW nodes based on path1
    for i in range(len(cips)):
        if path1[0] in cips[i] and graph.northeast in cips[i]:
            n_cip = i
        if path1[len(path1) - 1] in cips[i] and graph.northeast in cips[i]:
            e_cip = i

    add_edges(graph, new_adjacency_matrix, cips[n_cip], graph.north)
    add_edges(graph, new_adjacency_matrix, cips[e_cip], graph.east)
    add_edges(graph, new_adjacency_matrix, cips[(n_cip + 2) % 4], graph.south)
    add_edges(graph, new_adjacency_matrix, cips[(e_cip + 2) % 4], graph.west)

    # Connect NESW nodes
    connect_news(new_adjacency_matrix, graph)

    print(new_adjacency_matrix)
    print(graph.edgecnt)
    
    return new_adjacency_matrix


def find_cips_L_shaped(graph):
    # Initialize CIPs
    cips = graph.cip
    corner_points = []
    corner_points.append(graph.northeast)
    
    # Check conditions and update CIPs if necessary
    if graph.edgecnt == 3 and graph.nodecnt == 3:
        graph.cip = [[0], [0, 1], [1, 2], [2, 0]]
    else:
        if len(cips) < 4:
            graph.cip = boundary_path_single(news.find_bdy(cips), opr.ordered_bdy(graph.bdy_nodes, graph.bdy_edges),
                                             corner_points)
        else:
            triangular_cycles = opr.get_trngls(graph.matrix)
            digraph = opr.get_directed(graph.matrix)
            graph.bdy_nodes, graph.bdy_edges = opr.get_bdy(triangular_cycles, digraph)
            shortcut = sr.get_shortcut(graph.matrix, graph.bdy_nodes, graph.bdy_edges)
            ordered_boundary = opr.ordered_bdy(graph.bdy_nodes, graph.bdy_edges)
            
            # Remove excess shortcuts
            while len(shortcut) > 4:
                index = randint(0, len(shortcut) - 1)
                sr.remove_shortcut(shortcut[index], graph, graph.rdg_vertices, graph.rdg_vertices2,
                                   graph.to_be_merged_vertices)
                shortcut.pop(index)
            
            # Find CIPs and update them
            cips = cip.find_cip(ordered_boundary, shortcut)
            graph.cip = boundary_path_single(news.find_bdy(cips), opr.ordered_bdy(graph.bdy_nodes, graph.bdy_edges),
                                             corner_points)
    
    # Print and return CIPs
    cips = graph.cip
    print("Cips", cips)
    return cips


def connect_news(matrix, graph):
    # Connect NESW nodes in the matrix
    matrix[graph.north][graph.west] = 1
    matrix[graph.west][graph.north] = 1
    matrix[graph.west][graph.south] = 1
    matrix[graph.south][graph.west] = 1
    matrix[graph.south][graph.east] = 1
    matrix[graph.east][graph.south] = 1
    matrix[graph.east][graph.north] = 1
    matrix[graph.north][graph.east] = 1
