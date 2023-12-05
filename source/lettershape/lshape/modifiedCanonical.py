from turtle import pos
import networkx as nx
import matplotlib.pyplot as plt
import tkinter as tk
import numpy as np
import re


class canonical:

    def __init__(self):
        self.graphs = []
        self.G = nx.Graph()
        self.adjacencies = []
        # self.graph_data = dict.fromkeys(['iteration','marked','neighbors','currentCanonicalOrder'])
        self.graph_data = {}
        self.node_coordinate = []
        self.new_node_coordinate = {}
        self.triplet = []
        self.lshapegraph = []
        self.lshapematrix = []
        self.cip = []

    def run(self):

        # inputting te graph
        self.G = nx.Graph()
        self.adjacencies = []
        n = int(input("Enter number of nodes: "))
        for i in range(n):
            self.G.add_node(i, id=-1, chord=0, mark=False, out=False)
        t = list(tuple(map(int, input().split())) for r in range(int(input('enter no of self.adjacencies : '))))
        self.G.add_edges_from(t)
        self.graphs.append(self.G)

        v1 = int(input("Enter v1: "))
        v2 = int(input("Enter v2: "))
        vn = int(input("Enter vn: "))

        nx.draw_planar(self.G, with_labels=True, font_weight='bold')
        plt.savefig("inputgraph.png")
        plt.show()  # DEBUG TODOs

        # initialisations
        canord = np.zeros(n, dtype=int)
        self.canonical_order(canord, v1, v2, vn, n)  # TODO find v1,v2,vn

    def displayInputGraph(self, noOfNodes, matrix, nodes_data):
        for i in nodes_data:  # To get the Coordinates of the nodes
            temp_node_data = []
            temp_node_data.append(i.pos_x)
            temp_node_data.append(i.pos_y)
            self.node_coordinate.append(temp_node_data)

        self.graph_data = {'iteration': np.zeros(noOfNodes), 'marked': np.zeros(noOfNodes), 'neighbors': [],
                           'currentCanonicalOrder': np.zeros(noOfNodes * noOfNodes).reshape(noOfNodes, noOfNodes),
                           'indexToCanOrd': np.zeros(noOfNodes)}
        for i in range(noOfNodes):
            self.G.add_node(i, id=-1, chord=0, mark=False, out=False)
            # t = list(tuple(map(int,input().split())) for r in range(graph.edgecnt))
            rows, cols = np.where(matrix == 1)
            edges = zip(rows.tolist(), cols.tolist())
            self.G.add_edges_from(edges)

        # for x in edge_set:
        #     self.G.add_edge(x[0], x[1])

        # self.G.add_edges_from(t)
        self.graphs.append(self.G)
        is_planar, G2 = nx.check_planarity(self.G, False)
        if (not is_planar):
            return False
        print(self.node_coordinate)
        # nx.draw(self.G,self.node_coordinate,with_labels=True, font_weight='bold')
        # plt.gca().invert_yaxis()
        # plt.savefig("inputgraph.png")
        # plt.show()    #Uncomment above 4 lines to see input graph
        return True

    def runWithArguments(self, noOfNodes, v1, v2, vn, triplet, graph, matrix, cip):

        # print("v1 : {}".format(v1))
        # print("v1 : {}".format(v2))
        # print("v1 : {}".format(vn))

        # self.G.add_edges_from(t)
        # priority_order = ""
        # initialisations
        canord = np.zeros(noOfNodes, dtype=int)
        # if(priority_order!=""):
        #     self.priority_order = list(map(int, re.findall(r'\d+', priority_order)))
        #     if v1 in self.priority_order:
        #         self.priority_order.remove(v1)
        #     if v2 in self.priority_order:
        #         self.priority_order.remove(v2)

        self.triplet = triplet
        self.lshapegraph = graph
        self.lshapematrix = matrix
        self.cip = cip
        self.canonical_order(canord, v1, v2, vn, noOfNodes)  # TODO find v1,v2,vn

    def canonical_order(self, canord, v1, v2, vn, n):
        n = int(n)
        # print("Priority_Order : {}".format(self.priority_order))
        mark = np.zeros((n,), dtype=bool)
        chord = np.zeros((n,), dtype=bool)
        out = np.zeros((n,), dtype=bool)
        visited = np.zeros(n, dtype=int)

        canord[v1] = 0

        mark[v1] = True
        mark[v2] = True
        # mark[self.lshapegraph.north] = True
        # mark[self.lshapegraph.east] = True

        out[v1] = True
        out[v2] = True
        out[vn] = True
        # out[self.lshapegraph.northeast] = True

        print("\n\nIteration {}".format(1))
        print("Marked: {}".format(v1))
        print("Neighbors of it: {}".format(list(self.G.neighbors(v1))))
        print("Canonical Order: {}".format(canord))
        self.graph_data['iteration'][0] = 1
        self.graph_data['marked'][0] = v1
        self.graph_data['indexToCanOrd'][0] = v1  # map from index to its canord
        self.graph_data['currentCanonicalOrder'][0] = canord
        # self.graph_data['neighbors'][]([])
        canord[v2] = 1

        print("\n\nIteration {}".format(2))
        print("Marked: {}".format(v2))
        print("Neighbors of it: {}".format(list(self.G.neighbors(v2))))
        print("Canonical Order: {}".format(canord))

        self.graph_data['iteration'][1] = 2
        self.graph_data['marked'][1] = v2
        self.graph_data['indexToCanOrd'][1] = v2
        self.graph_data['currentCanonicalOrder'][1] = canord
        news = (self.lshapegraph.north, self.lshapegraph.west, self.lshapegraph.east, self.lshapegraph.south)
        secondary_vertices = set()
        # for tempNeighbor in list(self.G.neighbors(self.lshapegraph.north)):
        #     secondary_vertices.add(tempNeighbor)

        # secondary_vertices = secondary_vertices.difference(news)
        # self.updateVisited(visited,secondary_vertices)
        
        # for tempNeighbor in list(self.G.neighbors(self.lshapegraph.east)):
        #     secondary_vertices.add(tempNeighbor)
        # # secondary_vertices  = {x for x in tempList}
        # secondary_vertices = secondary_vertices.difference(news)
        # self.updateVisited(visited,secondary_vertices)
        # canord[vn] = n-1
        # # canord[vn-1] = self.lshapegraph.northeast

        visited[self.lshapegraph.north] = 2
        visited[self.lshapegraph.east] = 1

        print("no of cip {}".format(len(self.cip)))
        if(len(self.cip)>4): #atmost 4 CIP
            print("cip>4 in canonical ordering ")
            for i in range(n - 1, 1, -1):
                print("\n\nIteration {}".format(n + 2 - i))
                print("Chords : {}".format(chord))


                # Additions for Lshaped
                selectedNeighbor = np.zeros(n,dtype="bool")
                for j in range(0,n):
                    if visited[j]>=2:
                        selectedNeighbor[j] = True
                    else:
                        selectedNeighbor[j] = False
                temp_array = np.logical_and(np.logical_and(np.logical_and(np.logical_not(mark), out), np.logical_not(chord)),selectedNeighbor)
                # print(temp_array)
                poss_vertex = np.where(temp_array == True)[0].flatten()
                # print(poss_vertex)
                print("Options for Next Iteration: {}".format(poss_vertex))


                vk = poss_vertex[0]
                canord[vk] = i
                mark[vk] = True
                print("Marked: {} as {}".format(vk,i))
                neighbors = list(self.G.neighbors(vk))
                # indices = np.where(mark == True)
                # neighbors = np.delete(neighbors, np.where(neighbors == indices))
                print(neighbors)
                neighborlist = []
                for j in neighbors:
                    if mark[j] == False or j == v1 or j == v2:
                        neighborlist.append(j)
                        # The neighbors to which it is adjacent can also be saved in a separate data structure which is accessible outside this function
                # here we need only those neighbours which have not been marked in the canord yet. Therefore, we need to take an and with
                # and with the not marked thing as well.
                # These neighbors are now the ones which are the next present on the boundary
                neighbors = neighborlist
                print("New Outerface of vk: {} ".format(neighbors))
                self.updateVisited(visited,neighbors)
                for j in neighbors:
                    out[j] = True
                self.updatechord(chord, mark, out, v1, v2)
                print("Canonical Order: {}".format(canord))
                # self.displayGraph(canord,n)
                self.updateGraphData(n, i, vk, neighbors, canord)

        else: #CIP>4
            print("cip<=4 in canonical ordering ")
            # neighA = self.G.neighbors(self.triplet[0]);
            # neighB = self.G.neighbors(self.triplet[1]);
            # neighC = self.G.neighbors(self.triplet[2]);
            # x = [i for i in neighA if i in neighB]
            # y = [i for i in neighB if i in neighC]
            L = list(self.G.neighbors(self.triplet[1]))
            L.remove(self.triplet[0])
            L.remove(self.triplet[2])
            L.remove(self.lshapegraph.northeast)

            for i in range(n - 1, 1, -1):
                print("\n\nIteration {}".format(n + 2 - i))
                print("Chords : {}".format(chord))
                selectedNeighbor = np.zeros(n,dtype="bool")
                for j in range(0,n):
                    if visited[j]>=2:
                        selectedNeighbor[j] = True
                    else:
                        selectedNeighbor[j] = False
                temp_array = np.logical_and(np.logical_and(np.logical_and(np.logical_not(mark), out), np.logical_not(chord)),selectedNeighbor)
                # print(temp_array)
                poss_vertex = np.where(temp_array == True)[0].flatten()
                # print(poss_vertex)
                print("Options for Next Iteration: {}".format(poss_vertex))
                print("L is: {}".format(L))
                print(poss_vertex[0])
                print(self.triplet[1])
                if(poss_vertex[0]==self.triplet[1] or poss_vertex[0] in L):
                # Additions for Lshaped
                    if mark[self.triplet[0]] and mark[self.triplet[2]]:
                        vk = poss_vertex[0]
                    else:
                        vk = self.getNext(poss_vertex,self.triplet[1],L)
                else:
                    vk = poss_vertex[0]

                        
                
                # next = self.getNextPossibility(poss_vertex,self.triplet[1])
                # if (next == self.triplet[1]):
                #     if (mark[self.triplet[0]] and mark[self.triplet[2]]):
                #         vk = next
                #     else:
                #         next = self.getNextPossibility(poss_vertex,self.triplet[1],x,y)
                #         vk = next
                # elif (next == x or next==y):
                #     if(mark[self.triplet[1]]):
                #         vk = next
                #     else:
                #         next = self.getNextPossibility(poss_vertex,x,y)
                #         vk = next
                # else:
                #     vk = next

                canord[vk] = i
                mark[vk] = True
                print("Marked: {} as {}".format(vk,i))
                neighbors = list(self.G.neighbors(vk))
                # indices = np.where(mark == True)
                # neighbors = np.delete(neighbors, np.where(neighbors == indices))
                print(neighbors)
                neighborlist = []
                for j in neighbors:
                    if mark[j] == False or j == v1 or j == v2:
                        neighborlist.append(j)
                        # The neighbors to which it is adjacent can also be saved in a separate data structure which is accessible outside this function
                # here we need only those neighbours which have not been marked in the canord yet. Therefore, we need to take an and with
                # and with the not marked thing as well.
                # These neighbors are now the ones which are the next present on the boundary
                neighbors = neighborlist
                print("New Outerface of vk: {} ".format(neighbors))
                self.updateVisited(visited,neighbors)
                for j in neighbors:
                    out[j] = True
                self.updatechord(chord, mark, out, v1, v2)
                print("Canonical Order: {}".format(canord))
                # self.displayGraph(canord,n)
                self.updateGraphData(n, i, vk, neighbors, canord)
            
        self.graph_data['neighbors'].append([0])
        self.graph_data['neighbors'].append([])
        self.graph_data['neighbors'].reverse()
        print("\nFinal Canonical Order: {}".format(canord))
        print("\nIndex to Canord (10 at 0'th index means canonical order has 0 marked for node 10): {}".format(
            self.graph_data['indexToCanOrd']))
        print("Secondary Vertices: {}".format(secondary_vertices))
        print("Triplet = {}".format(self.triplet))
        print("OLD NEWS NE= {},{},{},{},{}".format(self.lshapegraph.north, self.lshapegraph.east, self.lshapegraph.west,
                                                   self.lshapegraph.south, self.lshapegraph.northeast))
        # self.displayGraph(canord,n)
        # plt.show()    #DEBUG TODO

        # for i in range(0,n, 1):
        #     print("i : {}",self.graph_data['neighbors'][i])
        # fig, axes = plt.subplots(nrows=1, ncols=2)
        # ax = axes.flatten()
        # fig.set_size_inches(15.0, 5.25)
        # ax[0].invert_yaxis()
        # ax[0].set_title('Input Graph')
        # ax[1].invert_yaxis()
        # ax[1].set_title('Output Graph after Canonical Order')

        # nx.draw(self.graphs[0],self.node_coordinate,with_labels=True, font_weight='bold',ax = ax[0])
        # ax[0].set_axis_off()
        # nx.draw(self.graphs[1],self.new_node_coordinate,with_labels=True, font_weight='bold',ax = ax[1])
        # ax[1].set_axis_off()
        # plt.savefig("./source/polygonal/lastcanonicalorder.png")
        # plt.show() #ON

    def getNext(self,poss_vertex,b,L):
        for next in poss_vertex:
            if (next!=b and next not in L):
                return next;
        print("No options available for next iteration. Should not pop according to algo")
        return -2
        
    # def getNextPossibility(self,poss_vertex,x1=-1,x2=-1,x3=-1):
    #     for next in poss_vertex:
    #         if(next!=x1 and next!=x2 and next!=x3):
    #             return next 
    #     print("No options available for next iteration. Should not pop according to algo")
    #     return -1

    def updateVisited(self,visited,secondary_vertices):
        for node in secondary_vertices:
            visited[node]+=1
        print("Initial Visted: {}".format(visited));


    def updateGraphData(self, n, i, vk, neighbors, canord):
        self.graph_data['iteration'][n + 2 - i - 1] = n + 2 - i
        self.graph_data['marked'][n + 2 - i - 1] = vk
        self.graph_data['indexToCanOrd'][i] = vk
        # self.graph_data['neighbors'][i]=neighbors
        self.graph_data['neighbors'].append(neighbors)

        self.graph_data['currentCanonicalOrder'][n + 2 - i - 1] = canord

    def displayGraph(self, canord, n):
        int2label = {}
        for i in range(n):
            int2label[i] = canord[i]
            self.new_node_coordinate[canord[i]] = self.node_coordinate[i]
        self.G = nx.relabel_nodes(self.G, int2label)
        self.graphs.append(self.G)
        # nx.draw(self.G,self.new_node_coordinate,with_labels=True, font_weight='bold') #Uncomment these 3 lines to see output graph
        # plt.gca().invert_yaxis()

    def updatechord(self, chord, mark, out, v1, v2):

        outer = np.logical_and(out, np.logical_not(mark))
        outer[v1] = True
        outer[v2] = True
        outer_surface = np.where(outer == True)[0]
        print("Outer Surface {}".format(outer_surface))  # On For Debug
        out_neighbor_count = np.zeros(np.size(outer_surface), dtype=int)

        for i in range(0, np.size(outer_surface)):
            for j in range(0, np.size(outer_surface)):
                if (i != j and self.G.has_edge(outer_surface[i], outer_surface[j])):
                    out_neighbor_count[i] += 1
            # print("out_neighbor_count[{}] : {}".format(i,out_neighbor_count[i]))
            if (out_neighbor_count[i] > 2):
                chord[outer_surface[i]] = True
            else:
                chord[outer_surface[i]] = False

        # print("Outer Neighbor Count {}".format(out_neighbor_count)) #On For Debug

        return


if __name__ == "__main__":
    canonical().run()
