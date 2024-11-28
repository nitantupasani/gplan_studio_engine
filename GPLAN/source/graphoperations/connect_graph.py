## Code to make diconnected components of the input graph connected.

def dfs(v, nodes, visited, graph):
    visited[v]= True
    for i in range(nodes):
        if(visited[i] or graph[v][i] == False):
            continue
        dfs(i, nodes, visited, graph)
def one_connected(graph):
    nodes = graph.shape[0]
    visited = [False]*nodes
    parents = []
    for i in range(nodes):
        if(visited[i]):
            continue
        parents.append(i)
        dfs(i, nodes, visited, graph)
    components = len(parents)
    for i in range(components - 1):
        graph[parents[i]][parents[i+1]] = True
        graph[parents[i+1]][parents[i]] = True