"""This file is the code to insert multiple spanning circulations for a given planar graph input
"""
from typing import List, Tuple
import networkx as nx
import matplotlib.pyplot as plt
import numpy as np
from copy import deepcopy
import itertools
from .trial import bdy as bdy
import circulation

class multiple_circ:
    # Initialization
    def __init__(self) -> None:
        self.multiple_circ = []
        self.exterior_edges = []

        # We are basically counting no of times multiple_circulation
        # function is called. Since it is called even when queue is empty (terminating condition)
        # Number of circulation will be 1 less than number of function calls
        # so we start counting from -1 instead of 0
        self.count_of_multi_circ = -1
    
    # Primary function
    def multiple_circulation_fixed_entry(self, queue: list, graph: nx.Graph, size: int) -> None:
        """        
        This function generates multiple spannig circulation by varying the choice of edge to be subdivided
        at each step of the circulation algorithm

        Args:
            queue (list): The list of faces after the last subdivision of an edge (i.e., the two triangular faces added
            adding a corridor vertex)
            graph (nx.Graph): The graph on which the corridor vertices are being added
            size (int): Initial size of graph (i.e., number of rooms)
        """
        m = size
        n = len(graph)
        adjacency = {}
        corridor_counter = 0

        if len(queue) > 0:
            print("Queue: ",end=" ")
            print(queue)
            s = queue.pop(0)
            # Note that from second function call, variable size != len(graph) since graph has
            # additional corridor vertices
            self.count_of_multi_circ += 1
                
            for ne in list(nx.common_neighbors(graph,s[0],s[1])):
                if ne < m :
                    graph.add_edge(s[0],n)
                    graph.add_edge(s[1],n)
                    # if(graph.has_edge(s[0], s[1])):
                    #     graph.remove_edge(s[0],s[1])
                    try:
                        graph.remove_edge(s[0],s[1])
                    except:
                        print("WARNING!! THE INITIAL CHOSEN ENTRY EDGE MUST BE EXTERIOR EDGE") # Warning displayed
                        return 0
                        exit()
                    
                    if s[2]>0:
                        # If condition satisfied this adds edge between current corridor vertex and previous one
                        graph.add_edge(n,s[2])
                    graph.add_edge(n,ne)
                    n+=1
                    # Adds the two tuples corresponding to the two triangles formed in the face considered
                    adjacency[corridor_counter] = [s[0],s[1]]
                    corridor_counter += 1
                    queue1 = queue
                    queue2 = queue

                    # The possible choice 1
                    queue1.append((ne,s[1],n-1))
                    queue1.append((ne,s[0],n-1))

                    # The possible choice 2
                    queue2.append((ne,s[0],n-1))
                    queue2.append((ne,s[1],n-1))

                    graph1 = deepcopy(graph)
                    q1, q2 = [], []
                    [q1.append(x) for x in queue1 if x not in q1]
                    [q2.append(x) for x in queue2 if x not in q1]
                    self.multiple_circulation_fixed_entry(q1, graph, size)
                    self.multiple_circulation_fixed_entry(q2, graph1, size)

        
        # Terminating condition for the recursive fn calls
        elif len(queue) == 0:
            
            corridor_vertices = [x+m for x in range(len(adjacency))]
            self.circulations_adjacency_list.append(dict(zip(corridor_vertices, list(adjacency.values()))))
            # We don't need to write the below line for graph1 since
            # this will be done in its corresponding function call
            self.multiple_circ.append(graph)
    
    def multiple_circulation(self, coord: list) -> None:

        graph = deepcopy(self.graph)
        flag = -1 # variable to see if wheel graph is subgraph of given graph

        self.find_exterior_edges(coord)
        # Steps:
        # (1) Run a for loop from 4 to size of graph
        # (2) For each k in above range, check if wheel graph of size k is contained in graph
        # (3) If yes, multiple circulations for a given fixed entry edge exists
        # (4) Else, multiple circulations can be generated only by varying entry edge and so the number of
        #     circulations in that case will be <= number of exterior edges

        # Step 1
        for i in range(4,len(graph) + 1):
            
            # Step 2
            # If wheel graph any valid size is subgraph of given graph
            # then change flag to 1 and call multiple circ for given entry
            if(self.is_subgraph(nx.wheel_graph(i), graph,i)):
                # Step 3
                flag = 1

                # Inform user that multiple circulation for fixed edge is possible
                print("Multiple circulation for fixed edge possible. These are the exterior edges: ")
                print(self.exterior_edges)             
                v1 = int(input("Please enter the first end of entry door: "))
                v2 = int(input("Please enter the other end of entry door: "))
                if([v1,v2] in self.exterior_edges):
                    print("Yay")
                    self.multiple_circulation_fixed_entry([(v1, v2, -1)],graph,len(graph))
                break
        
        # Step 4
        # If no wheel graph is subgraph of given graph then we jus generate
        # circ for different exterior edges
        if(flag == -1):
            print("Nah!")       
            print(self.exterior_edges)


# Auxillary functions
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

# Main function
def main():
    """Used for testing the above functions
    """
    def test_is_subgraph():
        """Used to test is_subgraph function
        """
        # Example1
        g1 = nx.wheel_graph(10)

        if(is_subgraph(g1,len(g1))):
            print("This graph contains wheel graph")
        else:
            print("This graph doesn't contain wheel graph")

        # Example2
        g2 = nx.complete_graph(5)

        if(is_subgraph(g2,len(g2))):
            print("This graph contains wheel graph")
        else:
            print("This graph doesn't contain wheel graph")

        # Example3
        g3 = nx.complete_graph(4)

        if(is_subgraph(g3,len(g3))):
            print("This graph contains wheel graph")
        else:
            print("This graph doesn't contain wheel graph")
    
    def test_multiple_circulation():
        """Used to test multiple circulation function
        """
        # # Example1
        # g1, coord1 = wheel_graph(10)
        # circ_obj1 = circulation(g1)
        # circ_obj1.multiple_circulation(coord1)
        # print(coord1)
        # print("Number of multiple circ: ",end=" ")
        # print(circ_obj1.count_of_multi_circ)

        # # Example2
        # g2,coord2 = complete_graph(4)
        # circ_obj2 = circulation(g2)
        # circ_obj2.multiple_circulation(coord2)
        # print(coord2)        
        # print(len(circ_obj2.multiple_circ))

        # Example3
        g3, coord3 = complete_graph(4)
        print(len(coord3))
        print(coord3)
        circ_obj3 = circulation(g3)
        circ_obj3.multiple_circulation(coord3)
        print(len(circ_obj3.multiple_circ))
    
    # test_is_subgraph()
    test_multiple_circulation()

if __name__ == "__main__":
    main()