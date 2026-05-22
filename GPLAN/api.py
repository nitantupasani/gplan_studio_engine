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

# Import boundary utilities from Space_Optimization folder
import sys
import os
space_opt_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'Space_Optimization')
if space_opt_path not in sys.path:
    sys.path.insert(0, space_opt_path)
from boundary_utils import boundary_to_regions as convert_boundary_to_regions


def boundary_to_regions(boundary, fixed_rooms=None):
    """
    Convert a polygonal boundary to a list of rectangular regions.
    
    Uses the same algorithm as the UI's CAD tool (decompose_into_rectangles).
    Creates a grid-based decomposition with cell merging for optimal region count.
    
    Args:
        boundary: List of [x, y] coordinate pairs defining the polygon vertices
        fixed_rooms: Optional list of fixed room polygons to exclude during decomposition
        
    Returns:
        List of region dictionaries with x, y, width, height
        
    Example:
        boundary = [[0, 0], [10, 0], [10, 5], [5, 5], [5, 10], [0, 10]]
        regions = boundary_to_regions(boundary)
        # Returns L-shape as merged rectangles
    """
    if not boundary or len(boundary) < 3:
        raise ValueError("Boundary must have at least 3 points")
    
    # Use the shared utility function (same as UI)
    return convert_boundary_to_regions(boundary, fixed_rooms=fixed_rooms)


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
    def __init__(self, _id, name, color, walls=None, assets=None, circular_coordinates=None,name_coord=None,area = None,width = None,height = None):
        self._id = _id
        self.name = name
        self.name_coord = name_coord
        self.area = area
        self.width = width
        self.height = height
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
            "label_coord": self.name_coord,
            "area" : self.area,
            "width" : self.width,
            "height" : self.height,
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
        self.ptpg_graph = None

    def append_floorplan(self,floorplan):
        if floorplan:
            self.floorplans.append([room.to_dict() for room in floorplan])
    
    def set_ptpg_graph(self, ptpg_graph):
        self.ptpg_graph = ptpg_graph

    def to_dict(self):
        doc_dict = {
            "documentID": self.documentID,
            "name": self.name,
            "count":self.count,
            # "hasMore": self.hasMore,
            # "offset": self.offset,
            "floorPlans": self.floorplans
        }
        if self.ptpg_graph is not None:
            doc_dict["ptpg_graph"] = self.ptpg_graph
            
        return {
            "Documents": doc_dict
        }

    @staticmethod
    def get_floorplans(starting_from: int, count: int, caller, nodes_list: list, graph: InputGraph, rectangular: bool, corridor=False,
                         dimensioned = False, dimensionedCirculation = False, minDimEnabled = False, removeAddCirculation = False, publicEnabled = False, nonAdj = False, normalize_const=40, limit=FLOORPLAN_LIMIT, corridor_thickness=None,documentID=None, name=None,circulationEnabled = 0, dim_inputs={},edges_list=[], non_adj_edge_list=[]):
        original_print = builtins.print

        def null_print(*args, **kwargs):
            pass

        builtins.print = null_print

        message = ""
        dim_parameters: DimParameters = None
        if minDimEnabled:
            dim_parameters = DimParameters(min_width=dim_inputs['min_width'], min_height=dim_inputs['min_height'],max_width=dim_inputs['max_width'], max_height=dim_inputs['max_height'], plot_width=dim_inputs['plot_width'], plot_height=dim_inputs['plot_height'], isOptimalEnabled=dim_inputs['optimal_floorplan'],isRotationAllowed = dim_inputs['rotation_enabled'])
        elif dimensioned:
            dim_parameters = DimParameters(min_width=dim_inputs['min_width'], min_height=dim_inputs['min_height'], max_width=dim_inputs['max_width'], max_height=dim_inputs['max_height'], min_ratio=dim_inputs['min_ratio'], max_ratio=dim_inputs['max_ratio'], plot_width=dim_inputs['plot_width'], plot_height=dim_inputs['plot_height'], symmetric=dim_inputs['symmetric'], isOptimalEnabled=dim_inputs['optimal_floorplan'])
        ui = GuiParameters(graph=graph).set_isDimensioned(dimensioned).set_isDimensionedCirculation(
            dimensionedCirculation).set_isMinDimensioned(minDimEnabled).set_isRemoveAddCirculation(
            removeAddCirculation).set_isPublic(publicEnabled).set_min_dim_inputs(dim_parameters).set_isCirculation(circulationEnabled)
        original_print(ui)
        documentID = str(uuid.uuid4()) if documentID is None else documentID
        name = "Untitled Document" if name is None else name
        ui.set_message("")
        ui.set_fptype(caller)
        ui.set_edges(edges_list)
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
                ui.set_isNonAdj(nonAdj)
                ui.set_non_adj_list(non_adj_edge_list)
                ui.set_is_multiple_door(False) 
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
                ui.set_isNonAdj(nonAdj)
                ui.set_non_adj_list(non_adj_edge_list)
                ui.set_is_multiple_door(True)
                handle_door_connectivity(ui, graph)
                message = 'Generated Multiple Door connectivity floorplan.'+ ui.get_message()
            elif caller == "multiple_l":
                handle_multiple_l(ui, graph)
            else:
                message = f"Support for {caller} Not yet Handled from Backend for Multiple Floorplan"
                print(message)
        if count == 1:
            outputData = ui.get_output_data()
        elif count > 1:
            outputData = ui.get_output_data()
        offset = 0
        hasMore = graph.fpcnt - offset - 1 > 0
        total_fp_count = min(min(len(outputData), limit),count)
        response = Documents(hasMore, offset, documentID, name, total_fp_count)
        
        # Add ptpg_graph if available
        if caller == "door_connectivity":
            ptpg_graph = ui.get_ptpg_graph() if hasattr(ui, 'get_ptpg_graph') else None
            if ptpg_graph:
                response.set_ptpg_graph(ptpg_graph)

        for index in range(min(min(len(outputData), limit),count)):
            rooms = []
            floorplanData = outputData[index].final_traversal
            name_coord = outputData[index].name_coords
            area = outputData[index].area
            widths = outputData[index].room_width
            heights = outputData[index].room_height
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
                            circular_coordinates=roomData,name_coord = name_coord[k],area=area[k],width = widths[k],height = heights[k])  # To add handling of node index starting from 0 then 1 then 2. It should be a unique no and GPLAN should map
                k = k + 1
                rooms.append(room)
            response.append_floorplan(rooms)

        builtins.print = original_print

        return response, message

    @staticmethod
    def get_space_optimized_floorplan(request_data):
        """
        Generate a space-optimized floorplan using the negNew FloorPlan engine.
        
        Args:
            request_data: Dictionary containing:
                - request_id: Unique request identifier
                - params: Dictionary with:
                    - regions: List of rectangular regions (optional if boundary is provided)
                    - boundary: List of [x,y] points defining polygonal boundary (optional if regions provided)
                    - rooms: List of room specifications
                    - fixed_rooms: List of fixed room specifications
                    - adjacency: List of adjacency requirements
                    - non_adjacency: List of non-adjacency requirements
                    - entrance_coords: Entrance location
                - ops: List of operations to perform (e.g., ["place", "compact", "expand", "score"])
        
        Returns:
            Dictionary with response data matching the expected output format
        """
        original_print = builtins.print

        def null_print(*args, **kwargs):
            pass

        builtins.print = null_print

        try:
            request_id = request_data.get('request_id', str(uuid.uuid4()))
            params = request_data.get('params', {})
            ops = request_data.get('ops', ['place', 'compact', 'expand', 'score'])
            
            # Extract parameters
            # Support EITHER regions OR boundary
            regions = params.get('regions', None)
            boundary = params.get('boundary', None)
            rooms = params.get('rooms', [])
            fixed_rooms = params.get('fixed_rooms', [])
            adjacency = params.get('adjacency', [])
            non_adjacency = params.get('non_adjacency', [])
            entrance_coords = params.get('entrance_coords', None)

            fixed_room_polygons = []
            for fixed_room in fixed_rooms:
                if not isinstance(fixed_room, dict):
                    continue
                polygon = fixed_room.get('polygon')
                if polygon:
                    fixed_room_polygons.append(polygon)
                    continue
                try:
                    fx = int(fixed_room['x'])
                    fy = int(fixed_room['y'])
                    fw = int(fixed_room['width'])
                    fh = int(fixed_room['height'])
                except Exception:
                    continue
                fixed_room_polygons.append([
                    [fx, fy],
                    [fx + fw, fy],
                    [fx + fw, fy + fh],
                    [fx, fy + fh],
                ])
            
            # If boundary is provided instead of regions, convert it
            if boundary and not regions:
                try:
                    regions = boundary_to_regions(boundary, fixed_rooms=fixed_room_polygons)
                    print(f"Converted boundary with {len(boundary)} points to {len(regions)} regions")
                except Exception as e:
                    builtins.print = original_print
                    return {
                        'request_id': request_id,
                        'status': 'error',
                        'data': {},
                        'error': {'message': f'Failed to convert boundary to regions: {str(e)}'}
                    }

            boundary_bounds = None
            if boundary:
                boundary_bounds = {
                    'min_x': min(point[0] for point in boundary),
                    'min_y': min(point[1] for point in boundary),
                    'max_x': max(point[0] for point in boundary),
                    'max_y': max(point[1] for point in boundary),
                }
            
            # Validate that we have regions (either provided or converted)
            if not regions:
                builtins.print = original_print
                return {
                    'request_id': request_id,
                    'status': 'error',
                    'data': {},
                    'error': {'message': 'Either regions or boundary must be provided'}
                }
            
            # Operation flags
            enable_expansion = 'expand' in ops
            enable_compaction = 'compact' in ops
            max_attempts = params.get('max_attempts', 100)
            
            # Create UI object for output storage
            from GPLAN.pythongui.GuiParameters import GuiParameters
            ui = GuiParameters(graph=None)
            
            # Call the handler
            success = handle_space_optimization(
                ui=ui,
                regions=regions,
                rooms=rooms,
                fixed_rooms=fixed_rooms,
                adjacency=adjacency,
                non_adjacency=non_adjacency,
                entrance_coords=entrance_coords,
                max_attempts=max_attempts,
                enable_expansion=enable_expansion,
                enable_compaction=enable_compaction,
                boundary_bounds=boundary_bounds
            )
            
            if not success:
                builtins.print = original_print
                return {
                    'request_id': request_id,
                    'status': 'error',
                    'data': {},
                    'error': {'message': ui.get_message()}
                }
            
            # Extract output data
            output_data = ui.get_output_data()
            if not output_data or len(output_data) == 0:
                builtins.print = original_print
                return {
                    'request_id': request_id,
                    'status': 'error',
                    'data': {},
                    'error': {'message': 'No output data generated'}
                }
            
            result = output_data[0]
            
            # Calculate floor dimensions
            floor_width = max(r['x'] + r['width'] for r in regions) if regions else 0
            floor_height = max(r['y'] + r['height'] for r in regions) if regions else 0
            
            # Format response
            response = {
                'request_id': request_id,
                'status': 'ok',
                'data': {
                    'floor': {
                        'width': floor_width,
                        'height': floor_height,
                        'regions': regions,
                        'entrance_coords': entrance_coords
                    },
                    'placements': result['rooms'],
                    'metrics': {
                        'ops_run': ops,
                        'adjacency_score': result['metrics']['adjacency_score'] / len(adjacency) if adjacency else 1.0,
                        'satisfied_pairs': result['metrics']['satisfied_pairs'],
                        'non_adjacency_violations': result['metrics']['non_adjacency_violations'],
                        'entrance_adjacent_rooms': result['metrics'].get('entrance_adjacent_rooms', []),
                        'area_utilization': result['metrics']['area_utilization'],
                        'integrity': {
                            'overlaps': [],
                            'out_of_bounds': [],
                            'invalid_adjacent_edges': []
                        }
                    }
                },
                'error': {}
            }
            
            builtins.print = original_print
            return response
            
        except Exception as e:
            builtins.print = original_print
            import traceback
            traceback.print_exc()
            return {
                'request_id': request_data.get('request_id', 'unknown'),
                'status': 'error',
                'data': {},
                'error': {'message': str(e)}
            }

    @staticmethod
    def get_ga_optimized_floorplan(request_data):
        """
        Generate a GA-optimized floorplan using genetic algorithm with corridor generation.
        
        Args:
            request_data: Dictionary containing:
                - request_id: Unique request identifier
                - engine: Should be "GA_FloorPlan"
                - params: Dictionary with:
                    - plot_width: Width of the plot
                    - plot_height: Height of the plot
                    - corridor_width: Width of corridors (default: 3)
                    - rooms: List of room objects with walls
                    - walls: List of all walls
                    - labels: List of labels (optional)
                    - ga_config: GA configuration (optional)
                        - max_workers: Number of workers for parallel processing (default: 1)
        
        Returns:
            Dictionary with response data matching temp2.json format
        """
        original_print = builtins.print

        def null_print(*args, **kwargs):
            pass

        builtins.print = null_print

        try:
            request_id = request_data.get('request_id', str(uuid.uuid4()))
            params = request_data.get('params', {})
            
            # Build floorplan_data in the format ga_current expects
            floorplan_data = {
                'plot_width': params.get('plot_width', 40),
                'plot_height': params.get('plot_height', 30),
                'rooms': params.get('rooms', []),
                'walls': params.get('walls', []),
                'labels': params.get('labels', []),
                'windows': params.get('windows', []),
                'doors': params.get('doors', [])
            }
            
            corridor_width = params.get('corridor_width', 3)
            ga_config = params.get('ga_config', None)
            
            # Create UI object for output storage
            from GPLAN.pythongui.GuiParameters import GuiParameters
            ui = GuiParameters(graph=None)
            
            # Call the GA handler
            success = handle_ga_optimization(
                ui=ui,
                floorplan_data=floorplan_data,
                corridor_width=corridor_width,
                ga_config=ga_config
            )
            
            if not success:
                builtins.print = original_print
                return {
                    'request_id': request_id,
                    'status': 'error',
                    'engine': 'GA_FloorPlan',
                    'data': {},
                    'error': {'message': ui.get_message()}
                }
            
            # Extract output data
            outputData = ui.get_output_data() if hasattr(ui, 'get_output_data') else []
            if not outputData:
                outputData = []
            
            if not outputData or len(outputData) == 0:
                builtins.print = original_print
                return {
                    'request_id': request_id,
                    'status': 'error',
                    'engine': 'GA_FloorPlan',
                    'data': {},
                    'error': {'message': 'No output data generated'}
                }
            
            result = outputData[0]
            
            # Format response matching temp2.json structure
            response = {
                'request_id': request_id,
                'status': 'success',
                'engine': 'GA_FloorPlan',
                'data': {
                    'floor': {
                        'plot_width': result['plot_width'],
                        'plot_height': result['plot_height']
                    },
                    'ga_optimization': {
                        'status': 'converged',
                        'solution_chromosome': result['ga_solution']
                    },
                    'rooms': result['rooms'],
                    'walls': result['walls'],
                    'labels': result['labels'],
                    'windows': result.get('windows', []),
                    'doors': result.get('doors', []),
                    'layout_matrix': result['layout_matrix']
                },
                'error': {}
            }
            
            builtins.print = original_print
            return response
            
        except Exception as e:
            builtins.print = original_print
            import traceback
            traceback.print_exc()
            return {
                'request_id': request_data.get('request_id', 'unknown'),
                'status': 'error',
                'engine': 'GA_FloorPlan',
                'data': {},
                'error': {'message': str(e)}
            }
