from api import *
false = False
true = True
import pprint


def post(request, shape):
    starting_from: int = request.data.get("starting_from", 0)
    count: int = request.data.get("count", 0)

    nodes_list: list = request.data.get("nodes", [])
    edges_list: list = request.data.get("edges", [])

    for node in nodes_list:
        if "color" not in node:
            node["color"] = "#1C4C82"
        if "ratio" not in node:
            node["ratio"] = {"max": 99999, "min": 3}

    nodes_list.sort(key=lambda node: node["id"])
    nodes = [[node.get("x", 0), node.get("y", 0)] for node in nodes_list]
    edges = [
        [edge["source"], edge["target"], edge.get("color", "black")]
        for edge in edges_list
        if edge.get("color", "black") == "black"
    ]
    non_adj_edges = [
        (edge["source"], edge["target"])
        for edge in edges_list
        if edge.get("color", "black") == "red"
    ]
    graph: InputGraph = InputGraph(len(nodes), len(edges), edges, nodes)

    rectangular = request.data.get("rectangular", False)
    corridor = request.data.get("corridor", False)
    dimensioned = request.data.get("dimensioned", False)
    dimensioned_circulation = request.data.get("dimensionedCirculation", False)
    min_dim_enabled = request.data.get("minDimEnabled", False)
    remove_add_circulation = request.data.get("removeAddCirculation", False)
    public_enabled = request.data.get("publicEnabled", False)
    normalize_const = request.data.get("normalizeConst", False)
    non_adj = request.data.get("non_adj", False)
    limit = request.data.get("limit", FLOORPLAN_LIMIT)
    corridor_thickness = request.data.get("corridorThickness", None)
    circulation_enabled = request.data.get("circulationEnabled", 0)

    documentID = request.data.get("documentID", None)
    name = request.data.get("name", None)

    if len(non_adj_edges) == 0:
        non_adj = False

    dim_inputs = {
        "min_width": [],
        "max_width": [],
        "min_height": [],
        "max_height": [],
        "min_ratio": [],
        "max_ratio": [],
        "plot_width": -1,
        "plot_height": -1,
        "symmetric": False,
        "optimal_floorplan": 0,
        "rotation_enabled": 1,
    }
    if dimensioned or min_dim_enabled:
        for node in nodes_list:
            if node["width"] is not None:
                if dimensioned:
                    min_width = (
                        node["width"]["min"]
                        if node["width"]["min"] is not None
                        or node["width"]["min"] != "none"
                        else 0
                    )
                elif min_dim_enabled:
                    min_width = (
                        node["width"]["min"]
                        if node["width"]["min"] is not None
                        or node["width"]["min"] != "none"
                        else 3
                    )
                dim_inputs["min_width"].append(min_width)
                max_width = (
                    node["width"]["max"]
                    if node["width"]["max"] is not None
                    or node["width"]["max"] != "none"
                    else 99999
                )
                dim_inputs["max_width"].append(max_width)
            if node["height"] is not None:
                if dimensioned:
                    min_height = (
                        node["height"]["min"]
                        if node["height"]["min"] is not None
                        or node["height"]["min"] != "none"
                        else 0
                    )
                elif min_dim_enabled:
                    min_height = (
                        node["height"]["min"]
                        if node["height"]["min"] is not None
                        or node["height"]["min"] != "none"
                        else 3
                    )
                dim_inputs["min_height"].append(min_height)
                max_height = (
                    node["height"]["max"]
                    if node["height"]["max"] is not None
                    or node["height"]["max"] != "none"
                    else 99999
                )
                dim_inputs["max_height"].append(max_height)
            if node["ratio"] is not None:
                min_ratio = (
                    node["ratio"]["min"]
                    if node["ratio"]["min"] is not None
                    or node["ratio"]["min"] != "none"
                    else 0.5
                )
                dim_inputs["min_ratio"].append(min_ratio)
                max_ratio = (
                    node["ratio"]["max"]
                    if node["ratio"]["max"] is not None
                    or node["ratio"]["max"] != "none"
                    else 2
                )
                dim_inputs["max_ratio"].append(max_ratio)
        dim_inputs["plot_width"] = request.data.get("plot_width", 0)
        dim_inputs["plot_height"] = request.data.get("plot_height", 0)
        dim_inputs["symmetric"] = request.data.get("symmetric", False)
        dim_inputs["optimal_floorplan"] = request.data.get("optimal_floorplan", 1)
        dim_inputs["rotation_enabled"] = request.data.get("rotation_enabled", 1)

    try:
        floorplans, message = Documents.get_floorplans(
            starting_from=starting_from,
            count=count,
            caller=shape,
            nodes_list=nodes_list,
            graph=graph,
            edges_list=edges,
            non_adj_edge_list=non_adj_edges,
            rectangular=rectangular,
            corridor=corridor,
            dimensioned=dimensioned,
            dimensionedCirculation=dimensioned_circulation,
            minDimEnabled=min_dim_enabled,
            removeAddCirculation=remove_add_circulation,
            publicEnabled=public_enabled,
            nonAdj=non_adj,
            normalize_const=normalize_const,
            limit=limit,
            corridor_thickness=corridor_thickness,
            documentID=documentID,
            name=name,
            dim_inputs=dim_inputs,
            circulationEnabled=circulation_enabled,
        )
        pprint.pprint(floorplans.to_dict())
        pprint.pp(f"MESSAGE: {message}")

    except Exception as e:
      pprint.pp(str(e))




if __name__ == '__main__':
    sample ={"rectangular":true,"corridor":false,"dimensioned":false,"non_adj":true,"dimensionedCirculation":false,"minDimEnabled":true,"removeAddCirculation":false,"publicEnabled":false,"normalizeConst":true,"limit":10,"starting_from":0,"count":10,"nodes":[{"id":0,"label":"1","height":{"min":5.0,"max":99999},"width":{"min":5.0,"max":99999},"color":"#1C4C82"},{"id":1,"label":"2","height":{"min":5.0,"max":99999},"width":{"min":5.0,"max":99999},"color":"#1C4C82"}],"edges":[{"source":0,"target":1,"color":"black"}],"corridorThickness":0.5,"plot_width":10,"plot_height":10}
    
class Request:
  def __init__(self, data):
      self.data = data

sample = Request(sample)
post(sample,'door_connectivity')