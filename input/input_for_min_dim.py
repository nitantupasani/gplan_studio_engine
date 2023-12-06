from input.input_template import nodes
from input.input_template import edges
from input.input_template import boundary_rooms

class floorplan:
    def __init__(self, fp_type, dim_set, dim_circ_set, add_del_corr_set, corr_thick):
        self.nodes = []
        self.edges = []
        self.floorplan_type = fp_type
        self.is_dimensions_needed = (dim_set == 1)
        self.is_corridor_needed = (fp_type == "circulation" and (not (dim_circ_set == 1 and add_del_corr_set == 1)))
        self.corridor_width = corr_thick if (fp_type == "circulation") else 0
        self.floorplan_limit = 100000
        self.boundary_rooms = {}
        
    def fill_nodes(self, id_list, colors, coords, min_width, min_height):
        for id in id_list:
            id = int(id)
            node_obj = nodes()
            self.nodes.append(node_obj.add_node(id, colors[id], coords[id][0], coords[id][1], min_width[id], min_height[id]))
    
    def fill_edges(self, edge_list):
        for edge in edge_list:
            edge_obj = edges()
            self.edges.append(edge_obj.add_edge(edge[0], edge[1]))
            
    def fill_boundary_rooms(self, enc_mat):
        boundary_room_obj = boundary_rooms()
        self.boundary_rooms = boundary_room_obj.get_boundary_rooms(enc_mat)
    
    def get_floorplan_details(self, id_list, colors, coords, min_width, min_height, 
                              edge_list, enc_mat):
        self.fill_nodes(id_list, colors, coords, min_width, min_height)
        self.fill_edges(edge_list)
        self.fill_boundary_rooms(enc_mat)
        
        return {
            "nodes": self.nodes,
            "edges": self.edges,
            "floorplan_type": self.floorplan_type,
            "dimensions_needed": self.is_dimensions_needed,
            "corridors_needed": self.is_corridor_needed,
            "corridor_width": self.corridor_width,
            "floorplan_limit": self.floorplan_limit,
            "boundary_rooms": self.boundary_rooms
        }