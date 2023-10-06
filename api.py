
"""API

Generates floorplamns for given graph data as input.
Current support only for rectangular floorplans.
A running example is available.

"""
from .source import inputgraph as inputgraph


def graph_to_rfp(input_data, normalize_const=40, limit=100000):
    """Generates a rfp for given graph data

    Args:
        input_data: A dictionary containing keys:
            nodes: Node data of the graph.
            edges: Edge data of the graph.
        normalize_const: (optional) Normalize height, width, top, left to this
        limit: (optional) Limit no. of RFPs to these many

    Returns:
        output_data: A list containing multiple or single floorplan.
            Each floorplan is a list of dictionary where each dictionary denotes a room.
    """
    nodecnt = len(input_data['nodes'])
    edgecnt = len(input_data['edges'])
    edgedata = []
    for edge in input_data['edges']:
        edgedata.append([edge['source'], edge['target']])
    node_coordinates = []
    for node in input_data['nodes']:
        node_coordinates.append([node['x'], node['y']])
    graph = inputgraph.InputGraph(nodecnt, edgecnt, edgedata, node_coordinates)
    output_data = []
    graph.irreg_multiple_dual()
    for idx in range(min(graph.fpcnt, limit)):
        output_fp = []
        for node in input_data['nodes']:
            output_fp.append({
                "id": node["id"],
                "label": node["label"],
                "color": node["color"],
                "left": int(graph.room_x[idx][node["id"]] * normalize_const),
                "top": int(graph.room_y[idx][node["id"]] * normalize_const),
                "width": int(graph.room_width[idx][node["id"]] * normalize_const),
                "height": int(graph.room_height[idx][node["id"]] * normalize_const)
            })
        for cnt in range(len(graph.mergednodes[idx])):
            output_fp.append({
                "id": graph.mergednodes[idx][cnt],
                "label": input_data['nodes'][graph.irreg_nodes1[idx][cnt]]["label"],
                "color": input_data['nodes'][graph.irreg_nodes1[idx][cnt]]["color"],
                "left": int(graph.room_x[idx][graph.mergednodes[idx][cnt]] * normalize_const),
                "top": int(graph.room_y[idx][graph.mergednodes[idx][cnt]] * normalize_const),
                "width": int(graph.room_width[idx][graph.mergednodes[idx][cnt]] * normalize_const),
                "height": int(graph.room_height[idx][graph.mergednodes[idx][cnt]] * normalize_const)
            })
        output_data.append(output_fp)
    return output_data


if __name__ == "__main__":
    input_data = {
        "nodes": [
            {"id": 0, "label": "kitchen", "x": 14, "y": 20, "color": "#e7e7e7","width_min": 2,"width_max": 4,"height_min": 2,"height_max": 6},
            {"id": 1, "label": "living room", "x": 25, "y": 20, "color": "#e7e7e7","width_min": 2,"width_max": 4,"height_min": 2,"height_max": 6},
            {"id": 2, "label": "rotunda", "x": 20, "y": 30, "color": "#e7e7e7","width_min": 2,"width_max": 4,"height_min": 2,"height_max": 6}],
        "edges": [
            {"source": 0, "target": 1},
            {"source": 1, "target": 2},
            {"source": 2, "target": 0}],
    "fp_type": "multiple",
    "rectangular": "false"
    }
    print(graph_to_rfp(input_data))

    input_data = {
        "nodes": [
            {"id": 0, "label": "kitchen", "x": 14, "y": 20, "color": "#e7e7e7"},
            {"id": 1, "label": "living room", "x": 25, "y": 20, "color": "#e7e7e7"},
            {"id": 2, "label": "rotunda", "x": 20, "y": 30, "color": "#e7e7e7"}],
        "edges": [
            {"source": 0, "target": 1},
            {"source": 1, "target": 2},
            {"source": 2, "target": 0}],
    }
    print(graph_to_rfp(input_data))

    input_data = {
        "nodes": [
            {"id": 0, "label": "kitchen", "x": 14, "y": 20, "color": "#e7e7e7"},
            {"id": 1, "label": "living room", "x": 25, "y": 20, "color": "#e7e7e7"},
            {"id": 2, "label": "rotunda", "x": 20, "y": 30, "color": "#e7e7e7"},
            {"id": 3, "label": "rotunda", "x": 20, "y": 25, "color": "#e7e7e7"}],
        "edges": [
            {"source": 0, "target": 1},
            {"source": 1, "target": 2},
            {"source": 2, "target": 0},
            {"source": 0, "target": 3},
            {"source": 1, "target": 3},
            {"source": 2, "target": 3}],
    }

    print(graph_to_rfp(input_data))
