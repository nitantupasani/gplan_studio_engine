"""This file is the code to insert a spanning circulation for a given planar graph input (where entry need not be exterior edge)
"""
import networkx as nx
import matplotlib.pyplot as plt
import numpy as np
from copy import deepcopy
from .source.trial import bdy as bdy
from typing import List, Tuple
import circulation

class custom_circ:
    def __init__(self, graph) -> None:
        self.graph = graph
        self.span_circ = nx.Graph()
        self.adjacency = {}
        self.modified_circ = self.graph
        self.corridor_tree = nx.Graph()

    def add_corridor(self, graph: nx.Graph, v1: int, v2:int) -> None:
        """Adding a corridor vertex between vertices v1 and v2 if the edge exists

        Args:
            graph (nx.Graph): Graph to be modified
            v1 (int): First endpoint of the target edge to add corridor vertex
            v2 (int): Second endpoint of the target edge to add corridor vertex
        """
        self.modified_circ = deepcopy(graph)
        n = len(self.modified_circ)
        m = len(self.graph)

        if(v1 < m and v2 < m):
            if(self.modified_circ.has_edge(v1,v2)):

                # Added to keep the grah triangulated
                for ne in list(nx.common_neighbors(self.modified_circ,v1,v2)):
                    self.modified_circ.add_edge(n,ne)
                
                # Subdividing the edge to add the corridor vertex in its place
                self.modified_circ.add_edge(v1,n)
                self.modified_circ.add_edge(v2,n)
                self.modified_circ.remove_edge(v1,v2)
                
                # Adding to dictionary the corridor vertex and the rooms that it connects
                self.adjacency[n] = [v1,v2]
                # print(self.adjacency)
            else:
                print("The edge " + str((v1,v2)) + "does not exist in the graph")
        
        else:
            print("You cannot add corridor vertex between a room vertex and another corridor vertex")

    def remove_corridor(self,graph:nx.Graph,v1:int,v2:int)->None:
        """To remove corridor vertex between v1 and v2 if exists

        Args:
            graph (nx.Graph): Graph to be modified
            v1 (int): First endpoint of the target edge from which we remove corridor vertex
            v2 (int): Second endpoint of the target edge from which we remove corridor vertex
        """
        self.modified_circ = deepcopy(graph)
        n = len(self.modified_circ)
        m = len(self.graph)

        # To ensure both the vertices are rooms
        if(v1 < m and v2 < m):
            # To ensure the rooms are adjacent
            if(self.graph.has_edge(v1,v2)):
                # To check if there is a corridor vertex between the rooms
                if([v1,v2] in self.adjacency.values()):
                    # Get the corridor vertex
                    i = list(self.adjacency.keys())[list(self.adjacency.values()).index([v1,v2])]
                    # Contracting one endpoint and the corridor to reverse the subdivision
                    mod_circ = nx.contracted_edge(self.modified_circ,(v1,i),False)
                    self.modified_circ = mod_circ
                
                elif([v2,v1] in self.adjacency.values()):
                    # Get the corridor vertex
                    i = list(self.adjacency.keys())[list(self.adjacency.values()).index([v2,v1])]
                    # Contracting one endpoint and the corridor to reverse the subdivision
                    mod_circ = nx.contracted_edge(self.modified_circ,(v1,i),False)
                    self.modified_circ = mod_circ
                
                else:
                    print("There is no corridor vertex between these rooms")
            else:
                print("The rooms are not adjacent")
        else:
            print("The two vertices passed must correspond to rooms")

    def nearest_exterior_edge(self,f1: int, f2: int,s1: int,s2: int) -> list:
        """User wants corridor space starting between edge s1--s2 till f1--f2. So, we use this function to
           get the nearest exterior edge to first find the spanning circulation. 

        Args:
            f1 (int): First endpoint of the target edge to end the circulation (maybe interior).
            f2 (int): Second endpoint of the target edge to end the circulation (maybe interior).
            s1 (int): First endpoint of the target edge to start the circulation (maybe interior).
            s2 (int): Second endpoint of the target edge to start the circulation (maybe interior).
        """
        # Note: Find a way to find the exterior edge that has corridor vertex
        # on both s1--s2 and f1--f2


    # Getting custom circulation by adding corridors to input graph
    def custom_circ1(self, edges: List):
        """Adds corridor on the edges passed as parameter (user's choice)

        Args:
            edges (List): The set of edges on which we want to add corridor vertices
        """

        for x in edges:
            self.add_corridor(self.modified_circ,x[0],x[1])

    # Getting custom circulation from spanning circulation
    """ Note: Find a way to find the exterior edge that has corridor vertex on both s1--s2 and f1--f2"""
    def custom_circ2(self,f1: int, f2: int,s1: int = 1,s2: int = 2,v1: int = 0,v2: int = 1) -> None:
        """
        Modifies the circulation graph having the spanning circulation to restrict it to user choice
    
        Args:
            f1 (int, optional): First endpoint of the target edge to end the circulation (maybe interior). Defaults to 1.
            f2 (int, optional): Second endpoint of the target edge to end the circulation (maybe interior). Defaults to 2.
            s1 (int, optional): First endpoint of the target edge to start the circulation (maybe interior). Defaults to 1.
            s2 (int, optional): Second endpoint of the target edge to start the circulation (maybe interior). Defaults to 2.
            v1 (int, optional): First endpoint of the exterior edge to start the circulation algorithm. Defaults to 1.
            v2 (int, optional): Second endpoint of the exterior edge to start the circulation algorithm. Defaults to 2.            
        """
        # Steps involved:
        # Step 1: Find spanning circulation
        # Step 2: Find corridor vertex on the edge s1--s2 and similarly f1--f2
        # Step 3: Find the path through corridor vertices between the start and end corridor vertex
        # Step 4: Remove and contract the edges having unnecessary corridor vertices

        # Step 1 (Note: later call the circ_algo from circulation.py instead of repeating code)

        graph = deepcopy(self.graph)
        # n is the number of vertices in the initial graph
        n = len(graph)
        m = n
        s = (v1 ,v2 , -1)

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

        self.span_circ = graph
        self.adjacency = final_adjacency

        # Step 2

        min = 999
        max = -1

        # Loop to find the corridor vertex labels that mark start and end of custom circulation
        # We find the v1, v2 such that it is the nearest exterior edge to the start and so we have
        # i for s1--s2 < i for f1--f2
        for i in range(len(self.graph),len(self.span_circ)):
            # Gets the tuple corresponding to the key value (key = corridor_vertex = i(here))
            [a,b] = self.adjacency.get(i)
            if([a,b] == [s1,s2] or [b,a] == [s1,s2]):
                if (min > i):
                    min = i

            if([a,b] == [f1,f2] or [b,a] == [f1,f2]):
                if(max < i):
                    max = i
    
        # Step 3

        # Finding path via corridor vertices between required start and end
        self.corridor_tree = nx.induced_subgraph(self.span_circ, range(len(self.graph), len(self.span_circ)))

        # Since we find simple path in a tree, we get a single path
        path = nx.all_simple_paths(self.corridor_tree, min, max)

        # We get the indices that are need to be removed from the spanning circulation
        indices = [x for x in range(len(self.graph), len(self.span_circ))]

        reqd_corridors = []
        for i in path:
            for idx in i:
                indices.remove(idx)
                reqd_corridors.append(idx)
        
        # Step 4

        # Contracting the edges to modify the circulation
        mod_circ = deepcopy(self.span_circ)
        for i in indices:
            for j in reqd_corridors:
                if mod_circ.has_edge(i,j):
                    mod_circ.remove_edge(i,j)
            [a,b] = self.adjacency.get(i)
            mod_circ = nx.contracted_edge(mod_circ, (a,i), False)
        self.modified_circ = mod_circ

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

def main():
    def make_graph():
        g = nx.Graph()
        g.add_edge(0,1)
        g.add_edge(0,2)
        g.add_edge(1,3)
        g.add_edge(1,2)
        g.add_edge(1,4)
        g.add_edge(3,6)
        g.add_edge(3,4)
        g.add_edge(2,4)
        g.add_edge(2,5)
        g.add_edge(4,5)
        g.add_edge(4,6)
        g.add_edge(5,6)

        return g

    """ Note: Find a way to find the exterior edge that has corridor vertex
        on both s1--s2 and f1--f2"""
    def test_custom_circ1():
        g = make_graph()
        custom_obj = custom_circ(g)
        # custom_obj.custom_circ(3,4,1,2,0,1)
        custom_obj.custom_circ2(3,4,1,2,1,3)
        plot(custom_obj.span_circ, len(custom_obj.span_circ))
        plot(custom_obj.corridor_tree, len(custom_obj.corridor_tree))
        plot(custom_obj.modified_circ, len(custom_obj.modified_circ))
    
    def test_custom_circ2():
        g =make_graph()
        custom_obj = custom_circ(g)
        custom_obj.custom_circ1([(1,2), (1,4),(3,4)])
        plot(custom_obj.graph, len(custom_obj.graph))
        plot(custom_obj.modified_circ, len(custom_obj.modified_circ))
    
    def test_remove_corridor():
        g =make_graph()
        custom_obj = custom_circ(g)
        plot(custom_obj.graph, len(custom_obj.graph))
        custom_obj.add_corridor(g,1,2)
        custom_obj.add_corridor(custom_obj.modified_circ,1,4)
        custom_obj.add_corridor(custom_obj.modified_circ,3,4)
        plot(custom_obj.modified_circ, len(custom_obj.modified_circ))
        custom_obj.remove_corridor(custom_obj.modified_circ,1,4)
        plot(custom_obj.modified_circ, len(custom_obj.modified_circ))
    
    # test_custom_circ1()
    # test_custom_circ2()
    test_remove_corridor()

if __name__ == "__main__":
    main()