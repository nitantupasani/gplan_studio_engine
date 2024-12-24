import networkx as nx
import itertools
from itertools import combinations
from collections import defaultdict

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

def find_valid_edge_multi(block1, block2, non_adj_list,potential_edges):
    """Finds a valid edge between two blocks that is not in the non-adjacency list.
    Args:
        block1: List of nodes in the first block.
        block2: List of nodes in the second block.
        non_adj_list: List of edges that should not be added.
    
    Returns:
        A valid edge (u, v) or None if no valid edge is found.
    """
    valid_edges_set = set()
    for u in block1:
        for v in block2:
            if (u, v) not in non_adj_list and (v, u) not in non_adj_list and \
                (u, v) not in potential_edges and (v,u) not in potential_edges and\
                    (u,v) not in valid_edges_set and (v,u) not in valid_edges_set:
                valid_edges_set.add((u, v))
    return valid_edges_set

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

def find_valid_edges(blocks, non_adj):
    """
    Finds all valid edges between nodes of different blocks.

    Args:
        blocks (list of lists): Each block contains a list of nodes.
        non_adj (list of tuples): List of non-adjacent edges.

    Returns:
        valid_edges (list of tuples): List of valid edges.
    """
    non_adj_set = set(non_adj)
    valid_edges = []

    for i, block1 in enumerate(blocks):
        for j, block2 in enumerate(blocks):
            if i >= j:  # Avoid duplicate checks and self-loops
                continue
            for u in block1:
                for v in block2:
                    if (u, v) not in non_adj_set and (v, u) not in non_adj_set:
                        valid_edges.append((u, v))

    return valid_edges

def connect_blocks(blocks, valid_edges, non_adj):
    """
    Connects all blocks with a minimum number of edges.

    Args:
        blocks (list of lists): Each block contains a list of nodes.
        valid_edges (list of tuples): List of valid edges.
        non_adj (list of tuples): List of non-adjacent edges.

    Returns:
        selected_edges (list of tuples): List of selected edges to connect blocks.
    """
    block_graph = defaultdict(set)
    block_count = len(blocks)

    # Map nodes to their blocks
    node_to_block = {}
    for block_idx, block in enumerate(blocks):
        for node in block:
            node_to_block[node] = block_idx

    # Kruskal's algorithm for Minimum Spanning Tree (MST)
    parent = list(range(block_count))

    def find(x):
        if parent[x] != x:
            parent[x] = find(parent[x])
        return parent[x]

    def union(x, y):
        root_x = find(x)
        root_y = find(y)
        if root_x != root_y:
            parent[root_y] = root_x

    # Sort valid edges by weight (default: unit weight)
    valid_edges.sort()
    selected_edges = []

    for u, v in valid_edges:
        block_u = node_to_block[u]
        block_v = node_to_block[v]
        if find(block_u) != find(block_v):
            union(block_u, block_v)
            selected_edges.append((u, v))
            block_graph[block_u].add(block_v)
            block_graph[block_v].add(block_u)

    # Check if all blocks are connected
    connected_blocks = len(set(find(i) for i in range(block_count)))

    if connected_blocks > 1:
        # Add non-adjacent edges if necessary to connect all blocks
        for u, v in non_adj:
            block_u = node_to_block[u]
            block_v = node_to_block[v]
            if find(block_u) != find(block_v):
                union(block_u, block_v)
                selected_edges.append((u, v))
                block_graph[block_u].add(block_v)
                block_graph[block_v].add(block_u)

    return selected_edges
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
        valid_edges = find_valid_edges(blocks, non_adj_list)
        selected_edges = connect_blocks(blocks, valid_edges, non_adj_list)
    
    return selected_edges


       



def make_biconnected_permutations(matrix, non_adj_list):
    """
    Returns all sets of edges that can be added to make the graph biconnected.

    Args:
        matrix: Adjacency matrix of the graph.
        non_adj_list: List of edges that should not be added.

    Returns:
        potential_edges: A set of edges that can be added to make the graph biconnected.
    """
    nxgraph = nx.from_numpy_array(matrix)
    articulation_points = list(nx.articulation_points(nxgraph))
    potential_edges = set()
    all_bicon_edges = set()
    connected_components = {}

    print("Non-Adjacency List Applied in Biconnectivity:", non_adj_list)

    # Initialize connected components for blocks
    for point in articulation_points:
        blocks = find_blocks(nxgraph, point)
        for block in blocks:
            connected_components[tuple(block)] = tuple(block)

    # Function to find the root of a block in connected components
    def find_root(block):
        if connected_components[block] != block:
            connected_components[block] = find_root(connected_components[block])
        return connected_components[block]

    # Union function to connect two blocks
    def union(block1, block2):
        root1, root2 = find_root(block1), find_root(block2)
        if root1 != root2:
            connected_components[root2] = root1

    # Identify potential edges to add by iterating over articulation points
    for point in articulation_points:
        blocks = find_blocks(nxgraph, point)
        neighbors = sort_list(nxgraph, list(nx.neighbors(nxgraph, point)))
        print(f"{point}: Sorted List: ", neighbors)

        for i, block in enumerate(blocks):
            valid_edge_found = False
            for j, other_block in enumerate(blocks):
                if i < j and find_root(tuple(block)) != find_root(tuple(other_block)):
                    # First attempt to find valid edge with non-adjacency constraints
                    valid_edges = find_valid_edge_multi(block, other_block, non_adj_list, potential_edges)
                    # If valid edges are found in either attempt, update potential edges and merge blocks
                    if valid_edges:
                        valid_edge_found = True
                        potential_edges = potential_edges | valid_edges
                        union(tuple(block), tuple(other_block))
            
            # If no valid edge, relaxing constraints
            if not valid_edge_found:
                print(f"No valid edge found for {block}. Relaxing constraints.")
                valid_edges = find_valid_edge_multi(block, neighbors, [], potential_edges)
                potential_edges = potential_edges | valid_edges

    for r in range(1, len(potential_edges) + 1):
        for edge_combo in combinations(potential_edges, r):
            # Temporarily add edges to the graph
            for edge in edge_combo:
                nxgraph.add_edge(*edge)            
            # Check if the graph is biconnected
            if nx.is_biconnected(nxgraph):
                #Remove edges to get the least set possible in each
                #This basically ensures cases in which there are more edges than needed are removed
                #Because the lesser variant were already included in prev combinations
                redundant_edges = set()
                for edge in edge_combo:
                    nxgraph.remove_edge(*edge)
                    if not nx.is_biconnected(nxgraph):
                        nxgraph.add_edge(*edge)
                    else:
                        redundant_edges.add(edge)
                edge_combo = set(edge_combo) - (redundant_edges)
                edge_combo = {tuple(sorted(edge)) for edge in edge_combo}
                edge_combo = sorted(edge_combo)
                edge_combo = tuple(edge_combo)
                if(nx.is_planar(nxgraph)):
                    all_bicon_edges.add(edge_combo)
                else:
                    pass
                if(len(all_bicon_edges) > 20):
                    break

            # Remove edges to restore the original state
            for edge in edge_combo:
                nxgraph.remove_edge(*edge)

    return all_bicon_edges