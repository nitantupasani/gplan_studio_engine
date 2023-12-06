"""
Input Template

This file creates a standard template that should be used for the input that can be provided by GPlan to any other service.

This module contains the following classes:

    * nodes: which provides the details for a node like id, label, color, coordinates and dimensions.
    * edges: which provides the source and target vertices for each edge.
    * boundary_rooms: which provides the rooms at the NSEW boundaries.
"""
class nodes:
    def __init__(self):
        self.id = None
        self.label = None
        self.x = None
        self.y = None
        self.color = None
        self.min_width = None
        self.max_width = None
        self.min_height = None
        self.max_height = None
        self.node_data = {}
    
    def set_identity(self, id, color, label = None):
        self.id = id
        self.color = color
        if label is not None:
            self.label = label
    
    def set_coordinates(self, x, y):
        self.x = x
        self.y = y
        
    def set_constraints(self, min_w, min_h, max_w = None, max_h = None):
        self.min_width = min_w
        self.min_height = min_h
        if max_w is not None:
            self.max_width = max_w
        if max_h is not None:
            self.max_height = max_h
            
    def append_identity(self):
        self.node_data["id"] = self.id
        self.node_data["color"] = self.color
        if self.label is not None:
            self.node_data["label"] = self.label 
            
    def append_coordinates(self):
        self.node_data["x"] = self.x
        self.node_data["y"] = self.y
    
    def append_constraints(self):
        self.node_data["min_width"] = self.min_width
        self.node_data["min_height"] = self.min_height
        if self.max_width is not None:
            self.node_data["max_width"] = self.max_width
        if self.max_height is not None:
            self.node_data["max_height"] = self.max_height
    
    def get_node_data(self):
        self.append_identity()
        self.append_coordinates()
        self.append_constraints()
        return self.node_data
    
    def add_node(self, id, color, x, y, min_w, min_h, max_w = None, max_h = None, label = None):
        self.set_identity(id, color, label)
        self.set_coordinates(x, y)
        self.set_constraints(min_w, min_h, max_w, max_h)
        return self.get_node_data()
    
class edges:
    def __init__(self):
        self.source = None
        self.target = None
        self.edge_data = {}
        
    def set_edge(self, x, y):
        self.source = x
        self.target = y
    
    def get_edge_data(self):
        self.edge_data["source"] = self.source
        self.edge_data["target"] = self.target
        return self.edge_data
    
    def add_edge(self, x, y):
        self.set_edge(x, y)
        return self.get_edge_data()
    
class boundary_rooms:
    def __init__(self):
        self.north = []
        self.south = []
        self.east = []
        self.west = []
    
    def identify_boundary(self, enc_mat):
        for i in range(0, len(enc_mat)):
            for j in range(0, len(enc_mat[0])):
                if i == 0 and i not in self.north:
                    self.north.append(i)
                if i == len(enc_mat)-1 and i not in self.south:
                    self.south.append(i)
                if j == 0 and j not in self.west:
                    self.west.append(j)
                if j == len(enc_mat)-1 and j not in self.east:
                    self.east.append(j)
                    
    def get_boundary_rooms(self, enc_mat):
        self.identify_boundary(enc_mat)
        return {
            "north": self.north,
            "south": self.south,
            "east": self.east,
            "west": self.west
        }
