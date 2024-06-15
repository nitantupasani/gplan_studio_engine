import GPLAN.source.polygonal.poly as poly
import GPLAN.input.input_for_min_dim as input_for_min_dim
import json
# from system_functions.os_functions import delete_fileimport input.input_for_min_dim as input_for_min_dim
from GPLAN.source.graphoperations.operations import get_encoded_matrix
from GPLAN.system_functions.os_functions import delete_file
import GPLAN.source.dimensioning.minimum_dimensioning as min_dim
import GPLAN.source.lettershape.lshape.Lshaped as Lshaped
import GPLAN.source.lettershape.tshape.tshape as Tshaped
import GPLAN.source.lettershape.ushape.ushape as Ushaped
import GPLAN.source.lettershape.zshape.zshape as Zshaped
import GPLAN.source.polygonal.limits as lim
import GPLAN.source.polygonal.newcoord as nc
import GPLAN.pythongui.dimensiongui as dimgui
import GPLAN.pythongui.mindimensiongui as mindimgui
import time
from tkinter import messagebox
import networkx as nx
import numpy as np
import GPLAN.pythongui.gui as gui
import GPLAN.source.inputgraph as inputgraph
import GPLAN.pythongui.drawing as draw
import GPLAN.circulation as cir
import matplotlib.pyplot as plt
import copy

origin = 0

def drawFunction(ui ,graph, origin, roomName, isPoly = False, gclass = None):
    if not isPoly:
        draw.draw_rdg(graph
                    , 1
                    , gclass.pen
                    , 1
                    , ui.get_roomColors()
                    , roomName
                    , origin)
    else:
        draw.draw_poly(gclass.canonicalObject.graph_data,1
            ,gclass.pen
            ,1
            ,ui.get_roomColors()
            ,[]
            ,origin,gclass.outer_boundary, gclass.shape,graph.matrix)
            
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


def call_circulation(ui, graph, gclass, coord, is_dimensioned, dim_constraints, remove_corridor,public_private, drawGUI):

    g = nx.Graph()
    edge_set = ui.get_edges()
    entry = gclass.entry_door

    for x in edge_set:
        g.add_edge(x[0], x[1])
    
    n = len(g)

    rooms = []
    for i in range(n):
        rooms.append(cir.Room(i, graph.room_x[i], graph.room_y[i] + graph.room_height[i], graph.room_x[i] + graph.room_width[i], graph.room_y[i]))

    
    rfp = cir.RFP(g, rooms)

    cir.plot(g,n)
    circulation_obj = cir.circulation(g, ui.get_corridor_thickness(), rfp, gclass.rem)
    
    # Add dimensional constraints if chosen option is "dimensioned circulation"
    if is_dimensioned == True:
        circulation_obj.is_dimensioned = True
        circulation_obj.dimension_constraints = dim_constraints
    
    # Apply circulation algorithm
    circulation_result = circulation_obj.circulation_algorithm(entry[0],entry[1])
    cir.plot(circulation_obj.circulation_graph, len(circulation_obj.circulation_graph))
    if circulation_result == 0:
        return None
    if public_private == True:
        circ = copy.deepcopy(circulation_obj)
        circ.adjust_RFP_to_circulation()

        # Printing how much shift was done for each room
        for room in circ.RFP.rooms:
            print("Room ",room.id, ":")
            print("Push top edge by: ", room.rel_push_T)
            print("Push bottom edge by: ", room.rel_push_B)
            print("Push left edge by: ", room.rel_push_L)
            print("Push right edge by: ", room.rel_push_R)
            print(room.target)
            print('\n')

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

        new_graph=copy.deepcopy(graph)
        new_graph.room_x=room_x1
        new_graph.room_y=room_y1
        new_graph.room_height=room_height1
        new_graph.room_width=room_width1
        new_graph.final_traversal=inputgraph.get_final_traversal(new_graph)
        if drawGUI:
            drawFunction(ui, new_graph, origin, [], gclass = gclass)

        # Now going back to flow of removing circulation
        corridors = circulation_obj.adjacency
        rem_edges = gclass.public_rooms(corridors)

        for x in rem_edges:
            circulation_obj.remove_corridor(circulation_obj.circulation_graph,x[0],x[1])
    
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

        new_graph=copy.deepcopy(graph)
        new_graph.room_x=room_x1
        new_graph.room_y=room_y1
        new_graph.room_height=room_height1
        new_graph.room_width=room_width1

        new_graph.final_traversal=inputgraph.get_final_traversal(new_graph)
        if drawGUI:
            drawFunction(ui, new_graph, origin, [], gclass = gclass)

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

    graph.room_x=room_x
    graph.room_y=room_y
    graph.room_height=room_height
    graph.room_width=room_width
    graph.area=circulation_obj.room_area
    return (graph, circulation_obj.is_dimensioning_successful)


def handle_circulation(ui, graph, drawGUI = False, gclass = None):
    is_dimensioned = False
    remove_corridor = False
    public_private = False
    node_coord = graph.coordinates
    dim_constraints = []
    if (ui.get_isDimensionedCirculation() == 0 and ui.get_isRemoveAddCirculation() == 0 and ui.get_isPublic()==0): #Non-dimensioned single circulation
        start = time.time()
        graph.irreg_single_dual()
        ui.print_gui('Generated Single Irregular floorplan with Circulation')
        end = time.time()
        ui.print_gui("Time taken: " + str((end-start)*1000) + " ms")
        print("type of roomx " + str(type(graph.room_x)))
        (new_graph, success) = call_circulation(ui, graph, gclass, node_coord, is_dimensioned, dim_constraints, remove_corridor,public_private,drawGUI) 
        # If there was some error in algorithm execution new_graph will be empty
        # we display the pop-up error message
        if new_graph == None:
            messagebox.showerror("Error", "ERROR!! THE INITIAL CHOSEN ENTRY EDGE MUST BE EXTERIOR EDGE")
        # If no issues we continue to draw the corridor
        else :
            graph.final_traversal = inputgraph.get_final_traversal(graph)
            if drawGUI:
                drawFunction(ui, new_graph, origin, [], gclass = gclass)
        
    elif(ui.get_isDimensionedCirculation() == 1 and ui.get_isRemoveAddCirculation() == 0 and ui.get_isPublic()==0): #Dimensioned single circulation
        is_dimensioned = True
        feasible_dim = 0
        old_dims = [[0] * ui.get_noOfNodes()
                    , [0] * ui.get_noOfNodes()
                    , [0] * ui.get_noOfNodes()
                    , [0] * ui.get_noOfNodes()
                    , ""
                    , [0] * ui.get_noOfNodes()
                    , [0] * ui.get_noOfNodes()]
        min_width,max_width,min_height,max_height, symm_string, min_aspect, max_aspect, plot_width, plot_height  = dimgui.gui_fnc(old_dims, ui.get_noOfNodes())
        dimensional_constraints = [min_width,max_width,min_height,max_height, symm_string, min_aspect, max_aspect, plot_width, plot_height]
        start = time.time()
        try:
            graph.oneconnected_dual("multiple")
            ui.print_gui('Generated Dimensioned Multiple Rectangular floorplan with Circulation')        
        except inputgraph.OCError:
            show_warning("Can not generate rectangular floorplan.")
            graph.irreg_multiple_dual()
            ui.print_gui('Generated Dimensioned Multiple Irregular floorplan instead of Rectangular with Circulation. OCERROR')

            
        except inputgraph.BCNError:
            graph.irreg_multiple_dual()
            ui.print_gui('Generated Dimensioned Multiple Irregular floorplan instead of Rectangular with Circulation. BCNError')
        
        graph.single_floorplan(min_width,min_height,max_width,max_height,symm_string, min_aspect, max_aspect, plot_width, plot_height)
        while(graph.floorplan_exist == False):
            old_dims = [min_width, max_width, min_height, max_height, symm_string, min_aspect, max_aspect]
            min_width,max_width,min_height,max_height, symm_string, min_aspect, max_aspect, plot_width, plot_height  = dimgui.gui_fnc(old_dims, ui.get_noOfNodes())
            graph.irreg_multiple_dual()
            graph.single_floorplan(min_width,min_height,max_width,max_height,symm_string, min_aspect, max_aspect, plot_width, plot_height)
        end = time.time()
        ui.print_gui("Time taken: " + str((end-start)*1000) + " ms")
        
            
        dim_constraints = [min_width, max_width, min_height, max_height, min_aspect, max_aspect]
        (new_graph, success) = call_circulation(ui, graph, gclass, node_coord, is_dimensioned, dim_constraints, remove_corridor, public_private,drawGUI)# type: ignore
        print("Constraints: ", dim_constraints)
        print("New graph data: ", new_graph)
        print("success: ", success)                        
        # If there was some error in algorithm execution new_graph will be empty
        # we display the pop-up error message
        if new_graph == None:
            messagebox.showerror("Error", "ERROR!! THE INITIAL CHOSEN ENTRY EDGE MUST BE EXTERIOR EDGE")
        # If no issues we continue to draw the corridor
        else :
            if (success == False):
                return
            new_graph.final_traversal=inputgraph.get_final_traversal(new_graph)
            if drawGUI:
                drawFunction(ui, new_graph, origin, [], gclass = gclass)
            feasible_dim = 1
            return
        if(feasible_dim == 0):
            messagebox.showerror("Error", "ERROR!! NO CIRCULATION POSSIBLE FOR GIVEN DIMENSIONS")
    
    elif(ui.get_isDimensionedCirculation() == 0 and ui.get_isRemoveAddCirculation() == 1 and ui.get_isPublic()==0): # Add/remove
        remove_corridor = True
        start = time.time()
        graph.irreg_single_dual()
        ui.print_gui('Generated Single Irregular floorplan with Circulation. Remove/Add Circulation:Enabled and Public: disabled')
        end = time.time()
        ui.print_gui("Time taken: " + str((end-start)*1000) + " ms")
        print("type of roomx " + str(type(graph.room_x)))
        
        (new_graph, success) = call_circulation(ui, graph, gclass, node_coord, is_dimensioned, dim_constraints, remove_corridor, public_private,drawGUI) # type: ignore
        
        # If there was some error in algorithm execution new_graph will be empty
        # we display the pop-up error message
        if new_graph == None:
            messagebox.showerror("Error", "ERROR!! THE INITIAL CHOSEN ENTRY EDGE MUST BE EXTERIOR EDGE")
        
        # If no issues we continue to draw the corridor
        else :
            if drawGUI:
                drawFunction(ui, new_graph, origin, [], gclass = gclass)
    elif(ui.get_isDimensionedCirculation() == 0 and ui.get_isPublic() == 1):
        public_private = True
        start = time.time()
        graph.irreg_single_dual()
        ui.print_gui('Generated Single Irregular floorplan with Circulation. Dimensioned: Disabled and Public: Enabled')
        end = time.time()
        ui.print_gui("Time taken: " + str((end-start)*1000) + " ms")

        (new_graph, success) = call_circulation(ui, graph, gclass, node_coord, is_dimensioned, dim_constraints, remove_corridor,public_private,drawGUI) # type: ignore

        # If there was some error in algorithm execution new_graph will be empty
        # we display the pop-up error message
        if new_graph == None:
            messagebox.showerror("Error", "ERROR!! THE INITIAL CHOSEN ENTRY EDGE MUST BE EXTERIOR EDGE")
        
        # If no issues we continue to draw the corridor
        else :
            new_graph.final_traversal=inputgraph.get_final_traversal(new_graph)
            if drawGUI:
                drawFunction(ui, new_graph, origin-300, [], gclass = gclass)

def handle_single(ui, graph, drawGUI = False, gclass = None):
    if (ui.get_isDimensioned() == 0):  # Non-Dimensioned single dual
        start = time.time()
        graph.irreg_single_dual()
        ui.print_gui('Generated Single Irregular floorplan')
        end = time.time()
        ui.print_gui("Time taken: " + str((end - start) * 1000) + " ms")
        ui._append_output_data(graph) 
        graph.final_traversal=inputgraph.get_final_traversal(graph)
        if drawGUI:
            drawFunction(ui, graph, origin, [], gclass = gclass)
    else:  # Dimensioned single floorplan
        old_dims = [[0] * ui.get_noOfNodes()
            , [0] * ui.get_noOfNodes()
            , [0] * ui.get_noOfNodes()
            , [0] * ui.get_noOfNodes()
            , ""
            , [0] * ui.get_noOfNodes()
            , [0] * ui.get_noOfNodes()]
        min_width, max_width, min_height, max_height, symm_string, min_aspect, max_aspect, plot_width, plot_height = dimgui.gui_fnc(
            old_dims, ui.get_noOfNodes())
        dimensional_constraints = [min_width, max_width, min_height, max_height, symm_string, min_aspect,
                                    max_aspect, plot_width, plot_height]
        ui._set_dim_constraints(dimensional_constraints)
        start = time.time()
        graph.irreg_multiple_dual()
        graph.single_floorplan(min_width,min_height,max_width,max_height,symm_string, min_aspect, max_aspect, plot_width, plot_height)
        while(graph.floorplan_exist == False):
            old_dims = [min_width, max_width, min_height, max_height, symm_string, min_aspect, max_aspect]
            min_width,max_width,min_height,max_height, symm_string, min_aspect, max_aspect, plot_width, plot_height  = dimgui.gui_fnc(old_dims, ui.get_noOfNodes())
            graph.irreg_multiple_dual()
            graph.single_floorplan(min_width,min_height,max_width,max_height,symm_string, min_aspect, max_aspect, plot_width, plot_height)
        end = time.time()
        ui.print_gui("Time taken: " + str((end-start)*1000) + " ms")
        graph.final_traversal = inputgraph.get_final_traversal(graph)
        if drawGUI:
            drawFunction(ui, graph, origin, [], gclass = gclass)

def handle_letter_shape(ui, graph, drawGUI = False, gclass = None, nodes_data = None):
    assert ui.get_letter is not None
    node_data = nodes_data if nodes_data is not None else gclass.app.nodes_data 
    if(ui.get_isDimensioned() == 0): #Non-Dimensioned Letter Shape
        start = time.time()
        if(ui.get_letter() == "L Shape"):
            Lshaped.LShapedFloorplan(graph, nodes_data)
        elif(ui.get_letter() == "T Shape"):
            Tshaped.TShapedFloorplan(graph)
        elif(ui.get_letter() == "Z Shape"):
            Zshaped.ZShapedFloorplan(graph)
        elif(ui.get_letter() == "U Shape"):
            Ushaped.UShapedFloorplan(graph)
        end = time.time()
        print("REL MATRIX \n", graph.matrix)
        graph.final_traversal=inputgraph.get_final_traversal(graph)
        if drawGUI:
            drawFunction(ui, graph, origin, [], gclass = gclass)
    else:
        old_dims = [[0] * ui.get_noOfNodes()
            , [0] * ui.get_noOfNodes()
            , [0] * ui.get_noOfNodes()
            , [0] * ui.get_noOfNodes()
            , ""
            , [0] * ui.get_noOfNodes()
            , [0] * ui.get_noOfNodes()]
        min_width, max_width, min_height, max_height, symm_string, min_aspect, max_aspect, plot_width, plot_height = dimgui.gui_fnc(
            old_dims, ui.get_noOfNodes())
        start = time.time()   
        if(ui.get_letter() == "L Shape"):
            Lshaped.LShapedFloorplan(graph, gclass.app.nodes_data)
        # elif(ui.get_letter() == "T Shape"):
        #     Tshaped.TShapedFloorplan(graph)
        # elif(ui.get_letter() == "Z Shape"):
        #     Zshaped.ZShapedFloorplan(graph)
        # elif(ui.get_letter() == "U Shape"):
            Ushaped.UShapedFloorplan(graph)
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
        ui.print_gui("Time taken: " + str((end - start) * 1000) + " ms") 
        graph.final_traversal=inputgraph.get_final_traversal(graph)
        if drawGUI:
            drawFunction(ui, graph, origin, [], gclass = gclass)

def handle_multiple_l(ui, graph, gclass = None, nodes_data = None):
    node_data = nodes_data if nodes_data is not None else gclass.app.nodes_data 
    if(ui.get_isDimensioned() == 0):#Non-Dimensioned multiple dual
        start = time.time()
        Lshaped.multipleLshapedFloorplans(graph, nodes_data)
        end = time.time()
        ui.print_gui("Average Time taken: " + str(((end - start) * 1000) / graph.fpcnt) + " ms")
        ui.print_gui("Number of floorplans: " + str(graph.fpcnt))

        for idx in range(graph.fpcnt):
            graph_new = graph.graph_list[idx]
            ui._set_multiple_output_found(1)
            graph_new.final_traversal = inputgraph.get_final_traversal(graph_new)
            gclass.output_data.append(graph_new)
            # draw.draw_rdg(graph_new
            #     ,idx+1
            #     ,gclass.pen
            #     ,1
            #     ,ui.get_roomColors()
            #     ,[]
            #     ,origin)
            # # origin += 1000
            # gclass.ocan.add_tab()
            # gclass.pen = gclass.ocan.getpen()
            # gclass.pen.speed(0)
    
def handle_staircase_shaped(ui, graph, drawGUI = False, gclass = None):
    start = time.time()
    inputgraph.staircaseshaped(graph)
    end = time.time()
    graph.final_traversal=inputgraph.get_final_traversal(graph)
    if drawGUI:
        drawFunction(ui, graph, origin, [], gclass = gclass)
    return graph
    
def handle_multiple(ui, graph, gclass = None):
    if(ui.get_isDimensioned() == 0):#Non-Dimensioned multiple dual
        start = time.time()
        graph.irreg_multiple_dual()
        end = time.time()
        ui.print_gui("Average Time taken: " + str(((end - start) * 1000) / graph.fpcnt) + " ms")
        ui.print_gui("Number of floorplans: " + str(graph.fpcnt))
        ui._set_multiple_output_found(1)
        for idx in range(graph.fpcnt):
            graph_new = graph.graph_list[idx]
            ui._append_output_data(graph_new)
    else:#Dimensioned multiple floorplans
        old_dims = [[0] * ui.get_noOfNodes()
                    , [0] * ui.get_noOfNodes()
                    , [0] * ui.get_noOfNodes()
                    , [0] * ui.get_noOfNodes()
                    , ""
                    , [0] * ui.get_noOfNodes()
                    , [0] * ui.get_noOfNodes()]
        min_width,max_width,min_height,max_height, symm_string, min_aspect, max_aspect, plot_width, plot_height  = dimgui.gui_fnc(old_dims, ui.get_noOfNodes())
        start = time.time()
        graph.irreg_multiple_dual()
        graph.multiple_floorplan(min_width,min_height,max_width,max_height,symm_string, min_aspect, max_aspect, plot_width, plot_height)
        end = time.time()
        ui.print_gui("Time taken: " + str((end-start)*1000) + " ms")
        ui.print_gui("Number of floorplans: " +  str(len(graph.graph_list)))
        ui._set_multiple_output_found(1)
        for idx in range(len(graph.fpcnt)):
            graph_new = graph.graph_list[idx]
            ui._append_output_data(graph_new)

def handle_single_oc(ui, graph, drawGUI = False, gclass = None):
    if(ui.get_isDimensioned() == 0 and ui.get_isMinDimensioned() == 0): #Non-Dimensioned single rectangular dual
        start = time.time()
        try:
            graph.oneconnected_dual("single")
            ui.print_gui('Generated single rectangular floorplan')        
        except inputgraph.OCError:
            show_warning("Can not generate rectangular floorplan.")
            graph.irreg_single_dual()
            ui.print_gui('Generated Single Irregular floorplan instead of Rectangular. OCERROR')
        except inputgraph.BCNError:
            graph.irreg_single_dual()
            ui.print_gui('Generated Single Irregular floorplan instead of Rectangular. BCNERROR')
        
        temp_graph_data = {}
        temp_graph_data["nodecnt"] = ui.get_noOfNodes()
        temp_graph_data["edgecnt"] = ui.get_edgeCount()
        temp_graph_data["edgeset"] = ui.get_edges()
        temp_graph_data["node_coordinate"] = ui.get_nodeCoordinates()
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

        for key, value in graph_data.items():
            if isinstance(value, np.ndarray):
                temp_graph_data[key] = value.tolist()
            else:
                temp_graph_data[key] = value

        input_path = "./saved_files/input_to_limits.json"
        with open(input_path, 'w') as json_file:
            json_data = json.dump(temp_graph_data,json_file, indent=2)
        print(f"JSON data has been written to {input_path}")

        #min_dim.main(input_path)
        end = time.time()
        ui.print_gui("Time taken: " + str((end - start) * 1000) + " ms")
        room_name = []
        if len(ui.get_roomNames()) > 0:
            room_name = ui.get_roomNames()
        graph.final_traversal=inputgraph.get_final_traversal(graph)
        if drawGUI:
            drawFunction(ui, graph, origin, [], gclass = gclass)
    elif (ui.get_isDimensioned() == 1):  # Dimensioned single floorplan
        old_dims = [[0] * ui.get_noOfNodes()
            , [0] * ui.get_noOfNodes()
            , [0] * ui.get_noOfNodes()
            , [0] * ui.get_noOfNodes()
            , ""
            , [0] * ui.get_noOfNodes()
            , [0] * ui.get_noOfNodes()]
        min_width, max_width, min_height, max_height, symm_string, min_aspect, max_aspect, plot_width, plot_height = dimgui.gui_fnc(
            old_dims, ui.get_noOfNodes(), ui.get_roomNames())
        start = time.time()
        try:
            graph.oneconnected_dual("multiple")
            ui.print_gui('Generated single rectangular floorplan. Dimensioned')        
        except inputgraph.OCError:
            show_warning("Can not generate rectangular floorplan. Dimensioned")
            graph.irreg_multiple_dual()
            ui.print_gui('Generated Multiple Irregular floorplan instead of Rectangular. OCError')
        except inputgraph.BCNError:
            graph.irreg_multiple_dual()
            ui.print_gui('Generated Multiple Irregular floorplan instead of Rectangular. BCNError')
        graph.single_floorplan(min_width, min_height, max_width, max_height, symm_string, min_aspect,
                                max_aspect, plot_width, plot_height)
        while (graph.floorplan_exist == False):
            old_dims = [min_width, max_width, min_height, max_height, symm_string, min_aspect, max_aspect]
            min_width, max_width, min_height, max_height, symm_string, min_aspect, max_aspect, plot_width, plot_height = dimgui.gui_fnc(
                old_dims, ui.get_noOfNodes())
            graph.multiple_dual()
            graph.single_floorplan(min_width, min_height, max_width, max_height, symm_string, min_aspect,
                                    max_aspect, plot_width, plot_height)
        end = time.time()
        ui.print_gui("Time taken: " + str((end - start) * 1000) + " ms")
        graph_new = graph.graph_list[0]
        ui._append_output_data(graph_new)
        room_name = []
        if len(ui.get_roomNames()) > 0:
            room_name = ui.get_roomNames()
        graph_new.final_traversal=inputgraph.get_final_traversal(graph_new)
        if drawGUI:
            drawFunction(ui, graph_new, origin, room_name, gclass = gclass)
    elif(ui.get_isMinDimensioned() == 1):
        old_dims = [[3] * ui.get_noOfNodes()
            , [3] * ui.get_noOfNodes()]
        min_width, min_height, plot_width, plot_height, optimal_floorplan = mindimgui.gui_fnc(old_dims, ui.get_noOfNodes(), ui.get_roomNames())
        start = time.time()
        try:
            graph.oneconnected_dual("multiple")
            ui.print_gui('Generated multiple rectangular floorplan. Min Dim Enabled')        
        except inputgraph.OCError:
            show_warning("Can not generate rectangular floorplan.")
            graph.irreg_multiple_dual()
            ui.print_gui('Generated Multiple Irregular floorplan instead of Rectangular. Min Dim Enabled. OCError')
        except inputgraph.BCNError:
            graph.irreg_multiple_dual()
            ui.print_gui('Generated Multiple Irregular floorplan instead of Rectangular. Min Dim Enabled. BCNError')
        number_of_floorplans = graph.fpcnt
        floorplan_found = False

        # Resets the data already present for downloading catalogues
        ui._set_output_data([])
        ui._set_multiple_output_found(0)

        # Variables for storing the data of the floorplan with minimal area
        min_area = -1
        min_graph = None
        areas = []
        
        # Iterate through all possible floorplans to find one which satisfies the given conditions
        for i in range(number_of_floorplans):
            print("Trying floorplan number", i + 1, "to see if minimum dimension floorplan can be constructed.")
            floorplan_obj = input_for_min_dim.floorplan(ui.get_command(), ui.get_isDimensioned(),
                                                ui.get_isDimensionedCirculation(), ui.get_isRemoveAddCirculation(), ui.get_corridor_thickness())
            enc_mat = get_encoded_matrix(ui.get_noOfNodes(), graph.graph_list[i].room_x, graph.graph_list[i].room_y, graph.graph_list[i].room_width, graph.graph_list[i].room_height)
            floorplan_data = floorplan_obj.get_floorplan_details(
                ui.get_roomNames(), ui.get_roomColors(), ui.get_nodeCoordinates(), min_width, min_height, graph.graph_list[i].room_x, graph.graph_list[i].room_y, graph.graph_list[i].room_width, graph.graph_list[i].room_height,
                ui.get_edges(), enc_mat
            )
            print(floorplan_data)
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
                
                # room_x = np.array(room_x)
                # room_y = np.array(room_y)
                # room_width = np.array(room_width)
                # room_height = np.array(room_height)
                
                graph.graph_list[i].room_x = room_x
                graph.graph_list[i].room_y = room_y
                graph.graph_list[i].room_width =  room_width
                graph.graph_list[i].room_height = room_height
                graph.graph_list[i].area = room_area
                                
                '''
                Adds the graph data to output_data for downloading the catalogue and 
                multiple_output_found flag is set which indicates that catalogue can be downloaded for this output
                '''
                ui._append_output_data(graph.graph_list[i])
                ui._set_multiple_output_found(1)

                
                delete_file(input_path)
                delete_file(output_path)
                floorplan_found = True

                # If optimal area not required, display floorplan
                if optimal_floorplan == 0:
                    graph.graph_list[i].final_traversal=inputgraph.get_final_traversal(graph.graph_list[i])
                    if drawGUI:
                        drawFunction(ui, graph.graph_list[i], origin, room_name, gclass = gclass)
                    break

                # Store graph data if graph area is less than current minimal area
                area_sum = sum(room_area)
                areas.append(area_sum)
                if min_area < 0 or area_sum < min_area:
                    min_area = area_sum
                    min_graph = graph.graph_list[i]
                
            else:
                delete_file(input_path)
        if not floorplan_found:
            print("No floorplan found which satisfies the minimum dimensions input by user.")
        
        # Display floorplan with optimal area if required
        elif optimal_floorplan == 1:
            print("Floorplan Areas Possible:", areas, "\nOptimal Area:", min_area)
            if drawGUI:
                drawFunction(ui, min_graph, origin, room_name, gclass = gclass)
                
        end = time.time()
        ui.print_gui("Time taken: " + str((end - start) * 1000) + " ms")

        # Sets the ptpg object to the current graph to use for download catalogue and also stores the dimensional constraints of the graph
        gclass.ptpg = graph
        ui._set_dim_constraints([min_width, min_height, plot_width, plot_height])
    
def handle_multiple_oc(ui, graph, drawGUI = False, gclass = None):
    if (ui.get_isDimensioned() == 0):  # Non-Dimensioned multiple dual
        start = time.time()
        try:
            graph.oneconnected_dual("multiple")
            ui.print_gui('Generated multiple rectangular floorplan')        
        except inputgraph.OCError:
            show_warning("Can not generate rectangular floorplan.")
            graph.irreg_multiple_dual()
            ui.print_gui('Generated Multiple Irregular floorplan instead of Rectangular. OCError')
        except inputgraph.BCNError:
            graph.irreg_multiple_dual()
            ui.print_gui('Generated Multiple Irregular floorplan instead of Rectangular. BCNError')
        end = time.time()
        ui.print_gui("Average Time taken: " + str(((end - start) * 1000) / graph.fpcnt) + " ms")
        ui.print_gui("Number of floorplans: " + str(graph.fpcnt))

        for idx in range(graph.fpcnt):
            graph_new = graph.graph_list[idx]
            ui._set_multiple_output_found(1)
            ui._append_output_data(graph_new)
    else:
        old_dims = [[0] * ui.get_noOfNodes()
            , [0] * ui.get_noOfNodes()
            , [0] * ui.get_noOfNodes()
            , [0] * ui.get_noOfNodes()
            , ""
            , [0] * ui.get_noOfNodes()
            , [0] * ui.get_noOfNodes()]
        min_width, max_width, min_height, max_height, symm_string, min_aspect, max_aspect, plot_width, plot_height = dimgui.gui_fnc(
            old_dims, ui.get_noOfNodes())
        ui._set_dim_constraints([min_width, max_width, min_height, max_height, symm_string, min_aspect, max_aspect, plot_width, plot_height])
        start = time.time()
        try:
            graph.oneconnected_dual("multiple")
            ui.print_gui('Generated multiple Dimensioned Rectangular floorplan')        
        except inputgraph.OCError:
            show_warning("Can not generate rectangular floorplan.")
            graph.irreg_multiple_dual()
            ui.print_gui('Generated Multiple Irregular Dimensioned floorplan instead of Rectangular. OCError')
        except inputgraph.BCNError:
            graph.irreg_multiple_dual()
            ui.print_gui('Generated Multiple Irregular Dimensioned floorplan instead of Rectangular. BCNError')
        graph.multiple_floorplan(min_width, min_height, max_width, max_height, symm_string, min_aspect,
                                max_aspect, plot_width, plot_height)
        end = time.time()
        ui.print_gui("Time taken: " + str((end - start) * 1000) + " ms")
        ui.print_gui("Number of floorplans: " + str(len(graph.room_x)))
        ui._set_multiple_output_found(1)

        room_name = []
        if len(ui.get_roomNames()) > 0:
            room_name = ui.get_roomNames()

        for idx in range(len(graph.room_x)):
            graph_new = graph.graph_list[idx]
            ui._append_output_data(graph_new)
            ui._set_dim_constraints([min_width, max_width, min_height, max_height, symm_string, min_aspect, max_aspect, plot_width, plot_height])
            gclass.ptpg = graph
            print_all_rfp = False
            if print_all_rfp == True:
                gclass.ocan.add_tab()
                gclass.pen = gclass.ocan.getpen()
                gclass.pen.speed(0)
                graph_new.final_traversal=inputgraph.get_final_traversal(graph_new)
                if drawGUI:
                    drawFunction(ui, graph_new, origin, room_name, gclass = gclass)

def handle_poly(ui, graph, drawGUI = False, gclass = None):
    start = time.time()
    # graph.irreg_single_dual()
    graph.polyonalinput(gclass.canonicalObject, gclass.v1, gclass.v2, gclass.vn, gclass.po, ui.get_edges(),
                        gclass.debugcano)
    end = time.time()
    if drawGUI:
        drawFunction(ui, graph, origin, [], isPoly=True, gclass = gclass)
        

def handle_limits(ui, graph, drawGUI = False, gclass = None):
    input_json = {}
    graph_data = {}
    start = time.time()
    input_path = "./saved_files/input_to_limits.json"

    try:
        with open(input_path, 'r') as file:
            input_json = json.load(file)
    except:
        show_warning("Draw a floorplan before applying Limits algorithm.")
        
        
    for key, value in input_json.items():
        if isinstance(value, list):
            graph_data[key] = np.array(value)
        else:
            graph_data[key] = value

    # delete_file(input_path)
    
    end = time.time()


    # graph1 = deepcopy(self.graph)

    # graph1 = nx.Graph(edgeset)
    nodecnt = graph_data['nodecnt']
    edgecnt = graph_data['edgecnt']
    edgeset = graph_data['edgeset']
    node_coordinate = graph_data['node_coordinate']

    adj_matrix = np.zeros((nodecnt,nodecnt), int)

    for edges in (edgeset):
        x = (int)(edges[0])
        y = (int)(edges[1])
        adj_matrix[x][y] = 1
        adj_matrix[y][x] = 1


    graph_data = {
                'room_x': graph_data["room_x"],
                'room_y': graph_data["room_y"],
                'room_width': graph_data["room_width"],
                'room_height': graph_data["room_height"],
                'area': graph_data["area"],
                'extranodes': graph_data["extranodes"],
                'mergednodes': graph_data["mergednodes"],
                'irreg_nodes': graph_data["irreg_nodes"]
            }
    cr_data = []
    rooms = []
    coordinates = {}
    print()
    for i in range(graph_data['room_x'].shape[0]):
        temp=[]
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
        # print(data)
        Room_i = poly.Room()
        for i in data:
            temp.append(i[0])

        temp2 = [temp[0]] + temp[1:][::-1]

        print(temp2)
        for i in temp2:
            Room_i.coords.append(i)
        rooms.append(Room_i)
    
    s_dir = ""
    dist = 0
    if(gclass.side == 0):
        s_dir = gclass.left_dropdown_value
        dist = gclass.left_shift_value
    elif(gclass.side == 1):
        s_dir = gclass.right_dropdown_value
        dist = gclass.right_shift_value
    elif(gclass.side == 2):
        s_dir = gclass.top_dropdown_value
        dist = gclass.top_shift_value
    elif(gclass.side == 3):
        s_dir = gclass.bottom_dropdown_value
        dist = gclass.bottom_shift_value
    
    limits_instance = lim.LimitsAlgorithm(gclass.side,gclass.room_limits,rooms,adj_matrix,s_dir,dist)
    old_unchanged_coordinates = []
    if(limits_instance.proceed==1):
        newRoomSet = []
        exact_RoomSet = []
        for i in range(len(adj_matrix[gclass.room_limits])):
            if adj_matrix[gclass.room_limits][i]==1:
                newRoomSet.append(rooms[i])
                exact_RoomSet.append(i)
                old_unchanged_coordinates.append(False)
            else:
                old_unchanged_coordinates.append(True)
        newCoordsInstance = nc.NewCoordinateAlgorithm(exact_RoomSet,newRoomSet,s_dir,dist,limits_instance.coords_input1,limits_instance.coords_input2, gclass.side,rooms[gclass.room_limits])
        k=0
        _circular_traversal = []
        new_graph  = inputgraph.InputGraph(ui.get_noOfNodes()
            , ui.get_edgeCount()
            , ui.get_edges()
            , ui.get_nodeCoordinates())
        ui.set_graph(new_graph)

        for i in range(len(old_unchanged_coordinates)):
            if(i==gclass.room_limits):
                _circular_traversal.append(newCoordsInstance.circularTraversalOfSelectedRoomForMain())
                
            elif(old_unchanged_coordinates[i]==True):
                _circular_traversal.append(inputgraph.get_circular_traversal(graph_data['room_x'],graph_data['room_y'],graph_data['room_width'],graph_data['room_height'],i))
            else:
                _circular_traversal.append(newCoordsInstance.adjrooms[k].coord())
                k = k + 1
            new_graph.final_traversal.append(_circular_traversal[i])
            
        # graph_data = {
        #             'room_x': new_graph_data["room_x"],
        #             'room_y': new_graph_data["room_y"],
        #             'room_width': new_graph_data["room_width"],
        #             'room_height': new_graph_data["room_height"],
        #             'area': [],
        #             'extranodes': [],
        #             'mergednodes': [],
        #             'irreg_nodes': []
        #         }
        
        # temp_graph_data = {}
        # temp_graph_data["nodecnt"] = ui.get_noOfNodes()
        # temp_graph_data["edgecnt"] = ui.get_edgeCount()
        # temp_graph_data["edgeset"] = ui.get_edges()
        # temp_graph_data["node_coordinate"] = ui.get_nodeCoordinates()

        # for key, value in graph_data.items():
        #     if isinstance(value, np.ndarray):
        #         temp_graph_data[key] = value.tolist()
        #     else:
        #         temp_graph_data[key] = value

        # input_path = "./saved_files/input_to_limits.json"
        # with open(input_path, 'w') as json_file:
        #     json_data = json.dump(temp_graph_data,json_file, indent=2)
        # print(f"JSON data has been written to {input_path}")

        # for key, value in new_graph_data.items():
        #     if isinstance(value, list):
        #         new_graph_data[key] = np.array(value)
        #     else:
        #         new_graph_data[key] = value

        # new_graph.circular_traversal = 
        print("circular traversal for all rooms: ", new_graph.final_traversal)
        # new_graph.room_x = new_graph_data['room_x']
        # new_graph.room_y = new_graph_data['room_y']
        # new_graph.room_width = new_graph_data['room_width']
        # new_graph.room_height = new_graph_data['room_height']
        # new_graph.area = new_graph_data['area']
        # new_graph.extranodes = new_graph_data['extranodes']
        # new_graph.mergednodes = new_graph_data['mergednodes']
        # new_graph.irreg_nodes1 = new_graph_data['irreg_nodes']

        if drawGUI:
            drawFunction(ui, new_graph, origin, [], gclass = gclass)
    else:
        print("Limit Exceeded")
        # show_warning(newCoordsInstance.error_message)

def handle_door_connectivity(ui, graph, drawGUI = False, gclass = None):
    start = time.time()
    graph2 = inputgraph.InputGraph(ui.get_noOfNodes() 
                                , ui.get_edgeCount()
                                , ui.get_edges()
                                , ui.get_nodeCoordinates())
    graphx = nx.from_numpy_array(graph.matrix)
    # plot(graphx, len(graphx.nodes))
    graph.door_connectivity()
    # plot(graphx, len(graphx.nodes))
    end = time.time()
    ui.print_gui("Time taken: " + str((end - start) * 1000) + " ms")
    ui._append_output_data(graph)
    graph.final_traversal=inputgraph.get_final_traversal(graph)
    if drawGUI:
        drawFunction(ui, graph, origin, [], gclass = gclass)
    
    # graph2.door_connectivity2()
    # graph2.final_traversal=inputgraph.get_final_traversal(graph2)
    # draw.draw_rdg(graph2
    #                 , 1
    #                 , gclass.pen
    #                 , 1
    #                 , ui.get_roomColors()
    #                 ,[]
    #                 , origin- 300)
    ui._set_time_taken((end - start) * 1000)
    ui._set_num_rfp(len(graph.graph_list))
    ui._set_pdf_colors(ui.get_roomColors()[0])
    ui._set_output_found(1)
    
def plot(graph: nx.Graph,m: int) -> None:
    """Plots the graph using matplotlib

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

def show_warning(str):
    messagebox.showinfo("Warning", str)
