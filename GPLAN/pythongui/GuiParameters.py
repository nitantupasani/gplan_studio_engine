from GPLAN.source import inputgraph as inputgraph
from GPLAN.pythongui import gui as gui
import tkinter as tk

class GuiParameters:
    
    __gclass: gui.gui_class = None
    __graph: inputgraph.InputGraph
    __isGui: bool
    __noOfNodes: int #gclass.value[0]
    __edgeCount: int #gclass.value[1]
    __edges: list #gclass.value[2]
    __fptype: str #gclass.value[3]
    __command: str
    __roomNames: list #gclass.value[5]
    __isDimensioned: int #gclass.value[4]
    __isDimensionedCirculation: int #gclass.value[8]
    __isRemoveAddCirculation: int #gclass.value[9]
    __isMinDimensioned: int #gclass.value[10]
    __isPublic: int
    __nodeCoordinates: list #gclass.value[7]
    __roomColors: list #gclass.value[6]
    __letter: str
    __corridor_thickness: float
    __message: str = ""
    output_data: list = []

    def get_fptype(self) -> str:
        return self.__fptype

    def set_fptype(self, fptype: str):
        self.__fptype = fptype
        return self

    def get_corridor_thickness(self) -> float:
        if self.__corridor_thickness is None:
            if self.get_gclass() is not None:
                return self.get_gclass().corridor_thickness
        return self.__corridor_thickness
    
    def set_corridor_thickness(self, corridor_thickness: float):
        self.__corridor_thickness = corridor_thickness
        return self
    
    def get_letter(self) -> str:
        return self.__letter
    
    def set_letter(self, letter: str):
        self.__letter = letter
        return self
    
    def get_isMinDimensioned(self) -> int:
        return self.__isMinDimensioned
    
    def set_isMinDimensioned(self, isMinDimensioned):
        if isMinDimensioned is None:
            self.__isMinDimensioned = 0
        else:
            self.__isMinDimensioned = isMinDimensioned
        return self
        
    def get_isPublic(self) -> int:
        return self.__isPublic
    
    def set_isPublic(self, isPublic):
        if isPublic is None:
            self.__isPublic = 0
        else:
            self.__isPublic = isPublic
        return self
        
    def get_isRemoveAddCirculation(self) -> int:
        return self.__isRemoveAddCirculation
    
    def set_isRemoveAddCirculation(self, isRemoveAddCirculation):
        if isRemoveAddCirculation is None:
            self.isRemoveAddCirculation = 0
        else:
            self.__isRemoveAddCirculation = isRemoveAddCirculation
        return self

    def get_isDimensionedCirculation(self) -> int:
        return self.__isDimensionedCirculation
    
    def set_isDimensionedCirculation(self, isDimensionedCirculation):
        if isDimensionedCirculation is None:
            self.isDimensionedCirculation = 0
        else:
            self.__isDimensionedCirculation = isDimensionedCirculation
        return self

    def get_isDimensioned(self) -> int:
        return self.__isDimensioned
    
    def set_isDimensioned(self, isDimensioned: int):
        if isDimensioned is None:
            self.isDimensioned = 0
        else:
            self.__isDimensioned = isDimensioned 
        return self
    
    def get_nodeCoordinates(self) -> list:
        return self.__nodeCoordinates
    
    def set_nodeCoordinates(self, nodeCoordinates: list):
        self.__nodeCoordinates = nodeCoordinates
        if self.get_gclass() is not None:
            self.get_gclass().coordinates = nodeCoordinates
        return self
         
    def set_gclass(self, gclass: gui.gui_class):
        self.__gclass = gclass
        return self

    def get_isGui(self) -> bool:
        return self.__isGui

    def set_isGui(self, isGui: bool):
        self.__isGui = isGui
        return self

    def get_noOfNodes(self) -> int:
        return self.__noOfNodes

    def set_noOfNodes(self, noOfNodes):
        self.__noOfNodes = noOfNodes
        if self.get_gclass() is not None:
            self.get_gclass().no_of_nodes = noOfNodes
        return self

    def get_edgeCount(self) -> int:
        return self.__edgeCount

    def set_edgeCount(self, edgeCount):
        self.__edgeCount = edgeCount
        if self.get_gclass() is not None:
            self.get_gclass().edge_count = edgeCount
        return self

    def get_edges(self) -> list:
        return self.__edges

    def set_edges(self, edges: list):
        self.__edges = edges
        if self.get_gclass() is not None:
            self.get_gclass().edges = edges
        return self

    def get_command(self) -> str:
        return self.__command

    def set_command(self, command: str):
        self.__command = command
        return self

    def get_roomNames(self) -> list:
        return self.__roomNames

    def set_roomNames(self, roomNames: list):
        self.__roomNames = roomNames
        return self

    def get_roomColors(self) -> list:
        return self.__roomColors

    def set_roomColors(self, roomColors: list):
        self.__roomColors = roomColors
        return self
    
    def get_gclass(self) -> gui.gui_class:
        return self.__gclass
    
    def get_graph(self) -> inputgraph.InputGraph:
        return self.__graph
    
    def set_graph(self, graph: inputgraph.InputGraph):
        self.__graph = graph
        return self
    
    def set_message(self, message: str):
        if self.get_message() is not None:
            self.__message += message
        return self.__message
    
    def get_message(self) -> str:
        return self.__message

    def get_dim_constraints(self):
        if self.get_gclass() is not None:
            return self.get_gclass().dimensional_constraints
        return None

    def __init__(self, gclass = None, graph = None):
        if gclass is not None:
            self.set_gclass(gclass)
            self.set_noOfNodes(gclass.value[0])
            self.set_edgeCount(gclass.value[1])
            self.set_edges(gclass.value[2])
            self.set_fptype(gclass.value[3])
            self.set_isDimensioned(gclass.value[4])
            self.set_roomNames(gclass.value[5])
            self.set_roomColors(gclass.value[6])
            self.set_nodeCoordinates(gclass.value[7])
            self.set_isDimensionedCirculation(gclass.value[8])
            self.set_isRemoveAddCirculation(gclass.value[9])
            self.set_isMinDimensioned(gclass.value[10])
            self.set_isPublic(gclass.value[11])
            self.set_isGui(True)
            self.set_letter(gclass.letter)
            self.set_corridor_thickness(gclass.corridor_thickness)
            self.set_message("")
            self.set_command(gclass.command)

            self.output_data = []
        
        if graph is not None:
            self.set_graph(graph)
            self.set_edgeCount(graph.edgecnt)
            self.set_noOfNodes(graph.nodecnt)
            # self.set_edges(graph.edges)
            self.set_nodeCoordinates(graph.coordinates)
            self.set_isGui(False)
    
    def print_gui(self, string):
        self.set_message(string)
        if self.get_gclass() is not None:
            self.get_gclass().textbox.insert(tk.END, string) # type: ignore
            self.get_gclass().textbox.insert(tk.END, "\n") # type: ignore
    def get_output_data(self):
        if self.get_gclass() is not None:
            return self.get_gclass().output_data
        return self.output_data

    def _append_output_data(self, graph_new):
        if self.get_gclass() is not None:
            self.get_gclass().output_data.append(graph_new)
        else:
            self.output_data.append(graph_new)

        if graph_new is not None and len(graph_new.final_traversal)==0: #FOR SANITY
            graph_new.final_traversal = inputgraph.get_final_traversal(graph_new)

    def _set_output_data(self, output_data):
        if self.get_gclass() is not None:
            self.get_gclass().output_data = output_data
        else:
            self.output_data = output_data
    
    def _set_time_taken(self, time_taken):
        if self.get_gclass() is not None:
            self.get_gclass().time_taken = time_taken
    
    def _set_num_rfp(self, num_rfp):
        if self.get_gclass() is not None:
            self.get_gclass().num_rfp = num_rfp
            
    def _set_pdf_colors(self, pdf_colors):
        if self.get_gclass() is not None:
            self.get_gclass().pdf_colors = pdf_colors
            
    def _set_output_found(self, output_found):
        if self.get_gclass() is not None:
            self.get_gclass().output_found = output_found
            
    def _set_multiple_output_found(self, multiple_output_found):
        if self.get_gclass() is not None:
            self.get_gclass().multiple_output_found = multiple_output_found
                    
    def _set_dim_constraints(self, dim_constraints):
        if self.get_gclass() is not None:
            self.get_gclass().dimensional_constraints = dim_constraints

    def _set_ptpg(self, graph):
        if self.get_gclass() is not None:
            self.get_gclass().ptpg = graph
    
# gclass.bottom_shift_value
# gclass.bottom_dropdown_value
# gclass.top_dropdown_value
# gclass.top_shift_value
# gclass.right_shift_value
# gclass.right_dropdown_value
# gclass.left_shift_value
# gclass.side
# gclass.left_dropdown_value
# gclass.room_limits
# gclass.ptpg = graph
# gclass.dimensional_constraints = [min_width, min_height, plot_width, plot_height]
# gclass.multiple_output_found = 1

