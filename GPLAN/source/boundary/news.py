"""North-East-West-South (NEWS) Module

This module allows user to do 4-completion (refer Documentation) of the
input graph and add four exterior vertices.

This module contains the following functions:

    * find_bdy - returns cip paths for the graph.
    * bdy_path - returns boundary paths for the graph.
    * find_multiple_boundary - returns multiple boundaries for the graph.
    * multiple_corners - returns multiple corner points for the graph.
    * all_boundaries - returns all combination of multiple corner points for the graph.
    * news_edges - connects given cip to given vertex.
    * connect_news - connects exterior vertices to each other.
    * add_news - adds north, east, west and south vertices.
"""
import itertools
import numpy as np
from random import randint

def find_bdy(cip):
    """Returns cip paths in the input graph.

    Args:
        cip: A list containing cips of the input graph.

    Returns:
        paths: A list containing cip paths of the graph.
    """
    paths = []
    for path in cip:
        paths.append(path[1:len(path)-1])
    return paths

def bdy_path(paths, bdy):
    """Returns boundary paths in the input graph.

    Args:
        paths: A list containing cip paths of the graph.
        bdy: A list containing boundary of the graph

    Returns:
        bdy_paths: A list containing boundary paths.
    """
    corner_points = []
    for path in paths:
        corner_points.append(path[randint(0, len(path)-1)]);
    while(len(corner_points) < 4):
        corner_vertex = bdy[randint(0, len(bdy) - 1)];
        while(corner_vertex in corner_points):
            corner_vertex = bdy[randint(0, len(bdy) - 1)];
        corner_points.append(corner_vertex)
    count = 0
    corner_points_index = []
    for node in bdy:
        if node in corner_points:
            corner_points_index.append(count)
        count += 1
    bdy_paths = []
    bdy_paths.append(bdy[corner_points_index[0]:corner_points_index[1] + 1])
    bdy_paths.append(bdy[corner_points_index[1]:corner_points_index[2] + 1])
    bdy_paths.append(bdy[corner_points_index[2]:corner_points_index[3] + 1])
    bdy_paths.append(bdy[corner_points_index[3]:len(bdy)]+ bdy[0:corner_points_index[0] + 1])

    return bdy_paths

def find_multiple_boundary(corner_points, boundary):
    """Returns multiple boundaries in the input graph.

    Args:
        corner_points: A list containing different corner points in the graph.
        bdy: A list containing outer boundary of the graph.

    Returns:
        bdy_paths: A list containing boundary paths.
    """
    result = []
    for corner_point in corner_points:
        count = 0
        corner_points_index = []
        for i  in boundary:
            if i in corner_point:
                if(corner_point.count(i) == 2):
                    corner_points_index.append(count)
                corner_points_index.append(count)
            count += 1
        boundary_paths = []
        boundary_paths.append(boundary[corner_points_index[0]:corner_points_index[1] + 1])
        boundary_paths.append(boundary[corner_points_index[1]:corner_points_index[2] + 1])
        boundary_paths.append(boundary[corner_points_index[2]:corner_points_index[3] + 1])
        boundary_paths.append(boundary[corner_points_index[3]:len(boundary)]+ boundary[0:corner_points_index[0] + 1])
        result.append(boundary_paths)
    return result

def multiple_corners(paths):
    """Returns multiple corner points in the input graph.

    Args:
        paths: A list containing cip paths.

    Returns:
        multiple_corner_points: A list containing multiple corner points.
    """
    n = len(paths)
    indices = [0 for i in range(n)]
    multiple_corner_points = []
    while(1):
        temp =[]
        for i in range(n):
            temp.append(paths[i][indices[i]])
        multiple_corner_points.append(temp)
        next = n - 1
        while(next >=0 and indices[next] + 1 >= len(paths[next])):
            next -= 1
        if(next < 0):
            return multiple_corner_points
        indices[next] += 1
        for i in range(next + 1, n):
            indices[i] = 0

def all_boundaries(paths, boundary):
    """Returns all combination of multiple corner points in the input graph.

    Args:
        paths: A list containing multiple corner points.
        boundary: A list containing the outer boundary of the graph.

    Returns:
        paths: A list containing all combinations of corner points.
    """
    result = []
    if(len(paths[0]) == 3):
        for path in paths:
            n = 4 - len(path);
            temp = boundary.copy()
            diff_options = list(itertools.combinations_with_replacement(temp, n))
        for i in diff_options:
            result.append(path + list(i))
        return result
    elif(len(paths[0]) == 2):
        for path in paths:
            n = 4 - len(path);
            temp = boundary.copy()
            for i in path:
                temp.remove(i)
            diff_options = list(itertools.combinations_with_replacement(temp, n))
            for i in diff_options:
                result.append(path + list(i))
            temp1 = path.copy()
            temp1.append(temp1[0])
            temp = boundary.copy()
            temp.remove(temp1[0])
            diff_options = list(itertools.combinations_with_replacement(temp, 1))
            for i in diff_options:
                result.append(temp1+list(i))
            temp1 = path.copy()
            temp1.append(temp1[1])
            temp = boundary.copy()
            temp.remove(temp1[0])
            temp.remove(temp1[1])
            diff_options = list(itertools.combinations_with_replacement(temp, 1))
            for i in diff_options:
                result.append(temp1+list(i))
        return result
    elif(len(paths[0]) == 1):
        for path in paths:
            n = 4 -len(path);
            temp = boundary.copy()
            for i in path:
                temp.remove(i)
            diff_options = list(itertools.combinations(temp, n))
            for i in diff_options:
                result.append(path+list(i))
            temp1 = path.copy()
            temp1.append(temp1[0])
            temp = boundary.copy()
            temp.remove(temp1[0])
            diff_options = list(itertools.combinations_with_replacement(temp, 2))
            for i in diff_options:
                result.append(temp1+list(i))
            temp1 = path.copy()
            for i in temp:
                temp2 = temp1.copy()
                temp2.append(i)
                temp2.append(i)
                temp3 = temp.copy()
                temp3.remove(i)
                for j in temp3:
                    result.append(temp2+[j])
        return result
    elif(len(paths[0]) == 0):
        diff_options = list(itertools.combinations(boundary, 4))
        for i in diff_options:
            result.append(list(i))
        for i in boundary:
            temp = [i]
            temp.append(i)
            temp1 = boundary.copy()
            temp1.remove(i)
            diff_options = list(itertools.combinations(temp1, 2))
            for i in diff_options:
                result.append(temp+list(i))
        for i in range(0,len(boundary)):
            for j in range(i+2,len(boundary)):
                if(i == 0 and j == len(boundary)-1):
                    continue
                temp = [boundary[i],boundary[i],boundary[j],boundary[j]]
                result.append(temp)
        return result
    return paths

def news_edges(matrix, cip, source_node):
    """Connects given cip to given exterior vertex.

    Args:
        matrix: A matrix containing adjacency matrix of graph.
        cip: A list containing cip.
        source_node: An integer indicating node number.

    Returns:
        None
    """
    edgecnt = 0
    for node in cip:
        edgecnt += 1
        matrix[source_node][node] = 1
        matrix[node][source_node] = 1
    return edgecnt

def connect_news(matrix, nodecnt):
    """Connects exterior vertices to each other.

    Args:
        matrix: A matrix representing adjacency list of the graph.
        nodecnt: An integer representing the node count of the graph.

    Returns:
        None
    """
    matrix[nodecnt][nodecnt + 3] = 1
    matrix[nodecnt + 3][nodecnt] = 1
    matrix[nodecnt + 3][nodecnt + 2] = 1
    matrix[nodecnt + 2][nodecnt + 3] = 1
    matrix[nodecnt + 2][nodecnt + 1] = 1
    matrix[nodecnt + 1][nodecnt + 2] = 1
    matrix[nodecnt][nodecnt + 1] = 1
    matrix[nodecnt + 1][nodecnt] = 1
    
def add_news(bdy,matrix,nodecnt,edgecnt):
    """Adds 4 outer vertices- N, E, S and W to the input graph.

    Args:
        bdy: A list containing 4 outer boundaries of the graph.
        matrix: A matrix representing the adjacency matrix of the graph.
        nodecnt: An integer representing the node count of the graph.
        edgecnt: An integer representing the edge count of the graph.

    Returns:
        adjmatrix: A matrix representing the modified adjacency matrix of the graph.
        edgecnt: An integer representing the edge count of the graph.
    """
    
    adjmatrix = np.zeros([matrix.shape[0] + 4, matrix.shape[0] + 4], int)
    adjmatrix[0:matrix.shape[0],0:matrix.shape[0]] = matrix
    edgecnt += news_edges(adjmatrix,bdy[0], nodecnt)
    edgecnt += news_edges(adjmatrix,bdy[1], nodecnt + 1) #east
    edgecnt += news_edges(adjmatrix,bdy[2], nodecnt + 2) #south
    edgecnt += news_edges(adjmatrix,bdy[3], nodecnt + 3) #west
    edgecnt += 4
    connect_news(adjmatrix, nodecnt)
    return adjmatrix, edgecnt


