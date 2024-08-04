"""API

Generates floorplamns for given graph data as input.
Current support only for rectangular floorplans.
A running example is available.

"""
from GPLAN.source.inputgraph import InputGraph
import GPLAN.pythongui.gui as gui
import uuid

from GPLAN.handlers import *
from GPLAN.pythongui.GuiParameters import GuiParameters, DimParameters
import builtins

class Asset:
    def __init__(self, _id, properties, asset_type):
        self._id = _id
        self.properties = properties
        self.type = asset_type

    def to_dict(self):
        return {
            "_id": self._id,
            "properties": self.properties,
            "type": self.type
        }


class Wall:
    def __init__(self, _id, x1, y1, x2, y2, assets=None):
        self._id = _id
        self.x1 = x1
        self.y1 = y1
        self.x2 = x2
        self.y2 = y2
        self.assets = []
        if assets is not None:
            self.assets = [asset.to_dict() for asset in assets]

    def to_dict(self):
        return {
            "_id": self._id,
            "x1": self.x1,
            "y1": self.y1,
            "x2": self.x2,
            "y2": self.y2,
            "assets": self.assets
        }


class Room:
    def __init__(self, _id, name, color, walls=None, assets=None, circular_coordinates=None):
        self._id = _id
        self.name = name
        self.assets = []
        if assets is not None:
            self.assets = [asset.to_dict() for asset in assets]
        self.color = color
        if walls is not None:
            self.walls = [wall.to_dict() for wall in walls]
        self.circular_coordinates = circular_coordinates

    def to_dict(self):
        return {
            "_id": self._id,
            "name": self.name,
            "assets": self.assets,
            "color": self.color,
            "walls": self.walls,
            "circular_coordinates": self.circular_coordinates
        }


FLOORPLAN_LIMIT = 10


class Documents:
    def __init__(self, hasMore, offset, documentID, name, count):
        self.hasMore = hasMore
        self.offset = offset
        self.documentID = documentID
        self.name = name
        self.count = count
        self.floorplans = []

    def append_floorplan(self,floorplan):
        if floorplan:
            self.floorplans.append([room.to_dict() for room in floorplan])

    def to_dict(self):
        return {
            "Documents": {
                "documentID": self.documentID,
                "name": self.name,
                "count":self.count,
                # "hasMore": self.hasMore,
                # "offset": self.offset,
                "floorPlans": self.floorplans
            }
        }

    @staticmethod
    def get_floorplans(starting_from: int, count: int, caller, nodes_list: list, graph: InputGraph, rectangular: bool, corridor=False,
                         dimensioned = False, dimensionedCirculation = False, minDimEnabled = False, removeAddCirculation = False, publicEnabled = False,normalize_const=40, limit=FLOORPLAN_LIMIT, corridor_thickness=None,documentID=None, name=None, dim_inputs={}):
        original_print = builtins.print

        def null_print(*args, **kwargs):
            pass

        builtins.print = null_print

        message = ""
        dim_parameters: DimParameters = None
        if minDimEnabled:
            dim_parameters = DimParameters(min_width=dim_inputs['min_width'], min_height=dim_inputs['min_height'],max_width=dim_inputs['max_width'], max_height=dim_inputs['max_height'], plot_width=dim_inputs['plot_width'], plot_height=dim_inputs['plot_height'], isOptimalEnabled=dim_inputs['optimal_floorplan'])
        elif dimensioned:
            dim_parameters = DimParameters(min_width=dim_inputs['min_width'], min_height=dim_inputs['min_height'], max_width=dim_inputs['max_width'], max_height=dim_inputs['max_height'], min_ratio=dim_inputs['min_ratio'], max_ratio=dim_inputs['max_ratio'], plot_width=dim_inputs['plot_width'], plot_height=dim_inputs['plot_height'], symmetric=dim_inputs['symmetric'], isOptimalEnabled=dim_inputs['optimal_floorplan'])
        ui = GuiParameters(graph=graph).set_isDimensioned(dimensioned).set_isDimensionedCirculation(
            dimensionedCirculation).set_isMinDimensioned(minDimEnabled).set_isRemoveAddCirculation(
            removeAddCirculation).set_isPublic(publicEnabled).set_min_dim_inputs(dim_parameters)
        documentID = str(uuid.uuid4()) if documentID is None else documentID
        name = "Untitled Document" if name is None else name
        ui.set_message("")
        roomColors = []
        roomNames = []
        for node in nodes_list:
            roomColors.append(node["color"])
            roomNames.append(node["label"])
        ui.set_roomNames(roomNames)
        ui.set_roomColors(roomColors)
        if corridor_thickness is not None:
            ui.set_corridor_thickness(corridor_thickness)
        if corridor:
            ui.set_command('circulation')
        if starting_from is None:
            starting_from = 0
        if count is None:
            count = 1
        nodes_data = []
        response = []
        if count == 1:
            if caller == 'lshape':
                ui.set_letter("L Shape")
                for node in nodes_list:
                    node_obj = gui.gui_class.Nodes(node['id'], node['x'], node['y'])
                    nodes_data.append(node_obj)
                handle_letter_shape(ui, graph, nodes_data=nodes_data)
                message = 'Generated L shaped floorplan.'
                message += ui.get_message()
                print(message)
            elif caller == 'ushape':
                ui.set_letter("U Shape")
                handle_letter_shape(ui, graph)
                message = 'Generated U shaped floorplan.'
                message += ui.get_message()
                print(message)
            elif caller == 'tshape':
                ui.set_letter("T Shape")
                handle_letter_shape(ui, graph)
                message = 'Generated T shaped floorplan.'
                message += ui.get_message()
                print(message)
            elif caller == 'zshape':
                ui.set_letter("Z Shape")
                handle_letter_shape(ui, graph)
                message = 'Generated Z shaped floorplan.'
                message += ui.get_message()
                print(message)
            elif caller == 'staircaseshape':
                handle_staircase_shaped(ui, graph)
                message = 'Generated Staircase shaped floorplan.'
                message += ui.get_message()
                print(message)
            # elif caller == 'pentagonal': #Support Not added yet
            #     Pentagonal.PentagonalFloorplan(ui, graph, nodes_list)
            # elif caller == 'hexagonal': #Support Not added yet
            #     Hexagonal.HexagonalFloorplan(ui, graph, nodes_list)
            # elif caller == 'custom': #Support Not added yet
            # Customplot.CustomplotFloorplan(graph, nodes_list)
            elif caller == 'rectangular' or caller == 'irregular':
                if rectangular:
                    handle_single_oc(ui, graph)
                else:
                    handle_single(ui, graph)

            elif caller == "door_connectivity":
                handle_door_connectivity(ui, graph)
            else:
                message = f"Support for {caller} Not yet Handled from Backend for Single Floorplan"
                print(message)
        else:
            if caller == 'lshape':
                print("Generating Multiple L shape")
                ui.set_letter("L Shape")
                for node in nodes_list:
                    node_obj = gui.gui_class.Nodes(node['id'], node['x'], node['y'])
                    nodes_data.append(node_obj)
                handle_multiple_l(ui, graph, nodes_data=nodes_data)
                message = 'Generated L shaped floorplan.'
                message += ui.get_message()
                print(message)
            elif caller == 'rectangular':
                handle_multiple_oc(ui, graph)
            elif caller == 'irregular':
                handle_multiple(ui, graph)
            elif caller == "door_connectivity":
                handle_door_connectivity(ui, graph)
            elif caller == "multiple_l":
                handle_multiple_l(ui, graph)
            else:
                message = f"Support for {caller} Not yet Handled from Backend for Multiple Floorplan"
                print(message)
        if count == 1:
            outputData = [graph]
        elif count > 1:
            outputData = ui.get_output_data()
        offset = 0
        hasMore = graph.fpcnt - offset - 1 > 0
        total_fp_count = min(min(len(outputData), limit),count)
        response = Documents(hasMore, offset, documentID, name, total_fp_count)

        for index in range(min(min(len(outputData), limit),count)):
            rooms = []
            floorplanData = outputData[index].final_traversal
            k = 0
            for roomData in floorplanData:
                room = None
                x1 = roomData[0][0]
                y1 = roomData[0][1]
                wallValues = []
                for i in range(1, len(roomData)):
                    x2 = roomData[i][0]
                    y2 = roomData[i][1]
                    wall = Wall(str(uuid.uuid4()), x1, y1, x2, y2)
                    wallValues.append(wall)
                    x1 = x2
                    y1 = y2
                wallValues.append(Wall(str(uuid.uuid4()), x1, y1, roomData[0][0], roomData[0][1]))
                room = Room(str(uuid.uuid4()), nodes_list[k]["label"], nodes_list[k]["color"], wallValues,
                            circular_coordinates=roomData)  # To add handling of node index starting from 0 then 1 then 2. It should be a unique no and GPLAN should map
                k = k + 1
                rooms.append(room)
            response.append_floorplan(rooms)

        builtins.print = original_print

        return response, message
