"""API

Generates floorplamns for given graph data as input.
Current support only for rectangular floorplans.
A running example is available.

"""
import re
from .source.inputgraph import InputGraph as InputGraph
from .source.lettershape.lshape import Lshaped as Lshaped
from .source.lettershape.tshape import tshape as Tshaped
from .source.lettershape.ushape import ushape as Ushaped
from .source.lettershape.zshape import zshape as Zshaped
from .pythongui import gui as gui
import uuid

from .main import GuiParameters, handle_letter_shape, handle_multiple, handle_multiple_l, handle_multiple_oc, \
    handle_single, handle_single_oc, handle_staircase_shaped


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


class FloorPlans:
    def __init__(self, hasMore, offset, values=None):
        self.hasMore = hasMore
        self.offset = offset
        if values:
            self.values = [value.to_dict() for value in values]

    def to_dict(self):
        return {
            "floorPlans": {
                "hasMore": self.hasMore,
                "offset": self.offset,
                "values": self.values
            }
        }

    @staticmethod
    def get_floorplans(starting_from: int, count: int, caller, nodes_list: list, graph: InputGraph, rectangular: bool, corridor=False,
                         dimensioned = False, dimensionedCirculation =False , minDimEnabled = False, removeAddCirculation = False, publicEnabled = False,normalize_const=40, limit=FLOORPLAN_LIMIT, corridor_thickness=None):
        message = ""
        isDimensioned = 1 if dimensioned == True else 0
        isDimensionedCirculation = 1 if dimensionedCirculation == True else 0
        isMinDimensioned = 1 if minDimEnabled == True else 0
        isRemoveAddCirculation = 1 if removeAddCirculation == True else 0
        isPublic = 1 if publicEnabled == True else 0
        ui = GuiParameters(graph=graph).set_isDimensioned(isDimensioned).set_isDimensionedCirculation(
            isDimensionedCirculation).set_isMinDimensioned(isMinDimensioned).set_isRemoveAddCirculation(
            isRemoveAddCirculation).set_isPublic(isPublic)
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
        floorplans = []
        if count == 1:
            if caller == 'lshape':
                print("Generating L shape")
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
                print("Generating Rectangular/Irregular shape")
                if rectangular:
                    handle_single_oc(ui, graph)
                else:
                    handle_single(ui, graph)
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
            else:
                message = f"Support for {caller} Not yet Handled from Backend for Multiple Floorplan"
                print(message)
        outputData = graph.final_traversal
        if count == 1:
            outputData = [outputData]
        offset = 0
        hasMore = graph.fpcnt - offset - 1 > 0
        for index in range(min(len(outputData), limit)):
            floorplanData = outputData[index]
            rooms = []
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
        floorplans = FloorPlans(hasMore, offset, rooms)

        return floorplans, message
