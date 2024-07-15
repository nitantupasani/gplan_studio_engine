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
        gclass.root.wait_variable(gclass.end)
        gclass.graph_ret()
        gclass.ocan.add_tab()
        gclass.pen = gclass.ocan.getpen()
        gclass.pen.speed(0)


if __name__ == "__main__":
    gclass: gui.gui_class = gui.gui_class()
    ui = GuiParameters(gclass)
    run()
