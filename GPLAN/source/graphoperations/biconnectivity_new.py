import networkx as nx
import itertools

def is_biconnected(matrix):
    """Returns a boolean representing whether the graph 
    is vertex biconnected or not.
    
    Args:
        nxgraph: An instance of NetworkX graph object.
    
    Returns:
        boolean: A boolean indicating TRUE if biconnected, FALSE otherwise.
    """
    nxgraph = nx.from_numpy_array(matrix)
    return nx.is_biconnected(nxgraph)

def get_cutvertices(nxgraph):
    """Returns list of cutvertices in the graph.
    Args:
        nxgraph: an instance of NetworkX graph object.
    
    Returns:
        articulation_list: A list of all articulation points in the graph.
    """
    articulation_list = list(nx.articulation_points(nxgraph))
    return articulation_list

def get_biconnected_components(nxgraph):
    """Returns list of biconnected components in the graph.
    Args:
        nxgraph: An instance of NetworkX graph object.
    
    Returns:
        components: A generator of biconnected components.
    """
    components = nx.biconnected_components(nxgraph)
    return components

def same_component(nxgraph, node1, node2):
    """Returns a boolean representing whether the given 2 nodes are in the same biconnected component or not.
    Args: 
        nxgraph: An instance of NetworkX graph object
        node1: An integer representing the first vertex to be checked.
        node2: An integer representing the second vertex to be checked.
    
    Returns:
        boolean: TRUE if vertices are in the same biconnected component else FALSE.
    """
    components = list(get_biconnected_components(nxgraph))
    for component in components:
        if (node1 in component) and (node2 in component):
            return True
    return False

def sort_list(nxgraph, neighbors):
    """Sorts the neighbors list such that neighbors in same components appear consecutively.
    Args:
        nxgraph: An instance of NetworkX graph object
        neighbors: List containing neighbors of an articulation point.
    
    Returns:
        neighbors_sorted: Required list with neighbors in same components appearing consecutively.
    """
    neighbors_sorted = []
    components = list(get_biconnected_components(nxgraph))
    for component in components:
        temp_list = []
        for vertex in neighbors:
            if vertex in component:
                if (vertex not in neighbors_sorted) and (vertex not in temp_list):
                    temp_list.append(vertex)
        neighbors_sorted.extend(temp_list)
    return neighbors_sorted

def find_valid_edge(block1, block2, non_adj_list):
    """Finds a valid edge between two blocks that is not in the non-adjacency list.
    Args:
        block1: List of nodes in the first block.
        block2: List of nodes in the second block.
        non_adj_list: List of edges that should not be added.
    
    Returns:
        A valid edge (u, v) or None if no valid edge is found.
    """
    for u in block1:
        for v in block2:
            if (u, v) not in non_adj_list and (v, u) not in non_adj_list:
                return (u, v)
    return None

def find_blocks(nxgraph, ap):
    """
    Find the connected components for a given articulation point in the graph.
    
    Parameters:
    G (networkx.Graph): The graph
    ap (node): The articulation point
    
    Returns:
    list: A nested list of connected components after removing the articulation point
    """
    # Create a copy of the graph without the articulation point
    G_copy = nxgraph.copy()
    G_copy.remove_node(ap)
    
    # Find the connected components in the modified graph
    components = list(nx.connected_components(G_copy))
    components = [list(component) for component in components]
    
    return components

def biconnect(matrix, non_adj_list):
    """Returns the edges to be added to make the graph biconnected.
    Args:
        matrix: Adjacency matrix of the said graph.
        non_adj_list: List of edges that should not be added.
    
    Returns:
        bicon_edges: A list of edges to be added to make the graph biconnected.
    """
    nxgraph = nx.from_numpy_array(matrix)
    articulation_points = get_cutvertices(nxgraph)
    added_edges = set()
    redundant_edges = set()
    bicon_edges = set()
    print("Non-Adjacency List Applied in Biconnectivity:", non_adj_list)
    
    for point in articulation_points: 
        neighbors = list(nx.neighbors(nxgraph, point))
        neighbors = sort_list(nxgraph, neighbors)
        print(f"{point}: Sorted List: ", neighbors)

        blocks = find_blocks(nxgraph, point)

        print (f"{point}: Blocks List: ", blocks)

        cycle_iter = itertools.cycle(blocks)
        for i in range(len(blocks) - 1):
            current_block = next(cycle_iter)
            next_block = next(cycle_iter)
            cycle_iter = itertools.cycle(itertools.islice(itertools.cycle(blocks), i+1, None))
    
            valid_edge = find_valid_edge(current_block, next_block, non_adj_list)
            if valid_edge is not None:
                added_edges.add(valid_edge)

        if valid_edge is None:
            print("No valid edge found.")
            for j in range(len(neighbors) - 1):
                if not same_component(nxgraph, neighbors[j], neighbors[j + 1]):
                    added_edges.add((neighbors[j], neighbors[j + 1]))                    

    for edge in added_edges:
        nxgraph.add_edge(*edge)
    for edge in added_edges:
        nxgraph.remove_edge(*edge)  
        if not nx.is_biconnected(nxgraph):
            nxgraph.add_edge(*edge)  
        else:
            redundant_edges.add(edge)

    bicon_edges = added_edges - redundant_edges

    return bicon_edges
