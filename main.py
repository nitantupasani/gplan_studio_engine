"""Main file of the project
"""

import warnings

from GPLAN.handlers import *
from GPLAN.pythongui.GuiParameters import GuiParameters

gclass: gui.gui_class
ui: GuiParameters


def run():
    warnings.filterwarnings("ignore")

    while (gclass.command != "end"):
        ui = GuiParameters(gclass)
        gclass.output_data = []
        if (gclass.command == "dissection"):
            make_dissection_corridor(gclass)
        else:
            graph = inputgraph.InputGraph(ui.get_noOfNodes()
                                          , ui.get_edgeCount()
                                          , ui.get_edges()
                                          , ui.get_nodeCoordinates())
            ui.set_graph(graph)
            nxgraph = nx.from_numpy_array(graph.matrix)
            graph.coordinates = nx.planar_layout(nxgraph)
            nx.draw_networkx(nxgraph,graph.coordinates , label=None,node_size=400 ,node_color='#4b8bc8',font_size=12, font_color='k', font_family='sans-serif', font_weight='normal', alpha=1, bbox=None, ax=None)
            plt.figure()
            graphtemp = nx.from_numpy_array(graph.matrix)
            nx.draw_networkx(graphtemp,graph.coordinates, label='After retriangulation',node_size=400 ,node_color='#4b8bc8',font_size=12, font_color='k', font_family='sans-serif', font_weight='normal', alpha=1, bbox=None, ax=None)
            plt.show()
            if not graph.is_connected():#Check if the graph is connected or not
                gclass.command = 'not_connected'
                
            origin = 0
            if gclass.command == "circulation":
                handle_circulation(ui, graph, True, gclass)
            elif gclass.command == "single":  # Single Irregular Dual/Floorplan
                handle_single(ui, graph, True, gclass)
            elif gclass.command == "letter_shape":
                handle_letter_shape(ui, graph, True, gclass)
            elif gclass.command == "multiple_l":
                handle_multiple_l(ui, graph, gclass)
            elif gclass.command == "staircase_shaped":
                handle_staircase_shaped(ui, graph, True, gclass)
            elif gclass.command == "multiple":
                handle_multiple(ui, graph, gclass)
            elif gclass.command == "single_oc":
                handle_single_oc(ui, graph, True, gclass)
            elif gclass.command == "multiple_oc":
                handle_multiple_oc(ui, graph, True, gclass)
            elif gclass.command == "poly":
                handle_poly(ui, graph, True, gclass)
            elif gclass.command == "limits":
                handle_limits(ui, graph, True, gclass)
            elif gclass.command == "door_connectivity":
                handle_door_connectivity(ui, graph, True, gclass)
            elif gclass.command == "not_connected":
                pass
            # gclass.time_taken = (end - start) * 1000
            gclass.num_rfp = len(graph.graph_list)
            gclass.pdf_colors = ui.get_roomColors()[0]
            gclass.output_found = 1

        gclass.root.wait_variable(gclass.end)
        gclass.graph_ret()
        gclass.ocan.add_tab()
        gclass.pen = gclass.ocan.getpen()
        gclass.pen.speed(0)


if __name__ == "__main__":
    gclass: gui.gui_class = gui.gui_class()
    ui = GuiParameters(gclass)
    run()
