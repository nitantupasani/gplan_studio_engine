import networkx as nx
import matplotlib.pyplot as plt
import numpy as np
import tkinter as tk
import numpy as np
import re
import math
import newcoord as newcoord
class LimitsAlgorithm:

    def __init__(self, opti, room_input, rooms, adj_mat,shiftDirection,shiftValue):
        self.proceed = 0
        self.errorMessage = ""
        self.opti = opti
        self.room_input = room_input
        self.rooms = rooms
        self.adj_mat = adj_mat
        self.coords_input1 = ()
        self.coords_input2 = ()
        self.wall_input()
        print(self.adj_mat)
        print("")
        print("")
        for i in range(len(self.rooms)):
            print(self.rooms[i].coords) 
        print("")
        (x_max,y_max) = self.run()
        self.proceed = 1
        if shiftDirection == "left" :
            if shiftValue>x_max:
                errorMessage = "Exceeding beyond the limits in the Left Direction" 
                print(errorMessage)
                self.proceed = 0
        elif shiftDirection == "right" :
            if shiftValue>y_max:
                errorMessage = "Exceeding beyond the limits in the Right Direction" 
                print(errorMessage)
                self.proceed = 0
        elif shiftDirection == "up" :
            if shiftValue>x_max:
                errorMessage = "Exceeding beyond the limits in the Up Direction" 
                print(errorMessage)
                self.proceed = 0
        elif shiftDirection == "down" :
            if shiftValue>y_max:
                errorMessage = "Exceeding beyond the limits in the Down Direction" 
                print(errorMessage)
                self.proceed = 0        


    def slope(self,x,y):
        if (y[0]-x[0])!=0:
            m = (float(y[1]-x[1]))/(float(y[0]-x[0]))
        else:
            m = "NOT DEFINED"
        return m

    def distance(self,x,y):
        d = ((y[1]-x[1])**2 + (y[0]-x[0])**2)**0.5
        return d

    def wall_input(self):
        if self.opti==0:
            self.coords_input1 = self.rooms[self.room_input].coords[0]
            self.coords_input2 = self.rooms[self.room_input].coords[1]
        elif self.opti==1:
            self.coords_input1 = self.rooms[self.room_input].coords[2]
            self.coords_input2 = self.rooms[self.room_input].coords[3]
        elif self.opti==2:
            self.coords_input1 = self.rooms[self.room_input].coords[1]
            self.coords_input2 = self.rooms[self.room_input].coords[2]
        elif self.opti==3:
            self.coords_input1 = self.rooms[self.room_input].coords[3]
            self.coords_input2 = self.rooms[self.room_input].coords[0]

    def IsInRegion(self,x,ci1,ci2): #choosing coordss which come inside the required region
        m1 = self.slope(ci1,ci2)
        if m1 != "NOT DEFINED":
            if m1 != 0:
                m2 = -(1/m1)
                #m2(X) + (-1)Y + (ci1[1] - m2(ci1[0])) = 0 ; equation of line 1
                #m2(X) + (-1)Y + (ci2[1] - m2(ci2[0])) = 0 ; equation if line 2 
                d1 = abs(m2*x[0] - x[1] + (ci1[1] - m2*(ci1[0])))/((m2**2 + 1)**0.5)
                d2 = abs(m2*x[0] - x[1] + (ci2[1] - m2*(ci2[0])))/((m2**2 + 1)**0.5)
                if d1 <= self.distance(ci1,ci2) and d2 <= self.distance(ci1,ci2):
                    return True 
                else:
                    return False
            else:
                d1 = abs(x[0]-ci1[0])
                d2 = abs(x[0]-ci2[0])
                if d1 <= self.distance(ci1,ci2) and d2 <= self.distance(ci1,ci2):
                    return True
                else:
                    return False
        else:
            d1 = abs(x[1]-ci1[1])
            d2 = abs(x[1]-ci2[1])
            if d1 <= self.distance(ci1,ci2) and d2 <= self.distance(ci1,ci2):
                return True
            else:
                return False

    # remember to make the self.adj_mat in the same order of self.rooms, very very important
    def run(self):
        #self.room_input = int(input("Room number : "))
        # if self.room_input != 0:
        #     self.room_input = self.room_input - 1 
        # else:
        #     self.room_input = len(self.rooms) - 1
        # print("Choose the coordsinate, considering the other coordsinate will be next to it moving in clockwise direction")
        # print("For entering the coords (1,3), just enter 1 3")
        #self.coords_input1 = tuple(map(float,input("coordsinate of room corner : ").split()))
        n=len(self.rooms[self.room_input].coords)
        # print(n)
        nbd_rooms=[]
        # print(self.coords_input1)
        # print(self.coords_input2)
        # print("")

        for k in range(len(self.adj_mat[self.room_input])):
                    if self.adj_mat[self.room_input][k]==1: 
                        nbd_rooms.append(k)
        print(self.rooms[self.room_input].coords[1])
        for i in range(n):
            if self.rooms[self.room_input].coords[i] == self.coords_input1 and i == n-1:
                self.coords_input2 = self.rooms[self.room_input].coords[0]
                #for k in len(self.adj_mat[self.room_input]):
                #    if self.adj_mat[self.room_input][k]=='1': 
                #        nbd_rooms.append(k) 
                break  
            elif self.rooms[self.room_input].coords[i] == self.coords_input1 and i != n-1: 
                self.coords_input2 = self.rooms[self.room_input].coords[i+1]   
                #for k in len(self.adj_mat[self.room_input]):
                #    if self.adj_mat[self.room_input][k]=='1': 
                #        nbd_rooms.append(k)  
                break 
        print(self.coords_input2)
        print(nbd_rooms)
        pts={}
        dts=[]

        # CASE 1: one in and one out

        for i in nbd_rooms:
            for j in range(len(self.rooms[i].coords)):      
                check = self.IsInRegion(self.rooms[i].coords[j],self.coords_input1,self.coords_input2)
                if check == True:
                    if j!=0:
                        check1 = self.IsInRegion(self.rooms[i].coords[j-1],self.coords_input1,self.coords_input2)  
                        if check1 == False:
                            m=self.slope(self.rooms[i].coords[j],self.rooms[i].coords[j-1]) 
                            m_ = self.slope(self.coords_input1,self.coords_input2)
                            '''
                            Y - self.rooms[i].coords[j-1][1] = m(X - self.rooms[i].coords[j-1][0])
                            m_ = (self.coords_input1[1]-self.coords_input2[1])/(self.coords_input1[0]-self.coords_input2[0])
                            m_ = -1/m_
                            Y - self.coords_input1[1] = (m_)(X - self.coords_input1[0])
                            ( self.coords_input1[1] - self.rooms[i].coords[j-1][1] - (self.coords_input1[0] - self.rooms[i].coords[j-1][0]) )/(m-m_) = X
                            ''' 
                            if m != "NOT DEFINED": 
                                if m_ != "NOT DEFINED" and m_ != 0: 
                                    m_ = -1/m_  
                                    if self.rooms[i].coords[j][1] < self.coords_input1[1] < self.rooms[i].coords[j-1][1] or self.rooms[i].coords[j][1] > self.coords_input1[1] > self.rooms[i].coords[j-1][1]:
                                        X = ( self.coords_input1[1] - self.rooms[i].coords[j-1][1] - (m_*self.coords_input1[0] - m*self.rooms[i].coords[j-1][0]) )/(m-m_)
                                        Y = m_*(X - self.coords_input1[0]) + self.coords_input1[1] 
                                        # mX - Y + (self.coords_input1[1] - m.self.coords_input1[0]) = 0
                                        pts[(X,Y)] = abs( m_*X - Y + (self.coords_input1[1] - m_*self.coords_input1[0]) )/((m_**2 + 1)**.5)
                                    elif self.rooms[i].coords[j][1] < self.coords_input2[1] < self.rooms[i].coords[j-1][1] or self.rooms[i].coords[j][1] > self.coords_input2[1] > self.rooms[i].coords[j-1][1]:
                                        X = ( self.coords_input2[1] - self.rooms[i].coords[j-1][1] - (m_*self.coords_input2[0] - m*self.rooms[i].coords[j-1][0]) )/(m-m_)
                                        Y = m_*(X - self.coords_input2[0]) + self.coords_input2[1]
                                        pts[(X,Y)] = abs( m_*X - Y + (self.coords_input1[1] - m_*self.coords_input1[0]) )/((m_**2 + 1)**.5)

                                elif m_ != "NOT DEFINED" and m_ == 0:
                                    if self.rooms[i].coords[j][0] < self.coords_input1[0] < self.rooms[i].coords[j-1][0] or self.rooms[i].coords[j][0] > self.coords_input1[0] > self.rooms[i].coords[j-1][0]:
                                        X = (self.coords_input1[0]) 
                                        Y = m*(self.coords_input1[0] - self.rooms[i].coords[j-1][0]) + self.rooms[i].coords[j-1][1]
                                        pts[(X,Y)] = abs( m_*X - Y + (self.coords_input1[1] - m_*self.coords_input1[0]) )/((m_**2 + 1)**.5)
                                    elif self.rooms[i].coords[j][0] < self.coords_input2[0] < self.rooms[i].coords[j-1][0] or self.rooms[i].coords[j][0] > self.coords_input2[0] > self.rooms[i].coords[j-1][0]:
                                        X = (self.coords_input2[0])
                                        Y = m*(self.coords_input2[0] - self.rooms[i].coords[j-1][0]) + self.rooms[i].coords[j-1][1]
                                        pts[(X,Y)] = abs( m_*X - Y + (self.coords_input1[1] - m_*self.coords_input1[0]) )/((m_**2 + 1)**.5)
                                
                                else:
                                    if self.rooms[i].coords[j][1] < self.coords_input1[1] < self.rooms[i].coords[j-1][1] or self.rooms[i].coords[j][1] > self.coords_input1[1] > self.rooms[i].coords[j-1][1]:
                                        X = (self.coords_input1[1] - self.rooms[i].coords[j-1][1])/m + self.rooms[i].coords[j-1][0] 
                                        Y = self.coords_input1[1]
                                        pts[(X,Y)] = abs(X - self.coords_input1[0])
                                    elif self.rooms[i].coords[j][1] < self.coords_input2[1] < self.rooms[i].coords[j-1][1] or self.rooms[i].coords[j][1] > self.coords_input2[1] > self.rooms[i].coords[j-1][1]:
                                        X = (self.coords_input2[1] - self.rooms[i].coords[j-1][1])/m + self.rooms[i].coords[j-1][0] 
                                        Y = self.coords_input2[1]
                                        pts[(X,Y)] = abs(X - self.coords_input2[0])
                            else:
                                if m_ != "NOT DEFINED" and m_ != 0:
                                    m_ = -1/m_ 
                                    if self.rooms[i].coords[j][1] < self.coords_input1[1] < self.rooms[i].coords[j-1][1] or self.rooms[i].coords[j][1] > self.coords_input1[1] > self.rooms[i].coords[j-1][1]:
                                        Y = self.rooms[i].coords[j-1][1] 
                                        X = ((Y - self.coords_input1[1])/m_) + self.coords_input1[0]  
                                        # mX - Y + (self.coords_input1[1] - m.self.coords_input1[0]) = 0
                                        pts[(X,Y)] = abs( m_*X - Y + (self.coords_input1[1] - m_*self.coords_input1[0]) )/((m_**2 + 1)**.5)
                                    elif self.rooms[i].coords[j][1] < self.coords_input2[1] < self.rooms[i].coords[j-1][1] or self.rooms[i].coords[j][1] > self.coords_input2[1] > self.rooms[i].coords[j-1][1]:
                                        Y = self.rooms[i].coords[j-1][1]
                                        X = ((Y - self.coords_input2[1])/m_) + self.coords_input2[0]
                                        pts[(X,Y)] = abs( m_*X - Y + (self.coords_input1[1] - m_*self.coords_input1[0]) )/((m_**2 + 1)**.5)
                                    
                                elif m_ == "NOT DEFINED":
                                    if self.rooms[i].coords[j][1] < self.coords_input1[1] < self.rooms[i].coords[j-1][1] or self.rooms[i].coords[j][1] > self.coords_input1[1] > self.rooms[i].coords[j-1][1]:
                                        X = ((self.coords_input1[1] - self.rooms[i].coords[j-1][1])/m) + self.rooms[i].coords[j-1][0] 
                                        Y = self.coords_input1[1]
                                        pts[(X,Y)] = abs(X - self.coords_input1[0])
                                    elif self.rooms[i].coords[j][1] < self.coords_input2[1] < self.rooms[i].coords[j-1][1] or self.rooms[i].coords[j][1] > self.coords_input2[1] > self.rooms[i].coords[j-1][1]:
                                        X = ((self.coords_input2[1] - self.rooms[i].coords[j-1][1])/m) + self.rooms[i].coords[j-1][0] 
                                        Y = self.coords_input2[1]
                                        pts[(X,Y)] = abs(X - self.coords_input2[0])
                    else:
                        check1 = self.IsInRegion(self.rooms[i].coords[len(self.rooms[i].coords)-1],self.coords_input1,self.coords_input2) 
                        if check1 == False:
                            m=self.slope(self.rooms[i].coords[j],self.rooms[i].coords[len(self.rooms[i].coords)-1]) 
                            m_ = self.slope(self.coords_input1,self.coords_input2)
                            if m != "NOT DEFINED":
                                if m_ != "NOT DEFINED" and m_ != 0:
                                    m_ = -1/m_  
                                    if self.rooms[i].coords[0][1] < self.coords_input1[1] < self.rooms[i].coords[len(self.rooms[i].coords)-1][1] or self.rooms[i].coords[0][1] > self.coords_input1[1] > self.rooms[i].coords[len(self.rooms[i].coords)-1][1]:
                                        X = ( self.coords_input1[1] - self.rooms[i].coords[n-1][1] - (m_*self.coords_input1[0] - m*self.rooms[i].coords[n-1][0]) )/(m-m_)
                                        Y = m_*(X - self.coords_input1[0]) + self.coords_input1[1]
                                        # mX - Y + (self.coords_input1[1] - m.self.coords_input1[0]) = 0
                                        pts[(X,Y)] = abs( m_*X - Y + (self.coords_input1[1] - m_*self.coords_input1[0]) )/((m_**2 + 1)**.5)
                                    elif self.rooms[i].coords[0][1] < self.coords_input2[1] < self.rooms[i].coords[len(self.rooms[i].coords)-1][1] or self.rooms[i].coords[0][1] > self.coords_input2[1] > self.rooms[i].coords[len(self.rooms[i].coords)-1][1]:
                                        X = ( self.coords_input2[1] - self.rooms[i].coords[n-1][1] - (m_*self.coords_input2[0] - m*self.rooms[i].coords[n-1][0]) )/(m-m_)
                                        Y = m_*(X - self.coords_input2[0]) + self.coords_input2[1]
                                        pts[(X,Y)] = abs( m_*X - Y + (self.coords_input1[1] - m_*self.coords_input1[0]) )/((m_**2 + 1)**.5)

                                elif m_ != "NOT DEFINED" and m_ == 0:
                                    if self.rooms[i].coords[0][1] < self.coords_input1[1] < self.rooms[i].coords[len(self.rooms[i].coords)-1][1] or self.rooms[i].coords[0][1] > self.coords_input1[1] > self.rooms[i].coords[len(self.rooms[i].coords)-1][1]:
                                        X = (self.coords_input1[0]) 
                                        Y = m*(self.coords_input1[0] - self.rooms[i].coords[n-1][0]) + self.rooms[i].coords[n-1][1]
                                        pts[(X,Y)] = abs( m_*X - Y + (self.coords_input1[1] - m_*self.coords_input1[0]) )/((m_**2 + 1)**.5)
                                    elif self.rooms[i].coords[0][1] < self.coords_input2[1] < self.rooms[i].coords[len(self.rooms[i].coords)-1][1] or self.rooms[i].coords[0][1] > self.coords_input2[1] > self.rooms[i].coords[len(self.rooms[i].coords)-1][1]:
                                        X = (self.coords_input2[0])
                                        Y = m*(self.coords_input2[0] - self.rooms[i].coords[n-1][0]) + self.rooms[i].coords[n-1][1]
                                        pts[(X,Y)] = abs( m_*X - Y + (self.coords_input1[1] - m_*self.coords_input1[0]) )/((m_**2 + 1)**.5)
                                        
                                else:
                                    if self.rooms[i].coords[0][1] < self.coords_input1[1] < self.rooms[i].coords[len(self.rooms[i].coords)-1][1] or self.rooms[i].coords[0][1] > self.coords_input1[1] > self.rooms[i].coords[len(self.rooms[i].coords)-1][1]:
                                        X = (self.coords_input1[1] - self.rooms[i].coords[n-1][1])/m + self.rooms[i].coords[n-1][0] 
                                        Y = self.coords_input1[1]
                                        pts[(X,Y)] = abs(X - self.coords_input1[0])
                                    elif self.rooms[i].coords[0][1] < self.coords_input2[1] < self.rooms[i].coords[len(self.rooms[i].coords)-1][1] or self.rooms[i].coords[0][1] > self.coords_input2[1] > self.rooms[i].coords[len(self.rooms[i].coords)-1][1]:
                                        X = (self.coords_input2[1] - self.rooms[i].coords[n-1][1])/m + self.rooms[i].coords[n-1][0] 
                                        Y = self.coords_input2[1]
                                        pts[(X,Y)] = abs(X - self.coords_input2[0])
                            else:
                                if m_ != "NOT DEFINED" and m_ != 0:
                                    m_ = -1/m_ 
                                    if self.rooms[i].coords[0][1] < self.coords_input1[1] < self.rooms[i].coords[len(self.rooms[i].coords)-1][1] or self.rooms[i].coords[0][1] > self.coords_input1[1] > self.rooms[i].coords[len(self.rooms[i].coords)-1][1]:
                                        Y = self.rooms[i].coords[j-1][1] 
                                        X = ((Y - self.coords_input1[1])/m_) + self.coords_input1[0]  
                                        # mX - Y + (self.coords_input1[1] - m.self.coords_input1[0]) = 0
                                        pts[(X,Y)] = abs( m_*X - Y + (self.coords_input1[1] - m_*self.coords_input1[0]) )/((m_**2 + 1)**.5)
                                    elif self.rooms[i].coords[0][1] < self.coords_input2[1] < self.rooms[i].coords[len(self.rooms[i].coords)-1][1] or self.rooms[i].coords[0][1] > self.coords_input2[1] > self.rooms[i].coords[len(self.rooms[i].coords)-1][1]:
                                        Y = self.rooms[i].coords[j-1][1]
                                        X = ((Y - self.coords_input2[1])/m_) + self.coords_input2[0]
                                        pts[(X,Y)] = abs( m_*X - Y + (self.coords_input1[1] - m_*self.coords_input1[0]) )/((m_**2 + 1)**.5)
                                    
                                elif m_ == "NOT DEFINED":
                                    if self.rooms[i].coords[0][1] < self.coords_input1[1] < self.rooms[i].coords[len(self.rooms[i].coords)-1][1] or self.rooms[i].coords[0][1] > self.coords_input1[1] > self.rooms[i].coords[len(self.rooms[i].coords)-1][1]:
                                        X = ((self.coords_input1[1] - self.rooms[i].coords[j-1][1])/m) + self.rooms[i].coords[j-1][0] 
                                        Y = self.coords_input1[1]
                                        pts[(X,Y)] = abs(X - self.coords_input1[0])
                                    elif self.rooms[i].coords[0][1] < self.coords_input2[1] < self.rooms[i].coords[len(self.rooms[i].coords)-1][1] or self.rooms[i].coords[0][1] > self.coords_input2[1] > self.rooms[i].coords[len(self.rooms[i].coords)-1][1]:
                                        X = ((self.coords_input2[1] - self.rooms[i].coords[j-1][1])/m) + self.rooms[i].coords[j-1][0] 
                                        Y = self.coords_input2[1]
                                        pts[(X,Y)] = abs(X - self.coords_input2[0])

                    # case 2 : both in

                    m = self.slope(self.coords_input1,self.coords_input2)
                    temp = self.rooms[i].coords[j]
                    if m != "NOT DEFINED":
                        # Y - self.coords_input1[1] = m(X - self.coords_input1[0]) => mX - Y + (self.coords_input1[1] - m.self.coords_input1[0]) = 0
                        pts[(temp[0],temp[1])] = abs( m*temp[0] - temp[1] + (self.coords_input1[1] - m*self.coords_input1[0]) )/((m**2 + 1)**.5)
                    else:
                        pts[(temp[0],temp[1])] = abs(temp[0] - self.coords_input1[0])

    # case 3 : both out

        for i in range(len(nbd_rooms)):
            for j in range(len(self.rooms[i].coords)):  
                n = len(self.rooms[i].coords[j])    
                if self.rooms[i].coords[j] != self.coords_input1 or self.rooms[i].coords[j] != self.coords_input2:
                    if j!=0:
                        m = self.slope(self.rooms[i].coords[j],self.rooms[i].coords[j-1])
                        m_ = self.slope(self.coords_input1,self.coords_input2)
                        if m != 'NOT DEFINED':
                            if m_ != "NOT DEFINED" and m_ != 0:
                                m_ = -1/m_
                                X = ( self.coords_input1[1] - self.rooms[i].coords[j-1][1] - (m_*self.coords_input1[0] - m*self.rooms[i].coords[j-1][0]) )/(m-m_)
                                Y = m_*(X - self.coords_input1[0]) + self.coords_input1[1]
                                pts[(X,Y)] = abs( m_*X - Y + (self.coords_input1[1] - m_*self.coords_input1[0]) )/((m_**2 + 1)**.5)

                                X = ( self.coords_input2[1] - self.rooms[i].coords[j-1][1] - (m_*self.coords_input2[0] - m*self.rooms[i].coords[j-1][0]) )/(m-m_)
                                Y = m_*(X - self.coords_input2[0]) + self.coords_input2[1]
                                pts[(X,Y)] = abs( m_*X - Y + (self.coords_input2[1] - m_*self.coords_input2[0]) )/((m_**2 + 1)**.5)
                            elif m_ != "NOT DEFINED" and m_ == 0:
                                
                                X = self.coords_input1[0]
                                Y = m_*(X - self.coords_input1[0]) + self.coords_input1[1]
                                pts[(X,Y)] = abs( m_*X - Y + (self.coords_input1[1] - m_*self.coords_input1[0]) )/((m_**2 + 1)**.5)

                                X = self.coords_input2[0]
                                Y = m_*(X - self.coords_input2[0]) + self.coords_input2[1]
                                pts[(X,Y)] = abs( m_*X - Y + (self.coords_input2[1] - m_*self.coords_input2[0]) )/((m_**2 + 1)**.5)
                            else:
                                Y = self.coords_input1[1]
                                X = (Y - self.rooms[i].coords[j-1][1])/m + self.rooms[i].coords[j-1][0] 
                                pts[(X,Y)] = abs(X - self.coords_input1[0])

                                Y = self.coords_input2[1]
                                X = (Y - self.rooms[i].coords[j-1][1])/m + self.rooms[i].coords[j-1][0] 
                                pts[(X,Y)] = abs(X - self.coords_input2[0])
                        else:
                            if m_ != "NOT DEFINED" and m_ != 0:
                                m_ = -1/m_
                                X = self.rooms[i].coords[j-1][0]
                                Y = m_*(X - self.coords_input1[0]) + self.coords_input1[1]
                                pts[(X,Y)] = abs( m_*X - Y + (self.coords_input1[1] - m_*self.coords_input1[0]) )/((m_**2 + 1)**.5)

                                X = self.rooms[i].coords[j-1][0]
                                Y = m_*(X - self.coords_input2[0]) + self.coords_input2[1]
                                pts[(X,Y)] = abs( m_*X - Y + (self.coords_input2[1] - m_*self.coords_input2[0]) )/((m_**2 + 1)**.5)
                            elif m_ == "NOT DEFINED":
                                Y = self.coords_input1[1]
                                X = self.rooms[i].coords[j][0]
                                pts[(X,Y)] = abs(X - self.coords_input1[0])

                                Y = self.coords_input2[1]
                                X = self.rooms[i].coords[j][0]
                                pts[(X,Y)] = abs(X - self.coords_input2[0])      
                    else:
                        m = self.slope(self.rooms[i].coords[j],self.rooms[i].coords[n-1])
                        if m != 'NOT DEFINED':
                            if m_ != "NOT DEFINED" and m_ != 0:
                                m_ = -1/m_
                                X = ( self.coords_input1[1] - self.rooms[i].coords[n-1][1] - (m_*self.coords_input1[0] - m*self.rooms[i].coords[n-1][0]) )/(m-m_)
                                Y = m_*(X - self.coords_input1[0]) + self.coords_input1[1]
                                pts[(X,Y)] = abs( m_*X - Y + (self.coords_input1[1] - m_*self.coords_input1[0]) )/((m_**2 + 1)**.5)

                                X = ( self.coords_input2[1] - self.rooms[i].coords[n-1][1] - (m_*self.coords_input2[0] - m*self.rooms[i].coords[n-1][0]) )/(m-m_)
                                Y = m_*(X - self.coords_input2[0]) + self.coords_input2[1]
                                pts[(X,Y)] = abs( m_*X - Y + (self.coords_input2[1] - m_*self.coords_input2[0]) )/((m_**2 + 1)**.5)
                            elif m_ != "NOT DEFINED" and m_ == 0:
                                
                                X = self.coords_input1[0]
                                Y = m_*(X - self.coords_input1[0]) + self.coords_input1[1]
                                pts[(X,Y)] = abs( m_*X - Y + (self.coords_input1[1] - m_*self.coords_input1[0]) )/((m_**2 + 1)**.5)

                                X = self.coords_input2[0]
                                Y = m_*(X - self.coords_input2[0]) + self.coords_input2[1]
                                pts[(X,Y)] = abs( m_*X - Y + (self.coords_input2[1] - m_*self.coords_input2[0]) )/((m_**2 + 1)**.5)
                            else:
                                Y = self.coords_input1[1]
                                X = (Y - self.rooms[i].coords[n-1][1])/m + self.rooms[i].coords[n-1][0] 
                                pts[(X,Y)] = abs(X - self.coords_input1[0])

                                Y = self.coords_input2[1]
                                X = (Y - self.rooms[i].coords[n-1][1])/m + self.rooms[i].coords[n-1][0] 
                                pts[(X,Y)] = abs(X - self.coords_input2[0])
                        else:
                            if m_ != "NOT DEFINED" and m_ != 0:
                                m_ = -1/m_
                                X = self.rooms[i].coords[n-1][0]
                                Y = m_*(X - self.coords_input1[0]) + self.coords_input1[1]
                                pts[(X,Y)] = abs( m_*X - Y + (self.coords_input1[1] - m_*self.coords_input1[0]) )/((m_**2 + 1)**.5)

                                X = self.rooms[i].coords[n-1][0]
                                Y = m_*(X - self.coords_input2[0]) + self.coords_input2[1]
                                pts[(X,Y)] = abs( m_*X - Y + (self.coords_input2[1] - m_*self.coords_input2[0]) )/((m_**2 + 1)**.5)
                            elif m_ == "NOT DEFINED":
                                Y = self.coords_input1[1]
                                X = self.rooms[i].coords[j][0]
                                pts[(X,Y)] = abs(X - self.coords_input1[0])

                                Y = self.coords_input2[1]
                                X = self.rooms[i].coords[j][0]
                                pts[(X,Y)] = abs(X - self.coords_input2[0])

        
        # Y - self.coords_input1[1] = (m_)(X - self.coords_input1[0])
        print(pts) 
        answer_left = []
        answer_right = []
        
        if self.opti == 0 or self.opti == 1:
            for i in pts.keys():
                if isinstance(pts[i], float) and not math.isinf(pts[i]) and not math.isnan(pts[i]):
                    if i[0] - self.coords_input1[0] < 0:
                        answer_left.append(pts[i])
                    if i[0] - self.coords_input1[0] > 0:
                        answer_right.append(pts[i])
        if self.opti == 2 or self.opti == 3:
            for i in pts.keys():
                if isinstance(pts[i], float) and not math.isinf(pts[i]) and not math.isnan(pts[i]):
                    if i[1] - self.coords_input1[1] < 0:
                        answer_left.append(pts[i])
                    if i[1] - self.coords_input1[1] > 0:
                        answer_right.append(pts[i])     
        if len(answer_left) == 0:
            answer_left.append(0)
        if len(answer_right) == 0:
            answer_right.append(0)
        print("can move towards the left by : ", max(answer_left))
        print("can move towards the right by : ", max(answer_right)) 
        return (max(answer_left),max(answer_right))

    # def find_limits(self,adj_mat,rooms):
    #     print()
    #     print()
    #     print()
    #     print("printing all room coords")
    #     for i in range(len(self.rooms)):
    #         print(self.rooms[i].coords)      #The order of self.rooms is like 1st room , 2nd room ..... 8th room, 0th room.
    #     print(f"Adj MAT = {self.adj_mat}")    #There is a node with 0 index in the graph, hence there is a zero room.
    #     self.wall_input()
        # run(self.rooms,self.adj_mat)

if __name__ == "__main__":
    print()
    # LimitsAlgorithm().find_limits(Null,Null)