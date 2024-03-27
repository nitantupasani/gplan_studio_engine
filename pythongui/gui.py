"""Main GUI of the project (implemented using Tkinter).


"""

import ast
import json
import os
import platform
import pickle
import random
import sys
import tkinter as tk
import tkinter.ttk as ttk
import turtle
import warnings
from tkinter import ALL, EventType, Label, Menu, filedialog, messagebox
import matplotlib.pyplot as plt
import networkx as nx
from PIL import Image, ImageTk
import sys

from networkx import edges
sys.path.append("..")
from GPLAN.pythongui import tablenoscroll as tablenoscroll
from GPLAN.pythongui import final as final
import numpy as np
import datetime
from fpdf import FPDF

from .catalogue_maker import generate_catalogue, generate_catalogue_dimensioned, generate_mindim_catalogue
from source.polygonal import canonical as cano


if os.environ.get('DISPLAY','') == '':
    print('no display found. Using :0.0')
    os.environ.__setitem__('DISPLAY', ':0.0')

done = True
col = ["white", "#9A8C98", "light grey", "white"]
# colors = ['#4BC0D9','#76E5FC','#6457A6','#5C2751','#7D8491','#BBBE64','#64F58D','#9DFFF9','#AB4E68','#C4A287','#6F9283','#696D7D','#1B1F3B','#454ADE','#FB6376','#6C969D','#519872','#3B5249','#A4B494','#CCFF66','#FFC800','#FF8427','#0F7173','#EF8354','#795663','#AF5B5B','#667761','#CF5C36','#F0BCD4','#ADB2D3','#FF1B1C','#6A994E','#386641','#8B2635','#2E3532','#124E78']*10
# colors = ['#4BC0D9']*10
rgb_colors = [
                 (123, 104, 238),  # medium slate blue
                 (64, 224, 208),  # turqouise
                 (255, 127, 80),  # coral
                 (255, 105, 180),  # hot pink
                 (230, 230, 250),  # lavender
                 (250, 128, 114),  # salmon
                 (152, 251, 152),  # pale green
                 (186, 85, 211),  # medium orchid
                 (176, 196, 222),  # light steel blue
                 (255, 165, 0),  # orange
                 (255, 218, 185),  # peach puff
                 (100, 149, 237),  # corn flower blue
             ] * 10
hex_colors = [
                 "#7B68EE",  # medium slate blue
                 "#40E0D0",  # turqouise
                 "#FF7F50",  # coral
                 "#FF69B4",  # hot pink
                 "#E6E6FA",  # lavender
                 "#FA8072",  # salmon
                 "#98FB98",  # pale green
                 "#BA55D3",  # medium orchid
                 "#B0C4DE",  # light steel blue
                 "#FFA500",  # orange
                 "#FFDAB9",  # peach puff
                 "#6495ED",  # corn flower blue
             ] * 10
colors = hex_colors
font = {'font': ("lato bold", 10, "")}
# reloader = Reloader()
warnings.filterwarnings("ignore")


class treenode:

    def __init__(self, parent, left, right, height, width, slice_type, d1, d2, d3, d4):
        self.parent = parent
        self.left = left
        self.right = right
        self.height = height
        self.width = width
        self.slice_type = slice_type
        self.d1 = d1
        self.d2 = d2
        self.d3 = d3
        self.d4 = d4


class gui_class:

    dimensional_constraints = []

    def __init__(self):
        
        self.open = False
        self.command = "Null"
        self.value = []
        self.root =tk.Tk()
        # For entry to start circulation
        self.entry_door = []
        self.l = tk.IntVar(None)
        self.l.set(0)
        self.r = tk.IntVar(None)
        self.r.set(1)
        self.left = 0
        self.right = 1
        self.entry_door.append(self.l)
        self.entry_door.append(self.r)

        # Circ_gui
        self.circ_choice = tk.IntVar(None)
        self.circ_choice.set(0)

        # Remove redundant rooms
        self.opti = tk.IntVar(None)
        self.rem = 0

        # To get user input for corridor thickness
        self.ct = tk.DoubleVar(None)
        self.ct.set(0.1)
        self.corridor_thickness=0.1
        self.remove_or_not = []
        self.remove_edges = []
        self.adjacency = {}
        # self.entry_door.append(self.l)
        # self.entry_door.append(self.r)
        self.canonicalObject = cano.canonical()
        self.entry_door = []
        self.letter = ""
        self.v1 = 0
        self.v2 = 0
        self.vn = 0
        self.po = ""
        self.shape = ""
        self.outer_boundary = []
        self.choice = tk.IntVar(None)
        self.v11 = tk.IntVar(None)
        self.v11.set(0)
        self.v22 = tk.IntVar(None)
        self.v22.set(1)
        self.vnn = tk.IntVar(None)
        self.vnn.set(2)
        self.shapes = tk.StringVar(None)
        self.shapes.set("Custom")
        self.outer_boundary2 = []
        self.priority_order = tk.StringVar(None)
        self.priority_order.set("")
        self.debugcano = tk.IntVar()
        self.canvasForOuterBoundary = None
        self.initialPoint = []
        self.finalPoint = []
        self.l = tk.IntVar(None)
        self.l.set(0)
        self.r = tk.IntVar(None)
        self.r.set(1)
        self.left = 0
        self.right = 1
        self.entry_door.append(self.l)
        self.entry_door.append(self.r)

        self.output_found = False
        self.json_data = {}
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        self.root.maxsize(screen_width, screen_height)
        self.open_ret = []
        # self.root.filename = 
        self.root.config(bg=col[2])
        self.textbox = tk.Text
        # self.pen = turtle.Screen()
        # self.pen = turtle.RawTurtle
        # self.pen.screen.bgcolor(col[2])
        self.end = tk.IntVar(self.root)
        self.frame2 = tk.Frame(self.root, bg=col[2])
        self.frame2.grid(row=0, column=1, rowspan=6, sticky='news')
        self.frame5 = tk.Frame(self.root, bg=col[2])
        self.frame5.grid(row=0, column=2, rowspan=3, sticky='news', padx=10)
        # self.tablehead = tk.Label(self.frame5,text='Room Info',bg =col[2])
        # self.tablehead.pack()

        self.app = self.PlotApp(self.frame2, self)
        self.root.title('Input Graph')
        self.checkvar1 = tk.IntVar()
        self.checkvar2 = tk.IntVar(None) # For dimensioned circ
        self.checkvar2.set(0)
        self.checkvar3 = tk.IntVar(None) # For remove/add circulation
        self.checkvar3.set(0)
        self.checkvar4 = tk.IntVar()

        self.e1 = tk.IntVar()
        self.e2 = tk.IntVar()

        self.tabledata = []
        self.frame1 = tk.Frame(self.root, bg=col[2])
        self.frame1.grid(row=0, column=0)

        label1 = tk.LabelFrame(self.frame1, text="tools")
        label1.grid(row=0, column=0, pady=10)
        self.frame3 = tk.Frame(self.root, bg=col[2])
        self.frame3.grid(row=1, column=0)

        self.Buttons(self.frame1, self)
        self.menu(self)
        self.root.protocol("WM_DELETE_WINDOW", self.exit)
        self.tbox = self.output_text(self.frame3)
        self.ocan = self.output_canvas(self.frame2)
        self.pen = self.ocan.getpen()
        self.dclass = None
        self.dissecting = 1
        self.root_window = self.ocan.getroot()
        self.root.wait_variable(self.end)
        self.graph_ret()
        self.cir_graph = nx.Graph()
        self.cir_dim_mat = []
        self.output_data = []
        self.time_taken = -1
        self.num_rfp = 0
        self.pdf_colors = []
        self.multiple_output_found = 0

        while ((self.value[0] == 0) and done):
            self.root.wait_variable(self.end)
            self.value = self.app.return_everything()
            tk.messagebox.showinfo("error", "The graph is empty , please draw a graph")

    class Nodes:
        def __init__(self, id, x, y):
            self.circle_id = id
            self.pos_x = x
            self.pos_y = y
            self.radius = 15
            self.adj_list = []

        def clear(self):
            self.circle_id = -1
            self.pos_x = 0
            self.pos_y = 0
            self.radius = 0
            self.adj_list = []

    class PlotApp:

        def __init__(self, toframe, master):
            root = tk.Frame(toframe)
            root.grid(row=0, column=0)
            self.root = root
            self.l1 = tk.Label(root, text='Draw a test graph here', bg=col[2])
            self.l1.grid(row=0, column=0)
            self._root = root
            self.radius_circle = 15
            self.rnames = []
            self.master = master
            self.command = "Null"
            self.table = tablenoscroll.Table(self.master.frame5, ["Index", "Room Name"], column_minwidths=[None, None])
            self.table.pack(padx=10, pady=10)
            self.table.config(bg="#F4A5AE")
            self.table.pack_forget()
            self.createCanvas()
            self.nodes_data = []

        # colors = ['#4BC0D9','#76E5FC','#6457A6','#5C2751','#7D8491','#BBBE64','#64F58D','#9DFFF9','#AB4E68','#C4A287','#6F9283','#696D7D','#1B1F3B','#454ADE','#FB6376','#6C969D','#519872','#3B5249','#A4B494','#CCFF66','#FFC800','#FF8427','#0F7173','#EF8354','#795663','#AF5B5B','#667761','#CF5C36','#F0BCD4','#ADB2D3','#FF1B1C','#6A994E','#386641','#8B2635','#2E3532','#124E78']
        # colors = ['#4BC0D9']*1000
        # colors = ['#edf1fe','#c6e3f7','#e1eaec','#e5e8f2','#def7fe','#f1ebda','#f3e2c6','#fff2de','#ecdfd6','#f5e6d3','#e3e7c4','#efdbcd','#ebf5f0','#cae1d9','#c3ddd6','#cef0cc','#9ab8c2','#ddffdd','#fdfff5','#eae9e0','#e0dddd','#f5ece7','#f6e6c5','#f4dbdc','#f4daf1','#f7cee0','#f8d0e7','#efa6aa','#fad6e5','#f9e8e2','#c4adc9','#f6e5f6','#feedca','#f2efe1','#fff5be','#ffffdd']
        colors = [
                     "#7B68EE",  # medium slate blue
                     "#40E0D0",  # turqouise
                     "#FF7F50",  # coral
                     "#FF69B4",  # hot pink
                     "#E6E6FA",  # lavender
                     "#FA8072",  # salmon
                     "#98FB98",  # pale green
                     "#BA55D3",  # medium orchid
                     "#B0C4DE",  # light steel blue
                     "#FFA500",  # orange
                     "#FFDAB9",  # peach puff
                     "#6495ED",  # corn flower blue
                 ] * 10
        nodes_data = []
        id_circle = []
        name_circle = []
        edge_count = 0
        hex_list = []
        multiple_rfp = 0
        cir = 0
        edges = []
        random_list = []
        connection = []
        oval = []
        rcanframe = []
        abc = 0
        xyz = 0
        elines = []
        connectivity = []

        def return_everything(self):
            node_coordinate = []
            for i in self.nodes_data:
                temp_node_data = []
                temp_node_data.append(i.pos_x)
                temp_node_data.append(i.pos_y)
                node_coordinate.append(temp_node_data)
            return [len(self.nodes_data), self.edge_count, self.edges, self.command, self.master.checkvar1.get(),
                    list(filter(None, [row[1].get() for row in self.table._data_vars])), self.hex_list, node_coordinate, self.master.checkvar2.get(), self.master.checkvar3.get(), self.master.checkvar4.get()]

        def createCanvas(self):
            self.id_circle.clear()
            self.name_circle.clear()
            for i in range(0, 100):
                self.id_circle.append(i)
            for i in range(0, 100):
                self.name_circle.append(str(i))
            self.nodes_data.clear()
            self.edges.clear()
            self.table._pop_all()
            self.edge_count = 0
            self.oval.clear()
            self.rcanframe.clear()
            self.abc = 0
            self.hex_list.clear()
            self.xyz = 0
            self.elines.clear()
            # border_details = {'highlightbackground': 'black', 'highlightcolor': 'black', 'highlightthickness': 1}
            self.canvas = tk.Canvas(self._root, bg=col[3], width=1000, height=370)
            self.canvas.grid(column=0, row=1, sticky='nwes')

            if (platform.system() == 'Darwin'):  # if MacOS
                self.canvas.bind("<Button-2>", self.addH)
                self.connection = []
                self.canvas.bind("<Button-1>", self.button_1_clicked)
                self.canvas.bind("<Button-3>", self.remove_node)

            elif (platform.system() == 'Windows' or platform.system() == 'Linux'):  # if Windows or Linux
                self.canvas.bind("<Button-3>", self.addH)
                self.connection = []
                self.canvas.bind("<Button-1>", self.button_1_clicked)
                self.canvas.bind("<Button-2>", self.remove_node)

            self.ButtonReset = tk.Button(self._root, text="Reset", fg='white', width=10, height=2, **font,
                                         relief='flat', bg=col[1], command=self.reset)
            self.ButtonReset.grid(column=0, row=1, sticky='n', pady=20, padx=40)

            self.ButtonPrev = tk.Button(self._root, text="Previous ", fg='white', width=10, height=2, **font,
                                        relief='flat', bg=col[1], command=self.open_recent)
            self.ButtonPrev.grid(column=0, row=1, sticky='ne', pady=20, padx=40)

            # self.instru = tk.Button(self._root, text="Instructions",fg='white',height=2 , **font ,relief = 'flat', bg=col[1] ,command=self.instructions)
            # self.instru.grid(column=0 ,row=1,sticky='wn',pady=22,padx=40)

            # self.lay = tk.Button(self._root, text="Switch to Layout",fg='white',height=2 ,**font,relief = 'flat',bg=col[1] ,command=self.switch)
            # self.lay.grid(column=0 ,row=1,sticky='ne',pady=20,padx=40)

        def open_recent(self):
            self.master.open_file("./saved_files/RFP_latest.txt")

        def switch(self):
            self.master.root.quit()
            final.run()

        def instructions(self):
            tk.messagebox.showinfo("Instructions",
                                   "--------User Instructrions--------\n 1. Draw the input graph. \n 2. Use right mouse click to create a new room. \n 3. left click on one node then left click on another to create an edge between them. \n 4. You can give your own room names by clicking on the room name in the graph or the table on the right. \n 5. After creating a graph you can choose one of the option to create it's corresponding RFP or multiple RFPs with or without dimension. You can also get the corridor connecting all the rooms by selecting 'circultion' or click on 'RFPchecker' to check if RFP exists for the given graph. \n 6. You can also select multiple options .You can also add rooms after creating RFP and click on RFP to re-create a new RFP. \n 7.Reset button is used to clear the input graph. \n 8. Press 'Exit' if you want to close the application or Press 'Restart' if you want to restart the application")

        def addH(self, event):
            x, y = event.x, event.y
            id_node = self.id_circle[0]
            self.id_circle.pop(0)
            self.create_new_node(x, y, id_node)

        def button_1_clicked(self, event):

            if len(self.connection) == 2:
                self.canvas.itemconfig(self.oval[self.xyz], outline='black')
                self.canvas.itemconfig(self.oval[self.abc], outline='black')
                self.connection = []
            if len(self.nodes_data) <= 1:
                tk.messagebox.showinfo("Connect Nodes", "Please make 2 or more nodes")
                return
            x, y = event.x, event.y
            value = self.get_id(x, y)
            self.abc = self.xyz
            self.xyz = self.nodes_data[value].circle_id
            self.hover_bright(event)
            if value == -1:
                evalue = self.get_edge(x, y)
                if evalue == -1:
                    return

                else:
                    self.toggle_edge_connectivity(evalue)
                return
            else:
                if value in self.connection:
                    tk.messagebox.showinfo("Connect Nodes", "You have clicked on same node. Please try again")
                    return
                self.connection.append(value)

            # changes
            if len(self.connection) > 1:
                node1 = self.connection[0]
                node2 = self.connection[1]
            

                if node2 not in self.nodes_data[node1].adj_list:
                    self.nodes_data[node1].adj_list.append(node2)
                if node1 not in self.nodes_data[node2].adj_list:
                    self.nodes_data[node2].adj_list.append(node1)
                    self.edge_count += 1

                #changes
                self.connection.append("black")
                #print("after appending black color",self.connection , self.edges)
                self.edges.append(self.connection.copy())
                self.connection.pop()
                #print("AFTER adding copy of connection to edges", self.connection,self.edges)

                self.connect_circles(self.connection)

        def connect_circles(self, connections):
            node1_id = connections[0]
            node2_id = connections[1]
            node1_x = self.nodes_data[node1_id].pos_x
            node1_y = self.nodes_data[node1_id].pos_y
            node2_x = self.nodes_data[node2_id].pos_x
            node2_y = self.nodes_data[node2_id].pos_y
            edge = self.canvas.create_line(node1_x, node1_y, node2_x, node2_y, width=3)
            self.elines.append([edge, connections])

        #changes
        def toggle_edge_connectivity(self, evalue):
            for node1_id, node2_id in evalue:
                for eid, connection in self.elines:
                    if (connection[0] == node1_id and connection[1] == node2_id) or (
                            connection[0] == node2_id and connection[1] == node1_id):
                        # print (self.canvas.itemcget(eid,"fill"))
                        # if self.canvas.itemcget(eid, "fill") == '#000000':
                            for edge in self.edges:
                                if ((edge[0] == node1_id and edge[1] == node2_id) or (edge[0] == node2_id and edge[1] == node1_id)) and edge[2]=="black":
                                    edge[2] = "red"
                                    self.canvas.itemconfig(eid, fill='red')
                                    self.connectivity.append(connection)
                                elif ((edge[0] == node1_id and edge[1] == node2_id) or (edge[0] == node2_id and edge[1] == node1_id)) and edge[2]=="red":
                                    self.canvas.delete(eid)
                                    self.elines.remove([eid,connection])
                                    self.edges.remove(edge)
                                    self.connectivity.remove(connection)
                            #print("to check whether we ad",connection)
                            # print("whether this is executing")

                            # for edge in self.edges:
                            #     if (edge[0] == node1_id and edge[1] == node2_id) or (edge[0] == node2_id and edge[1] == node1_id):
                            #         edge[2] = "red"

                            # self.connectivity.append(connection)

                        # else:
                        #     print (self.canvas.itemcget(eid,"fill"))
                        #     self.canvas.delete(eid)
                        #     self.elines.remove([eid,connection])
                        #     # self.canvas.itemconfig(eid, fill='black')
                            
                        
                        #     # self.canvas.itemconfig(eid, fill='black')
                        #     #print("changes",connection)
                        #     print("before removing",self.edges)


                        #     for edge in self.edges:
                        #         if ((edge[0] == node1_id and edge[1] == node2_id) or (edge[0] == node2_id and edge[1] == node1_id)) and edge[2]=="red":
                        #             print(edge[2])
                        #             self.edges.remove(edge)
                        #             # edge[2]="black"
                        #     try:
                        #         self.connectivity.remove(connection)
                        #     except:
                        #         pass

                            print("changes",self.edges)
                            print("changes in eline",self.elines)

            return
            
        def create_new_node(self, x, y, id_node):
            self.random_list.append(0)
            hex_number = self.colors[0]
            # self.colors.insert(len(self.colors),self.colors[0])
            self.colors.pop(0)
            self.hex_list.append(hex_number)
            node = self.master.Nodes(id_node, x, y)
            self.nodes_data.append(node)
            self.rframe = tk.Frame(self._root, width=20, height=20)
            self.rname = tk.StringVar(self._root)
            self.rnames.append(self.rname)
            self.rname.set(self.name_circle[0])
            self.table.insert_row(list((id_node, self.rname.get())), self.table._number_of_rows)
            self.name_circle.pop(0)
            self.rframe.grid(row=0, column=1)
            self.oval.append(
                self.canvas.create_oval(x - self.radius_circle, y - self.radius_circle, x + self.radius_circle,
                                        y + self.radius_circle, width=3, fill=hex_number, tag=str(id_node)))
            self.rcanframe.append(self.canvas.create_window(x, y - self.radius_circle - 12, window=self.rframe))
            self.entry = tk.Entry(self.rframe, textvariable=self.table._data_vars[self.id_circle[0] - 1][1],
                                  relief='flat', justify='c', width=7, bg='white')
            self.entry.grid()

        def retreive_graph(self, node_data, edge_data, con_data):

            for node in node_data:
                x = node[0]
                y = node[1]
                id_node = node[2]
                self.create_new_node(x, y, id_node)

            self.edges = edge_data
            for edge in self.edges:
                self.connect_circles(edge)

            self.connectivity = con_data

            for eid, connection in self.elines:
                revcon = []
                revcon.append(connection[1])
                revcon.append(connection[0])

                if connection in con_data or revcon in con_data:
                    self.canvas.itemconfig(eid, fill='red')

            self.edge_count = len(self.edges)

            self.id_circle.clear()
            self.name_circle.clear()
            for i in range(len(self.nodes_data), 100):
                self.id_circle.append(i)
            for i in range(len(self.nodes_data), 100):
                self.name_circle.append(str(i))

        def get_edge(self, x, y):
            ans = []
            for i_no, i in enumerate(self.nodes_data):
                for j_no, j in enumerate(self.nodes_data):
                    if i_no == j_no:
                        continue
                    epsi = (x - i.pos_x) * (i.pos_y - j.pos_y) / (i.pos_x - j.pos_x) + i.pos_y - y
                    if ((x <= j.pos_x and x >= i.pos_x) or (x >= i.pos_x and x <= i.pos_x)) and (
                            (y <= i.pos_y and y >= j.pos_y) or (
                            y >= i.pos_y and y <= j.pos_y)) and epsi < 10 and epsi > -10:
                        ans.append((i_no, j_no))
            if not ans:
                tk.messagebox.showinfo("Connect Nodes",
                                       "You have clicked outside all the circles and edges. Please try again")
                return -1
            else:
                return ans

        def get_id(self, x, y):
            for j, i in enumerate(self.nodes_data):
                distance = ((i.pos_x - x) ** 2 + (i.pos_y - y) ** 2) ** (1 / 2)
                if distance <= self.radius_circle:
                    return j
            # tk.messagebox.showinfo("Connect Nodes","You have clicked outside all the circles. Please try again")
            return -1

        def remove_node(self, event):
            id = self.get_id(event.x, event.y)
            # id = self.nodes_data[id].circle_id
            self.canvas.delete(self.oval[id])
            self.canvas.delete(self.rcanframe[id])
            for i in self.elines:
                if i[1][0] == id or i[1][1] == id:
                    self.canvas.delete(i[0])
                    self.edges.remove(i[1])
                    self.edge_count -= 1
            self.nodes_data[id].clear()
            self.nodes_data.pop(id)
            self.hex_list.pop(id)
            for j in range(self.table.number_of_columns):
                self.table._data_vars[id][j].set("")
            self.table._data_vars.pop(id)
            # self.edges.pop(id)
            # self.table.delete_row(id)
            i = id
            # while i < self.table._number_of_rows-1:
            #     row_of_vars_1 = self.table._data_vars[i]
            #     row_of_vars_2 = self.table._data_vars[i+1]

            #     j = 0
            #     while j <self.table._number_of_columns:
            #         row_of_vars_1[j].set(row_of_vars_2[j].get())
            #         j+=1
            #     i += 1

            # self.table._pop_n_rows(1)
            # self.table._number_of_rows-=1
            # self.table._data_vars.pop(id)
            for j in range(self.table.number_of_columns):
                self.table.grid_slaves(row=i + 1, column=j)[0].destroy()
            self.table._number_of_rows -= 1

            # if self.table._on_change_data is not None: self.table._on_change_data()

        def hover_bright(self, event):
            # self.canvas.itemconfig(self.oval[self.xyz],outline='red')
            self.canvas.itemconfig(self.oval[self.xyz], outline='black')

        def reset(self):
            self.canvas.destroy()
            self.edges = []
            self.output_data = []
            self.createCanvas()

    class dissected:
        def __init__(self, master, win=None):
            if (win is None):
                win = tk.Tk()
            tk.Entry(win)
            self.master = master
            self.current = None
            self.rootnode = None
            self.prev = None
            self.index = 0
            self.s = 25
            self.scale = 0
            self.startx = 10
            self.starty = 60
            self.rooms = 1
            self.ch = 0
            self.cir = []
            self.leaves = []
            self.mat = 0
            self.dim_mat = 0
            wd = 672
            ht = 345

            root = tk.Frame(win)

            tk.Label(win, text='Create a Dissected Floor Plan').grid(row=0)
            root.grid(row=1, column=0, sticky="n")
            self.root = root

            border_details = {'highlightbackground': 'black', 'highlightcolor': 'black', 'highlightthickness': 1}

            self.canvas = tk.Canvas(root, width=wd, height=ht, background='white', **border_details)
            self.canvas.grid(row=1, column=0, columnspan=5)

            self.canvas2 = tk.Canvas(root, width=340, height=ht, background='white', **border_details)
            self.canvas2.grid(row=1, column=5, columnspan=2)
            self.canvas2.create_text(120, 30, fill='black', font="Times 16 italic bold", text=' Dimensions of Rooms ')
            self.canvas2.create_line(0, 50, 340, 50)

            self.type = " Rectangular plot "
            self.popup = tk.Menu(root, tearoff=0)
            self.popup.add_command(label="Horizontal Slice", command=self.addH)
            self.popup.add_command(label="Vertical Slice", command=self.addV)
            self.popup.add_separator()
            self.popup.add_command(label="Make a Room", command=self.addLeaf)

            showButton = tk.Button(root, text=" Start a new dissection ", command=self.choice)
            showButton.grid(row=0, column=0)
            tk.Button(root, text=" Generate Spanning Circulation ", command=self.end).grid(row=2, column=0)

            tk.Button(root, text='Leave', command=self.forceExit).grid(row=0, column=1)
            tk.Button(root, text=' Change Entry Point ', command=self.changeentry).grid(row=2, column=1)
            tk.Label(root, text=" Dimensions of Total Plot ").grid(row=2, column=2)
            tk.Label(root, text=" Height  ").grid(row=2, column=3)
            tk.Label(root, text=" Width   ").grid(row=2, column=5)

            self.en1 = tk.Entry(root)
            self.en2 = tk.Entry(root)

            self.en1.grid(row=2, column=4)
            self.en2.grid(row=2, column=6)

            tk.Label(root, text=" Dimensions of Current block ").grid(row=0, column=2)
            tk.Label(root, text=" Height  ").grid(row=0, column=3)
            tk.Label(root, text=" Width   ").grid(row=0, column=5)

            self.ent1 = tk.Entry(root)
            self.ent2 = tk.Entry(root)

            self.master.e1 = tk.IntVar()
            self.master.e2 = tk.IntVar()
            self.master.e1.set(1)
            self.master.e2.set(2)

            self.ent1.grid(row=0, column=4)
            self.ent2.grid(row=0, column=6)
            self.done = True
            # if(self.done == 1):
            self.endvar = tk.IntVar()
            self.endvar.set(0)

            self.root.wait_variable(self.endvar)
            # while(self.done):
            # self.root.wait_variable(self.endvar)

        def forceExit(self):
            self.root.destroy()
            self.master.root.destroy()
            # self.master.root.quit()

        def changeentry(self):
            top = tk.Toplevel()

            tk.Label(top, text="Enter adjcent rooms to entry room" + self.type).grid(row=0, columnspan=2)
            tk.Label(top, text=" Left room  ").grid(row=1)
            tk.Label(top, text=" Right room   ").grid(row=2)

            entry1 = tk.Entry(top, textvariable=self.master.e1)
            entry2 = tk.Entry(top, textvariable=self.master.e2)

            entry1.grid(row=1, column=1)
            entry2.grid(row=2, column=1)
            # entry1.insert(0,1)
            # entry2.insert(0,2)

            but1 = tk.Button(top, text="   Submit   ", command=top.destroy)
            but1.grid(row=3, columnspan=2)

        def end(self):
            # self.done = 0
            if (self.rooms > 1):
                self.submit()
                self.root.quit()
                self.done = False
                self.master.value.append(1)
                self.endvar.set(self.endvar.get() + 1)
                self.master.end.set(self.master.end.get() + 1)
            else:
                tk.messagebox.showinfo("error", "Please make a dissection of two or more rooms")

        def start(self, canvas):
            global type
            global entry1
            global entry2
            global master
            global current
            current = self.current
            master = tk.Tk()
            tk.Label(master, text="Enter dimensions of " + self.type).grid(row=0, columnspan=2)
            tk.Label(master, text=" Height  ").grid(row=1)
            tk.Label(master, text=" Width   ").grid(row=2)

            entry1 = tk.Entry(master)
            entry2 = tk.Entry(master)

            entry1.grid(row=1, column=1)
            entry2.grid(row=2, column=1)
            entry1.insert(0, 10)
            entry2.insert(0, 10)
            but1 = tk.Button(master, text="   Save   ", command=lambda: self.saveDimsRect(canvas))
            but1.grid(row=3, columnspan=2)
            if current is not None and current.slice_type == "V" and current.height != 0:
                entry1.insert(0, current.height)
                entry1.configure(state='disabled')
                entry2.insert(0, current.width / 2)
            if current is not None and current.slice_type == "H" and current.width != 0:
                entry2.insert(0, current.width)
                entry1.insert(0, current.height / 2)
                entry2.configure(state='disabled')

            if current is not None and current.slice_type == 'L' and current.height != 0 and current.width != 0:
                entry2.insert(0, current.width)
                entry1.insert(0, current.height)

            master.mainloop()

        def error(self, h_val, w_val, rr):
            global master
            if rr == 0:
                master.destroy()
            if rr == 1:

                if w_val != 0:
                    box1 = tk.Tk()
                    if ch == 1:
                        tk.Label(box1, text="The width should be less than " + str(w_val)).grid(row=0)
                    if ch == 2:
                        tk.Label(box1, text="The width should be less than or equal to " + str(w_val)).grid(row=0)
                    but2 = tk.Button(box1, text="Okay", command=box1.destroy)
                    but2.grid(row=1)
                    box1.mainloop()

                if h_val != 0:
                    box2 = tk.Tk()
                    if ch == 1:
                        tk.Label(box2, text="The height should be less than " + str(h_val)).grid(row=0)
                    if ch == 2:
                        tk.Label(box2, text="The height should be less than or equal to " + str(h_val)).grid(row=0)
                    but2 = tk.Button(box2, text="Okay", command=box2.destroy)
                    but2.grid(row=1)
                    box2.mainloop()

        def disp(self, event, length, breadth):
            self.ent1.insert(0, length)
            self.ent2.insert(0, breadth)

        def remove(self, event, length, breadth):
            self.ent1.delete(0, "end")
            self.ent2.delete(0, "end")

        def saveDimsRect(self, canvas):
            global rootnode
            rootnode = self.rootnode
            global current
            current = self.current
            global v1
            global v2
            global temp1
            global temp2
            global fig1
            global fig2
            global master5
            global scale
            if rootnode is None:

                v1 = float(entry1.get())
                v2 = float(entry2.get())
                if v1 <= 30 and v2 <= 40:
                    scale = 20
                elif v1 <= 45 and v2 <= 50:
                    scale = 15
                elif v1 <= 65 and v2 <= 90:
                    scale = 10
                elif v1 <= 110 and v2 <= 160:
                    scale = 6
                elif v1 <= 220 and v2 <= 320:
                    scale = 3
                elif v1 <= 680 and v2 <= 980:
                    scale = 1
                elif v1 <= 1360 and v2 <= 1960:
                    scale = 0.5
                elif v1 <= 2720 and v2 <= 3920:
                    scale = 0.25
                else:
                    box3 = tk.Tk()
                    tk.Label(box3, text="Try with smaller dimensions! ").grid(row=0)
                    but2 = tk.Button(box3, text="Okay", command=box3.destroy)
                    but2.grid(row=1)
                    box3.mainloop()
                    quit()
                self.error(0, 0, 0)
                self.en1.insert(0, v1)
                self.en2.insert(0, v2)
                fig1 = canvas.create_rectangle(10, 10, (v2 * scale) + 10, (v1 * scale) + 10, fill="snow2")
                canvas.tag_bind(fig1, "<Enter>", lambda event, arg1=v1, arg2=v2: self.disp(event, arg1, arg2))
                canvas.tag_bind(fig1, "<Leave>", lambda event, arg1=v1, arg2=v2: self.remove(event, arg1, arg2))

                rootnode = treenode(None, None, None, v1, v2, None, 10, 10, (v2 * scale) + 10, (v1 * scale) + 10)
                current = rootnode
                self.current = current
                self.rootnode = rootnode
                canvas.tag_bind(fig1, "<Button-3>", self.do_popup)

            elif current.slice_type == 'H':
                rem = 0
                u_v1 = float(entry1.get())
                u_v2 = float(entry2.get())

                if u_v1 >= current.height and current.height != 0:
                    rem = 1
                self.error(current.height, 0, rem)

                temp1 = treenode(current, None, None, u_v1, u_v2, None, current.d1, current.d2, current.d3,
                                 current.d2 + (u_v1 * scale))
                current.left = temp1
                fig1 = canvas.create_rectangle(temp1.d1, temp1.d2, temp1.d3, temp1.d4, fill="snow2")
                canvas.tag_bind(fig1, "<Enter>", lambda event, arg1=u_v1, arg2=u_v2: self.disp(event, arg1, arg2))
                canvas.tag_bind(fig1, "<Leave>", lambda event, arg1=u_v1, arg2=u_v2: self.remove(event, arg1, arg2))

                l_v1 = current.height - u_v1
                l_v2 = u_v2
                temp2 = treenode(current, None, None, l_v1, l_v2, None, current.d1, current.d2 + (u_v1 * scale),
                                 current.d3, current.d4)
                current.right = temp2
                fig2 = canvas.create_rectangle(temp2.d1, temp2.d2, temp2.d3, temp2.d4, fill="snow2")
                canvas.tag_bind(fig2, "<Enter>", lambda event, arg1=l_v1, arg2=l_v2: self.disp(event, arg1, arg2))
                canvas.tag_bind(fig2, "<Leave>", lambda event, arg1=l_v1, arg2=l_v2: self.remove(event, arg1, arg2))
                current = self.current

                canvas.create_line(temp2.d1, temp2.d2, temp1.d3, temp1.d4)
                canvas.tag_bind(fig1, "<Button-1>", lambda event, arg1=temp1: self.shadeRectangle1(event, arg1))
                canvas.tag_bind(fig2, "<Button-1>", lambda event, arg2=temp2: self.shadeRectangle2(event, arg2))

            elif current.slice_type == 'V':
                rem = 0
                l_v1 = float(entry1.get())
                l_v2 = float(entry2.get())

                if l_v2 >= current.width and current.width != 0:
                    rem = 1
                self.error(0, current.width, rem)

                temp1 = treenode(current, None, None, l_v1, l_v2, None, current.d1, current.d2,
                                 (l_v2 * scale) + current.d1, current.d4)
                current.left = temp1
                fig1 = canvas.create_rectangle(temp1.d1, temp1.d2, temp1.d3, temp1.d4, fill="snow2")
                canvas.tag_bind(fig1, "<Enter>", lambda event, arg1=l_v1, arg2=l_v2: self.disp(event, arg1, arg2))
                canvas.tag_bind(fig1, "<Leave>", lambda event, arg1=l_v1, arg2=l_v2: self.remove(event, arg1, arg2))

                r_v1 = l_v1
                r_v2 = current.width - l_v2
                temp2 = treenode(current, None, None, r_v1, r_v2, None, current.d1 + (l_v2 * scale), current.d2,
                                 current.d3, current.d4)
                current.right = temp2
                fig2 = canvas.create_rectangle(temp2.d1, temp2.d2, temp2.d3, temp2.d4, fill="snow2")
                canvas.tag_bind(fig2, "<Enter>", lambda event, arg1=r_v1, arg2=r_v2: self.disp(event, arg1, arg2))
                canvas.tag_bind(fig2, "<Leave>", lambda event, arg1=r_v1, arg2=r_v2: self.remove(event, arg1, arg2))
                current = self.current

                canvas.create_line(temp2.d1, temp2.d2, temp1.d3, temp1.d4)
                canvas.tag_bind(fig1, "<Button-1>", lambda event, arg1=temp1: self.shadeRectangle1(event, arg1))
                canvas.tag_bind(fig2, "<Button-1>", lambda event, arg2=temp2: self.shadeRectangle2(event, arg2))

            elif current.slice_type == 'L':
                v1 = float(entry1.get())
                v2 = float(entry2.get())
                rem = 0
                hh = 0
                ww = 0
                if v1 > current.height and current.height != 0:
                    rem = 1
                    hh = current.height
                if v2 > current.width and current.width != 0:
                    rem = 1
                    ww = current.width
                self.error(hh, ww, rem)

                global var1
                global var2
                global var3
                global var4
                global rooms
                global starty
                starty = self.starty
                rooms = self.rooms
                startx = self.startx

                if v1 == 0 or v2 == 0:
                    canvas.create_rectangle(current.d1, current.d2, current.d3, current.d4, fill='white')

                elif v1 != current.height and v1 != 0 and current.height != 0:
                    self.getVerInfo("top", "bottom", "for the block")
                    if var1 == 0 and var2 == 1:
                        canvas.create_rectangle(current.d1, current.d2, current.d3,
                                                current.d4 - ((current.height * scale) - (v1 * scale)), fill='snow3')
                        canvas.create_rectangle(current.d1, current.d2 + (v1 * scale), current.d3, current.d4,
                                                fill='white')
                        current.d4 = current.d4 - ((current.height * scale) - (v1 * scale))
                        canvas.create_text((current.d1 + current.d3) / 2, (current.d2 + current.d4) / 2, fill='black',
                                           font="Times 14 bold", text='R' + str(rooms))


                    elif var1 == 1 and var2 == 0:
                        canvas.create_rectangle(current.d1, current.d2 + ((current.height * scale) - (v1 * scale)),
                                                current.d3, current.d4, fill='snow3')
                        canvas.create_rectangle(current.d1, current.d2, current.d3, current.d4 - (v1 * scale),
                                                fill='white')
                        current.d2 = current.d2 + ((current.height * scale) - (v1 * scale))
                        canvas.create_text((current.d1 + current.d3) / 2, (current.d2 + current.d4) / 2, fill='black',
                                           font="Times 14 bold", text='R' + str(rooms))


                elif v2 != current.width and v2 != 0 and current.width != 0:
                    self.getHorInfo('left', 'right', 'for the block')
                    if var3 == 0 and var4 == 1:
                        canvas.create_rectangle(current.d1, current.d2,
                                                current.d3 - ((current.width * scale) - (v2 * scale)), current.d4,
                                                fill='snow3')
                        canvas.create_rectangle(current.d1 + (v2 * scale), current.d2, current.d3, current.d4,
                                                fill='white')
                        current.d3 = current.d3 - ((current.width * scale) - (v2 * scale))
                        canvas.create_text((current.d1 + current.d3) / 2, (current.d2 + current.d4) / 2, fill='black',
                                           font="Times 14 bold", text='R' + str(rooms))


                    elif var3 == 1 and var4 == 0:
                        canvas.create_rectangle(current.d1 + ((current.width * scale) - (v2 * scale)), current.d2,
                                                current.d3, current.d4, fill='snow3')
                        canvas.create_rectangle(current.d1, current.d2, current.d3 - (v2 * scale), current.d4,
                                                fill='white')
                        current.d1 = current.d1 + ((current.width * scale) - (v2 * scale))
                        canvas.create_text((current.d1 + current.d3) / 2, (current.d2 + current.d4) / 2, fill='black',
                                           font="Times 14 bold", text='R' + str(rooms))


                elif v1 == current.height and v2 == current.width:
                    canvas.create_rectangle(current.d1, current.d2, current.d3, current.d4, fill='snow3')
                    canvas.create_text((current.d1 + current.d3) / 2, (current.d2 + current.d4) / 2, fill='black',
                                       font="Times 14 bold", text='R' + str(rooms))

                if v1 != 0 and v2 != 0:
                    txt = 'R' + str(rooms) + '  H = ' + str(v1) + '  W = ' + str(v2)
                    self.canvas2.create_text(startx + 160, starty + 15, fill="black", font="Times 14 italic bold",
                                             text=txt)
                    self.canvas2.create_line(0, starty + 30, 340, starty + 30)
                    starty = starty + 30
                    rooms = rooms + 1

                if current is current.parent.left:
                    if current.parent.right.slice_type != 'L':
                        current = current.parent.right
                elif current is current.parent.right:
                    if current.parent.left.slice_type != 'L':
                        current = current.parent.left
                if current.parent.right.slice_type == 'L' and current.parent.left.slice_type == 'L':
                    if current.parent is not rootnode and current.parent is current.parent.parent.left:
                        current = current.parent.parent.right
                    elif current.parent is not rootnode and current.parent is current.parent.parent.right:
                        current = current.parent.parent.left

                self.current = current
                self.rooms = rooms
                self.starty = starty
                self.startx = startx

        def shadeRectangle1(self, event, temp):
            global current
            current = self.current
            canvas = self.canvas
            shade1 = canvas.create_rectangle(temp.d1, temp.d2, temp.d3, temp.d4, fill='grey')
            canvas.tag_bind(shade1, "<Enter>",
                            lambda event, arg1=temp.height, arg2=temp.width: self.disp(event, arg1, arg2))
            canvas.tag_bind(shade1, "<Leave>",
                            lambda event, arg1=temp.height, arg2=temp.width: self.remove(event, arg1, arg2))
            current = temp
            self.current = current
            canvas.tag_bind(shade1, "<Button-3>", self.do_popup)

        def shadeRectangle2(self, event, temp):
            global current
            current = self.current
            canvas = self.canvas
            shade2 = canvas.create_rectangle(temp.d1, temp.d2, temp.d3, temp.d4, fill='grey')
            canvas.tag_bind(shade2, "<Enter>",
                            lambda event, arg1=temp.height, arg2=temp.width: self.disp(event, arg1, arg2))
            canvas.tag_bind(shade2, "<Leave>",
                            lambda event, arg1=temp.height, arg2=temp.width: self.remove(event, arg1, arg2))
            current = temp
            self.current = current
            canvas.tag_bind(shade2, "<Button-3>", self.do_popup)

        def do_popup(self, event):
            try:
                self.popup.tk_popup(event.x_root, event.y_root, 0)
            finally:
                self.popup.grab_release()

        def addH(self):
            global type
            self.type = " Upper Block of the Dissection "
            self.current.slice_type = 'H'
            self.start(self.canvas)

        def addV(self):
            global type
            self.type = " Left Block of the Dissection "
            current.slice_type = 'V'
            self.start(self.canvas)

        def addLeaf(self):
            global current
            global starty
            global rooms
            global type
            # global master4
            current = self.current
            canvas = self.canvas
            rooms = self.rooms
            startx = self.startx
            starty = self.starty
            canvas2 = self.canvas2
            leaves = self.leaves
            current.slice_type = 'L'
            if ch == 1:
                canvas.create_rectangle(current.d1, current.d2, current.d3, current.d4, fill='snow3')
                canvas.create_text((current.d1 + current.d3) / 2, (current.d2 + current.d4) / 2, fill='black',
                                   font="Times 14 bold", text='R' + str(rooms))

                txt = 'R' + str(rooms) + '  H = ' + str(current.height) + '  W = ' + str(current.width)
                canvas2.create_text(startx + 160, starty + 15, fill="black", font="Times 14 italic bold", text=txt)
                canvas2.create_line(0, starty + 30, 340, starty + 30)
                starty = starty + 30
                rooms = rooms + 1
                leaves.append(current)

                if current is current.parent.left:
                    if current.parent.right.slice_type != 'L':
                        current = current.parent.right
                elif current is current.parent.right:
                    if current.parent.left.slice_type != 'L':
                        current = current.parent.left
                if current.parent.right.slice_type == 'L' and current.parent.left.slice_type == 'L':
                    if current.parent is not rootnode and current.parent is current.parent.parent.left:
                        current = current.parent.parent.right
                    elif current.parent is not rootnode and current.parent is current.parent.parent.right:
                        current = current.parent.parent.left
                self.rooms = rooms
                self.current = current
                self.startx = startx
                self.starty = starty
                self.leaves = leaves

            elif ch == 2:
                type = " room "
                self.start(canvas)
            return

        def getVerInfo(self, a, b, c):
            global var1
            global var2
            global master5
            master5 = tk.Tk()
            tk.Label(master5, text=" Specify the location of Vacant Space " + c).grid(row=0, columnspan=2)
            butt1 = tk.Button(master5, text=" At the " + a,
                              command=lambda: [master5.destroy(), self.setVal1(), master5.quit()])
            butt1.grid(row=1, columnspan=2)
            butt2 = tk.Button(master5, text=" At the " + b,
                              command=lambda: [master5.destroy(), self.setVal2(), master5.quit()])
            butt2.grid(row=2, columnspan=2)
            master5.mainloop()
            return

        def getHorInfo(self, a, b, c):
            global var3
            global var4
            global master6
            master6 = tk.Tk()
            tk.Label(master6, text=" Specify the location of Vacant Space " + c).grid(row=0, columnspan=2)
            butt1 = tk.Button(master6, text=" At the " + a,
                              command=lambda: [master6.destroy(), self.setVal3, master6.quit()])
            butt1.grid(row=1, columnspan=2)
            butt2 = tk.Button(master6, text=" At the " + b,
                              command=lambda: [master6.destroy(), self.setVal4, master6.quit()])
            butt2.grid(row=2, columnspan=2)
            master6.mainloop()
            return

        def setVal1(self):
            global var1
            global var2
            var1 = 1
            var2 = 0

        def setVal2(self):
            global var1
            global var2
            var1 = 0
            var2 = 1

        def setVal3(self):
            global var3
            global var4
            var3 = 1
            var4 = 0

        def setVal4(self):
            global var3
            global var4
            var3 = 0
            var4 = 1

        def submit(self):
            # master2 = tk.Tk()\
            ch = 1
            if ch == 1:
                leaves = self.leaves
                rooms = self.rooms
                # Adjacency matrix Generation
                mat = np.zeros(([rooms - 1, rooms - 1]), dtype=int)
                dim_mat = np.zeros(([rooms - 1, rooms - 1]), dtype=float)
                for j in range(0, len(leaves)):
                    leaf1 = leaves[j]

                    for i in range(0, len(leaves)):
                        leaf2 = leaves[i]
                        if not i == j:
                            if (leaf1.d1 == leaf2.d1 and leaf1.d4 == leaf2.d2):
                                mat[i, j] = 1
                                mat[j, i] = 1
                                if leaf1.width <= leaf2.width:
                                    dim_mat[i, j] = leaf1.width
                                    dim_mat[j, i] = leaf1.width
                                else:
                                    dim_mat[i, j] = leaf2.width
                                    dim_mat[j, i] = leaf2.width
                            if (leaf1.d3 == leaf2.d1 and leaf1.d4 == leaf2.d4):
                                mat[i, j] = 1
                                mat[j, i] = 1
                                if leaf1.height <= leaf2.height:
                                    dim_mat[i, j] = leaf1.height
                                    dim_mat[j, i] = leaf1.height
                                else:
                                    dim_mat[i, j] = leaf2.height
                                    dim_mat[j, i] = leaf2.height
                            if (leaf1.d3 == leaf2.d1 and leaf1.d2 == leaf2.d2):
                                mat[i, j] = 1
                                mat[j, i] = 1
                                if leaf1.height <= leaf2.height:
                                    dim_mat[i, j] = leaf1.height
                                    dim_mat[j, i] = leaf1.height
                                else:
                                    dim_mat[i, j] = leaf2.height
                                    dim_mat[j, i] = leaf2.height
                            if (leaf1.d3 == leaf2.d3 and leaf1.d4 == leaf2.d2):
                                mat[i, j] = 1
                                mat[j, i] = 1
                                if leaf1.width <= leaf2.width:
                                    dim_mat[i, j] = leaf1.width
                                    dim_mat[j, i] = leaf1.width
                                else:
                                    dim_mat[i, j] = leaf2.width
                                    dim_mat[j, i] = leaf2.width
                            if ((
                                    leaf1.d1 < leaf2.d1 and leaf1.d3 > leaf2.d1 and leaf1.d3 < leaf2.d3) and leaf1.d4 == leaf2.d2):
                                mat[i, j] = 1
                                mat[j, i] = 1
                                dim_mat[i, j] = (leaf1.d3 - leaf2.d1) / scale
                                dim_mat[j, i] = (leaf1.d3 - leaf2.d1) / scale
                            if ((
                                    leaf2.d1 < leaf1.d1 and leaf2.d3 > leaf1.d1 and leaf2.d3 < leaf1.d3) and leaf1.d4 == leaf2.d2):
                                mat[i, j] = 1
                                mat[j, i] = 1
                                dim_mat[i, j] = (leaf2.d3 - leaf1.d1) / scale
                                dim_mat[j, i] = (leaf2.d3 - leaf1.d1) / scale
                            if ((
                                    leaf1.d2 < leaf2.d2 and leaf1.d4 < leaf2.d4 and leaf2.d2 < leaf1.d4) and leaf1.d3 == leaf2.d1):
                                mat[i, j] = 1
                                mat[j, i] = 1
                                dim_mat[i, j] = (leaf1.d4 - leaf2.d2) / scale
                                dim_mat[j, i] = (leaf1.d4 - leaf2.d2) / scale
                            if ((
                                    leaf2.d2 < leaf1.d2 and leaf2.d4 < leaf1.d4 and leaf1.d2 < leaf2.d4) and leaf1.d3 == leaf2.d1):
                                mat[i, j] = 1
                                mat[j, i] = 1
                                dim_mat[i, j] = (leaf2.d4 - leaf1.d2) / scale
                                dim_mat[j, i] = (leaf2.d4 - leaf1.d2) / scale
                            if ((leaf1.d2 < leaf2.d2 and leaf1.d4 > leaf2.d4) and leaf1.d3 == leaf2.d1):
                                mat[i, j] = 1
                                mat[j, i] = 1
                                dim_mat[i, j] = leaf2.height
                                dim_mat[j, i] = leaf2.height
                            if ((leaf1.d1 > leaf2.d1 and leaf2.d3 > leaf1.d3) and leaf1.d4 == leaf2.d2):
                                mat[i, j] = 1
                                mat[j, i] = 1
                                dim_mat[i, j] = leaf1.width
                                dim_mat[j, i] = leaf1.width
                            # if ((leaf2.d1 > leaf1.d1 and leaf1.d3 > leaf2.d3) and leaf2.d2 == leaf1.d4):
                            #     mat[i,j] = 1
                            #     mat[j,i] = 1
                            #     dim_mat[i,j] = leaf2.width
                            #     dim_mat[j,i] = leaf2.width
                            if dim_mat[i, j] == 0:
                                dim_mat[i, j] = -1
                                dim_mat[j, i] = -1

                self.mat = mat
                self.dim_mat = dim_mat
                # self.done= TRUE
                # root.quit()
                return mat, dim_mat

        def choice(self):
            master3 = tk.Tk()
            tk.Label(master3, text=" Select the type of Floor Plan to be generated ").grid(row=0, columnspan=2)
            but3 = tk.Button(master3, text=" RFP without empty spaces ",
                             command=lambda: [master3.destroy(), self.decideRect()])
            but3.grid(row=1, columnspan=2)
            but4 = tk.Button(master3, text=" RFP with empty spaces ",
                             command=lambda: [master3.destroy(), self.decideNonRect()])
            but4.grid(row=2, columnspan=2)
            master3.mainloop()

        def decideRect(self):
            global ch
            ch = 1
            self.start(self.canvas)

        def decideNonRect(self):
            global ch
            ch = 2
            self.start(self.canvas)

        def add_cir(self):
            mat = self.master.cir_dim_mat
            tab = self.master.ocan.tabs[self.master.ocan.tabno]

            canvas = self.master.ocan.canvas
            # canvas = tk.Canvas(tab,width=970, height=350, bg ="white")
            # canvas.grid(row=1, column = 0)

            e1 = self.master.e1.get()
            e2 = self.master.e2.get()

            i = 0
            leaves = self.leaves
            for room in leaves:
                i += 1
                canvas.create_rectangle(room.d1, room.d2, room.d3, room.d4, fill=hex_colors[i])

            num_corridors = len(mat) - len(leaves)
            # for cor in range( 0, num_corridors):
            n = len(leaves)

            self.make_corridor(e1 - 1, e2 - 1, canvas, 0)
            # self.make_corridor(2,3,canvas)
            mat = np.squeeze(np.asarray(mat))

            for cor in range(n + 1, len(mat)):
                for itr in range(n, cor):
                    if (mat[cor][itr] == 1):
                        rms = self.intersect(mat[cor], mat[itr], n)
                        self.make_corridor(rms[0], rms[1], canvas, 1)
                        break

        def make_corridor(self, e1, e2, canvas, num):

            leaves = self.leaves
            room1 = leaves[e1]
            room2 = leaves[e2]
            pts = self.common_points(room1, room2, num)
            if len(pts) != 4:
                pts = self.common_points(room2, room1, num)
            canvas.create_rectangle(pts[0], pts[1], pts[2], pts[3], fill="white", outline="white")

        def intersect(self, row1, row2, n):
            pt = []
            for i in range(0, n):
                if (row1[i] == 1 and row2[i] == 1):
                    pt.append(i)

            return pt

        def common_points(self, leaf1, leaf2, num):
            pt = []
            if (leaf1.d1 == leaf2.d1 and leaf1.d4 == leaf2.d2):
                if num == 0:
                    pt.append(leaf2.d1)
                    pt.append(leaf2.d2 - 5)
                elif num == 1:
                    pt.append(leaf2.d1 - 5)
                    pt.append(leaf2.d2 - 5)
                if leaf1.width <= leaf2.width:
                    pt.append(leaf1.d3 + 5)
                    pt.append(leaf1.d4 + 5)
                else:
                    pt.append(leaf2.d3 + 5)
                    pt.append(leaf2.d2 + 5)

            elif (leaf1.d3 == leaf2.d1 and leaf1.d4 == leaf2.d4):
                if num == 0:
                    pt.append(leaf1.d3 - 5)
                    pt.append(leaf1.d4)
                elif num == 1:
                    pt.append(leaf1.d3 - 5)
                    pt.append(leaf1.d4 + 5)
                if leaf1.height <= leaf2.height:
                    pt.append(leaf1.d3 + 5)
                    pt.append(leaf1.d2 - 5)
                else:
                    pt.append(leaf1.d3 + 5)
                    pt.append(leaf2.d2 - 5)

            elif (leaf1.d3 == leaf2.d1 and leaf1.d2 == leaf2.d2):
                if num == 0:
                    pt.append(leaf2.d1 - 5)
                    pt.append(leaf2.d2)
                elif num == 1:
                    pt.append(leaf2.d1 - 5)
                    pt.append(leaf2.d2 + 5)
                if leaf1.height <= leaf2.height:
                    pt.append(leaf1.d3 + 5)
                    pt.append(leaf1.d4 - 5)
                else:
                    pt.append(leaf1.d3 + 5)
                    pt.append(leaf2.d4 - 5)

            elif (leaf1.d3 == leaf2.d3 and leaf1.d4 == leaf2.d2):
                if num == 0:
                    pt.append(leaf1.d3)
                    pt.append(leaf1.d4 - 5)
                elif num == 1:
                    pt.append(leaf1.d3 + 5)
                    pt.append(leaf1.d4 - 5)
                if leaf1.width <= leaf2.width:
                    pt.append(leaf1.d1 + 5)
                    pt.append(leaf1.d4 + 5)
                else:
                    pt.append(leaf2.d1 + 5)
                    pt.append(leaf2.d2 + 5)

            elif ((leaf1.d1 < leaf2.d1 and leaf1.d3 > leaf2.d1 and leaf1.d3 < leaf2.d3) and leaf1.d4 == leaf2.d2):
                pt.append(leaf2.d1 - 5)
                pt.append(leaf1.d4 - 5)
                pt.append(leaf1.d3)
                pt.append(leaf1.d4 + 5)
            elif ((leaf2.d1 < leaf1.d1 and leaf2.d3 > leaf1.d1 and leaf2.d3 < leaf1.d3) and leaf1.d4 == leaf2.d2):
                pt.append(leaf1.d1 - 5)
                pt.append(leaf1.d4 - 5)
                pt.append(leaf2.d3)
                pt.append(leaf1.d4 + 5)
            elif ((leaf1.d2 < leaf2.d2 and leaf1.d4 < leaf2.d4 and leaf2.d2 < leaf1.d4) and leaf1.d3 == leaf2.d1):
                pt.append(leaf2.d1 - 5)
                pt.append(leaf2.d2 - 5)
                pt.append(leaf2.d1 + 5)
                pt.append(leaf1.d4)
            elif ((leaf2.d2 < leaf1.d2 and leaf2.d4 < leaf1.d4 and leaf1.d2 < leaf2.d4) and leaf1.d3 == leaf2.d1):
                pt.append(leaf2.d1 - 5)
                pt.append(leaf1.d2 - 5)
                pt.append(leaf2.d1 + 5)
                pt.append(leaf2.d4)
            elif ((leaf1.d2 < leaf2.d2 and leaf1.d4 > leaf2.d4) and leaf1.d3 == leaf2.d1):
                pt.append(leaf2.d1 - 5)
                pt.append(leaf2.d2 - 5)
                pt.append(leaf2.d1 + 5)
                pt.append(leaf2.d4)
            elif ((leaf1.d1 > leaf2.d1 and leaf2.d3 > leaf1.d3) and leaf1.d4 == leaf2.d2):
                pt.append(leaf1.d1 - 5)
                pt.append(leaf1.d4 - 5)
                pt.append(leaf1.d3)
                pt.append(leaf1.d4 + 5)
            return pt

    class Buttons:
        def __init__(self, root, master):
            button_details = {'wraplength': '150', 'bg': col[1], 'fg': 'white', 'font': ('lato', '14'), 'padx': 5,
                              'pady': 5, 'activebackground': col[2]}
            b1 = tk.Button(master.frame1, width=10, text='Irregular Floor Plan', relief='flat', **button_details,
                           command=master.single_floorplan)
            b1.grid(row=1, column=0, padx=5, pady=5)

            b2 = tk.Button(master.frame1, width=10, text='Multiple Irregular Floor Plans', relief='flat',
                           **button_details, command=master.multiple_floorplan)
            b2.grid(row=2, column=0, padx=5, pady=5)

            c1 = tk.Checkbutton(master.frame1, text="Dimensioned", relief='flat', **button_details,
                                selectcolor='#4A4E69', width=7, variable=master.checkvar1, onvalue=1, offvalue=0)
            c1.grid(row=4, column=1, padx=5, pady=5)

            b3 = tk.Button(master.frame1, width=10, text='Rectangular Floor Plan', relief='flat', **button_details,
                           command=master.single_oc_floorplan)
            b3.grid(row=3, column=0, padx=5, pady=5)

            b4 = tk.Button(master.frame1, width=10, text='Multiple Rectangular Floor Plans', relief='flat',
                           **button_details, command=master.multiple_oc_floorplan)
            b4.grid(row=4, column=0, padx=5, pady=5)

            b6 = tk.Button(master.frame1, width=10, text='Circulation', relief='flat', **button_details,
                           command=master.circ_menu)
            b6.grid(row=6, column=0, padx=5, pady=5)

            # c1 = tk.Checkbutton(master.frame1, text = "Dimensioned Circulation",relief='flat',**button_details,selectcolor='#4A4E69',width=13 ,variable = master.checkvar2,onvalue = 1, offvalue = 0)
            # c1.grid(row=7,column=0,padx=5,pady=5)

            # c2 = tk.Checkbutton(master.frame1, text = "Remove Circulation",relief='flat',**button_details,selectcolor='#4A4E69',width=13 ,variable = master.checkvar3,onvalue = 1, offvalue = 0)
            # c2.grid(row=8,column=0,padx=5,pady=5)

            b7 = tk.Button(master.frame1, width=10, text='Polygonal Floorplans', relief='flat', **button_details,
                           command=master.polygonal_inputbox)
            b7.grid(row=1, column=1, padx=5, pady=5)

            b8 = tk.Button(master.frame1, width=10, text='Letter Shaped Floor Plan', relief='flat', **button_details,
                           command=master.letter_inputbox)
            b8.grid(row=2, column=1, padx=5, pady=5)

            # b9 = tk.Button(master.frame1, width=10, text='Z Shaped Floor Plan', relief='flat', **button_details,
            #                command=master.z_shaped)
            # b9.grid(row=9, column=0, padx=5, pady=5)

            # b10 = tk.Button(master.frame1, width=10, text='T Shaped Floor Plan', relief='flat', **button_details,
            #                 command=master.t_shaped)
            # b10.grid(row=10, column=0, padx=5, pady=5)

            b11 = tk.Button(master.frame1, width=10, text='Staircase Shaped Floor Plan', relief='flat',
                            **button_details, command=master.staircase_shaped)
            b11.grid(row=3, column=1, padx=5, pady=5)

            # b12 = tk.Button(master.frame1, width=10, text='L Shaped Floor Plan', relief='flat',
            #                 **button_details, command=master.l_shaped)
            # b12.grid(row=12, column=0, padx=5, pady=5)
            # b3 = tk.Button(master.frame1,width=10, text='Circulation',relief='flat',**button_details,command=master.change_entry_gui)
            # b3.grid(row=4,column=0,padx=5,pady=5)

            # b32 = tk.Button(master.frame1,width=10, text='Change entry',relief='flat',**button_details,command=master.change_entry_gui)
            # b32.grid(row=5,column=0,padx=5,pady=5)

            # b4 = tk.Button(master.frame1,width=10, text='RFPchecker' ,relief='flat',**button_details,command=master.checker)
            # b4.grid(row=6,column=0,padx=5,pady=5)

            # b7 = tk.Button(master.frame1,width=10, text='Dissection' ,relief='flat',**button_details,command=master.dissection)
            # b7.grid(row=7,column=0,padx=5,pady=5)

            # b6 = tk.Button(master.frame1,width=10, text='Restart',relief='flat', **button_details,command=master.restart)
            # b6.grid(row=6,column=0,padx=5,pady=5)
            # c1 = tk.Checkbutton(master.frame1, text = "Dimensioned Circulation",relief='flat',**button_details,selectcolor='#4A4E69',width=7 ,variable = master.checkvar2,onvalue = 1, offvalue = 0)
            # c1.grid(row=4,column=1,padx=5,pady=5)

            # c2 = tk.Checkbutton(master.frame1, text = "Remove Circulation",relief='flat',**button_details,selectcolor='#4A4E69',width=7 ,variable = master.checkvar3,onvalue = 1, offvalue = 0)
            # c2.grid(row=5,column=1,padx=5,pady=5)

            b12 = tk.Button(master.frame1, width=10, text='Door Connectivity', relief='flat',
                            **button_details, command=master.door_connectivity)
            b12.grid(row=7, column=0, padx=5, pady=5)

            b13 = tk.Button(master.frame1, width=10, text='Multiple L-shaped floorplans', relief='flat',
                            **button_details, command=master.multiple_l_floorplan)
            b13.grid(row=7, column=1, padx=5, pady=5)

            b5 = tk.Button(master.frame1,width=10, text='EXIT',relief='flat', **button_details,command=master.exit)
            b5.grid(row=6,column=1,padx=5,pady=5)
            
            b14 = tk.Checkbutton(master.frame1, text="Min Dim", relief='flat', **button_details,
                                selectcolor='#4A4E69', width=7, variable=master.checkvar4, onvalue=1, offvalue=0)
            b14.grid(row=8, column=0, padx=5, pady=5)

    class menu:
        def __init__(self, master):
            root = master.root
            menubar = tk.Menu(root, bg=col[3])
            menubar.config(background=col[3])
            filemenu = tk.Menu(menubar, bg=col[3], tearoff=2)
            filemenu.add_command(label="New", command=master.restart)
            filemenu.add_command(label="Open", command=master.open_file)
            filemenu.add_command(label="Save", command=master.save_file)
            filemenu.add_command(label="Save as JSON", command=master.save_JSON)
            filemenu.add_command(label="Download Catalogue", command=master.download_catalogue)
            filemenu.add_command(label="Close", command=master.exit)

            filemenu.add_separator()

            filemenu.add_command(label="Exit", command=master.exit)
            menubar.add_cascade(label="File", menu=filemenu)
            editmenu = tk.Menu(menubar, bg=col[3], tearoff=0)
            editmenu.add_command(label="Undo")

            editmenu.add_separator()

            editmenu.add_command(label="Cut")
            editmenu.add_command(label="Copy")
            editmenu.add_command(label="Paste")
            editmenu.add_command(label="Delete")
            editmenu.add_command(label="Select All")

            menubar.add_cascade(label="Edit", menu=editmenu)
            helpmenu = tk.Menu(menubar, bg=col[3], tearoff=0)
            helpmenu.add_command(label="About...")
            menubar.add_cascade(label="Help", menu=helpmenu)

            root.config(menu=menubar)

    class output_canvas:
        def __init__(self, root):
            self.root = root
            self.root_window = tk.PanedWindow(root)
            self.l1 = tk.Label(self.root_window, text='Rectangular Dual')
            self.root_window.grid(row=2, column=0, pady=5)
            self.tabs = []
            self.tabno = -1
            self.tabControl = ttk.Notebook(self.root_window)
            # self.tabs = ttk.Frame(self.tabControl)

            # self.tabControl.add(self.tabs, text='Tab 1')
            self.tabControl.pack(expand=1, fill="both")
            # tk.Label(tabs, text="Welcome to GeeksForGeeks").grid(column=0, row=0, padx=30, pady=30)
            # tk.Label(self.tab2, text="Lets dive into the world of computers").grid(column=0, row=0, padx=30, pady=30)
            self.add_tab()

        def add_tab(self):
            self.tabno += 1
            self.tabs.append(ttk.Frame(self.tabControl))
            self.tabControl.add(self.tabs[self.tabno], text='Tab ' + str(self.tabno + 1))
            self.tabControl.select(self.tabno)
            self.canvas = turtle.ScrolledCanvas(self.tabs[self.tabno], width=970, height=350)
            self.canvas.bind("<Double-Button-1>", self.zoom)
            self.canvas.grid(column=0, row=1, padx=2, pady=2)
            self.tscreen = turtle.TurtleScreen(self.canvas)
            self.tscreen.screensize(50000, 1000)
            self.tscreen.bgcolor(col[3])
            self.pen = turtle.RawTurtle(self.tscreen)
            self.pen.speed(0)

            self.canvas.bind("<MouseWheel>", self.do_zoom)
            self.canvas.bind('<Button-1>', lambda event: self.canvas.scan_mark(event.x, event.y))
            self.canvas.bind("<B1-Motion>", lambda event: self.canvas.scan_dragto(event.x, event.y, gain=1))
            # imname = "./assets/close1.png"
            # im1 = Image.open(imname).convert("1")
            # size = (im1.width // 24, im1.height // 24)
            # im1.resize(size)
            # # # im1.show()
            # # im1 = ImageTk.BitmapImage(im1.resize(size)) 
            # im2 = ImageTk.PhotoImage(Image.open(imname).resize(size))

            # ImageTk.PhotoImage(file="./assets/close1.png")
            # # flat, groove, raised, ridge, solid, or sunke
            # # self.canvas.create_image(20,20,anchor='ne',image=butimg)
            # self.closeb = tk.Button(self.tabs[self.tabno],relief='solid',bg=col[3],activebackground=col[2],image=im2,command=self.close)
            # self.closeb.image=im2
            # self.closeb.grid(row=1,column=0,sticky='ne',pady=20,padx=70)

        def add_cir_tab(self):
            self.tabno += 1
            self.tabs.append(ttk.Frame(self.tabControl))
            self.tabControl.add(self.tabs[self.tabno], text='Tab ' + str(self.tabno + 1))
            self.tabControl.select(self.tabno)
            self.canvas = turtle.ScrolledCanvas(self.tabs[self.tabno], width=970, height=350)
            self.canvas.bind("<Double-Button-1>", self.zoom)
            self.canvas.grid(column=0, row=1)
            self.canvas.bind("<MouseWheel>", self.do_zoom)
            self.canvas.bind('<Button-1>', lambda event: self.canvas.scan_mark(event.x, event.y))
            self.canvas.bind("<B1-Motion>", lambda event: self.canvas.scan_dragto(event.x, event.y, gain=1))
            '''imname = "./close1.png"
            im1 = Image.open(imname).convert("1")
            size = (im1.width // 4, im1.height // 4)
            im2 = ImageTk.PhotoImage(Image.open(imname).resize(size))
            
            ImageTk.PhotoImage(file="./close1.png")
            self.closeb = tk.Button(self.tabs[self.tabno],relief='solid',bg=col[3],activebackground=col[2],image=im2,command=self.close)
            self.closeb.image=im2
            self.closeb.grid(row=1,column=0,sticky='ne',pady=20,padx=70)'''

        def do_zoom(self, event):
            factor = 1.001 ** event.delta
            self.canvas.scale(ALL, event.x, event.y, factor, factor)

        def getpen(self):
            return self.pen

        def getroot(self):
            return self.root_window

        def zoom(self, event):
            self.canvas.config(width=self.root.winfo_screenwidth(), height=self.root.winfo_screenheight())

        def close(self):
            self.tabno -= 1
            self.tabs.pop()
            self.tabControl.forget(self.tabControl.select())

    class output_text:
        def __init__(self, root):
            self.root = root
            self.textbox = tk.Text(root, bg=col[3], fg='black', relief='flat', height=25, width=30, padx=5, pady=5,
                                   **font)
            self.textbox.grid(row=0, column=0, padx=10, pady=10)
            self.textbox.insert('insert', "\t         Output\n")

        def gettext(self):
            return self.textbox

        def clear(self):
            self.textbox.destroy()
            self.textbox = tk.Text(self.root, bg=col[3], fg='black', relief='flat', height=32, width=30, padx=5, pady=5,
                                   **font)
            self.textbox.grid(row=0, column=0, padx=10, pady=10)
            self.textbox.insert('insert', "\t         Output\n")

    def graph_ret(self):
        # value is set here, dimensioned and mindim flags are set for graphs from input file
        if self.open == True and len(self.value) > 0:
            isDimensioned, isMindim = self.value[4], self.value[10]
            self.value = self.app.return_everything()
            self.value[4], self.value[10] = isDimensioned, isMindim
        else:
            self.value = self.app.return_everything()
        self.textbox = self.tbox.gettext()

    def single_floorplan(self):
        self.app.command = "single"
        self.command = "single"
        self.end.set(self.end.get() + 1)
        # self.root.state('zoomed')
        # root.destroy()

    def door_connectivity(self):
        self.app.command = "door_connectivity"
        self.command = "door_connectivity"
        self.end.set(self.end.get() + 1)
        # self.root.state('zoomed')
        # root.destroy()

    def multiple_floorplan(self):
        self.app.command = "multiple"
        self.command = "multiple"
        self.end.set(self.end.get() + 1)
        # root.destroy()

    def single_oc_floorplan(self):
        self.app.command = "single_oc"
        self.command = "single_oc"
        self.end.set(self.end.get() + 1)
        # self.root.state('zoomed')
        # root.destroy()

    def multiple_oc_floorplan(self):
        self.app.command = "multiple_oc"
        self.command = "multiple_oc"
        self.end.set(self.end.get() + 1)
        # self.root.state('zoomed')
        # root.destroy()

    def multiple_l_floorplan(self):
        self.app.command = "multiple_l"
        self.command = "multiple_l"
        self.end.set(self.end.get() + 1)
        # root.destroy()

    def circulation(self):
        self.app.command = "circulation"
        self.command = "circulation"
        self.end.set(self.end.get() + 1)

    def polygonal(self):
        self.v1 = self.v11.get()
        self.v2 = self.v22.get()
        self.vn = self.vnn.get()
        self.outer_boundary = self.outer_boundary2
        self.shape = self.shapes.get()
        self.po = self.priority_order.get()
        self.top.destroy()
        self.app.command = "poly"
        self.command = "poly"
        self.end.set(self.end.get() + 1)

    def checker(self):
        self.app.command = "checker"
        self.command = "checker"
        self.end.set(self.end.get() + 1)

    def dissection(self):
        # graphplotter.destroy()
        # self.disframe = tk.Frame(self.root)
        # self.disframe.grid(row=0,column=1)
        if self.dissecting:
            self.app.root.destroy()

            self.dclass = self.dissected(self, self.frame2)
            self.app.command = "dissection"
            self.command = "dissection"
            self.end.set(self.end.get() + 1)
            global done
            done = False
            self.dissecting = 0
        else:
            self.app.table.destroy()
            self.app = self.PlotApp(self.frame2, self)
            self.dclass.root.destroy()
            self.dissecting = 1

    def staircase_shaped(self):
        self.app.command = "staircase_shaped"
        self.command = "staircase_shaped"
        self.end.set(self.end.get() + 1)

    def restart(self):
        os.execl(sys.executable, os.path.abspath(__file__), *sys.argv)

    def exit(self):
        global done

        self.app.command = "end"
        self.command = "end"
        self.end.set(self.end.get() + 10)
        done = False
        current_time = datetime.datetime.now().strftime("%m_%d_%Y_%H_%M_%S")
        if not os.path.exists('saved_files'):
            os.makedirs('saved_files')
        self.save_file(".\saved_files\RFP_" + str(current_time) + ".txt")

        try:
            self.dclass.root.destory()
        except:
            pass
        # self.saver = tk.Toplevel()
        # saverlabel = tk.Label(self.saver,text="hwakeoa")
        # saverlabel.pack()

        # b1 = tk.Button(self.saver,text="No",command=sys.exit(0))
        # b1.pack()
        # self.saver.wait_window(self.saver)

        self.root.quit()

        # return self.value , self.root , self.textbox , self.pen ,self.end

    def open_file(self, filename=None):
        self.app.reset()
        if filename == None:

            self.file = filedialog.askopenfile(mode='r', defaultextension=".txt", title="Select file",
                                               filetypes=(("text files", "*.txt"), ("all files", "*.*")))
        else:
            self.file = open(filename, 'r')
        f = self.file.read()
        fname = self.file.name
        fname = fname[:-3]
        fname += "png"
        self.open_ret = ast.literal_eval(f)
        self.value = self.open_ret[0]
        node_data = self.open_ret[1]
        edge_data = self.open_ret[2]
        con_data = self.open_ret[3]
        self.dimensional_constraints = self.open_ret[4]
        self.app.retreive_graph(node_data, edge_data, con_data)
        self.open = True

    def save_JSON(self):
        if not self.output_found:
            tk.messagebox.showinfo("error", "Output not yet found")

        else:
            # self.end.set(self.end.get()+1)
            self.json_data = self.ptpg.return_data()
            f = filedialog.asksaveasfile(defaultextension=".JSON", title="Select location to Save file as JSON",
                                         filetypes=(("JSON files", "*.JSON"), ("all files", "*.*")),
                                         initialfile="_latest_JSON.JSON")
            f.write(json.dumps(self.json_data))
            fauto = open(".\saved_files\RFP_latest.txt", "w")
            jstr = json.dumps(self.json_data, indent=4)
            fauto.write(jstr)
            fauto.close()
            f.close()

    def download_catalogue(self):
        if not self.multiple_output_found:
            tk.messagebox.showinfo("error", "Output not yet found")
        else:
            edge_list=self.app.edges.copy()
            edge_list=[[x for x in elem[:-1]] for elem in edge_list]
            # If Dimensioned floorplans have been generated
            if self.value[4] == 1:
                generate_catalogue_dimensioned(self.num_rfp, self.output_data, self.dimensional_constraints, edges = edge_list, 
                                               time_taken = self.time_taken, fpcnt = self.ptpg.fpcnt, room_name = self.value[5])
            # If Minimum Dimension floorplans have been generated
            elif self.value[10] == 1:
                generate_mindim_catalogue(self.num_rfp, self.output_data, self.dimensional_constraints, edges = edge_list, 
                                          time_taken = self.time_taken, fpcnt = self.ptpg.fpcnt, room_name = self.value[5])
            else:
                generate_catalogue(edge_list, self.num_rfp, self.time_taken, self.output_data,
                                   self.dimensional_constraints)

    def polygonal_inputbox(self):
        """This function takes user input for starting edge/door for the corridor
        """
        self.canonicalObject = cano.canonical()
        self.canonicalObject.displayInputGraph(len(self.app.nodes_data), self.app.edges, self.app.nodes_data)

        self.top = tk.Toplevel(self.root, width=300, height=300)
        root = self.top
        root.title('Outermost Nodes for Canonical Order')
        main_text = tk.Label(root, text="Enter priority order(if any) v1 , v2, vn.")
        main_text.grid(row=0, column=0)
        v1_val = tk.Entry(root, textvariable=self.v11)
        v1_val.grid(row=1, column=1)
        v2_val = tk.Entry(root, textvariable=self.v22)
        v2_val.grid(row=1, column=2)
        vn_val = tk.Entry(root, textvariable=self.vnn)
        vn_val.grid(row=1, column=3)
        priority_order = tk.Entry(root, textvariable=self.priority_order)
        priority_order.grid(row=1, column=0)
        self.choice = tk.IntVar()
        self.choice.set(1)
        sub_text = tk.Label(root,
                            text="""Choose the outer structure of Floorplan:""",
                            justify=tk.LEFT,
                            padx=20)
        sub_text.grid(row=3)

        btn1 = tk.Radiobutton(root,
                              text="Pentagon",
                              padx=20,
                              variable=self.choice,
                              value=1)
        btn1.grid(row=4, column=0)
        btn2 = tk.Radiobutton(root,
                              text="Hexagon",
                              padx=20,
                              variable=self.choice,
                              value=2)
        btn2.grid(row=4, column=1)

        btn3 = tk.Radiobutton(root,
                              text="Draw Structure",
                              padx=20,
                              variable=self.choice,
                              value=3)
        btn3.grid(row=4, column=2)

        tk.Checkbutton(root, text="Show Canonical Order", variable=self.debugcano).grid(row=5, sticky=tk.W)

        ex = tk.Button(root, text="Submit", command=self.choiceFunction)
        ex.grid(row=6)
        # else: 
        #     tk.messagebox.showerror("Error", "ERROR!! THE INITIAL GRAPH IS NON PLANAR, START AGAIN")
        # TODO NOt working if error

    def letter_inputbox(self):
        """This function takes user input for letter shaped floor plans
        """
        self.top = tk.Toplevel(self.root, width=300, height=300)
        root = self.top
        sub_text = tk.Label(root,
                            text="""Choose the letter structure of Floorplan:""",
                            justify=tk.LEFT,
                            padx=20)
        sub_text.grid(row=3)
        btn1 = tk.Radiobutton(root,
                              text="L Shape",
                              padx=20,
                              variable=self.choice,
                              value=1)
        btn1.grid(row=4, column=0)
        btn2 = tk.Radiobutton(root,
                              text="T Shape",
                              padx=20,
                              variable=self.choice,
                              value=2)
        btn2.grid(row=4, column=1)

        btn3 = tk.Radiobutton(root,
                              text="Z Shape",
                              padx=20,
                              variable=self.choice,
                              value=3)
        btn3.grid(row=4, column=2)

        btn4 = tk.Radiobutton(root,
                              text="U Shape",
                              padx=20,
                              variable=self.choice,
                              value=4)
        btn4.grid(row=4, column=3)

        ex = tk.Button(root, text="Submit", command=self.letterChoiceFunction)
        ex.grid(row=6)


    def letterChoiceFunction(self):
        self.top.destroy()
        if(self.choice.get() == 1):
            self.letter = "L Shape"
            self.lettershape()
        elif(self.choice.get() == 2):
            self.letter = "T Shape"
            self.lettershape()
        elif(self.choice.get() == 3):
            self.letter = "Z Shape"
            self.lettershape()
        elif(self.choice.get() == 4):
            self.letter = "U Shape"
            self.lettershape()

    def lettershape(self):
        self.top.destroy()
        self.app.command = "letter_shape"
        self.command = "letter_shape"
        self.end.set(self.end.get() + 1)

    def choiceFunction(self):
        self.top.destroy()
        if (self.choice.get() == 1):
            self.shapes.set("Pentagon")
            self.polygonal()
        elif (self.choice.get() == 2):
            self.shapes.set("Hexagon")
            self.polygonal()
        else:
            self.cano_out_bdry()

    def completeStructure(self):
        self.canvasForOuterBoundary.create_line(self.outer_boundary2[len(self.outer_boundary2) - 1][2],
                                                self.outer_boundary2[len(self.outer_boundary2) - 1][3],
                                                self.outer_boundary2[0][0], self.outer_boundary2[0][1])

    def create_grid(self, event=None):
        w = self.canvasForOuterBoundary.winfo_width()  # Get current width of canvas
        h = self.canvasForOuterBoundary.winfo_height()  # Get current height of canvas
        self.canvasForOuterBoundary.delete('grid_line')  # Will only remove the grid_line

        # Creates all vertical lines at intevals of 100
        for i in range(0, w, 20):
            self.canvasForOuterBoundary.create_line([(i, 0), (i, h)], tag='grid_line', fill='grey')

        # Creates all horizontal lines at intevals of 100
        for i in range(0, h, 20):
            self.canvasForOuterBoundary.create_line([(0, i), (w, i)], tag='grid_line')

    def cano_out_bdry(self):
        self.shapes.set("Custom");
        self.top = tk.Toplevel(self.root, width=300, height=300)
        root = self.top
        root.title('Boundary of Outer Structure')
        canvas = tk.Canvas(root, bg="white", width=600, height=400)
        self.canvasForOuterBoundary = canvas
        canvas.bind('<Configure>', self.create_grid)

        main_text = tk.Label(root, text="First draw Active Front\n(Left to Right).")
        main_text.place(x=0, y=0)
        # main_text.grid(row = 0, column = 0)

        main_text2 = tk.Label(root,
                              text="At the end, to join \n initial and final points\n press Complete Structure \n and Submit")
        # main_text2.grid(row = 1, column = 0)
        main_text2.place(x=0, y=50)
        btn0 = tk.Button(root, text='Complete Structure!', width=15,
                         height=5, bd='10', command=self.completeStructure)

        btn0.place(x=0, y=120)

        btn = tk.Button(root, text='Submit!', width=15,
                        height=5, bd='10', command=self.polygonal)

        btn.place(x=0, y=270)
        canvas.scale("all", 0, 0, 1, -1)
        canvas.pack()
        coords = {"x": 0, "y": 0, "x2": 0, "y2": 0}
        self.outer_boundary2 = []
        lines = []

        self.previous_point = []

        def click(e):
            if (len(self.previous_point) == 0):
                coords["x"] = e.x
                coords["y"] = e.y
            else:
                coords["x"] = self.previous_point[0]
                coords["y"] = self.previous_point[1]

            lines.append(canvas.create_line(coords["x"], coords["y"], coords["x"], coords["y"]))

        def release(l):
            lis = []
            lis.append(coords["x"]);
            lis.append(coords["y"]);
            lis.append(coords["x2"]);
            lis.append(coords["y2"])
            self.previous_point = [coords["x2"], coords["y2"]]

            self.outer_boundary2.append(lis)

        def drag(e):
            coords["x2"] = e.x
            coords["y2"] = e.y
            canvas.coords(lines[-1], coords["x"], coords["y"], coords["x2"], coords["y2"])

        canvas.bind("<ButtonPress-1>", click)
        canvas.bind("<B1-Motion>", drag)
        canvas.bind('<ButtonRelease-1>', release)
        # root.mainloop()
        print("Final = {}".format(self.outer_boundary2))
        for i in range(len(self.outer_boundary2)):
            self.outer_boundary2.append([self.outer_boundary2[i][2], self.outer_boundary2[i][3]])
            if (i == len(self.outer_boundary2) - 1):
                self.outer_boundary2.append([self.outer_boundary2[0][0], self.outer_boundary2[0][1]])
                print("Outer Boundary detected in the shape: {}".format(self.outer_boundary2))

        # self.outer_boundary[len(self.outer_boundary)-1][1] = self.outer_boundary[0][1]
        # first = self.outer_boundary[0]
        # for i in range(len(self.outer_boundary)-1):
        #     self.outer_boundary[i] = self.outer_boundary[i+1]
        # self.outer_boundary[len(self.outer_boundary)-1] = first;

        # poly.dissected(self.graph_data,self.pen,self.color_list,self.outer_boundary)

    def radio_sel(self,mode):
        if mode=="menu":
            # Set mode
            if(self.circ_choice.get() == 2):
                self.checkvar2.set(1)
                self.checkvar3.set(0)
                self.checkvar4.set(0)
            elif(self.circ_choice.get() == 3):
                self.checkvar2.set(0)
                self.checkvar3.set(1)
                self.checkvar4.set(0)
            elif (self.circ_choice.get() == 4):
                self.checkvar2.set(0)
                self.checkvar3.set(0)
                self.checkvar4.set(1)
        elif mode=="redundant":
            self.rem = self.opti.get()
            print("The redundant corridors will be removed")

    def radio_desel(self,mode):
        if mode=="menu":
            self.circ_choice.set(0)
            self.checkvar2.set(0)
            self.checkvar3.set(0)
        elif mode=="redundant":
            self.opti.set(0)
            self.rem = self.opti.get()
            print("The whole spanning circulation will be displayed")
        

    def circ_menu(self):
        """Choose which type of circulation you want
        """
        # c1 = tk.Checkbutton(master.frame1, text = "Dimensioned Circulation",relief='flat',**button_details,selectcolor='#4A4E69',width=7 ,variable = master.checkvar2,onvalue = 1, offvalue = 0)
        # c1.grid(row=4,column=1,padx=5,pady=5)

        # c2 = tk.Checkbutton(master.frame1, text = "Remove Circulation",relief='flat',**button_details,selectcolor='#4A4E69',width=7 ,variable = master.checkvar3,onvalue = 1, offvalue = 0)
        # c2.grid(row=5,column=1,padx=5,pady=5)

        self.top = tk.Toplevel(self.root, width=300, height=300)
        root = self.top
        root.geometry("1000x100")
        sub_text = tk.Label(root, text="""Choose the circulation choice:""", justify=tk.LEFT, padx=20)
        sub_text.grid(row=3)

        btn1 = tk.Radiobutton(root, text="Normal", padx=20, variable=self.circ_choice, value=1, command=lambda: self.radio_sel("menu"))
        btn1.grid(row=4, column=0)
        
        btn2 = tk.Radiobutton(root, text="Dimensioned circulation", padx=20, variable=self.circ_choice, value=2, command=lambda: self.radio_sel("menu"))
        btn2.grid(row=4, column=1)

        btn3 = tk.Radiobutton(root, text="Remove corridors", padx=20, variable=self.circ_choice, value=3, command=lambda: self.radio_sel("menu"))
        btn3.grid(row=4, column=2)

        btn4 = tk.Radiobutton(root, text="Minimum dimensioned circulation", padx=20, variable=self.circ_choice, value=4, command=lambda: self.radio_sel("menu"))
        btn4.grid(row=4, column=3)

        clear_button = tk.Button(root, text="Clear Selection", command=lambda: self.radio_desel("menu"))
        clear_button.grid(row = 7, column = 2, pady=10)

        ex = tk.Button(root,text = "Submit",command = self.change_entry_gui, justify=tk.CENTER)
        ex.grid(row = 7, column = 0, pady=10)

        
        # self.top1 = tk.Toplevel(self.root, width=1000, height=1000)
        # root = self.top1
        # root.geometry("500x200")
        # root.title('Circulation Entry Changer')
        # main_text = tk.Label(root, text="Enter the two rooms adjacent to the new entry door")
        # main_text.grid(row= 1, column= 0, padx = 20, ipady = 10)
        # l_val = tk.Entry(root, textvariable = self.l)
        # l_val.grid(row  = 3, column = 0)
        # r_val = tk.Entry(root, textvariable = self.r)
        # r_val.grid(row = 3, column = 2)
        # opti_btn = tk.Radiobutton(root, text="Remove redundant corridors", padx=20, variable=self.opti, value=1, command=lambda: self.radio_sel())
        # opti_btn.grid(row = 7, column = 0)
        # clear_button = tk.Button(root, text="Clear Selection", command=lambda: self.radio_desel())
        # clear_button.grid(row = 7, column = 2, pady=10)
        # ex = tk.Button(root,text = "Submit",command = self.corridor_thickness_gui, justify=tk.CENTER)
        # ex.grid(padx=100, pady=20)


    def change_entry_gui(self):
        """This function takes user input for starting edge/door for the corridor
        """
        self.top.destroy()
        self.top1 = tk.Toplevel(self.root, width=1000, height=1000)
        root = self.top1
        root.geometry("500x200")
        root.title('Circulation Entry Changer')
        main_text = tk.Label(root, text="Enter the two rooms adjacent to the new entry door")
        main_text.grid(row= 1, column= 0, padx = 20, ipady = 10)
        l_val = tk.Entry(root, textvariable = self.l)
        l_val.grid(row  = 3, column = 0)
        r_val = tk.Entry(root, textvariable = self.r)
        r_val.grid(row = 3, column = 2)
        opti_btn = tk.Radiobutton(root, text="Get minimal circulation", padx=20, variable=self.opti, value=1, command=lambda: self.radio_sel("redundant"))
        opti_btn.grid(row = 7, column = 0)
        clear_button = tk.Button(root, text="Clear Selection", command=lambda: self.radio_desel("redundant"))
        clear_button.grid(row = 7, column = 2, pady=10)
        ex = tk.Button(root,text = "Submit",command = self.corridor_thickness_gui, justify=tk.CENTER)
        ex.grid(padx=100, pady=20)
    

    def corridor_thickness_gui(self):

        """This function takes user input for starting edge/door for the corridor
        """
        self.top2 = tk.Toplevel(self.root, width=800, height=400)
        root = self.top2
        root.geometry("400x100")
        root.title('Corridor thickness')
        corridor_text = tk.Label(root,text="Enter the corridor thickness")
        corridor_text.grid(row= 3, column= 0, ipadx = 5, ipady = 20)
        thickness = tk.Entry(root, textvariable=self.ct)
        thickness.grid(row  = 3, column = 2)
        ex = tk.Button(root,text = "Submit",command = self.corridor_thickness_ender, justify=tk.CENTER)
        ex.grid(column= 1, ipadx=10)

    def corridor_thickness_ender(self):
        """This function concludes user input for corridor thickness and entry door
            and transfers control to the background functions
        """
        self.left = self.l.get() + 1
        self.right = self.r.get() + 1
        self.entry_door = [self.left, self.right]
        self.corridor_thickness = self.ct.get()
        self.end.set(self.end.get()+1)
        self.top1.destroy()
        self.top2.destroy()
        
        self.app.command="circulation"
        self.command = "circulation"
        self.end.set(self.end.get()+1)

    def remove_corridor_gui(self, adjacency):
        """GUI for user to indicate where to remove corridors
        Args:
            adjacency (dict): Dictionary having keys as the corridor vertices and
                              the values as the pair of rooms the corridor connects
        Returns:
            rem_edges (List): List of edges between which the corridor vertex has to be removed
        """
        # Required variables
        adj_list = list(adjacency.values()) # List to display the corridors as a list
        rem_or_not = [] # List to hold values 0 or 1 (1 if corridor needs to be removed)
        rem_edges = [] # List of edges where corridors are to be removed

         # GUI initialization for the window
        root = tk.Toplevel()
        root.title('Remove corridor')
        root.geometry(str(400) + 'x' + str(400))
        
        # Create a Main Frame
        main_frame = tk.Frame(root)
        main_frame.pack(fill=tk.BOTH, expand=1)

        # Create Canvas
        my_canvas = tk.Canvas(main_frame)
        my_canvas.pack(side=tk.LEFT,fill=tk.BOTH,expand=1)

        # Add Scrollbar to the canvas
        my_scrollbar = ttk.Scrollbar(main_frame, orient=tk.VERTICAL, command=my_canvas.yview)
        my_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Configure the canvas
        my_canvas.configure(yscrollcommand=my_scrollbar.set)
        my_canvas.bind('<Configure>',lambda e: my_canvas.configure(scrollregion=my_canvas.bbox("all")))

        # Create another frame inside the canvas
        second_frame = tk.Frame(my_canvas)

        # Add that new frame to a window in the canvas
        my_canvas.create_window((0,0), window=second_frame, anchor="nw")

        corr_text = tk.Label(second_frame,text="Enter 1 if you want to remove corridor",justify=tk.CENTER)
        corr_text.grid(row= 3, column= 10, ipadx = 5, ipady = 20)

        # Initializing the rem_or_not array
        for i in range(len(adjacency)):
            rem_or_not.append(tk.IntVar(value=0))
        
        # For getting user input for which corridors to remove
        for i in range(1,len(adjacency)):
            text = tk.Label(second_frame, text = str(adj_list[i][0]) + "           " + str(adj_list[i][1]))
            text.grid(row=i+30,column=8)
            rem_val = tk.Entry(second_frame, textvariable=rem_or_not[i])
            rem_val.grid(row=i+30,column=10)

            # rem_corr_btn = tk.Radiobutton(root, text=str(adj_list[i][0]) + "           " + str(adj_list[i][1]), padx=20, variable=self.opti, value=1, command=lambda: self.radio_sel())
            # rem_corr_btn.grid(row = i+30, column = 8)

        # When submit is clicked
        def rem_corr_submit():
            """This function records the input for removing corridors
            """
            for i in range(len(rem_or_not)):
                # Checks if the remove corridor value is zero or not
                if(rem_or_not[i].get()):
                    rem_edges.append(adj_list[i])
                    
            print("rem_corridor_submit")
            root.destroy()

        # When we want to remove all corridors
        def rem_all():
            """This function gives an option to delete all corridors in single click
            """
            for i in range(len(rem_or_not)):
                rem_or_not[i].set(1)
        
        done_btn = tk.Button(second_frame, text='Submit', padx=5, command=rem_corr_submit)
        # done_btn.place(relx=0.4, rely=0.9, anchor='ne')
        done_btn.grid(row=len(adjacency)+30,column=8)

        rem_all_btn = tk.Button(second_frame, text="Remove all", padx=5, command=rem_all)
        rem_all_btn.grid(row=len(adjacency)+30,column=16)

        root.wait_window(root)
        print("rem_corr_gui")
        print("To remove the corridors between: ")
        for i in range(len(rem_edges)):
            print(rem_edges[i])

        self.app.command="circulation"
        self.command = "circulation"
        self.end.set(self.end.get()+1)
            
        return rem_edges
        
    def save_file(self, filename="Rectangular Dual Graph.txt"):
        # self.root.filename = self.value
        if filename == "Rectangular Dual Graph.txt":
            f = filedialog.asksaveasfile(defaultextension=".txt", title="Select file",
                                         filetypes=(("text files", "*.txt"), ("all files", "*.*")),
                                         initialfile=filename)
        else:
            f = open(filename, "w")
        if f is None:
            return

        saved_data = []
        saved_data.append(self.value)

        node_data = []
        for node in self.app.nodes_data:
            ndata = []
            ndata.append(node.pos_x)
            ndata.append(node.pos_y)
            ndata.append(node.circle_id)
            node_data.append(ndata)

        saved_data.append(node_data)
        saved_data.append(self.app.edges)
        saved_data.append(self.app.connectivity)
        saved_data.append(self.dimensional_constraints)
        f.write(str(saved_data))
        # f.write(str(node_data))
        l = open(".\saved_files\RFP_latest.txt", "w")
        l.write(str(saved_data))
        l.close()
        f.close()

    def show_warning(self, str):
        tk.messagebox.showinfo("Warning", str)


if __name__ == '__main__':
    value = gui_class()
