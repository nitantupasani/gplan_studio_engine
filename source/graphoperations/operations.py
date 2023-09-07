"""Graph Theoretical Operations Module

This module allows the user to perform different graph theoretical
operations.

This module contains the following functions:
    * intersection - returns intersection of two lists.
    * list_comparer - checks if there exists an element in list 1
                      whose intersection with list 2 is of given 
                      size.
    * get_directed - returns a directed graph.
    * get_trngls - returns all triangles in the graph.
    * get_bdy - returns outer boundary of the graph.
    * ordered_nbr_label - returns label and the ordered 
                          neighbour of the vertex.
    * ordered_nbr - returns ordered neighbour 
                    of the vertex.
    * order_nbrs - returns ordered neighbours around
                   a given vertex.
    * get_encoded_matrix - returns the encoded matrix of the floorplan.
    * ordered_bdy - returns the ordered boundary.
    * calculate_area - returns area of each room.
"""
import numpy as np
import networkx as nx 


def intersection(lst1, lst2):
    """Returns intersection of two lists.

    Args:
        lst1: A list containing elements of list 1.
        lst2: A list containing elements of list 2.

    Returns:
        lst3: A list containing intersection of elements of list1 and list2.
    """
    lst3 = [value for value in lst1 if value in lst2] 
    return lst3
 
def list_comparer(lst1, lst2, size):
    """Checks if there exists an element in list 2
       whose intersection with list 1 is of given size. 

    Args:
        lst1: A list containing elements of list 1.
        lst2: A list containing elements of list 2.
        size: An integer representing size to be compared.

    Returns:
        boolean: A boolean representing if such an element exists.
    """
    for elem in lst2:
        if(len(intersection(lst1,elem)) == size):
            return True
    return False

def get_directed(matrix):
    """Returns a directed graph of the input adjacency matrix.

    Args:
        matrix: A matrix representing the adjacency matrix of the graph.

    Returns:
        digraph: A NetworkX directed graph of the input adjacency matrix.
    """
    digraph = nx.from_numpy_array(matrix,create_using = nx.DiGraph)
    return digraph

def get_trngls(matrix):
    """Returns all triangular cycles in a graph.

    Args:
        matrix: A matrix representing the adjacency matrix of the graph.

    Returns:
        trngles: A list containing all triangular cycles in the graph.
    """
    nxgraph = nx.from_numpy_array(matrix)
    all_cliques = nx.enumerate_all_cliques(nxgraph)
    trngles = [x for x in all_cliques if len(x) == 3]
    return trngles

def get_bdy(trngls, digraph):
    """Returns outer boundary of the graph.

    Args:
        trngls: A list containing all triangular cycles in the graph.
        digraph: A NetworkX directed graph of the input graph.

    Returns:
        bdy_nodes: A list containing nodes on the outer boundary.
        bdy_edges: A list containing edges on the outer boundary.
    """
    bdy_edges = []
    for edge in digraph.edges:
        count = 0
        for trngl in trngls:
            if edge[0] in trngl and edge[1] in trngl:
                count += 1
        if count == 1:
            bdy_edges.append(edge)
    bdy_nodes = []
    for edge in bdy_edges:
        if edge[0] not in bdy_nodes:
            bdy_nodes.append(edge[0])
        if edge[1] not in bdy_nodes:
            bdy_nodes.append(edge[1])
    return bdy_nodes, bdy_edges

def ordered_nbr_label(matrix, nodecnt, centre, nbr, cw=False):
    """Returns label of ordered neighbour of the vertex.

    Args:
        matrix: A matrix representing the adjacency matrix of the graph.
        nodecnt: An integer representing the node count of the graph.
        centre: An integer representing the vertex.
        nbr: An integer represening neighbour of the vertex.
        cw: A boolean representing direction to move.

    Returns:
        integer: An integer representing label (2 or 3).
        next: An integer representing the ordered neighbour.
    """
    next = ordered_nbr(matrix, nodecnt, centre, nbr, cw)
    if matrix[centre][next] == 2 or matrix[next][centre] == 2:
        return 2,next
    else:
        return 3,next

def ordered_nbr(matrix, nodecnt, centre, nbr, cw=False):
    """Returns ordered neighbour of the vertex.

    Args:
        matrix: A matrix representing the adjacency matrix of the graph.
        nodecnt: An integer representing the node count of the graph.
        centre: An integer representing the vertex.
        nbr: An integer represening neighbour of the vertex.
        cw: A boolean representing direction to move.

    Returns:
        integer: An integer representing ordered neighbour.
    """
    ordered_nbrs = order_nbrs(matrix, nodecnt, centre, cw)
    return ordered_nbrs[(ordered_nbrs.index(nbr) + 1) % len(ordered_nbrs)]

def order_nbrs(matrix, nodecnt, centre, cw=False):
    """Returns neighbour of the vertex in ordered fashion.

    Args:
        graph: An instance of InputGraph class.
        centre: An integer indicating representing the vertex.
        cw: A boolean representing direction to move.

    Returns:
        ord_set: A list representing ordered neighbours of the vertex.
    """  
    vertex_set = np.concatenate([np.where(np.logical_or(matrix[centre] == 2
        ,matrix[centre] == 3))[0]
        ,np.where(np.logical_or(matrix[:, centre] == 2
        ,matrix[:, centre] == 3))[0]]).tolist()
    ord_set = [vertex_set.pop(0)]
    while len(vertex_set) != 0:
        for i in vertex_set:
            if matrix[ord_set[len(ord_set) - 1]][i] != 0 \
                    or matrix[i][ord_set[len(ord_set) - 1]] != 0:
                ord_set.append(i)
                vertex_set.remove(i)
                break
            elif matrix[ord_set[0]][i] != 0 \
            or matrix[i][ord_set[0]] != 0:
                ord_set.insert(0, i)
                vertex_set.remove(i)
                break
    current = 0
    if centre == nodecnt - 2:
        if matrix[nodecnt - 1][ord_set[0]] != 0:
            ord_set.reverse()
    elif centre == nodecnt - 1:
        if matrix[ord_set[0]][nodecnt - 4] != 0:
            ord_set.reverse()
    elif matrix[centre][ord_set[0]] == 2:
        while matrix[centre][ord_set[current]] == 2:
            current += 1
        if matrix[centre][ord_set[current]] == 3:
            ord_set.reverse()
    elif matrix[ord_set[0]][centre] == 3:
        while matrix[ord_set[current]][centre] == 3:
            current += 1
        if matrix[centre][ord_set[current]] == 2:
            ord_set.reverse()
    elif matrix[ord_set[0]][centre] == 2:
        while matrix[ord_set[current]][centre] == 2:
            current += 1
        if matrix[ord_set[current]][centre] == 3:
            ord_set.reverse()
    elif matrix[centre][ord_set[0]] == 3:
        while matrix[centre][ord_set[current]] == 3:
            current += 1
        if matrix[ord_set[current]][centre] == 2:
            ord_set.reverse()
    if cw:
        ord_set.reverse()
    return ord_set

def get_encoded_matrix(nodecnt, room_x, room_y, room_width, room_height):
    """Returns the encoded matrix.

    Args:
        nodecnt: An integer representing the node count of the graph.
        room_x: A list representing the x coordinates of the room.
        room_y: A list representing the y coordinates of the room.
        room_width: A list representing the width of the room.
        room_height: A list representing the height of the room.

    Returns:
        encoded_matrix: A matrix representing the encoded matrix.
    """  

    mat_width = int(max(a + b for a, b in zip(room_x, room_width)))
    mat_height = int(max(a + b for a, b in zip(room_y, room_height)))
    encoded_matrix =  np.zeros((mat_height, mat_width), int)
    room_width_arr = np.array(room_width, dtype='int')
    room_height_arr = np.array(room_height, dtype='int')
    room_x_arr = np.array(room_x, dtype='int')
    room_y_arr = np.array(room_y, dtype='int')
    for node in range(nodecnt):
        for width in range(room_width_arr[node]):
            for height in range(room_height_arr[node]):
                encoded_matrix[room_y_arr[node] + height][room_x_arr[node] + width] = node
    return encoded_matrix

def ordered_bdy(bdy_nodes, bdy_edges):
    """Returns ordered boundary of the input graph.

    Args:
        bdy_nodes: A list containing nodes on the outer boundary.
        bdy_edges: A list containing edges on the outer boundary.

    Returns:
        ordered_bdy: A list containing boundary nodes in circular order.
    """
    ordered_bdy = [bdy_nodes[0]]
    while(len(ordered_bdy) != len(bdy_nodes)):
        temp = ordered_bdy[len(ordered_bdy) - 1]
        for vertex in bdy_nodes:
            if((temp,vertex) in bdy_edges
             and vertex not in ordered_bdy):
                ordered_bdy.append(vertex)
                break
    return ordered_bdy

def calculate_area(nodecnt, room_width, room_height, extranodes, mergednodes, irreg_nodes):
    """Calculates area of the given graph.

    Args:
        nodecnt: An integer repesenting the node count of the graph.
        room_width: A list representing the width of the rooms.
        room_height: A list representing the height of the rooms.
        extranodes: A list representing the extra vertices.
        mergednodes: A list representing nodes to be merged.
        irreg_nodes: A list representing the irregular nodes.

    Returns:
        rooms_area: A list representing the area of the rooms.
    """
    rooms_area = []
    for i in range(nodecnt):
        if room_width[i] == 0 or i in extranodes or i in mergednodes:
            continue
        area = room_width[i] * room_height[i]
        if(i in irreg_nodes):
            merged_node_indices = [j for j, x in enumerate(irreg_nodes) if x == i]
            for idx in merged_node_indices:
                area += room_width[mergednodes[idx]] * room_height[mergednodes[idx]]
        rooms_area.append(round(area,3))
    return rooms_area