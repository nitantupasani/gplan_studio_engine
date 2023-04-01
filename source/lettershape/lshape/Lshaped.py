from pickle import FALSE, TRUE
from random import randint, triangular
from networkx.algorithms.centrality.betweenness_subset import betweenness_centrality_source
from networkx.algorithms.core import core_number
from networkx.classes import graph

from source.floorplangen import rdg
from source.lettershape.lshape.modifiedCanonical import canonical
import source.boundary.cip as cip
import source.graphoperations.operations as opr
import numpy as np
import source.boundary.news as news
import source.irregular.shortcutresolver as sr
import source.floorplangen.contraction as cntr
import source.floorplangen.expansion as exp
import source.lettershape.lshape.canonicalTransition as Canonical_LShaped
import pythongui.drawing as draw


# import ptpg
# import flip

# L-shaped function is called from the ptpg file. then the order of execution is:
# CIP
# Triplet
# Paths - conditions 
# Northeast
# Rel - conditions
# Flipping
# Draw

def LShapedFloorplan(graph, nodes_data):
    cip = find_cips(graph)
    if len(cip) > 5:
        return "cips greater than 5"
    print("len of cip {}".format(len(cip)))
    triplet = find_triplet(graph)
    path1 = find_paths(graph, triplet, cip)
    print("checking path1", path1)
    new_adjacency_mat = connect_northeast(graph, path1)
    print("checking new_adjacency_matrix", new_adjacency_mat)
    graph.user_matrix = new_adjacency_mat
    graph.cip = find_cips(graph)
    print("len of cip {}".format(len(graph.cip)))
    new_adjacency_mat = add_NESW(graph, new_adjacency_mat, path1)
    graph.matrix = new_adjacency_mat
    graph.matrix[graph.north][graph.south] = 1
    graph.matrix[graph.south][graph.north] = 1
    print("checking final graph.matrix ", graph.matrix)

    can = canonical()
    can.displayInputGraph(graph.nodecnt, graph.matrix, nodes_data)
    can.runWithArguments(graph.nodecnt, graph.west, graph.south, graph.north, triplet, graph, graph.matrix,cip)
    graph.matrix[graph.north][graph.south] = 0
    graph.matrix[graph.south][graph.north] = 0
    print(can.graph_data['indexToCanOrd'])
    my_rel = Canonical_LShaped.Canonical_L_Shaped(can.graph_data['indexToCanOrd'], graph, nodes_data, triplet)
    graph.matrix = my_rel
    get_floorplan(graph, triplet)


def find_cips(graph):
    triangular_cycles = opr.get_trngls(graph.matrix)
    digraph = opr.get_directed(graph.matrix)
    graph.bdy_nodes, graph.bdy_edges = opr.get_bdy(triangular_cycles, digraph)
    shortcuts = sr.get_shortcut(graph.matrix, graph.bdy_nodes, graph.bdy_edges)
    ordered_boundary = opr.ordered_bdy(graph.bdy_nodes, graph.bdy_edges)

    cips = cip.find_cip(ordered_boundary, shortcuts)
    return cips


def find_triplet(graph):
    H = opr.get_directed(graph.matrix)

    ordered_outer_vertices = opr.ordered_bdy(graph.bdy_nodes, graph.bdy_edges)

    triplet = False

    for i in range(0, len(ordered_outer_vertices) - 1):

        a = ordered_outer_vertices[i]

        if (i < len(ordered_outer_vertices) - 2):
            b = ordered_outer_vertices[i + 1]
            c = ordered_outer_vertices[i + 2]

        elif (i == len(ordered_outer_vertices) - 2):
            b = ordered_outer_vertices[i + 1]
            c = ordered_outer_vertices[0]

        else:
            b = ordered_outer_vertices[0]
            c = ordered_outer_vertices[1]

        if (a, c) in H.edges():
            continue

        triplet = True

        for v in H.nodes():
            if v != b and ((a, v) in H.edges() and (v, c) in H.edges):
                triplet = False
                break

        if (triplet == True):
            break

    if (triplet):
        print("=====triplet=====")
        print(a, b, c)
        return (a, b, c)
    else:
        return -1


def find_paths(graph, triplet, cip):
    a = triplet[0]
    b = triplet[1]
    c = triplet[2]

    triangular_cycles = opr.get_trngls(graph.matrix)
    digraph = opr.get_directed(graph.matrix)
    graph.bdy_nodes, graph.bdy_edges = opr.get_bdy(triangular_cycles, digraph)
    ordered_boundary = opr.ordered_bdy(graph.bdy_nodes, graph.bdy_edges)
    
    clockwise_outer_boundary = []

    for i in range(len(ordered_boundary)):
        if ordered_boundary[i] == a:
            clockwise_outer_boundary.extend(ordered_boundary[i:])
            break

    clockwise_outer_boundary.extend(ordered_boundary[:i])

    print("checking for clocking outer boundary", clockwise_outer_boundary)

    tripletInCip = False
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

    for corner in cip:
        possible_corners_in_cips.extend(corner[1:len(corner) - 1])

    print("=====possible_corners======")
    print(possible_corners_in_cips)

    if len(cip) == 5 and tripletInCip == False:
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
    if (path1_conditions(graph, path1, triplet)):
        return path1


def path1_conditions(graph, path1, triplet):
    a = triplet[0]
    b = triplet[1]
    c = triplet[2]
    flag = True

    for i in range(0, len(path1)):
        if (path1[i] == a):
            indA = i
            indB = i + 1
            indC = i + 2
            break

    leftOfB = []
    rightofB = []

    for i in range(0, graph.nodecnt):
        leftOfB.append(0)
        rightofB.append(0)

    for i in range(0, indB):
        leftOfB[path1[i]] = 1
        for j in range(0, graph.nodecnt):
            if graph.matrix[path1[i]][j] == 1:
                leftOfB[j] = 1

    for i in range(indC, len(path1)):
        rightofB[path1[i]] = 1
        for j in range(0, graph.nodecnt):
            if graph.matrix[path1[i]][j] == 1:
                rightofB[j] = 1

    for i in range(0, graph.nodecnt):
        if leftOfB[i] == 1 and rightofB == 1:
            flag = True
            break

    return flag


def connect_northeast(graph, path1):
    graph.original_node_count = graph.nodecnt

    graph.northeast = graph.nodecnt
    graph.nodecnt += 1

    new_adjacency_matrix = new_matrix(graph, graph.nodecnt)

    add_edges(graph, new_adjacency_matrix, path1, graph.northeast)

    print("======New Adj Mat=======")
    print(new_adjacency_matrix)

    return new_adjacency_matrix


def add_edges(graph, matrix, adj_vertices, new_vertex):
    for vertex in adj_vertices:
        graph.edgecnt += 1
        matrix[vertex][new_vertex] = 1
        matrix[new_vertex][vertex] = 1


def new_matrix(graph, node_count):
    new_adjacency_mat = np.zeros([node_count, node_count], int)
    matrix = graph.matrix.copy()
    new_adjacency_mat[0:matrix.shape[0], 0:matrix.shape[1]] = matrix
    return new_adjacency_mat


def boundary_path_single(paths, boundary, corner_points):
    for path in paths:
        corner_points.append(path[randint(0, len(path) - 1)])
    while (len(corner_points) < 4):
        corner_vertex = boundary[randint(0, len(boundary) - 1)]
        while (corner_vertex in corner_points):
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
    graph.contraction = []
    degrees = cntr.degrees(graph.matrix)
    goodnodes = cntr.goodnodes(graph.matrix, degrees)
    v, u = cntr.contract(graph.matrix, goodnodes, degrees)
    while v != -1:
        v, u = cntr.contract(graph.matrix, goodnodes, degrees)
    exp.basecase(graph.matrix, graph.nodecnt)
    while len(graph.contractions) != 0:
        k = 1
        k = exp.expand(graph.matrix, graph.nodecnt, graph.contractions.pop())

    if (k == 0):
        graph.nodecnt = graph.node_count_required
        graph.edgecnt = graph.edge_count_required
        new_adjacency_mat = add_NESW(graph, graph.user_matrix, path1)
        graph.matrix = new_adjacency_mat
        get_rel(graph, path1)
    print("REL")
    print(graph.matrix)


def get_floorplan(graph, triplet):
    a = triplet[0]
    b = triplet[1]
    c = triplet[2]
    b_ne = graph.matrix[b][graph.northeast]

    graph.extranodes.append(graph.northeast)
    print("here")
    [graph.room_x, graph.room_y, graph.room_width, graph.room_height] = rdg.construct_dual(graph.matrix, graph.nodecnt,
                                                                                           graph.mergednodes,
                                                                                           graph.irreg_nodes1)


def add_NESW(graph, new_adjacency_mat, path1):
    graph.matrix = new_adjacency_mat
    # graph.triangles = opr.get_all_triangles(graph)
    # graph.outer_vertices, graph.outer_boundary = opr.get_outer_boundary_vertices(graph)
    triangular_cycles = opr.get_trngls(graph.matrix)
    digraph = opr.get_directed(graph.matrix)
    graph.bdy_nodes, graph.bdy_edges = opr.get_bdy(triangular_cycles, digraph)
    cips = find_cips_L_shaped(graph)

    graph.node_count_required = graph.nodecnt
    graph.edge_count_required = graph.edgecnt
    graph.north = graph.nodecnt
    graph.nodecnt += 1
    graph.east = graph.nodecnt
    graph.nodecnt += 1
    graph.south = graph.nodecnt
    graph.nodecnt += 1
    graph.west = graph.nodecnt
    graph.nodecnt += 1

    new_adjacency_matrix = new_matrix(graph, graph.nodecnt)

    for i in range(len(cips)):
        if (path1[0] in cips[i] and graph.northeast in cips[i]):
            n_cip = i
        if (path1[len(path1) - 1] in cips[i] and graph.northeast in cips[i]):
            e_cip = i

    add_edges(graph, new_adjacency_matrix, cips[n_cip], graph.north)
    add_edges(graph, new_adjacency_matrix, cips[e_cip], graph.east)
    add_edges(graph, new_adjacency_matrix, cips[(n_cip + 2) % 4], graph.south)
    add_edges(graph, new_adjacency_matrix, cips[(e_cip + 2) % 4], graph.west)

    connect_news(new_adjacency_matrix, graph)

    print(new_adjacency_matrix)
    print(graph.edgecnt)
    return new_adjacency_matrix


def find_cips_L_shaped(graph):
    cips = graph.cip
    corner_points = []
    corner_points.append(graph.northeast)
    if (graph.edgecnt == 3 and graph.nodecnt == 3):
        graph.cip = [[0], [0, 1], [1, 2], [2, 0]]
    else:
        if (len(cips) < 4):
            graph.cip = boundary_path_single(news.find_bdy(cips), opr.ordered_bdy(graph.bdy_nodes, graph.bdy_edges),
                                             corner_points)
        else:
            triangular_cycles = opr.get_trngls(graph.matrix)
            digraph = opr.get_directed(graph.matrix)
            graph.bdy_nodes, graph.bdy_edges = opr.get_bdy(triangular_cycles, digraph)
            shortcut = sr.get_shortcut(graph.matrix, graph.bdy_nodes, graph.bdy_edges)
            ordered_boundary = opr.ordered_bdy(graph.bdy_nodes, graph.bdy_edges)
            while (len(shortcut) > 4):
                index = randint(0, len(shortcut) - 1)
                sr.remove_shortcut(shortcut[index], graph, graph.rdg_vertices, graph.rdg_vertices2,
                                   graph.to_be_merged_vertices)
                shortcut.pop(index)
            cips = cip.find_cip(ordered_boundary,shortcut)
            graph.cip = boundary_path_single(news.find_bdy(cips), opr.ordered_bdy(graph.bdy_nodes, graph.bdy_edges),
                                             corner_points)
    cips = graph.cip
    print("Cips", cips)
    return cips


def connect_news(matrix, graph):
    matrix[graph.north][graph.west] = 1
    matrix[graph.west][graph.north] = 1
    matrix[graph.west][graph.south] = 1
    matrix[graph.south][graph.west] = 1
    matrix[graph.south][graph.east] = 1
    matrix[graph.east][graph.south] = 1
    matrix[graph.east][graph.north] = 1
    matrix[graph.north][graph.east] = 1
