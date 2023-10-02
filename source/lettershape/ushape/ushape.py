from pickle import FALSE, TRUE
from random import randint
#from networkx.algorithms.centrality.betweenness_subset import betweenness_centrality_source
from networkx.algorithms.core import core_number
from networkx.classes import graph
# from LShaped import connect_news, new_matrix
from ...floorplangen import rdg 
from ...boundary import cip  
from ...graphoperations import operations as opr
import numpy as np
from ...boundary import news as news
from ...irregular import shortcutresolver as sr 
from ...floorplangen import contraction as cntr
from ...floorplangen import expansion as exp
# import pythongui.drawing as draw
import copy


def new_matrix(graph, node_count):
    new_adjacency_mat = np.zeros([node_count, node_count], int)
    matrix = graph.matrix.copy()
    new_adjacency_mat[0:matrix.shape[0], 0:matrix.shape[1]] = matrix
    return new_adjacency_mat


def connect_news(matrix, graph):
    matrix[graph.north][graph.west] = 1
    matrix[graph.west][graph.north] = 1
    matrix[graph.west][graph.south] = 1
    matrix[graph.south][graph.west] = 1
    matrix[graph.south][graph.east] = 1
    matrix[graph.east][graph.south] = 1
    matrix[graph.east][graph.north] = 1
    matrix[graph.north][graph.east] = 1


def path_lister(graph, cip):
    triangular_cycles = get_trngls(graph.matrix)
    digraph = get_directed(graph.matrix)
    graph.bdy_nodes, graph.bdy_edges = get_bdy(triangular_cycles, digraph)
    ordered_boundary = ordered_bdy(graph.bdy_nodes, graph.bdy_edges)
    path_list = []
    centre_cip = []
    centre_cip_temp = []
    for i in range(6):
        centre_cip.append(cip[i][1])
    for i in ordered_boundary:
        if i in centre_cip:
            centre_cip_temp.append(i)
    centre_cip = centre_cip_temp
    while ordered_boundary[0] != centre_cip[0]:
        ordered_boundary.insert(0, ordered_boundary.pop())
    first = ordered_boundary[0]
    ordered_boundary.pop(0)
    ordered_boundary.append(first)
    print("ordered vertices sorted", ordered_boundary)
    temp_path = [first]
    for i in ordered_boundary:
        print("val", i)
        temp_path.append(i)
        if i in centre_cip:
            path_list.append(temp_path)
            temp_path = [i]
    return path_list


def UShapedFloorplan(graph):
    cip = find_cips(graph)
    if len(cip) != 6:
        return "cips not equal to 6"
    paths = path_lister(graph, cip)
    path1 = paths[0]
    dummy_graph = copy.deepcopy(graph)
    new_adjacency_mat = connect(dummy_graph, path1)
    newcips = find_cips(dummy_graph)
    if len(newcips) > 4:
        path1 = paths[1]

    new_adjacency_mat = connect(graph, path1)
    graph.cip = find_cips(graph)
    print("sdfasdfsafaew",graph.cip)
    new_adjacency_mat = add_NESW(graph, new_adjacency_mat)
    graph.matrix = new_adjacency_mat
    get_rel(graph, path1)
    get_floorplan(graph)


def get_floorplan(graph):
    graph.extranodes.append(graph.northeast)
    print("here")
    [graph.room_x, graph.room_y, graph.room_width, graph.room_height] = rdg.construct_dual(graph.matrix, graph.nodecnt, graph.mergednodes, graph.irreg_nodes1)


def connect(graph, path1):
    graph.original_node_count = graph.nodecnt
    graph.northeast = graph.nodecnt
    graph.nodecnt += 1

    new_adjacency_matrix = new_matrix(graph, graph.nodecnt)

    add_edges1(graph, new_adjacency_matrix, path1, graph.northeast)

    print("======New Adj Mat=======")
    print(new_adjacency_matrix)

    return new_adjacency_matrix


def add_edges(graph, matrix, adj_vertices, new_vertex):
    for vertex in adj_vertices:
        graph.edgecnt += 1
        matrix[vertex][new_vertex] = 1
        matrix[new_vertex][vertex] = 1


def add_edges1(graph, matrix, adj_vertices1, new_vertex1):
    for vertex in adj_vertices1:
        graph.edgecnt += 1
        matrix[vertex][new_vertex1] = 1
        matrix[new_vertex1][vertex] = 1


def find_cips(graph):
	triangular_cycles = get_trngls(graph.matrix)
	digraph = get_directed(graph.matrix)
	graph.bdy_nodes, graph.bdy_edges = get_bdy(triangular_cycles, digraph)
	shortcuts = get_shortcut(graph.matrix, graph.bdy_nodes, graph.bdy_edges)
	ordered_boundary = ordered_bdy(graph.bdy_nodes, graph.bdy_edges)

	cips = cip.find_cip(ordered_boundary,shortcuts)
	print("====cip====")
	print(cips)
	return cips


def get_rel(graph, path1):
    graph.degrees = degrees(graph.matrix)
    goodnodes = goodnodes(graph.matrix, graph.degrees)
    graph.matrix, graph.degrees, goodnodes, cntrs = contract(graph.matrix, goodnodes, graph.degrees)
    graph.matrix = basecase(graph.matrix, graph.nodecnt)
    while len(cntrs) != 0:
        graph.matrix = expand(graph.matrix, graph.nodecnt, cntrs)

    print("REL")
    print(graph.matrix)


def add_NESW(graph, new_adjacency_mat):
    graph.matrix = new_adjacency_mat
    triangular_cycles = get_trngls(graph.matrix)
    digraph = get_directed(graph.matrix)
    graph.bdy_nodes, graph.bdy_edges = get_bdy(triangular_cycles, digraph)
    
    cips = find_cips_U_shaped(graph)

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

    add_edges(graph, new_adjacency_matrix, cips[0], graph.north)
    add_edges(graph, new_adjacency_matrix, cips[1], graph.east)
    add_edges(graph, new_adjacency_matrix, cips[2], graph.south)
    add_edges(graph, new_adjacency_matrix, cips[3], graph.west)

    connect_news(new_adjacency_matrix, graph)

    print(new_adjacency_matrix)
    print(graph.edgecnt)
    return new_adjacency_matrix


def find_cips_U_shaped(graph):
    cips = find_cips(graph)
    corner_points = []
    graph.cip = boundary_path_single(find_bdy(cips),ordered_bdy(graph.bdy_nodes,graph.bdy_edges), corner_points)
    cips = graph.cip
    return cips


def boundary_path_single(paths, boundary, corner_points):
    for path in paths:
        corner_points.append(path[randint(0, len(path) - 1)])
    while len(corner_points) < 4:
        corner_vertex = boundary[randint(0, len(boundary) - 1)]
        while corner_vertex in corner_points:
            corner_vertex = boundary[randint(0, len(boundary) - 1)]
        corner_points.append(corner_vertex)
    count = 0
    corner_points_index = []
    print("boundary", boundary, corner_points)
    for i in boundary:
        if i in corner_points:
            print("corner points ")
            print(i)
            corner_points_index.append(count)
        count += 1
    boundary_paths = [boundary[corner_points_index[0]:corner_points_index[1] + 1],
                      boundary[corner_points_index[1]:corner_points_index[2] + 1],
                      boundary[corner_points_index[2]:corner_points_index[3] + 1],
                      boundary[corner_points_index[3]:len(boundary)] + boundary[0:corner_points_index[0] + 1]]

    return boundary_paths
