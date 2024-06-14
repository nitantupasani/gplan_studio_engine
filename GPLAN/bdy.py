"""This file is to use boundary identification algo to find the exterior edges of the planar graph
"""
import numpy as np
import networkx as nx
from random import randint
from GPLAN.source.graphoperations import biconnectivity as bcn
from GPLAN.source.graphoperations import oneconnectivity as onc
from GPLAN.source.graphoperations import operations as opr
from GPLAN.source.graphoperations import graph_crossings as gc
from GPLAN.source.graphoperations import triangularity as trng
from GPLAN.source.irregular import shortcutresolver as sr
from GPLAN.source.irregular import septri as st
from GPLAN.source.floorplangen import contraction as cntr
from GPLAN.source.floorplangen import expansion as exp
from GPLAN.source.floorplangen import rdg as rdg
from GPLAN.source.floorplangen import transformation as transform
from GPLAN.source.floorplangen import flippable as flp
from GPLAN.source.dimensioning import floorplan_to_st as fpts
from GPLAN.source.dimensioning import block_checker as bc
from GPLAN.source.boundary import cip as cip
from GPLAN.source.boundary import news as news

class Boundary:
    """A Boundary class for boundary identification of the graph.
    This class provides methods to generate single or
     multiple dimensioned/dimensionless floorplans.

    Attributes:
        nodecnt: An integer count of the number of nodes in the graph.
        edgecnt: An integer count of the number of edges in the graph.
        matrix: An adjacency matrix of the graph.
        bdy_nodes: A list containing all boundary nodes in the graph.
        bdy_edges: A list contaning all boundary edges in the graph.
        cip: A list containing all cips in the graph.
        irreg_nodes1: A list containing irregular room nodes 1. 
                        (list of list for multiple floorplans)
        irreg_nodes2: A list containing irregular room nodes 2. 
                        (list of list for multiple floorplans)
        mergednodes: A list containing nodes to be merged.
                        (list of list for multiple floorplans)
        degrees: A list containing degree of each node.
        room_height: A list containing height of each room.
        room_width: A list containing width of each room.
        nodecnt_list: A list containing node count for each rel matrix.
        nonrect: A boolean indicating if non rectangular floor plans exist.
        extranodes: A list containing extra nodes added for biconnectivity 
                    and triangularity. (list of list for multiple floorplans)
        area: A list containing the area of each room.
                (list of list for multiple floorplans)
        rel_matrix_list: A list containing multiple rel_matrices.
        floorplan_exist: A boolean indicating floorplan exists.
        fpcnt: An integer indicating the count of floorplans.
        coordinates: A list containing the coordinates of each node.
    """
    def __init__(self, nodecnt, edgecnt, edgeset):
        self.nodecnt = nodecnt
        self.edgecnt = edgecnt
        self.matrix = np.zeros((self.nodecnt, self.nodecnt), int)
        for edges in (edgeset):
            self.matrix[edges[0]][edges[1]] = 1
            self.matrix[edges[1]][edges[0]] = 1
        self.bdy_nodes = []
        self.bdy_edges = []
        self.irreg_nodes1 = []
        self.irreg_nodes2 = []
        self.mergednodes = []
        self.degrees = None
        self.room_x = np.zeros(self.nodecnt)
        self.room_y = np.zeros(self.nodecnt)
        self.room_height = np.zeros(self.nodecnt)
        self.room_width = np.zeros(self.nodecnt)
        self.nodecnt_list = []
        self.nonrect = False
        self.extranodes = []
        self.area = []
        self.rel_matrix_list = []
        self.floorplan_exist = False
        self.fpcnt = 0
        # self.coordinates = [np.array(x) for x in node_coordinates]

        # # Check if input has crossings
        # x_coord = [x[0] for x in node_coordinates]
        # y_coord = [x[1] for x in node_coordinates]
        # if(gc.check_intersection(x_coord, y_coord, self.matrix)):
        #     graph = nx.from_numpy_array(self.matrix)
        #     new_node_coordinates = list(nx.planar_layout(graph).values())
        #     self.coordinates = [np.array(x) for x in new_node_coordinates]
        # else:
        #     pass
    
    def identify_bdy(self):

        if(self.nodecnt == 2 and self.edgecnt == 1):
            self.room_x = np.array([0.0, 1.0])
            self.room_y = np.array([0.0, 0.0])
            self.room_width = np.array([1.0, 1.0])
            self.room_height = np.array([1.0, 1.0])
            return 
        #Biconnectivity Augmentation
        bcn_edges = []
        if (not bcn.is_biconnected(self.matrix)):
            bcn_edges = bcn.biconnect(self.matrix)
        for edge in bcn_edges:
            self.matrix[edge[0]][edge[1]] = 1
            self.matrix[edge[1]][edge[0]] = 1
            self.edgecnt += 1  # Extra edge added
        bcn_edges_added = len(bcn_edges) > 0

        #Triangularity
        trng_edges,positions,tri_faces = trng.triangulate(self.matrix
                                                ,bcn_edges_added
                                                ,self.coordinates)
        for edge in trng_edges:
            self.matrix[edge[0]][edge[1]] = 1
            self.matrix[edge[1]][edge[0]] = 1
            self.edgecnt += 1  # Extra edge added
        
        if(len(bcn_edges) != 0 or len(trng_edges) != 0):
            self.nonrect = True

        #Edge to vertex transformation
        for edge in bcn_edges:
            self.extranodes.append(self.nodecnt)
            self.matrix, tri_faces, positions, extra_edges_cnt = transform.transform_edges(
                self.matrix, edge, tri_faces, positions)
            self.nodecnt += 1  # Extra node added
            self.edgecnt += extra_edges_cnt
        
        for edge in trng_edges:
            self.extranodes.append(self.nodecnt)
            self.matrix, tri_faces, positions, extra_edges_cnt = transform.transform_edges(
                self.matrix, edge, tri_faces, positions)
            self.nodecnt += 1  # Extra node added
            self.edgecnt += extra_edges_cnt

        
        #Separating Triangle Elimination
        if(self.nodecnt - self.edgecnt + len(opr.get_trngls(self.matrix)) != 1):
            ptpg_matrices, extra_nodes = st.handle_STs(
                self.matrix, positions, 1)
            self.matrix = ptpg_matrices[0]
            self.nodecnt = self.matrix.shape[0]
            self.edgecnt = int(np.count_nonzero(self.matrix == 1)/2)
            for key in extra_nodes[0]:
                self.mergednodes.append(key)
                self.irreg_nodes1.append(extra_nodes[0][key][0])
                self.irreg_nodes2.append(extra_nodes[0][key][1])

        #Boundary Identification
        triangular_cycles = opr.get_trngls(self.matrix)
        digraph = opr.get_directed(self.matrix)
        self.bdy_nodes, self.bdy_edges = opr.get_bdy(
            triangular_cycles, digraph)
        shortcuts = sr.get_shortcut(
            self.matrix, self.bdy_nodes, self.bdy_edges)
        bdys = []
        if(self.edgecnt == 3 and self.nodecnt == 3):
            bdys = [[0], [0, 1], [1, 2], [2, 0]]
        else:
            bdy_ordered = opr.ordered_bdy(self.bdy_nodes, self.bdy_edges)
            cips = cip.find_cip(bdy_ordered, shortcuts)
            if(len(cips) <= 4):
                bdys = news.bdy_path(news.find_bdy(cips), bdy_ordered)
            else:
                while(len(shortcuts) > 4):
                    index = randint(0, len(shortcuts)-1)
                    self.matrix = sr.remove_shortcut(
                        shortcuts[index], triangular_cycles, self.matrix)
                    self.irreg_nodes1.append(shortcuts[index][0])
                    self.irreg_nodes2.append(shortcuts[index][1])
                    self.mergednodes.append(self.nodecnt)
                    self.nodecnt += 1  # Extra vertex added to remove shortcut
                    self.edgecnt += 3  # Extra edges added to remove shortcut
                    shortcuts.pop(index)
                    triangular_cycles = opr.get_trngls(self.matrix)
                bdy_ordered = opr.ordered_bdy(self.bdy_nodes, self.bdy_edges)
                cips = cip.find_cip(bdy_ordered, shortcuts)
                bdys = news.bdy_path(news.find_bdy(cips), bdy_ordered)
        return bdys

def main():

    g =nx.Graph()
    g.add_edge(0,1)
    g.add_edge(1,2)
    g.add_edge(2,3)
    g.add_edge(3,4)
    g.add_edge(4,5)
    g.add_edge(5,0)

    bdy_obj = Boundary(6,6,[[0,1],[1,2],[2,3],[3,4],[4,5],[5,0]],[[1,5],[1,10],[5,15],[10,10],[10,5],[5,1]])
    bdy = bdy_obj.identify_bdy()
    exterior = []
    for x in bdy:
        if len(x) == 2:
            exterior.append(x)
        
        else:
            for i in range(len(x) - 1):
                exterior.append([x[i], x[i+1]])
    
    print(exterior)

if __name__ == "__main__":
    main()
