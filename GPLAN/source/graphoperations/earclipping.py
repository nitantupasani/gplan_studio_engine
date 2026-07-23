"""Ear Clipping Algorithm 

    This algorithm divides a polygon into triangles.
    Bitbucket. (n.d.). Retrieved December 13, 2021, from https://bitbucket.org/nils_olovsson/ear_clipping_triangulation. 
"""

import numpy as np

class Node:
    """
        Node element in a DoubleLinkedList.
        Each node in a valid list is associated with a value/data element and
        with its left and right neighbor.
        [Prev. node]<--[Node]-->[Next node]
                         |
                       [Data]
    """

    def __init__(self, data):
        self.data = data
        self.prev = None
        self.next = None

class DoubleLinkedList:
    """
        A double linked list. Each element keeps a reference to both left and
        right neighbor. This allows e.g. for easy removal of elements.
        The list is circular and is usually considered traversed when the next element
        is the same element as when when we started.
    """

    def __init__(self):
        self.first = None
        self.size  = 0

    def __str__(self):
        if self.first==None:
            return '[]'
        msg = '['
        msg += str(self.first.data)
        node = self.first.next
        while node != self.first:
            msg += ', ' + str(node.data)
            node = node.next
        msg += ']'
        return msg

    def append(self, data):
        self.size += 1
        if self.first == None:
            self.first = Node(data)
            self.first.prev = self.first
            self.first.next = self.first
            return
        node = Node(data)
        last = self.first.prev
        node.prev = last
        node.next = self.first
        last.next = node
        self.first.prev = node

    def remove(self, item):
        if self.first==None:
            return
        rmv = None
        node = self.first
        if node.data == item:
            rmv = node
        node = node.next
        while not rmv and node != self.first:
            if node.data == item:
                rmv = node
            node = node.next
        if rmv:
            nxt = rmv.next
            prv = rmv.prev
            prv.next = nxt
            nxt.prev = prv
            self.size -= 1
            if rmv == self.first:
                self.first = nxt
            if rmv == self.first:
                self.first = None
        return

    def count(self):
        if self.first==None:
            return 0
        i = 1
        node = self.first.next
        while node != self.first:
            i+=1
            node = node.next
        return i

    def flatten(self):
        if self.first==None:
            return []
        l = []
        node = self.first
        l.append(node.data)
        node = self.first.next
        while node != self.first:
            l.append(node.data)
            node = node.next
        return l

def angleCCW(a, b):
    """
        Counter clock wise angle (radians) from normalized 2D vectors a to b
    """
    dot = a[0]*b[0] + a[1]*b[1]
    det = a[0]*b[1] - a[1]*b[0]
    angle = np.arctan2(dot, det)
    if angle<0.0 :
        angle = 2.0*np.pi + angle
    return angle

def polygon_area(vertices):
    n = len(vertices)
    area = 0
    for i in range(n):
        x1, y1 = vertices[i]
        x2, y2 = vertices[(i + 1) % n]
        area += x1 * y2 - y1 * x2
    return abs(area) / 2

def isConvex(vertices, vert_prev, vert_crnt, vert_next):
    
    original_area = polygon_area(vertices)
    new_vertices = []
    for vertice in vertices:
        if ((vertice[0] == vert_crnt[0]) and (vertice[1] == vert_crnt[1])) :
            pass
        else:
            new_vertices.append(vertice)
    
    # Area of the modified polygon
    new_area = polygon_area(new_vertices)
    return original_area - new_area >= -1e-7   # Return True if areas are almost equal


def area(x1, y1, x2, y2, x3, y3):
    return abs((x1 * (y2 - y3) + x2 * (y3 - y1) 
                + x3 * (y1 - y2)) / 2.0)

def insideTriangle(a, b, c, p):
    x1 = a[0]
    x2 = b[0]
    x3 = c[0]
    x = p[0]
    y1 = a[1]
    y2 = b[1]
    y3 = c[1]
    y = p[1]
    # Calculate area of triangle ABC
    A = area (x1, y1, x2, y2, x3, y3)
 
    # Calculate area of triangle PBC 
    A1 = area (x, y, x2, y2, x3, y3)
     
    # Calculate area of triangle PAC 
    A2 = area (x1, y1, x, y, x3, y3)
     
    # Calculate area of triangle PAB 
    A3 = area (x1, y1, x2, y2, x, y)
     
    # Check if sum of A1, A2 and A3 
    # is same as A
    Total = A1+A2+A3
    if(abs(A - Total)<1e-9):
        return True
    else:
        return False

def triangulate(vertices, max_iterations=0):
    """
        Triangulation of a polygon in 2D.
        Assumption that the polygon is simple, i.e has no holes, is closed and
        has no crossings and also that it the vertex order is counter clockwise.
        https://geometrictools.com/Documentation/TriangulationByEarClipping.pdf
    """

    n, m = vertices.shape
    indices = np.zeros([n-2, 3], dtype=np.int64)

    #print('shape: {}x{}'.format(n,m))

    vertlist = DoubleLinkedList()
    for i in range(0, n):
        vertlist.append(i)

    index_counter = 0
    it_counter = 0
    stall_counter = 0  # iterations since the last ear was clipped

    # Simplest possible algorithm. Create list of indexes.
    # Find first ear vertex. Create triangle. Remove vertex from list
    # Do this while number of vertices > 2.
    node = vertlist.first
    #while vertlist.size > 2 and it_counter < 10:
    while vertlist.size > 2 and (max_iterations<=0 or max_iterations>index_counter):
        #print(it_counter)
        #print('vertlist.size: {}'.format(vertlist.size))
        i = node.prev.data
        j = node.data
        k = node.next.data

        vert_prev = vertices[i,:]
        vert_crnt = vertices[j,:]
        vert_next = vertices[k,:]

        is_convex = isConvex(vertices,vert_prev, vert_crnt, vert_next)
        is_ear = True
        if is_convex:
            test_node = node.next.next
            while test_node!=node.prev and is_ear:
                vert = vertices[test_node.data,:]
                is_ear = not insideTriangle(vert_prev, vert_crnt, vert_next, vert)
                test_node = test_node.next
        else:
            is_ear = False
        if is_ear and area(vert_prev[0], vert_prev[1], vert_crnt[0], vert_crnt[1], vert_next[0], vert_next[1]) == 0:
            # Zero-area (collinear) ears are normally skipped, but once a full
            # sweep has found no clippable ear they are the only way forward:
            # accept them then - the emitted triangle is degenerate in the
            # embedding but combinatorially valid (callers only consume the
            # vertex triples/edges), and the polygon keeps shrinking.
            if stall_counter <= vertlist.size:
                is_ear = False
        if is_ear:
            indices[index_counter, :] = np.array([i, j, k], dtype=np.int64)
            index_counter += 1
            vertlist.remove(node.data)
            stall_counter = 0
        else:
            stall_counter += 1
            if stall_counter > vertlist.size:
                # A full sweep found no clippable ear: the remaining polygon is
                # degenerate (collinear/duplicate points, common in
                # planar_layout embeddings). Drop the current vertex without
                # emitting a triangle so the loop terminates instead of
                # spinning forever.
                vertlist.remove(node.data)
                stall_counter = 0

        it_counter += 1
        node = node.next
    indices = indices[0:index_counter, :]
    return indices