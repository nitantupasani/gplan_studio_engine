import networkx as nx
import matplotlib.pyplot as plt
import tkinter as tk
import numpy as np
import re

def distance(x, y):
    d = ((y[1] - x[1])**2 + (y[0] - x[0])**2)**0.5
    return d

def isInPerimeter(room, x):
    perimeter = 0.00
    for j in range(len(room.coord())):
        if j != len(room.coord()) - 1:
            if (room.coord()[j][0] == x[0] and room.coord()[j + 1][0] == x[0]) or (room.coord()[j][1] == x[1] and room.coord()[j + 1][1] == x[1]):
                perimeter += distance(room.coord()[j], x) + distance(x, room.coord()[j + 1])
            else:
                perimeter += distance(room.coord()[j], room.coord()[j + 1])
        else:
            perimeter += distance(room.coord()[j], room.coord()[0])
    perimeter1 = 0.00
    for k in range(len(room.coord())):
        if k != len(room.coord()) - 1:
            perimeter1 += distance(room.coord()[k], room.coord()[k + 1])
        else:
            perimeter1 += distance(room.coord()[k], room.coord()[0])
    return perimeter == perimeter1        

def sideAdjacent(room, x, y, s):
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

def isCoord(room, x):
    for j in range(len(room.coord())):
        if room.coord()[j][0] == x[0] and room.coord()[j][1] == x[1]:
            return True
    return False

def shift_coordinate(coord, s, shift):
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

def moveCoordinate(room, coord_index, s, shift):
    room.coord()[coord_index] = shift_coordinate(room.coord()[coord_index], s, shift)

def insertCoordinate(room, coord_index, s, shift):
    new_coord = shift_coordinate(room.coord()[coord_index], s, shift)
    room.coord().insert(coord_index, new_coord)

def updateAdjacentRoomCoordinates(adjrooms, x, y, s, shift):
    for j in range(len(adjrooms)):
        if sideAdjacent(adjrooms[j], x, y, s):
            if isInPerimeter(adjrooms[j], x):
                for k in range(len(adjrooms[j].coord())):
                    if isCoord(adjrooms[j], x):
                        moveCoordinate(adjrooms[j], k, s, shift)
                        break
                    else:
                        if (
                            (adjrooms[j].coord()[k][0] <= x[0] <= adjrooms[j].coord()[(k + 1) % len(adjrooms[j].coord())][0])
                            or (adjrooms[j].coord()[(k + 1) % len(adjrooms[j].coord())][0] <= x[0] <= adjrooms[j].coord()[k][0])
                        ) and (
                            (adjrooms[j].coord()[k][1] <= x[1] <= adjrooms[j].coord()[(k + 1) % len(adjrooms[j].coord())][1])
                            or (adjrooms[j].coord()[(k + 1) % len(adjrooms[j].coord())][1] <= x[1] <= adjrooms[j].coord()[k][1])
                        ):
                            insertCoordinate(adjrooms[j], (k + 1) % len(adjrooms[j].coord()), s, shift)
                            break
                for k in range(len(adjrooms[j].coord())):
                    if (
                        (adjrooms[j].coord()[k][0] == x[0] and adjrooms[j].coord()[k][0] == y[0] and (adjrooms[j].coord()[k][1] <= x[1] and adjrooms[j].coord()[k][1] >= y[1]))
                        or (adjrooms[j].coord()[k][1] == x[1] and adjrooms[j].coord()[k][1] == y[1] and (adjrooms[j].coord()[k][0] <= x[0] and adjrooms[j].coord()[k][0] >= y[0]))
                    ):
                        moveCoordinate(adjrooms[j], k, s, shift)       
            elif isInPerimeter(adjrooms[j], y):
                for k in range(len(adjrooms[j].coord())):
                    if isCoord(adjrooms[j], y):
                        moveCoordinate(adjrooms[j], k, s, shift)
                        break
                    else:
                        if (
                            (adjrooms[j].coord()[k][0] <= y[0] <= adjrooms[j].coord()[(k + 1) % len(adjrooms[j].coord())][0])
                            or (adjrooms[j].coord()[(k + 1) % len(adjrooms[j].coord())][0] <= y[0] <= adjrooms[j].coord()[k][0])
                        ) and (
                            (adjrooms[j].coord()[k][1] <= y[1] <= adjrooms[j].coord()[(k + 1) % len(adjrooms[j].coord())][1])
                            or (adjrooms[j].coord()[(k + 1) % len(adjrooms[j].coord())][1] <= y[1] <= adjrooms[j].coord()[k][1])
                        ):
                            insertCoordinate(adjrooms[j], (k + 1) % len(adjrooms[j].coord()), s, shift)
                            break
                for k in range(len(adjrooms[j].coord())):
                    if (
                        (adjrooms[j].coord()[k][0] == x[0] and adjrooms[j].coord()[k][0] == y[0] and (adjrooms[j].coord()[k][1] <= x[1] and adjrooms[j].coord()[k][1] >= y[1]))
                        or (adjrooms[j].coord()[k][1] == x[1] and adjrooms[j].coord()[k][1] == y[1] and (adjrooms[j].coord()[k][0] <= x[0] and adjrooms[j].coord()[k][0] >= y[0]))
                    ):
                        moveCoordinate(adjrooms[j], k, s, shift)          
            else:
                for k in range(len(adjrooms[j].coord())):
                    if (
                        (adjrooms[j].coord()[k][0] == x[0] and adjrooms[j].coord()[k][0] == y[0] and (adjrooms[j].coord()[k][1] <= x[1] and adjrooms[j].coord()[k][1] >= y[1]))
                        or (adjrooms[j].coord()[k][1] == x[1] and adjrooms[j].coord()[k][1] == y[1] and (adjrooms[j].coord()[k][0] <= x[0] and adjrooms[j].coord()[k][0] >= y[0]))
                    ):
                        moveCoordinate(adjrooms[j], k, s, shift)

def shiftAndUpdateCoordinates(adjrooms, x, y, s, shift):
    updateAdjacentRoomCoordinates(adjrooms, x, y, s, shift)
    x = shift_coordinate(x, s, shift)
    y = shift_coordinate(y, s, shift)
    printAllRooms()
    return x, y

def run(adjrooms,x,y):
    s = ""
    s_dir = input("Shift Direction: (L,R,T,B): ")
    shift = input("Shift Value: ")
    if s_dir == "L":
        s = "left"
    elif s_dir == "R":
        s = "right"
    elif s_dir == "T":
        s = "up"
    else: 
        s = "down"
    newShiftValues = shiftAndUpdateCoordinates(adjrooms,x,y,s,shift)
    print("Wall moved from: (x=%d,y=%d) to (X=%d,Y=%d)",x,y,newShiftValues.x,newShiftValues.y)

def printAllRooms(rooms):
    i = 0
    for room in rooms:
        print("Room:%d",i)
        i+=1
        print(room.coords)
        print()
