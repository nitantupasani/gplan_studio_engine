"""This file is the code to insert a spanning circulation for a given planar graph input and entry input
"""
import networkx as nx
import matplotlib.pyplot as plt
import numpy as np
from copy import deepcopy
import itertools
import bdy
from typing import List, Tuple

class Point:
    def __init__(self, x: float, y: float):
        self.x = x
        self.y = y

class Edge:
    def __init__(self, id: int, left: Point, right: Point):
        self.id = id
        self.left = left
        self.right = right

class Room:
    def __init__(self, id : int, tl_x: float, tl_y: float, br_x: float, br_y: float):
        self.id = id
        self.top_left_x = tl_x
        self.top_left_y = tl_y
        self.bottom_right_x = br_x
        self.bottom_right_y = br_y
        self.height = abs(self.bottom_right_y - self.top_left_y)
        self.width = abs(self.bottom_right_x - self.top_left_x)
        self.rel_push_T = 0
        self.rel_push_B = 0
        self.rel_push_L = 0
        self.rel_push_R = 0
        # To keep track of what is the final changed state for each room edges: Example - (L,0.5) for say room id = 1, denotes that after all
        # movements finally the left edge of room must be pushed by 0.5 from its initial position
        self.target = {'T': 0, 'B': 0, 'L': 0, 'R': 0}


class RFP:
    def __init__(self,graph: nx.Graph,rooms: list[Room]):
        self.graph = graph
        self.rooms = rooms


    #Functions to create RFP from the graph

class circulation:
    def __init__(self,graph: nx.Graph, thickness: float = 0.1, rfp: RFP = None) -> None:
        self.graph = graph
        self.adjacency = {}
        self.circulation_graph = nx.Graph() 
        self.RFP = rfp
        self.temp_push_states = []
        self.corridor_thickness = thickness
        self.pushed_stack = []
        self.circulations_adjacency_list = []
        self.multiple_circ = []
        self.exterior_edges = []
        self.is_dimensioned = False
        self.dimensions = {}
        self.dimension_constraints = []
        self.room_area = []
        # self.room_width = []
        # self.room_height = []
        self.is_dimensioning_successful = False    
    
    def multiple_circulation(self,coord:List) -> None:

        self.find_exterior_edges(coord)
        print("Exterior edges:")
        print(self.exterior_edges)

        for x in self.exterior_edges:
            self.circulation_algorithm(x[0],x[1])
            self.multiple_circ.append(self.circulation_graph)
    
    def find_exterior_edges(self, coord: List) -> None:
        """This function finds the exterior edges of the graph input by the user

        Args:
            coord (List): This is the list of coordinates of the vertices of the graph
        """
        graph1 = deepcopy(self.graph)
        adj = nx.to_numpy_matrix(graph1)
        edgecnt = adj.sum()/2
        edgeset =[]
        for i in range(len(graph1)):
            for j in range(i+1, len(graph1)):
                if(adj[i,j] == 1):
                    edgeset.append((i,j))
        bdy_obj = bdy.Boundary(len(graph1), edgecnt, edgeset, coord)
        boundary = bdy_obj.identify_bdy()
        for x in boundary:
            if len(x) == 2:
                self.exterior_edges.append(x)
            
            else:
                for i in range(len(x) - 1):
                    self.exterior_edges.append([x[i], x[i+1]])


    def remove_corridor(self,graph:nx.Graph,v1:int = 0,v2:int = 1)->None:
        """To remove corridor vertex between v1 and v2 if exists
        Args:
            graph (nx.Graph): Graph to be modified
            v1 (int): First endpoint of the target edge from which we remove corridor vertex
            v2 (int): Second endpoint of the target edge from which we remove corridor vertex
        """
        self.circulation_graph = deepcopy(graph)
        # n = len(self.circulation_graph)
        m = len(self.graph)
        
        # To ensure both the vertices are rooms
        if(v1 < m and v2 < m):
            # To ensure the rooms are adjacent
            if(self.graph.has_edge(v1,v2)):
                # To check if there is a corridor vertex between the rooms
                if([v1,v2] in self.adjacency.values()):
                    # Get the corridor vertex
                    i = list(self.adjacency.keys())[list(self.adjacency.values()).index([v1,v2])]

                    # Approach 1(Not working): Contracting one endpoint and the corridor to reverse the subdivision
                    # Approach 2(Not working): 1. Delete the corridor vertex 2. Add edge connecting the two rooms
                    # Approach 3:
                    # Finding the vertex to which we must contract
                    x = list(nx.common_neighbors(self.circulation_graph,i,v1))
                    y = list(nx.common_neighbors(self.circulation_graph,i,v2))

                    # Find the room that is part of the required triangle
                    for r in x+y:
                        if(r < m):
                            break
                    
                    # Decision for contracting edge between the i and v1 or i and v2
                    # c1 is a boolean variable that holds truth value of "There is a corridor joining v1 and r"
                    c1 = ([r,v1] in self.adjacency.values()) or ([v1,r] in self.adjacency.values())
                    # c2 is a boolean variable that holds truth value of "There is a corridor joining v2 and r"
                    c2 = ([r,v2] in self.adjacency.values()) or ([v2,r] in self.adjacency.values())

                    # Case 1: Both are false - happens when i is the last corridor
                    if(not (c1 or c2)):
                        # Doesn't matter if you contract v1-i or v2-i
                        mod_circ = nx.contracted_edge(self.circulation_graph, (v1,i), self_loops=False)
                    
                    # Case 2: One of c1 or c2 is true - most common case
                    elif(c1 and not c2):
                        # Contract v2-i
                        mod_circ = nx.contracted_edge(self.circulation_graph, (v2,i), self_loops=False)
                    
                    elif(c2 and not c1):
                        # Contract v1-i
                        mod_circ = nx.contracted_edge(self.circulation_graph, (v1,i), self_loops=False)
                    
                    # Case 3: Both are true - happens when both v2-r and v1-r are part of another interior face of the graph
                    elif(c1 and c2):
                        # Confirm from sir
                        # Remove edge between r and i else creates unnecessary adjaceny after contraction
                        self.circulation_graph.remove_edge(r,i)
                        mod_circ = nx.contracted_edge(self.circulation_graph, (v1,i), self_loops=False)

                    print("Before deletion:", self.adjacency)
                    self.circulation_graph = mod_circ
                    # Remove the entry of corridor i from adjacency dict
                    del self.adjacency[i]

                    print("After deletion:", self.adjacency)
                
                elif([v2,v1] in self.adjacency.values()):
                    # Get the corridor vertex
                    i = list(self.adjacency.keys())[list(self.adjacency.values()).index([v2,v1])]

                    # Approach 1(Not working): Contracting one endpoint and the corridor to reverse the subdivision
                    # Approach 2(Not working): 1. Delete the corridor vertex 2. Add edge connecting the two rooms
                    # Approach 3:
                    # Finding the vertex to which we must contract
                    x = list(nx.common_neighbors(self.circulation_graph,i,v1))
                    y = list(nx.common_neighbors(self.circulation_graph,i,v2))

                    # Find the room that is part of the required triangle
                    for r in x+y:
                        if(r < m):
                            break
                    
                    # Decision for contracting edge between the i and v1 or i and v2
                    # c1 is a boolean variable that holds truth value of "There is a corridor joining v1 and r"
                    c1 = ([r,v1] in self.adjacency.values()) or ([v1,r] in self.adjacency.values())
                    # c2 is a boolean variable that holds truth value of "There is a corridor joining v2 and r"
                    c2 = ([r,v2] in self.adjacency.values()) or ([v2,r] in self.adjacency.values())

                    # Case 1: Both are false - happens when i is the last corridor
                    if(not (c1 or c2)):
                        # Doesn't matter if you contract v1-i or v2-i
                        mod_circ = nx.contracted_edge(self.circulation_graph, (v1,i), self_loops=False)
                    
                    # Case 2: One of c1 or c2 is true - most common case
                    elif(c1 and not c2):
                        # Contract v2-i
                        mod_circ = nx.contracted_edge(self.circulation_graph, (v2,i), self_loops=False)
                    
                    elif(c2 and not c1):
                        # Contract v1-i
                        mod_circ = nx.contracted_edge(self.circulation_graph, (v1,i), self_loops=False)
                    
                    # Case 3: Both are true - happens when both v2-r and v1-r are part of another interior face of the graph
                    elif(c1 and c2):
                        # Confirm from sir
                        # Remove edge between r and i else creates unnecessary adjaceny after contraction
                        self.circulation_graph.remove_edge(r,i)
                        mod_circ = nx.contracted_edge(self.circulation_graph, (v1,i), self_loops=False)

                    print("Before deletion:", self.adjacency)
                    self.circulation_graph = mod_circ
                    # Remove the entry of corridor i from adjacency dict
                    del self.adjacency[i]

                    print("After deletion:", self.adjacency)
                
                else:
                    print("There is no corridor vertex between these rooms")
            else:
                print("The rooms are not adjacent")
        else:
            print("The two vertices passed must correspond to rooms")

    def circulation_algorithm(self,v1: int = 1,v2: int = 2) -> int:
        """
        Applies the circulation algorithm on the PTPG graph
        
        Args:
            v1 (int, optional): First endpoint of the exterior edge to start the circulation algorithm. Defaults to 1.
            v2 (int, optional): Second endpoint of the exterior edge to start the circulation algorithm. Defaults to 2.
        """
        graph = deepcopy(self.graph)
        # Use to_numpy_array instead of to_numpy_matrix if Networkx 3.0 or above
        # print(nx.to_numpy_matrix(graph))
        print(nx.to_numpy_array(graph))
        # n is the number of vertices in the initial graph
        n = len(graph)
        m = n
        s = (v1-1 ,v2-1 , -1)

        # This dictionary tracks the pair of rooms each corridor is adjacent to
        # (key is vertex corresponding to corridor and values are a pair of rooms)
        adjacency = {}
        corridor_counter = 0
        queue = []
        queue.append(s)

        # Start of circulation algorithm
        while ( queue ):
            # Pops out the first element of the queue to subdivide the edge for V_n+1
            s = queue.pop(0)  
            for ne in list(nx.common_neighbors(graph,s[0],s[1])):
                if ne < m :
                    graph.add_edge(s[0],n)
                    graph.add_edge(s[1],n)
                    try:
                        graph.remove_edge(s[0],s[1])
                    except:
                        print("WARNING!! THE INITIAL CHOSEN ENTRY EDGE MUST BE EXTERIOR EDGE") # Warning displayed
                        return 0
                    
                    if s[2]>0:
                        # If condition satisfied this adds edge between current corridor vertex and previous one
                        graph.add_edge(n,s[2])
                    graph.add_edge(n,ne)
                    n+=1
                    # Adds the two tuples corresponding to the two triangles formed in the face considered
                    adjacency[corridor_counter] = [s[0],s[1]]
                    corridor_counter += 1
                    queue.append((ne,s[0],n-1))
                    queue.append((ne,s[1],n-1))
        
        # Change the key values to corridor vertex number
        corridor_vertices = [x+m for x in range(len(adjacency))]

        # Now the final_adjacency dictionary contains the pair of rooms adjacent to each corridor
        final_adjacency = dict(zip(corridor_vertices, list(adjacency.values())))

        # Now A stores the adjacency matrix of the graph, the nodelist parameter ensures the proper order of rows
        # corresponding to the node id
        A = nx.adjacency_matrix(graph, nodelist=range(m))

        # todense prints the matrix in proper format along with the data type
        print(A.todense())

        self.circulation_graph = graph
        self.adjacency = final_adjacency
        return 1

    def corridor_boundary_rooms(self,corridor_vertex: nx.Graph.nodes) -> list:
        """For a given corridor, this function outputs the two rooms it connects

        Args:
            corridor_vertex (Networkx node): Node corresponding to the corridor for which we need to find the neighbors
            # v1 (int, optional): First endpoint of the exterior edge to start the circulation algorithm. Defaults to 1.
            # v2 (int, optional): Second endpoint of the exterior edge to start the circulation algorithm. Defaults to 2.

        Returns:
            [a,b]: pair of rooms that the corridor_vertex is adjacent to
        """
        # Gets the tuple corresponding to the key value (key = corridor_vertex)
        [a,b] = self.adjacency.get(corridor_vertex)
        
        return [a,b]
    
    # Main function integrating the others
    def adjust_RFP_to_circulation(self) -> None:
        """
        Adjusts the RFP to form the circulation

        Args:
            None

        Returns:
            None
        """       
        # For each corridor vertex we find the pair of rooms that this corridor connects
        # Shifted left bound by 1 to shift the boundary only from the second corridor vertex
        end = max(list(self.adjacency.keys()))
        start = min(list(self.adjacency.keys()))
        print("First corridor: ",start)
        print("Last corridor: ",end)
        for corridor in range(start + 1, end + 1):
            if corridor in list(self.adjacency.keys()):
                [room1, room2] = self.corridor_boundary_rooms(corridor)
                self.add_corridor_between_2_rooms(self.RFP.rooms[room1],self.RFP.rooms[room2])
            else:
                continue
        
        # For rooms that are connected by corridors we directly assign relative push values
        # as calculated in add_corridor_between_rooms fn
        for room in self.RFP.rooms:
            if(room.target.get('T') != 0):
                room.rel_push_T = room.target.get('T')

            if(room.target.get('B') != 0):
                room.rel_push_B = room.target.get('B')

            if(room.target.get('L') != 0):
                room.rel_push_L = room.target.get('L')

            if(room.target.get('R') != 0):
                room.rel_push_R = room.target.get('R')

        for room in self.RFP.rooms:
            self.push_edges(room)
        print(self.dimensions)
        if(self.is_dimensioned == True):
            is_feasible = self.check_dimensions_feasibility()
            self.is_dimensioning_successful = is_feasible
            if is_feasible == True:
                for i in range(len(self.dimension_constraints[0])):
                    # self.room_area.append(self.dimensions[i][0] * self.dimensions[i][1])
                    self.room_area.append("W:{0}; H:{1}; A:{2}".format(round(self.dimensions[i][0], 2), 
                                            round(self.dimensions[i][1], 2), round(self.dimensions[i][0] * self.dimensions[i][1], 2)))

    
    def add_corridor_between_2_rooms(self,room1: Room,room2: Room) -> None:
        """Adds corridors between 2 given rooms. First finds the common edge between the two rooms
           then finds the temporary push states (the neighbor and shift direction). In the next step, for
           each of the tuple in the temp_push_states list we call move_edge function to do the shifting

        Args:
            room1 (int): Room index of first room 
            room2 (int): Room index of second room
        """

        # This tuple has 5 elements, namely the x and y of left end of common edge, x and y of right end of common edge
        #  and the direction of common edge with respect to room1 (N/S/E/W)
        common_edge = self.find_common_edges(room1, room2)

        # Forming the gap between room1 and room2 first
        if(common_edge[4][1] == "N"):
            self.temp_push_states.append([(room1.id, "S", "T", room2.id, "N", "B")])

            # To properly calculate rel push values
            room1.target.update({'T': -0.5*self.corridor_thickness})

            # To properly calculate rel push values
            room2.target.update({'B': 0.5*self.corridor_thickness})

        elif(common_edge[4][1] == "S"):
            self.temp_push_states.append([(room1.id, "N", "B", room2.id, "S", "T")])

            # To properly calculate rel push values
            room1.target.update({'B': 0.5*self.corridor_thickness})

            # To properly calculate rel push values
            room2.target.update({'T': -0.5*self.corridor_thickness})

        elif(common_edge[4][1] == "E"):
            self.temp_push_states.append([(room1.id, "W", "R", room2.id, "E", "L")])

            # To properly calculate rel push values
            room1.target.update({'R': -0.5*self.corridor_thickness})

            # To properly calculate rel push values
            room2.target.update({'L': 0.5*self.corridor_thickness})

        elif(common_edge[4][1] == "W"):
            self.temp_push_states.append([(room1.id, "E", "L", room2.id, "W", "R")])

            # To properly calculate rel push values
            room1.target.update({'L': 0.5*self.corridor_thickness})

            # To properly calculate rel push values
            room2.target.update({'R': -0.5*self.corridor_thickness})

        # Finds the common neighbors and their push states for room1 and room2
        self.find_common_neighbors(room1,room2, -1)

        # Push the room edges as per the push states populated using the above function
        for tuple_list in self.temp_push_states:
            for each_tuple in tuple_list:

                self.calculate_edge_move(self.RFP.rooms[each_tuple[0]], each_tuple[1], each_tuple[2])
                self.calculate_edge_move(self.RFP.rooms[each_tuple[3]], each_tuple[4], each_tuple[5])


    def find_common_edges(self,room1: Room,room2: Room) -> tuple:
        """Given two rooms this function finds the common edges between the two rooms

        Args:
            room1 (Room object): Room object of first room 
            room2 (Room object): Room object of second room 

        Returns:
            [tuple]: This tuple has 5 elements, namely the x and y of left end of common edge, x and y of right end of common edge
                     and the direction of common edge with respect to room1 (N/S/E/W)
        """

        common_edge = (0,0,0,0,(room1.id,"Null"))
        # Case1: The rooms are vertically (same y coordinates)
        # Room1 is below Room2
        if room1.top_left_y == room2.bottom_right_y:
            common_edge = (max(room1.top_left_x, room2.top_left_x), room1.top_left_y, min(room1.bottom_right_x, room2.bottom_right_x), room2.bottom_right_y, (room1.id, "N"))
        
        # Room1 is above Room2
        elif room1.bottom_right_y == room2.top_left_y:
            common_edge = (max(room1.top_left_x, room2.top_left_x), room2.top_left_y, min(room1.bottom_right_x, room2.bottom_right_x), room1.bottom_right_y, (room1.id, "S"))

        # Case2: The rooms are horizontally adjacent (same x coordinates)
        # Room1 is to right of Room2 
        elif room1.top_left_x == room2.bottom_right_x:
            common_edge = (room1.top_left_x, max(room1.bottom_right_y, room2.bottom_right_y), room2.bottom_right_x, min(room1.top_left_y,room2.top_left_y), (room1.id, "W"))
        
        # Room1 is to left of Room2
        elif room1.bottom_right_x == room2.top_left_x:
            common_edge = (room2.top_left_x, max(room1.bottom_right_y, room2.bottom_right_y), room1.bottom_right_x, min(room1.top_left_y,room2.top_left_y), (room1.id, "E"))
        
        return common_edge

    def find_common_neighbors(self,room1: Room,room2: Room, last_visited: Room) -> list:
        """For each common neighbor of room1 and room2, checks if that neighbor shares an edge with
           room1 or room2 along the direction of common edge between room1 and room2. After each check it appends
           the neighbor, the orientation of common edge and the direction in which the room has to be shifted to form
           corridor between room1 and room2.

        Args:
            room1 (Room object): Room object of first room 
            room2 (Room object): Room object of second room 

        Returns:
            [list]: list contains tuples that contain the corresponding room each neighbor is connected to
                    and the direction in which we have to move to form corridors
        """
        # Note: T - top edge, B - bottom edge, L - left edge, R - right edge
        # Note: N - north, S - south, E - east, W - west
        # Note: (room1.id, "S", "T", room2.id, "N", "B") means that the top edge of room 1 has to be moved South
        # and the bottom edge of room 2 has to be moved North
        
        common_edge = self.find_common_edges(room1, room2)

        # neighbors is a list that contains tuples that contain the corresponding room each neighbor is
        # connected to and the direction in which we have to move to form corridors
        neighbors_room1 = []
        neighbors_room2 = []
        orientation = 'x'
        height = 0
        # Common edge is parallel to x axis
        if(common_edge[1] == common_edge[3]):
            height = common_edge[1]
            orientation = 'x'
        
        # Common edge is parallel to y axis
        elif(common_edge[0] == common_edge[2]):
            height = common_edge[0]
            orientation = 'y'
        
        # The axis wrt which we shift the room edges to form corridor
        axis = (orientation, height)

        print("common neighbor test", self.graph.edges(), room1.id, room2.id)
        for neighbor_room_id in list(nx.common_neighbors(self.graph, room1.id, room2.id)):
            if neighbor_room_id == last_visited:
                continue
            
            room = self.RFP.rooms[neighbor_room_id]
            # Change self.RFP[room] to just room and resolving the error will just be to make it an
            # object of class room, but how to assign the coordinates
            common_edge1 = self.find_common_edges(room, room1) 
            common_edge2 = self.find_common_edges(room, room2)

            # Finding the direction/orientation of common edge between room and room1 wrt room1
            if(common_edge1[4][1] == "N" and axis[0] == 'x'):
                neighbors_room1.append((room.id, "N", "T", room1.id, "N", "B"))
            elif(common_edge1[4][1] == "S" and axis[0] == 'x'):
                neighbors_room1.append((room.id, "S", "B", room1.id, "S", "T"))
            elif(common_edge1[4][1] == "W" and axis[0] == 'y'):
                neighbors_room1.append((room.id, "W", "L", room1.id, "W", "R"))
            elif(common_edge1[4][1] == "E" and axis[0] == 'y'):
                neighbors_room1.append((room.id, "E", "R", room1.id, "E", "L"))
                      
            # Finding the direction/orientation of common edge between room and room2 wrt room2
            elif(common_edge2[4][1] == "N" and axis[0] == 'x'):
                neighbors_room2.append((room.id, "N", "T", room2.id, "N", "B"))
            elif(common_edge2[4][1] == "S" and axis[0] == 'x'):
                neighbors_room2.append((room.id, "S", "B", room2.id, "S", "T"))
            elif(common_edge2[4][1] == "W" and axis[0] == 'y'):
                neighbors_room2.append((room.id, "W", "L", room2.id, "W", "R"))
            elif(common_edge2[4][1] == "E" and axis[0] == 'y'):
                neighbors_room2.append((room.id, "E", "R", room2.id, "E", "L"))
        
        # KEY STEP
        # Append the tuples in neigbors_room1 and neighbors_room2 to neighbors list (common for whole graph)
        if neighbors_room1:
            self.temp_push_states.append(neighbors_room1)
        # Testing the common_neighbors function
        print("For ", room1.id, ", ", room2.id, " the common edges with  ", room1.id, ": ", neighbors_room1)
        if neighbors_room2:
            self.temp_push_states.append(neighbors_room2)
        # Testing the common_neighbors function
        print("For ", room1.id, ", ", room2.id, " the common edges with  ", room2.id, ": ", neighbors_room2)
        print("\n")
    

        # This for loop executes the function to find common edges for those that
        # share edge with room1 along the axis
        for neighbor1 in neighbors_room1:
            neighbor_of_room1 = self.RFP.rooms[neighbor1[0]]
            self.find_common_neighbors(room1, neighbor_of_room1, room2.id)
        
        # This for loop executes the function to find common edges for those that
        # share edge with room2 along the axis
        for neighbor2 in neighbors_room2:
            neighbor_of_room2 = self.RFP.rooms[neighbor2[0]]
            self.find_common_neighbors(room2, neighbor_of_room2, room1.id)  
        
    def calculate_edge_move(self,room: Room, direction: str, coordinate: str) -> None:
        """This function takes in two room objects and calculates by what value
           the corresponding common edge should be shifted in the required direction

        Args:
            room1 (Room object): The first room whose coordinates need to be modified
            direction1 (string): The direction in which room1's edge needs to be shifted
            room2 (Room object): The second room whose coordinates need to be modified
            direction2 (string): The direction in which room2's edge needs to be shifted
        """
        room_obj = self.RFP.rooms[room.id]

        # This shifts edge of room1 in given direction
        if(direction == "E" and coordinate == "R"):
            room_obj.rel_push_R = max(room_obj.rel_push_R, 0.5*self.corridor_thickness) if room_obj.rel_push_R >= 0 else room_obj.rel_push_R

        elif(direction == "E" and coordinate == "L"):
            room_obj.rel_push_L = max(room_obj.rel_push_L, 0.5*self.corridor_thickness) if room_obj.rel_push_L >= 0 else room_obj.rel_push_L

        elif(direction == "W" and coordinate == "R"):
            room_obj.rel_push_R = min(room_obj.rel_push_R, -0.5*self.corridor_thickness) if room_obj.rel_push_R <= 0 else room_obj.rel_push_R

        elif(direction == "W" and coordinate == "L"):
            room_obj.rel_push_L = min(room_obj.rel_push_L, -0.5*self.corridor_thickness) if room_obj.rel_push_L <= 0 else room_obj.rel_push_L 
        
        elif(direction == "N" and coordinate == "T"):
            room_obj.rel_push_T = max(room_obj.rel_push_T, 0.5*self.corridor_thickness) if room_obj.rel_push_T >= 0 else room_obj.rel_push_T

            
        elif(direction == "N" and coordinate == "B"):
            room_obj.rel_push_B = max(room_obj.rel_push_B, 0.5*self.corridor_thickness) if room_obj.rel_push_B >= 0 else room_obj.rel_push_B
        
        elif(direction == "S" and coordinate == "T"):
            room_obj.rel_push_T = min(room_obj.rel_push_L, -0.5*self.corridor_thickness) if room_obj.rel_push_T <= 0 else room_obj.rel_push_T

        elif(direction == "S" and coordinate == "B"):
            room_obj.rel_push_B = min(room_obj.rel_push_B, -0.5*self.corridor_thickness) if room_obj.rel_push_B <= 0 else room_obj.rel_push_B

    def push_edges(self, room: Room) -> None:
        """This modifies the room coordinates (final step of adjustment)

        Args:
            room (Room): Room whose coordinates are modified
        """
        
        room.top_left_y += room.rel_push_T
        room.top_left_x += room.rel_push_L
        room.bottom_right_y += room.rel_push_B
        room.bottom_right_x += room.rel_push_R
        height = room.top_left_y - room.bottom_right_y
        width = room.bottom_right_x- room.top_left_x
        self.dimensions[room.id] = [width, height]

    def check_dimensions_feasibility(self) -> bool:
        """This checks which dimensioned floorplans still satisfies the dimensional constraints after adding circulation

        Returns:
            bool: True if modified floorplan still satisfies dimension conditions, else False
        """
        # Variables declared for readability
        min_width = self.dimension_constraints[0]
        max_width = self.dimension_constraints[1]
        min_height = self.dimension_constraints[2]
        max_height = self.dimension_constraints[3]
        min_ar = self.dimension_constraints[4]
        max_ar = self.dimension_constraints[5]

        flag = 0
        for i in range(len(min_width)):
            width = self.dimensions[i][0]
            height = self.dimensions[i][1]
            if (width < min_width[i] - self.corridor_thickness or height < min_height[i] - self.corridor_thickness or width/height < min_ar[i]):
                flag = 1
                break
        if flag == 1:
            return False
        else:
            return True  


def wheel_graph(n: int) -> Tuple[nx.Graph, list]:
    """Returns a wheel graph of size n and its positional coordinates

    Args:
        n (int): Size of the wheel graph to be generated

    Returns:
        Tuple[nx.Graph, list]: Returns the wheel graph of size n and list has coordinates of vertices in the coordinate plane
    """

    A = np.zeros((n,n),dtype=int)
    
    for i in range(1,n-1):
        A[0][i] = A[i][0] = A[i][i+1] = A[i+1][i] = 1

    A[0][n-1] = A[n-1][0] = A[1][n-1] = A[n-1][0] = 1

    coord = [(0,0)]
    t = np.linspace(0, 2*np.pi, n - 1, endpoint=False)
    x = 10 * np.cos(t)
    y = 10 * np.sin(t)
    
    for i in range(len(t)):
        coord.append((x[i],y[i]))
    G = nx.from_numpy_array(A)
    return G, coord

def complete_graph(n: int) -> Tuple[nx.Graph, list]:
    """Returns a complete graph of size n and its positional coordinates

    Args:
        n (int): Size of the complete graph to be generated

    Returns:
        Tuple[nx.Graph, list]: Returns the complete graph of size n and list has coordinates of vertices in the coordinate plane
    """

    G = nx.complete_graph(n)
    coord = []
    t = np.linspace(0, 2*np.pi, n, endpoint=False)
    x = 10 * np.cos(t)
    y = 10 * np.sin(t)

    for i in range(len(t)):
        coord.append((x[i],y[i]))
    return G, coord

def plot(graph: nx.Graph,m: int) -> None:
    """Plots thr graph using matplotlib

    Args:
        graph (Networkx graph): The graph to plot
        m (integer): Number of vertices in the graph
    """
    pos=nx.spring_layout(graph) # positions for all nodes
    nx.draw_networkx(graph,pos, label=None,node_size=400 ,node_color='#4b8bc8',font_size=12, font_color='k', font_family='sans-serif', font_weight='normal', alpha=1, bbox=None, ax=None)
    nx.draw_networkx_edges(graph,pos)
    nx.draw_networkx_nodes(graph,pos,
                        nodelist=list(range(m,len(graph))),
                        node_color='r',
                        node_size=500,
                    alpha=1)
    plt.show()

def is_subgraph(g1: nx.graph, k: int) -> bool:
    """This function checks if graph g1 contains a wheel graph of size <= k

    Args:
        g1 (nx.graph): Graph in which we want to check if it contains a wheel graph
        k (int): Size of graph g1

    Returns:
        bool: true if g1 contains wheel graph of size <= k else false
    """

    for i in range(4,k+1):    
        for SG in (g1.subgraph(s) for s in itertools.combinations(g1, k)):
            # print(SG.nodes(), SG.edges())
            if(nx.is_isomorphic(nx.wheel_graph(i),SG)):
                return True
        
    return False

# Main fn for writing the test cases for each feature
def main():
    def make_graph():
        g = nx.Graph()
        g.add_edge(0,1)
        g.add_edge(0,2)
        g.add_edge(0,3)
        g.add_edge(1,2)
        g.add_edge(2,3)
        n = len(g)

        return g
    
    def test_circ():

        g = make_graph()
        n = len(g)
        plot(g,n)

        tl_x1 = 0.0
        br_x1 = 10.0
        br_y1 = 0.0
        tl_y1 = 30.0

        tl_x2 = 10.0
        tl_y2 = 30.0
        br_x2 = 20.0
        br_y2 = 20.0

        tl_x3 = 10.0
        tl_y3 = 20.0
        br_x3 = 20.0
        br_y3 = 10.0

        tl_x4 = 10.0
        tl_y4 = 10.0
        br_x4 = 20.0
        br_y4 = 0.0

        room1 = Room(0, tl_x1, tl_y1, br_x1, br_y1)
        room2 = Room(1, tl_x2, tl_y2, br_x2, br_y2)
        room3 = Room(2, tl_x3, tl_y3, br_x3, br_y3)
        room4 = Room(3, tl_x4, tl_y4, br_x4, br_y4)

        rfp = RFP(g, [room1, room2, room3, room4])
        circulation_obj = circulation(g, rfp)
        rooms = []
        circulation_obj.circulation_algorithm()
        plot(circulation_obj.circulation_graph, len(circulation_obj.circulation_graph))
        # rooms = circulation_obj.corridor_boundary_rooms(n)
        # print("Adjacency: ", circulation_obj.adjacency)
        # print("Rooms that corridor ", n, " connects: ", rooms)

    def test_comm_edges():
        # Case1 test:
        g1 = make_graph()
        tl_x1 = 10
        br_x1 = 20
        br_y1 = 0
        tl_y1 = 10
        tl_x2 = 0
        tl_y2 = 20
        br_x2 = 30
        br_y2 = 10
        room1 = Room("0", tl_x1, tl_y1, br_x1, br_y1)
        room2 = Room("1", tl_x2, tl_y2, br_x2, br_y2)

        rfp1 = RFP(g1, [room1, room2])
        circulation_obj1 = circulation(g1, rfp1, room1, room2)
        common_edge1 = circulation_obj1.find_common_edges(room1, room2)
        print("Common edge case1:", common_edge1)

        # Case2 test:
        g2 = make_graph()
        tl_x3 = 10
        br_x3 = 20
        br_y3 = 10
        tl_y3 = 20
        tl_x4 = 0
        tl_y4 = 10
        br_x4 = 30
        br_y4 = 0
        room3 = Room("0", tl_x3, tl_y3, br_x3, br_y3)
        room4 = Room("1", tl_x4, tl_y4, br_x4, br_y4)

        rfp2 = RFP(g2, [room3, room4])
        circulation_obj2 = circulation(g2, rfp2, room3, room4)
        common_edge2 = circulation_obj2.find_common_edges(room3, room4)
        print("Common edge case2:", common_edge2)

        # Case3 test:
        g3 = make_graph()
        tl_x5 = 10
        br_x5 = 20
        br_y5 = 5
        tl_y5 = 15
        tl_x6 = 0
        tl_y6 = 20
        br_x6 = 10
        br_y6 = 0
        room5 = Room("0", tl_x5, tl_y5, br_x5, br_y5)
        room6 = Room("1", tl_x6, tl_y6, br_x6, br_y6)

        rfp3 = RFP(g3, [room5, room6])
        circulation_obj3 = circulation(g3, rfp3, room5, room6)
        common_edge3 = circulation_obj3.find_common_edges(room5, room6)
        print("Common edge case3:", common_edge3)

        # Case4 test:
        g4 = make_graph()
        tl_x7= 0
        br_x7 = 10
        br_y7 = 5
        tl_y7 = 15 
        tl_x8 = 10
        tl_y8 = 20
        br_x8 = 20
        br_y8 = 0
        room7 = Room("0", tl_x7, tl_y7, br_x7, br_y7)
        room8 = Room("1", tl_x8, tl_y8, br_x8, br_y8)

        rfp4 = RFP(g4, [room7, room8])
        circulation_obj4 = circulation(g4, rfp4, room7, room8)
        common_edge4 = circulation_obj4.find_common_edges(room7, room8)
        print("Common edge case4:", common_edge4)

    def test_comm_neighbors():
        g = make_graph()
        n = len(g)
        plot(g,n)

        tl_x1 = 0
        br_x1 = 10
        br_y1 = 0
        tl_y1 = 30

        tl_x2 = 10
        tl_y2 = 30
        br_x2 = 20
        br_y2 = 20

        tl_x3 = 10
        tl_y3 = 20
        br_x3 = 20
        br_y3 = 10

        tl_x4 = 10
        tl_y4 = 10
        br_x4 = 20
        br_y4 = 0

        room1 = Room(0, tl_x1, tl_y1, br_x1, br_y1)
        room2 = Room(1, tl_x2, tl_y2, br_x2, br_y2)
        room3 = Room(2, tl_x3, tl_y3, br_x3, br_y3)
        room4 = Room(3, tl_x4, tl_y4, br_x4, br_y4)

        rfp = RFP(g, [room1, room2, room3, room4])

        circulation_obj = circulation(g, rfp, room1, room3)
        circulation_obj.find_common_neighbors(room1, room3, -1)

    def test_move_edges():
        g = make_graph()
        n = len(g)
        plot(g,n)

        tl_x1 = 0
        br_x1 = 10
        br_y1 = 0
        tl_y1 = 30

        tl_x2 = 10
        tl_y2 = 30
        br_x2 = 20
        br_y2 = 20

        tl_x3 = 10
        tl_y3 = 20
        br_x3 = 20
        br_y3 = 10

        tl_x4 = 10
        tl_y4 = 10
        br_x4 = 20
        br_y4 = 0

        room1 = Room(0, tl_x1, tl_y1, br_x1, br_y1)
        room2 = Room(1, tl_x2, tl_y2, br_x2, br_y2)
        room3 = Room(2, tl_x3, tl_y3, br_x3, br_y3)
        room4 = Room(3, tl_x4, tl_y4, br_x4, br_y4)

        rfp = RFP(g, [room1, room2, room3, room4])

        circulation_obj = circulation(g, rfp)
        circulation_obj.add_corridor_between_2_rooms(room1, room3)
        for room in circulation_obj.RFP.rooms:
            print("Room ",room.id, ":")
            print("Push top edge by: ", room.rel_push_T)
            print("Push bottom edge by: ", room.rel_push_B)
            print("Push left edge by: ", room.rel_push_L)
            print("Push right edge by: ", room.rel_push_R)
            print('\n')
        
    def test_adjust_RFP_to_circ():
        g = make_graph()
        n = len(g)
        plot(g,n)

        tl_x1 = 0.0
        br_x1 = 10.0
        br_y1 = 0.0
        tl_y1 = 30.0

        tl_x2 = 10.0
        tl_y2 = 30.0
        br_x2 = 20.0
        br_y2 = 20.0

        tl_x3 = 10.0
        tl_y3 = 20.0
        br_x3 = 20.0
        br_y3 = 10.0

        tl_x4 = 10.0
        tl_y4 = 10.0
        br_x4 = 20.0
        br_y4 = 0.0

        room1 = Room(0, tl_x1, tl_y1, br_x1, br_y1)
        room2 = Room(1, tl_x2, tl_y2, br_x2, br_y2)
        room3 = Room(2, tl_x3, tl_y3, br_x3, br_y3)
        room4 = Room(3, tl_x4, tl_y4, br_x4, br_y4)

        rfp = RFP(g, [room1, room2, room3, room4])

        circulation_obj = circulation(g, rfp)
        """, room1, room3)"""
        door1 = int(input("Enter one end of entry edge: "))
        door2 = int(input("Enter other end of entry edge: "))
        circulation_obj.circulation_algorithm(door1+1, door2+1)
        circulation_obj.adjust_RFP_to_circulation()

        for room in circulation_obj.RFP.rooms:
            print("Room ",room.id, ":")
            print("Push top edge by: ", room.rel_push_T)
            print("Push bottom edge by: ", room.rel_push_B)
            print("Push left edge by: ", room.rel_push_L)
            print("Push right edge by: ", room.rel_push_R)
            print(room.target)
            print('\n')
    
    def test_remove_corridor():
        g = make_graph()
        n = len(g)
        plot(g,n)

        tl_x1 = 0.0
        br_x1 = 10.0
        br_y1 = 0.0
        tl_y1 = 30.0

        tl_x2 = 10.0
        tl_y2 = 30.0
        br_x2 = 20.0
        br_y2 = 20.0

        tl_x3 = 10.0
        tl_y3 = 20.0
        br_x3 = 20.0
        br_y3 = 10.0

        tl_x4 = 10.0
        tl_y4 = 10.0
        br_x4 = 20.0
        br_y4 = 0.0

        room1 = Room(0, tl_x1, tl_y1, br_x1, br_y1)
        room2 = Room(1, tl_x2, tl_y2, br_x2, br_y2)
        room3 = Room(2, tl_x3, tl_y3, br_x3, br_y3)
        room4 = Room(3, tl_x4, tl_y4, br_x4, br_y4)

        rfp = RFP(g, [room1, room2, room3, room4])
        circulation_obj = circulation(g, 0.1, rfp)
        # rooms = []
        circulation_obj.circulation_algorithm()
        plot(circulation_obj.circulation_graph, len(circulation_obj.circulation_graph))
        circulation_obj.remove_corridor(circulation_obj.circulation_graph)
        plot(circulation_obj.circulation_graph, len(circulation_obj.circulation_graph))
    
    def test_multiple_circ():
        # Example1
        g1, coord1 = wheel_graph(10)
        circ_obj1 = circulation(g1)
        circ_obj1.multiple_circulation(coord1)
        print("Number of multiple circulations: ", end=" ")
        print(len(circ_obj1.multiple_circ))

        # # Example2
        # g2,coord2 = complete_graph(5)
        # circ_obj2 = circulation(g2)
        # circ_obj2.multiple_circulation(coord2)
        # print("Number of multiple circulations: ", end=" ")
        # print(len(circ_obj2.multiple_circ))

        # # Example3
        # g3, coord3 = complete_graph(4)
        # circ_obj3 = circulation(g3)
        # circ_obj3.multiple_circulation(coord3)
        # print("Number of multiple circulations: ", end=" ")
        # print(len(circ_obj3.multiple_circ))

    # test_circ()
    # test_comm_edges()
    # test_comm_neighbors()
    # test_move_edges()
    # test_adjust_RFP_to_circ()
    test_remove_corridor()
    # test_multiple_circ()
    

if __name__ == "__main__":
    main()

''' Note:
Try to implement:
1. Combining dimension and circulation
2. Catalogue for circulation
3. Multiple circulation (one for each exterior edge)
4. Remove corridor fn
'''
