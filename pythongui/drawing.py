"""Drawing Module

"""
import networkx as nx 
import numpy as np 
import turtle
# import ptpg
import source.floorplangen.dual as dual
import math
import source.polygonal.poly as poly
from source.polygonal.draw import DrawOuterBoundary
import source.inputgraph as inputgraph


scale = 300
origin = {'x': 300, 'y': -150}

def find_points(x1, y1, x2, y2,
               x3, y3, x4, y4):
    x7 = max(x1, x3)
    y8 = max(y1, y3)
    x8 = min(x2, x4)
    y7 = min(y2, y4)
    first_rect = ""
    second_rect = ""
    if(x7 == x8):
        if(x7 == x2):
            first_rect = "right"
            second_rect = "left"
        elif(x7 == x1):
            first_rect = "left"
            second_rect = "right"
    if(y7 == y8):
        if(y7 == y2):
            first_rect = "top"
            second_rect = "bottom"
        elif(y7 == y1):
            first_rect = "bottom"
            second_rect = "top"
    
    
    return [(x7,y7), (x8,y8)],first_rect,second_rect

# Draw rectangular dual of graph
# import turtle as pen
def find_areas(graph):
    for shape in graph.final_traversal:
        area = 0
        for j in range(len(shape) ):
            x1, y1 = shape[j]
            x2, y2 = shape[(j + 1)%len(shape)]
            area += x1 * y2 - x2 * y1
        graph.area.append(abs(area)/2)

def draw_rdg(graph,count,pen,mode,color_list,room_names,origin,scale=True):

    pen.width(1.5)
    pen.color('black')
    pen.hideturtle()
    pen.penup()
    shapes=graph.final_traversal
    find_areas(graph)
    print(graph.area)
    max_area=np.amax(graph.area)
    plot_area=np.sum(graph.area)
    scale=100*(math.exp(-0.3*math.sqrt(max_area)+math.log(0.8))+0.1)
    # dim gives the bounding box for the rfp
    dim=[0,0]
    dim[0] = max(coord[0] for shape in shapes for coord in shape)
    dim[1] = max(coord[1] for shape in shapes for coord in shape)
    origin = {'x': origin - 100, 'y': -100}
    #Drawing the rooms
    for i, shape_coords in enumerate(shapes):
        pen.fillcolor(color_list[i%len(color_list)])
        pen.begin_fill()
        start_x, start_y = shape_coords[0]
        pen.setposition(start_x * scale + origin['x'], start_y * scale + origin['y'])
        pen.pendown()

        for coord in shape_coords:
            x, y = coord
            pen.setposition(x * scale + origin['x'], y * scale + origin['y'])
            pen.pendown()

        pen.setposition(start_x * scale + origin['x'], start_y * scale + origin['y'])
        pen.penup()

        pen.end_fill()
    #Writing the Room numbers
    for i in range(len(shapes)):
        pen.setposition(((2 * shapes[i][0][0] ) * scale / 2) + origin['x'] + 5,
                        ((shapes[i][0][1] + shapes[i][1][1]) * scale / 2) + origin['y'])
        pen.write(i)
        pen.penup()
    value = 1
    #Writing areas of each room and height width for rectangular rooms
    if(len(graph.area) != 0):
        pen.setposition(dim[0]* scale + origin['x']+50, dim[1]* scale + origin['y']-30)
        pen.write('Area of Each Room' ,font=("Arial", 20, "normal"))
        for i in range(0,len(graph.area)):
            shape=shapes[i]
            heigt=shape[1][1] - shape[0][1]
            width=shape[3][0] - shape[0][0]
            pen.setposition(dim[0]* scale + origin['x']+50, dim[1]* scale + origin['y']-30-value*30)
            if(len(shape)==4):
                if not room_names:
                    pen.write('Room ' + str(i)+ ': '+
                              'Area: '+ str(graph.area[i])+
                              ' H: ' + str(heigt)+
                              ' W: ' + str(width)
                              ,font=("Arial", 15, "normal"))
                else:
                    pen.write(str(room_names[i]) + ': ' + str(graph.area[i]),font=("Arial", 15, "normal"))
            else:
                if not room_names:
                    pen.write('Room ' + str(i)+ ': ' +
                              'Area: '+ str(graph.area[i])+
                              'H: ' + str(heigt)+
                              'W: ' + str(width),
                              font=("Arial", 15, "normal"))
                else:
                    pen.write(str(room_names[i]) + ': ' + str(graph.area[i]),font=("Arial", 15, "normal"))
            pen.penup()
            value+=1

def draw_rdg2(graph_data,count,pen,mode,color_list,room_names,origin):
    coordinates = {}
    for i in range(graph_data['room_x'].shape[0]):
        data = []
        data.append([(graph_data['room_x'][i],graph_data['room_y'][i]),
                        (graph_data['room_x'][i] + graph_data['room_width'][i],graph_data['room_y'][i])])
        data.append([(graph_data['room_x'][i] + graph_data['room_width'][i],graph_data['room_y'][i]),
                        (graph_data['room_x'][i] + graph_data['room_width'][i],graph_data['room_y'][i] + graph_data['room_height'][i])])
        data.append([(graph_data['room_x'][i] + graph_data['room_width'][i],graph_data['room_y'][i] + graph_data['room_height'][i]),
                        (graph_data['room_x'][i],graph_data['room_y'][i] + graph_data['room_height'][i])])
        data.append([(graph_data['room_x'][i],graph_data['room_y'][i] + graph_data['room_height'][i]),
                        (graph_data['room_x'][i],graph_data['room_y'][i])])
        coordinates[i] = data
        print(data)
        #find_limits(self.adj_mat,self.rooms)     #temporary, to be erased, as it will run everytime
                                                 #button for finding limits needs to be made
    
    for i in range(len(graph_data['mergednodes'])):
        node_1 = graph_data['mergednodes'][i]
        node_2 = graph_data['irreg_nodes'][i]
        common_points,first_room_dir,second_room_dir = find_points(graph_data['room_x'][node_1],
                                                            graph_data['room_y'][node_1],
                                                            graph_data['room_x'][node_1] + graph_data['room_width'][node_1],
                                                            graph_data['room_y'][node_1] + graph_data['room_height'][node_1],
                                                            graph_data['room_x'][node_2],
                                                            graph_data['room_y'][node_2],
                                                            graph_data['room_x'][node_2] + graph_data['room_width'][node_2],
                                                            graph_data['room_y'][node_2] + graph_data['room_height'][node_2])
        if(first_room_dir == 'bottom'):
            coordinates[node_1][0].append(common_points[0])
            coordinates[node_1][0].append(common_points[1])
        elif(first_room_dir == 'right'):
            coordinates[node_1][1].append(common_points[0])
            coordinates[node_1][1].append(common_points[1])
        elif(first_room_dir == 'top'):
            coordinates[node_1][2].append(common_points[0])
            coordinates[node_1][2].append(common_points[1])
        elif(first_room_dir == 'left'):
            coordinates[node_1][3].append(common_points[0])
            coordinates[node_1][3].append(common_points[1])

        if(second_room_dir == 'bottom'):
            coordinates[node_2][0].append(common_points[0])
            coordinates[node_2][0].append(common_points[1])
        elif(second_room_dir == 'right'):
            coordinates[node_2][1].append(common_points[0])
            coordinates[node_2][1].append(common_points[1])
        elif(second_room_dir == 'top'):
            coordinates[node_2][2].append(common_points[0])
            coordinates[node_2][2].append(common_points[1])
        elif(second_room_dir == 'left'):
            coordinates[node_2][3].append(common_points[0])
            coordinates[node_2][3].append(common_points[1])

    for i in coordinates:
        coordinates[i][0] = sorted(coordinates[i][0], key = lambda x: x[0])
        coordinates[i][1] = sorted(coordinates[i][1], key = lambda x: x[1])
        coordinates[i][2] = sorted(coordinates[i][2], key = lambda x: x[0], reverse=True)
        coordinates[i][3] = sorted(coordinates[i][3], key = lambda x: x[1], reverse=True)

    pen.width(1.5)
    pen.color('black')
    pen.hideturtle()
    pen.penup()
    width= np.amax(graph_data['room_width'])
    height = np.amax(graph_data['room_height'])
    if(width == 0):
        width = 1
    if(height == 0):
        height = 1
    if(width < height):
        width = height
    scale = 100*(math.exp(-0.30*width+math.log(0.8)) + 0.1)
    # origin = {'x': graph_data[origin, 'y': -550}
    dim =[0,0]
    origin = {'x': origin - 400, 'y': -100}
    for i in range(graph_data['room_x'].shape[0]):
        if graph_data['room_width'][i] == 0 or i in graph_data['extranodes']:
            continue
        if i in graph_data['mergednodes']:
            pen.fillcolor(color_list[graph_data['irreg_nodes'][graph_data['mergednodes'].index(i)]])
        else:
            pen.fillcolor(color_list[i])
        pen.begin_fill()
        for dir in range(4):
            for idx in range(len(coordinates[i][dir])):
                if(idx%2 == 0):
                    pen.setposition(coordinates[i][dir][idx][0] * scale + origin['x'],
                                    coordinates[i][dir][idx][1] * scale + origin['y'])
                    pen.pendown()
                else:
                    pen.setposition(coordinates[i][dir][idx][0] * scale + origin['x'],
                                    coordinates[i][dir][idx][1] * scale + origin['y'])
                    pen.penup()
        pen.end_fill()
        if(graph_data['room_x'][i] + graph_data['room_width'][i]> dim[0] ):
            dim[0] = graph_data['room_x'][i] + graph_data['room_width'][i]
        if(graph_data['room_y'][i] + graph_data['room_height'][i]> dim[1] ):
            dim[1] = graph_data['room_y'][i] + graph_data['room_height'][i]
    x_index = int(np.where(graph_data['room_x'] == np.min(graph_data['room_x']))[0][0])
    y_index = int(np.where(graph_data['room_y'] == np.max(graph_data['room_y']))[0][0])
    pen.setposition((graph_data['room_x'][x_index]) * scale + origin['x'],(graph_data['room_y'][y_index] + graph_data['room_height'][y_index]) * scale + origin['y'] + 200)  
    pen.write(count,font=("Arial", 20, "normal"))
    pen.penup()
    for i in range(graph_data['room_x'].shape[0]):
        if i in graph_data['extranodes']:
            continue
        pen.color('black')
        if(i not in graph_data['mergednodes']):
            pen.setposition(((2 * graph_data['room_x'][i] ) * scale / 2) + origin['x'] + 5,
                            ((2 * graph_data['room_y'][i] + graph_data['room_height'][i]) * scale / 2) + origin['y'])
            if not room_names:
                pen.write(i)
            else:
                pen.write(room_names[i])
            pen.penup()
        if(i in graph_data['mergednodes'] and mode == 2):
            pen.setposition(((2 * graph_data['room_x'][i] ) * scale / 2) + origin['x'] + 5,
                            ((2 * graph_data['room_y'][i] + graph_data['room_height'][i]) * scale / 2) + origin['y'])
            if not room_names:
                pen.write(i)
            else:
                pen.write(room_names[i])
            pen.penup()       
    value = 1
    if(len(graph_data['area']) != 0):
        pen.setposition(dim[0]* scale + origin['x']+50, dim[1]* scale + origin['y']-30)
        pen.write('Area of Each Room' ,font=("Arial", 20, "normal"))
        for i in range(0,len(graph_data['area'])):
            if i in graph_data['extranodes']:
                continue
            pen.setposition(dim[0]* scale + origin['x']+50, dim[1]* scale + origin['y']-30-value*30)
            # pen.write('Room ' + str(i)+ ': '+ str(graph_data['area'][i]),font=("Arial", 15, "normal"))
            if not room_names:
                pen.write('Room ' + str(i)+ ': ' + 'W:' + str(graph_data['room_width'][i])+ '  H:' + str(graph_data['room_height'][i]),font=("Arial", 15, "normal"))
            else:
                pen.write(str(room_names[i]) + ': ' + 'W:' + str(graph_data['room_width'][i])+ '  H:' + str(graph_data['room_height'][i]),font=("Arial", 15, "normal"))
            pen.penup()
            value+=1

def draw_poly(graph_data,count,pen,mode,color_list,room_names,origin,outer_boundary,shape,adj_mat):
    innerBoundary = []
    if(outer_boundary!=[]): #To take active front as input first in the drawing
        temp = outer_boundary[0]
        for i in range(0,len(outer_boundary)):
            corner = []
            if i==0:
                corner.append(outer_boundary[i][2])
                corner.append(outer_boundary[i][3])
            else:
                corner.append(outer_boundary[i][2])
                corner.append(2*outer_boundary[0][3] - outer_boundary[i][3])
            innerBoundary.append(corner)
        corner1 = []
        corner1.append(outer_boundary[0][0])
        corner1.append(outer_boundary[0][1])    
        innerBoundary.append(corner1)
    
    db = poly.dissected(graph_data,pen,color_list,shape,adj_mat,innerBoundary)
    # obj = DrawOuterBoundary(graph_data,pen,color_list)
    