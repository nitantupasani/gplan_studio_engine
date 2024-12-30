from api import *
false = False
true = True

def post(request, shape):
        starting_from: int = request.get('starting_from', 0)
        count: int = request.get('count', 1)

        nodes_list: list = request.get('nodes', [])
        edges_list: list = request.get('edges', [])

        nodes_list.sort(key=lambda node: node['id'])
        nodes = [[node['x'], node['y']] for node in nodes_list]
        edges = [[edge['source'], edge['target'],edge.get('color','black')] for edge in edges_list]
        non_adj_edges = [[edge['source'], edge['target']] for edge in edges_list if edge.get('color', 'black') == 'red']
        graph: InputGraph = InputGraph(len(nodes), len(edges), edges, nodes)

        rectangular = request.get('rectangular', False)
        corridor = request.get('corridor', False)
        dimensioned = request.get('dimensioned', False)
        dimensioned_circulation = request.get('dimensionedCirculation', False)
        min_dim_enabled = request.get('minDimEnabled', False)
        remove_add_circulation = request.get('removeAddCirculation', False)
        public_enabled = request.get('publicEnabled', False)
        normalize_const = request.get('normalizeConst', False)
        non_adj = request.get('non_adj', False)
        limit = request.get('limit', FLOORPLAN_LIMIT)
        corridor_thickness = request.get('corridorThickness', None)
        documentID = request.get('documentID', None)
        name = request.get('name', None)
        dim_inputs = {
            "min_width": [],
            "max_width": [],
            "min_height": [],
            "max_height": [],
            "min_ratio": [],
            "max_ratio": [],
            "plot_width": 0,
            "plot_height": 0,
            "symmetric": False,
            "optimal_floorplan": 0
        }
        if dimensioned or min_dim_enabled:
            dim_inputs["plot_width"] = request.get('plot_width', 0)
            dim_inputs["plot_height"] = request.get('plot_height', 0)
            for node in nodes_list:
                if node['width'] is not None:
                    if dimensioned:
                        min_width = node['width']['min'] if node['width']['min'] is not None or node['width'][
                            'min'] != "none" else 0
                    elif min_dim_enabled:
                        min_width = node['width']['min'] if node['width']['min'] is not None or node['width'][
                            'min'] != "none" else 3
                    dim_inputs['min_width'].append(min_width)
                    max_width = node['width']['max'] if node['width']['max'] is not None or node['width'][
                        'max'] != "none" else 99999
                    dim_inputs['max_width'].append(max_width)
                if node['height'] is not None:
                    if dimensioned:
                        min_height = node['height']['min'] if node['height']['min'] is not None or node['height'][
                            'min'] != "none" else 0
                    elif min_dim_enabled:
                        min_height = node['height']['min'] if node['height']['min'] is not None or node['height'][
                            'min'] != "none" else 3
                    dim_inputs['min_height'].append(min_height)
                    max_height = node['height']['max'] if node['height']['max'] is not None or node['height'][
                        'max'] != "none" else 99999
                    dim_inputs['max_height'].append(max_height)
                if node['ratio'] is not None:
                    min_ratio = node['ratio']['min'] if node['ratio']['min'] is not None or node['ratio'][
                        'min'] != "none" else 0.5
                    dim_inputs['min_ratio'].append(min_ratio)
                    max_ratio = node['ratio']['max'] if node['ratio']['max'] is not None or node['ratio'][
                        'max'] != "none" else 2
                    dim_inputs['max_ratio'].append(max_ratio)
            dim_inputs['plot_width'] = request.get('plot_width', 0)
            dim_inputs['plot_height'] = request.get('plot_height', 0)
            dim_inputs['symmetric'] = request.get('symmetric', False)
            dim_inputs['optimal_floorplan'] = request.get('optimal_floorplan', True)  # Default is set

        floorplans, message = Documents.get_floorplans(
            starting_from=starting_from,
            count=count,
            caller=shape,
            nodes_list=nodes_list,
            graph=graph,
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
            edges_list=edges,
            non_adj_edge_list=non_adj_edges
        )
        import pprint
        pprint.pprint(floorplans.to_dict())
        pprint.pp(f"MESSAGE: {message}")





if __name__ == '__main__':
    sample ={
  "rectangular": true,
  "corridor": false,
  "dimensioned": false,
  "non_adj": true,
  "dimensionedCirculation": false,
  "minDimEnabled": true,
  "removeAddCirculation": false,
  "publicEnabled": false,
  "normalizeConst": true,
  "limit": 10,
  "corridorThickness": 0.5,
  "starting_from": 0,
  "count": 10,
  "nodes": [
    {
      "id": 0,
      "x": 580,
      "y": 320,
      "label": "1(Dining)",
      "color": "#1C4C82",
      "width": {
        "max": 99999,
        "min": 8
      },
      "height": {
        "max": 99999,
        "min": 6
      },
      "ratio": {
        "max": 3,
        "min": 3
      }
    },
    {
      "id": 1,
      "x": 900,
      "y": 360,
      "label": "2(Kitchen)",
      "color": "#1C4C82",
      "width": {
        "max": 99999,
        "min": 6
      },
      "height": {
        "max": 99999,
        "min": 10
      },
      "ratio": {
        "max": 3,
        "min": 3
      }
    },
    {
      "id": 2,
      "x": 600,
      "y": 580,
      "label": "3(Bedroom)",
      "color": "#1C4C82",
      "width": {
        "max": 99999,
        "min": 12
      },
      "height": {
        "max": 99999,
        "min": 14
      },
      "ratio": {
        "max": 3,
        "min": 3
      }
    },
    {
      "id": 3,
      "x": 260,
      "y": 480,
      "label": "4(Bathroom)",
      "color": "#1C4C82",
      "width": {
        "max": 99999,
        "min": 7
      },
      "height": {
        "max": 99999,
        "min": 5
      },
      "ratio": {
        "max": 3,
        "min": 3
      }
    },
    {
      "id": 4,
      "x": 240,
      "y": 220,
      "label": "5(WC)",
      "color": "#1C4C82",
      "width": {
        "max": 99999,
        "min": 4
      },
      "height": {
        "max": 99999,
        "min": 6
      },
      "ratio": {
        "max": 3,
        "min": 3
      }
    },
    {
      "id": 5,
      "x": 540,
      "y": 120,
      "label": "6(Bedroom)",
      "color": "#1C4C82",
      "width": {
        "max": 99999,
        "min": 11
      },
      "height": {
        "max": 99999,
        "min": 11
      },
      "ratio": {
        "max": 3,
        "min": 3
      }
    }
  ],
  "edges": [
    {
      "source": 0,
      "target": 4
    },
    {
      "source": 2,
      "target": 3
    },
    {
      "source": 2,
      "target": 0
    },
    {
      "source": 0,
      "target": 1
    },
    {
      "source": 0,
      "target": 5
    },
    {
      "source": 5,
      "target": 4
    },
    {
      "source": 2,
      "target": 5
    }
  ],
  "plot_width": 20,
  "plot_height": 20
}
    post(sample,'door_connectivity')