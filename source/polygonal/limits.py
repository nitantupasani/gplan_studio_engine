import networkx as nx
import matplotlib.pyplot as plt
import numpy as np
import tkinter as tk
import numpy as np
import re

def slope(x,y):
    if (y[0]-x[0])!=0:
        m = (y[1]-x[1])/(y[0]-x[0])
    else:
        m = "NOT DEFINED"
    return m

def distance(x,y):
    d = ((y[1]-x[1])**2 + (y[0]-x[0])**2)**0.5
    return d


def IsInRegion(x,ci1,ci2): #choosing coords which come inside the required region
    m1 = slope(ci1,ci2)
    if m1 != "NOT DEFINED":
        if m1 != 0:
            m2 = -(1/m1)
            #m2(X) + (-1)Y + (ci1[1] - m2(ci1[0])) = 0 ; equation of line 1
            #m2(X) + (-1)Y + (ci2[1] - m2(ci2[0])) = 0 ; equation if line 2 
            d1 = abs(m2*x[0] - x[1] + (ci1[1] - m2*(ci1[0])))/((m2**2 + 1)**0.5)
            d2 = abs(m2*x[0] - x[1] + (ci2[1] - m2*(ci2[0])))/((m2**2 + 1)**0.5)
            if d1 <= distance(ci1,ci2) and d2 <= distance(ci1,ci2):
                return True 
            else:
                return False
        else:
            d1 = abs(x[0]-ci1[0])
            d2 = abs(x[0]-ci2[0])
            if d1 <= distance(ci1,ci2) and d2 <= distance(ci1,ci2):
                return True
            else:
                return False
    else:
        d1 = abs(x[1]-ci1[1])
        d2 = abs(x[1]-ci2[1])
        if d1 <= distance(ci1,ci2) and d2 <= distance(ci1,ci2):
            return True
        else:
            return False


# remember to make the adj_matrix in the same order of rooms, very very important
def run(rooms,adj_matrix):
    room_input = int(input("Room number : "))


    room_input = room_input-1              #doubt ask from ayush!!!!!!!!!

    print("Choose the coordinate, considering the other coordinate will be next to it moving in clockwise direction")
    print("For entering the coord (1,3), just enter 1 3")
    coord_input1 = tuple(map(int,input("Coordinate of room corner : ").split()))
    n=len(rooms[room_input].coord())

    nbd_rooms=[]

    for k in len(adj_matrix[room_input]):
                if adj_matrix[room_input][k]=='1': 
                    nbd_rooms.append(k)

    for i in range(n):
        if rooms[room_input].coord()[i] == coord_input1 and i == n-1:
            coord_input2 = rooms[room_input].coord()[0]
            #for k in len(adj_matrix[room_input]):
            #    if adj_matrix[room_input][k]=='1': 
            #        nbd_rooms.append(k) 
            break  
        elif rooms[room_input].coord()[i] == coord_input1 and i != n-1: 
            coord_input2 = rooms[room_input].coord()[i+1]   
            #for k in len(adj_matrix[room_input]):
            #    if adj_matrix[room_input][k]=='1': 
            #        nbd_rooms.append(k)  
            break 
    
    pts={}
    dts=[]
    for i in range(len(nbd_rooms)):
        for j in range(len(rooms[i].coord())):      
            check = IsInRegion(rooms[i].coord()[j],coord_input1,coord_input2)
            if check == True:
                if j!=0:
                    check1 = IsInRegion(rooms[i].coord()[j-1],coord_input1,coord_input2)  
                    if check1 == False:
                        m=slope(rooms[i].coord()[j],rooms[i].coord()[j-1]) 
                        m_ = slope(coord_input1,coord_input2)
                        if m_ != "NOT DEFINED" and m_ != 0:
                            m_ = -1/m_
                            X = ( coord_input1[1] - rooms[i].coord()[j-1][1] - (coord_input1[0] - rooms[i].coord()[j-1][0]) )/(m-m_)
                            Y = m_(X - coord_input1[0]) + coord_input1[1]
                            # mX - Y + (coord_input1[1] - m.coord_input1[0]) = 0
                            pts[(X,Y)] = abs( m_*X - Y + (coord_input1[1] - m_*coord_input1[0]) )/((m_**2 + 1)**.5)

                            X = ( coord_input2[1] - rooms[i].coord()[j-1][1] - (coord_input2[0] - rooms[i].coord()[j-1][0]) )/(m-m_)
                            Y = m_(X - coord_input2[0]) + coord_input2[1]
                            pts[(X,Y)] = abs( m_*X - Y + (coord_input1[1] - m_*coord_input1[0]) )/((m_**2 + 1)**.5)

                        elif m_ != "NOT DEFINED" and m_ == 0:
                            X = (coord_input1[0]) 
                            Y = m(coord_input1[0] - rooms[i].coord()[j-1][0]) + rooms[i].coord()[j-1][1]
                            pts[(X,Y)] = abs( m_*X - Y + (coord_input1[1] - m_*coord_input1[0]) )/((m_**2 + 1)**.5)
                            
                            X = (coord_input2[0])
                            Y = m(coord_input2[0] - rooms[i].coord()[j-1][0]) + rooms[i].coord()[j-1][1]
                            pts[(X,Y)] = abs( m_*X - Y + (coord_input1[1] - m_*coord_input1[0]) )/((m_**2 + 1)**.5)
                            
                        else:
                            X = (coord_input1[1] - rooms[i].coord()[j-1][1])/m + rooms[i].coord()[j-1][0] 
                            Y = coord_input1[1]
                            pts[(X,Y)] = abs(X - coord_input1[0])

                            X = (coord_input2[1] - rooms[i].coord()[j-1][1])/m + rooms[i].coord()[j-1][0] 
                            Y = coord_input2[1]
                            pts[(X,Y)] = abs(X - coord_input2[0])
                else:
                    check1 = IsInRegion(rooms[i].coord()[n-1],coord_input1,coord_input2) 
                    if check1 == False:
                        m=slope(rooms[i].coord()[j],rooms[i].coord()[n-1]) 
                        m_ = slope(coord_input1,coord_input2)
                        if m_ != "NOT DEFINED" and m_ != 0:
                            m_ = -1/m_
                            X = ( coord_input1[1] - rooms[i].coord()[n-1][1] - (coord_input1[0] - rooms[i].coord()[n-1][0]) )/(m-m_)
                            Y = m_(X - coord_input1[0]) + coord_input1[1]
                            # mX - Y + (coord_input1[1] - m.coord_input1[0]) = 0
                            pts[(X,Y)] = abs( m_*X - Y + (coord_input1[1] - m_*coord_input1[0]) )/((m_**2 + 1)**.5)

                            X = ( coord_input2[1] - rooms[i].coord()[n-1][1] - (coord_input2[0] - rooms[i].coord()[n-1][0]) )/(m-m_)
                            Y = m_(X - coord_input2[0]) + coord_input2[1]
                            pts[(X,Y)] = abs( m_*X - Y + (coord_input1[1] - m_*coord_input1[0]) )/((m_**2 + 1)**.5)

                        elif m_ != "NOT DEFINED" and m_ == 0:
                            X = (coord_input1[0]) 
                            Y = m(coord_input1[0] - rooms[i].coord()[n-1][0]) + rooms[i].coord()[n-1][1]
                            pts[(X,Y)] = abs( m_*X - Y + (coord_input1[1] - m_*coord_input1[0]) )/((m_**2 + 1)**.5)
                            
                            X = (coord_input2[0])
                            Y = m(coord_input2[0] - rooms[i].coord()[n-1][0]) + rooms[i].coord()[n-1][1]
                            pts[(X,Y)] = abs( m_*X - Y + (coord_input1[1] - m_*coord_input1[0]) )/((m_**2 + 1)**.5)
                            
                        else:
                            X = (coord_input1[1] - rooms[i].coord()[n-1][1])/m + rooms[i].coord()[n-1][0] 
                            Y = coord_input1[1]
                            pts[(X,Y)] = abs(X - coord_input1[0])

                            X = (coord_input2[1] - rooms[i].coord()[n-1][1])/m + rooms[i].coord()[n-1][0] 
                            Y = coord_input2[1]
                            pts[(X,Y)] = abs(X - coord_input2[0])
                if j==len(rooms[i].coord())-1:
                    check2 = IsInRegion(rooms[i].coord()[0],coord_input1,coord_input2)
                    if check2 == False:
                        m=slope(rooms[i].coord()[j],rooms[i].coord()[0])
                        m_ = slope(coord_input1,coord_input2)
                        if m_ != "NOT DEFINED" and m_ != 0:
                            m_ = -1/m_
                            X = ( coord_input1[1] - rooms[i].coord()[0][1] - (coord_input1[0] - rooms[i].coord()[0][0]) )/(m-m_)
                            Y = m_(X - coord_input1[0]) + coord_input1[1]
                            pts[(X,Y)] = abs( m_*X - Y + (coord_input1[1] - m_*coord_input1[0]) )/((m_**2 + 1)**.5)
                            
                            X = ( coord_input2[1] - rooms[i].coord()[0][1] - (coord_input2[0] - rooms[i].coord()[0][0]) )/(m-m_)
                            Y = m_(X - coord_input2[0]) + coord_input2[1]
                            pts[(X,Y)] = abs( m_*X - Y + (coord_input1[1] - m_*coord_input1[0]) )/((m_**2 + 1)**.5)
                            
                        elif m_ != "NOT DEFINED" and m_ == 0:
                            X = (coord_input1[0])
                            Y = m(coord_input1[0] - rooms[i].coord()[0][0]) + rooms[i].coord()[0][1]
                            pts[(X,Y)] = abs( m_*X - Y + (coord_input1[1] - m_*coord_input1[0]) )/((m_**2 + 1)**.5)
                            
                            X = (coord_input2[0])
                            Y = m(coord_input2[0] - rooms[i].coord()[0][0]) + rooms[i].coord()[0][1]
                            pts[(X,Y)] = abs( m_*X - Y + (coord_input1[1] - m_*coord_input1[0]) )/((m_**2 + 1)**.5)

                        else:
                            X = (coord_input1[1] - rooms[i].coord()[0][1])/m + rooms[i].coord()[0][0] 
                            Y = coord_input1[1]
                            pts[(X,Y)] = abs(X - coord_input1[0])
                            
                            X = (coord_input2[1] - rooms[i].coord()[0][1])/m + rooms[i].coord()[0][0] 
                            Y = coord_input2[1]
                            pts[(X,Y)] = abs(X - coord_input1[0])
                else:
                    check2 = IsInRegion(rooms[i].coord()[j+1],coord_input1,coord_input2)
                    if check2 == False:
                        m=slope(rooms[i].coord()[j],rooms[i].coord()[j+1])
                        '''
                        Y - rooms[i].coord()[j+1][1] = m(X - rooms[i].coord()[j+1][0])
                        m_ = (coord_input1[1]-coord_input2[1])/(coord_input1[0]-coord_input2[0])
                        m_ = -1/m_
                        Y - coord_input1[1] = (m_)(X - coord_input1[0])
                        ( coord_input1[1] - rooms[i].coord()[j-1][1] - (coord_input1[0] - rooms[i].coord()[j-1][0]) )/(m-m') = X
                        ''' 
                        m_ = slope(coord_input1,coord_input2)
                        if m_ != "NOT DEFINED" and m_ != 0:
                            m_ = -1/m_
                            X = ( coord_input1[1] - rooms[i].coord()[j+1][1] - (coord_input1[0] - rooms[i].coord()[j+1][0]) )/(m-m_)
                            Y = m_(X - coord_input1[0]) + coord_input1[1]
                            pts[(X,Y)] = abs( m_*X - Y + (coord_input1[1] - m_*coord_input1[0]) )/((m_**2 + 1)**.5)
                            
                            X = ( coord_input2[1] - rooms[i].coord()[j+1][1] - (coord_input2[0] - rooms[i].coord()[j+1][0]) )/(m-m_)
                            Y = m_(X - coord_input2[0]) + coord_input2[1]
                            pts[(X,Y)] = abs( m_*X - Y + (coord_input1[1] - m_*coord_input1[0]) )/((m_**2 + 1)**.5)

                        elif m_ != "NOT DEFINED" and m_ == 0:
                            X = (coord_input1[0])
                            Y = m(coord_input1[0] - rooms[i].coord()[j+1][0]) + rooms[i].coord()[j+1][1]
                            pts[(X,Y)] = abs( m_*X - Y + (coord_input1[1] - m_*coord_input1[0]) )/((m_**2 + 1)**.5)
                            
                            X = (coord_input2[0])
                            Y = m(coord_input2[0] - rooms[i].coord()[j+1][0]) + rooms[i].coord()[j+1][1]
                            pts[(X,Y)] = abs( m_*X - Y + (coord_input1[1] - m_*coord_input1[0]) )/((m_**2 + 1)**.5)

                        else: 
                            X = (coord_input1[1] - rooms[i].coord()[j+1][1])/m + rooms[i].coord()[j+1][0] 
                            Y = coord_input1[1]
                            pts[(X,Y)] = abs(X - coord_input1[0])
                            
                            X = (coord_input2[1] - rooms[i].coord()[j+1][1])/m + rooms[i].coord()[j+1][0] 
                            Y = coord_input2[1]
                            pts[(X,Y)] = abs(X - coord_input1[0])

                m = slope(coord_input1,coord_input2)
                temp = rooms[i].coord()[j]
                if m != "NOT DEFINED":
                    # Y - coord_input1[1] = m(X - coord_input1[0]) => mX - Y + (coord_input1[1] - m.coord_input1[0]) = 0
                    pts[(temp[0],temp[1])] = abs( m*temp[0] - temp[1] + (coord_input1[1] - m*coord_input1[0]) )/((m**2 + 1)**.5)
                else:
                    pts[(temp[0],temp[1])] = abs(temp[0] - coord_input1[0])

    m_ = slope(coord_input1,coord_input2)
    for i in range(len(nbd_rooms)):
        for j in range(len(rooms[i].coord())):      
            if rooms[i].coord()[j] != coord_input1 or rooms[i].coord()[j] != coord_input2:
                if j!=0:
                    m = slope(rooms[i].coord()[j],rooms[i].coord()[j-1])
                    X = ( coord_input1[1] - rooms[i].coord()[j-1][1] - (coord_input1[0] - rooms[i].coord()[j-1][0]) )/(m-m_)
                    Y = m_(X - coord_input1[0]) + coord_input1[1]
                    pts[(X,Y)] = abs( m_*X - Y + (coord_input1[1] - m_*coord_input1[0]) )/((m_**2 + 1)**.5)
                else:
                    m = slope(rooms[i].coord()[j],rooms[i].coord()[n-1])
                    X = ( coord_input1[1] - rooms[i].coord()[n-1][1] - (coord_input1[0] - rooms[i].coord()[n-1][0]) )/(m-m_)
                    Y = m_(X - coord_input1[0]) + coord_input1[1]
                    pts[(X,Y)] = abs( m_*X - Y + (coord_input1[1] - m_*coord_input1[0]) )/((m_**2 + 1)**.5)

    m_ = slope(coord_input1,coord_input2)
    # Y - coord_input1[1] = (m_)(X - coord_input1[0])
    
    if coord_input1 != rooms[room_input].coord()[0] and coord_input2 != rooms[room_input].coord()[0]:
        temp = pts[rooms[room_input].coord()[0]]
    else:
        temp = pts[rooms[room_input].coord()[1]]
    for i in pts.keys():
        if i[1] - m_*i[0] + (m_*coord_input1[0] - coord_input1[1]) > 0:
            if temp > pts[i]:
                temp = pts[i]
        else:
            temp1 = temp
            if temp1 > abs(pts[i]):
                temp1 = abs(pts[i])
    print("can move towards the left by : ", temp1)
    print("can move towards the right by : ", temp) 

def find_limits(adj_mat,rooms):
    print(f"Adj MAT = {adj_mat}")
    run(rooms,adj_mat)