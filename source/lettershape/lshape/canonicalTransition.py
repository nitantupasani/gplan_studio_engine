from ...graphoperations.operations import *
import numpy as np
import copy


# step 1: write the output manually for north, east and NE vertices.
# uske baaad algo go brr


def process_edge(node, edge_list):
    # print("processing: ", node, ": ", edge_list)
    min_element = edge_list[0]
    for i in edge_list:
        if i < min_element:
            min_element = i
    while edge_list[-1] != min_element:
        edge_list.insert(0, edge_list.pop())
    final_list = []
    for i in edge_list:
        if i > node:
            final_list.append(i)
    # print("Processed: ", node, ": ", final_list)
    return final_list

def get_edge_order(graph, node, point_order):
    node -=1
    left_point = point_order[0] - 1
    right_point = point_order[-1] -1
    edge_order = [-1, -1]
    curr_node_adjcacencies = graph.matrix[node]
    left_point_adjacencies = graph.matrix[left_point]
    right_point_adjacencies = graph.matrix[right_point]
    for i in range(len(curr_node_adjcacencies)):
        if curr_node_adjcacencies[i] == 1 and left_point_adjacencies[i]==1 and i>node:
            edge_order[0] = i
        if curr_node_adjcacencies[i] == 1 and right_point_adjacencies[i]==1 and i>node:
            edge_order[1] = i
    
    edge_order = [x+1 for x in edge_order]
    return edge_order


def create_canonical_matrix(canonical_order, matrix):
    new_matrix = matrix.copy()
    mat_size = len(canonical_order)
    print("old matrix", matrix)
    for i in range(mat_size):
        for j in range(mat_size):
            new_matrix[canonical_order[i]][canonical_order[j]] = 0
            if matrix[i][j] == 1:
                new_matrix[canonical_order[i]][canonical_order[j]] = 1
    print("new matrix", new_matrix)
    return new_matrix


def Update_Graph(graph, matrix, canonical_order):
    graph.matrix = matrix

    triangular_cycles = get_trngls(graph.matrix)
    digraph = get_directed(graph.matrix)
    graph.bdy_nodes, graph.bdy_edges = get_bdy(triangular_cycles, digraph)
    new_outer_boundary = ordered_bdy(graph.bdy_nodes, graph.bdy_edges)
    wst = canonical_order[graph.west]
    sth = canonical_order[graph.south]
    while not ((new_outer_boundary[0] == wst and new_outer_boundary[-1] == sth) or (
            new_outer_boundary[0] == sth and new_outer_boundary[-1] == wst)):
        new_outer_boundary.insert(0, new_outer_boundary.pop())
    if new_outer_boundary[0] == sth:
        new_outer_boundary.reverse()
    return new_outer_boundary


def Canonical_L_Shaped(canonical_order, graph):
    can_ord_origin = copy.deepcopy(canonical_order)
    canonical_order = (np.ceil(canonical_order)).astype(int) #map from index to its canonical order
    can_ord_final = copy.deepcopy(canonical_order)
    for i in range(len(canonical_order)):
        can_ord_final[canonical_order[i]] = i
    print("my order:", can_ord_final) #map from canonical order to the vertex
    canonical_order = can_ord_final
    adj_matrix = create_canonical_matrix(canonical_order, graph.matrix)
    dummy_graph = copy.deepcopy(graph)
    dummy_graph.matrix = adj_matrix
    triangular_cycles = get_trngls(dummy_graph.matrix)
    digraph = get_directed(dummy_graph.matrix)
    dummy_graph.bdy_nodes, dummy_graph.bdy_edges = get_bdy(triangular_cycles, digraph)
    outer_boundary = ordered_bdy(dummy_graph.bdy_nodes, dummy_graph.bdy_edges)
    dummy_graph_constant = copy.deepcopy(dummy_graph)
    print("old outer boundary", outer_boundary)
    basis_edge = []
    point_order = []
    edge_order = []

    # taking care of every node
    n_cnt = dummy_graph.nodecnt
    n_cnt_constant = n_cnt
    curr_basis = []
    while n_cnt > 3:
        for i in range(n_cnt):  # this takes care of basis edge for max node IE north
            if adj_matrix[n_cnt - 1][i] == 1:
                basis_edge.append([i + 1, n_cnt])
                curr_basis = [i + 1, n_cnt]
                break

        adj_n_cnt = adj_matrix[n_cnt - 1] #storing adjacencies of vertex with n_cnt
        adj_matrix = np.delete(adj_matrix, n_cnt - 1, axis=0)
        adj_matrix = np.delete(adj_matrix, n_cnt - 1, axis=1)

        new_outer_boundary = Update_Graph(dummy_graph, adj_matrix, canonical_order)

        curr_pnt_ord = []
        for i in new_outer_boundary:
            if adj_n_cnt[i] == 1:
                curr_pnt_ord.append(i)
        curr_pnt_ord = [x + 1 for x in curr_pnt_ord]
        point_order.append(curr_pnt_ord)

        # Get positions of nodes. First 3 are trivial. For rest of nodes use any 2 nodes??
        if n_cnt == n_cnt_constant:
            curr_edge = []
        elif n_cnt == n_cnt_constant - 1:
            curr_edge = [n_cnt_constant]
        elif n_cnt == n_cnt_constant - 2:
            curr_edge = [n_cnt_constant, n_cnt_constant - 1]
        else:
            curr_edge = get_edge_order(dummy_graph_constant, n_cnt, curr_pnt_ord)
        edge_order.append(curr_edge)
        # print("removed last node:", adj_matrix)
        # print("new outer boundary", new_outer_boundary)

        # print("After Itr: ", n_cnt, basis_edge, point_order, edge_order)
        # print(n_cnt, '\t\t', curr_basis, '\t\t', curr_pnt_ord, '\t\t', curr_edge)
        n_cnt = n_cnt - 1  # or n_cnt = n_cnt - 1
    basis_edge.append([1, 3])
    basis_edge.append([1, 2])
    point_order.append([1, 2])
    point_order.append([1])
    edge_order.append(get_edge_order(dummy_graph_constant, 3, [1, 2]))
    edge_order.append([3])
    
    for i in basis_edge:
        i[0] = i[0] - 1
        i[1] = i[1] - 1
    for i in point_order:
        for j in range(len(i)):
            i[j] = i[j] - 1
    for i in edge_order:
        for j in range(len(i)):
            i[j] = i[j] - 1
    print("Finals: ", basis_edge, point_order, edge_order)

    for i in range(len(basis_edge)):
        print(len(basis_edge) - i, '\t\t', basis_edge[i], '\t\t', point_order[i], '\t\t', edge_order[i])

    print("Added vertices", graph.north, canonical_order[graph.north], graph.west, canonical_order[graph.west],
          graph.south, canonical_order[graph.south], graph.east, canonical_order[graph.east])

    
    left_edges, right_edges = calculateEdges(basis_edge, point_order, edge_order, can_ord_origin)
    rel = generate_rel(graph, left_edges, right_edges)
    return rel


def calculateEdges(basis_edge, point_order, edge_order, can_ord_origin):
    right_edges = []
    left_edges = []
    numberOfVertices = len(basis_edge)
    print("checking order: ", edge_order)
    print("num count: ", numberOfVertices)
    for i in range(2, len(edge_order)):
        left_edge = [numberOfVertices - i, edge_order[i][0]]
        right_edge = [numberOfVertices - i, edge_order[i][len(edge_order[i]) - 1]]
        left_edges.append(left_edge)
        if(left_edge[1]!=right_edge[1]):
            right_edges.append(right_edge)
    for i in range(0, len(basis_edge)):
        x = basis_edge[i][0]
        if x == point_order[i][0]:
            right_edges.append(copy.deepcopy(basis_edge[i]))
        else:
            left_edges.append(copy.deepcopy(basis_edge[i]))

    print("left edges", left_edges)
    print("right edges", right_edges)

    for i in left_edges:
        i[0] = int(can_ord_origin[i[0]])
        i[1] = int(can_ord_origin[i[1]])
    for i in right_edges:
        i[0] = int(can_ord_origin[i[0]])
        i[1] = int(can_ord_origin[i[1]])
    print("left edges", left_edges)
    print("right edges", right_edges)
    return left_edges, right_edges


def generate_rel(graph, left_edges, right_edges):
    rel = copy.deepcopy(graph.matrix)
    numberOfVertices = len(graph.matrix[0])
    for edge in left_edges:
        if edge[0] > numberOfVertices - 5 and edge[1] > numberOfVertices - 5:
            print("ignored: ", edge[0], edge[1])
            continue
        rel[edge[0]][edge[1]] = 2
        rel[edge[1]][edge[0]] = 0

    for edge in right_edges:
        if edge[0] > numberOfVertices - 5 and edge[1] > numberOfVertices - 5:
            print("ignored: ", edge[0], edge[1])
            continue
        rel[edge[0]][edge[1]] = 3
        rel[edge[1]][edge[0]] = 0

    print("rel", rel)
    return rel
