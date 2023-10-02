# from ssl import create_default_context
import tkinter as tk
# import turtle
# from source.polygonal.draw import DrawOuterBoundary
from source.polygonal.polygui import PolyGUI 
from source.polygonal.limits import find_limits 
# import time


class Room:
    def __init__(self):
        self.coords = []
        self.leftDisecDone = False
        self.rightDisecDone = False
        self.disecAllowed = True
        self.noOfSides = 0
    def coord():
        return self.coords

class dissected:

    def __init__(self,graph_data,pen,color_list,shape,adj_mat,innerBoundary = [[200,400],[400,200],[200,0],[-200,0],[-400,200],[-200,400]]):
        pen.width(1.5)
        pen.color('black')
        # pen.write(1,font=("Arial", 20, "normal"))
        print("\nReceieved Inner Boundary = {}\n".format(innerBoundary))
        print("\nReceieved Shape = {}\n".format(shape))
        self.adj_mat = adj_mat
        self.graph_data = graph_data
        self.pen = pen
        self.noOfNodes = len(self.graph_data['iteration'])
        self.scale = 0.5*self.noOfNodes/10 #MODIFY SCALE
        self.divFactor_num =   4
        self.divFactor_den = 5
        self.correctCanonicalOrder = self.graph_data['currentCanonicalOrder'][self.noOfNodes-1]
        self.coordinatepoints  = {} #This is the dictionary which will hold the initial coordinates of the figure when they are being constructed
        self.innerBoundary = innerBoundary #this is the outer boundary that is specified by the user(can also be NULL) 
        self.outerBoundary = []
        self.lowestPointIndex = 0 #for disections in case of custom rooms
        self.rooms = []  #this is the list of the rooms data structure, please please please remember! 
        self.outerPath = [0,2,1] #this stores the path of the outer surface -> used for finding the leftmost and righnmost neighbors in the canonical order 
        self.shape = shape
        polygui = PolyGUI(pen,graph_data,self.rooms,color_list, self.innerBoundary)
        if(shape=="Pentagon"):
            polygui.createPentagon(self.coordinatepoints)
            polygui.createInitalRoomsForPentagon(self.coordinatepoints)
        elif(shape=="Hexagon"):
            polygui.createHexagon(self.coordinatepoints)
            polygui.createInitalRoomsForHexagon(self.coordinatepoints)
        else:
            self.lowestPointIndex= polygui.createCustom(self.outerBoundary)
        self.mainDisectionFunction()
        polygui.startDisection()
        find_limits(self.adj_mat,self.rooms)


    def createDefaultDisectionsforPentagon(self):
        #first we initialise the rooms 1,2,3, which will always exist
        Room1 = Room()
        Room1.coords.append(self.coordinatepoints[1])
        Room1.coords.append(self.coordinatepoints[6])
        Room1.coords.append(self.coordinatepoints[7])
        Room1.coords.append(self.coordinatepoints[8])
        Room1.coords.append(self.coordinatepoints[4])
        Room1.coords.append(self.coordinatepoints[5])
        Room1.disecAllowed = False
        self.rooms.append(Room1)
        Room2 = Room()
        Room2.coords.append(self.coordinatepoints[9])
        Room2.coords.append(self.coordinatepoints[2])
        Room2.coords.append(self.coordinatepoints[3])
        Room2.coords.append(self.coordinatepoints[8])
        Room2.coords.append(self.coordinatepoints[11])
        Room2.coords.append(self.coordinatepoints[10])
        Room2.disecAllowed = False
        self.rooms.append(Room2)
        Room3 = Room()
        Room3.coords.append(self.coordinatepoints[6])
        Room3.coords.append(self.coordinatepoints[9])
        Room3.coords.append(self.coordinatepoints[10])
        Room3.coords.append(self.coordinatepoints[11])
        Room3.coords.append(self.coordinatepoints[7])
        self.rooms.append(Room3)

    def createDefaultDisectionsforHexagon(self):
        #first we initialise the rooms 1,2,3, which will always exist
        Room1 = Room()
        Room1.coords.append(self.coordinatepoints[1])
        Room1.coords.append(self.coordinatepoints[7])
        Room1.coords.append(self.coordinatepoints[8])
        Room1.coords.append(self.coordinatepoints[9])
        Room1.coords.append(self.coordinatepoints[5])
        Room1.coords.append(self.coordinatepoints[6])
        Room1.disecAllowed = False
        self.rooms.append(Room1)
        Room2 = Room()
        Room2.coords.append(self.coordinatepoints[10])
        Room2.coords.append(self.coordinatepoints[2])
        Room2.coords.append(self.coordinatepoints[3])
        Room2.coords.append(self.coordinatepoints[4])
        Room2.coords.append(self.coordinatepoints[9])
        Room2.coords.append(self.coordinatepoints[13])
        Room2.coords.append(self.coordinatepoints[12])
        Room2.coords.append(self.coordinatepoints[11])
        Room2.disecAllowed = False
        self.rooms.append(Room2)
        Room3 = Room()
        Room3.coords.append(self.coordinatepoints[7])
        Room3.coords.append(self.coordinatepoints[10])
        Room3.coords.append(self.coordinatepoints[11])
        Room3.coords.append(self.coordinatepoints[12])
        Room3.coords.append(self.coordinatepoints[13])
        Room3.coords.append(self.coordinatepoints[8])
        self.rooms.append(Room3)

    def createDefaultDisectionsforCustom(self):
        

        Room1 = Room()
        Room1.coords.append(self.outerBoundary[-1])
        for i in range(len(self.innerBoundary)-1, self.lowestPointIndex-1, -1):
            Room1.coords.append(self.innerBoundary[i])
        for i in range(self.lowestPointIndex, len(self.outerBoundary)-1, 1):
            Room1.coords.append(self.outerBoundary[i])
        Room1.disecAllowed = False
        print(Room1.coords)
        self.rooms.append(Room1)

        Room2 = Room()
        Room2.coords.append(self.innerBoundary[0])
        for i in range(0, self.lowestPointIndex+1,1):
            Room2.coords.append(self.outerBoundary[i])
        for i in range(self.lowestPointIndex, 0, -1):
            Room2.coords.append(self.innerBoundary[i])
        Room2.disecAllowed = False
        print(Room2.coords)
        self.rooms.append(Room2)
        
                
        
        Room3 = Room()
        print(self.innerBoundary)
        Room3.coords.append(self.innerBoundary[-1])
        for i in range(0, len(self.innerBoundary)-1, 1):
            Room3.coords.append(self.innerBoundary[i])
        print(Room3.coords)
        self.rooms.append(Room3)

        
    def mainDisectionFunction(self):
        if(self.shape=="Pentagon"):
            self.createDefaultDisectionsforPentagon()
        elif(self.shape=="Hexagon"):
            self.createDefaultDisectionsforHexagon()
        else:
            self.createDefaultDisectionsforCustom()
        #now 0,1,2 are already made, we need to make the rooms for all the others from 3 to n-1 
        #this function is responsible for determining the coordinates and storing with each disection of each room!
        
        for i in range(3, self.noOfNodes, 1):
            #determine the number of neighbors of i-> to determine which operation to perform 
            neighborNum = len(self.graph_data['neighbors'][i])
            neighborListIndex = self.graph_data['neighbors'][i] #consists of indexes in original input Graph
            neighborListCanOrd = [] 
            indexInPathArray = []                            #consists of the indexes of the neighbors in the canonically ordered graph
            for j in neighborListIndex:
                neighborListCanOrd.append(int(self.correctCanonicalOrder[j]))
                #print(self.correctCanonicalOrder[j])
            #now we have to update the path from 1 to 2 as well, to be used in other iterations
            for j in neighborListCanOrd:
                indexInPathArray.append(self.outerPath.index(j))

            l = min(indexInPathArray)
            r = max(indexInPathArray) 
            print("left : {} , right = {}".format(l,r) )          
            newPath =[]
            for j in range(0,l+1,1):
                newPath.append(self.outerPath[j])
            newPath.append(i)
            for j in range(r,len(self.outerPath),1):
                newPath.append(self.outerPath[j])
            
            leftCanOrd = self.outerPath[l]
            rightCanOrd = self.outerPath[r]
            self.outerPath = newPath
            print(self.outerPath)
            if neighborNum == 2:
                print("Vertex {} has 2 neighbors.".format(i))
                # now since we know it has 2 neighbors, we need to make a disection in either of the two
                # before that we need to determine which neighbor is present on the left and which on the right
                # Important to our logic!
                # Remember, the first two
            
                Room0 = self.rooms[neighborListCanOrd[0]] 
                Room1 = self.rooms[neighborListCanOrd[1]] 
                Room0Active0 = Room0.coords[0]
                Room0Active1 = Room0.coords[1]
                Room1Active0 = Room1.coords[0]
                Room1Active1 = Room1.coords[1]
                if(Room0Active1 == Room1Active0):
                    leftRoom = Room0
                    rightRoom = Room1
                else:
                    leftRoom = Room1
                    rightRoom = Room0
                
                #now we have determined the left and the right room and we will now go to do the dissection on the basis of the conditions
                #now we can do 2 things : either do a right dissection in left room or do a left dissection in right room
                # we will decide which to do in the following if statement

                if (leftRoom.disecAllowed==True and leftRoom.rightDisecDone == False):
                    print("The dissection will be done in the left room.")
                    activeFront0 = leftRoom.coords[0]
                    activeFront1 = leftRoom.coords[1]
                    print(activeFront0)
                    print(activeFront1)
                    newActivePoint = ((activeFront0[0]+activeFront1[0])/2,activeFront0[1])
                    #now we will determine the y coordinate - slightly complicated process
                    print(newActivePoint)
                    initYCoord = activeFront0[1]
                    first0  = initYCoord
                    first1 = initYCoord
                    last = initYCoord
                    print(initYCoord)
                    print(leftRoom.coords)
                    print(rightRoom.coords)
                    for j in range(2,len(leftRoom.coords),1):
                        last = leftRoom.coords[j][1]
                        if(last>=first0):
                            break
                        else:
                            first0 = last
                    
                    for j in range(len(rightRoom.coords)-1,1, -1):
                        last = rightRoom.coords[j][1]
                        
                        if(last>=first1):
                            break
                        else:
                            first1 = last

                    finalYCoord = max(first0, first1)
                    print(finalYCoord)
                    newYCoord = (initYCoord*(self.divFactor_den- self.divFactor_num)+finalYCoord*self.divFactor_num)/self.divFactor_den
                    print(newYCoord)
                    newCoordtoConsider = 1
                    for j in range(1,len(leftRoom.coords),1):
                        if(leftRoom.coords[j][1]<newYCoord):
                            newCoordtoConsider = j
                            break
                    print(newCoordtoConsider)
                    newPointXCoord = ((leftRoom.coords[newCoordtoConsider][0]- leftRoom.coords[newCoordtoConsider-1][0])/(leftRoom.coords[newCoordtoConsider][1]- leftRoom.coords[newCoordtoConsider-1][1]))*(newYCoord - leftRoom.coords[newCoordtoConsider][1]) + leftRoom.coords[newCoordtoConsider][0]
                    print(newPointXCoord)
                    Point1 = (newActivePoint[0], newYCoord)
                    Point2 = (newPointXCoord, newYCoord)
                    newcoordList=[]
                    newcoordList.append(activeFront0)
                    newcoordList.append(newActivePoint)
                    newcoordList.append(Point1)
                    newcoordList.append(Point2)
                    for j in range(newCoordtoConsider,len(leftRoom.coords),1):
                        newcoordList.append(leftRoom.coords[j])
                    #Making and apending new room
                    newRoom = Room()
                    newRoom.coords.append(newActivePoint)
                    for j in range(1,newCoordtoConsider,1):
                        newRoom.coords.append(leftRoom.coords[j])
                    newRoom.coords.append(Point2)
                    newRoom.coords.append(Point1)
                    print(newRoom.coords)
                    self.rooms.append(newRoom)
                    leftRoom.coords = newcoordList
                    leftRoom.rightDisecDone = True
                    
                else:
                    #we will do the left dissection of the right room 
                    print("The dissection will be done in the right room.")
                    activeFront0 = rightRoom.coords[0]
                    activeFront1 = rightRoom.coords[1]
                    newActivePoint = ((activeFront0[0]+activeFront1[0])/2,activeFront0[1])
                    #now we will determine the y coordinate - slightly complicated process
                    initYCoord = activeFront0[1]
                    first0  = initYCoord #least y coordinate of left room
                    first1 = initYCoord #least y coordinate of right room
                    last = initYCoord
                    for j in range(2,len(leftRoom.coords),1):
                        last = leftRoom.coords[j][1]
                        if(last>=first0):
                            break
                        else:
                            first0 = last
                    
                    for j in range(len(rightRoom.coords)-1,-1, -1):
                        last = rightRoom.coords[j][1]
                        if(last>=first1):
                            break
                        else:
                            first1 = last
                    finalYCoord = max(first0, first1)
                    newYCoord = (initYCoord*(self.divFactor_den- self.divFactor_num)+finalYCoord*self.divFactor_num)/self.divFactor_den

                    newCoordtoConsider = len(rightRoom.coords)-1; 
                    for j in range(len(rightRoom.coords)-1,-1, -1):
                        if(rightRoom.coords[j][1]<newYCoord):
                            newCoordtoConsider = j
                            break
                    
                    newPointXCoord = ((rightRoom.coords[newCoordtoConsider][0]- rightRoom.coords[(newCoordtoConsider+1)%len(rightRoom.coords)][0])/(rightRoom.coords[newCoordtoConsider][1]- rightRoom.coords[(newCoordtoConsider+1)%len(rightRoom.coords)][1]))*(newYCoord - rightRoom.coords[newCoordtoConsider][1]) + rightRoom.coords[newCoordtoConsider][0]
                    Point1 = (newActivePoint[0], newYCoord)
                    Point2 = (newPointXCoord, newYCoord)
                    newcoordList=[]
                    newcoordList.append(newActivePoint)
                    newcoordList.append(activeFront1)
                    
                    for j in range(2,newCoordtoConsider+1,1):
                        newcoordList.append(rightRoom.coords[j])
                    newcoordList.append(Point2)
                    newcoordList.append(Point1)
                    
                    #Making and apending new room
                    newRoom = Room()
                    newRoom.coords.append(activeFront0)
                    newRoom.coords.append(newActivePoint)
                    newRoom.coords.append(Point1)
                    newRoom.coords.append(Point2)
                    for j in range(newCoordtoConsider+1,len(rightRoom.coords),1 ):
                        newRoom.coords.append(rightRoom.coords[j])
                    self.rooms.append(newRoom)
                    rightRoom.coords = newcoordList
                    rightRoom.leftDisecDone = True
                                
            else:
                print("Vertex {} has {} neighbors".format(i,neighborNum))
                # just need to find the new y coordinate and we will be done with this work
                
                upperY = self.rooms[leftCanOrd].coords[0][1]
                lowerY = float('-inf')
                for j in neighborListCanOrd:
                    
                    last = upperY
                    for k in range(2,len(self.rooms[j].coords),1):
                        if(self.rooms[j].coords[k][1]>= last):
                            break
                        else:
                            last = self.rooms[j].coords[k][1]
                    lowerY = max(lowerY, last)
                print(lowerY)
                newYCoord = (upperY*(self.divFactor_den - self.divFactor_num)+lowerY*self.divFactor_num)/self.divFactor_den
                print(newYCoord)
                for j in neighborListCanOrd:
                    if(j != leftCanOrd and j!= rightCanOrd):

                        newCoordtoConsider1 = 0    
                        for k in range(1, len(self.rooms[j].coords),1):
                            if(self.rooms[j].coords[k][1]<newYCoord):
                                newCoordtoConsider1 = k
                                break
                        
                        newXCoordright = ((self.rooms[j].coords[newCoordtoConsider1][0]- self.rooms[j].coords[newCoordtoConsider1-1][0])/(self.rooms[j].coords[newCoordtoConsider1][1]- self.rooms[j].coords[newCoordtoConsider1-1][1]))*(newYCoord - self.rooms[j].coords[newCoordtoConsider1][1]) + self.rooms[j].coords[newCoordtoConsider1][0]

                        for k in range(len(self.rooms[j].coords)-1, -1,-1):
                            if(self.rooms[j].coords[k][1]<newYCoord):
                                newCoordtoConsider2 = k
                                break
                        print(newCoordtoConsider2)
                        newXCoordleft = ((self.rooms[j].coords[newCoordtoConsider2][0]- self.rooms[j].coords[(newCoordtoConsider2+1)%len(self.rooms[j].coords)][0])/(self.rooms[j].coords[newCoordtoConsider2][1]- self.rooms[j].coords[(newCoordtoConsider2+1)%len(self.rooms[j].coords)][1]))*(newYCoord - self.rooms[j].coords[newCoordtoConsider2][1]) + self.rooms[j].coords[newCoordtoConsider2][0]
            
                        newcoordlist = []
                        newcoordlist.append((newXCoordleft, newYCoord))
                        newcoordlist.append((newXCoordright, newYCoord))
                        print(self.rooms[j].coords)

                        for k in range(newCoordtoConsider1, newCoordtoConsider2+1, 1) :
                            print(k)
                            newcoordlist.append(self.rooms[j].coords[k])
                        self.rooms[j].coords = newcoordlist
                
                newRoom = Room()
                leftTop = self.rooms[leftCanOrd].coords[1]
                rightTop = self.rooms[rightCanOrd].coords[0]
                newRoom.coords.append(leftTop)
                newRoom.coords.append(rightTop)

                newCoordtoConsider1 = 0
                for j in range(len(self.rooms[rightCanOrd].coords)-1,0,-1 ):
                    if(self.rooms[rightCanOrd].coords[j][1]<newYCoord):
                        newCoordtoConsider1 = j
                        break

                newCoordtoConsider2 = 0
                for j in range(1, len(self.rooms[leftCanOrd].coords)-1,1 ):
                    if(self.rooms[leftCanOrd].coords[j][1]<newYCoord):
                        newCoordtoConsider2 = j
                        break
        
                print(newCoordtoConsider1)
                print(newCoordtoConsider2)
                print(self.rooms[leftCanOrd].coords)
                print(self.rooms[rightCanOrd].coords)
                
                #make changes as discussed 
                rightBotX = ((self.rooms[rightCanOrd].coords[newCoordtoConsider1][0]- self.rooms[rightCanOrd].coords[(newCoordtoConsider1+1)%len(self.rooms[rightCanOrd].coords)][0])/(self.rooms[rightCanOrd].coords[newCoordtoConsider1][1]- self.rooms[rightCanOrd].coords[(newCoordtoConsider1+1)%len(self.rooms[rightCanOrd].coords)][1]))*(newYCoord - self.rooms[rightCanOrd].coords[newCoordtoConsider1][1]) + self.rooms[rightCanOrd].coords[newCoordtoConsider1][0]
                leftBotX = ((self.rooms[leftCanOrd].coords[newCoordtoConsider2][0]- self.rooms[leftCanOrd].coords[newCoordtoConsider2-1][0])/(self.rooms[leftCanOrd].coords[newCoordtoConsider2][1]- self.rooms[leftCanOrd].coords[newCoordtoConsider2-1][1]))*(newYCoord - self.rooms[leftCanOrd].coords[newCoordtoConsider2][1]) + self.rooms[leftCanOrd].coords[newCoordtoConsider2][0]
                rightBot = (rightBotX, newYCoord)
                leftBot = (leftBotX,newYCoord)

                for k in range(len(self.rooms[rightCanOrd].coords)-1,newCoordtoConsider1,-1):
                    newRoom.coords.append(self.rooms[rightCanOrd].coords[k])
                
                newRoom.coords.append(rightBot)
                newRoom.coords.append(leftBot)
        
                for k in range(newCoordtoConsider2-1,1, -1):    
                    newRoom.coords.append(self.rooms[leftCanOrd].coords[k])
                print(newRoom.coords)        
                        
                self.rooms.append(newRoom)
            # start_coord = (0,0) #IMP this is the initial starting coordinate of the dissection
            # self.pen.penup()
            # self.pen.goto(start_coord)
            # self.pen.setheading(0)
            # initialCoord =  self.rooms[i].coords[0]
            # self.pen.goto((initialCoord[0],initialCoord[1]))
            # self.pen.pendown()
            # for corner in range(1,len(self.rooms[i].coords)):
            #     nextCoords =  self.rooms[i].coords[corner] 
            #     self.pen.goto((nextCoords[0],nextCoords[1]))
            # self.pen.goto((initialCoord[0],initialCoord[1]))

            # self.pen.penup()
            # time.sleep(1)



