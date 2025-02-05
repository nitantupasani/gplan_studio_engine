import tkinter as tk

from GPLAN.pythongui.GuiParameters import DimParameters

def gui_fnc(ui,old_dims, nodes, room_name = [] , gclass=None):
    """Creates the GUI to accept minimun dimensions for room width and height and returns the read values. 

    Args:
        old_dims: A list containing the initial values for minimun width and height for each room. They may also include the initial values for the plot width and height.
        nodes: Number of nodes in the graph.
        room_name: A list of the room labels for each room.

    Returns:
        min_width: A list containing minimum width for each room in the floorplan.
        min_height: A list containing minimum height for each room in the floorplan.
        plot_width: Input width of the plot for the floorplan.
        plot_height: Input height of the plot for the floorplan.
    """

    if gclass == None:
        dim_parameters : DimParameters = ui.get_min_dim_inputs()
        return dim_parameters.get_min_width(), dim_parameters.get_min_height(), dim_parameters.get_plot_width(), dim_parameters.get_plot_height(), dim_parameters.get_isOptimalEnabled(),dim_parameters.get_isRotationAllowed()

    min_width = []
    min_height = []

    root = tk.Toplevel()

    root.title('Minimum Room Dimensions')
    
    # Size of default GUI window 
    root.geometry(str(650) + 'x' + str(400))
    
    Upper_right = tk.Label(root, text="Enter minimum dimensions required for each room", font=("Times New Roman", 13))

    Upper_right.place(relx=0.70,
                      rely=0.1,
                      anchor='ne')

    text_head_width = []
    text_head_height = []
    text_room = []
    width_textbox = []
    height_textbox = []
    default_width = []
    default_height = []

    # Support for free dimensions feature
    plot_height = tk.IntVar(root, 0)
    plot_width = tk.IntVar(root, 0)
    optimal_floorplan = tk.IntVar(root)
    allow_rotation = tk.IntVar(root)
    
    for i in range(0, nodes):
        i_value_x = 0
        i_value_y = i
        default_width.append(tk.IntVar(value=old_dims[0][i]))
        default_height.append(tk.IntVar(value=old_dims[1][i]))

        if (i_value_y == 0):
            # Placing headers for Minimum Width and Height
            text_head_width.append("text_head_width_" + str(i_value_x + 1))
            text_head_width[i_value_x] = tk.Label(root, text="Min Width", font=("Times New Roman", 10)) 
            text_head_width[i_value_x].place(relx=0.32 + 0.20 * i_value_x,
                                             rely=0.2,
                                             anchor='ne')
            text_head_height.append("text_head_height_" + str(i_value_x + 1))
            text_head_height[i_value_x] = tk.Label(root, text="Min Height", font=("Times New Roman", 10))
            text_head_height[i_value_x].place(relx=0.52 + 0.20 * i_value_x,
                                            rely=0.2,
                                            anchor='ne')
            
        # Placing headers for Rooms
        if len(room_name) > 0:
            text_room.append("text_room_" + str(room_name[i]))
            text_room[i] = tk.Label(root, text=str(room_name[i]), font=("Times New Roman", 10))
            text_room[i].place(relx=0.20 + 0.30 * i_value_x,
                            rely=0.3 + (0.04 * i_value_y),
                            anchor='ne')
        else:
            text_room.append("text_room_" + str(i))
            text_room[i] = tk.Label(root, text="Room" + str(i), font=("Times New Roman", 10))
            text_room[i].place(relx=0.20 + 0.30 * i_value_x,
                            rely=0.3 + (0.04 * i_value_y),
                            anchor='ne')
        
        # Placing text holders for Minimum Width and Height input
        width_textbox.append("width_textbox" + str(i))
        width_textbox[i] = tk.Entry(root, width=5, textvariable=default_width[i])
        width_textbox[i].place(relx=0.30 + 0.30 * i_value_x,
                             rely=0.3 + (0.04) * i_value_y,
                             anchor='ne')
        height_textbox.append("height_textbox" + str(i))
        height_textbox[i] = tk.Entry(root, width=5, textvariable=default_height[i])
        height_textbox[i].place(relx=0.50 + 0.30 * i_value_x,
                            rely=0.3 + (0.04) * i_value_y,
                            anchor='ne')

    # Support for free dimensions feature
    plot_label = tk.Label(root, text="Enter the plot dimensions\n(0 if no limit)", font=("Times New Roman", 10))
    plot_label.place(relx=0.9, rely=0.2, anchor='ne')

    plot_width_label = tk.Label(root, text="Plot Width", font=("Times New Roman", 10))
    plot_width_label.place(relx=0.55, rely=0.3, anchor='nw')

    plot_width_tbox = tk.Entry(root, textvariable=plot_width)
    plot_width_tbox.place(relx=0.98, rely=0.3, anchor='ne')

    plot_height_label = tk.Label(root, text="Plot Height", font=("Times New Roman", 10))
    plot_height_label.place(relx=0.55, rely=0.34, anchor='nw')

    plot_height_tbox = tk.Entry(root, textvariable=plot_height)
    plot_height_tbox.place(relx=0.98, rely=0.34, anchor='ne')

    if len(old_dims) == 4:
        plot_width.set(old_dims[2])
        plot_height.set(old_dims[3])

    # Placing checkbox for generating floorplan with least area
    optimal_floorplan_checkbox = tk.Checkbutton(root, text="Generate Optimal Floorplan", variable=optimal_floorplan, onvalue=1, offvalue=0)
    optimal_floorplan_checkbox.place(relx=0.55, rely=0.4, anchor='nw')

    # Placing checkbox for allowing floorplan rotation
    optimal_floorplan_checkbox = tk.Checkbutton(root, text="Allow Floorplan Rotation", variable=allow_rotation, onvalue=1, offvalue=0)
    optimal_floorplan_checkbox.place(relx=0.55, rely=0.5, anchor='nw')

    def submit_clicked():
        # Helper function for submit button click
        for i in range(0, nodes):
            min_width.append(int(width_textbox[i].get()))
            min_height.append(int(height_textbox[i].get()))
        print("min dimension gui submit button clicked")
        
        root.destroy()

    # Support for free dimensions feature
    '''
    def free_plotsize_func():
        plot_height.set(-1)
        plot_width.set(-1)
    '''

    button = tk.Button(root, text='Submit', padx=5, command=submit_clicked)
    button.place(relx=0.4,
                 rely=0.80,
                 anchor='ne')
    
    # Support for free dimensions feature
    '''
    free_dim_btn = tk.Button(root, text="Free Plot Size", padx=5, command=free_plotsize_func)
    free_dim_btn.place(relx=0.58, rely=0.85, anchor='ne')
    '''

    # destroying the GUI window
    root.wait_window(root)
    
    return min_width, min_height, plot_width.get(), plot_height.get(), optimal_floorplan.get(),allow_rotation.get()


if __name__ == "__main__":
    # main function to test GUI creation
    gui_fnc(None, [], 3, [])
    