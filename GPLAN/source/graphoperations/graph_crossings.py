"""
This file handles graphs that have a planar embedding but input has crossings (eg: K4)
This uses a an algorithm known as Sweep-Line Algorithm from domain of Computational Geometry

For more info:
    (a) https://www.thealgorists.com/Algo/SweepLine
"""

from operator import le
from turtle import right
import numpy as np
class Point:
    def __init__(self,x: float,y: float) -> None:
        self.x = x
        self.y = y

def display(p: Point, q: Point) -> str:

    return "{(" + str(p.x) + ", " + str(p.y) + "), " + "(" + str(q.x) + ", " + str(q.y) + ")}"

def eq(p: Point, q: Point) -> bool:

    if((p.x == q.x) and (p.y == q.y)):
        return True
    
    return False

def sort_by_x(points: list) -> list:
    """
    This function is used to sort the points in the list in the ascending order of the x-coordinates.

    Args:
        points (list): This is a list of objects of class Point

    Returns:
        list: Returns sorted list of Points
    """
    # Basis of sorting is x coordinate of left endpoint
    # So key is the 0th element of each tuple in the list

    return sorted(points, key= lambda p: p.x)

def orientation(p1: Point, p2: Point, p3: Point) -> int:
    """
    Slope of line segment (p1, p2): M = (y2 - y1)/(x2 - x1)
    Slope of line segment (p2, p3): N = (y3 - y2)/(x3 - x2)

    If  M > N, the orientation is clockwise (right turn). Using above values of M and N, we can conclude that, 
    the orientation depends on sign of  below expression: 

    val = (y2 - y1)*(x3 - x2) - (y3 - y2)*(x2 - x1)

    Clockwise if val is positive (M > N); Counterclockwise if val is negative (M < N); Collinear if val is 0
    (Note: We use this function to decide whether two lines intersect or not)

    Args:
        p1 (Point): First point
        p2 (Point): Second point
        p3 (Point): Third point

    Returns:
        int: We return 0, 1 or 2 depending on whether the 3 points are collinear, clockwise or counterclockwise respectively
    """
    val = ((p2.y - p1.y) * (p3.x - p2.x)) - ((p2.x - p1.x) * (p3.y - p2.y))
    if (val > 0):
         
        # Clockwise orientation
        return 1
    elif (val < 0):
         
        # Counterclockwise orientation
        return 2
    else:
         
        # Collinear orientation
        return 0

def onSegment(p1: Point, p2: Point, p3: Point) -> bool:
    """
    Given three collinear points p1, p2, p3, the function checks if point p2 lies on line segment 'p1p3'

    Args:
        p1 (Point): First point
        p2 (Point): Second point
        p3 (Point): Third point

    Returns:
        bool: Returns true if p2 lies on the segment p1p3 else returns false
    """
    if ( (p2.x <= max(p1.x, p3.x)) and (p2.x >= min(p1.x, p3.x)) and
           (p2.y <= max(p1.y, p3.y)) and (p2.y >= min(p1.y, p3.y))):
        return True
    return False

def doIntersect_endpts(p1: Point,q1: Point,p2: Point,q2: Point) -> bool:
    """
    (Note: In this function if one of the wnspoints of line1 is same as an endpoint of line2 we don't consider it as intersection)
    For intersection of two lines line1 having endpoints p1, q1 and line2 having endpoints p2, q2 we have the following cases:

    General Case: 
    (p1, q1, p2) and (p1, q1, q2) have different orientations and (p2, q2, p1) and (p2, q2, q1) have different orientations

    Special Case:
    (p1, q1, p2), (p1, q1, q2), (p2, q2, p1), and (p2, q2, q1) are all collinear and
    the x-projections of (p1, q1) and (p2, q2) intersect 
    the y-projections of (p1, q1) and (p2, q2) intersect

    Args:
        p1 (Point): Left endpoint of line1
        q1 (Point): Right endpoint of line1
        p2 (Point): Left endpoint of line2
        q2 (Point): Right endpoint of line2

    Returns:
        bool: Returns True if line1 and line2 intersect 
    """
     
    # Find the 4 orientations required for
    # the general and special cases
    o1 = orientation(p1, q1, p2)
    o2 = orientation(p1, q1, q2)
    o3 = orientation(p2, q2, p1)
    o4 = orientation(p2, q2, q1)
 
    # Any two of the endpoints are equal
    if((eq(p1,p2)) or (eq(p1,q2)) or (eq(q1,p2)) or (eq(q1,q2))):
        return False
    
    # All endpoints are distinct
    else:    
        # General case
        if ((o1 != o2) and (o3 != o4)):
            return True
    
        # Special Cases
        # p1 , q1 and p2 are collinear and p2 lies on segment p1q1
        if ((o1 == 0) and onSegment(p1, p2, q1)):
            return True
    
        # p1 , q1 and q2 are collinear and q2 lies on segment p1q1
        if ((o2 == 0) and onSegment(p1, q2, q1)):
            return True
    
        # p2 , q2 and p1 are collinear and p1 lies on segment p2q2
        if ((o3 == 0) and onSegment(p2, p1, q2)):
            return True
    
        # p2 , q2 and q1 are collinear and q1 lies on segment p2q2
        if ((o4 == 0) and onSegment(p2, q1, q2)):
            return True
    
        # If none of the cases
        return False

def get_points_edges(x_list: list, y_list: list, adj: np.array) -> list and dict:
    """
    This function gets the list of x and y coordinates ordered by vertex id (= index) and the adjacency matrix 
    to return the list of points (objects of class Point) and a dictionary of the edges.

    Args:
        x_coord (list): List of x coordinates ordered by vertex id
        y_coord (list): List of y coordinates ordered by vertex id
        adj (np.array): Adjacency matrix

    Returns:
        list and dict: list of points and dictionary of edges is returned
    """
    points = []

    # Creates list of points by converting it to class objects
    for i in range(len(x_list)):
        points.append(Point(x_list[i],y_list[i]))
    
    edges = dict()

    # If two vertices are adjacent, we assign the edge an id (key of dict)
    # and denote edge by list of point objects [left_pt, right_point] (val of the dict)
    key_var = 0
    for i in range(len(x_list)):
        for j in range(i+1,len(y_list)):

            if (adj[i][j] == 1):
                if(points[i].x <= points[j].x):
                    edges[key_var] = [points[i], points[j]]
                else:
                    edges[key_var] = [points[j], points[i]]
                key_var += 1
    
    return points, edges


def check_intersection(x_coord: list, y_coord: list, A: np.array) -> bool:
    """
    This functions moves a vertical line, starting from x = min(x) among the lines and till x = max(x) among the lines.
    Whenever this sweep line meets left endpoint of a line, that line's index is added into a self-balancing binary search tree.
    We check for the intersection of the most recently added lines. If intersection found we return true, else we continue. When
    we encounter a right endpoint, the line's index is deleted from the tree and we continue.

    Args:
        x_coord (list): List of x coordinates ordered by vertex id
        y_coord (list): List of y coordinates ordered by vertex id
        A (np.array): Adjacency matrix

    Returns:
        bool: Returns true if any two edges intersect at a point other than the endpoints/vertices
    """
    points, edges = get_points_edges(x_coord, y_coord, A)
    left_pts = [x[0] for x in list(edges.values())]
    right_pts = [x[1] for x in list(edges.values())]

    # A list to keep track of traversed vertices
    traversed = []

    # We have a sorted list of points for traversal
    sorted_by_x = sorted(points, key= lambda p : p.x)

    indices_p = [i for i, x in enumerate(left_pts) if x == sorted_by_x[0]]
    check_count = len(indices_p)

    # We stop at each point
    for p in sorted_by_x:

        # If it is left endpoint of an edge, add it edge id to traversed
        if(p in left_pts):
            # Get all indices where p is the left endpoint
            indices_p = [i for i, x in enumerate(left_pts) if x == p]
            # Add all elements of indices_p to traversed
            traversed.extend(indices_p)
            # We don't need to check if edges added together intersect
            # since they have a common endpoint
            if(len(traversed) > len(indices_p)):

                for i in indices_p:
                    for j in range(len(traversed) - len(indices_p) - check_count, len(traversed) - len(indices_p)):

                        t = traversed[j]
                        if(doIntersect_endpts(edges.get(i)[0], edges.get(i)[1], edges.get(t)[0], edges.get(t)[1])):
                            return True
                        else:
                            pass
            
            # Since edges of first point have been added
            else:
                pass

            check_count = len(indices_p)
        
        # If it is right endpoint of an edge, the corresponding edge id is removed from traversed
        if((p in right_pts) and (right_pts.index(p) in traversed)):
            traversed.remove(right_pts.index(p))
            if((len(traversed) == 0) and (p == sorted_by_x[-1])):
                return False

def main():
    def test_orientation() -> None:
        p1 = Point(0, 0)
        p2 = Point(4, 4)
        p3 = Point(1, 2)
        
        o = orientation(p1, p2, p3)
        
        if (o == 0):
            print("Orientation of the points: (" + str(p1.x) + ", " + str(p1.y) + "), (" + str(p2.x) + ", " + str(p2.y) + "), (" + str(p3.x) + ", " + str(p3.y) + "): Linear")
        elif (o == 1):
            print("Orientation of the points: (" + str(p1.x) + ", " + str(p1.y) + "), (" + str(p2.x) + ", " + str(p2.y) + "), (" + str(p3.x) + ", " + str(p3.y) + "): Clockwise")
        else:
            print("Orientation of the points: (" + str(p1.x) + ", " + str(p1.y) + "), (" + str(p2.x) + ", " + str(p2.y) + "), (" + str(p3.x) + ", " + str(p3.y) + "): CounterClockwise")
        
    def test_doIntersect_endpts() -> None:
        p1 = Point(1, 1)
        q1 = Point(10, 1)
        p2 = Point(1, 2)
        q2 = Point(10, 2)
        
        if doIntersect_endpts(p1, q1, p2, q2):
            print("Does the lines l1 joining " + display(p1,q1) + "and l2 joining " + display(p2,q2) + "?: Yes")
        else:
            print("Does the lines l1 joining " + display(p1,q1) + "and l2 joining " + display(p2,q2) + "?: No")
        
        p1 = Point(10, 0)
        q1 = Point(0, 10)
        p2 = Point(0, 0)
        q2 = Point(10,10)
        
        if doIntersect_endpts(p1, q1, p2, q2):
            print("Does the lines l1 joining " + display(p1,q1) + "and l2 joining " + display(p2,q2) + "?: Yes")
        else:
            print("Does the lines l1 joining " + display(p1,q1) + "and l2 joining " + display(p2,q2) + "?: No")
        
        p1 = Point(-5,-5)
        q1 = Point(0, 0)
        p2 = Point(1, 1)
        q2 = Point(10, 10)
        
        if doIntersect_endpts(p1, q1, p2, q2):
            print("Does the lines l1 joining " + display(p1,q1) + "and l2 joining " + display(p2,q2) + "?: Yes")
        else:
            print("Does the lines l1 joining " + display(p1,q1) + "and l2 joining " + display(p2,q2) + "?: No")
        
        p1 = Point(-5,-5)
        q1 = Point(0, 0)
        p2 = Point(0, 0)
        q2 = Point(10, 11)
        
        if doIntersect_endpts(p1, q1, p2, q2):
            print("Does the lines l1 joining " + display(p1,q1) + "and l2 joining " + display(p2,q2) + "?: Yes")
        else:
            print("Does the lines l1 joining " + display(p1,q1) + "and l2 joining " + display(p2,q2) + "?: No")
    
    def test_check_intersection():

        # Example 1
        x1 = np.array([0, 5, 20, 5])
        y1 = np.array([10, 0, 10, 20])
        A1 = np.array([[0, 1, 1, 1], [1, 0, 1, 1], [1, 1, 0, 1], [1, 1, 1, 0]])
        if(check_intersection(x1,y1,A1)):
            print("Your graph is not planar")
        else:
            print("Your graph is planar")
        
        # Example 2
        x2 = np.array([0, 5, 20, 5])
        y2 = np.array([10, 0, 10, 20])
        A2 = np.array([[0, 1, 1, 1], [1, 0, 1, 0], [1, 1, 0, 1], [1, 0, 1, 0]])
        if(check_intersection(x2,y2,A2)):
            print("Your graph is not planar")
        else:
            print("Your graph is planar")

        # Example 3
        x3 = np.array([0, 2, 5, 9, 5, 2])
        y3 = np.array([10, 0, 0, 10, 20, 20])
        A3 = np.array([[0, 1, 0, 1, 0, 1], [1, 0, 1, 0, 0, 0], [0, 1, 0, 1, 0, 0], [0, 0, 1, 0, 1, 0], [0, 0, 0, 1, 0, 1], [1, 0, 0, 0, 1, 0]])
        if(check_intersection(x3,y3,A3)):
            print("Your graph is not planar")
        else:
            print("Your graph is planar")
        
        # Example 4
        x4 = np.array([0, 2, 5, 9, 5, 2])
        y4 = np.array([10, 0, 0, 10, 20, 20])
        A4 = np.array([[0, 1, 0, 1, 0, 1], [1, 0, 1, 0, 1, 0], [0, 1, 0, 1, 0, 0], [0, 0, 1, 0, 1, 0], [0, 1, 0, 1, 0, 1], [1, 0, 0, 0, 1, 0]])
        if(check_intersection(x4,y4,A4)):
            print("Your graph is not planar")
        else:
            print("Your graph is planar")
        
        # Example 5
        x5 = np.array([244,235,352,359])
        y5 = np.array([253,122,105,324])
        A5 = np.array([[0, 1, 1, 1], [1, 0, 1, 1], [1, 1, 0, 1], [1, 1, 1, 0]])
        if(check_intersection(x5,y5,A5)):
            print("Your graph is not planar")
        else:
            print("Your graph is planar")
        
        # Example 6
        x6 = np.array([0,10,15,18,25,35,45])
        y6 = np.array([10,15,0,7,13,2,10])
        A6 = np.array([[0, 1, 0, 0, 0, 1, 0],
                       [1, 0, 1, 0, 1, 0, 0],
                       [0, 1, 0, 1, 0, 0, 1],
                       [0, 0, 1, 0, 1, 0, 0],
                       [0, 1, 0, 1, 0, 1, 0],
                       [1, 0, 0, 0, 1, 0, 1],
                       [0, 0, 1, 0, 0, 1, 0]])
        if(check_intersection(x6,y6,A6)):
            print("Your graph is not planar")
        else:
            print("Your graph is planar")
        
        # Example 7
        x7 = np.array([0,5,10,5,15])
        y7 = np.array([10,0,10,15,5])
        A7 = np.array([[0, 1, 1, 0, 1],
                       [1, 0, 1, 1, 0],
                       [1, 1, 0, 0, 0],
                       [0, 1, 0, 0, 0],
                       [1, 0, 0, 0, 0]])
        if(check_intersection(x7,y7,A7)):
            print("Your graph is not planar")
        else:
            print("Your graph is planar")

        # Example 8
        x8 = np.array([2,4,5,4,2,1,2,4])
        y8 = np.array([4,4,2,0,0,2,2,2])
        A8 = np.array([[0, 1, 0, 0, 0, 1, 0, 1],
                       [1, 0, 1, 0, 0, 0, 1, 0],
                       [0, 1, 0, 1, 0, 0, 0, 0],
                       [0, 0, 1, 0, 1, 0, 0, 0],
                       [0, 0, 0, 1, 0, 1, 0, 0],
                       [1, 0, 0, 0, 1, 0, 0, 0],
                       [0, 1, 0, 0, 0, 0, 0, 0],
                       [1, 0, 0, 0, 0, 0, 0, 0]])
        
        if(check_intersection(x8,y8,A8) == True):
            print("Your graph is not planar")
        else:
            print("Your graph is planar")
        print(check_intersection(x8,y8,A8))

    test_check_intersection()
    


if __name__ == "__main__":
    main()