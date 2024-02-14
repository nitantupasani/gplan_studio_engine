import networkx as nx
import matplotlib.pyplot as plt
import tkinter as tk
import numpy as np
import re
import copy

class NewCoordinateAlgorithm:
    def __init__(self, adjrooms, s_dir, shift_value, x, y, opti,originalRoom):
        self.s_dir = s_dir
        self.shift_value = shift_value
        self.adjrooms = adjrooms
        self.opti = opti
        self.originalRoom = originalRoom
        self.run(adjrooms, x, y)    


    def converterForMain(self, index, key):
        if key == "room_x":
            return self.adjrooms[index].coords[0][0] if index!= -1 else self.originalRoom.coords[0][0]
        elif key == "room_y":
            return self.adjrooms[index].coords[0][1] if index!= -1 else self.originalRoom.coords[0][1]
        elif key == "room_width":
            return self.adjrooms[index].coords[3][0] - self.adjrooms[index].coords[0][0] if index!= -1 else self.originalRoom.coords[3][0] - self.originalRoom.coords[0][0]
        elif key == "room_height":
            return self.adjrooms[index].coords[1][1] - self.adjrooms[index].coords[0][1] if index!= -1 else self.originalRoom.coords[1][1] - self.originalRoom.coords[0][1]

    def distance(self, x, y):
        d = ((y[1] - x[1])**2 + (y[0] - x[0])**2)**0.5
        return d

    def isInPerimeter(self, room, x):
        perimeter = 0.00
        a = room.coord()
        for j in range(len(a)):
            if (a[j][0] == x[0] and a[(j + 1) % len(a)][0] == x[0]) or (a[j][1] == x[1] and a[(j + 1) % len(a)][1] == x[1]):
                perimeter += self.distance(a[j], x) + self.distance(x, a[(j + 1) % len(a)])
            else:
                perimeter += self.distance(a[j], a[(j + 1) % len(a)])
        perimeter1 = 0.00
        for k in range(len(a)):
            perimeter1 += self.distance(a[k], a[(k + 1) % len(a)])
        return perimeter == perimeter1        

    def sideAdjacent(self, room, x, y):
        a = room.coord()
        for j in range(len(a)):
            if j != len(a) - 1:
                if (a[j][0] == x[0] and a[j + 1][0] == y[0] and self.opti == 1):
                    return a[j][1] <= x[1] and a[j + 1][1] >= y[1]
                elif (a[j][1] == x[1] and a[j + 1][1] == y[1] and self.opti == 2):
                    return a[j][0] <= x[0] and a[j + 1][0] >= y[0]
                if (a[j][0] == x[0] and a[j + 1][0] == y[0] and self.opti == 0):
                    return a[j][1] >= x[1] and a[j + 1][1] <= y[1]
                elif (a[j][1] == x[1] and a[j + 1][1] == y[1] and self.opti == 3):
                    return a[j][0] <= x[0] and a[j + 1][0] >= y[0]
            else:
                if (a[j][0] == x[0] and a[0][0] == y[0] and self.opti == 1):
                    return a[j][1] <= x[1] and a[0][1] >= y[1]
                elif (a[j][1] == x[1] and a[0][1] == y[1] and self.opti == 2):
                    return a[j][0] >= x[0] and a[0][0] <= y[0]
                if (a[j][0] == x[0] and a[0][0] == y[0] and self.opti == 0):
                    return a[j][1] >= x[1] and a[0][1] <= y[1]
                elif (a[j][1] == x[1] and a[0][1] == y[1] and self.opti == 3):
                    return a[j][0] <= x[0] and a[0][0] >= y[0]
        return False

    def isCoord(self, room, x, k):
        if room.coord()[k][0] == x[0] and room.coord()[k][1] == x[1]:
            return True
        return False

    def shift_coordinate(self, coord, s, shift):
        temp = list(coord)
        if s == "right":
            temp[0] += shift
        elif s == "left":
            temp[0] -= shift
        elif s == "up":
            temp[1] += shift
        elif s == "down":
            temp[1] -= shift
        return tuple(temp)

    def moveCoordinate(self, room, coord_index, s, shift):
        room.coord()[coord_index] = self.shift_coordinate(room.coord()[coord_index], s, shift)

    def insertCoordinate(self, room, coord_index, s, shift, coord):
        temp = copy.deepcopy(coord)
        new_coord = self.shift_coordinate(temp, s, shift)
        room.coord().insert(coord_index, new_coord)

    def updateAdjacentRoomCoordinates(self, adjrooms, x, y, s, shift):
        a = copy.deepcopy(adjrooms)
        for j in range(len(self.adjrooms)):  
            if self.sideAdjacent(self.adjrooms[j], x, y):
                if self.isInPerimeter(self.adjrooms[j], x):
                    for k in range(len(self.adjrooms[j].coord())):
                        if self.isCoord(self.adjrooms[j], x, k):
                            self.moveCoordinate(a[j], k, s, shift)
                            break
                        else:
                            if ((self.adjrooms[j].coord()[k][0] == x[0] == self.adjrooms[j].coord()[(k + 1) % len(self.adjrooms[j].coord())][0]) and (
                                self.adjrooms[j].coord()[k][1] < x[1] < self.adjrooms[j].coord()[(k + 1) % len(self.adjrooms[j].coord())][1]))or((self.adjrooms[j].coord()[k][0] < x[0] < self.adjrooms[j].coord()[(k + 1) % len(self.adjrooms[j].coord())][0]) and (
                                self.adjrooms[j].coord()[k][1] == x[1] == self.adjrooms[j].coord()[(k + 1) % len(self.adjrooms[j].coord())][1])):
                                self.insertCoordinate(a[j], (k + 1), s, shift, x)
                                self.insertCoordinate(a[j], (k + 2), s, 0, x)
                                break
                            elif ((self.adjrooms[j].coord()[(k + 1) % len(self.adjrooms[j].coord())][0] == x[0] == self.adjrooms[j].coord()[k][0])and (
                                self.adjrooms[j].coord()[(k + 1) % len(self.adjrooms[j].coord())][1] < x[1] < self.adjrooms[j].coord()[k][1]))or((self.adjrooms[j].coord()[(k + 1) % len(self.adjrooms[j].coord())][0] < x[0] < self.adjrooms[j].coord()[k][0])and (
                                self.adjrooms[j].coord()[(k + 1) % len(self.adjrooms[j].coord())][1] == x[1] == self.adjrooms[j].coord()[k][1])):
                                self.insertCoordinate(a[j], (k + 1), s, shift, x)
                                self.insertCoordinate(a[j], (k + 2), s, 0, x)
                                break
                    for k in range(len(self.adjrooms[j].coord())):
                        if (
                            (self.adjrooms[j].coord()[k][0] == x[0] and self.adjrooms[j].coord()[k][0] == y[0] and ((self.adjrooms[j].coord()[k][1] < x[1] and self.adjrooms[j].coord()[k][1] > y[1])or(self.adjrooms[j].coord()[k][1] > x[1] and self.adjrooms[j].coord()[k][1] < y[1])))
                            or (self.adjrooms[j].coord()[k][1] == x[1] and self.adjrooms[j].coord()[k][1] == y[1] and ((self.adjrooms[j].coord()[k][0] < x[0] and self.adjrooms[j].coord()[k][0] > y[0])or(self.adjrooms[j].coord()[k][0] > x[0] and self.adjrooms[j].coord()[k][0] < y[0])))
                        ):
                            self.moveCoordinate(a[j], k, s, shift)    
                if self.isInPerimeter(self.adjrooms[j], y):
                    for k in range(len(self.adjrooms[j].coord())):
                        if self.isCoord(self.adjrooms[j], y, k):
                            self.moveCoordinate(a[j], k, s, shift)
                            break
                        else:
                            if ((self.adjrooms[j].coord()[k][0] < y[0] < self.adjrooms[j].coord()[(k + 1) % len(self.adjrooms[j].coord())][0]) and (
                            self.adjrooms[j].coord()[k][1] == y[1] == self.adjrooms[j].coord()[(k + 1) % len(self.adjrooms[j].coord())][1]))or((self.adjrooms[j].coord()[k][0] == y[0] == self.adjrooms[j].coord()[(k + 1) % len(self.adjrooms[j].coord())][0]) and (
                            self.adjrooms[j].coord()[k][1] < y[1] < self.adjrooms[j].coord()[(k + 1) % len(self.adjrooms[j].coord())][1])):
                                self.insertCoordinate(a[j], (k + 1), s, 0, y)
                                self.insertCoordinate(a[j], (k + 2), s, shift, y)
                                break
                            elif ((self.adjrooms[j].coord()[(k + 1) % len(self.adjrooms[j].coord())][0] == y[0] == self.adjrooms[j].coord()[k][0])and (
                            self.adjrooms[j].coord()[(k + 1) % len(self.adjrooms[j].coord())][1] < y[1] < self.adjrooms[j].coord()[k][1]))or((self.adjrooms[j].coord()[(k + 1) % len(self.adjrooms[j].coord())][0] < y[0] < self.adjrooms[j].coord()[k][0])and (
                            self.adjrooms[j].coord()[(k + 1) % len(self.adjrooms[j].coord())][1] == y[1] == self.adjrooms[j].coord()[k][1])):
                                self.insertCoordinate(a[j], (k + 1), s, 0, y)
                                self.insertCoordinate(a[j], (k + 2), s, shift, y)
                                break
                    for k in range(len(self.adjrooms[j].coord())):
                        if (
                            (self.adjrooms[j].coord()[k][0] == x[0] and self.adjrooms[j].coord()[k][0] == y[0] and ((self.adjrooms[j].coord()[k][1] < x[1] and self.adjrooms[j].coord()[k][1] > y[1])or(self.adjrooms[j].coord()[k][1] > x[1] and self.adjrooms[j].coord()[k][1] < y[1])))
                            or (self.adjrooms[j].coord()[k][1] == x[1] and self.adjrooms[j].coord()[k][1] == y[1] and ((self.adjrooms[j].coord()[k][0] < x[0] and self.adjrooms[j].coord()[k][0] > y[0])or(self.adjrooms[j].coord()[k][0] > x[0] and self.adjrooms[j].coord()[k][0] < y[0])))
                        ):
                            self.moveCoordinate(a[j], k, s, shift)          
                if not(self.isInPerimeter(self.adjrooms[j], y)) and not(self.isInPerimeter(self.adjrooms[j], x)) :
                    for k in range(len(self.adjrooms[j].coord())):
                        if (
                            (self.adjrooms[j].coord()[k][0] == x[0] and self.adjrooms[j].coord()[k][0] == y[0] and ((self.adjrooms[j].coord()[k][1] < x[1] and self.adjrooms[j].coord()[k][1] > y[1])or(self.adjrooms[j].coord()[k][1] > x[1] and self.adjrooms[j].coord()[k][1] < y[1])))
                            or (self.adjrooms[j].coord()[k][1] == x[1] and self.adjrooms[j].coord()[k][1] == y[1] and ((self.adjrooms[j].coord()[k][0] < x[0] and self.adjrooms[j].coord()[k][0] > y[0])or(self.adjrooms[j].coord()[k][0] > x[0] and self.adjrooms[j].coord()[k][0] < y[0])))
                        ):
                            self.moveCoordinate(a[j], k, s, shift)
        return a

    def shiftAndUpdateCoordinates(self, adjrooms, x, y, s, shift):
        self.adjrooms = self.updateAdjacentRoomCoordinates(self.adjrooms, x, y, s, shift)
        x = self.shift_coordinate(x, s, shift)
        y = self.shift_coordinate(y, s, shift)
        print("OLD")
        self.printAllRooms(adjrooms)
        print("NEW")
        self.printAllRooms(self.adjrooms)
        return x, y

    def run(self, adjrooms, x, y):
        s = ""
        if self.s_dir == "Left":
            s = "left"
        elif self.s_dir == "Right":
            s = "right"
        elif self.s_dir == "Up":
            s = "up"
        else: 
            s = "down"  
        (X,Y) = self.shiftAndUpdateCoordinates(self.adjrooms,x,y,s,self.shift_value)
        self.chosenRoomNewCoords(x,y,X,Y)
        print("Wall moved from: (x=%d,y=%d) to (X=%d,Y=%d)",x,y,X,Y)

    def chosenRoomNewCoords(self,x,y,X,Y):
        for i in range(0,len(self.originalRoom.coords)):
            if(self.originalRoom.coords[i][0]==x[0] and self.originalRoom.coords[i][1]==x[1]):
                self.originalRoom.coords[i] = (X[0],X[1])
            elif(self.originalRoom.coords[i][0]==y[0] and self.originalRoom.coords[i][1]==y[1]):
                self.originalRoom.coords[i] = (Y[0],Y[1])
                
    def printAllRooms(self, rooms):
        i = 0
        for room in rooms:
            print("Room:%d",i)
            i+=1
            print(room.coords)
            print()
