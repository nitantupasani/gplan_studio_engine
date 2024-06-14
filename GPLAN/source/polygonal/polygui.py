import math
import tkinter as tk
import turtle
import time
from numpy import outer

class PolyGUI:
    def __init__(self,pen,graph_data,rooms,color_list, outer):
        self.pen = pen
        self.graph_data = graph_data
        self.color_list = color_list
        self.noOfNodes = len(self.graph_data['iteration'])
        # self.correctCanonicalOrder = self.graph_data['currentCanonicalOrder'][self.noOfNodes-1]
        self.scale = 0.5*self.noOfNodes/10 #MODIFY SCALE
        self.inner = outer
        self.rooms = rooms
        # self.startDisection()
        
    def startDisection(self):
        # self.canvas = screen.getcanvas()

        # button = tk.Button(canvas.master, text="Press me", command=press)
        # button.pack()
        
        # canvas.create_window(-200, -200, window=button)
        
        # Test Cases
        # self.hline(0,100,0)
        # self.lshape([-100,0],[100,-200])
        # self.createPentagon()
        # self.createInitalRoomsForPentagon()
        for room in range(0,len(self.rooms)):
            # if(room==2):
            #     continue
            start_coord = (0,0) #IMP this is the initial starting coordinate of the dissection
            self.pen.penup()
            self.pen.goto(start_coord)
            self.pen.setheading(0)
            self.pen.fillcolor(self.color_list[int(self.graph_data['indexToCanOrd'][room])])
            self.pen.begin_fill()

            initialCoord =  self.rooms[room].coords[0]
            self.pen.goto((initialCoord[0],initialCoord[1]))
            self.pen.pendown()
            for corner in range(1,len(self.rooms[room].coords)):
                nextCoords =  self.rooms[room].coords[corner] 
                self.pen.goto((nextCoords[0],nextCoords[1]))
            self.pen.goto((initialCoord[0],initialCoord[1]))
            self.pen.penup()
            self.pen.end_fill()
            # time.sleep(1)

            # start_coord = (0,0) #IMP this is the initial starting coordinate of the dissection
            # self.pen.penup()
            # self.pen.goto(start_coord)
            # self.pen.setheading(0)
            # initialCoord =  self.rooms[room].coords[0]
            # self.pen.goto((initialCoord[0]*self.scale,initialCoord[1]*self.scale))
            # self.pen.pendown()
            # for corner in range(1,len(self.rooms[room].coords)):
            #     nextCoords =  self.rooms[room].coords[corner] 
            #     self.pen.goto((nextCoords[0]*self.scale,nextCoords[1]*self.scale))
            # self.pen.penup()
        
        # FOR TEXT

        # self.pen.color('black')
        # for room in range(0,len(self.rooms)):
        #     if(room==2):
        #         continue
        #     self.pen.setposition(self.find_Centroid(list(self.rooms[room].coords)))
        #     self.pen.write(room)
        #     self.pen.penup()       

        self.pen.hideturtle()

    def createPentagon(self,coordinatepoints):
        initial_coord = (-200*self.scale,300*self.scale) #IMP this is the initial starting coordinate of the dissection
        self.pen.penup()
        self.pen.goto(initial_coord)
        
        # self.pen.fillcolor(self.color_list[int(self.graph_data['indexToCanOrd'][2])])
        # self.pen.begin_fill()

        #self.pen.pendown()
        for i in range(5):
            CoordA = self.pen.pos()
            coordinatepoints[i+1] = CoordA #this sets the values of the coordinates of the polygon's vertices
            self.pen.forward(400*self.scale) #Assuming the side of a pentagon is 400 units 
            self.pen.right(72) #Turning the turtle by 72 degree

        # self.pen.end_fill()

    def createInitalRoomsForPentagon(self,coordinatepoints):
        
        initial_coord = (-150*self.scale,300*self.scale) #now starting the second side 
        self.pen.penup()

        self.pen.goto(initial_coord)
        self.pen.setheading(0)
        coordinatepoints[6] = self.pen.pos()
        
        # self.pen.fillcolor(self.color_list[int(self.graph_data['indexToCanOrd'][0])])
        # self.pen.begin_fill()

        #self.pen.pendown()
        self.pen.right(108)

        # self.pen.left(72) #Turning the turtle by 72 degree
        self.pen.forward(400*self.scale) #Assuming the side of a pentagon is 400 units 
        coordinatepoints[7] = self.pen.pos()
        self.pen.left(72) #Turning the turtle by 72 degree
        length = 400 - 50*math.cos(math.pi/5) + 50*(math.sin(math.pi/5)/math.tan(2*math.pi/5))
        self.pen.forward(length*self.scale) #Assuming the side of a pentagon is 400 units
        coordinatepoints[8] = self.pen.pos() 
 
        # self.pen.end_fill()
 
        initial_coord = (150*self.scale,300*self.scale) #coordinate number 6
        self.pen.penup()
        self.pen.goto(initial_coord)
        self.pen.setheading(0)
        coordinatepoints[9] = self.pen.pos() #the value is stored in the dictionary

        # self.pen.fillcolor(self.color_list[int(self.graph_data['indexToCanOrd'][1])])
        # self.pen.begin_fill()

        #self.pen.pendown()

        self.pen.right(72) #Turning the turtle by 72 degree
        self.pen.forward(400*self.scale) #Assuming the side of a pentagon is 400 units
        coordinatepoints[10] = self.pen.pos()
        self.pen.right(72) #Turning the turtle by 72 degree
        length = 400 - 50*math.cos(math.pi/5) - 25/math.cos(math.pi/5) + 50*(math.sin(math.pi/5)/math.tan(2*math.pi/5))
        # print(length)
        self.pen.forward(length*self.scale) #Assuming the side of a pentagon is 400 units
        coordinatepoints[11] = self.pen.pos()
        
        # self.pen.end_fill()

         
               #created the initial rooms and also put their coordinates in the self function
        #now will use these to initialise the rooms in the datastructure which stores the room coordinates
    
    def createHexagon(self,coordinatepoints):
        initial_coord = (-200*self.scale,300*self.scale) #IMP this is the initial starting coordinate of the dissection
        self.pen.penup()
        self.pen.goto(initial_coord)
        
        # self.pen.fillcolor(self.color_list[int(self.graph_data['indexToCanOrd'][2])])
        # self.pen.begin_fill()

        #self.pen.pendown()
        for i in range(6):
            CoordA = self.pen.pos()
            coordinatepoints[i+1] = CoordA #this sets the values of the coordinates of the polygon's vertices
            self.pen.forward(400*self.scale) #Assuming the side of a pentagon is 400 units 
            self.pen.right(60) #Turning the turtle by 60 degree

        # self.pen.end_fill()

    def createInitalRoomsForHexagon(self,coordinatepoints):
        
        initial_coord = (-150*self.scale,300*self.scale) #now starting the second side 
        self.pen.penup()

        self.pen.goto(initial_coord)
        self.pen.setheading(0)
        coordinatepoints[7] = self.pen.pos()
        
        # self.pen.fillcolor(self.color_list[int(self.graph_data['indexToCanOrd'][0])])
        # self.pen.begin_fill()

        #self.pen.pendown()
        self.pen.right(120)

        # self.pen.left(72) #Turning the turtle by 72 degree
        self.pen.forward(400*self.scale) #Assuming the side of a pentagon is 400 units 
        coordinatepoints[8] = self.pen.pos()
        self.pen.left(60) #Turning the turtle by 60 degree
        length = 400
        self.pen.forward(length*self.scale) #Assuming the side of a pentagon is 400 units
        coordinatepoints[9] = self.pen.pos() 
 
        # self.pen.end_fill()
 
        initial_coord = (150*self.scale,300*self.scale) #coordinate number 6
        self.pen.penup()
        self.pen.goto(initial_coord)
        self.pen.setheading(0)
        coordinatepoints[10] = self.pen.pos() #the value is stored in the dictionary

        # self.pen.fillcolor(self.color_list[int(self.graph_data['indexToCanOrd'][1])])
        # self.pen.begin_fill()

        #self.pen.pendown()

        self.pen.right(60) #Turning the turtle by 60 degree
        self.pen.forward(400*self.scale) #Assuming the side of a pentagon is 400 units
        coordinatepoints[11] = self.pen.pos()
        self.pen.right(60) #Turning the turtle by 60 degree
        length = 400 - 50/math.sin(math.pi/3) 
        # print(length)
        self.pen.forward(length*self.scale) #Assuming the side of a pentagon is 400 units
        coordinatepoints[12] = self.pen.pos()
        
        self.pen.right(60) #Turning the turtle by 60 degree
        length = 300 + 100/math.tan(math.pi/3) 
        # print(length)
        self.pen.forward(length*self.scale) #Assuming the side of a pentagon is 400 units
        coordinatepoints[13] = self.pen.pos()

    def createCustom(self, outer):
        #always take the coordinates starting from the top right corner
        #now the attribute self.outer contains a list of the inner boundary coordinate points
        #we first make the list of the outer boundary coordinate points as well
        #turtle doesn't move, we only need to decide  the coordinates here, which we have done
        # n = int(input("Enter number of points of outer boundary: "))
        # for i in range(n):
        #     x =  int(input("Enter x coordinates: "))
        #     y =  int(input("Enter y coordinates: "))
        #     outer.append((x,y))


        low = 0
        minval = self.inner[0][1]
        for i in range(1, len(self.inner),1):
            if(self.inner[i][1]<minval):
                low = i 
                minval = self.inner[i][1]
            else: 
                break
        for i in range(0, len(self.inner),1):
            if(self.inner[i][1]== minval):
                outercoord = []
                outercoord.append(self.inner[i][0])
                outercoord.append(self.inner[i][1] - 50) #hardcoded for now, will change later
                outer.append(outercoord)
            elif(i < low):
                outercoord = []
                outercoord.append(self.inner[i][0] + 50)
                outercoord.append(self.inner[i][1]) #hardcoded for now, will change later
                outer.append(outercoord)
            else:
                outercoord = []
                outercoord.append(self.inner[i][0]-50)
                outercoord.append(self.inner[i][1]) #hardcoded for now, will change later
                outer.append(outercoord)
        print(low)
        print(outer) 
        return low
        # self.pen.end_fill()

            

               #created the initial rooms and also put their coordinates in the self function
        #now will use these to initialise the rooms in the datastructure which stores the room coordinates




    # def hline(self, x1, x2 ,height):    #To create Horizontal Line
    # #     self.c.create_line(x1,height,x2,height, fill="black", width=3)
    #     x = (x1, height)
    #     y = (x2, height)

    #     self.pen.penup()
    #     self.pen.goto(x)
    #     self.pen.pendown()
    #     self.pen.goto(y)


    # def vline(self, y1, y2 ,width): #To create Vertical Line
    #     # self.c.create_line(width,y1,width,y2, fill="black", width=3)
    #     x = (width, y1)
    #     y = (width, y2)

    #     self.pen.penup()
    #     self.pen.goto(x)
    #     self.pen.pendown()
    #     self.pen.goto(y)

    # def lshape(self, top, end): #To create L Shaped Line

    #     self.vline(top[1],end[1],top[0])
    #     self.hline(top[0],end[0],end[1])

# def do_stuff():
#     for color in ["red", "yellow", "green"]:
#         my_lovely_turtle.color(color)
#         my_lovely_turtle.right(120)


# def press():
#     do_stuff()
    def find_Centroid(self,v):
        ans = [0, 0]
    
        n = len(v)
        signedArea = 0
    
        # For all vertices
        for i in range(len(v)):
    
            x0 = v[i][0]
            y0 = v[i][1]
            x1 = v[(i + 1) % n][0]
            y1 =v[(i + 1) % n][1]
    
            # Calculate value of A
            # using shoelace formula
            A = (x0 * y1) - (x1 * y0)
            signedArea += A
    
            # Calculating coordinates of
            # centroid of polygon
            ans[0] += (x0 + x1) * A
            ans[1] += (y0 + y1) * A
    
        signedArea *= 0.5
        ans[0] = (ans[0]) / (6 * signedArea)
        ans[1] = (ans[1]) / (6 * signedArea)
    
        return ans
 
# Driver code
 
# Coordinate of the vertices
# vp = [ [ 1, 2 ],
#        [ 3, -4 ],
#        [ 6, -7 ] ]
 
# ans = find_Centroid(vp)
 
# print(round(ans[0], 12), ans[1])

if __name__ == '__main__':
    top = tk.Tk()   
    c = tk.Canvas(top,bg = "white",height = "800",width= "800")  
    c.pack(side=tk.LEFT)
    screen = turtle.TurtleScreen(c)
    pen = turtle.RawTurtle(screen)
    PolyGUI(pen,{},{})
