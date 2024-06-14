from GPLAN.input.input_template import nodes
from GPLAN.input.input_template import edges
from GPLAN.input.input_template import boundary_rooms

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
        
    def fill_nodes(self, id_list, colors, coords, min_width, min_height, room_x, room_y, room_width, room_height):
        for id in range(len(id_list)):
            node_obj = nodes()
            self.nodes.append(node_obj.add_node(id, colors[id], coords[id][0], coords[id][1], min_width[id], min_height[id], room_x=room_x[id], room_y=room_y[id], room_width=room_width[id], room_height=room_height[id], label=id_list[id]))
            curr = self.nodes[id]
            curr["room_y"] = curr["room_y"] + curr["room_height"]
            self.nodes.pop()
            self.nodes.append(curr) 
    
    def fill_edges(self, edge_list):
        for edge in edge_list:
            edge_obj = edges()
            self.edges.append(edge_obj.add_edge(edge[0], edge[1],edge[2]))
            
    def fill_boundary_rooms(self, enc_mat, room_x, room_y):
        boundary_room_obj = boundary_rooms()
        self.boundary_rooms = boundary_room_obj.get_boundary_rooms(enc_mat, room_x, room_y)
    
    def get_floorplan_details(self, id_list, colors, coords, min_width, min_height, 
                              room_x, room_y, room_width, room_height, edge_list, enc_mat):
        self.fill_nodes(id_list, colors, coords, min_width, min_height, room_x, room_y, room_width, room_height)
        self.fill_edges(edge_list)
        self.fill_boundary_rooms(enc_mat, room_x, room_y)
        
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