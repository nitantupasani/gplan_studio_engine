import tkinter as tk

def gui_non_adj(ui):
    """Creates the GUI to accept non-adjacency list for edges that should not be added.

    Returns:
        non_adj_list: A list of tuples representing edges that should not be added.
    """

    non_adj_list = []

    root = tk.Toplevel()

    root.title('Non-Adjacency List')
    
    # Size of default GUI window 
    root.geometry('400x300')
    
    label = tk.Label(root, text="Enter the non-adjacency list (e.g., (3,4), (5,6)):", font=("Times New Roman", 13))
    label.pack(pady=10)

    input_var = tk.StringVar()
    input_entry = tk.Entry(root, textvariable=input_var, width=40)
    input_entry.pack(pady=10)

    def submit_clicked():
        nonlocal non_adj_list
        input_str = input_var.get()
        try:
            # Convert input string to list of tuples
            non_adj_list = eval(f"[{input_str}]")
            #print("Non-Adjacency List:", non_adj_list)
        except:
            print("Invalid input format. Please enter a list of tuples.")
        
        root.destroy()

    submit_button = tk.Button(root, text='Submit', command=submit_clicked)
    submit_button.pack(pady=20)

    root.wait_window(root)
    
    return non_adj_list

# To test the GUI creation
if __name__ == "__main__":
    gui_non_adj()
