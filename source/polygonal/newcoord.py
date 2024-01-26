import networkx as nx
import matplotlib.pyplot as plt
import tkinter as tk
import numpy as np
import re

class NewCoordinateAlgorithm:
    def __init__(self, adjrooms, s_dir, shift_value, x, y):
        self.s_dir = s_dir
        self.shift_value = shift_value
        self.adjrooms = adjrooms
        self.run(adjrooms, x, y)

    def distance(self, x, y):
        d = ((y[1] - x[1])**2 + (y[0] - x[0])**2)**0.5
        return d

    def isInPerimeter(self, room, x):
        perimeter = 0.00
        for j in range(len(room.coord())):
            if j != len(room.coord()) - 1:
                if (room.coord()[j][0] == x[0] and room.coord()[j + 1][0] == x[0]) or (room.coord()[j][1] == x[1] and room.coord()[j + 1][1] == x[1]):
                    perimeter += self.distance(room.coord()[j], x) + self.distance(x, room.coord()[j + 1])
                else:
                    perimeter += self.distance(room.coord()[j], room.coord()[j + 1])
            else:
                perimeter += self.distance(room.coord()[j], room.coord()[0])
        perimeter1 = 0.00
        for k in range(len(room.coord())):
            if k != len(room.coord()) - 1:
                perimeter1 += self.distance(room.coord()[k], room.coord()[k + 1])
            else:
                perimeter1 += self.distance(room.coord()[k], room.coord()[0])
        return perimeter == perimeter1        

    def sideAdjacent(self, room, x, y, s):
        for j in range(len(room.coord())):
            if j != len(room.coord()) - 1:
                if (room.coord()[j][0] == x[0] and room.coord()[j + 1][0] == y[0] and s == "right"):
                    return room.coord()[j][1] >= x[1] and room.coord()[j + 1][1] <= y[1]
                elif (room.coord()[j][1] == x[1] and room.coord()[j + 1][1] == y[1] and s == "up"):
                    return room.coord()[j][0] <= x[0] and room.coord()[j + 1][0] >= y[0]
                if (room.coord()[j][0] == x[0] and room.coord()[j + 1][0] == y[0] and s == "left"):
                    return room.coord()[j][1] <= x[1] and room.coord()[j + 1][1] >= y[1]
                elif (room.coord()[j][1] == x[1] and room.coord()[j + 1][1] == y[1] and s == "down"):
                    return room.coord()[j][0] >= x[0] and room.coord()[j + 1][0] <= y[0]
            else:
                if (room.coord()[j][0] == x[0] and room.coord()[0][0] == y[0] and s == "right"):
                    return room.coord()[j][1] >= x[1] and room.coord()[0][1] <= y[1]
                elif (room.coord()[j][1] == x[1] and room.coord()[0][1] == y[1] and s == "up"):
                    return room.coord()[j][0] <= x[0] and room.coord()[0][0] >= y[0]
                if (room.coord()[j][0] == x[0] and room.coord()[0][0] == y[0] and s == "left"):
                    return room.coord()[j][1] <= x[1] and room.coord()[0][1] >= y[1]
                elif (room.coord()[j][1] == x[1] and room.coord()[0][1] == y[1] and s == "down"):
                    return room.coord()[j][0] >= x[0] and room.coord()[0][0] <= y[0]
        return False

    def isCoord(self, room, x):
        for j in range(len(room.coord())):
            if room.coord()[j][0] == x[0] and room.coord()[j][1] == x[1]:
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

    def insertCoordinate(self, room, coord_index, s, shift):
        new_coord = self.shift_coordinate(room.coord()[coord_index], s, shift)
        room.coord().insert(coord_index, new_coord)

    def updateAdjacentRoomCoordinates(self, adjrooms, x, y, s, shift):
        for j in range(len(self.adjrooms)):
            if self.sideAdjacent(self.adjrooms[j], x, y, s):
                if self.isInPerimeter(self.adjrooms[j], x):
                    for k in range(len(self.adjrooms[j].coord())):
                        if self.isCoord(self.adjrooms[j], x):
                            self.moveCoordinate(self.adjrooms[j], k, s, shift)
                            break
                        else:
                            if (
                                (self.adjrooms[j].coord()[k][0] <= x[0] <= self.adjrooms[j].coord()[(k + 1) % len(self.adjrooms[j].coord())][0])
                                or (self.adjrooms[j].coord()[(k + 1) % len(self.adjrooms[j].coord())][0] <= x[0] <= self.adjrooms[j].coord()[k][0])
                            ) and (
                                (self.adjrooms[j].coord()[k][1] <= x[1] <= self.adjrooms[j].coord()[(k + 1) % len(self.adjrooms[j].coord())][1])
                                or (self.adjrooms[j].coord()[(k + 1) % len(self.adjrooms[j].coord())][1] <= x[1] <= self.adjrooms[j].coord()[k][1])
                            ):
                                self.insertCoordinate(self.adjrooms[j], (k + 1) % len(self.adjrooms[j].coord()), s, shift)
                                break
                    for k in range(len(self.adjrooms[j].coord())):
                        if (
                            (self.adjrooms[j].coord()[k][0] == x[0] and self.adjrooms[j].coord()[k][0] == y[0] and (self.adjrooms[j].coord()[k][1] <= x[1] and self.adjrooms[j].coord()[k][1] >= y[1]))
                            or (self.adjrooms[j].coord()[k][1] == x[1] and self.adjrooms[j].coord()[k][1] == y[1] and (self.adjrooms[j].coord()[k][0] <= x[0] and self.adjrooms[j].coord()[k][0] >= y[0]))
                        ):
                            self.moveCoordinate(self.adjrooms[j], k, s, shift)       
                elif self.isInPerimeter(self.adjrooms[j], y):
                    for k in range(len(self.adjrooms[j].coord())):
                        if self.isCoord(self.adjrooms[j], y):
                            self.moveCoordinate(self.adjrooms[j], k, s, shift)
                            break
                        else:
                            if (
                                (self.adjrooms[j].coord()[k][0] <= y[0] <= self.adjrooms[j].coord()[(k + 1) % len(self.adjrooms[j].coord())][0])
                                or (self.adjrooms[j].coord()[(k + 1) % len(self.adjrooms[j].coord())][0] <= y[0] <= self.adjrooms[j].coord()[k][0])
                            ) and (
                                (self.adjrooms[j].coord()[k][1] <= y[1] <= self.adjrooms[j].coord()[(k + 1) % len(self.adjrooms[j].coord())][1])
                                or (self.adjrooms[j].coord()[(k + 1) % len(self.adjrooms[j].coord())][1] <= y[1] <= self.adjrooms[j].coord()[k][1])
                            ):
                                self.insertCoordinate(self.adjrooms[j], (k + 1) % len(self.adjrooms[j].coord()), s, shift)
                                break
                    for k in range(len(self.adjrooms[j].coord())):
                        if (
                            (self.adjrooms[j].coord()[k][0] == x[0] and self.adjrooms[j].coord()[k][0] == y[0] and (self.adjrooms[j].coord()[k][1] <= x[1] and self.adjrooms[j].coord()[k][1] >= y[1]))
                            or (self.adjrooms[j].coord()[k][1] == x[1] and self.adjrooms[j].coord()[k][1] == y[1] and (self.adjrooms[j].coord()[k][0] <= x[0] and self.adjrooms[j].coord()[k][0] >= y[0]))
                        ):
                            self.moveCoordinate(self.adjrooms[j], k, s, shift)          
                else:
                    for k in range(len(self.adjrooms[j].coord())):
                        if (
                            (self.adjrooms[j].coord()[k][0] == x[0] and self.adjrooms[j].coord()[k][0] == y[0] and (self.adjrooms[j].coord()[k][1] <= x[1] and self.adjrooms[j].coord()[k][1] >= y[1]))
                            or (self.adjrooms[j].coord()[k][1] == x[1] and self.adjrooms[j].coord()[k][1] == y[1] and (self.adjrooms[j].coord()[k][0] <= x[0] and self.adjrooms[j].coord()[k][0] >= y[0]))
                        ):
                            self.moveCoordinate(self.adjrooms[j], k, s, shift)

    def shiftAndUpdateCoordinates(self, adjrooms, x, y, s, shift):
        self.updateAdjacentRoomCoordinates(self.adjrooms, x, y, s, shift)
        x = self.shift_coordinate(x, s, shift)
        y = self.shift_coordinate(y, s, shift)
        self.printAllRooms()
        return x, y

    def run(self, adjrooms, x, y):
        s = ""
        if self.s_dir == "Left":
            s = "left"
        elif self.s_dir == "Right":
            s = "right"
        elif self.s_dir == "Top":
            s = "up"
        else: 
            s = "down"  
        newShiftValues = self.shiftAndUpdateCoordinates(self.adjrooms,x,y,s,self.shift_value)
        print("Wall moved from: (x=%d,y=%d) to (X=%d,Y=%d)",x,y,newShiftValues.x,newShiftValues.y)

    def printAllRooms(self, rooms):
        i = 0
        for room in rooms:
            print("Room:%d",i)
            i+=1
            print(room.coords)
            print()
