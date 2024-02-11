"""
Input Template

This file creates a standard template that should be used for the input that can be provided by GPlan to any other service.

This module contains the following classes:

    * nodes: which provides the details for a node like id, label, color, coordinates and dimensions.
    * edges: which provides the source and target vertices for each edge.
    * boundary_rooms: which provides the rooms at the NSEW boundaries.
"""
from pickle import NONE


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
        self.room_x = None
        self.room_y = None
        self.room_width = None
        self.room_height = None
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
        
    def set_undim_rfp_data(self, room_x = None, room_y = None, room_width = None, room_height = None):
        if room_x is not None:
            self.room_x = room_x
        if room_y is not None:
            self.room_y = room_y
        if room_width is not None:
            self.room_width = room_width
        if room_height is not None:
            self.room_height = room_height
            
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
    
    def append_undim_rfp_data(self):
        if self.room_x is not None:
            self.node_data["room_x"] = self.room_x
        if self.room_y is not None:
            self.node_data["room_y"] = self.room_y
        if self.room_width is not None:
            self.node_data["room_width"] = self.room_width
        if self.room_height is not None:
            self.node_data["room_height"] = self.room_height
    
    def get_node_data(self):
        self.append_identity()
        self.append_coordinates()
        self.append_constraints()
        self.append_undim_rfp_data()
        return self.node_data
    
    def add_node(self, id, color, x, y, min_w, min_h, max_w = None, max_h = None, label = None, room_x = None, room_y = None, room_width = None, room_height = None):
        self.set_identity(id, color, label)
        self.set_coordinates(x, y)
        self.set_constraints(min_w, min_h, max_w, max_h)
        self.set_undim_rfp_data(room_x, room_y, room_width, room_height)
        return self.get_node_data()
#changes in class edges
class edges:
    def __init__(self):
        self.source = None
        self.target = None
        self.color = None
        self.edge_data = {}
        
    def set_edge(self, x, y, color):
        self.source = x
        self.target = y
        self.color = color
    
    def get_edge_data(self):
        self.edge_data["source"] = self.source
        self.edge_data["target"] = self.target
        self.edge_data["color"] = self.color
        return self.edge_data
    
    def add_edge(self, x, y, color):
        self.set_edge(x, y,color)
        return self.get_edge_data()
    
class boundary_rooms:
    def __init__(self):
        self.north = []
        self.south = []
        self.east = []
        self.west = []
    
    def identify_boundary(self, enc_mat, room_x, room_y):      
        for i in range(0, len(room_x)):
            if (room_x[i] == 0.0):
                self.west.append(i)
        
        for i in range(0, len(room_y)):
            if (room_y[i] == 0.0):
                self.south.append(i)
                
        for i in range(0, len(enc_mat)):
            for j in range(0, len(enc_mat[0])):
                if ((i == 0 or i == len(enc_mat)-1) and enc_mat[i][j] not in self.north and enc_mat[i][j] not in self.south):
                    self.north.append(int(enc_mat[i][j]))
                if ((j == 0 or j == len(enc_mat[0])-1) and enc_mat[i][j] not in self.east and enc_mat[i][j] not in self.west):
                    self.east.append(int(enc_mat[i][j]))
                    
    def get_boundary_rooms(self, enc_mat, room_x, room_y):
        self.identify_boundary(enc_mat, room_x, room_y)
        return {
            "north": self.north,
            "south": self.south,
            "east": self.east,
            "west": self.west
        }
