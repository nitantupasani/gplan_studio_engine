"""Main file of the project

"""
# from graphoperations.operations import get_encoded_matrix
from dataclasses import is_dataclass
import warnings
import time
import tkinter as tk
import networkx as nx
import numpy as np
from numpy import true_divide
import pythongui.gui as gui
import source.inputgraph as inputgraph
import pythongui.drawing as draw
import pythongui.dimensiongui as dimgui
import pythongui.mindimensiongui as mindimgui
import circulation as cir
import matplotlib.pyplot as plt
import copy
import input.input_for_min_dim as input_for_min_dim
from source.graphoperations.operations import get_encoded_matrix
import json
from system_functions.os_functions import delete_file
import source.dimensioning.minimum_dimensioning as min_dim

import source.lettershape.lshape.Lshaped as Lshaped
import source.lettershape.tshape.tshape as Tshaped
import source.lettershape.ushape.ushape as Ushaped
import source.lettershape.zshape.zshape as Zshaped

# import checker
# from tkinter import messagebox
# import dimension_gui as dimgui
# import boundary_gui as bdygui

# import tests
# import triangularity as trng
origin = 0


def run():
    """Runs the GPLAN program.

    Args:
        None

    Returns:
        None
    """

    def printe(string):
        """Prints string on GUI console.

        Args:
            None

        Returns:
            None
        """
        gclass.textbox.insert('end', string)
        gclass.textbox.insert('end', "\n")

    warnings.filterwarnings("ignore")
    gclass = gui.gui_class() 
    for i in range(0,11):
        print(gclass.value[i])

    dim_circ = False

    while (gclass.command!="end"):
        if(gclass.command=="dissection"):
            make_dissection_corridor(gclass)
        else:
            graph = inputgraph.InputGraph(gclass.value[0]
                                          , gclass.value[1]
                                          , gclass.value[2]
                                          , gclass.value[7])
                        # Get node coordinates
            node_coord = graph.coordinates
            origin = 0
            # print("GUI Return", gclass.__dir__())
            if(gclass.command == "circulation"): # For spanning circulation
                is_dimensioned = False
                remove_corridor = False
                dim_constraints = []
                if (gclass.value[8] == 0 and gclass.value[9] == 0): #Non-dimensioned single circulation
                    start = time.time()
                    graph.irreg_single_dual()
                    end = time.time()
                    printe("Time taken: " + str((end-start)*1000) + " ms")
                    print("type of roomx " + str(type(graph.room_x)))
                    graph_data = {
                            'room_x': graph.room_x,
                            'room_y': graph.room_y,
                            'room_width': graph.room_width,
                            'room_height': graph.room_height,
                            # 'room_x_bottom_left': graph.room_x_bottom_left,
                            # 'room_x_bottom_right': graph.room_x_bottom_right,
                            # 'room_x_top_left': graph.room_x_top_left,
                            # 'room_x_top_right': graph.room_x_top_right,
                            # 'room_y_left_bottom': graph.room_y_left_bottom,
                            # 'room_y_right_bottom': graph.room_y_right_bottom,
                            # 'room_y_left_top': graph.room_y_left_top,
                            # 'room_y_right_top': graph.room_y_right_top,
                            'area': graph.area,
                            'extranodes': graph.extranodes,
                            'mergednodes': graph.mergednodes,
                            'irreg_nodes': graph.irreg_nodes1
                        }
                    
                    # new_graph_data = call_circulation(graph_data, gclass.value[2], gclass.entry_door, gclass.corridor_thickness)
                    (new_graph_data, success) = call_circulation(graph_data, gclass, node_coord, is_dimensioned, dim_constraints, remove_corridor)
                    # If there was some error in algorithm execution new_graph_data will be empty
                    # we display the pop-up error message
                    if new_graph_data == None:
                        tk.messagebox.showerror("Error", "ERROR!! THE INITIAL CHOSEN ENTRY EDGE MUST BE EXTERIOR EDGE")
                    
                    # If no issues we continue to draw the corridor
                    else :
                        # draw_circulation(new_graph_data, gclass.ocan.canvas, gclass.value[6], gclass.entry_door)
                        # draw_circulation(new_graph_data, gclass.pen, gclass.ocan.canvas, gclass.value[6])
                        draw.draw_rdg(new_graph_data, 1, gclass.pen, 1, gclass.value[6], [],origin)


                elif(gclass.value[8] == 1 and gclass.value[9] == 0): #Dimensioned single circulation
                    is_dimensioned = True
                    feasible_dim = 0
                    old_dims = [[0] * gclass.value[0]
                                , [0] * gclass.value[0]
                                , [0] * gclass.value[0]
                                , [0] * gclass.value[0]
                                , ""
                                , [0] * gclass.value[0]
                                , [0] * gclass.value[0]]
                    min_width,max_width,min_height,max_height, symm_string, min_aspect, max_aspect, plot_width, plot_height  = dimgui.gui_fnc(old_dims, gclass.value[0])
                    dimensional_constraints = [min_width,max_width,min_height,max_height, symm_string, min_aspect, max_aspect, plot_width, plot_height]
                    start = time.time()
                    try:
                        graph.oneconnected_dual("multiple")
                    except inputgraph.OCError:
                        gclass.show_warning("Can not generate rectangular floorplan.")
                        graph.irreg_multiple_dual()
                    except inputgraph.BCNError:
                        graph.irreg_multiple_dual()
                    
                    graph.single_floorplan(min_width,min_height,max_width,max_height,symm_string, min_aspect, max_aspect, plot_width, plot_height)
                    while(graph.floorplan_exist == False):
                        old_dims = [min_width, max_width, min_height, max_height, symm_string, min_aspect, max_aspect]
                        min_width,max_width,min_height,max_height, symm_string, min_aspect, max_aspect, plot_width, plot_height  = dimgui.gui_fnc(old_dims, gclass.value[0])
                        graph.irreg_multiple_dual()
                        graph.single_floorplan(min_width,min_height,max_width,max_height,symm_string, min_aspect, max_aspect, plot_width, plot_height)
                    end = time.time()
                    printe("Time taken: " + str((end-start)*1000) + " ms")
                    for idx in range(len(graph.room_x)):
                        graph_data = {
                                'room_x': graph.room_x,
                                'room_y': graph.room_y,
                                'room_width': graph.room_width,
                                'room_height': graph.room_height,
                                'area': graph.area,
                                'extranodes': graph.extranodes,
                                'mergednodes': graph.mergednodes,
                                'irreg_nodes': graph.irreg_nodes1
                            }

                        # new_graph_data = call_circulation(graph_data, gclass.value[2], gclass.entry_door, gclass.corridor_thickness)
                        dim_constraints = [min_width, max_width, min_height, max_height, min_aspect, max_aspect]
                        (new_graph_data, success) = call_circulation(graph_data, gclass, node_coord, is_dimensioned, dim_constraints, remove_corridor)
                        print("Constraints: ", dim_constraints)
                        print("New graph data: ", new_graph_data)
                        print("success: ", success)                        
                        # If there was some error in algorithm execution new_graph_data will be empty
                        # we display the pop-up error message
                        if new_graph_data == None:
                            tk.messagebox.showerror("Error", "ERROR!! THE INITIAL CHOSEN ENTRY EDGE MUST BE EXTERIOR EDGE")
                        
                        # If no issues we continue to draw the corridor
                        else :
                            if (success == False):
                                continue
                            # draw_circulation(new_graph_data, gclass.ocan.canvas, gclass.value[6], gclass.entry_door)
                            # draw_circulation(new_graph_data, gclass.pen, gclass.ocan.canvas, gclass.value[6])
                            draw.draw_rdg(new_graph_data, 1, gclass.pen, 1, gclass.value[6], [],origin)
                            feasible_dim = 1
                            break
                    
                    if(feasible_dim == 0):
                        tk.messagebox.showerror("Error", "ERROR!! NO CIRCULATION POSSIBLE FOR GIVEN DIMENSIONS")
                
                elif(gclass.value[8] == 0 and gclass.value[9] == 1): # Add/remove
                    remove_corridor = True
                    start = time.time()
                    graph.irreg_single_dual()
                    end = time.time()
                    printe("Time taken: " + str((end-start)*1000) + " ms")
                    print("type of roomx " + str(type(graph.room_x)))
                    graph_data = {
                            'room_x': graph.room_x,
                            'room_y': graph.room_y,
                            'room_width': graph.room_width,
                            'room_height': graph.room_height,
                            'area': graph.area,
                            'extranodes': graph.extranodes,
                            'mergednodes': graph.mergednodes,
                            'irreg_nodes': graph.irreg_nodes1
                        }
                    
                    (new_graph_data, success) = call_circulation(graph_data, gclass, node_coord, is_dimensioned, dim_constraints, remove_corridor)
                    
                    # If there was some error in algorithm execution new_graph_data will be empty
                    # we display the pop-up error message
                    if new_graph_data == None:
                        tk.messagebox.showerror("Error", "ERROR!! THE INITIAL CHOSEN ENTRY EDGE MUST BE EXTERIOR EDGE")
                    
                    # If no issues we continue to draw the corridor
                    else :
                        # draw_circulation(new_graph_data, gclass.ocan.canvas, gclass.value[6], gclass.entry_door)
                        # draw_circulation(new_graph_data, gclass.pen, gclass.ocan.canvas, gclass.value[6])
                        draw.draw_rdg(new_graph_data, 1, gclass.pen, 1, gclass.value[6], [],origin)



            elif (gclass.command == "single"):  # Single Irregular Dual/Floorplan
                if (gclass.value[4] == 0):  # Non-Dimensioned single dual
                    start = time.time()
                    graph.irreg_single_dual()
                    end = time.time()
                    printe("Time taken: " + str((end - start) * 1000) + " ms")
                    graph_data = {
                        'room_x': graph.room_x,
                        'room_y': graph.room_y,
                        'room_width': graph.room_width,
                        'room_height': graph.room_height,
                        'area': graph.area,
                        'extranodes': graph.extranodes,
                        'mergednodes': graph.mergednodes,
                        'irreg_nodes': graph.irreg_nodes1
                    }
                    gclass.output_data.append(graph_data)
                    draw.draw_rdg(graph_data
                                  , 1
                                  , gclass.pen
                                  , 1
                                  , gclass.value[6]
                                  , []
                                  , origin)
                else:  # Dimensioned single floorplan
                    old_dims = [[0] * gclass.value[0]
                        , [0] * gclass.value[0]
                        , [0] * gclass.value[0]
                        , [0] * gclass.value[0]
                        , ""
                        , [0] * gclass.value[0]
                        , [0] * gclass.value[0]]
                    min_width, max_width, min_height, max_height, symm_string, min_aspect, max_aspect, plot_width, plot_height = dimgui.gui_fnc(
                        old_dims, gclass.value[0])
                    dimensional_constraints = [min_width, max_width, min_height, max_height, symm_string, min_aspect,
                                               max_aspect, plot_width, plot_height]
                    gclass.dimensional_constraints = dimensional_constraints
                    start = time.time()
                    graph.irreg_multiple_dual()
                    graph.single_floorplan(min_width,min_height,max_width,max_height,symm_string, min_aspect, max_aspect, plot_width, plot_height)
                    while(graph.floorplan_exist == False):
                        old_dims = [min_width, max_width, min_height, max_height, symm_string, min_aspect, max_aspect]
                        min_width,max_width,min_height,max_height, symm_string, min_aspect, max_aspect, plot_width, plot_height  = dimgui.gui_fnc(old_dims, gclass.value[0])
                        graph.irreg_multiple_dual()
                        graph.single_floorplan(min_width,min_height,max_width,max_height,symm_string, min_aspect, max_aspect, plot_width, plot_height)
                    end = time.time()
                    printe("Time taken: " + str((end-start)*1000) + " ms")
                    graph_data = {
                            'room_x': graph.room_x,
                            'room_y': graph.room_y,
                            'room_width': graph.room_width,
                            'room_height': graph.room_height,
                            'area': graph.area,
                            'extranodes': graph.extranodes,
                            'mergednodes': graph.mergednodes,
                            'irreg_nodes': graph.irreg_nodes1
                        }
                    draw.draw_rdg(graph_data
                            ,1
                            ,gclass.pen
                            ,1
                            ,gclass.value[6]
                            ,[]
                            ,origin)
                            
            elif gclass.command == "letter_shape":
                if(gclass.value[4] == 0): #Non-Dimensioned Letter Shape
                    start = time.time()
                    if(gclass.letter == "L Shape"):
                        Lshaped.LShapedFloorplan(graph, gclass.app.nodes_data)
                    elif(gclass.letter == "T Shape"):
                        Tshaped.TShapedFloorplan(graph)
                    elif(gclass.letter == "Z Shape"):
                        Zshaped.ZShapedFloorplan(graph)
                    elif(gclass.letter == "U Shape"):
                        Ushaped.UShapedFloorplan(graph)
                    end = time.time()
                    print("REL MATRIX \n", graph.matrix)
                    graph_data = {
                        'room_x': graph.room_x,
                        'room_y': graph.room_y,
                        'room_width': graph.room_width,
                        'room_height': graph.room_height,
                        'area': graph.area,
                        'extranodes': graph.extranodes,
                        'mergednodes': graph.mergednodes,
                        'irreg_nodes': graph.irreg_nodes1
                    }
                    draw.draw_rdg(graph_data
                                , 1
                                , gclass.pen
                                , 1
                                , gclass.value[6]
                                , []
                                , origin)
                else:
                    old_dims = [[0] * gclass.value[0]
                        , [0] * gclass.value[0]
                        , [0] * gclass.value[0]
                        , [0] * gclass.value[0]
                        , ""
                        , [0] * gclass.value[0]
                        , [0] * gclass.value[0]]
                    min_width, max_width, min_height, max_height, symm_string, min_aspect, max_aspect, plot_width, plot_height = dimgui.gui_fnc(
                        old_dims, gclass.value[0])
                    start = time.time()   
                    if(gclass.letter == "L Shape"):
                        Lshaped.LShapedFloorplan(graph, gclass.app.nodes_data)
                    # elif(letter == "T Shape"):
                    #     source.lettershape.tshape.tshape.TShapedFloorplan(graph)
                    # elif(letter == "Z Shape"):
                    #     source.lettershape.zshape.zshape.ZShapedFloorplan(graph)
                    # elif(letter == "U Shape"):
                    #     source.lettershape.ushape.ushape.UShapedFloorplan(graph)
                    
                    graph.rel_matrix_list.append(graph.matrix) #All rels are in it. Currently we have only 1.
                    
                    # Since multiple rfp are generated before calling single_floorplan, all the parameters need to be
                    # converted list of lists
                    temp_lst = []
                    temp_lst.append(graph.extranodes)
                    graph.extranodes = temp_lst
                    temp_lst = []
                    temp_lst.append(graph.mergednodes)
                    graph.mergednodes = temp_lst
                    temp_lst = []
                    temp_lst.append(graph.irreg_nodes1)
                    graph.irreg_nodes1 = temp_lst
                    temp_lst = []
                    temp_lst.append(graph.room_x)
                    graph.room_x = temp_lst
                    temp_lst = []
                    temp_lst.append(graph.room_y)
                    graph.room_y = temp_lst
                    temp_lst = []
                    temp_lst.append(graph.room_width)
                    graph.room_width = temp_lst
                    temp_lst = []
                    temp_lst.append(graph.room_height)
                    graph.room_height = temp_lst
                    
                    graph.nodecnt -= 4 # Because Lshaped was counting NESW as well
                    
                    graph.single_floorplan(min_width, min_height, max_width, max_height, symm_string, min_aspect,
                                           max_aspect, plot_width, plot_height)
                    
                    # Add code here in case multiple RELs get generated.
                    
                    end = time.time()
                    printe("Time taken: " + str((end - start) * 1000) + " ms") 
                    graph_data = {
                        'room_x': graph.room_x,
                        'room_y': graph.room_y,
                        'room_width': graph.room_width,
                        'room_height': graph.room_height,
                        'area': graph.area,
                        'extranodes': graph.extranodes,
                        'mergednodes': graph.mergednodes,
                        'irreg_nodes': graph.irreg_nodes1
                    }
                    draw.draw_rdg(graph_data
                                , 1
                                , gclass.pen
                                , 1
                                , gclass.value[6]
                                , []
                                , origin)
                    
            elif(gclass.command == "multiple_l"):#Multiple L-shaped Floorplan
                if(gclass.value[4] == 0):#Non-Dimensioned multiple dual
                    start = time.time()
                    Lshaped.multipleLshapedFloorplans(graph, gclass.app.nodes_data)
                    end = time.time()
                    printe("Average Time taken: " + str(((end - start) * 1000) / graph.fpcnt) + " ms")
                    printe("Number of floorplans: " + str(graph.fpcnt))
                    for idx in range(graph.fpcnt):
                        graph_data = {
                            'room_x': graph.room_x[idx],
                            'room_y': graph.room_y[idx],
                            'room_width': graph.room_width[idx],
                            'room_height': graph.room_height[idx],
                            'area': graph.area,
                            'extranodes': graph.extranodes[idx],
                            'mergednodes': graph.mergednodes[idx],
                            'irreg_nodes': graph.irreg_nodes1[idx]
                        }
                        gclass.multiple_output_found = 1

                        gclass.output_data.append(graph_data)
                    
            elif (gclass.command == "staircase_shaped"):
                start = time.time()
                inputgraph.staircaseshaped(graph)
                end = time.time()
                graph_data = {
                    'room_x': graph.room_x,
                    'room_y': graph.room_y,
                    'room_width': graph.room_width,
                    'room_height': graph.room_height,
                    'area': graph.area,
                    'extranodes': graph.extranodes,
                    'mergednodes': graph.mergednodes,
                    'irreg_nodes': graph.irreg_nodes1
                }
                draw.draw_rdg(graph_data
                              , 1
                              , gclass.pen
                              , 1
                              , gclass.value[6]
                              , []
                              , origin)

            elif(gclass.command == "multiple"):#Multiple Irregular Dual/Floorplan
                if(gclass.value[4] == 0):#Non-Dimensioned multiple dual
                    start = time.time()
                    graph.irreg_multiple_dual()
                    end = time.time()
                    printe("Average Time taken: " + str(((end - start) * 1000) / graph.fpcnt) + " ms")
                    printe("Number of floorplans: " + str(graph.fpcnt))
                    for idx in range(graph.fpcnt):
                        graph_data = {
                            'room_x': graph.room_x[idx],
                            'room_y': graph.room_y[idx],
                            'room_width': graph.room_width[idx],
                            'room_height': graph.room_height[idx],
                            'area': graph.area,
                            'extranodes': graph.extranodes[idx],
                            'mergednodes': graph.mergednodes[idx],
                            'irreg_nodes': graph.irreg_nodes1[idx]
                        }
                        gclass.multiple_output_found = 1

                        gclass.output_data.append(graph_data)
                        # draw.draw_rdg(graph_data
                        #     ,idx+1
                        #     ,gclass.pen
                        #     ,1
                        #     ,gclass.value[6]
                        #     ,[]
                        #     ,origin)
                        # origin += 1000
                        
                        # gclass.ocan.add_tab()
                        # gclass.pen = gclass.ocan.getpen()
                        # gclass.pen.speed(0)
                else:#Dimensioned multiple floorplans
                    old_dims = [[0] * gclass.value[0]
                                , [0] * gclass.value[0]
                                , [0] * gclass.value[0]
                                , [0] * gclass.value[0]
                                , ""
                                , [0] * gclass.value[0]
                                , [0] * gclass.value[0]]
                    min_width,max_width,min_height,max_height, symm_string, min_aspect, max_aspect, plot_width, plot_height  = dimgui.gui_fnc(old_dims, gclass.value[0])
                    start = time.time()
                    graph.irreg_multiple_dual()
                    graph.multiple_floorplan(min_width,min_height,max_width,max_height,symm_string, min_aspect, max_aspect, plot_width, plot_height)
                    end = time.time()
                    printe("Time taken: " + str((end-start)*1000) + " ms")
                    printe("Number of floorplans: " +  str(len(graph.room_x)))
                    for idx in range(len(graph.room_x)):
                        graph_data = {
                            'room_x': graph.room_x[idx],
                            'room_y': graph.room_y[idx],
                            'room_width': graph.room_width[idx],
                            'room_height': graph.room_height[idx],
                            'area': graph.area[idx],
                            'extranodes': graph.extranodes[idx],
                            'mergednodes': graph.mergednodes[idx],
                            'irreg_nodes': graph.irreg_nodes1[idx]
                        }
                        gclass.multiple_output_found = 1

                        gclass.output_data.append(graph_data)
                        gclass.dimensional_constraints = dimensional_constraints
                        gclass.ptpg = graph
                        # origin += 1000
                        # draw.draw_rdg(graph_data
                        #     ,idx+1
                        #     ,gclass.pen
                        #     ,1
                        #     ,gclass.value[6]
                        #     ,[]
                        #     ,origin)
                        
                        # gclass.ocan.add_tab()
                        # gclass.pen = gclass.ocan.getpen()
                        # gclass.pen.speed(0)
            elif(gclass.command == "single_oc"):
                if(gclass.value[4] == 0 and gclass.value[10] == 0): #Non-Dimensioned single rectangular dual
                    start = time.time()
                    try:
                        graph.oneconnected_dual("single")
                    except inputgraph.OCError:
                        gclass.show_warning("Can not generate rectangular floorplan.")
                        graph.irreg_single_dual()
                    except inputgraph.BCNError:
                        graph.irreg_single_dual()
                    end = time.time()
                    printe("Time taken: " + str((end - start) * 1000) + " ms")
                    graph_data = {
                        'room_x': graph.room_x,
                        'room_y': graph.room_y,
                        'room_width': graph.room_width,
                        'room_height': graph.room_height,
                        'area': graph.area,
                        'extranodes': graph.extranodes,
                        'mergednodes': graph.mergednodes,
                        'irreg_nodes': graph.irreg_nodes1
                    }

                    # If room labels are provided, they are stored else left empty
                    room_name = []
                    if len(gclass.value[5]) > 0:
                        room_name = gclass.value[5]
                    draw.draw_rdg(graph_data
                                  , 1
                                  , gclass.pen
                                  , 1
                                  , gclass.value[6]
                                  , room_name
                                  , origin)
                elif (gclass.value[4] == 1):  # Dimensioned single floorplan
                    old_dims = [[0] * gclass.value[0]
                        , [0] * gclass.value[0]
                        , [0] * gclass.value[0]
                        , [0] * gclass.value[0]
                        , ""
                        , [0] * gclass.value[0]
                        , [0] * gclass.value[0]]
                    min_width, max_width, min_height, max_height, symm_string, min_aspect, max_aspect, plot_width, plot_height = dimgui.gui_fnc(
                        old_dims, gclass.value[0], gclass.value[5])
                    start = time.time()
                    try:
                        graph.oneconnected_dual("multiple")
                    except inputgraph.OCError:
                        gclass.show_warning("Can not generate rectangular floorplan.")
                        graph.irreg_multiple_dual()
                    except inputgraph.BCNError:
                        graph.irreg_multiple_dual()
                    graph.single_floorplan(min_width, min_height, max_width, max_height, symm_string, min_aspect,
                                           max_aspect, plot_width, plot_height)
                    while (graph.floorplan_exist == False):
                        old_dims = [min_width, max_width, min_height, max_height, symm_string, min_aspect, max_aspect]
                        min_width, max_width, min_height, max_height, symm_string, min_aspect, max_aspect, plot_width, plot_height = dimgui.gui_fnc(
                            old_dims, gclass.value[0])
                        graph.multiple_dual()
                        graph.single_floorplan(min_width, min_height, max_width, max_height, symm_string, min_aspect,
                                               max_aspect, plot_width, plot_height)
                    end = time.time()
                    printe("Time taken: " + str((end - start) * 1000) + " ms")
                    graph_data = {
                        'room_x': graph.room_x,
                        'room_y': graph.room_y,
                        'room_width': graph.room_width,
                        'room_height': graph.room_height,
                        'area': graph.area,
                        'extranodes': graph.extranodes,
                        'mergednodes': graph.mergednodes,
                        'irreg_nodes': graph.irreg_nodes1
                    }

                    # If room labels are provided, they are stored else left empty
                    room_name = []
                    if len(gclass.value[5]) > 0:
                        room_name = gclass.value[5]
                    gclass.output_data.append(graph_data)
                    draw.draw_rdg(graph_data
                                  , 1
                                  , gclass.pen
                                  , 1
                                  , gclass.value[6]
                                  , room_name
                                  , origin)
                elif(gclass.value[10] == 1):
                    old_dims = [[3] * gclass.value[0]
                        , [3] * gclass.value[0]]
                    min_width, min_height, plot_width, plot_height, optimal_floorplan = mindimgui.gui_fnc(old_dims, gclass.value[0], gclass.value[5])
                    start = time.time()
                    try:
                        graph.oneconnected_dual("multiple")
                    except inputgraph.OCError:
                        gclass.show_warning("Can not generate rectangular floorplan.")
                        graph.irreg_multiple_dual()
                    except inputgraph.BCNError:
                        graph.irreg_multiple_dual()
                    number_of_floorplans = graph.fpcnt
                    floorplan_found = False

                    # Resets the data already present for downloading catalogues
                    gclass.output_data = []
                    gclass.multiple_output_found = 0

                    # Variables for storing the data of the floorplan with minimal area
                    min_area = -1
                    min_graph_data = None
                    areas = []
                    
                    # Iterate through all possible floorplans to find one which satisfies the given conditions
                    for i in range(number_of_floorplans):
                        print("Trying floorplan number", i + 1, "to see if minimum dimension floorplan can be constructed.")
                        floorplan_obj = input_for_min_dim.floorplan(gclass.value[3], gclass.value[4],
                                                            gclass.value[8], gclass.value[9], gclass.corridor_thickness)
                        enc_mat = get_encoded_matrix(gclass.value[0], graph.room_x[i], graph.room_y[i], graph.room_width[i], graph.room_height[i])
                        floorplan_data = floorplan_obj.get_floorplan_details(
                            gclass.value[5], gclass.value[6], gclass.value[7], min_width, min_height, graph.room_x[i], graph.room_y[i], graph.room_width[i], graph.room_height[i],
                            gclass.value[2], enc_mat
                        )
                        input_path = "input_to_min_dim.json"
                        json_data = json.dumps(floorplan_data, indent=2)
                        with open(input_path, 'w') as json_file:
                            json_file.write(json_data)
                        print(f"JSON data has been written to {input_path}")

                        # If floorplan satisfying the given constraints is satisfied
                        if min_dim.main(input_path, plot_width, plot_height):
                            output_path = "output_from_min_dim.json"
                            with open(output_path, 'r') as file:
                                json_content = json.load(file)
                            
                            room_x = [] 
                            room_y = [] 
                            room_width = [] 
                            room_height = [] 
                            room_area = []
                            room_name = []
                            for room_detail in json_content["nodes"]:
                                room_x.append(room_detail["room_x"])
                                room_y.append(room_detail["room_y"])
                                room_width.append(room_detail["width"])
                                room_height.append(room_detail["height"])
                                room_area.append(room_detail["width"] * room_detail["height"])

                            # Store the room labels if they have been entered
                            for room_id in range(len(json_content["nodes"])):
                                if "label" not in json_content["nodes"][room_id]:
                                    room_name.append(str(room_id))
                                else:
                                    room_name.append(json_content["nodes"][room_id]["label"])
                            
                            room_x = np.array(room_x)
                            room_y = np.array(room_y)
                            room_width = np.array(room_width)
                            room_height = np.array(room_height)
                            
                            graph_data = {
                                'room_x': room_x,
                                'room_y': room_y,
                                'room_width': room_width,
                                'room_height': room_height,
                                'area': room_area,
                                'extranodes': graph.extranodes,
                                'mergednodes': graph.mergednodes,
                                'irreg_nodes': graph.irreg_nodes1
                            }
                            
                            '''
                            Adds the graph data to output_data for downloading the catalogue and 
                            multiple_output_found flag is set which indicates that catalogue can be downloaded for this output
                            '''
                            gclass.output_data.append(graph_data)
                            gclass.multiple_output_found = 1
                            
                            delete_file(input_path)
                            delete_file(output_path)
                            floorplan_found = True

                            # If optimal area not required, display floorplan
                            if optimal_floorplan == 0:
                                draw.draw_rdg(graph_data
                                            , 1
                                            , gclass.pen
                                            , 1
                                            , gclass.value[6]
                                            , room_name
                                            , origin)
                                break

                            # Store graph data if graph area is less than current minimal area
                            area_sum = sum(room_area)
                            areas.append(area_sum)
                            if min_area < 0 or area_sum < min_area:
                                min_area = area_sum
                                min_graph_data = graph_data
                            
                        else:
                            delete_file(input_path)
                    if not floorplan_found:
                        print("No floorplan found which satisfies the minimum dimensions input by user.")
                    
                    # Display floorplan with optimal area if required
                    elif optimal_floorplan == 1:
                        print("Floorplan Areas Possible:", areas, "\nOptimal Area:", min_area)
                        draw.draw_rdg(min_graph_data
                                    , 1
                                    , gclass.pen
                                    , 1
                                    , gclass.value[6]
                                    , room_name
                                    , origin)

                    end = time.time()
                    printe("Time taken: " + str((end - start) * 1000) + " ms")

                    # Sets the ptpg object to the current graph to use for download catalogue and also stores the dimensional constraints of the graph
                    gclass.ptpg = graph
                    gclass.dimensional_constraints = [min_width, min_height, plot_width, plot_height]
                    
            elif (gclass.command == "multiple_oc"):
                if (gclass.value[4] == 0 and gclass.value[10] == 0):  # Non-Dimensioned multiple dual
                    start = time.time()
                    try:
                        graph.oneconnected_dual("multiple")
                    except inputgraph.OCError:
                        gclass.show_warning("Can not generate rectangular floorplan.")
                        graph.irreg_multiple_dual()
                    except inputgraph.BCNError:
                        graph.irreg_multiple_dual()
                    end = time.time()
                    printe("Average Time taken: " + str(((end - start) * 1000) / graph.fpcnt) + " ms")
                    printe("Number of floorplans: " + str(graph.fpcnt))
                    gclass.multiple_output_found = 1

                    for idx in range(graph.fpcnt):
                        graph_data = {
                            'room_x': graph.room_x[idx],
                            'room_y': graph.room_y[idx],
                            'room_width': graph.room_width[idx],
                            'room_height': graph.room_height[idx],
                            'area': graph.area,
                            'extranodes': graph.extranodes[idx],
                            'mergednodes': graph.mergednodes[idx],
                            'irreg_nodes': graph.irreg_nodes1[idx]
                        }
                        gclass.output_data.append(graph_data)
                        # draw.draw_rdg(graph_data
                        #     ,idx+1
                        #     ,gclass.pen
                        #     ,1
                        #     ,gclass.value[6]
                        #     ,[]
                        #     ,origin)
                        # gclass.ocan.add_tab()
                        # gclass.pen = gclass.ocan.getpen()
                        # gclass.pen.speed(0)
                elif (gclass.value[10] == 1): # Minimum dimensioned rectangular floorplans
                    old_dims = [[3] * gclass.value[0]
                        , [3] * gclass.value[0]]
                    min_width, min_height, plot_width, plot_height, optimal_floorplan = mindimgui.gui_fnc(old_dims, gclass.value[0], gclass.value[5])
                    start = time.time()
                    try:
                        graph.oneconnected_dual("multiple")
                    except inputgraph.OCError:
                        gclass.show_warning("Can not generate rectangular floorplan.")
                        graph.irreg_multiple_dual()
                    except inputgraph.BCNError:
                        graph.irreg_multiple_dual()
                    number_of_floorplans = graph.fpcnt
                    floorplan_found = False

                    # Resets the data already present for downloading catalogues
                    gclass.output_data = []
                    gclass.multiple_output_found = 0
                    
                    # Iterate through all possible floorplans to find one which satisfies the given conditions
                    for i in range(number_of_floorplans):
                        print("Trying floorplan number", i + 1, "to see if minimum dimension floorplan can be constructed.")
                        floorplan_obj = input_for_min_dim.floorplan(gclass.value[3], gclass.value[4],
                                                            gclass.value[8], gclass.value[9], gclass.corridor_thickness)
                        enc_mat = get_encoded_matrix(gclass.value[0], graph.room_x[i], graph.room_y[i], graph.room_width[i], graph.room_height[i])
                        floorplan_data = floorplan_obj.get_floorplan_details(
                            gclass.value[5], gclass.value[6], gclass.value[7], min_width, min_height, graph.room_x[i], graph.room_y[i], graph.room_width[i], graph.room_height[i],
                            gclass.value[2], enc_mat
                        )
                        input_path = "input_to_min_dim.json"
                        json_data = json.dumps(floorplan_data, indent=2)
                        with open(input_path, 'w') as json_file:
                            json_file.write(json_data)
                        print(f"JSON data has been written to {input_path}")

                        # If floorplan satisfying the given constraints is satisfied
                        if min_dim.main(input_path, plot_width, plot_height):
                            output_path = "output_from_min_dim.json"
                            with open(output_path, 'r') as file:
                                json_content = json.load(file)
                            
                            room_x = [] 
                            room_y = [] 
                            room_width = [] 
                            room_height = [] 
                            room_area = []
                            room_name = []
                            for room_detail in json_content["nodes"]:
                                room_x.append(room_detail["room_x"])
                                room_y.append(room_detail["room_y"])
                                room_width.append(room_detail["width"])
                                room_height.append(room_detail["height"])
                                room_area.append(room_detail["width"] * room_detail["height"])

                            # Store the room labels if they have been entered
                            for room_id in range(len(json_content["nodes"])):
                                if "label" not in json_content["nodes"][room_id]:
                                    room_name.append(str(room_id))
                                else:
                                    room_name.append(json_content["nodes"][room_id]["label"])
                            
                            room_x = np.array(room_x)
                            room_y = np.array(room_y)
                            room_width = np.array(room_width)
                            room_height = np.array(room_height)
                            
                            graph_data = {
                                'room_x': room_x,
                                'room_y': room_y,
                                'room_width': room_width,
                                'room_height': room_height,
                                'area': room_area,
                                'extranodes': graph.extranodes,
                                'mergednodes': graph.mergednodes,
                                'irreg_nodes': graph.irreg_nodes1
                            }
                            
                            '''
                            Adds the graph data to output_data for downloading the catalogue and 
                            multiple_output_found flag is set which indicates that catalogue can be downloaded for this output
                            '''
                            gclass.output_data.append(graph_data)
                            gclass.multiple_output_found = 1
                            
                            delete_file(input_path)
                            delete_file(output_path)
                            floorplan_found = True

                            draw.draw_rdg(graph_data
                                        , 1
                                        , gclass.pen
                                        , 1
                                        , gclass.value[6]
                                        , room_name
                                        , origin)
                            gclass.ocan.add_tab()
                            gclass.pen = gclass.ocan.getpen()
                            gclass.pen.speed(0)
                        else:
                            delete_file(input_path)
                    if not floorplan_found:
                        print("No floorplan found which satisfies the minimum dimensions input by user.")

                    end = time.time()
                    printe("Time taken: " + str((end - start) * 1000) + " ms")

                    # Sets the ptpg object to the current graph to use for download catalogue and also stores the dimensional constraints of the graph
                    gclass.ptpg = graph
                    gclass.dimensional_constraints = [min_width, min_height, plot_width, plot_height]
                else:
                    old_dims = [[0] * gclass.value[0]
                        , [0] * gclass.value[0]
                        , [0] * gclass.value[0]
                        , [0] * gclass.value[0]
                        , ""
                        , [0] * gclass.value[0]
                        , [0] * gclass.value[0]]
                    min_width, max_width, min_height, max_height, symm_string, min_aspect, max_aspect, plot_width, plot_height = dimgui.gui_fnc(
                        old_dims, gclass.value[0], gclass.value[5])
                    dimensional_constraints = [min_width, max_width, min_height, max_height, symm_string, min_aspect,
                                            max_aspect, plot_width, plot_height]
                    start = time.time()
                    try:
                        graph.oneconnected_dual("multiple")
                    except inputgraph.OCError:
                        gclass.show_warning("Can not generate rectangular floorplan.")
                        graph.irreg_multiple_dual()
                    except inputgraph.BCNError:
                        graph.irreg_multiple_dual()
                    graph.multiple_floorplan(min_width, min_height, max_width, max_height, symm_string, min_aspect,
                                            max_aspect, plot_width, plot_height)
                    end = time.time()
                    printe("Time taken: " + str((end - start) * 1000) + " ms")
                    printe("Number of floorplans: " + str(len(graph.room_x)))
                    gclass.multiple_output_found = 1

                    room_name = []
                    if len(gclass.value[5]) > 0:
                        room_name = gclass.value[5]

                    for idx in range(len(graph.room_x)):
                        graph_data = {
                            'room_x': graph.room_x[idx],
                            'room_y': graph.room_y[idx],
                            'room_width': graph.room_width[idx],
                            'room_height': graph.room_height[idx],
                            'area': graph.area[idx],
                            'extranodes': graph.extranodes[idx],
                            'mergednodes': graph.mergednodes[idx],
                            'irreg_nodes': graph.irreg_nodes1[idx]
                        }
                        gclass.output_data.append(graph_data)
                        gclass.dimensional_constraints = dimensional_constraints
                        gclass.ptpg = graph
                        print_all_rfp = False
                        if print_all_rfp == True:
                            gclass.ocan.add_tab()
                            gclass.pen = gclass.ocan.getpen()
                            gclass.pen.speed(0)
                            draw.draw_rdg(graph_data
                                ,1
                                ,gclass.pen
                                ,1
                                ,gclass.value[6]
                                ,room_name
                                ,origin)
            elif (gclass.command == "poly"):  # Polygonal Floorplan
                start = time.time()
                # graph.irreg_single_dual()
                graph.polyonalinput(gclass.canonicalObject, gclass.v1, gclass.v2, gclass.vn, gclass.po, gclass.value[2],
                                    gclass.debugcano)
                end = time.time()

                # printe("Time taken: " + str((end-start)*1000) + " ms")
                # graph_data = {
                #         'room_x': graph.room_x,
                #         'room_y': graph.room_y,
                #         'room_width': graph.room_width,
                #         'room_height': graph.room_height,
                #         'area': graph.area,
                #         'extranodes': graph.extranodes,
                #         'mergednodes': graph.mergednodes,
                #         'irreg_nodes': graph.irreg_nodes1
                #     }
                # gclass.output_data.append(graph_data)
                draw.draw_poly(gclass.canonicalObject.graph_data,1
                        ,gclass.pen
                        ,1
                        ,gclass.value[6]
                        ,[]
                        ,origin,gclass.outer_boundary, gclass.shape)
                
            elif (gclass.command == "door_connectivity"):  # Door Connectivity Floorplan
                start = time.time()
                graph.door_connectivity()
                end = time.time()
                printe("Time taken: " + str((end - start) * 1000) + " ms")
                graph_data = {
                    'room_x': graph.room_x,
                    'room_y': graph.room_y,
                    'room_width': graph.room_width,
                    'room_height': graph.room_height,
                    'area': graph.area,
                    'extranodes': graph.extranodes,
                    'mergednodes': graph.mergednodes,
                    'irreg_nodes': graph.irreg_nodes1
                }
                gclass.output_data.append(graph_data)
                draw.draw_rdg(graph_data
                                , 1
                                , gclass.pen
                                , 1
                                , gclass.value[6]
                                , []
                                , origin)

            gclass.time_taken = (end-start)*1000
            gclass.num_rfp = len(graph.room_x)
            gclass.pdf_colors = gclass.value[6][0]
            gclass.output_found = 1

        gclass.root.wait_variable(gclass.end)
        gclass.graph_ret()
        gclass.ocan.add_tab()
        gclass.pen = gclass.ocan.getpen()
        gclass.pen.speed(0)

        # gclass.ocan.tscreen.resetscreen()


def make_dissection_corridor(gclass):
    dis = nx.Graph()
    dis = nx.from_numpy_array(gclass.dclass.mat)
    m = len(dis)
    spanned = circulation.BFS(dis, gclass.e1.get(), gclass.e2.get())
    gclass.cir_dim_mat = nx.to_numpy_matrix(spanned)
    # colors = ['#4BC0D9','#76E5FC','#6457A6','#5C2751','#7D8491','#BBBE64','#64F58D','#9DFFF9','#AB4E68','#C4A287','#6F9283','#696D7D','#1B1F3B','#454ADE','#FB6376','#6C969D','#519872','#3B5249','#A4B494','#CCFF66','#FFC800','#FF8427','#0F7173','#EF8354','#795663','#AF5B5B','#667761','#CF5C36','#F0BCD4','#ADB2D3','#FF1B1C','#6A994E','#386641','#8B2635','#2E3532','#124E78']*10
    colors = ['#4BC0D9'] * 10
    rnames = []
    for i in range(1, m + 1):
        rnames.append('Room' + str(i))
    rnames.append("Corridor")
    for i in range(1, 10):
        colors[m + i - 1] = '#FF4C4C'
        rnames.append("")
    parameters = [len(spanned), spanned.size(), spanned.edges(), 0, 0, rnames, colors]
    C = ptpg.PTPG(parameters)
    C.create_single_dual(1, gclass.pen, gclass.textbox)
    gclass.ocan.add_cir_tab()
    gclass.dclass.add_cir()


# def make_graph_circulation(G,gclass):
#     m =len(G.graph)
#     spanned = circulation.BFS(G.graph,1,2)
#     # plotter.plot(spanned,m)
#     colors= gclass.value[6].copy()
#     for i in range(0,100):
#         colors.append('#FF4C4C')
#     # print(colors)
#     rnames = G.room_names
#     rnames.append("Corridor")
#     for i in range(0,100):
#         rnames.append("")
#     # print(rnames)

#     parameters= [len(spanned), spanned.size() , spanned.edges() , 0,0 ,rnames,colors]
#     C = ptpg.PTPG(parameters)
#     # C.create_single_dual(1,gclass.pen,gclass.textbox)
#     G.create_circulation_dual(1,gclass.pen,gclass.textbox)
#     # draw.draw_rdg(G,1,gclass.pen,G.to_be_merged_vertices,G.rdg_vertices,0,gclass.value[6],gclass.value[5])
#     G.circulation(gclass.pen,gclass.ocan.canvas, C, 1, 2)


# def call_circulation(graph_data, edge_set, entry):
def call_circulation(graph_data, gclass, coord, is_dimensioned, dim_constraints, remove_corridor):

    g = nx.Graph()
    edge_set = gclass.value[2]
    entry = gclass.entry_door

    for x in edge_set:
        g.add_edge(x[0], x[1])
    
    n = len(g)

    rooms = []
    for i in range(n):
        rooms.append(cir.Room(i, graph_data.get("room_x")[i], graph_data.get("room_y")[i] + graph_data.get("room_height")[i], graph_data.get("room_x")[i] + graph_data.get("room_width")[i], graph_data.get("room_y")[i]))

    
    rfp = cir.RFP(g, rooms)

    cir.plot(g,n)
    circulation_obj = cir.circulation(g, gclass.corridor_thickness, rfp, gclass.rem)
    
    # Add dimensional constraints if chosen option is "dimensioned circulation"
    if is_dimensioned == True:
        circulation_obj.is_dimensioned = True
        circulation_obj.dimension_constraints = dim_constraints
    
    # Apply circulation algorithm
    circulation_result = circulation_obj.circulation_algorithm(entry[0],entry[1])
    cir.plot(circulation_obj.circulation_graph, len(circulation_obj.circulation_graph))
    if circulation_result == 0:
        return None
    
    if remove_corridor == True:
        # Created a deepcopy of object to display circulation before
        # we display GUI for removing corridor
        circ = copy.deepcopy(circulation_obj)
        circ.adjust_RFP_to_circulation()

        # Printing how much shift was done for each room
        print("\t\tT\tB\t\L\tR\t\tTarget")
        for room in circ.RFP.rooms:
            print(f"{room.id}\t{room.rel_push_T}\t{room.rel_push_B}\t{room.rel_push_L}\t{room.rel_push_R}\t\t{room.target}")
            # print("Room ",room.id, ":")
            # print("Push top edge by: ", room.rel_push_T)
            # print("Push bottom edge by: ", room.rel_push_B)
            # print("Push left edge by: ", room.rel_push_L)
            # print("Push right edge by: ", room.rel_push_R)
            # print(room.target)
            # print('\n')

        room_x1 = []
        room_y1 = []
        room_height1 = []
        room_width1 = []

        # Getting the required values
        for room in circ.RFP.rooms:
            room_x1.append(room.top_left_x)
            room_y1.append(room.bottom_right_y)
            room_height1.append(abs(room.top_left_y - room.bottom_right_y))
            room_width1.append(abs(room.top_left_x - room.bottom_right_x))

        graph_data1 = {}
        graph_data1['room_x'] = np.array(room_x1)
        graph_data1['room_y'] = np.array(room_y1)
        graph_data1['room_height'] = np.array(room_height1)
        graph_data1['room_width'] = np.array(room_width1)
        graph_data1['area'] = np.array(circulation_obj.room_area)
        graph_data1['extranodes'] = graph_data['extranodes']
        graph_data1['mergednodes'] = graph_data['mergednodes']
        graph_data1['irreg_nodes'] = graph_data['irreg_nodes']
        draw.draw_rdg(graph_data1, 1, gclass.pen, 1, gclass.value[6], [], origin)

        # Now going back to flow of removing circulation
        corridors = circulation_obj.adjacency
        rem_edges = gclass.remove_corridor_gui(corridors)

        for x in rem_edges:
            circulation_obj.remove_corridor(circulation_obj.circulation_graph,x[0],x[1])
        
        
    # To remove entry corridor alone we are just shifting rooms by looking at second corridor vertex
    # Done by shifting the range left bound in for loop of adjust_RFP_to_circulation()
    circulation_obj.adjust_RFP_to_circulation()

    # Printing how much shift was done for each room
    print("\tT\tB\tL\tR")
    for room in circulation_obj.RFP.rooms:
        print(f"{room.id}\t{room.rel_push_T}\t{room.rel_push_B}\t{room.rel_push_L}\t{room.rel_push_R}")
        # print("Room ",room.id, ":")
        # print("Push top edge by: ", room.rel_push_T)
        # print("Push bottom edge by: ", room.rel_push_B)
        # print("Push left edge by: ", room.rel_push_L)
        # print("Push right edge by: ", room.rel_push_R)
        # print(room.target)
        # print('\n')

    room_x = []
    room_y = []
    room_height = []
    room_width = []

    # Getting the required values
    for room in circulation_obj.RFP.rooms:
        room_x.append(room.top_left_x)
        room_y.append(room.bottom_right_y)
        room_height.append(abs(room.top_left_y - room.bottom_right_y))
        room_width.append(abs(room.top_left_x - room.bottom_right_x))

    graph_data['room_x'] = np.array(room_x)
    graph_data['room_y'] = np.array(room_y)
    graph_data['room_height'] = np.array(room_height)
    graph_data['room_width'] = np.array(room_width)
    graph_data['area'] = np.array(circulation_obj.room_area)
    return (graph_data, circulation_obj.is_dimensioning_successful)

def plot(graph: nx.Graph,m: int) -> None:
    """Plots thr graph using matplotlib

    Args:
        graph (Networkx graph): The graph to plot
        m (integer): Number of vertices in the graph
    """
    pos=nx.spring_layout(graph) # positions for all nodes
    nx.draw_networkx(graph,pos, label=None,node_size=400 ,node_color='#4b8bc8',font_size=12, font_color='k', font_family='sans-serif', font_weight='normal', alpha=1, bbox=None, ax=None)
    nx.draw_networkx_edges(graph,pos)
    nx.draw_networkx_nodes(graph,pos,
                        nodelist=list(range(m,len(graph))),
                        node_color='r',
                        node_size=500,
                    alpha=1)
    plt.show()

# def draw_circulation(graph_data, canvas, color_list,entry):
def draw_circulation(graph_data, pen, canvas, color_list):
    """This is the draw function specifically for the circulation module

    Args:
        graph_data (dict): Contains the room coordinates, dimensions, area, etc.
        pen (output_canvas class in gui.py): To write area of each room
        canvas (output_canvas class in gui.py): To draw the rooms
        color_list (list): Color of each room
    """
    
    origin_x, origin_y = -200,-100
    scale = 50
    room_x = graph_data["room_x"]
    room_y = graph_data["room_y"]
    room_height = graph_data["room_height"]
    room_width = graph_data["room_width"]
    for i in range(len(room_x)):
        canvas.create_rectangle(origin_x + scale*room_x[i], origin_y + scale*room_y[i], origin_x + scale*(room_x[i] + room_width[i]), origin_y + scale*(room_y[i] + room_height[i]), fill = color_list[i])
        canvas.create_text(origin_x + scale*(room_x[i] + room_width[i]/2), origin_y + scale*(room_y[i] + room_height[i]/2), text = str(i))
    
    # Printing dimensions in case it is dimensioned
    # Gets the max x coordinate (rightmost end of floorplan)
    x_max = np.max(graph_data['room_x']) + graph_data['room_width'][np.argmax(graph_data['room_x'])]
    # Gets the max y coordinate (topmost end of floorplan)
    y_max = np.max(graph_data['room_y'])



    value = 1 # variable to write next area in next line
    pen.penup()
    if(len(graph_data['area']) != 0):
        pen.setposition(x_max* scale + origin_x + 50, y_max* scale + origin_y - 30)
        pen.write('Dimensions of Each Room' ,font=("Arial", 20, "normal"))
        for i in range(0,len(graph_data['area'])):
            if i in graph_data['extranodes']:
                continue
            pen.setposition(x_max* scale + origin_x+50, y_max* scale + origin_y - 30 - value*30)
            pen.write('Room ' + str(i)+ ': Width= '+ str(round(graph_data['room_width'][i],1)) + ' Height= ' + str(round(graph_data['room_height'][i], 1)),font=("Arial", 15, "normal"))
            pen.penup()
            # Moving pen to next line
            value+=1

    # draw door
    # print("Entry: ", entry)

if __name__ == "__main__":
    run()
