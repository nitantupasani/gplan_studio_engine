from pickle import FALSE, TRUE
from random import randint
#from networkx.algorithms.centrality.betweenness_subset import betweenness_centrality_source
from networkx.algorithms.core import core_number
from networkx.classes import graph


from ..floorplangen import rdg 
from ..boundary import cip  
from ..graphoperations import operations as opr
import numpy as np
from ..boundary import news as news
from ..irregular import shortcutresolver as sr 
from ..floorplangen import contraction as cntr
from ..floorplangen import expansion as exp
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
    triangular_cycles = opr.get_trngls(graph.matrix)
    digraph = opr.get_directed(graph.matrix)
    graph.bdy_nodes, graph.bdy_edges = opr.get_bdy(triangular_cycles, digraph)
    ordered_boundary = opr.ordered_bdy(graph.bdy_nodes, graph.bdy_edges)
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
    temp_path = [first]
    for i in ordered_boundary:
        temp_path.append(i)
        if i in centre_cip:
            path_list.append(temp_path)
            temp_path = [i]
    return path_list


def StaircaseShapedFloorplan(graph): 
    cip = find_cips(graph)
    if len(cip) != 6:
        return "cips not equal to 6"
    paths = path_lister(graph, cip)
    path1 = paths[1]
    new_adjacency_mat = connect(graph, path1)
    graph.matrix = new_adjacency_mat
    path2 = paths[0]
    path2.append(graph.northeast)
    new_adjacency_mat = connect1(graph, path2)
    graph.cip = find_cips(graph)
    new_adjacency_mat = add_NESW(graph, new_adjacency_mat)
    graph.matrix = new_adjacency_mat
    get_rel(graph)
    get_floorplan(graph)

def get_floorplan(graph):
    graph.extranodes.append(graph.northeast)
    graph.extranodes.append(graph.northwest)
    [graph.room_x, graph.room_y, graph.room_width, graph.room_height] = rdg.construct_dual(graph.matrix, graph.nodecnt, graph.mergednodes, graph.irreg_nodes1)


def connect(graph, path1):
    graph.original_node_count = graph.nodecnt
    graph.northeast = graph.nodecnt
    graph.nodecnt += 1

    new_adjacency_matrix = new_matrix(graph, graph.nodecnt)
    add_edges(graph, new_adjacency_matrix, path1, graph.northeast)
    return new_adjacency_matrix

def connect1(graph, path1):
    graph.original_node_count = graph.nodecnt
    graph.northwest = graph.nodecnt
    graph.nodecnt += 1
    new_adjacency_matrix = new_matrix(graph, graph.nodecnt)
    add_edges(graph, new_adjacency_matrix, path1, graph.northwest)
    return new_adjacency_matrix


def add_edges(graph, matrix, adj_vertices, new_vertex):
    for vertex in adj_vertices:
        graph.edgecnt += 1
        matrix[vertex][new_vertex] = 1
        matrix[new_vertex][vertex] = 1


def find_cips(graph):
	triangular_cycles = opr.get_trngls(graph.matrix)
	digraph = opr.get_directed(graph.matrix)
	graph.bdy_nodes, graph.bdy_edges = opr.get_bdy(triangular_cycles, digraph)
	shortcuts = sr.get_shortcut(graph.matrix, graph.bdy_nodes, graph.bdy_edges)
	ordered_boundary = opr.ordered_bdy(graph.bdy_nodes, graph.bdy_edges)

	cips = cip.find_cip(ordered_boundary,shortcuts)
	return cips


def get_rel(graph):
    graph.degrees = cntr.degrees(graph.matrix)
    goodnodes = cntr.goodnodes(graph.matrix, graph.degrees)
    graph.matrix, graph.degrees, goodnodes, cntrs = cntr.contract(graph.matrix, goodnodes, graph.degrees)
    graph.matrix = exp.basecase(graph.matrix, graph.nodecnt)
    while len(cntrs) != 0:
        graph.matrix = exp.expand(graph.matrix, graph.nodecnt, cntrs)


def add_NESW(graph, new_adjacency_mat):
    graph.matrix = new_adjacency_mat
    triangular_cycles = opr.get_trngls(graph.matrix)
    digraph = opr.get_directed(graph.matrix)
    graph.bdy_nodes, graph.bdy_edges = opr.get_bdy(triangular_cycles, digraph)
    cips = find_cips_staircase_shaped(graph)


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

    return new_adjacency_matrix


def find_cips_staircase_shaped(graph):
    cips = find_cips(graph)
    corner_points = []
    corner_points.append(graph.northeast)
    graph.cip = boundary_path_single(news.find_bdy(cips),opr.ordered_bdy(graph.bdy_nodes,graph.bdy_edges), corner_points)
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
    for i in boundary:
        if i in corner_points:
            corner_points_index.append(count)
        count += 1
    boundary_paths = [boundary[corner_points_index[0]:corner_points_index[1] + 1],
                      boundary[corner_points_index[1]:corner_points_index[2] + 1],
                      boundary[corner_points_index[2]:corner_points_index[3] + 1],
                      boundary[corner_points_index[3]:len(boundary)] + boundary[0:corner_points_index[0] + 1]]

    return boundary_paths
