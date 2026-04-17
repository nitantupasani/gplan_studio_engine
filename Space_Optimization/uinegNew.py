import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import numpy as np
from negNew import FloorPlan  # Import from your original file
import json
from tkinter import filedialog
import matplotlib.patches as mpatches
from matplotlib.patches import Rectangle
from matplotlib.lines import Line2D
from tkinter import simpledialog
from types import SimpleNamespace
import os

# import matplotlib.patches as mpatches
import math
import matplotlib.path as mpath


def _normalize_polygon_points(points):
    normalized = []
    for pt in points or []:
        if isinstance(pt, (list, tuple)) and len(pt) >= 2:
            normalized.append((float(pt[0]), float(pt[1])))
    if len(normalized) >= 2 and normalized[0] == normalized[-1]:
        normalized = normalized[:-1]
    return normalized


def _point_inside_polygon(x, y, polygon):
    inside = False
    n = len(polygon)
    if n < 3:
        return False
    j = n - 1
    for i in range(n):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        if (yi > y) != (yj > y):
            denom = (yj - yi)
            if denom != 0:
                x_at_y = (xj - xi) * (y - yi) / denom + xi
                if x < x_at_y:
                    inside = not inside
        j = i
    return inside


def _polygon_to_occupied_cells(polygon_points):
    poly = _normalize_polygon_points(polygon_points)
    if len(poly) < 3:
        return []

    min_x = int(min(p[0] for p in poly))
    max_x = int(max(p[0] for p in poly))
    min_y = int(min(p[1] for p in poly))
    max_y = int(max(p[1] for p in poly))

    cells = []
    for cy in range(min_y, max_y):
        for cx in range(min_x, max_x):
            if _point_inside_polygon(cx + 0.5, cy + 0.5, poly):
                cells.append((cx, cy))
    return cells


class CADApp:
    # Replace existing CADApp.__init__(self, parent, callback) with this:
    # In the CADApp class, replace the __init__ method with this corrected version:

    # In the CADApp class in uinegNew.py, replace the entire __init__ method with this one:

    def __init__(self, parent, callback, initial_state=None):
        """
        Initializes the CAD tool, now with all attributes correctly ordered.
        """
        print("[CAD] CADApp.__init__ called; initial_state provided:", bool(initial_state))
        if initial_state and isinstance(initial_state, dict):
            print("[CAD] CADApp.__init__ initial_state keys:", list(initial_state.keys()))

        self.window = tk.Toplevel(parent)
        self.callback = callback
        self.grid_spacing = tk.IntVar(value=1)
        self.grid_spacing_set = False

        # --- START: Consolidated Attribute Initialization (FIX) ---
        # All instance attributes are now initialized here to prevent ordering errors.

        # UI and State attributes
        self.window.title("Enhanced CAD Grid Tool")
        self.window.state('zoomed')
        self.text_input_mode = False
        self.text_entry = None
        self.current_font_size = 12
        self.text_items = []
        self.original_click_handler = None

        # Grid and Drawing attributes
        self.unit_spacing = 1
        self.unit_spacing_prev = 0
        self.pixels_per_unit = 50
        self.dot_radius = 2
        self.mini_x = 999
        self.mini_y = 999
        self.grid_points = []
        self.grid_dots = {}
        self.last_valid_point = None
        self.clicked_coordinates = []
        self.drawn_lines = []
        self.hover_line = None
        self.distance_labels = []
        self.is_closed_shape = False
        self.boundary_closed = False
        self.first_point = None
        self.scaled_coordinates = []
        self.scaled_area_coordinates = []

        # Mode-specific attributes
        self.insertion_mode = False
        self.insertion_start_point = None
        self.insertion_end_point = None
        self.insertion_position = None
        self.temp_coordinates = []

        self.is_area_drawing = False
        self.area_coords = []
        self.final_area = []
        self.scaled_final_area = []
        self.count = 1
        self.done = False
        self.done2 = False

        self.clicked_on_cooridors = False
        self.clicked_on_pillars = False
        self.hidden_dots = set()
        self.stored_coordinates = []

        # Data lists for session state
        self.fixed_names = []
        self.last_regions = []
        self.last_fixed_rooms = []
        self.boundary_state = []

        # Area calculation attributes
        self._ensure_tk_var("remaining_area", tk.IntVar, 0)
        self.old = 0
        self.rooms_area = 0
        # --- END: Consolidated Attribute Initialization ---

        # Build UI & canvas
        self.setup_ui()
        self.create_grid()
        self.bind_events()
        self.window.bind('<Configure>', self.on_window_resize)

        # Restore state passed from the main GUI (in-memory only)
        try:
            if initial_state and isinstance(initial_state, dict):
                self.final_area = list(initial_state.get('final_area') or [])
                self.last_fixed_rooms = list(initial_state.get('last_fixed_rooms') or [])
                self.boundary_state = list(initial_state.get('boundary_state') or [])
                self.fixed_names = list(initial_state.get('fixed_names') or [])
                spacing_val = initial_state.get('unit_spacing')
                if spacing_val is not None:
                    try:
                        spacing_int = int(float(spacing_val))
                    except Exception:
                        spacing_int = 1
                    if spacing_int > 0:
                        self.unit_spacing = spacing_int
                        self.grid_spacing.set(spacing_int)
                        self.grid_spacing_set = True
                        self.unit_spacing_prev = spacing_int
                        self.done2 = True
                ### FIX ###: Load the raw entrance coordinates from the main GUI state
                self.stored_coordinates = list(initial_state.get('entrance_grid_coords') or [])
        except Exception:
            pass

        # Replay/redraw any existing shapes from the current session
        try:
            self.load_initial_state()
        except Exception as e:
            print(f"Error during initial state load: {e}")

    def redraw_entrance(self):
        """Redraws the entrance lines and label from self.stored_coordinates."""
        if not hasattr(self, "canvas") or not self.stored_coordinates or len(self.stored_coordinates) < 2:
            return

        print(f"[CAD] Redrawing entrance with {len(self.stored_coordinates)} points.")
        # Draw the lines
        for i in range(len(self.stored_coordinates) - 1):
            start_point = self.stored_coordinates[i]
            end_point = self.stored_coordinates[i + 1]

            pixel_start_x = start_point[0] * self.pixels_per_unit
            pixel_start_y = start_point[1] * self.pixels_per_unit
            pixel_end_x = end_point[0] * self.pixels_per_unit
            pixel_end_y = end_point[1] * self.pixels_per_unit

            self.canvas.create_line(
                pixel_start_x, pixel_start_y, pixel_end_x, pixel_end_y,
                fill='red', width=2, tags=("replayed", "entrance_line")
            )

        # Draw the label using logic from end_ent
        max_x = max(coord[0] for coord in self.stored_coordinates)
        min_y = min(coord[1] for coord in self.stored_coordinates)
        max_y = max(coord[1] for coord in self.stored_coordinates)
        pixel_min_y = min_y * self.pixels_per_unit
        pixel_max_y = max_y * self.pixels_per_unit

        self.canvas.create_text(
            (max_x - 0.5) * self.pixels_per_unit, (pixel_min_y + pixel_max_y) / 2,
            text="ENTRANCE", fill="red", font=('Arial', 10, 'bold'),
            angle=90, tags=("replayed", "entrance_label")
        )

    def load_initial_state(self):
        """
        Repaints all shapes from the current session state onto the canvas.
        """
        if not hasattr(self, "canvas") or self.canvas is None:
            return

        print("[CAD] Repainting all shapes from current session state...")

        # 1. Redraw the main boundary
        for item in getattr(self, "boundary_state", []):
            if isinstance(item, dict) and item.get("type") == "polygon":
                coords = item.get('coords', [])
                if coords:
                    self.draw_polygon_from_grid_coords(coords, outline="blue", width=2,
                                                       tags=("replayed", "main_boundary"))
                    if item.get('id') == 'main_boundary_shape':
                        self.clicked_coordinates = coords
                        self.drawn_lines = []
                        for i in range(len(coords) - 1):
                            self.drawn_lines.append({'start': coords[i], 'end': coords[i + 1]})

        # 2. Redraw all fixed shapes
        final_area_polygons = getattr(self, "final_area", []) or []
        fixed_shape_names = getattr(self, "fixed_names", []) or []

        print(f"[CAD] Found {len(final_area_polygons)} fixed shapes and {len(fixed_shape_names)} names to redraw.")

        for i, polygon in enumerate(final_area_polygons):
            poly_id = self.draw_polygon_from_grid_coords(polygon, fill="lightgreen", outline="green",
                                                         tags=("fixed_shape",))

            if i < len(fixed_shape_names):
                shape_name = fixed_shape_names[i]
                print(f"Redrawing fixed shape {i}: '{shape_name}'")
                self.add_fixed_room_label_centered(shape_name, grid_coords=polygon, poly_id=poly_id)
            else:
                print(f"Redrawing fixed shape {i}: (No name found)")

        ### FIX ###: Call the new function to redraw the entrance
        self.redraw_entrance()

    # In the CADApp class, ADD this new method:
    def point_inside_polygon(self, x, y, polygon):
        """Check if a point (x, y) is inside a polygon using the ray-casting algorithm."""
        if not polygon:
            return False
        n, inside = len(polygon), False
        p1x, p1y = polygon[0]
        for i in range(1, n + 1):
            p2x, p2y = polygon[i % n]
            if y > min(p1y, p2y) and y <= max(p1y, p2y) and x <= max(p1x, p2x):
                if p1y != p2y:
                    xinters = (y - p1y) * (p2x - p1x) / (p2y - p1y) + p1x
                if p1x == p2x or x <= xinters:
                    inside = not inside
            p1x, p1y = p2x, p2y
        return inside

    # In the CADApp class, ADD this new method:
    def redraw_canvas(self):
        """Clears and redraws the entire canvas from the current state."""
        self.canvas.delete("all")
        self.create_grid()

        # Redraw main boundary lines and labels
        temp_lines = list(self.drawn_lines)
        self.drawn_lines = []
        if self.clicked_coordinates:
            self.last_valid_point = self.clicked_coordinates[0]
            for i in range(len(self.clicked_coordinates) - 1):
                end_point = self.clicked_coordinates[i + 1]
                if any(d['start'] == self.last_valid_point and d['end'] == end_point for d in temp_lines):
                    pixel_x_end = end_point[0] * self.pixels_per_unit
                    pixel_y_end = end_point[1] * self.pixels_per_unit
                    self.draw_line_with_distance(end_point[0], end_point[1], pixel_x_end, pixel_y_end)
                self.last_valid_point = end_point

        # Redraw all fixed shapes
        for i, polygon in enumerate(self.final_area):
            poly_id = self.draw_polygon_from_grid_coords(polygon, fill="lightgreen", outline="green",
                                                         tags=("fixed_shape",))
            if i < len(self.fixed_names):
                self.add_fixed_room_label_centered(self.fixed_names[i], grid_coords=polygon, poly_id=poly_id)

        self.update_point_colors()
        self.update_status()

    def _ensure_tk_var(self, attr_name: str, var_cls, initial_value=None):
        """
        Ensure `self.<attr_name>` exists and is a tk.Variable instance of var_cls.
        If it exists, set its value to initial_value (if provided) instead of replacing the object.
        Usage: self._ensure_tk_var('total_area', tk.IntVar, 0)
        """
        cur = getattr(self, attr_name, None)
        # If current is not a tk.Variable, create one and assign
        if cur is None or not isinstance(cur, tk.Variable):
            try:
                if initial_value is not None:
                    setattr(self, attr_name, var_cls(value=initial_value))
                else:
                    setattr(self, attr_name, var_cls())
            except Exception:
                # fallback to simple constructor if value arg fails
                setattr(self, attr_name, var_cls())
        else:
            # Already exists; set value instead of replacing the variable object
            if initial_value is not None:
                try:
                    cur.set(initial_value)
                except Exception:
                    pass

    def setup_text_controls(self):
        """Add text controls to your existing control_frame"""
        # Add this call in your setup_ui method after creating other buttons

        # Text input button
        ttk.Button(self.control_frame, text="Add Text", command=self.toggle_text_mode).pack(side=tk.LEFT, padx=5)

        # Font size controls frame
        font_frame = ttk.Frame(self.control_frame)
        font_frame.pack(side=tk.LEFT, padx=5)

        ttk.Label(font_frame, text="Font:").pack(side=tk.LEFT)

        # Font size decrease button
        ttk.Button(font_frame, text="-", command=self.decrease_font_size, width=3).pack(side=tk.LEFT, padx=1)

        # Font size label
        self.font_size_label = ttk.Label(font_frame, text=str(self.current_font_size), width=3, relief="sunken")
        self.font_size_label.pack(side=tk.LEFT, padx=1)

        # Font size increase button
        ttk.Button(font_frame, text="+", command=self.increase_font_size, width=3).pack(side=tk.LEFT, padx=1)

    def toggle_text_mode(self):
        """Toggle text input mode on/off"""
        if self.text_input_mode:
            self.exit_text_mode()
        else:
            self.enter_text_mode()

    def enter_text_mode(self):
        """Enter text input mode"""
        self.text_input_mode = True

        # Store the current click handler if any
        self.original_click_handler = self.canvas.bind("<Button-1>")

        # Bind canvas click event for text input
        self.canvas.bind("<Button-1>", self.on_canvas_click_for_text)

        # messagebox.showinfo("Text Mode", "Text mode activated! Click anywhere on the canvas to add text.\nPress Enter to confirm, Escape to cancel.")

    def exit_text_mode(self):
        """Exit text input mode"""
        self.text_input_mode = False

        # Remove text entry if it exists
        if self.text_entry:
            self.text_entry.destroy()
            self.text_entry = None

        # Restore original click handler
        self.bind_events()  # This will rebind your original events

        print("Text mode deactivated")

    def on_canvas_click_for_text(self, event):
        """Handle canvas click in text mode"""
        if self.text_entry:
            # If there's already an entry, destroy it
            self.text_entry.destroy()

        # Get click coordinates
        x = self.canvas.canvasx(event.x)
        y = self.canvas.canvasy(event.y)

        # Create text entry widget at click position
        self.text_entry = tk.Entry(
            self.canvas,
            font=('Arial', self.current_font_size),
            bg="white",
            fg="black",
            insertbackground="black",
            relief="solid",
            borderwidth=1
        )

        # Place the entry on canvas
        self.canvas.create_window(x, y, window=self.text_entry, anchor="center", tags="temp_text_entry")

        # Bind Enter key to confirm text
        self.text_entry.bind("<Return>", lambda e: self.confirm_text(x, y))
        self.text_entry.bind("<Escape>", lambda e: self.cancel_text_entry())

        # Focus on the entry
        self.text_entry.focus_set()

    def confirm_text(self, x, y):
        """Confirm and create permanent text"""
        if self.text_entry:
            text_content = self.text_entry.get().strip()

            if text_content:
                # ✅ Save the last entered text for fixed shape naming
                self.last_text_name = text_content

                # Create permanent text on canvas
                text_item = self.canvas.create_text(
                    x, y,
                    text=text_content,
                    fill="black",
                    font=('Arial', self.current_font_size, 'bold'),
                    tags="permanent_text"
                )

                # Store the text item for management
                self.text_items.append({
                    'item': text_item,
                    'text': text_content,
                    'x': x,
                    'y': y,
                    'font_size': self.current_font_size
                })

                print(f"Added text: '{text_content}' at ({x:.0f}, {y:.0f})")

            # Remove the entry widget
            self.text_entry.destroy()
            self.text_entry = None

            # Remove temporary entry from canvas
            self.canvas.delete("temp_text_entry")

    def cancel_text_entry(self):
        """Cancel text entry"""
        if self.text_entry:
            self.text_entry.destroy()
            self.text_entry = None
            self.canvas.delete("temp_text_entry")

    def increase_font_size(self):
        """Increase font size"""
        if self.current_font_size < 72:  # Max font size limit
            self.current_font_size += 2
            self.font_size_label.config(text=str(self.current_font_size))

    def decrease_font_size(self):
        """Decrease font size"""
        if self.current_font_size > 8:  # Min font size limit
            self.current_font_size -= 2
            self.font_size_label.config(text=str(self.current_font_size))

    def clear_all_text(self):
        """Clear all permanent text"""
        self.canvas.delete("permanent_text")
        self.text_items.clear()
        print("All text cleared!")

    def setup_ui(self):
        main_frame = ttk.Frame(self.window)
        main_frame.pack(fill=tk.BOTH, expand=True)

        control_frame = ttk.Frame(main_frame)
        control_frame.pack(side=tk.TOP, fill=tk.X, pady=5)

        self.control_frame = control_frame

        ttk.Button(control_frame, text="Clear All", command=self.clear_all).pack(side=tk.LEFT, padx=5)
        ttk.Button(control_frame, text="Show Coordinates", command=self.show_coordinates).pack(side=tk.LEFT, padx=5)

        ttk.Label(control_frame, text="Grid Spacing:").pack(side=tk.LEFT, padx=5)
        self.grid_entry = ttk.Entry(control_frame, textvariable=self.grid_spacing, width=10)
        self.grid_entry.pack(side=tk.LEFT, padx=5)
        ttk.Button(control_frame, text="Set Grid Spacing", command=self.get_Grid_space).pack(side=tk.LEFT, padx=5)

        ttk.Button(control_frame, text="Entrance", command=self.draw_ent).pack(side=tk.LEFT, padx=5)
        ttk.Button(control_frame, text="Entrance_END", command=self.end_ent).pack(side=tk.LEFT, padx=5)

        ttk.Button(control_frame, text="Fixed shape", command=self.draw_area).pack(side=tk.LEFT, padx=5)
        ttk.Button(control_frame, text="Corridor", command=self.draw_cooridors).pack(side=tk.LEFT, padx=5)
        ttk.Button(control_frame, text="Pillars", command=self.draw_pillars).pack(side=tk.LEFT, padx=5)
        ttk.Button(control_frame, text="Finalize", command=self.is_finalize2).pack(side=tk.LEFT, padx=5)
        ttk.Button(control_frame, text="Load JSON", command=self.load_json_in_cad).pack(side=tk.LEFT, padx=5)

        self.setup_text_controls()

        # --- Area display controls (ADDED) ---
        # Numeric variables (keeps compatibility with existing code using remaining_area)
        self._ensure_tk_var("total_area", tk.IntVar, 0)
        self._ensure_tk_var("only_rooms_area", tk.IntVar, 0)
        self._ensure_tk_var("remaining_area", tk.IntVar, 0)
        self._ensure_tk_var("remaining_percent", tk.StringVar, "0.0%")

        # Display Total Area
        ttk.Label(control_frame, text="Total Area:", font=("Arial", 14)).pack(side=tk.LEFT, padx=5)
        ttk.Label(control_frame, textvariable=self.total_area, font=("Arial", 14)).pack(side=tk.LEFT, padx=5)

        # Display Remaining Area (existing)
        ttk.Label(control_frame, text="Remaining Area:", font=("Arial", 14)).pack(side=tk.LEFT, padx=5)
        ttk.Label(control_frame, textvariable=self.remaining_area, font=("Arial", 14)).pack(side=tk.LEFT, padx=5)

        # Display Remaining Percentage (NEW)
        ttk.Label(control_frame, text="Remaining %:", font=("Arial", 14)).pack(side=tk.LEFT, padx=5)
        ttk.Label(control_frame, textvariable=self.remaining_percent, font=("Arial", 14)).pack(side=tk.LEFT, padx=5)
        # ------------------------------------------------

        self.remaining_area.set(0)

        self.status_label = ttk.Label(control_frame, text="Enter a positive integer grid spacing to start drawing")
        self.status_label.pack(side=tk.RIGHT, padx=10)

        canvas_frame = ttk.Frame(main_frame)
        canvas_frame.pack(fill=tk.BOTH, expand=True)

        self.window.update_idletasks()
        width = self.window.winfo_width()
        height = self.window.winfo_height() - 100

        self.grid_width_units = max(50, width // self.pixels_per_unit)
        self.grid_height_units = max(30, height // self.pixels_per_unit)

        canvas_width = self.grid_width_units * self.pixels_per_unit + self.pixels_per_unit
        canvas_height = self.grid_height_units * self.pixels_per_unit + self.pixels_per_unit

        self.canvas = tk.Canvas(canvas_frame, bg='white',
                                scrollregion=(-self.pixels_per_unit / 2, -self.pixels_per_unit / 2,
                                              canvas_width, canvas_height))

        print("[CAD] tk.Canvas created, size (units):", self.grid_width_units, self.grid_height_units,
              "pixels_per_unit:", self.pixels_per_unit)

        h_scroll = ttk.Scrollbar(canvas_frame, orient=tk.HORIZONTAL, command=self.canvas.xview)
        v_scroll = ttk.Scrollbar(canvas_frame, orient=tk.VERTICAL, command=self.canvas.yview)
        self.canvas.configure(xscrollcommand=h_scroll.set, yscrollcommand=v_scroll.set)

        self.canvas.grid(row=0, column=0, sticky="nsew")
        h_scroll.grid(row=1, column=0, sticky="ew")
        v_scroll.grid(row=0, column=1, sticky="ns")

        canvas_frame.grid_rowconfigure(0, weight=1)
        canvas_frame.grid_columnconfigure(0, weight=1)

        canvas_frame.grid_rowconfigure(0, weight=1)
        canvas_frame.grid_columnconfigure(0, weight=1)

        # --- Replay any previously-saved shapes now that the tk.Canvas exists ---
        try:
            # show current in-memory sizes (useful for debugging)
            try:
                print(
                    f"[CAD] before replay in-memory sizes: final_area={len(getattr(self, 'final_area', []) or [])}, last_fixed_rooms={len(getattr(self, 'last_fixed_rooms', []) or [])}, boundary_state={len(getattr(self, 'boundary_state', []) or [])}")
            except Exception:
                pass

            # If CAD didn't receive a live initial_state, try reading the persisted fallback file
            try:
                fallback_path = os.path.join(os.getcwd(), "cad_last_state.json")
                if os.path.exists(fallback_path):
                    with open(fallback_path, "r") as _f:
                        file_payload = json.load(_f) or {}
                    # Merge only when in-memory lists are empty so we don't overwrite a fresh programmatic state
                    if (not getattr(self, "final_area", [])) and file_payload.get("final_area"):
                        self.final_area = list(file_payload.get("final_area") or [])
                    if (not getattr(self, "last_fixed_rooms", [])):
                        self.last_fixed_rooms = list(
                            file_payload.get("last_fixed_rooms") or file_payload.get("fixed_rooms") or [])
                    if (not getattr(self, "boundary_state", [])) and file_payload.get("boundary_state"):
                        self.boundary_state = list(file_payload.get("boundary_state") or [])
                    if file_payload:
                        print(
                            f"[CAD] merged fallback cad_last_state.json into in-memory state (final_area={len(self.final_area)})")
            except Exception as e:
                print("[CAD] error reading/merging cad_last_state.json:", e)

            # Finally, replay into the canvas (no-op if lists are empty)
            try:
                # debug: show what we are about to replay
                print(
                    f"[CAD] load_initial_state: final_area={len(getattr(self, 'final_area', []) or [])}, last_fixed_rooms={len(getattr(self, 'last_fixed_rooms', []) or [])}, boundary_state={len(getattr(self, 'boundary_state', []) or [])}")
                self.load_initial_state()
                print("[CAD] load_initial_state() finished")
            except AttributeError:
                print("[CAD] load_initial_state() not found; skipping replay")
            except Exception as e:
                print("[CAD] load_initial_state() error:", e)
        except Exception:
            pass

    # def update_area_stats(self, regions=None, fixed_rooms=None, fixed_area=None):
    #     """
    #     Unified updater for Total Area, Used (rooms+fixed), Remaining Area, and Remaining %.
    #     Works in real units.
    #     """
    #     # --- total region area (real units) ---
    #     regions_list = regions if regions is not None else getattr(self, "last_regions", None) or []
    #     total_region_area = 0.0
    #     try:
    #         for r in regions_list:
    #             if isinstance(r, dict):
    #                 w = float(r.get("width", r.get("w", 0)) or 0)
    #                 h = float(r.get("height", r.get("h", 0)) or 0)
    #             else:
    #                 w = float(getattr(r, "width", 0) or getattr(r, "w", 0) or 0)
    #                 h = float(getattr(r, "height", 0) or getattr(r, "h", 0) or 0)
    #             total_region_area += max(0.0, w * h)
    #     except Exception:
    #         total_region_area = float(getattr(self, "total_area_fallback", 0.0) or 0.0)
    #
    #     # --- fixed shapes total (real units) ---
    #     if fixed_area is not None:
    #         fixed_total = float(fixed_area or 0.0)
    #     else:
    #         fixed_list = fixed_rooms if fixed_rooms is not None else getattr(self, "last_fixed_rooms", None) or []
    #         fixed_total = 0.0
    #         try:
    #             for f in fixed_list:
    #                 if isinstance(f, dict):
    #                     fw = float(f.get("width", f.get("w", 0)) or 0)
    #                     fh = float(f.get("height", f.get("h", 0)) or 0)
    #                 else:
    #                     fw = float(getattr(f, "width", 0) or getattr(f, "w", 0) or 0)
    #                     fh = float(getattr(f, "height", 0) or getattr(f, "h", 0) or 0)
    #                 fixed_total += max(0.0, fw * fh)
    #         except Exception:
    #             fixed_total = 0.0
    #
    #     # --- rooms area (real units) ---
    #     rooms_area = sum(getattr(self, "rooms_area_list", []))  # real units
    #
    #     # --- combine & compute remaining ---
    #     used = rooms_area + fixed_total
    #     remaining = max(0.0, total_region_area - used) if total_region_area > 0 else 0.0
    #     remaining_pct = (remaining / total_region_area * 100.0) if total_region_area > 0 else 0.0
    #
    #     # --- update Tk variables (defensive) ---
    #     try:
    #         if isinstance(getattr(self, "total_area", None), tk.Variable):
    #             self.total_area.set(int(round(total_region_area)))
    #     except Exception:
    #         pass
    #
    #     try:
    #         if isinstance(getattr(self, "only_rooms_area", None), tk.Variable):
    #             # UI label shows used area (rooms + fixed) as you requested earlier
    #             self.only_rooms_area.set(int(round(used)))
    #     except Exception:
    #         pass
    #
    #     try:
    #         if isinstance(getattr(self, "remaining_area", None), tk.Variable):
    #             self.remaining_area.set(int(round(remaining)))
    #     except Exception:
    #         pass
    #
    #     try:
    #         if isinstance(getattr(self, "remaining_percent", None), tk.Variable):
    #             self.remaining_percent.set(f"{remaining_pct:.1f}%")
    #     except Exception:
    #         pass
    #
    #     # cache + debug
    #     self._cached_area_stats = {
    #         "total_region_area": total_region_area,
    #         "fixed_total": fixed_total,
    #         "rooms_area": rooms_area,
    #         "used_area": used,
    #         "remaining_area": remaining,
    #         "remaining_pct": remaining_pct,
    #     }
    #     print(f"[GUI area stats] total={total_region_area} fixed={fixed_total} rooms={rooms_area} "
    #           f"used={used} remaining={remaining} ({remaining_pct:.2f}%)")

    def register_floor_region(self, polygon_coords=None, x=None, y=None, width_units=None, height_units=None):
        """
        Register the main floor region for area statistics.

        - polygon_coords : list of (grid_x, grid_y) points (grid units) - bounding box is computed from these.
        - or provide x,y,width_units,height_units in grid units (width_units and height_units are grid steps).
        The helper converts grid units -> real units via self.unit_spacing and stores into self.last_regions
        as [{'x': x_real, 'y': y_real, 'width': width_real, 'height': height_real}].
        After registering, it calls update_area_stats(...) to refresh the UI labels.

        This method is robust — it prints debug messages if something looks off.
        """
        try:
            # Determine bounding box in grid units
            if polygon_coords and len(polygon_coords) >= 3:
                xs = [int(round(pt[0])) for pt in polygon_coords]
                ys = [int(round(pt[1])) for pt in polygon_coords]
                min_x, max_x = min(xs), max(xs)
                min_y, max_y = min(ys), max(ys)
                width_units = max_x - min_x
                height_units = max_y - min_y
                x_units = min_x
                y_units = min_y
            elif width_units is not None and height_units is not None:
                # x,y may be None -> default to 0
                x_units = int(round(x)) if x is not None else 0
                y_units = int(round(y)) if y is not None else 0
                width_units = int(round(width_units))
                height_units = int(round(height_units))
            else:
                # Nothing sensible to register
                print("register_floor_region: no valid polygon or width/height supplied; skipping registration.")
                return

            # Convert grid units -> real units (units per grid step)
            spacing = float(getattr(self, "unit_spacing", 1) or 1)
            width_real = max(0.0, float(width_units) * spacing)
            height_real = max(0.0, float(height_units) * spacing)
            x_real = float(x_units) * spacing
            y_real = float(y_units) * spacing

            # Save as a single region (you can extend to multiple regions if your UI supports that)
            self.last_regions = [{'x': x_real, 'y': y_real, 'width': width_real, 'height': height_real}]

            print(
                f"[register_floor_region] registered region: x={x_real}, y={y_real}, width={width_real}, height={height_real}")

            # Update UI variables immediately
            try:
                self.update_area_stats(regions=self.last_regions, fixed_rooms=getattr(self, "last_fixed_rooms", None))
            except Exception as e:
                print("register_floor_region: update_area_stats() call failed:", e)

        except Exception as ex:
            print("register_floor_region: unexpected error:", ex)

    def get_Grid_space(self):
        try:
            value = self.grid_spacing.get()
            if value <= 0:
                messagebox.showerror("Invalid Input", "Grid spacing must be a positive integer.")
                return
            self.unit_spacing = value
            self.grid_spacing.set(value)
            if (not self.done2):
                self.unit_spacing_prev = value
                self.done2 = True
            self.grid_spacing_set = True
            self.update_status()
            print(f"Grid spacing set to: {self.unit_spacing}")
        except tk.TclError:
            messagebox.showerror("Invalid Input", "Please enter a valid integer for grid spacing.")

    def _sync_unit_spacing_from_entry(self, require_positive=False):
        """
        Synchronize self.unit_spacing from the grid spacing entry value.
        If require_positive is True, show an error and return False on invalid input.
        """
        try:
            value = int(self.grid_spacing.get())
        except Exception:
            if require_positive:
                messagebox.showerror("Invalid Input", "Please enter a valid integer for grid spacing.")
            return False

        if value <= 0:
            if require_positive:
                messagebox.showerror("Invalid Input", "Grid spacing must be a positive integer.")
            return False

        changed = value != int(getattr(self, "unit_spacing", 1) or 1)
        self.unit_spacing = value
        self.grid_spacing_set = True
        if (not self.done2):
            self.unit_spacing_prev = value
            self.done2 = True
        elif changed:
            self.unit_spacing_prev = value

        if changed:
            try:
                self.update_status()
            except Exception:
                pass
            print(f"[CAD] Auto-synced grid spacing to {self.unit_spacing} before area operations")

        return True

    def create_grid(self):
        self.grid_points = []
        self.grid_dots = {}

        for grid_x in range(0, self.grid_width_units + 1):
            for grid_y in range(0, self.grid_height_units + 1):
                # Skip dots that are marked as hidden
                if (grid_x, grid_y) in self.hidden_dots:
                    continue

                pixel_x = grid_x * self.pixels_per_unit
                pixel_y = grid_y * self.pixels_per_unit

                dot = self.canvas.create_oval(
                    pixel_x - self.dot_radius, pixel_y - self.dot_radius,
                    pixel_x + self.dot_radius, pixel_y + self.dot_radius,
                    fill='gray', outline='gray', tags="grid_dot"
                )

                self.grid_points.append((grid_x, grid_y, pixel_x, pixel_y, dot))
                self.grid_dots[(grid_x, grid_y)] = dot

    def hide_dots_inside_shape(self, area_coords):
        """Find and mark grid dots inside the closed shape to be hidden."""
        if not area_coords or len(area_coords) < 3:  # Need at least 3 points for a polygon
            return

        # Convert area_coords (list of (grid_x, grid_y) to pixel coordinates)
        pixel_coords = [(x * self.pixels_per_unit, y * self.pixels_per_unit) for x, y in area_coords]
        polygon = mpath.Path(pixel_coords)

        # Check each grid point
        for grid_x in range(0, self.grid_width_units + 1):
            for grid_y in range(0, self.grid_height_units + 1):
                pixel_x = grid_x * self.pixels_per_unit
                pixel_y = grid_y * self.pixels_per_unit

                # Check if point is strictly inside (not on boundary)
                # Use a small offset to test if point is truly inside
                test_points = [
                    (pixel_x + 0.1, pixel_y),
                    (pixel_x - 0.1, pixel_y),
                    (pixel_x, pixel_y + 0.1),
                    (pixel_x, pixel_y - 0.1)
                ]

                # If the point and all nearby test points are inside, then it's truly interior
                if (polygon.contains_point((pixel_x, pixel_y)) and
                        all(polygon.contains_point(tp) for tp in test_points)):
                    self.hidden_dots.add((grid_x, grid_y))

        # Recreate the grid to apply hidden dots
        print("Dots hidden")
        self.recreate_grid()

    def bind_events2(self):
        self.canvas.bind("<Button-1>", self.on_click2)
        self.canvas.bind("<Button-3>", self.on_right_click2)
        self.canvas.bind("<Motion>", self.on_hover2)

    def bind_events3(self):
        self.canvas.bind("<Button-1>", self.on_click3)
        self.canvas.bind("<Button-3>", self.on_right_click)
        self.canvas.bind("<Motion>", self.on_hover3)

    def on_click3(self, event):
        if not self.grid_spacing_set:
            messagebox.showinfo("Grid Spacing Required", "Please set a valid grid spacing before drawing.")
            return

        x, y = self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)
        closest_point = self.find_closest_point(x, y)

        if closest_point:
            grid_x, grid_y = closest_point[0], closest_point[1]
            pixel_x, pixel_y = closest_point[2], closest_point[3]

            # Check if this is a valid orthogonal move (only if there's a previous point)
            valid_move = True
            if self.stored_coordinates:
                last_grid_x, last_grid_y = self.stored_coordinates[-1]
                dx = abs(grid_x - last_grid_x)
                dy = abs(grid_y - last_grid_y)

                # Only allow orthogonal moves
                if not ((dx == 0 and dy != 0) or (dx != 0 and dy == 0)):
                    valid_move = False
                    messagebox.showinfo("Invalid Move", "You can only move in straight lines (up, down, left, right).")
                    return

            # Store the coordinates in a list for later use
            if (grid_x, grid_y) not in self.stored_coordinates:
                self.stored_coordinates.append((grid_x, grid_y))
                print(
                    f"Stored: Grid({grid_x}, {grid_y}) = Units({grid_x * self.unit_spacing}, {grid_y * self.unit_spacing})")

                # Draw permanent line and distance if there's a previous point
                if len(self.stored_coordinates) > 1:
                    # Get the previous point
                    prev_grid_x, prev_grid_y = self.stored_coordinates[-2]
                    prev_pixel_x = prev_grid_x * self.pixels_per_unit
                    prev_pixel_y = prev_grid_y * self.pixels_per_unit

                    # Create permanent line
                    self.canvas.create_line(
                        prev_pixel_x, prev_pixel_y, pixel_x, pixel_y,
                        fill=(
                            'red'  # if self.clicked_on_cooridors
                            # else 'purple' if self.clicked_on_pillars
                            # else 'green'
                        ),
                        width=2, tags="permanent_line"  # Made it slightly thicker and permanent tag
                    )

                    # Calculate and display permanent distance
                    distance = self.calculate_distance((prev_grid_x, prev_grid_y), (grid_x, grid_y))
                    mid_x = (prev_pixel_x + pixel_x) / 2
                    mid_y = (prev_pixel_y + pixel_y) / 2
                    self.canvas.create_text(
                        mid_x + 10, mid_y - 10, text=f"{distance:.0f}",
                        fill=(
                            'red'  # if self.clicked_on_cooridors
                            # else 'purple' if self.clicked_on_pillars
                            # else 'green'
                        ),
                        font=('Arial', 9, 'bold'), tags="permanent_distance"
                    )

            # Draw a point to visualize the click
            self.canvas.create_oval(pixel_x - 3, pixel_y - 3, pixel_x + 3, pixel_y + 3, fill="red", tags="point")

            self.update_status()

    # def on_hover3(self, event):
    #     x, y = self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)
    #     closest_point = self.find_closest_point(x, y)

    #     # Clear previous hover highlight
    #     self.canvas.delete("hover_point")

    #     if closest_point:
    #         pixel_x, pixel_y = closest_point[2], closest_point[3]
    #         # Highlight the closest grid point
    #         self.canvas.create_oval(pixel_x - 5, pixel_y - 5, pixel_x + 5, pixel_y + 5, fill="red", tags="hover_point")

    #         # Update status with grid coordinates
    #         grid_x, grid_y = closest_point[0], closest_point[1]
    #         self.status_label.config(text=f"Grid: ({grid_x}, {grid_y}) | Units: ({grid_x * self.unit_spacing}, {grid_y * self.unit_spacing})")
    #     else:
    #         self.status_label.config(text="Hover outside grid")

    def on_hover3(self, event):
        if not self.grid_spacing_set:
            return

        x, y = self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)
        closest_point = self.find_closest_point(x, y)

        # Clear previous hover highlights and lines
        self.canvas.delete("hover_point")
        if self.hover_line:
            self.canvas.delete(self.hover_line)
            self.canvas.delete("hover_distance")
            self.hover_line = None

        if closest_point:
            grid_x, grid_y = closest_point[0], closest_point[1]
            pixel_x, pixel_y = closest_point[2], closest_point[3]

            # Check if we should show hover effects
            show_hover = True

            # If there is a last clicked point, check if current hover is in orthogonal direction only
            if self.stored_coordinates:
                last_grid_x, last_grid_y = self.stored_coordinates[-1]

                # Calculate differences
                dx = abs(grid_x - last_grid_x)
                dy = abs(grid_y - last_grid_y)

                # Only show hover if it's orthogonal (straight up, down, left, right)
                # This means either dx=0 and dy!=0, or dx!=0 and dy=0 (but not both non-zero)
                if not ((dx == 0 and dy != 0) or (dx != 0 and dy == 0)):
                    show_hover = False

            if show_hover:
                # Highlight the closest grid point
                self.canvas.create_oval(pixel_x - 5, pixel_y - 5, pixel_x + 5, pixel_y + 5, fill="red",
                                        tags="hover_point")

                # If there is a last clicked point, draw a temporary line and show distance
                if self.stored_coordinates:
                    last_grid_x, last_grid_y = self.stored_coordinates[-1]
                    last_pixel_x = last_grid_x * self.pixels_per_unit
                    last_pixel_y = last_grid_y * self.pixels_per_unit

                    # Draw temporary dashed line to hovered point
                    self.hover_line = self.canvas.create_line(
                        last_pixel_x, last_pixel_y, pixel_x, pixel_y,
                        fill=(
                            'red' if self.clicked_on_cooridors
                            else 'purple' if self.clicked_on_pillars
                            else 'green'
                        ),
                        width=1, dash=(5, 5), tags="hover_line"
                    )

                    # Calculate and display distance
                    distance = self.calculate_distance((last_grid_x, last_grid_y), (grid_x, grid_y))
                    mid_x = (last_pixel_x + pixel_x) / 2
                    mid_y = (last_pixel_y + pixel_y) / 2
                    self.canvas.create_text(
                        mid_x + 10, mid_y - 10, text=f"{distance:.0f}",
                        fill=(
                            'red' if self.clicked_on_cooridors
                            else 'purple' if self.clicked_on_pillars
                            else 'green'
                        ),
                        font=('Arial', 9, 'bold'), tags="hover_distance"
                    )

                    # Update status label
                    status_text = (f"Grid: ({grid_x}, {grid_y}) | Units: ({grid_x * self.unit_spacing}, "
                                   f"{grid_y * self.unit_spacing}) | Distance from last point: {distance:.2f} units")
                else:
                    status_text = (f"Grid: ({grid_x}, {grid_y}) | Units: ({grid_x * self.unit_spacing}, "
                                   f"{grid_y * self.unit_spacing}) | No points clicked yet")

                self.status_label.config(text=status_text)
            else:
                # Still show grid coordinates but indicate it's not a valid direction
                status_text = (f"Grid: ({grid_x}, {grid_y}) | Units: ({grid_x * self.unit_spacing}, "
                               f"{grid_y * self.unit_spacing}) | Diagonal direction - not allowed")
                self.status_label.config(text=status_text)
        else:
            self.status_label.config(text="Hover outside grid")

    def draw_line_with_distance3(self, grid_x, grid_y, pixel_x, pixel_y):
        last_pixel_x = self.last_valid_point[0] * self.pixels_per_unit
        last_pixel_y = self.last_valid_point[1] * self.pixels_per_unit

        if self.hover_line:
            self.canvas.delete(self.hover_line)
            self.canvas.delete("hover_distance")
            self.hover_line = None

        line = self.canvas.create_line(
            last_pixel_x, last_pixel_y, pixel_x, pixel_y,
            fill=(
                'red' if self.clicked_on_cooridors
                else 'purple' if self.clicked_on_pillars
                else 'green'
            ),
            width=2, tags="drawn_line"
        )

        distance = self.calculate_distance(self.last_valid_point, (grid_x, grid_y))
        mid_x = (last_pixel_x + pixel_x) / 2
        mid_y = (last_pixel_y + pixel_y) / 2

        distance_label = self.canvas.create_text(
            mid_x + 10, mid_y - 10, text=f"{distance:.0f}",
            fill=(
                'red' if self.clicked_on_cooridors
                else 'purple' if self.clicked_on_pillars
                else 'green'
            ),
            font=('Arial', 9, 'bold'), tags="distance_label"
        )

        self.drawn_lines.append({
            'line': line,
            'distance_label': distance_label,
            'start': self.last_valid_point,
            'end': (grid_x, grid_y)
        })

        self.last_valid_point = (grid_x, grid_y)
        if not self.insertion_mode:
            print(f"Line drawn to ({grid_x}, {grid_y}) - Distance: {distance:.0f} units")

    def on_hover2(self, event):
        if not self.grid_spacing_set or self.last_valid_point is None or self.is_closed_shape:
            return

        x, y = self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)
        closest_point = self.find_closest_point(x, y)

        if closest_point and (closest_point[0], closest_point[1]) != self.last_valid_point:
            if self.hover_line:
                self.canvas.delete(self.hover_line)
                self.canvas.delete("hover_distance")
                self.hover_line = None

            if self.is_aligned(self.last_valid_point, (closest_point[0], closest_point[1])):
                last_pixel_x = self.last_valid_point[0] * self.pixels_per_unit
                last_pixel_y = self.last_valid_point[1] * self.pixels_per_unit

                self.hover_line = self.canvas.create_line(
                    last_pixel_x, last_pixel_y,
                    closest_point[2], closest_point[3],
                    fill=(
                        'red' if self.clicked_on_cooridors
                        else 'purple' if self.clicked_on_pillars
                        else 'green'
                    )
                    , width=1, dash=(5, 5)
                )

                distance = self.calculate_distance(self.last_valid_point, (closest_point[0], closest_point[1]))
                mid_x = (last_pixel_x + closest_point[2]) / 2
                mid_y = (last_pixel_y + closest_point[3]) / 2

                self.canvas.create_text(mid_x, mid_y - 10, text=f"{distance:.0f} units",
                                        fill=(
                                            'red' if self.clicked_on_cooridors
                                            else 'purple' if self.clicked_on_pillars
                                            else 'green'
                                        ),
                                        tags="hover_distance", font=('Arial', 8))
        else:
            if self.hover_line:
                self.canvas.delete(self.hover_line)
                self.canvas.delete("hover_distance")
                self.hover_line = None

    def add_fixed_room_label_centered(self, name, grid_coords=None, poly_id=None):
        """
        Draw the fixed-room name centered inside the polygon immediately.
        - name: string to display
        - grid_coords: list of (grid_x, grid_y) vertices in grid units (optional if poly_id passed)
        - poly_id: optional canvas polygon id (preferred if available)
        Returns (rect_id, text_id) or (None, None).
        """
        try:
            if not hasattr(self, "canvas"):
                return (None, None)
            px_per = float(getattr(self, "pixels_per_unit", 50) or 50)

            # Prefer polygon bbox if poly_id provided
            if poly_id is not None:
                try:
                    bbox = self.canvas.bbox(poly_id)
                    if bbox and len(bbox) == 4:
                        x1, y1, x2, y2 = bbox
                        label_x = (x1 + x2) / 2.0
                        label_y = (y1 + y2) / 2.0
                    else:
                        poly_id = None
                except Exception:
                    poly_id = None

            # Fallback: compute from grid_coords if poly_id unavailable
            if poly_id is None:
                if not grid_coords:
                    return (None, None)
                xs = [p[0] for p in grid_coords]
                ys = [p[1] for p in grid_coords]
                min_x, max_x = min(xs), max(xs)
                min_y, max_y = min(ys), max(ys)
                px_min = min_x * px_per
                px_max = max_x * px_per
                py_min = min_y * px_per
                py_max = max_y * px_per
                label_x = (px_min + px_max) / 2.0
                label_y = (py_min + py_max) / 2.0

            safe_name = str(name).replace(" ", "_")
            tag_name = f"fixed_label_{safe_name}"

            # choose font size based on shape width
            try:
                if poly_id is not None:
                    shape_w_px = abs(x2 - x1)
                else:
                    shape_w_px = max(1, px_max - px_min)
                font_size = max(8, min(18, int(max(8, shape_w_px // 10))))
            except Exception:
                font_size = 12

            text_id = self.canvas.create_text(
                label_x, label_y,
                text=str(name),
                font=('Arial', font_size, 'bold'),
                fill="black",
                tags=("fixed_label", tag_name, "fixed_label_text"),
                anchor="center"
            )

            rect_id = None
            try:
                tbbox = self.canvas.bbox(text_id)
                if tbbox and len(tbbox) == 4:
                    pad = max(2, int(font_size * 0.4))
                    x1t, y1t, x2t, y2t = tbbox
                    rect_id = self.canvas.create_rectangle(
                        x1t - pad, y1t - pad, x2t + pad, y2t + pad,
                        fill="white", outline="", tags=("fixed_label", tag_name, "fixed_label_back")
                    )
                    try:
                        self.canvas.tag_lower(rect_id, text_id)
                    except Exception:
                        pass
            except Exception:
                rect_id = None

            # ensure text is above polygon
            try:
                if poly_id is not None:
                    try:
                        self.canvas.tag_raise(text_id, poly_id)
                        if rect_id:
                            self.canvas.tag_lower(rect_id, text_id)
                    except Exception:
                        pass
                # final safety: raise text to top
                try:
                    self.canvas.tag_raise(text_id)
                    if rect_id:
                        self.canvas.tag_lower(rect_id, text_id)
                except Exception:
                    pass
            except Exception:
                pass

            # track ids for later deletion
            try:
                if not hasattr(self, "fixed_labels"):
                    self.fixed_labels = []
                if rect_id is not None:
                    self.fixed_labels.append(rect_id)
                self.fixed_labels.append(text_id)
            except Exception:
                pass

            return (rect_id, text_id)
        except Exception as e:
            try:
                print("add_fixed_room_label_centered error:", e)
            except Exception:
                pass
            return (None, None)

    def remove_all_fixed_room_labels(self):
        """Remove all labels previously added (call when clearing shapes or reloading)."""
        try:
            if hasattr(self, "canvas"):
                try:
                    self.canvas.delete("fixed_label")
                except Exception:
                    pass
            try:
                self.fixed_labels = []
            except Exception:
                pass
        except Exception:
            pass

    def draw_polygon_from_grid_coords(self, grid_coords, fill=None, outline="black", tags=(), width=1):
        """
        Draw polygon on canvas from grid coords. Returns polygon canvas id.
        grid_coords: list of (gx, gy) pairs (grid units).
        """
        try:
            if not hasattr(self, "canvas"):
                return None
            px = float(getattr(self, "pixels_per_unit", 50) or 50)
            flat = []
            for (gx, gy) in grid_coords:
                flat.append(gx * px)
                flat.append(gy * px)
            try:
                poly_id = self.canvas.create_polygon(flat, fill=fill if fill is not None else "",
                                                     outline=outline, width=width, tags=tags)
                return poly_id
            except Exception as e:
                try:
                    return self.canvas.create_polygon(flat, fill=fill or "", outline=outline, width=width, tags=tags)
                except Exception:
                    print("draw_polygon_from_grid_coords failed:", e)
                    return None
        except Exception as e:
            try:
                print("draw_polygon_from_grid_coords error:", e)
            except Exception:
                pass
            return None

    def add_fixed_room_label_centered(self, name, grid_coords=None, poly_id=None):
        """
        Draw a centered label inside polygon. Returns (rect_id, text_id) or (None,None).
        """
        try:
            if not hasattr(self, "canvas"):
                return (None, None)
            px_per = float(getattr(self, "pixels_per_unit", 50) or 50)

            # Prefer polygon bbox if poly_id provided
            if poly_id is not None:
                try:
                    bbox = self.canvas.bbox(poly_id)
                    if bbox and len(bbox) == 4:
                        x1, y1, x2, y2 = bbox
                        label_x = (x1 + x2) / 2.0
                        label_y = (y1 + y2) / 2.0
                    else:
                        poly_id = None
                except Exception:
                    poly_id = None

            # Fallback to grid_coords
            if poly_id is None:
                if not grid_coords:
                    return (None, None)
                xs = [p[0] for p in grid_coords]
                ys = [p[1] for p in grid_coords]
                min_x, max_x = min(xs), max(xs)
                min_y, max_y = min(ys), max(ys)
                px_min = min_x * px_per
                px_max = max_x * px_per
                py_min = min_y * px_per
                py_max = max_y * px_per
                label_x = (px_min + px_max) / 2.0
                label_y = (py_min + py_max) / 2.0

            safe_name = str(name).replace(" ", "_")
            tag_name = f"fixed_label_{safe_name}"

            try:
                if poly_id is not None:
                    shape_w_px = abs(x2 - x1)
                else:
                    shape_w_px = max(1, px_max - px_min)
                font_size = max(8, min(18, int(max(8, shape_w_px // 10))))
            except Exception:
                font_size = 12

            text_id = self.canvas.create_text(
                label_x, label_y,
                text=str(name),
                font=('Arial', font_size, 'bold'),
                fill="black",
                tags=("fixed_label", tag_name, "fixed_label_text"),
                anchor="center"
            )

            rect_id = None
            try:
                tbbox = self.canvas.bbox(text_id)
                if tbbox and len(tbbox) == 4:
                    pad = max(2, int(font_size * 0.4))
                    x1t, y1t, x2t, y2t = tbbox
                    rect_id = self.canvas.create_rectangle(
                        x1t - pad, y1t - pad, x2t + pad, y2t + pad,
                        fill="white", outline="", tags=("fixed_label", tag_name, "fixed_label_back")
                    )
                    try:
                        self.canvas.tag_lower(rect_id, text_id)
                    except Exception:
                        pass
            except Exception:
                rect_id = None

            try:
                if poly_id is not None:
                    try:
                        self.canvas.tag_raise(text_id, poly_id)
                        if rect_id:
                            self.canvas.tag_lower(rect_id, text_id)
                    except Exception:
                        pass
                try:
                    self.canvas.tag_raise(text_id)
                    if rect_id:
                        self.canvas.tag_lower(rect_id, text_id)
                except Exception:
                    pass
            except Exception:
                pass

            try:
                if not hasattr(self, "fixed_labels"):
                    self.fixed_labels = []
                if rect_id is not None:
                    self.fixed_labels.append(rect_id)
                self.fixed_labels.append(text_id)
            except Exception:
                pass

            return (rect_id, text_id)
        except Exception as e:
            try:
                print("add_fixed_room_label_centered error:", e)
            except Exception:
                pass
            return (None, None)

    def remove_all_fixed_room_labels(self):
        """Delete all labels that were added with add_fixed_room_label_centered."""
        try:
            if hasattr(self, "canvas"):
                try:
                    self.canvas.delete("fixed_label")
                except Exception:
                    pass
            try:
                self.fixed_labels = []
            except Exception:
                pass
        except Exception:
            pass

    def on_click2(self, event):
        if not getattr(self, "grid_spacing_set", False):
            messagebox.showinfo("Grid Spacing Required", "Please set a valid grid spacing before drawing.")
            return

        x, y = self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)
        closest_point = self.find_closest_point(x, y)

        if not closest_point:
            return

        grid_x, grid_y = closest_point[0], closest_point[1]
        pixel_x, pixel_y = closest_point[2], closest_point[3]

        # Check for shape closure
        if (self.first_point is not None and
                (grid_x, grid_y) == self.first_point and
                len(getattr(self, "area_coords", [])) > 2 and
                self.last_valid_point is not None and
                self.is_aligned(self.last_valid_point, (grid_x, grid_y))):
            self.close_shape2(grid_x, grid_y, pixel_x, pixel_y)
            # continue to closed-shape handling below

        # If a closed shape was completed and not in insertion mode: treat as fixed shape
        if getattr(self, "is_closed_shape", False) and not getattr(self, "insertion_mode", False):
            # Snapshot polygon coords (grid units)
            final_coords = getattr(self, "area_coords", []).copy()

            # Prompt user for fixed-shape name
            name = simpledialog.askstring("Fixed shape name", "Enter a name for this fixed shape:",
                                          parent=self.window) or ""
            name = name.strip()

            # Auto-generate name if none provided
            if not name:
                name = f"Fixed{len(self.final_area) + 1}"

            # --- CHANGE: Draw the filled polygon and its label immediately ---
            # Draw the filled polygon on the canvas
            poly_id = self.draw_polygon_from_grid_coords(final_coords, fill="lightgreen", outline="green",
                                                         tags=("fixed_shape",))

            # Draw the centered label on top of the polygon
            self.add_fixed_room_label_centered(name, grid_coords=final_coords, poly_id=poly_id)
            # --- END CHANGE ---

            # Store a copy of polygon coords and name
            self.final_area.append(final_coords)
            self.fixed_names.append(name)

            self.status_label.config(text=f"Shape '{name}' closed. Delete edges or reset to continue.")
            print(f"Added fixed shape '{name}' size is", len(self.final_area))

            self.hide_dots_inside_shape(final_coords)
            self.canvas.update()

            # Reset for a new area drawing
            self.is_closed_shape = False
            self.area_coords = []
            self.last_valid_point = None
            self.first_point = None
            return

        # insertion mode path
        if getattr(self, "insertion_mode", False):
            self.handle_insertion_click2(grid_x, grid_y, pixel_x, pixel_y)
            return

        # Normal point-addition path: add the clicked grid point as polygon vertex
        if not hasattr(self, "area_coords") or self.area_coords is None:
            self.area_coords = []
        self.area_coords.append((grid_x, grid_y))
        print(
            f"Clicked: Grid({grid_x}, {grid_y}) = Units({grid_x * getattr(self, 'unit_spacing', 1)}, {grid_y * getattr(self, 'unit_spacing', 1)})")

        if getattr(self, "last_valid_point", None) is None:
            self.last_valid_point = (grid_x, grid_y)
            if getattr(self, "first_point", None) is None:
                self.first_point = (grid_x, grid_y)
        else:
            if self.is_aligned(self.last_valid_point, (grid_x, grid_y)):
                if (grid_x, grid_y) != self.last_valid_point:
                    self.draw_line_with_distance2(grid_x, grid_y, pixel_x, pixel_y)

        self.update_point_colors()
        self.update_status2()

    def handle_insertion_click2(self, grid_x, grid_y, pixel_x, pixel_y):
        current_point = (grid_x, grid_y)

        if self.last_valid_point is None:
            if current_point == self.insertion_start_point:
                self.last_valid_point = current_point
                self.temp_coordinates = [current_point]
                print(f"Insertion started from: {current_point}")
                self.update_status2()
                return
            else:
                print(f"Must start from the original start point: {self.insertion_start_point}")
                return

        if current_point == self.insertion_end_point:
            self.temp_coordinates.append(current_point)
            self.complete_insertion2(pixel_x, pixel_y)
            return

        if self.is_aligned(self.last_valid_point, current_point):
            if current_point != self.last_valid_point and current_point not in self.temp_coordinates:
                self.temp_coordinates.append(current_point)
                self.draw_line_with_distance2(grid_x, grid_y, pixel_x, pixel_y)
                print(f"Insertion: Line drawn to ({grid_x}, {grid_y})")
        else:
            print("Diagonal point - skipped in insertion mode")

        self.update_point_colors()
        self.update_status()

    def complete_insertion2(self, pixel_x, pixel_y):
        if len(self.temp_coordinates) < 2:
            print("Not enough points for insertion")
            self.cancel_insertion2()
            return

        if self.hover_line:
            self.canvas.delete(self.hover_line)
            self.canvas.delete("hover_distance")
            self.hover_line = None

        start_index = self.area_coords.index(self.insertion_start_point)
        end_index = self.area_coords.index(self.insertion_end_point)

        self.area_coords[start_index:end_index + 1] = self.temp_coordinates

        self.update_affected_lines2(start_index, end_index)

        print(f"Insertion completed! Added {len(self.temp_coordinates) - 2} new coordinates")
        print(f"New coordinates: {self.temp_coordinates[1:-1]}")

        self.insertion_mode = False
        self.insertion_start_point = None
        self.insertion_end_point = None
        self.insertion_position = None
        self.temp_coordinates = []
        self.last_valid_point = self.insertion_end_point

        self.update_status()
        print("Insertion mode ended. You can continue drawing from the end point.")

    def update_affected_lines2(self, start_index, end_index):
        lines_to_remove = []
        for line_data in self.drawn_lines:
            line_start_index = self.area_coords.index(line_data['start'])
            if start_index <= line_start_index < end_index:
                self.canvas.delete(line_data['line'])
                self.canvas.delete(line_data['distance_label'])
                lines_to_remove.append(line_data)

        for line_data in lines_to_remove:
            self.drawn_lines.remove(line_data)

        self.last_valid_point = self.area_coords[start_index]
        for i in range(start_index, start_index + len(self.temp_coordinates) - 1):
            start_point = self.area_coords[i]
            end_point = self.area_coords[i + 1]

            start_pixel_x = start_point[0] * self.pixels_per_unit
            start_pixel_y = start_point[1] * self.pixels_per_unit
            end_pixel_x = end_point[0] * self.pixels_per_unit
            end_pixel_y = end_point[1] * self.pixels_per_unit

            line = self.canvas.create_line(
                start_pixel_x, start_pixel_y, end_pixel_x, end_pixel_y,
                fill='blue', width=2, tags="drawn_line"
            )

            distance = self.calculate_distance(start_point, end_point)
            mid_x = (start_pixel_x + end_pixel_x) / 2
            mid_y = (start_pixel_y + end_pixel_y) / 2

            distance_label = self.canvas.create_text(
                mid_x + 10, mid_y - 10, text=f"{distance:.0f}",
                fill='darkblue', font=('Arial', 9, 'bold'), tags="distance_label"
            )

            self.drawn_lines.append({
                'line': line,
                'distance_label': distance_label,
                'start': start_point,
                'end': end_point
            })
            self.last_valid_point = end_point

        self.update_point_colors()

    def cancel_insertion2(self):
        if self.insertion_mode:
            self.insertion_mode = False
            self.insertion_start_point = None
            self.insertion_end_point = None
            self.insertion_position = None
            self.temp_coordinates = []
            self.last_valid_point = None
            print("Insertion mode cancelled")
            self.update_status()

    def close_shape2(self, grid_x, grid_y, pixel_x, pixel_y):
        self.draw_line_with_distance2(grid_x, grid_y, pixel_x, pixel_y)
        self.is_closed_shape = True
        self.status_label.config(text="Shape closed! Right-click edges to delete them.")
        print("Shape closed!")
        print(self.count, "area drawn")

    def draw_line_with_distance2(self, grid_x, grid_y, pixel_x, pixel_y):
        last_pixel_x = self.last_valid_point[0] * self.pixels_per_unit
        last_pixel_y = self.last_valid_point[1] * self.pixels_per_unit

        if self.hover_line:
            self.canvas.delete(self.hover_line)
            self.canvas.delete("hover_distance")
            self.hover_line = None

        line = self.canvas.create_line(
            last_pixel_x, last_pixel_y, pixel_x, pixel_y,
            fill=(
                'red' if self.clicked_on_cooridors
                else 'purple' if self.clicked_on_pillars
                else 'green'
            ),
            width=2, tags="drawn_line"
        )

        distance = self.calculate_distance(self.last_valid_point, (grid_x, grid_y))
        mid_x = (last_pixel_x + pixel_x) / 2
        mid_y = (last_pixel_y + pixel_y) / 2

        distance_label = self.canvas.create_text(
            mid_x + 10, mid_y - 10, text=f"{distance:.0f}",
            fill=(
                'red' if self.clicked_on_cooridors
                else 'purple' if self.clicked_on_pillars
                else 'green'
            ),
            font=('Arial', 9, 'bold'), tags="distance_label"
        )

        self.drawn_lines.append({
            'line': line,
            'distance_label': distance_label,
            'start': self.last_valid_point,
            'end': (grid_x, grid_y)
        })

        self.last_valid_point = (grid_x, grid_y)
        if not self.insertion_mode:
            print(f"Line drawn to ({grid_x}, {grid_y}) - Distance: {distance:.0f} units")

    def on_right_click2(self, event):
        if not self.grid_spacing_set:
            return

        x, y = self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)

        closest_line = None
        min_distance = float('inf')

        for line_data in self.drawn_lines:
            line_distance = self.distance_to_line2(x, y, line_data)
            if line_distance < 10 and line_distance < min_distance:
                min_distance = line_distance
                closest_line = line_data

        if closest_line:
            self.delete_line2(closest_line)

    def distance_to_line2(self, px, py, line_data):
        start_x = line_data['start'][0] * self.pixels_per_unit
        start_y = line_data['start'][1] * self.pixels_per_unit
        end_x = line_data['end'][0] * self.pixels_per_unit
        end_y = line_data['end'][1] * self.pixels_per_unit

        dx = end_x - start_x
        dy = end_y - start_y

        if dx == 0 and dy == 0:
            return math.sqrt((px - start_x) ** 2 + (py - start_y) ** 2)

        t = max(0, min(1, ((px - start_x) * dx + (py - start_y) * dy) / (dx * dx + dy * dy)))

        closest_x = start_x + t * dx
        closest_y = start_y + t * dy

        return math.sqrt((px - closest_x) ** 2 + (py - closest_y) ** 2)

    def delete_line2(self, line_data):
        self.canvas.delete(line_data['line'])
        self.canvas.delete(line_data['distance_label'])

        start_point = line_data['start']
        end_point = line_data['end']

        start_index = self.area_coords.index(start_point)
        end_index = self.area_coords.index(end_point)

        print(f"Deleted line from {start_point} to {end_point}")

        self.drawn_lines.remove(line_data)

        if end_index == start_index + 1:
            self.insertion_mode = True
            self.insertion_start_point = start_point
            self.insertion_end_point = end_point
            self.insertion_position = start_index
            self.last_valid_point = None

            print(f"Entering insertion mode: Start from {start_point}, end at {end_point}")
            print("Click on the start point to begin inserting new edges")
        else:
            self.reset_drawing_state_after_deletion()

        if self.is_closed_shape:
            self.is_closed_shape = False

        self.update_point_colors()
        self.update_status2()

    def update_status2(self):
        if not self.grid_spacing_set:
            text = "Enter a positive integer grid spacing to start drawing"
        elif self.insertion_mode:
            if self.last_valid_point is None:
                text = f"INSERTION MODE: Click on the start point {self.insertion_start_point} to begin"
            else:
                text = f"INSERTION MODE: Drawing from {self.insertion_start_point} to {self.insertion_end_point} | Points added: {len(self.temp_coordinates) - 1}"
        elif self.is_closed_shape:
            text = "Shape is closed. Right-click edges to delete."

        elif self.last_valid_point is None:
            text = f"Click on any grid point to start drawing (Grid spacing: {self.unit_spacing} units)"
        else:
            text = f"Continue from current point - Points: {len(self.area_coords)} | Lines: {len(self.drawn_lines)}"
        self.status_label.config(text=text)

    def draw_cooridors(self):
        self.clicked_on_cooridors = True
        self.clicked_on_pillars = False

        self.bind_events2()

    def merge(self):

        store_areas = []
        store_areas = self.find_area()

        i = 0
        load_examples_rooms = []
        for i in range(len(self.text_items)):
            area_coords = self.final_area[i]

            # Step 1: Scale points
            scaled_area = [(a * self.unit_spacing, b * self.unit_spacing) for a, b in area_coords]
            print(scaled_area)

            first_coor = scaled_area[0]
            second_corr = scaled_area[1]
            fourth_corr = scaled_area[3]

            height = abs(fourth_corr[1] - first_coor[1])
            width = abs(second_corr[0] - first_coor[0])

            text = self.text_items[i]['text']
            area = store_areas[i]
            temp = (text, width, height, 5, area)

            load_examples_rooms.append(temp)

        print("HI HELLLO ___________............")
        return load_examples_rooms

    def draw_pillars(self):
        self.clicked_on_pillars = True

        self.clicked_on_cooridors = False

        self.merge()

        self.bind_events2()

    def draw_area(self):
        # self.clicked_on_cooridors=False
        # self.clicked_on_pillars=False

        # if(not self.is_closed_shape):
        #     messagebox.showerror("Error", "Draw Your Plot Boundary First.")
        #     return
        print("[CAD] draw_area() clicked; is_area_drawing before flip:", getattr(self, "is_area_drawing", None))

        if (not self.done):
            self.scaled_coordinates.clear()
            for a, b in self.clicked_coordinates:
                scaled_point = (a * self.unit_spacing, b * self.unit_spacing)
                self.scaled_coordinates.append(scaled_point)

            self.mini_x = 999
            self.mini_y = 999
            for a, b in self.scaled_coordinates:
                if (a < self.mini_x):
                    self.mini_x = a
                if (b < self.mini_y):
                    self.mini_y = b

            self.scaled_coordinates = [
                (a - self.mini_x, b - self.mini_y) for a, b in self.scaled_coordinates
            ]

            self.done = True

        self.is_closed_shape = False
        self.temp_coordinates = []

        self.is_closed_shape = False
        self.area_coords = []
        self.last_valid_point = None
        self.first_point = None
        # self.bind_events2()

        self.bind_events2()

        self.last_valid_point = None
        # self.clicked_coordinates = []
        self.drawn_lines = []
        self.hover_line = None
        self.distance_labels = []
        self.is_closed_shape = False
        self.first_point = None
        # self.scaled_coordinates = []

        self.insertion_mode = False
        self.insertion_start_point = None
        self.insertion_end_point = None
        self.insertion_position = None
        self.temp_coordinates = []

        self.is_area_drawing = False
        self.area_coords = []

        # def reset_drawing_state_after_deletion(self):
        #     self.last_valid_point = None
        #     self.first_point = None

        # def point_has_connections(self, point):
        #     for line_data in self.drawn_lines:
        #         if line_data['start'] == point or line_data['end'] == point:
        #             return True
        #     return False

        # def get_connected_points(self):
        #     connected_points = set()
        #     for line_data in self.drawn_lines:
        #         connected_points.add(line_data['start'])
        #         connected_points.add(line_data['end'])
        #     return connected_points

        # def update_point_colors(self):
        #     connected_points = self.get_connected_points()

        #     for point in self.grid_points:
        #         point_coord = (point[0], point[1])

        #         if self.insertion_mode:
        #             if point_coord == self.insertion_start_point:
        #                 self.canvas.itemconfig(point[4], fill='lime', outline='lime')
        #             elif point_coord == self.insertion_end_point:
        #                 self.canvas.itemconfig(point[4], fill='orange', outline='orange')
        #             elif point_coord in connected_points:
        #                 self.canvas.itemconfig(point[4], fill='red', outline='red')
        #             elif point_coord == self.last_valid_point:
        #                 self.canvas.itemconfig(point[4], fill='blue', outline='blue')
        #             else:
        #                 self.canvas.itemconfig(point[4], fill='gray', outline='gray')
        #         else:
        #             if point_coord in connected_points:
        #                 self.canvas.itemconfig(point[4], fill='red', outline='red')
        #             elif (point_coord == self.first_point and
        #                 self.first_point is not None and
        #                 self.first_point != self.last_valid_point and
        #                 len(self.drawn_lines) > 0):
        #                 self.canvas.itemconfig(point[4], fill='green', outline='green')
        #             elif point_coord == self.last_valid_point and self.last_valid_point is not None:
        #                 self.canvas.itemconfig(point[4], fill='red', outline='red')
        #             else:
        #                 self.canvas.itemconfig(point[4], fill='gray', outline='gray')

        # def find_closest_point(self, x, y):
        #     min_dist = float('inf')
        #     closest = None

        #     for point in self.grid_points:
        #         dist = math.sqrt((point[2] - x)**2 + (point[3] - y)**2)
        #         if dist < self.dot_radius * 4 and dist < min_dist:
        #             min_dist = dist
        #             closest = point
        #     return closest

        # def is_aligned(self, p1, p2):
        #     return p1[0] == p2[0] or p1[1] == p2[1]

        # def calculate_distance(self, p1, p2):
        #     grid_distance = abs(p1[0] - p2[0]) + abs(p1[1] - p2[1])
        #     return grid_distance * self.unit_spacing

    def draw_ent(self):
        if (not self.boundary_closed):
            messagebox.showerror("Error", "Draw Your Plot Boundary First.")
            return

        # self.is_closed_shape=False
        # self.temp_coordinates=[]

        # self.is_closed_shape = False
        # self.area_coords = []
        # self.last_valid_point = None
        # self.first_point = None

        self.bind_events3()

    def end_ent(self):
        print("printing begins form here:----")
        print(self.stored_coordinates)

        if self.stored_coordinates:
            # Find the maximum x-coordinate for rightmost point
            max_x = max(coord[0] for coord in self.stored_coordinates)
            min_y = min(coord[1] for coord in self.stored_coordinates)
            max_y = max(coord[1] for coord in self.stored_coordinates)

            # Convert to pixel coordinates
            pixel_max_x = max_x * self.pixels_per_unit
            pixel_min_y = min_y * self.pixels_per_unit
            pixel_max_y = max_y * self.pixels_per_unit

            # Create a single vertical "ENTRANCE" label
            self.canvas.create_text(
                (max_x - 0.5) * self.pixels_per_unit, (pixel_min_y + pixel_max_y) / 2,
                text="ENTRANCE",
                fill="red",
                font=('Arial', 10, 'bold'),
                angle=90,
                tags="entrance_label"
            )

            # BELOW THE CODE TO INPUT THE IMAGE

            # # Load and place the door symbol image to the right
            # from PIL import Image, ImageTk
            # door_image = Image.open("door.png")  # Replace with your image file path
            # door_photo = ImageTk.PhotoImage(door_image)

            # # Position the image slightly to the right of the rightmost point
            # image_x = pixel_max_x + 20  # Offset by 20 pixels to the right
            # image_y = (pixel_min_y + pixel_max_y) / 2  # Center vertically
            # self.canvas.create_image(image_x, image_y, image=door_photo, anchor="center", tags="door_symbol")

            # # Keep a reference to the image to prevent garbage collection
            # self.door_photo = door_photo

    def is_finalize2(self):
        """
        Finalizes the drawing and sends the data back to the main GUI.
        """
        if not self._sync_unit_spacing_from_entry(require_positive=True):
            return

        # --- Always scale the main boundary so Finalize works without Fixed shape ---
        self.scaled_coordinates.clear()
        for a, b in self.clicked_coordinates:
            scaled_point = (a * self.unit_spacing, b * self.unit_spacing)
            self.scaled_coordinates.append(scaled_point)

        self.mini_x = min(p[0] for p in self.scaled_coordinates) if self.scaled_coordinates else 0
        self.mini_y = min(p[1] for p in self.scaled_coordinates) if self.scaled_coordinates else 0

        self.scaled_coordinates = [
            (a - self.mini_x, b - self.mini_y) for a, b in self.scaled_coordinates
        ]
        # -------------------------------------------------------------------

        main_boundary_coords = getattr(self, 'clicked_coordinates', [])
        if main_boundary_coords:
            boundary_id = 'main_boundary_shape'
            if not hasattr(self, 'boundary_state'): self.boundary_state = []
            self.boundary_state = [item for item in self.boundary_state if
                                   not (isinstance(item, dict) and item.get('id') == boundary_id)]
            self.boundary_state.append({
                'type': 'polygon', 'coords': main_boundary_coords, 'id': boundary_id,
                'outline': 'blue', 'width': 2
            })

        self.scaled_final_area = []
        for area_coords in getattr(self, "final_area", []):
            scaled_area = [(a * self.unit_spacing, b * self.unit_spacing) for a, b in area_coords]
            shifted_area = [(a - getattr(self, "mini_x", 0), b - getattr(self, "mini_y", 0)) for a, b in scaled_area]
            if len(shifted_area) >= 3:
                self.scaled_final_area.append(shifted_area)

        fixed_rooms = []
        for idx, poly in enumerate(self.scaled_final_area):
            if poly:
                normalized_poly = _normalize_polygon_points(poly)
                min_x, max_x = min(p[0] for p in normalized_poly), max(p[0] for p in normalized_poly)
                min_y, max_y = min(p[1] for p in normalized_poly), max(p[1] for p in normalized_poly)
                width, height = int(round(max_x - min_x)), int(round(max_y - min_y))
                if width > 0 and height > 0:
                    name = self.fixed_names[idx] if hasattr(self, "fixed_names") and idx < len(
                        self.fixed_names) else f"Fixed{idx + 1}"
                    occupied_cells = _polygon_to_occupied_cells(normalized_poly)
                    fixed_rooms.append(
                        {
                            'name': name,
                            'x': int(round(min_x)),
                            'y': int(round(min_y)),
                            'width': width,
                            'height': height,
                            'is_fixed': True,
                            'max_expansion': 0,
                            'polygon': [[p[0], p[1]] for p in normalized_poly],
                            'occupied_cells': [[c[0], c[1]] for c in occupied_cells]
                        }
                    )

        regions = self.decompose_into_rectangles()
        if not regions:
            messagebox.showerror("Error", "Failed to generate valid regions from boundary.")
            return

        floor_h = max(r.get('y', 0) + r.get('height', 0) for r in regions) if regions else 0
        stored = getattr(self, "stored_coordinates", []) or []
        entrance_units = [
            (x * self.unit_spacing - getattr(self, "mini_x", 0), y * self.unit_spacing - getattr(self, "mini_y", 0)) for
            x, y in stored]
        flipped_entrance_coords = [(ux, float(floor_h) - uy) for ux, uy in
                                   entrance_units] if floor_h else entrance_units

        precise_total_area = self.find_area_plot(self.clicked_coordinates)

        print(f"DEBUG 1 (CADApp): Finalizing with precise_total_area = {precise_total_area}")

        payload_full = {
            'regions': regions, 'fixed_rooms': fixed_rooms, 'entrance_coords': flipped_entrance_coords,
            ### FIX ###: Send the raw grid coordinates back to the main GUI for storage
            'entrance_grid_coords': stored,
            'final_area': getattr(self, 'final_area', []), 'boundary_state': self.boundary_state,
            'fixed_area': getattr(self, 'fixed_area_total', 0.0),
            'fixed_names': getattr(self, 'fixed_names', []),
            'total_area': precise_total_area,
            'unit_spacing': self.unit_spacing
        }

        if callable(self.callback):
            self.callback(**payload_full)

    def load_json_in_cad(self):
        """
        Load a JSON floor plan file directly from the CAD window,
        bypassing the need to draw a boundary first.
        """
        file_path = filedialog.askopenfilename(
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
            title="Load Floor Plan JSON"
        )
        if not file_path:
            return

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            # Send the raw JSON data through the callback so the main GUI
            # can run its full load_floor_plan_json logic.
            if callable(self.callback):
                self.callback(json_load_data=data, json_file_path=file_path)
                self.window.destroy()
        except Exception as e:
            messagebox.showerror("Error", f"Failed to read JSON file:\n{str(e)}")
            import traceback
            traceback.print_exc()

    # ... (Keep all other CADApp methods as they are) ...
    # From line 150 (point_inside_polygon) to line 1860 (is_Finalize)
    # The methods 'point_inside_polygon', 'redraw_canvas', '_ensure_tk_var', etc., do not need changes.
    # The file is very long, so I am omitting the unchanged middle section.
    # The next change is in the FloorPlanGUI class.
    # ...

    def bind_events(self):
        self.canvas.bind("<Button-1>", self.on_click)
        self.canvas.bind("<Button-3>", self.on_right_click)
        self.canvas.bind("<Motion>", self.on_hover)

    def on_window_resize(self, event):
        if event.widget == self.window:
            self.window.after_idle(self.recreate_grid)

    def recreate_grid(self):
        self.canvas.delete("grid_dot")

        width = self.window.winfo_width()
        height = self.window.winfo_height() - 100

        self.grid_width_units = max(50, width // self.pixels_per_unit)
        self.grid_height_units = max(30, height // self.pixels_per_unit)

        canvas_width = self.grid_width_units * self.pixels_per_unit + self.pixels_per_unit
        canvas_height = self.grid_height_units * self.pixels_per_unit + self.pixels_per_unit
        self.canvas.configure(scrollregion=(-self.pixels_per_unit / 2, -self.pixels_per_unit / 2,
                                            canvas_width, canvas_height))

        self.create_grid()

    def on_hover(self, event):
        if not self.grid_spacing_set or self.last_valid_point is None or self.is_closed_shape:
            return

        x, y = self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)
        closest_point = self.find_closest_point(x, y)

        if closest_point and (closest_point[0], closest_point[1]) != self.last_valid_point:
            if self.hover_line:
                self.canvas.delete(self.hover_line)
                self.canvas.delete("hover_distance")
                self.hover_line = None

            if self.is_aligned(self.last_valid_point, (closest_point[0], closest_point[1])):
                last_pixel_x = self.last_valid_point[0] * self.pixels_per_unit
                last_pixel_y = self.last_valid_point[1] * self.pixels_per_unit

                self.hover_line = self.canvas.create_line(
                    last_pixel_x, last_pixel_y,
                    closest_point[2], closest_point[3],
                    fill='lightblue', width=1, dash=(5, 5)
                )

                distance = self.calculate_distance(self.last_valid_point, (closest_point[0], closest_point[1]))
                mid_x = (last_pixel_x + closest_point[2]) / 2
                mid_y = (last_pixel_y + closest_point[3]) / 2

                self.canvas.create_text(mid_x, mid_y - 10, text=f"{distance:.0f} units",
                                        fill='blue', tags="hover_distance", font=('Arial', 8))
        else:
            if self.hover_line:
                self.canvas.delete(self.hover_line)
                self.canvas.delete("hover_distance")
                self.hover_line = None

    def on_click(self, event):
        if not self.grid_spacing_set:
            messagebox.showinfo("Grid Spacing Required", "Please set a valid grid spacing before drawing.")
            return

        x, y = self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)
        closest_point = self.find_closest_point(x, y)

        if closest_point:
            grid_x, grid_y = closest_point[0], closest_point[1]
            pixel_x, pixel_y = closest_point[2], closest_point[3]

            if self.is_closed_shape and not self.insertion_mode:
                self.status_label.config(text="Shape is closed. Delete edges or reset to continue.")
                print(self.clicked_coordinates)
                self.old = self.find_area_plot(self.clicked_coordinates)
                self.remaining_area.set(self.old)
                return

            if self.insertion_mode:
                self.handle_insertion_click(grid_x, grid_y, pixel_x, pixel_y)
                return

            if (self.first_point is not None and
                    (grid_x, grid_y) == self.first_point and
                    len(self.clicked_coordinates) > 2 and
                    self.last_valid_point is not None and
                    self.is_aligned(self.last_valid_point, (grid_x, grid_y))):
                self.close_shape(grid_x, grid_y, pixel_x, pixel_y)
                return

            self.clicked_coordinates.append((grid_x, grid_y))
            print(
                f"Clicked: Grid({grid_x}, {grid_y}) = Units({grid_x * self.unit_spacing}, {grid_y * self.unit_spacing})")

            if self.last_valid_point is None:
                self.last_valid_point = (grid_x, grid_y)
                if self.first_point is None:
                    self.first_point = (grid_x, grid_y)
                print(f"Starting from grid point: ({grid_x}, {grid_y})")
            else:
                if self.is_aligned(self.last_valid_point, (grid_x, grid_y)):
                    if (grid_x, grid_y) != self.last_valid_point:
                        self.draw_line_with_distance(grid_x, grid_y, pixel_x, pixel_y)
                else:
                    print("Diagonal point - skipped")

            self.update_point_colors()
            self.update_status()

    def handle_insertion_click(self, grid_x, grid_y, pixel_x, pixel_y):
        current_point = (grid_x, grid_y)

        if self.last_valid_point is None:
            if current_point == self.insertion_start_point:
                self.last_valid_point = current_point
                self.temp_coordinates = [current_point]
                print(f"Insertion started from: {current_point}")
                self.update_status()
                return
            else:
                print(f"Must start from the original start point: {self.insertion_start_point}")
                return

        if current_point == self.insertion_end_point:
            self.temp_coordinates.append(current_point)
            self.complete_insertion(pixel_x, pixel_y)
            return

        if self.is_aligned(self.last_valid_point, current_point):
            if current_point != self.last_valid_point and current_point not in self.temp_coordinates:
                self.temp_coordinates.append(current_point)
                self.draw_line_with_distance(grid_x, grid_y, pixel_x, pixel_y)
                print(f"Insertion: Line drawn to ({grid_x}, {grid_y})")
        else:
            print("Diagonal point - skipped in insertion mode")

        self.update_point_colors()
        self.update_status()

    def complete_insertion(self, pixel_x, pixel_y):
        if len(self.temp_coordinates) < 2:
            print("Not enough points for insertion")
            self.cancel_insertion()
            return

        if self.hover_line:
            self.canvas.delete(self.hover_line)
            self.canvas.delete("hover_distance")
            self.hover_line = None

        start_index = self.clicked_coordinates.index(self.insertion_start_point)
        end_index = self.clicked_coordinates.index(self.insertion_end_point)

        self.clicked_coordinates[start_index:end_index + 1] = self.temp_coordinates

        self.update_affected_lines(start_index, end_index)

        print(f"Insertion completed! Added {len(self.temp_coordinates) - 2} new coordinates")
        print(f"New coordinates: {self.temp_coordinates[1:-1]}")

        self.insertion_mode = False
        self.insertion_start_point = None
        self.insertion_end_point = None
        self.insertion_position = None
        self.temp_coordinates = []
        self.last_valid_point = self.insertion_end_point

        self.update_status()
        print("Insertion mode ended. You can continue drawing from the end point.")

    def update_affected_lines(self, start_index, end_index):
        lines_to_remove = []
        for line_data in self.drawn_lines:
            line_start_index = self.clicked_coordinates.index(line_data['start'])
            if start_index <= line_start_index < end_index:
                self.canvas.delete(line_data['line'])
                self.canvas.delete(line_data['distance_label'])
                lines_to_remove.append(line_data)

        for line_data in lines_to_remove:
            self.drawn_lines.remove(line_data)

        self.last_valid_point = self.clicked_coordinates[start_index]
        for i in range(start_index, start_index + len(self.temp_coordinates) - 1):
            start_point = self.clicked_coordinates[i]
            end_point = self.clicked_coordinates[i + 1]

            start_pixel_x = start_point[0] * self.pixels_per_unit
            start_pixel_y = start_point[1] * self.pixels_per_unit
            end_pixel_x = end_point[0] * self.pixels_per_unit
            end_pixel_y = end_point[1] * self.pixels_per_unit

            line = self.canvas.create_line(
                start_pixel_x, start_pixel_y, end_pixel_x, end_pixel_y,
                fill='blue', width=2, tags="drawn_line"
            )

            distance = self.calculate_distance(start_point, end_point)
            mid_x = (start_pixel_x + end_pixel_x) / 2
            mid_y = (start_pixel_y + end_pixel_y) / 2

            distance_label = self.canvas.create_text(
                mid_x + 10, mid_y - 10, text=f"{distance:.0f}",
                fill='darkblue', font=('Arial', 9, 'bold'), tags="distance_label"
            )

            self.drawn_lines.append({
                'line': line,
                'distance_label': distance_label,
                'start': start_point,
                'end': end_point
            })
            self.last_valid_point = end_point

        self.update_point_colors()

    def cancel_insertion(self):
        if self.insertion_mode:
            self.insertion_mode = False
            self.insertion_start_point = None
            self.insertion_end_point = None
            self.insertion_position = None
            self.temp_coordinates = []
            self.last_valid_point = None
            print("Insertion mode cancelled")
            self.update_status()

    def close_shape(self, grid_x, grid_y, pixel_x, pixel_y):
        self.draw_line_with_distance(grid_x, grid_y, pixel_x, pixel_y)
        self.is_closed_shape = True
        self.boundary_closed = True
        self.status_label.config(text="Shape closed! Right-click edges to delete them.")
        print("Shape closed!")

        self.old = self.find_area_plot(self.clicked_coordinates)
        self.remaining_area.set(self.old)

    def draw_line_with_distance(self, grid_x, grid_y, pixel_x, pixel_y):
        last_pixel_x = self.last_valid_point[0] * self.pixels_per_unit
        last_pixel_y = self.last_valid_point[1] * self.pixels_per_unit

        if self.hover_line:
            self.canvas.delete(self.hover_line)
            self.canvas.delete("hover_distance")
            self.hover_line = None

        line = self.canvas.create_line(
            last_pixel_x, last_pixel_y, pixel_x, pixel_y,
            fill='blue', width=2, tags="drawn_line"
        )

        distance = self.calculate_distance(self.last_valid_point, (grid_x, grid_y))
        mid_x = (last_pixel_x + pixel_x) / 2
        mid_y = (last_pixel_y + pixel_y) / 2

        distance_label = self.canvas.create_text(
            mid_x + 10, mid_y - 10, text=f"{distance:.0f}",
            fill='darkblue', font=('Arial', 9, 'bold'), tags="distance_label"
        )

        self.drawn_lines.append({
            'line': line,
            'distance_label': distance_label,
            'start': self.last_valid_point,
            'end': (grid_x, grid_y)
        })

        self.last_valid_point = (grid_x, grid_y)
        if not self.insertion_mode:
            print(f"Line drawn to ({grid_x}, {grid_y}) - Distance: {distance:.0f} units")

    def on_right_click(self, event):
        if not self.grid_spacing_set:
            return

        x, y = self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)

        # First, check if a line segment was clicked
        closest_line = None
        min_distance = float('inf')
        for line_data in self.drawn_lines:
            line_distance = self.distance_to_line(x, y, line_data)
            if line_distance < 10 and line_distance < min_distance:
                min_distance = line_distance
                closest_line = line_data

        if closest_line:
            self.delete_line(closest_line)
            return

        # If no line was clicked, check for deleting fixed shapes
        grid_x, grid_y = x / self.pixels_per_unit, y / self.pixels_per_unit

        for i in range(len(self.final_area) - 1, -1, -1):
            polygon = self.final_area[i]
            if self.point_inside_polygon(grid_x, grid_y, polygon):
                shape_name = self.fixed_names[i] if i < len(self.fixed_names) else "this shape"
                if messagebox.askyesno("Delete Shape", f"Are you sure you want to delete {shape_name}?"):
                    del self.final_area[i]
                    if i < len(self.fixed_names):
                        del self.fixed_names[i]
                    self.redraw_canvas()
                return

    def distance_to_line(self, px, py, line_data):
        start_x = line_data['start'][0] * self.pixels_per_unit
        start_y = line_data['start'][1] * self.pixels_per_unit
        end_x = line_data['end'][0] * self.pixels_per_unit
        end_y = line_data['end'][1] * self.pixels_per_unit

        dx = end_x - start_x
        dy = end_y - start_y

        if dx == 0 and dy == 0:
            return math.sqrt((px - start_x) ** 2 + (py - start_y) ** 2)

        t = max(0, min(1, ((px - start_x) * dx + (py - start_y) * dy) / (dx * dx + dy * dy)))

        closest_x = start_x + t * dx
        closest_y = start_y + t * dy

        return math.sqrt((px - closest_x) ** 2 + (py - closest_y) ** 2)

    def delete_line(self, line_data):
        self.canvas.delete(line_data['line'])
        self.canvas.delete(line_data['distance_label'])

        start_point = line_data['start']
        end_point = line_data['end']

        start_index = self.clicked_coordinates.index(start_point)
        end_index = self.clicked_coordinates.index(end_point)

        print(f"Deleted line from {start_point} to {end_point}")

        self.drawn_lines.remove(line_data)

        if end_index == start_index + 1:
            self.insertion_mode = True
            self.insertion_start_point = start_point
            self.insertion_end_point = end_point
            self.insertion_position = start_index
            self.last_valid_point = None

            print(f"Entering insertion mode: Start from {start_point}, end at {end_point}")
            print("Click on the start point to begin inserting new edges")
        else:
            self.reset_drawing_state_after_deletion()

        if self.is_closed_shape:
            self.is_closed_shape = False

        self.update_point_colors()
        self.update_status()

    def reset_drawing_state_after_deletion(self):
        self.last_valid_point = None
        self.first_point = None

    def point_has_connections(self, point):
        for line_data in self.drawn_lines:
            if line_data['start'] == point or line_data['end'] == point:
                return True
        return False

    def get_connected_points(self):
        connected_points = set()
        for line_data in self.drawn_lines:
            connected_points.add(line_data['start'])
            connected_points.add(line_data['end'])
        return connected_points

    def update_point_colors(self):
        connected_points = self.get_connected_points()

        for point in self.grid_points:
            point_coord = (point[0], point[1])

            if self.insertion_mode:
                if point_coord == self.insertion_start_point:
                    self.canvas.itemconfig(point[4], fill='lime', outline='lime')
                elif point_coord == self.insertion_end_point:
                    self.canvas.itemconfig(point[4], fill='orange', outline='orange')
                elif point_coord in connected_points:
                    self.canvas.itemconfig(point[4], fill='red', outline='red')
                elif point_coord == self.last_valid_point:
                    self.canvas.itemconfig(point[4], fill='blue', outline='blue')
                else:
                    self.canvas.itemconfig(point[4], fill='gray', outline='gray')
            else:
                if point_coord in connected_points:
                    self.canvas.itemconfig(point[4], fill='red', outline='red')
                elif (point_coord == self.first_point and
                      self.first_point is not None and
                      self.first_point != self.last_valid_point and
                      len(self.drawn_lines) > 0):
                    self.canvas.itemconfig(point[4], fill='green', outline='green')
                elif point_coord == self.last_valid_point and self.last_valid_point is not None:
                    self.canvas.itemconfig(point[4], fill='red', outline='red')
                else:
                    self.canvas.itemconfig(point[4], fill='gray', outline='gray')

    def find_closest_point(self, x, y):
        min_dist = float('inf')
        closest = None
        for point in self.grid_points:
            dist = math.sqrt((point[2] - x) ** 2 + (point[3] - y) ** 2)
            if dist < self.dot_radius * 4 and dist < min_dist:
                min_dist = dist
                closest = point
        return closest

    def is_aligned(self, p1, p2):
        return p1[0] == p2[0] or p1[1] == p2[1]

    def calculate_distance(self, p1, p2):
        grid_distance = abs(p1[0] - p2[0]) + abs(p1[1] - p2[1])
        return grid_distance * self.unit_spacing

    def clear_all(self):
        self.old = 0
        self.remaining_area.set(0)

        self.canvas.delete("all")

        # Reset all data structures holding shape info
        self.final_area = []
        self.last_fixed_rooms = []
        self.fixed_names = []
        self.clicked_coordinates = []
        self.drawn_lines = []
        self.distance_labels = []
        self.stored_coordinates = []
        self.text_items = []
        self.hidden_dots.clear()

        # Reset drawing state variables
        self.last_valid_point = None
        self.first_point = None
        self.is_closed_shape = False
        self.hover_line = None

        self.insertion_mode = False

        if self.text_input_mode:
            self.exit_text_mode()

        self.recreate_grid()
        self.bind_events()
        self.update_status()
        print("All cleared!")

    def is_Finalize(self):
        # if not self.is_closed_shape:
        #     messagebox.showerror("Error", "Please close the shape before finalizing.")
        #     return

        self.scaled_coordinates.clear()
        for a, b in self.clicked_coordinates:
            scaled_point = (a * self.unit_spacing, b * self.unit_spacing)
            self.scaled_coordinates.append(scaled_point)

        mini_x = 999
        mini_y = 999
        for a, b in self.scaled_coordinates:
            if (a < mini_x):
                mini_x = a
            if (b < mini_y):
                mini_y = b

        self.scaled_coordinates = [
            (a - mini_x, b - mini_y) for a, b in self.scaled_coordinates
        ]

        # Convert boundary to regions
        regions = self.decompose_into_rectangles()
        if regions:
            # Send regions back to main GUI and close CAD window
            self.callback(regions)
            # self.window.destroy()
        else:
            messagebox.showerror("Error", "Failed to generate valid regions from boundary.")

    def decompose_into_rectangles(self):
        """
        Decomposes the main polygon into rectangular regions, correctly excluding fixed shape areas.
        """
        self.regions = []

        main_polygon = self.scaled_coordinates
        if not main_polygon or len(main_polygon) < 3:
            return []

        # Get all unique x and y coordinates from the main boundary and all fixed shapes
        all_coords = list(main_polygon)
        if hasattr(self, 'scaled_final_area'):
            for area in self.scaled_final_area:
                all_coords.extend(area)

        x_coords = sorted(list(set(p[0] for p in all_coords)))
        y_coords = sorted(list(set(p[1] for p in all_coords)))

        # Create a grid of cells and check if the center of each cell is valid
        for i in range(len(x_coords) - 1):
            for j in range(len(y_coords) - 1):
                x_start, x_end = x_coords[i], x_coords[i + 1]
                y_start, y_end = y_coords[j], y_coords[j + 1]

                width, height = x_end - x_start, y_end - y_start
                if width <= 0 or height <= 0:
                    continue

                # Test the center point of the cell
                mid_x, mid_y = x_start + width / 2, y_start + height / 2

                # Check if the point is inside the main boundary
                if not self.point_inside_polygon(mid_x, mid_y, main_polygon):
                    continue

                # Check if the point is inside any of the fixed shapes (excluded areas)
                is_excluded = False
                if hasattr(self, 'scaled_final_area'):
                    for area in self.scaled_final_area:
                        if self.point_inside_polygon(mid_x, mid_y, area):
                            is_excluded = True
                            break

                if not is_excluded:
                    self.regions.append({'x': x_start, 'y': y_start, 'width': width, 'height': height})

        # --- Merge adjacent rectangles ---
        merged = True
        while merged:
            merged = False
            for r1 in self.regions:
                for r2 in self.regions:
                    if r1 == r2: continue

                    # Merge if they share a vertical edge and have the same height
                    if r1['x'] + r1['width'] == r2['x'] and r1['y'] == r2['y'] and r1['height'] == r2['height']:
                        r1['width'] += r2['width']
                        self.regions.remove(r2)
                        merged = True
                        break
                    # Merge if they share a horizontal edge and have the same width
                    if r1['y'] + r1['height'] == r2['y'] and r1['x'] == r2['x'] and r1['width'] == r2['width']:
                        r1['height'] += r2['height']
                        self.regions.remove(r2)
                        merged = True
                        break
                if merged: break

        # Normalize coordinates - flip y-coordinates
        if self.regions:
            max_y = max(r['y'] + r['height'] for r in self.regions)
            for region in self.regions:
                region['y'] = max_y - (region['y'] + region['height'])

        return self.regions

    def show_coordinates(self):
        print("\n=== All Clicked Points ===")
        for i, coords in enumerate(self.clicked_coordinates):
            actual_units = (coords[0] * self.unit_spacing, coords[1] * self.unit_spacing)
            print(f"Point {i + 1}: Grid({coords[0]}, {coords[1]}) = Units{actual_units}")
        print("==========================\n")

        coord_window = tk.Toplevel(self.window)
        coord_window.title("Clicked Coordinates")
        coord_window.geometry("450x400")

        text_widget = tk.Text(coord_window, wrap=tk.WORD, padx=10, pady=10)
        text_widget.pack(fill=tk.BOTH, expand=True)

        text_widget.insert(tk.END, f"All Clicked Points (Unit spacing: {self.unit_spacing}):\n\n")
        for i, coords in enumerate(self.clicked_coordinates):
            actual_units = (coords[0] * self.unit_spacing, coords[1] * self.unit_spacing)
            text_widget.insert(tk.END, f"Point {i + 1}: Grid({coords[0]}, {coords[1]}) = Units{actual_units}\n")

        if self.drawn_lines:
            text_widget.insert(tk.END, f"\nTotal Lines: {len(self.drawn_lines)}\n")
            text_widget.insert(tk.END, "Lines with distances:\n")
            for i, line_data in enumerate(self.drawn_lines):
                distance = self.calculate_distance(line_data['start'], line_data['end'])
                start_units = (line_data['start'][0] * self.unit_spacing, line_data['start'][1] * self.unit_spacing)
                end_units = (line_data['end'][0] * self.unit_spacing, line_data['end'][1] * self.unit_spacing)
                text_widget.insert(tk.END, f"Line {i + 1}: {start_units} → {end_units} = {distance:.0f} units\n")

        text_widget.config(state=tk.DISABLED)

    def update_status(self):
        if not self.grid_spacing_set:
            text = "Enter a positive integer grid spacing to start drawing"
        elif self.insertion_mode:
            if self.last_valid_point is None:
                text = f"INSERTION MODE: Click on the start point {self.insertion_start_point} to begin"
            else:
                text = f"INSERTION MODE: Drawing from {self.insertion_start_point} to {self.insertion_end_point} | Points added: {len(self.temp_coordinates) - 1}"
        elif self.is_closed_shape:
            text = "Shape is closed. Right-click edges to delete."
        elif self.last_valid_point is None:
            text = f"Click on any grid point to start drawing (Grid spacing: {self.unit_spacing} units)"
        else:
            text = f"Continue from current point - Points: {len(self.clicked_coordinates)} | Lines: {len(self.drawn_lines)}"
        self.status_label.config(text=text)

    def find_area(self):

        store_area = []
        scaled_temp = []

        print("THIS IS THE FINAL AREA")
        print(self.final_area)

        for i in range(len(self.text_items)):
            area_coords = self.final_area[i]
            scaled_temp.append([(a * self.unit_spacing, b * self.unit_spacing) for a, b in area_coords])

        # for area_coords in self.final_area:
        #     # scaled_temp.append([])
        #     scaled_temp.append([(a*self.unit_spacing, b*self.unit_spacing) for a,b in area_coords])

        print(scaled_temp)

        for area_coords in scaled_temp:

            if len(area_coords) < 3:
                print("Need at least 3 points to calculate area.")
                return 0

            # Shoelace formula implementation    AND I DON'T KNOW WHATS THIS FORMULA IS CLAUDE GIVE ME THIS FROMULA AND ALL THIS GUI CODE IS GENERATED BE CHATBOTS
            coordinates = area_coords
            n = len(coordinates)
            area = 0

            # Calculate area using shoelace formula
            for i in range(n):
                j = (i + 1) % n
                area += coordinates[i][0] * coordinates[j][1]
                area -= coordinates[j][0] * coordinates[i][1]

            area = abs(area) / 2

            # print(f"Scaled coordinates: {self.scaled_coordinates}")
            # print(f"Calculated area: {area} square units")

            store_area.append(area)

        print("This is the area")
        print(store_area)
        # self.rooms_area=self.rooms_area+area
        return store_area

    def find_area_plot(self, clicked_coordinates):
        print("into the scaled_areas")
        # print(clicked_coordinates)
        # clicked_coordinates=self.clicked_coordinates
        scaled_temp = []

        scaled_temp = [(a * self.unit_spacing, b * self.unit_spacing) for a, b in clicked_coordinates]

        coordinates = scaled_temp
        n = len(coordinates)
        area = 0

        # Calculate area using shoelace formula
        for i in range(n):
            j = (i + 1) % n
            area += coordinates[i][0] * coordinates[j][1]
            area -= coordinates[j][0] * coordinates[i][1]

        area = abs(area) / 2
        print("This is the area", area)
        return area

    def returning_rooms_area(self):
        return self.rooms_area

    def find_area_plot2(self):
        print("into the scaled_areas")
        # print(clicked_coordinates)
        clicked_coordinates = self.clicked_coordinates
        scaled_temp = []

        scaled_temp = [(a * self.unit_spacing, b * self.unit_spacing) for a, b in clicked_coordinates]

        coordinates = scaled_temp
        n = len(coordinates)
        area = 0

        # Calculate area using shoelace formula
        for i in range(n):
            j = (i + 1) % n
            area += coordinates[i][0] * coordinates[j][1]
            area -= coordinates[j][0] * coordinates[i][1]

        area = abs(area) / 2

        return area


class FloorPlanGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Floor Plan Designer")
        self.root.geometry("1200x800")

        self.floor_plan = None
        self.current_screen = "regions"
        self.fixed_names = []
        self.entrance_grid_coords = []
        self.cad_window = None  # <<< ADDED THIS LINE
        self.loaded_json_data = None

        self.main_frame = ttk.Frame(root)
        self.main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        self.nav_frame = ttk.Frame(self.main_frame)
        self.nav_frame.pack(fill=tk.X, pady=(0, 10))

        self.nav_buttons = {}
        self.load_rooms = []
        self.area_coords = []
        self.rooms_area_list = []

        self._ensure_tk_var("remaining_area", tk.IntVar, 0)
        self._ensure_tk_var("total_area", tk.IntVar, 0)
        self.rooms_area = 0
        self.only_room_area = 0
        self._ensure_tk_var("only_rooms_area", tk.IntVar, self.only_room_area)
        self.corridors_area = 0
        self._ensure_tk_var("remaining_percent", tk.StringVar, "0.0%")

        self.plot_area = 0

        nav_items = [
            ("Rooms", "rooms"),
            ("Adjacency", "adjacency"),
            ("Non-Adjacency", "non_adjacency"),
            ("Output", "output")
        ]

        for i, (text, screen) in enumerate(nav_items):
            btn = ttk.Button(self.nav_frame, text=text,
                             command=lambda s=screen: self.show_screen(s))
            btn.pack(side=tk.LEFT, padx=5)
            self.nav_buttons[screen] = btn

        draw_boundary_btn = ttk.Button(self.nav_frame, text="Draw Boundary",
                                       command=self.launch_cad_tool)
        draw_boundary_btn.pack(side=tk.LEFT, padx=5)
        self.nav_buttons["draw_boundary"] = draw_boundary_btn

        ttk.Button(self.nav_frame, text="Generate Floor Plan",
                   command=self.generate_floor_plan,
                   style="Accent.TButton").pack(side=tk.RIGHT, padx=5)

        self.content_frame = ttk.Frame(self.main_frame)
        self.content_frame.pack(fill=tk.BOTH, expand=True)

        self.screens = {}
        self.init_screens()

        self.show_screen("rooms")


    def safe_draw_canvas(self):
        """
        Draw the matplotlib canvas if present, otherwise try to refresh a tkinter.Canvas.
        This avoids AttributeError when self.canvas is a tk.Canvas instead of a FigureCanvas.
        """
        try:
            # Prefer the Matplotlib canvas if it exists and has draw()
            if hasattr(self, "mpl_canvas") and callable(getattr(self.mpl_canvas, "draw", None)):
                try:
                    self.mpl_canvas.draw()
                    return
                except Exception as _:
                    pass

            # Backwards-compatible: if self.canvas is a FigureCanvas with draw()
            if hasattr(self, "canvas") and callable(getattr(self.canvas, "draw", None)):
                try:
                    self.safe_draw_canvas()

                    return
                except Exception:
                    pass

            # Fallback: if self.canvas is a tkinter.Canvas, just update it
            try:
                import tkinter as _tk
                if hasattr(self, "canvas") and isinstance(self.canvas, _tk.Canvas):
                    try:
                        self.canvas.update_idletasks()
                        self.canvas.update()
                    except Exception:
                        pass
            except Exception:
                # if tkinter isn't available for some reason, silently ignore
                pass
        except Exception as e:
            # diagnostic print only (do not crash the app)
            print("safe_draw_canvas error:", e)

    def open_cad(self):
        """
        Open the CAD helper window and pass the main update_area_stats as callback.
        """
        try:
            cad_win = CADApp(self.window, callback=self.update_area_stats)
            self.cad_window = cad_win
        except Exception as e:
            print("open_cad: failed to open CAD window:", e)

    def _ensure_tk_var(self, attr_name: str, var_cls, initial_value=None):
        """
        Ensure `self.<attr_name>` exists and is a tk.Variable instance of var_cls.
        If it exists, set its value to initial_value (if provided) instead of replacing the object.
        Usage: self._ensure_tk_var('total_area', tk.IntVar, 0)
        """
        cur = getattr(self, attr_name, None)
        # If current is not a tk.Variable, create one and assign
        if cur is None or not isinstance(cur, tk.Variable):
            try:
                if initial_value is not None:
                    setattr(self, attr_name, var_cls(value=initial_value))
                else:
                    setattr(self, attr_name, var_cls())
            except Exception:
                # fallback to simple constructor if value arg fails
                setattr(self, attr_name, var_cls())
        else:
            # Already exists; set value instead of replacing the variable object
            if initial_value is not None:
                try:
                    cur.set(initial_value)
                except Exception:
                    pass

    def init_screens(self):
        self.init_regions_screen()
        self.init_rooms_screen()
        self.init_adjacency_screen()
        self.init_non_adjacency_screen()
        self.init_output_screen()

    def init_regions_screen(self):
        frame = ttk.Frame(self.content_frame)
        self.screens["regions"] = frame

        ttk.Label(frame, text="Floor Region Specifications",
                  font=("Arial", 16, "bold")).pack(pady=(0, 20))

        instructions = ttk.Label(frame,
                                 text="Click 'Draw Boundary' to open the CAD tool and draw the floor boundary. Finalize to generate regions.",
                                 wraplength=800)
        instructions.pack(pady=(0, 10))

        # We will still use this frame to show the treeview after the regions are generated
        regions_frame = ttk.LabelFrame(frame, text="Regions", padding=10)
        regions_frame.pack(fill=tk.BOTH, expand=True, pady=10)

        columns = ("X", "Y", "Width", "Height")
        self.regions_tree = ttk.Treeview(regions_frame, columns=columns, show="tree headings", height=8)

        self.regions_tree.heading("#0", text="Region")
        self.regions_tree.column("#0", width=80)
        for col in columns:
            self.regions_tree.heading(col, text=col)
            self.regions_tree.column(col, width=80)

        self.regions_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        regions_scrollbar = ttk.Scrollbar(regions_frame, orient=tk.VERTICAL, command=self.regions_tree.yview)
        regions_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.regions_tree.config(yscrollcommand=regions_scrollbar.set)

        # Move this button outside the region_frame for better separation
        button_frame = ttk.Frame(frame)
        button_frame.pack(fill=tk.X, pady=10)

        ttk.Button(button_frame, text="Draw Boundary", command=self.launch_cad_tool).pack(side=tk.LEFT, padx=5)

        # Add back the clear button, but only show it after a boundary has been drawn.
        self.clear_regions_button = ttk.Button(button_frame, text="Clear All", command=self.clear_regions)
        self.clear_regions_button.pack(side=tk.LEFT, padx=5)
        self.clear_regions_button.pack_forget()  # Initially hide it

    def launch_cad_tool(self):
        """
        Launch CAD, ensuring any previous CAD window is closed first.
        """
        # <<< ADDED THIS BLOCK to check for and destroy the existing window
        if self.cad_window and self.cad_window.winfo_exists():
            self.cad_window.destroy()

        print("[MAIN] launch_cad_tool() called")

        def on_finalize_callback(**payload):
            print("[MAIN] on_finalize_callback invoked; payload keys:", list(payload.keys()))

            # --- Handle JSON load from CAD window ---
            if 'json_load_data' in payload:
                self.root.deiconify()
                self.load_floor_plan_json(preloaded_data=payload['json_load_data'],
                                          preloaded_path=payload.get('json_file_path', ''))
                return

            # Persist all relevant lists from the CAD tool
            if 'final_area' in payload:
                self.final_area = list(payload.get('final_area') or [])
            if 'last_fixed_rooms' in payload:
                self.last_fixed_rooms = list(payload.get('last_fixed_rooms') or [])
            if 'boundary_state' in payload:
                self.boundary_state = list(payload.get('boundary_state') or [])
            if 'fixed_names' in payload:
                self.fixed_names = list(payload.get('fixed_names') or [])
            if 'entrance_grid_coords' in payload:
                self.entrance_grid_coords = list(payload.get('entrance_grid_coords') or [])
            if 'unit_spacing' in payload:
                try:
                    spacing_val = int(float(payload.get('unit_spacing') or 1))
                except Exception:
                    spacing_val = 1
                if spacing_val > 0:
                    self.unit_spacing = spacing_val

            self.update_regions_from_cad(payload)
            self.root.deiconify()

        initial_state = {
            'final_area': getattr(self, 'final_area', []) or [],
            'last_fixed_rooms': getattr(self, 'last_fixed_rooms', []) or [],
            'boundary_state': getattr(self, 'boundary_state', []) or [],
            'fixed_names': getattr(self, 'fixed_names', []) or [],
            'entrance_grid_coords': getattr(self, 'entrance_grid_coords', []) or [],
            'unit_spacing': getattr(self, 'unit_spacing', 1) or 1
        }

        print(
            f"[MAIN] initial_state lengths: final_area={len(initial_state['final_area'])}, fixed_names={len(initial_state['fixed_names'])}")

        # Create the new CADApp instance
        cad_app_instance = CADApp(self.root, on_finalize_callback, initial_state=initial_state)

        # <<< ADDED THIS LINE to store a reference to the new window
        self.cad_window = cad_app_instance.window

        print("[MAIN] CADApp instance created and started")

    def load_cad_fixed_rooms_into_ui(self):
        """
        Populate the Rooms tab with CAD fixed rooms *without* creating FloorPlan objects.
        Call this immediately after you set self.cad_fixed_rooms (i.e. right after CAD import/parse).
        This is idempotent and will remove previously-loaded CAD fixed rows before re-adding.
        """
        try:
            cad_fixed = getattr(self, 'cad_fixed_rooms', []) or []
            if not cad_fixed:
                # clear previously tagged fixed rows (optional)
                try:
                    if hasattr(self, "rooms_tree") and self.rooms_tree is not None:
                        for iid in list(self.rooms_tree.get_children()):
                            try:
                                if "fixed" in self.rooms_tree.item(iid).get("tags", ()):
                                    self.rooms_tree.delete(iid)
                            except Exception:
                                continue
                except Exception:
                    pass
                return

            # remove previously inserted CAD fixed rows (avoid duplicates)
            try:
                if hasattr(self, "rooms_tree") and self.rooms_tree is not None:
                    for iid in list(self.rooms_tree.get_children()):
                        try:
                            if "fixed" in self.rooms_tree.item(iid).get("tags", ()):
                                self.rooms_tree.delete(iid)
                        except Exception:
                            continue
            except Exception:
                pass

            for fr in cad_fixed:
                try:
                    # name fallback
                    name = fr.get('name') or fr.get('id') or f"CAD_{len(fr)}"
                    w = int(fr.get('width', 0) or 0)
                    h = int(fr.get('height', 0) or 0)
                    # create lightweight room-like object for UI functions
                    room_obj = SimpleNamespace(
                        name=name,
                        # default max_expansion to 3 if missing
                        max_expansion=int(fr.get('max_expansion', 3) or 3),
                        width=w,
                        height=h,
                        is_fixed=True,
                        occupied_cells=fr.get('occupied_cells')
                    )
                    # add row to rooms_tree (does not touch your FloorPlan model)
                    try:
                        self.add_fixed_room_to_rooms_tree(room_obj, w, h)
                    except Exception:
                        # fallback direct insertion if helper not available
                        try:
                            if hasattr(self, "rooms_tree") and self.rooms_tree is not None:
                                item = self.rooms_tree.insert("", "end", text=name)
                                try:
                                    self.rooms_tree.set(item, "Width", int(w))
                                    self.rooms_tree.set(item, "Height", int(h))
                                    self.rooms_tree.set(item, "Max Expansion", int(room_obj.max_expansion))
                                    self._set_room_tree_area(item, w, h, room_obj=room_obj)
                                    self.rooms_tree.set(item, "Need Corridor", "Yes")
                                    # tag as fixed
                                    try:
                                        self.rooms_tree.item(item, tags=("fixed",))
                                    except Exception:
                                        pass
                                except Exception:
                                    pass
                        except Exception:
                            pass
                except Exception:
                    continue

            # make sure comboboxes/listboxes show the newly added CAD rooms immediately
            try:
                if hasattr(self, "sync_ui_after_fixed_rooms") and callable(self.sync_ui_after_fixed_rooms):
                    self.sync_ui_after_fixed_rooms()
                else:
                    # conservative fallbacks
                    if hasattr(self, "refresh_room_combos_from_floorplan") and callable(
                            self.refresh_room_combos_from_floorplan):
                        self.refresh_room_combos_from_floorplan()
                    if hasattr(self, "rebuild_room_listboxes") and callable(self.rebuild_room_listboxes):
                        self.rebuild_room_listboxes()
            except Exception:
                pass

            # debug trace
            try:
                print("Loaded CAD fixed rooms into UI:", [fr.get('name') for fr in cad_fixed])
            except Exception:
                pass

        except Exception as e:
            try:
                print("load_cad_fixed_rooms_into_ui error:", e)
            except Exception:
                pass

    def update_regions_from_cad(self, payload_or_regions):
        """
        Handles the data from the CAD tool, preventing duplicate fixed rooms and using precise total area.
        """
        if isinstance(payload_or_regions, dict):
            payload = payload_or_regions
            regions = payload.get('regions', []) or []
            fixed_rooms = payload.get('fixed_rooms', []) or []
            total_area_from_cad = payload.get('total_area')
            ### FIX ###: Store the final (processed) coordinates for visualization
            self.entrance_coords = payload.get('entrance_coords', [])
            print(f"DEBUG 2 (GUI): Received total_area_from_cad = {total_area_from_cad}")
        else:  # Fallback for older format
            regions = payload_or_regions or []
            fixed_rooms = []
            total_area_from_cad = None
            self.entrance_coords = []

        self.clear_regions()

        for i, region in enumerate(regions):
            item = self.regions_tree.insert("", "end", text=f"Region {i + 1}")
            self.regions_tree.set(item, "X", int(region.get('x', 0)))
            self.regions_tree.set(item, "Y", int(region.get('y', 0)))
            self.regions_tree.set(item, "Width", int(region.get('width', 0)))
            self.regions_tree.set(item, "Height", int(region.get('height', 0)))

        for item in self.rooms_tree.get_children():
            if 'fixed' in self.rooms_tree.item(item).get('tags', []):
                self.rooms_tree.delete(item)

        self.cad_fixed_rooms = fixed_rooms or []

        self.load_cad_fixed_rooms_into_ui()

        self.update_area_stats(total_area_override=total_area_from_cad)

        self.show_screen("rooms")

    def init_rooms_screen(self):
        frame = ttk.Frame(self.content_frame)
        self.screens["rooms"] = frame

        ttk.Label(frame, text="Room Specifications",
                  font=("Arial", 16, "bold")).pack(pady=(0, 20))

        instruction_frame = ttk.Frame(frame)
        instruction_frame.pack(fill='x', pady=(0, 10))

        instructions = ttk.Label(instruction_frame,
                                 text="Define rooms with their dimensions and maximum expansion limits.",
                                 wraplength=600)
        instructions.pack()

        area_info_frame = ttk.Frame(instruction_frame)
        area_info_frame.pack(side='right')

        # Total area row
        total_frame = ttk.Frame(area_info_frame)
        total_frame.pack(fill='x')
        ttk.Label(total_frame, text="Total Area:", font=("Arial", 10)).pack(side='left')
        ttk.Label(total_frame, textvariable=self.total_area, font=("Arial", 10)).pack(side='left')

        # Room area row
        room_area_frame = ttk.Frame(area_info_frame)
        room_area_frame.pack(fill='x')
        ttk.Label(room_area_frame, text="Room Area:", font=("Arial", 10)).pack(side='left')
        ttk.Label(room_area_frame, textvariable=self.only_rooms_area, font=("Arial", 10)).pack(side='left')

        # Remaining area row
        remaining_frame = ttk.Frame(area_info_frame)
        remaining_frame.pack(fill='x')
        ttk.Label(remaining_frame, text="Remaining Area:", font=("Arial", 10)).pack(side='left')
        ttk.Label(remaining_frame, textvariable=self.remaining_area, font=("Arial", 10)).pack(side='left')

        # Remaining % row (NEW)
        remaining_pct_frame = ttk.Frame(area_info_frame)
        remaining_pct_frame.pack(fill='x')
        ttk.Label(remaining_pct_frame, text="Remaining %:", font=("Arial", 10)).pack(side='left')
        ttk.Label(remaining_pct_frame, textvariable=self.remaining_percent, font=("Arial", 10)).pack(side='left')

        rooms_frame = ttk.LabelFrame(frame, text="Rooms", padding=10)
        rooms_frame.pack(fill=tk.BOTH, expand=True, pady=10)

        columns = ("Width", "Height", "Max Expansion", "Area", "Need Corridor")
        self.rooms_tree = ttk.Treeview(rooms_frame, columns=columns, show="tree headings", height=8)
        self.rooms_tree.bind("<Double-1>", lambda event: self.edit_room())
        self.rooms_tree.heading("#0", text="Room Name")
        self.rooms_tree.column("#0", width=120)
        for col in columns:
            self.rooms_tree.heading(col, text=col)
            self.rooms_tree.column(col, width=100)

        self.rooms_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        rooms_scrollbar = ttk.Scrollbar(rooms_frame, orient=tk.VERTICAL, command=self.rooms_tree.yview)
        rooms_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.rooms_tree.config(yscrollcommand=rooms_scrollbar.set)

        single_input_frame = ttk.LabelFrame(frame, text="Add Single Room", padding=10)
        single_input_frame.pack(fill=tk.X, pady=5)

        ttk.Label(single_input_frame, text="Name:").grid(row=0, column=0, padx=5, sticky=tk.W)
        self.room_name_var = tk.StringVar()
        ttk.Entry(single_input_frame, textvariable=self.room_name_var, width=15).grid(row=0, column=1, padx=5)

        ttk.Label(single_input_frame, text="Width:").grid(row=0, column=2, padx=5, sticky=tk.W)
        self.room_width_var = tk.StringVar()
        ttk.Entry(single_input_frame, textvariable=self.room_width_var, width=10).grid(row=0, column=3, padx=5)

        ttk.Label(single_input_frame, text="Height:").grid(row=0, column=4, padx=5, sticky=tk.W)
        self.room_height_var = tk.StringVar()
        ttk.Entry(single_input_frame, textvariable=self.room_height_var, width=10).grid(row=0, column=5, padx=5)

        ttk.Label(single_input_frame, text="Max Expansion:").grid(row=0, column=6, padx=5, sticky=tk.W)
        # Default max expansion should be 3
        self.room_max_exp_var = tk.StringVar(value="3")
        ttk.Entry(single_input_frame, textvariable=self.room_max_exp_var, width=10).grid(row=0, column=7, padx=5)

        # NEW: Need Corridor toggle for single room (default Yes)
        self.room_need_corr_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(single_input_frame, text="Need Corridor", variable=self.room_need_corr_var).grid(row=0, column=8, padx=5)

        ttk.Button(single_input_frame, text="Add Room", command=self.add_room).grid(row=0, column=9, padx=10)

        bulk_input_frame = ttk.LabelFrame(frame, text="Add Multiple Rooms", padding=10)
        bulk_input_frame.pack(fill=tk.X, pady=5)

        ttk.Label(bulk_input_frame, text="Base Name:").grid(row=0, column=0, padx=5, sticky=tk.W)
        self.bulk_room_name_var = tk.StringVar()
        ttk.Entry(bulk_input_frame, textvariable=self.bulk_room_name_var, width=15).grid(row=0, column=1, padx=5)

        ttk.Label(bulk_input_frame, text="Quantity:").grid(row=0, column=2, padx=5, sticky=tk.W)
        self.bulk_room_quantity_var = tk.StringVar()
        ttk.Entry(bulk_input_frame, textvariable=self.bulk_room_quantity_var, width=10).grid(row=0, column=3, padx=5)

        ttk.Label(bulk_input_frame, text="Width:").grid(row=0, column=4, padx=5, sticky=tk.W)
        self.bulk_room_width_var = tk.StringVar()
        ttk.Entry(bulk_input_frame, textvariable=self.bulk_room_width_var, width=10).grid(row=0, column=5, padx=5)

        ttk.Label(bulk_input_frame, text="Height:").grid(row=0, column=6, padx=5, sticky=tk.W)
        self.bulk_room_height_var = tk.StringVar()
        ttk.Entry(bulk_input_frame, textvariable=self.bulk_room_height_var, width=10).grid(row=0, column=7, padx=5)

        ttk.Label(bulk_input_frame, text="Max Expansion:").grid(row=0, column=8, padx=5, sticky=tk.W)
        # Default max expansion should be 3
        self.bulk_room_max_exp_var = tk.StringVar(value="3")
        ttk.Entry(bulk_input_frame, textvariable=self.bulk_room_max_exp_var, width=10).grid(row=0, column=9, padx=5)

        # NEW: Need Corridor toggle for bulk rooms (default Yes)
        self.bulk_room_need_corr_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(bulk_input_frame, text="Need Corridor", variable=self.bulk_room_need_corr_var).grid(row=0, column=10, padx=5)

        ttk.Button(bulk_input_frame, text="Add Multiple Rooms", command=self.add_bulk_rooms).grid(row=0, column=11, padx=10)

        management_frame = ttk.Frame(frame)
        management_frame.pack(fill=tk.X, pady=10)

        ttk.Button(management_frame, text="Remove Selected", command=self.remove_room).pack(side=tk.LEFT, padx=5)
        ttk.Button(management_frame, text="Edit Selected", command=self.edit_room).pack(side=tk.LEFT, padx=5)
        ttk.Button(management_frame, text="Clear All", command=self.clear_rooms).pack(side=tk.LEFT, padx=5)
        ttk.Button(management_frame, text="Toggle Corridor", command=self.toggle_corridor).pack(side=tk.LEFT, padx=5)

    def init_adjacency_screen(self):
        frame = ttk.Frame(self.content_frame)
        self.screens["adjacency"] = frame

        ttk.Label(frame, text="Room Adjacency Requirements",
                  font=("Arial", 16, "bold")).pack(pady=(0, 20))

        instructions = ttk.Label(frame,
                                 text="Define which rooms should be adjacent to each other (share a wall).",
                                 wraplength=800)
        instructions.pack(pady=(0, 10))

        main_container = ttk.Frame(frame)
        main_container.pack(fill=tk.BOTH, expand=True)

        left_frame = ttk.LabelFrame(main_container, text="Add Adjacency", padding=10)
        left_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 10))

        ttk.Label(left_frame, text="Room 1:").pack(anchor=tk.W)
        self.room1_combo = ttk.Combobox(left_frame, state="readonly", width=20)
        self.room1_combo.pack(fill=tk.X, pady=(0, 10))

        ttk.Label(left_frame, text="Room 2:").pack(anchor=tk.W)
        self.room2_combo = ttk.Combobox(left_frame, state="readonly", width=20)
        self.room2_combo.pack(fill=tk.X, pady=(0, 10))

        ttk.Button(left_frame, text="Add Adjacency", command=self.add_adjacency).pack(pady=10)

        right_frame = ttk.LabelFrame(main_container, text="Current Adjacencies", padding=10)
        right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)

        self.adjacencies_listbox = tk.Listbox(right_frame, height=15)
        self.adjacencies_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        adj_scrollbar = ttk.Scrollbar(right_frame, orient=tk.VERTICAL, command=self.adjacencies_listbox.yview)
        adj_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.adjacencies_listbox.config(yscrollcommand=adj_scrollbar.set)

        adj_button_frame = ttk.Frame(right_frame)
        adj_button_frame.pack(fill=tk.X, pady=(10, 0))

        ttk.Button(adj_button_frame, text="Remove Selected",
                   command=self.remove_adjacency).pack(side=tk.LEFT, padx=2)
        ttk.Button(adj_button_frame, text="Clear All",
                   command=self.clear_adjacencies).pack(side=tk.LEFT, padx=2)

    # def update_area_stats(self, regions=None, fixed_rooms=None, fixed_area=None, rooms=None):
    #     """
    #     Unified area updater — place this in the main GUI class (FloorPlanGUI).
    #     Call from CADApp via callback, and from add_room/add_bulk_rooms.
    #     """
    #
    #     def _get_area_from_room(r):
    #         try:
    #             return float(r.width) * float(r.height)
    #         except Exception:
    #             try:
    #                 return float(r.get("width", 0)) * float(r.get("height", 0))
    #             except Exception:
    #                 return 0.0
    #
    #     def _get_coords(r):
    #         try:
    #             return float(r.x), float(r.y), float(r.width), float(r.height)
    #         except Exception:
    #             return float(r.get("x", 0)), float(r.get("y", 0)), float(r.get("width", 0)), float(r.get("height", 0))
    #
    #     try:
    #         # Prefer explicit regions if provided or if last_regions exists
    #         regions_list = regions if regions is not None else getattr(self, "last_regions", None) or []
    #         total_region_area = 0.0
    #         if regions_list:
    #             try:
    #                 total_region_area = sum(
    #                     (float(r.get("width", r.get("w", 0))) * float(r.get("height", r.get("h", 0))))
    #                     if isinstance(r, dict) else (float(getattr(r, "width", 0)) * float(getattr(r, "height", 0)))
    #                     for r in regions_list
    #                 )
    #             except Exception:
    #                 total_region_area = float(
    #                     getattr(self, "_cached_area_stats", {}).get("total_region_area", 0.0) or 0.0)
    #
    #         # Rooms area resolution
    #         if rooms is None:
    #             # prefer numeric list added via UI
    #             ral = getattr(self, "rooms_area_list", None)
    #             if isinstance(ral, (list, tuple)) and ral:
    #                 try:
    #                     rooms_area = sum(float(x or 0) for x in ral)
    #                 except Exception:
    #                     rooms_area = 0.0
    #             else:
    #                 # fallback to floorplan/floor_plan objects
    #                 floor = getattr(self, "floor_plan", None) or getattr(self, "floorplan", None)
    #                 if floor is not None and hasattr(floor, "rooms"):
    #                     rooms_area = sum(_get_area_from_room(r) for r in getattr(floor, "rooms", []))
    #                 else:
    #                     rooms_area = 0.0
    #         else:
    #             rooms_area = sum(_get_area_from_room(r) for r in rooms)
    #
    #         # Fixed area resolution
    #         if fixed_area is not None:
    #             try:
    #                 fixed_total = float(fixed_area or 0.0)
    #             except Exception:
    #                 fixed_total = 0.0
    #         else:
    #             if fixed_rooms is not None:
    #                 fixed_total = sum(_get_area_from_room(r) for r in fixed_rooms)
    #             else:
    #                 fixed_total = float(getattr(self, "fixed_area_total", 0.0) or 0.0)
    #                 if fixed_total <= 0.0:
    #                     candidate = getattr(self, "cad_fixed_rooms", None) or getattr(self, "last_fixed_rooms", None)
    #                     if not candidate:
    #                         floor = getattr(self, "floor_plan", None) or getattr(self, "floorplan", None)
    #                         if floor is not None:
    #                             candidate = getattr(floor, "fixed_rooms", None) or getattr(floor, "fixed_rooms_list",
    #                                                                                        None)
    #                     if candidate:
    #                         fixed_total = sum(_get_area_from_room(r) for r in candidate)
    #
    #         # If no explicit regions, compute bounding box from rooms+fixed
    #         if total_region_area <= 0.0:
    #             coords_objs = []
    #             if rooms is not None:
    #                 coords_objs += [_get_coords(r) for r in rooms if
    #                                 (r and (_get_coords(r)[2] > 0 and _get_coords(r)[3] > 0))]
    #             else:
    #                 floor = getattr(self, "floor_plan", None) or getattr(self, "floorplan", None)
    #                 if floor is not None:
    #                     coords_objs += [_get_coords(r) for r in getattr(floor, "rooms", []) if
    #                                     (_get_coords(r)[2] > 0 and _get_coords(r)[3] > 0)]
    #                     coords_objs += [_get_coords(r) for r in getattr(floor, "fixed_rooms", []) if
    #                                     (_get_coords(r)[2] > 0 and _get_coords(r)[3] > 0)]
    #                 coords_objs += [_get_coords(r) for r in (getattr(self, "last_fixed_rooms", []) or []) if
    #                                 (_get_coords(r)[2] > 0 and _get_coords(r)[3] > 0)]
    #
    #             if coords_objs:
    #                 min_x = min(x for x, y, w, h in coords_objs)
    #                 min_y = min(y for x, y, w, h in coords_objs)
    #                 max_x = max(x + w for x, y, w, h in coords_objs)
    #                 max_y = max(y + h for x, y, w, h in coords_objs)
    #                 total_region_area = max(0.0, (max_x - min_x) * (max_y - min_y))
    #             else:
    #                 total_region_area = float(
    #                     getattr(self, "_cached_area_stats", {}).get("total_region_area", 0.0) or 0.0)
    #
    #         used = rooms_area + fixed_total
    #         remaining = max(0.0, total_region_area - used) if total_region_area > 0 else 0.0
    #         remaining_pct = (remaining / total_region_area * 100.0) if total_region_area > 0 else 0.0
    #
    #         # Update Tk variables defensively
    #         try:
    #             if isinstance(getattr(self, "total_area", None), tk.Variable):
    #                 self.total_area.set(int(round(total_region_area)))
    #         except Exception:
    #             pass
    #         try:
    #             if isinstance(getattr(self, "only_rooms_area", None), tk.Variable):
    #                 self.only_rooms_area.set(int(round(used)))
    #         except Exception:
    #             pass
    #         try:
    #             if isinstance(getattr(self, "remaining_area", None), tk.Variable):
    #                 self.remaining_area.set(int(round(remaining)))
    #         except Exception:
    #             pass
    #         try:
    #             if isinstance(getattr(self, "remaining_percent", None), tk.Variable):
    #                 self.remaining_percent.set(f"{remaining_pct:.1f}%")
    #         except Exception:
    #             pass
    #
    #         # Cache
    #         self._cached_area_stats = {
    #             "total_region_area": total_region_area,
    #             "rooms_area": rooms_area,
    #             "fixed_total": fixed_total,
    #             "used_area": used,
    #             "remaining_area": remaining,
    #             "remaining_pct": remaining_pct,
    #         }
    #
    #         print(f"[AREA stats] total={total_region_area} rooms={rooms_area} fixed={fixed_total} "
    #               f"used={used} remaining={remaining} ({remaining_pct:.2f}%)")
    #
    #     except Exception as e:
    #         print("update_area_stats: unexpected error:", e)

    def _unit_spacing_factor(self):
        """Return squared unit spacing used for area conversions."""
        try:
            spacing = float(getattr(self, "unit_spacing", 1.0) or 1.0)
        except Exception:
            spacing = 1.0
        return spacing ** 2

    def _occupied_cells_count(self, room_obj=None, room_data=None):
        """Return unique occupied-cell count when polygon occupancy is available."""
        cells = None
        if room_obj is not None:
            try:
                if hasattr(room_obj, "get_occupied_cells") and callable(room_obj.get_occupied_cells):
                    cells = room_obj.get_occupied_cells()
            except Exception:
                cells = None
            if not cells:
                cells = getattr(room_obj, "occupied_cells", None)
        elif isinstance(room_data, dict):
            cells = room_data.get("occupied_cells")

        if not cells:
            return None

        try:
            unique_cells = {
                (int(cell[0]), int(cell[1]))
                for cell in cells
                if isinstance(cell, (list, tuple)) and len(cell) >= 2
            }
            return len(unique_cells) if unique_cells else None
        except Exception:
            return None

    def _scaled_room_area_value(self, width, height, room_obj=None, room_data=None):
        """Compute room area from geometry only (occupied-cells or width*height), independent of grid spacing."""
        occupied_count = self._occupied_cells_count(room_obj=room_obj, room_data=room_data)
        raw_area = float(occupied_count) if occupied_count is not None else float(width or 0) * float(height or 0)
        return int(round(raw_area))

    def _set_room_tree_area(self, item, width, height, room_obj=None, room_data=None):
        """Set the Area column using literal room area semantics (no spacing scaling)."""
        area_value = self._scaled_room_area_value(width, height, room_obj=room_obj, room_data=room_data)
        self.rooms_tree.set(item, "Area", str(area_value))

    # In FloorPlanGUI class
    def update_area_stats(self, total_area_override=None):
        """
        Unified area updater. Calculates total area from override or uses the stored value.
        Used area is calculated from the rooms_tree to prevent double-counting.
        """
        try:
            # Logic to persist the total area correctly
            total_region_area = 0.0
            if total_area_override is not None:
                # If an override is given (from the CAD tool), use it and store it permanently.
                total_region_area = float(total_area_override)
                self.total_area.set(int(round(total_region_area)))

                print(f"DEBUG 3 (update_area_stats): SETTING self.total_area to {self.total_area.get()}")
            else:
                # On all subsequent calls (add/edit room), get the stored total area.
                total_region_area = float(self.total_area.get())

            # Determine Used Area (from the rooms_tree)
            used_area = 0.0
            for item in self.rooms_tree.get_children():
                try:
                    area_val = self.rooms_tree.set(item, "Area")
                    used_area += float(area_val or 0)
                except (ValueError, TypeError):
                    continue

            # Calculate final stats
            remaining = max(0.0, total_region_area - used_area)
            remaining_pct = (remaining / total_region_area * 100.0) if total_region_area > 0 else 0.0

            # Update the UI labels
            self.only_rooms_area.set(int(round(used_area)))
            self.remaining_area.set(int(round(remaining)))
            self.remaining_percent.set(f"{remaining_pct:.1f}%")

            print(
                f"[AREA stats] total={total_region_area} used={used_area} remaining={remaining} ({remaining_pct:.2f}%)")

        except Exception as e:
            print("update_area_stats: unexpected error:", e)

    def update_output_display(self):
        """Update the output display with statistics and visualization"""
        if not self.floor_plan:
            return

        self.stats_text.delete('1.0', tk.END)

        layout_result = getattr(self.floor_plan, "last_layout_result", {}) or {}
        placed_count = int(layout_result.get("placed_count") or sum(1 for room in self.floor_plan.rooms if room.x is not None))
        total_room_count = int(layout_result.get("total_rooms") or len(self.floor_plan.rooms))
        is_partial_layout = bool(layout_result.get("partial")) and placed_count < total_room_count

        # ### This is the crucial line that needs to be changed ###
        # It ensures we use the correct total area (60) that we confirmed is being stored.
        total_area = self.total_area.get()

        # This is the debug print to confirm the fix is applied.
        print(
            f"DEBUG 4 (update_output_display): At the moment of display, self.total_area.get() is {self.total_area.get()}")

        used_area = 0.0
        for room in self.floor_plan.rooms:
            if room.x is None:
                continue
            used_area += self._scaled_room_area_value(room.width, room.height, room_obj=room)

        stats_title = "PARTIAL FLOOR PLAN STATISTICS (Best Available)" if is_partial_layout else "FLOOR PLAN STATISTICS (Generated)"
        stats = f"{stats_title}\n{'=' * 30}\n\n"
        stats += f"Total Floor Area: {total_area} square units\n"
        if is_partial_layout:
            stats += f"Placed Rooms: {placed_count}/{total_room_count}\n"
        stats += f"Final Used Area: {used_area} square units\n"
        if total_area > 0:
            stats += f"Space Utilization: {used_area / total_area:.2%}\n\n"

        if is_partial_layout:
            unplaced_rooms = [room.name for room in self.floor_plan.rooms if room.x is None]
            if unplaced_rooms:
                stats += f"Unplaced Rooms: {', '.join(unplaced_rooms)}\n\n"

        score, adjacent_pairs, violations = self.floor_plan.evaluate_adjacency_score()
        stats += f"Adjacency Score: {score}/{len(self.floor_plan.adjacency_graph.edges)}\n"
        stats += f"Adjacent Pairs: {adjacent_pairs}\n\n"

        stats += "ROOM EXPANSION STATISTICS:\n" + "-" * 30 + "\n"
        for room in self.floor_plan.rooms:
            if room.x is not None:
                original_area = room.original_width * room.original_height
                current_area = room.width * room.height
                expansion_pct = (current_area - original_area) / original_area * 100 if original_area > 0 else 0
                stats += f"- {room.name}: {room.original_width}x{room.original_height} → {room.width}x{room.height} ({expansion_pct:.1f}% increase)\n"

        stats += "\nFINAL ROOM PLACEMENTS:\n" + "-" * 20 + "\n"
        for room in self.floor_plan.rooms:
            stats += f"{room}\n"

        self.stats_text.insert('1.0', stats)

        self.ax.clear()
        self.visualize_floor_plan()
        self.safe_draw_canvas()

        # Enable GA button if floor plan exists
        if hasattr(self, 'ga_button'):
            self.ga_button.config(state=tk.NORMAL)

        # Switch to the output screen
        self.show_screen("output")

    def init_non_adjacency_screen(self):
        frame = ttk.Frame(self.content_frame)
        self.screens["non_adjacency"] = frame

        ttk.Label(frame, text="Room Non-Adjacency Requirements",
                  font=("Arial", 16, "bold")).pack(pady=(0, 20))

        instructions = ttk.Label(frame,
                                 text="Define which rooms should NOT be adjacent to each other (should not share a wall).",
                                 wraplength=800)
        instructions.pack(pady=(0, 10))

        main_container = ttk.Frame(frame)
        main_container.pack(fill=tk.BOTH, expand=True)

        left_frame = ttk.LabelFrame(main_container, text="Add Non-Adjacency", padding=10)
        left_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 10))

        ttk.Label(left_frame, text="Room 1:").pack(anchor=tk.W)
        self.non_adj_room1_combo = ttk.Combobox(left_frame, state="readonly", width=20)
        self.non_adj_room1_combo.pack(fill=tk.X, pady=(0, 10))

        ttk.Label(left_frame, text="Room 2:").pack(anchor=tk.W)
        self.non_adj_room2_combo = ttk.Combobox(left_frame, state="readonly", width=20)
        self.non_adj_room2_combo.pack(fill=tk.X, pady=(0, 10))

        ttk.Button(left_frame, text="Add Non-Adjacency", command=self.add_non_adjacency).pack(pady=10)

        right_frame = ttk.LabelFrame(main_container, text="Current Non-Adjacencies", padding=10)
        right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)

        self.non_adjacencies_listbox = tk.Listbox(right_frame, height=15)
        self.non_adjacencies_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        non_adj_scrollbar = ttk.Scrollbar(right_frame, orient=tk.VERTICAL, command=self.non_adjacencies_listbox.yview)
        non_adj_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.non_adjacencies_listbox.config(yscrollcommand=non_adj_scrollbar.set)

        non_adj_button_frame = ttk.Frame(right_frame)
        non_adj_button_frame.pack(fill=tk.X, pady=(10, 0))

        ttk.Button(non_adj_button_frame, text="Remove Selected",
                   command=self.remove_non_adjacency).pack(side=tk.LEFT, padx=2)
        ttk.Button(non_adj_button_frame, text="Clear All",
                   command=self.clear_non_adjacencies).pack(side=tk.LEFT, padx=2)

    def init_output_screen(self):
        frame = ttk.Frame(self.content_frame)
        self.screens["output"] = frame
        self.add_mode = tk.StringVar(value="none")

        ttk.Label(frame, text="Floor Plan Output",
                  font=("Arial", 16, "bold")).pack(pady=(0, 20))

        paned = ttk.PanedWindow(frame, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True)

        left_panel = ttk.Frame(paned)
        paned.add(left_panel, weight=1)

        controls_frame = ttk.LabelFrame(left_panel, text="Generation Controls", padding=10)
        controls_frame.pack(fill=tk.X, pady=(0, 10))

        gen_controls_row = ttk.Frame(controls_frame)
        gen_controls_row.pack(fill=tk.X, pady=(0, 10))

        ttk.Button(gen_controls_row, text="Add Door", command=lambda: self.add_mode.set("door")).grid(row=0, column=4,
                                                                                                      padx=5)
        ttk.Button(gen_controls_row, text="Add Window", command=lambda: self.add_mode.set("window")).grid(row=0,
                                                                                                          column=5,
                                                                                                          padx=5)

        ttk.Label(gen_controls_row, text="Max Attempts:").grid(row=0, column=0, sticky=tk.W, padx=5)
        self.max_attempts_var = tk.StringVar(value="1000")
        ttk.Entry(gen_controls_row, textvariable=self.max_attempts_var, width=10).grid(row=0, column=1, padx=5)

        self.enable_expansion_var = tk.BooleanVar(value=True)
        self.enable_space_optimization_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(gen_controls_row, text="Enable Room Expansion",
                        variable=self.enable_expansion_var).grid(row=0, column=2, padx=20)
        ttk.Checkbutton(gen_controls_row, text="Enable Space Optimization",
                        variable=self.enable_space_optimization_var).grid(row=0, column=3, padx=20)

        # Corridor width control
        ttk.Label(gen_controls_row, text="Corridor Width:").grid(row=0, column=6, sticky=tk.W, padx=5)
        self.corridor_width_var = tk.IntVar(value=4)
        corridor_spinbox = tk.Spinbox(gen_controls_row, from_=1, to=10, textvariable=self.corridor_width_var, width=5)
        corridor_spinbox.grid(row=0, column=7, padx=5)

        # GA button
        self.ga_button = ttk.Button(gen_controls_row, text="Generate Circulation", command=self.run_genetic_algorithm)
        self.ga_button.grid(row=0, column=8, padx=5)
        self.ga_button.config(state=tk.DISABLED)

        save_controls_row = ttk.Frame(controls_frame)
        save_controls_row.pack(fill=tk.X)

        ttk.Button(save_controls_row, text="Save as JSON",
                   command=self.save_floor_plan_json).pack(side=tk.LEFT, padx=5)
        ttk.Button(save_controls_row, text="Load from JSON",
                   command=self.load_floor_plan_json).pack(side=tk.LEFT, padx=5)

        stats_frame = ttk.LabelFrame(left_panel, text="Statistics", padding=10)
        stats_frame.pack(fill=tk.BOTH, expand=True)

        self.stats_text = scrolledtext.ScrolledText(stats_frame, height=20, width=40)
        self.stats_text.pack(fill=tk.BOTH, expand=True)

        right_panel = ttk.Frame(paned)
        paned.add(right_panel, weight=2)

        viz_frame = ttk.LabelFrame(right_panel, text="Floor Plan Visualization", padding=10)
        viz_frame.pack(fill=tk.BOTH, expand=True)

        self.fig, self.ax = plt.subplots(figsize=(8, 6))
        self.mpl_canvas = FigureCanvasTkAgg(self.fig, viz_frame)
        self.mpl_canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        self.mpl_canvas.mpl_connect("button_press_event", self.on_canvas_click)

    def get_non_adjacencies_data(self):
        non_adjacencies = []
        for i in range(self.non_adjacencies_listbox.size()):
            non_adjacency_text = self.non_adjacencies_listbox.get(i)
            if "✗" in non_adjacency_text:
                room1, room2 = non_adjacency_text.split("✗", 1)
            elif "â��" in non_adjacency_text:
                room1, room2 = non_adjacency_text.split("â��", 1)
            else:
                parts = non_adjacency_text.split()
                if len(parts) >= 2:
                    room1, room2 = parts[0], parts[-1]
                else:
                    continue

            non_adjacencies.append([room1.strip(), room2.strip()])
        return non_adjacencies

    def on_canvas_click(self, event):
        if event.xdata is None or event.ydata is None:
            return

        if self.add_mode.get() == "door":
            self.place_door(event.xdata, event.ydata)
            self.add_mode.set("none")
        elif self.add_mode.get() == "window":
            self.place_window(event.xdata, event.ydata)
            self.add_mode.set("none")

    def place_door(self, x, y):
        """
        Door width = 1/2 of the wall length where placed.
        Draws an L-shaped door (jamb + leaf) and a quarter-arc that always lies INSIDE
        the room (corrected directions).
        """
        wall = None
        room_found = None

        # find clicked wall + room
        for room in getattr(self, 'floor_plan', []).rooms if hasattr(self, 'floor_plan') and getattr(self.floor_plan,
                                                                                                     'rooms',
                                                                                                     None) else []:
            if getattr(room, 'x', None) is None or getattr(room, 'y', None) is None:
                continue
            if abs(y - room.y) < 0.5 and room.x <= x <= room.x + room.width:
                wall = "bottom";
                room_found = room
            elif abs(y - (room.y + room.height)) < 0.5 and room.x <= x <= room.x + room.width:
                wall = "top";
                room_found = room
            elif abs(x - room.x) < 0.5 and room.y <= y <= room.y + room.height:
                wall = "left";
                room_found = room
            elif abs(x - (room.x + room.width)) < 0.5 and room.y <= y <= room.y + room.height:
                wall = "right";
                room_found = room
            if wall:
                break

        if not wall or not room_found:
            return  # clicked outside a valid wall

        # door width = half of the wall it's on
        if wall in ("top", "bottom"):
            door_w = 0.5 * room_found.width
        else:
            door_w = 0.5 * room_found.height

        if door_w < 0.15:
            door_w = 0.15

        color = "saddlebrown"
        thickness = 2.5
        arc_color = "gray"

        # clamp center so door stays within wall extents
        if wall in ["top", "bottom"]:
            x = max(room_found.x + door_w / 2, min(x, room_found.x + room_found.width - door_w / 2))
        else:
            y = max(room_found.y + door_w / 2, min(y, room_found.y + room_found.height - door_w / 2))

        # Draw L-shaped door and a quarter-circle arc that is inside the room.
        # Arc angle mapping (degrees):
        # - bottom  -> 0 -> 90   (inside = +x / +y quadrant)
        # - top     -> 180 -> 270 (inside = -x / -y quadrant)
        # - left    -> 0 -> 90   (inside = +x / +y quadrant)
        # - right   -> 90 -> 180 (inside = +y / -x quadrant)
        if wall == "bottom":
            # jamb up, leaf to +x
            self.ax.plot([x, x], [y, y + door_w], color=color, linewidth=thickness)  # jamb
            self.ax.plot([x, x + door_w], [y, y], color=color, linewidth=thickness)  # leaf
            arc = mpatches.Arc((x, y), 2 * door_w, 2 * door_w, angle=0, theta1=0, theta2=90,
                               color=arc_color, linewidth=1.5)
        elif wall == "top":
            # jamb down, leaf to -x
            self.ax.plot([x, x], [y, y - door_w], color=color, linewidth=thickness)
            self.ax.plot([x, x - door_w], [y, y], color=color, linewidth=thickness)
            arc = mpatches.Arc((x, y), 2 * door_w, 2 * door_w, angle=0, theta1=180, theta2=270,
                               color=arc_color, linewidth=1.5)
        elif wall == "left":
            # jamb right, leaf up
            self.ax.plot([x, x + door_w], [y, y], color=color, linewidth=thickness)
            self.ax.plot([x, x], [y, y + door_w], color=color, linewidth=thickness)
            # interior quadrant for left wall is +x (0°) to +y (90°)
            arc = mpatches.Arc((x, y), 2 * door_w, 2 * door_w, angle=0, theta1=0, theta2=90,
                               color=arc_color, linewidth=1.5)
        else:  # right
            # jamb left, leaf up
            self.ax.plot([x, x - door_w], [y, y], color=color, linewidth=thickness)
            self.ax.plot([x, x], [y, y + door_w], color=color, linewidth=thickness)
            # interior quadrant for right wall is +y (90°) to -x (180°)
            arc = mpatches.Arc((x, y), 2 * door_w, 2 * door_w, angle=0, theta1=90, theta2=180,
                               color=arc_color, linewidth=1.5)

        try:
            self.ax.add_patch(arc)
        except Exception:
            pass

        if not hasattr(self, 'placed_doors'):
            self.placed_doors = []
        self.placed_doors.append({"x": x, "y": y, "wall": wall, "width": door_w})

        self.safe_draw_canvas()

    def place_window(self, x, y):
        """
        Draw a window whose length = 1/2 of the wall length where it's placed.
        The window is centered on the click (clamped to wall extents), shows a short
        frame (caps) and is recorded in self.placed_windows.
        """
        wall = None
        room_found = None

        # find clicked wall + room
        for room in getattr(self, 'floor_plan', []).rooms if hasattr(self, 'floor_plan') and getattr(self.floor_plan,
                                                                                                     'rooms',
                                                                                                     None) else []:
            if getattr(room, 'x', None) is None or getattr(room, 'y', None) is None:
                continue
            if abs(y - room.y) < 0.5 and room.x <= x <= room.x + room.width:
                wall = "bottom";
                room_found = room
            elif abs(y - (room.y + room.height)) < 0.5 and room.x <= x <= room.x + room.width:
                wall = "top";
                room_found = room
            elif abs(x - room.x) < 0.5 and room.y <= y <= room.y + room.height:
                wall = "left";
                room_found = room
            elif abs(x - (room.x + room.width)) < 0.5 and room.y <= y <= room.y + room.height:
                wall = "right";
                room_found = room
            if wall:
                break

        if not wall or not room_found:
            return

        # --- window length = half of the wall where it's placed ---
        if wall in ("top", "bottom"):
            win_len = 0.5 * room_found.width
        else:
            win_len = 0.5 * room_found.height

        # enforce a small minimum (so it's visible on tiny rooms)
        if win_len < 0.12:
            win_len = 0.12

        half = win_len / 2.0
        # small offset from wall so the line doesn't overlap wall stroke (fraction of win_len)
        offset = max(0.03, win_len * 0.04)
        color = "dodgerblue"
        thickness = 2.0
        cap_len = max(0.12, win_len * 0.15)  # cap length (perpendicular to main line)

        # clamp center so window stays entirely on the wall
        if wall in ["top", "bottom"]:
            x = max(room_found.x + half, min(x, room_found.x + room_found.width - half))
        else:
            y = max(room_found.y + half, min(y, room_found.y + room_found.height - half))

        # draw depending on wall orientation
        if wall in ["top", "bottom"]:
            # choose which side of the wall to offset the visible window line
            y_off = y + offset if wall == "top" else y - offset
            # main window short line centered at (x, y_off)
            self.ax.plot([x - half, x + half], [y_off, y_off], color=color, linewidth=thickness)
            # caps (perpendicular short lines at ends)
            self.ax.plot([x - half, x - half], [y_off - cap_len / 2, y_off + cap_len / 2], color=color,
                         linewidth=thickness * 0.6)
            self.ax.plot([x + half, x + half], [y_off - cap_len / 2, y_off + cap_len / 2], color=color,
                         linewidth=thickness * 0.6)
        else:
            # left or right wall: vertical main line
            x_off = x + offset if wall == "left" else x - offset
            self.ax.plot([x_off, x_off], [y - half, y + half], color=color, linewidth=thickness)
            # caps (small horizontal lines at top and bottom)
            self.ax.plot([x_off - cap_len / 2, x_off + cap_len / 2], [y - half, y - half], color=color,
                         linewidth=thickness * 0.6)
            self.ax.plot([x_off - cap_len / 2, x_off + cap_len / 2], [y + half, y + half], color=color,
                         linewidth=thickness * 0.6)

        # record placement
        if not hasattr(self, 'placed_windows'):
            self.placed_windows = []
        self.placed_windows.append({"x": x, "y": y, "wall": wall, "length": win_len})

        self.safe_draw_canvas()

    def save_floor_plan_json(self):
        try:
            file_path = filedialog.asksaveasfilename(
                defaultextension=".json",
                filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
                title="Save Floor Plan"
            )

            if not file_path:
                return

            data = {
                "metadata": {
                    "version": "2.0",  # Mark as new format
                    "created_at": self.get_current_timestamp(),
                    "description": "Floor plan configuration and results"
                },
                # ### NEW: Save the raw CAD drawing state ###
                "cad_state": {
                    "boundary_state": getattr(self, 'boundary_state', []),
                    "final_area": getattr(self, 'final_area', []),
                    "fixed_names": getattr(self, 'fixed_names', []),
                    "cad_fixed_rooms": getattr(self, 'cad_fixed_rooms', []),
                    "entrance_grid_coords": getattr(self, 'entrance_grid_coords', [])
                },
                "regions": self.get_regions_data(),
                "rooms": self.get_rooms_data(),
                "adjacencies": self.get_adjacencies_data(),
                "non_adjacencies": self.get_non_adjacencies_data(),
                "generation_settings": {
                    "max_attempts": int(self.max_attempts_var.get()),
                    "enable_expansion": self.enable_expansion_var.get(),
                    "unit_spacing": float(getattr(self, "unit_spacing", 1.0) or 1.0)
                }
            }

            if self.floor_plan:
                data["results"] = self.get_floor_plan_results()

            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

            messagebox.showinfo("Success", f"Floor plan saved to:\n{file_path}")

        except Exception as e:
            messagebox.showerror("Error", f"Failed to save floor plan:\n{str(e)}")

    # In FloorPlanGUI class in uinegNew.py
    # Replace the ENTIRE load_floor_plan_json method with this:

    # In FloorPlanGUI class in uinegNew.py
    # Replace the ENTIRE load_floor_plan_json method with this:
    def _set_total_area_from_boundary(self, boundary_coords):
        """
        Compute polygon area from boundary_coords using the shoelace formula,
        scale by unit_spacing, and store it into self.total_area (Tk variable).
        """
        if not boundary_coords or len(boundary_coords) < 3:
            area_units = 0.0
        else:
            area = 0.0
            n = len(boundary_coords)
            for i in range(n):
                x1, y1 = boundary_coords[i]
                x2, y2 = boundary_coords[(i + 1) % n]
                area += x1 * y2 - x2 * y1
            area_units = abs(area) * 0.5  # area in coordinate units

        spacing = getattr(self, "unit_spacing", 1.0) or 1.0
        total_area_real = area_units * (spacing ** 2)

        # Make sure self.total_area is a tk.Variable and update it
        try:
            # if already a Tk variable (IntVar / DoubleVar)
            if hasattr(self, "total_area") and isinstance(self.total_area, tk.Variable):
                # cast to int; if you want decimals, use DoubleVar and skip int()
                self.total_area.set(int(round(total_area_real)))
            else:
                # create it
                self.total_area = tk.IntVar(value=int(round(total_area_real)))
        except Exception:
            # absolute fallback: at least store it somewhere
            self.total_area = int(round(total_area_real))

        print("DEBUG: loaded total_area =", total_area_real)

    def load_floor_plan_json(self, preloaded_data=None, preloaded_path=None):
        try:
            if preloaded_data is not None:
                data = preloaded_data
                file_path = preloaded_path or '(loaded from CAD)'
            else:
                file_path = filedialog.askopenfilename(
                    filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
                    title="Load Floor Plan"
                )
                if not file_path: return

                with open(file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)

            self.clear_all_data()

            main_boundary_coords = []
            cad_state = data.get("cad_state", {})

            # Modern format: Try to load from cad_state first
            if cad_state:
                self.boundary_state = cad_state.get("boundary_state", [])
                self.final_area = cad_state.get("final_area", [])
                self.fixed_names = cad_state.get("fixed_names", [])
                self.unit_spacing = data.get("generation_settings", {}).get("unit_spacing", 1.0)
                main_boundary_coords = next(
                    (item.get('coords', []) for item in self.boundary_state if item.get("type") == "polygon"), [])

                # Preferred path for modern files: restore exact fixed-room geometry payload.
                cad_fixed_state = cad_state.get("cad_fixed_rooms", [])
                if isinstance(cad_fixed_state, list) and cad_fixed_state:
                    self.cad_fixed_rooms = cad_fixed_state

            # Fallback for OLD format: If no boundary found, reconstruct from "regions"
            if not main_boundary_coords and "regions" in data:
                print("Legacy JSON format detected. Reconstructing boundary from regions.")
                legacy_regions = data.get("regions", [])
                if legacy_regions:
                    # These coordinates are already scaled, so unit_spacing is 1
                    self.unit_spacing = 1.0
                    min_x = min(r['x'] for r in legacy_regions)
                    min_y = min(r['y'] for r in legacy_regions)
                    max_x = max(r['x'] + r['width'] for r in legacy_regions)
                    max_y = max(r['y'] + r['height'] for r in legacy_regions)
                    main_boundary_coords = [[min_x, min_y], [max_x, min_y], [max_x, max_y], [min_x, max_y]]
                    # Old files have no concept of fixed shapes
                    self.final_area = []
                    self.fixed_names = []

            if not main_boundary_coords:
                raise ValueError("File does not contain a valid boundary in 'cad_state' or a 'regions' list.")

            # Calculate total area from boundary using current unit spacing.
            # This avoids mixed-unit issues when regions come from legacy/unscaled payloads.
            regions_data = data.get("regions", [])
            self._set_total_area_from_boundary(main_boundary_coords)

            # Normalize all coordinates to a (0,0) origin
            offset_x = min(p[0] for p in main_boundary_coords)
            offset_y = min(p[1] for p in main_boundary_coords)
            boundary_width = (max(p[0] for p in main_boundary_coords) - offset_x)
            boundary_height = (max(p[1] for p in main_boundary_coords) - offset_y)

            # Clear the regions tree first
            for item in self.regions_tree.get_children():
                self.regions_tree.delete(item)

            # FIX: Use saved regions from JSON if available (preserves L-shapes and other non-rectangular boundaries)
            # Otherwise fall back to a single bounding-box region
            if regions_data and len(regions_data) > 0:
                # Use the saved decomposed regions (these preserve the actual floor shape)
                for idx, region in enumerate(regions_data):
                    region_name = f"Region {idx + 1}" if len(regions_data) > 1 else "Main Region"
                    item = self.regions_tree.insert("", "end", text=region_name)
                    self.regions_tree.set(item, "X", int(region.get('x', 0)))
                    self.regions_tree.set(item, "Y", int(region.get('y', 0)))
                    self.regions_tree.set(item, "Width", int(region.get('width', 0)))
                    self.regions_tree.set(item, "Height", int(region.get('height', 0)))
                print(f"DEBUG: Loaded {len(regions_data)} regions from JSON (non-rectangular boundary preserved)")
            else:
                # Fallback: create a single bounding-box region (legacy behavior)
                solid_normalized_region = {'x': 0, 'y': 0, 'width': boundary_width, 'height': boundary_height}
                item = self.regions_tree.insert("", "end", text="Main Region")
                self.regions_tree.set(item, "X", int(solid_normalized_region['x']))
                self.regions_tree.set(item, "Y", int(solid_normalized_region['y']))
                self.regions_tree.set(item, "Width", int(solid_normalized_region['width']))
                self.regions_tree.set(item, "Height", int(solid_normalized_region['height']))
                print("DEBUG: No regions in JSON, created single bounding-box region (rectangular fallback)")

            # Reconstruct fixed rooms from polygons only when modern cad_fixed_rooms are not available.
            if not getattr(self, "cad_fixed_rooms", None):
                self.cad_fixed_rooms = []
                for i, poly in enumerate(self.final_area):
                    if poly and i < len(self.fixed_names):
                        normalized_poly = _normalize_polygon_points(poly)
                        scaled_poly = [
                            ((p[0] - offset_x) * self.unit_spacing, (p[1] - offset_y) * self.unit_spacing)
                            for p in normalized_poly
                        ]
                        poly_min_x = min(p[0] for p in scaled_poly)
                        poly_min_y = min(p[1] for p in scaled_poly)
                        occupied_cells = _polygon_to_occupied_cells(scaled_poly)
                        self.cad_fixed_rooms.append({
                            'name': self.fixed_names[i],
                            'x': poly_min_x,
                            'y': poly_min_y,
                            'width': (max(p[0] for p in scaled_poly) - poly_min_x),
                            'height': (max(p[1] for p in scaled_poly) - poly_min_y),
                            'polygon': [[p[0], p[1]] for p in scaled_poly],
                            'occupied_cells': [[c[0], c[1]] for c in occupied_cells]
                        })

            # Set Total Area and populate UI

            # Build a lookup of fixed room coordinates from results.room_placements
            self.json_fixed_rooms = {}
            placements = data.get("results", {}).get("room_placements", [])
            placement_dict = {p['name']: p for p in placements}

            fixed_room_names = {fr['name'] for fr in self.cad_fixed_rooms}
            cad_fixed_lookup = {
                fr.get('name'): fr
                for fr in (self.cad_fixed_rooms or [])
                if isinstance(fr, dict) and fr.get('name')
            }
            for room in data.get("rooms", []):
                # If this room is marked fixed in JSON, store its coordinates
                if room.get('is_fixed'):
                    fixed_room_names.add(room['name'])
                    # Get coords from fixed_x/fixed_y fields, or fall back to results.room_placements
                    if room.get('fixed_x') is not None and room.get('fixed_y') is not None:
                        self.json_fixed_rooms[room['name']] = {
                            'x': int(room['fixed_x']), 'y': int(room['fixed_y']),
                            'width': int(room['width']), 'height': int(room['height'])
                        }
                    elif room['name'] in placement_dict:
                        p = placement_dict[room['name']]
                        self.json_fixed_rooms[room['name']] = {
                            'x': int(p['x']), 'y': int(p['y']),
                            'width': int(p['width']), 'height': int(p['height'])
                        }
                    print(f"DEBUG: Fixed room '{room['name']}' detected, coords={self.json_fixed_rooms.get(room['name'])}")

                item = self.rooms_tree.insert("", "end", text=room['name'])
                width, height = int(room['width']), int(room['height'])
                self.rooms_tree.set(item, "Width", width);
                self.rooms_tree.set(item, "Height", height)
                self.rooms_tree.set(item, "Max Expansion", room.get('max_expansion', 0))
                room_area_data = room
                if room.get('name') in cad_fixed_lookup and not room.get('occupied_cells'):
                    fixed_meta = cad_fixed_lookup.get(room.get('name')) or {}
                    if fixed_meta.get('occupied_cells'):
                        room_area_data = dict(room)
                        room_area_data['occupied_cells'] = fixed_meta.get('occupied_cells')
                self._set_room_tree_area(item, width, height, room_data=room_area_data)
                if room['name'] in fixed_room_names: self.rooms_tree.item(item, tags=('fixed',))

            if "adjacencies" in data:
                for adj in data["adjacencies"]:
                    if isinstance(adj, dict):
                        room1, room2 = adj.get('room1'), adj.get('room2')
                    elif isinstance(adj, (list, tuple)) and len(adj) >= 2:
                        room1, room2 = adj[0], adj[1]
                    else:
                        continue
                    room1 = room1.strip() if isinstance(room1, str) else room1
                    room2 = room2.strip() if isinstance(room2, str) else room2
                    if room1 and room2:
                        self.adjacencies_listbox.insert(tk.END, f"{room1} ↔ {room2}")
            if "non_adjacencies" in data:
                for non_adj in data["non_adjacencies"]:
                    if isinstance(non_adj, dict):
                        room1, room2 = non_adj.get('room1'), non_adj.get('room2')
                    elif isinstance(non_adj, (list, tuple)) and len(non_adj) >= 2:
                        room1, room2 = non_adj[0], non_adj[1]
                    else:
                        continue
                    room1 = room1.strip() if isinstance(room1, str) else room1
                    room2 = room2.strip() if isinstance(room2, str) else room2
                    if room1 and room2:
                        self.non_adjacencies_listbox.insert(tk.END, f"{room1} ✗ {room2}")

            settings = data.get("settings") or data.get("generation_settings") or {}
            if settings:
                self.max_attempts_var.set(str(settings.get("max_attempts", 1000)))
                self.enable_expansion_var.set(settings.get("enable_expansion", True))
                self.enable_space_optimization_var.set(settings.get("enable_space_optimization", True))
                if hasattr(self, "corridor_width_var"):
                    self.corridor_width_var.set(int(settings.get("corridor_width", self.corridor_width_var.get())))

            self.update_area_stats()
            messagebox.showinfo("Success", f"Floor plan configuration loaded from:\n{file_path}")
            self.show_screen('rooms')

        except Exception as e:
            messagebox.showerror("Error", f"Failed to load floor plan:\n{str(e)}")
            import traceback
            traceback.print_exc()

    def restore_floor_plan_from_results(self, results_data):
        try:
            regions = self.get_regions_data()
            if not regions:
                raise ValueError("No regions defined")

            self.floor_plan = FloorPlan(regions)

            # Add all rooms (including fixed ones from CAD) to the new floor plan object
            for item in self.rooms_tree.get_children():
                name = self.rooms_tree.item(item)['text']

                # Handle fixed rooms loaded from CAD
                is_fixed_tag = 'fixed' in self.rooms_tree.item(item).get('tags', [])

                if is_fixed_tag:
                    # Find the corresponding fixed room data to get its position
                    fixed_room_data = next(
                        (fr for fr in (getattr(self, 'cad_fixed_rooms', []) or []) if fr.get('name') == name), None)
                    if fixed_room_data:
                        floor_height = max(r['y'] + r['height'] for r in regions) if regions else 0
                        w, h, fx, fy = int(fixed_room_data['width']), int(fixed_room_data['height']), int(
                            fixed_room_data['x']), int(fixed_room_data['y'])
                        fy = floor_height - (fy + h)  # Flip Y coordinate
                        room = self.floor_plan.add_fixed_room(
                            width=w,
                            height=h,
                            fixed_x=fx,
                            fixed_y=fy,
                            name=name,
                            polygon_coords=fixed_room_data.get('polygon'),
                            occupied_cells=fixed_room_data.get('occupied_cells')
                        )
                        room.is_fixed = True
                else:
                    # Handle regular rooms
                    width = int(self.rooms_tree.set(item, "Width"))
                    height = int(self.rooms_tree.set(item, "Height"))
                    max_exp = int(self.rooms_tree.set(item, "Max Expansion"))
                    room_obj = self.floor_plan.add_room(name, width, height, max_exp)
                    try:
                        need_corr = self.rooms_tree.set(item, "Need Corridor")
                        room_obj.need_corridor = True if str(need_corr).lower().startswith("y") else False
                    except Exception:
                        pass

            # ### FIX: Use the correct separator '↔' when reading from the listbox ###
            for i in range(self.adjacencies_listbox.size()):
                adjacency = self.adjacencies_listbox.get(i)
                room1, room2 = adjacency.split(" ↔ ")
                self.floor_plan.add_adjacency(room1, room2)

            # ### NEW: Add non-adjacencies for a complete restoration ###
            for i in range(self.non_adjacencies_listbox.size()):
                non_adjacency = self.non_adjacencies_listbox.get(i)
                room1, room2 = non_adjacency.split(" ✗ ")
                self.floor_plan.add_non_adjacency(room1, room2)

            if "room_placements" in results_data:
                for placement in results_data["room_placements"]:
                    room = next((r for r in self.floor_plan.rooms if r.name == placement["name"]), None)
                    if room and not getattr(room, 'is_fixed', False):  # Only apply placement to non-fixed rooms
                        room.x = placement["x"]
                        room.y = placement["y"]
                        room.width = placement["width"]
                        room.height = placement["height"]
                        room.rotated = placement.get("rotated", False)

                        if not hasattr(room, 'original_width'):
                            room.original_width = placement.get("original_width", placement["width"])
                        if not hasattr(room, 'original_height'):
                            room.original_height = placement.get("original_height", placement["height"])

            # Persist fixed-room info so subsequent Generate calls will re-anchor them.
            try:
                fixed_rooms_from_results = []
                # compute floor_height in the same way generate_floor_plan expects for CAD-fixed entries
                floor_height = max(r['y'] + r['height'] for r in regions) if regions else 0
                for placement in results_data.get("room_placements", []):
                    if placement.get("is_fixed"):
                        # convert placement coords into CAD-style fixed-room entries so the CAD path
                        # in generate_floor_plan will re-add them correctly on later runs
                        px = int(placement.get('x', 0))
                        py = int(placement.get('y', 0))
                        w = int(placement.get('width', 0))
                        h = int(placement.get('height', 0))
                        # reverse the flip used by the CAD path: fr_y such that
                        # floor_height - (fr_y + h) == py  =>  fr_y = floor_height - (py + h)
                        fr_y = int(floor_height - (py + h)) if floor_height else int(placement.get('y', 0))
                        fr = {
                            'name': placement.get('name'),
                            'width': w,
                            'height': h,
                            'x': int(px),
                            'y': int(fr_y),
                            # default to 3 when missing so UI/backend keep a sensible value
                            'max_expansion': int(placement.get('max_expansion', 3))
                        }
                        fixed_rooms_from_results.append(fr)

                if fixed_rooms_from_results:
                    # store so generate_floor_plan (CAD path) will pick them up on subsequent runs
                    self.cad_fixed_rooms = fixed_rooms_from_results
                    self.last_fixed_rooms = list(fixed_rooms_from_results)
                    # refresh the UI list for fixed rooms
                    try:
                        self.load_cad_fixed_rooms_into_ui()
                    except Exception:
                        pass
            except Exception:
                pass

            self.update_output_display()

        except Exception as e:
            messagebox.showwarning("Restoration Failed",
                                   f"Could not restore exact layout: {str(e)}\n"
                                   "Generating new layout instead...")
            self.generate_floor_plan()

    def get_regions_data(self):
        regions = []
        for item in self.regions_tree.get_children():
            region = {
                "x": int(self.regions_tree.set(item, "X")),
                "y": int(self.regions_tree.set(item, "Y")),
                "width": int(self.regions_tree.set(item, "Width")),
                "height": int(self.regions_tree.set(item, "Height"))
            }
            regions.append(region)
        return regions

    def get_rooms_data(self):
        rooms = []
        for item in self.rooms_tree.get_children():
            # Determine need_corridor (default Yes)
            need_corr_val = self.rooms_tree.set(item, "Need Corridor") if "Need Corridor" in self.rooms_tree['columns'] else "Yes"

            # Determine is_fixed: prefer an explicit tag, otherwise check any 'Fixed'/'Is Fixed' column if present
            try:
                is_fixed_tag = 'fixed' in self.rooms_tree.item(item).get('tags', [])
            except Exception:
                is_fixed_tag = False

            fixed_col_val = None
            for colcand in ("Is Fixed", "Fixed", "is_fixed"):
                try:
                    if colcand in self.rooms_tree['columns']:
                        fixed_col_val = self.rooms_tree.set(item, colcand)
                        break
                except Exception:
                    continue

            if fixed_col_val is not None:
                try:
                    is_fixed = True if str(fixed_col_val).lower().startswith('y') or str(fixed_col_val) in ('1', 'true', 'True') else False
                except Exception:
                    is_fixed = bool(fixed_col_val)
            else:
                is_fixed = bool(is_fixed_tag)

            room = {
                "name": self.rooms_tree.item(item)['text'],
                "width": int(self.rooms_tree.set(item, "Width")),
                "height": int(self.rooms_tree.set(item, "Height")),
                "max_expansion": int(self.rooms_tree.set(item, "Max Expansion")),
                "need_corridor": True if str(need_corr_val).lower().startswith("y") else False,
                "is_fixed": bool(is_fixed)
            }
            rooms.append(room)
        return rooms

    def get_adjacencies_data(self):
        adjacencies = []
        for i in range(self.adjacencies_listbox.size()):
            adjacency_text = self.adjacencies_listbox.get(i)
            if "↔" in adjacency_text:
                room1, room2 = adjacency_text.split("↔", 1)
            elif "â��" in adjacency_text:
                room1, room2 = adjacency_text.split("â��", 1)
            else:
                parts = adjacency_text.split()
                if len(parts) >= 2:
                    room1, room2 = parts[0], parts[-1]
                else:
                    continue

            adjacencies.append([room1.strip(), room2.strip()])
        return adjacencies

    def get_floor_plan_results(self):
        if not self.floor_plan:
            return None

        total_area = sum(region['width'] * region['height'] for region in self.floor_plan.floor_regions)
        used_area = sum(room.width * room.height for room in self.floor_plan.rooms if room.x is not None)
        score, adjacent_pairs, violations = self.floor_plan.evaluate_adjacency_score()

        room_placements = []
        for room in self.floor_plan.rooms:
            if room.x is not None:
                placement = {
                    "name": room.name,
                    "x": room.x,
                    "y": room.y,
                    "width": room.width,
                    "height": room.height,
                    "original_width": room.original_width,
                    "original_height": room.original_height,
                    "rotated": room.rotated,
                    "max_expansion": room.max_expansion
                }
                # include is_fixed flag so exported placements know which rooms are fixed
                try:
                    placement["is_fixed"] = bool(getattr(room, "is_fixed", False))
                except Exception:
                    placement["is_fixed"] = False
                # include need_corridor flag so downstream consumers know if a corridor is required
                try:
                    placement["need_corridor"] = bool(getattr(room, "need_corridor", False))
                except Exception:
                    placement["need_corridor"] = False
                room_placements.append(placement)

        return {
            "statistics": {
                "total_floor_area": total_area,
                "used_area": used_area,
                "space_utilization": used_area / total_area if total_area > 0 else 0,
                "adjacency_score": score,
                "total_adjacency_requirements": len(self.floor_plan.adjacency_graph.edges),
                "satisfied_adjacencies": len(adjacent_pairs)
            },
            "room_placements": room_placements,
            "satisfied_adjacencies": [{"room1": pair[0], "room2": pair[1]} for pair in adjacent_pairs]
        }

    def get_current_timestamp(self):
        from datetime import datetime
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def show_screen(self, screen_name):
        for screen in self.screens.values():
            screen.pack_forget()

        if screen_name in self.screens:
            self.screens[screen_name].pack(fill=tk.BOTH, expand=True)
            self.current_screen = screen_name

            for name, btn in self.nav_buttons.items():
                if name == screen_name:
                    btn.state(['pressed'])
                else:
                    btn.state(['!pressed'])

            # New logic to handle the visibility of the regions treeview and buttons
            if screen_name == "regions":
                # Check if there are any regions to display
                if not self.regions_tree.get_children():
                    # If no regions, hide the treeview and the clear button
                    self.regions_tree.pack_forget()
                    self.clear_regions_button.pack_forget()
                else:
                    # If regions exist, show the treeview and the clear button
                    self.regions_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
                    self.clear_regions_button.pack(side=tk.LEFT, padx=5)

            if screen_name == "adjacency":
                self.refresh_room_combos()
            elif screen_name == "non_adjacency":
                self.refresh_non_adjacency_combos()

    def refresh_non_adjacency_combos(self):
        """Refresh the non-adjacency combo boxes with current room names and the Entrance."""
        room_names = [self.rooms_tree.item(item)['text'] for item in self.rooms_tree.get_children()]

        # <<< FIX: Add "ENTRANCE" to the list if it has been drawn >>>
        if hasattr(self, 'entrance_grid_coords') and self.entrance_grid_coords:
            room_names.insert(0, "ENTRANCE")

        self.non_adj_room1_combo['values'] = room_names
        self.non_adj_room2_combo['values'] = room_names

    def add_non_adjacency(self):
        room1 = self.non_adj_room1_combo.get()
        room2 = self.non_adj_room2_combo.get()

        if not room1 or not room2:
            messagebox.showerror("Error", "Please select both rooms")
            return

        if room1 == room2:
            messagebox.showerror("Error", "A room cannot be non-adjacent to itself")
            return

        non_adjacency1 = f"{room1} ✗ {room2}"  # Use ✗ instead of â†”
        non_adjacency2 = f"{room2} ✗ {room1}"  # Use ✗ instead of â†”

        for i in range(self.non_adjacencies_listbox.size()):
            existing = self.non_adjacencies_listbox.get(i)
            if existing == non_adjacency1 or existing == non_adjacency2:
                messagebox.showerror("Error", "This non-adjacency already exists")
                return

        self.non_adjacencies_listbox.insert(tk.END, non_adjacency1)

        self.non_adj_room1_combo.set("")
        self.non_adj_room2_combo.set("")

    def remove_non_adjacency(self):
        selection = self.non_adjacencies_listbox.curselection()
        if selection:
            self.non_adjacencies_listbox.delete(selection[0])

    def clear_non_adjacencies(self):
        self.non_adjacencies_listbox.delete(0, tk.END)

    def load_example_data(self):
        """
        Load default example data.
        """
        self.clear_all_data()

        # Empty lists to prevent default data from being added
        example_regions = []
        example_rooms = []
        example_adjacencies = []
        example_non_adjacencies = []

        for i, region in enumerate(example_regions):
            item = self.regions_tree.insert("", "end", text=f"Region {i + 1}")
            self.regions_tree.set(item, "X", region['x'])
            self.regions_tree.set(item, "Y", region['y'])
            self.regions_tree.set(item, "Width", region['width'])
            self.regions_tree.set(item, "Height", region['height'])

        print("THISSSS IS THE ROOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOM")
        print(self.load_rooms)
        self.total_area.set(self.plot_area)
        self.remaining_area.set(self.plot_area - self.rooms_area)

        example_rooms = self.load_rooms

        for room_data in example_rooms:
            name, width, height, max_exp, area = room_data
            self.only_room_area = self.only_room_area + area
            item = self.rooms_tree.insert("", "end", text=name)
            self.rooms_tree.set(item, "Width", width)
            self.rooms_tree.set(item, "Height", height)
            self.rooms_tree.set(item, "Max Expansion", max_exp)
            self._set_room_tree_area(item, width, height)
            self.rooms_tree.set(item, "Need Corridor", "Yes")
            # self.rooms_tree.set(item, "Area", area)

        self.only_rooms_area.set(self.only_room_area)
        self.corridors_area = self.rooms_area - self.only_room_area

        for room1, room2 in example_adjacencies:
            self.adjacencies_listbox.insert(tk.END, f"{room1} ↔ {room2}")

        for room1, room2 in example_non_adjacencies:
            self.non_adjacencies_listbox.insert(tk.END, f"{room1} ✗ {room2}")

    def clear_all_data(self):
        for item in self.regions_tree.get_children():
            self.regions_tree.delete(item)
        for item in self.rooms_tree.get_children():
            self.rooms_tree.delete(item)
        self.adjacencies_listbox.delete(0, tk.END)
        self.non_adjacencies_listbox.delete(0, tk.END)

        # ### NEW: Reset CAD state variables ###
        self.boundary_state = []
        self.final_area = []
        self.fixed_names = []
        self.entrance_grid_coords = []
        self.cad_fixed_rooms = []
        self.floor_plan = None
        self.loaded_json_data = None

        # Reset area stats
        self.total_area.set(0)
        self.update_area_stats()

    def add_region(self):
        try:
            x = int(self.region_x_var.get())
            y = int(self.region_y_var.get())
            width = int(self.region_width_var.get())
            height = int(self.region_height_var.get())

            if width <= 0 or height <= 0:
                messagebox.showerror("Error", "Width and height must be positive")
                return

            region_count = len(self.regions_tree.get_children()) + 1
            item = self.regions_tree.insert("", "end", text=f"Region {region_count}")
            self.regions_tree.set(item, "X", x)
            self.regions_tree.set(item, "Y", y)
            self.regions_tree.set(item, "Width", width)
            self.regions_tree.set(item, "Height", height)

            self.region_x_var.set("")
            self.region_y_var.set("")
            self.region_width_var.set("")
            self.region_height_var.set("")

        except ValueError:
            messagebox.showerror("Error", "Please enter valid numbers")

    def remove_region(self):
        selected = self.regions_tree.selection()
        if selected:
            self.regions_tree.delete(selected[0])

    def edit_region(self):
        selected = self.regions_tree.selection()
        if not selected:
            messagebox.showwarning("Warning", "Please select a region to edit")
            return

        item = selected[0]
        current_x = self.regions_tree.set(item, "X")
        current_y = self.regions_tree.set(item, "Y")
        current_width = self.regions_tree.set(item, "Width")
        current_height = self.regions_tree.set(item, "Height")

        self.region_x_var.set(current_x)
        self.region_y_var.set(current_y)
        self.region_width_var.set(current_width)
        self.region_height_var.set(current_height)

        region_name = self.regions_tree.item(item)['text']
        self.regions_tree.delete(item)

        messagebox.showinfo("Edit Mode",
                            f"Region values loaded into input fields.\nModify the values and click 'Add Region' to save changes.\n\nNote: {region_name} has been temporarily removed.")

    def clear_regions(self):
        for item in self.regions_tree.get_children():
            self.regions_tree.delete(item)

    def save_room_changes(self):
        """Save the edited room data and update the area stats."""
        try:
            new_name = self.edit_name_var.get().strip()
            new_width = int(self.edit_width_var.get())
            new_height = int(self.edit_height_var.get())
            new_max_exp = int(self.edit_max_exp_var.get())

            # Validation
            if not new_name:
                messagebox.showerror("Error", "Please enter a room name")
                return

            if new_width <= 0 or new_height <= 0:
                messagebox.showerror("Error", "Width and height must be positive")
                return

            if new_max_exp < 0:
                messagebox.showerror("Error", "Max expansion cannot be negative")
                return

            # Check if new name already exists (but allow keeping the same name)
            current_name = self.edit_context['current_name']
            if new_name != current_name:
                for item in self.rooms_tree.get_children():
                    if self.rooms_tree.item(item)['text'] == new_name:
                        messagebox.showerror("Error", "Room name already exists")
                        return

            # Update adjacencies if room name changed
            if new_name != current_name:
                self.update_adjacencies_after_room_rename(current_name, new_name)

            # Update the treeview item
            selected_item = self.edit_context['selected_item']
            self.rooms_tree.item(selected_item, text=new_name)
            self.rooms_tree.set(selected_item, "Width", new_width)
            self.rooms_tree.set(selected_item, "Height", new_height)
            self.rooms_tree.set(selected_item, "Max Expansion", new_max_exp)
            self._set_room_tree_area(selected_item, new_width, new_height)
            # Update Need Corridor value from edit dialog checkbox
            try:
                need_corr_val = bool(getattr(self, 'edit_need_corr_var', tk.BooleanVar(value=True)).get())
                self.rooms_tree.set(selected_item, "Need Corridor", "Yes" if need_corr_val else "No")
                # Also update underlying FloorPlan room object if present
                floor = getattr(self, "floorplan", None) or getattr(self, "floor_plan", None)
                if floor is not None and hasattr(floor, 'rooms'):
                    for r in floor.rooms:
                        try:
                            if getattr(r, 'name', None) == new_name or (isinstance(r, dict) and r.get('name') == new_name):
                                try:
                                    setattr(r, 'need_corridor', need_corr_val)
                                except Exception:
                                    # if it's a dict
                                    try:
                                        r['need_corridor'] = need_corr_val
                                    except Exception:
                                        pass
                        except Exception:
                            continue
            except Exception:
                pass

            # Recalculate and display the updated area statistics
            self.update_area_stats()

            # Refresh room combos if name changed
            if new_name != current_name:
                self.refresh_room_combos()

            self.edit_window.destroy()
            messagebox.showinfo("Success", "Room updated successfully")

        except ValueError:
            messagebox.showerror("Error", "Please enter valid numbers")

    def cancel_room_edit(self):
        """Cancel editing and close the dialog."""
        self.edit_window.destroy()

    def update_adjacencies_after_room_rename(self, old_name, new_name):
        """Update adjacency list when a room is renamed."""
        # Get all adjacencies
        adjacencies = []
        for i in range(self.adjacencies_listbox.size()):
            adjacency = self.adjacencies_listbox.get(i)
            # Replace old room name with new name in adjacency strings
            if old_name in adjacency:
                updated_adjacency = adjacency.replace(old_name, new_name)
                adjacencies.append(updated_adjacency)
            else:
                adjacencies.append(adjacency)

        # Clear and repopulate the listbox
        self.adjacencies_listbox.delete(0, tk.END)
        for adjacency in adjacencies:
            self.adjacencies_listbox.insert(tk.END, adjacency)

    def edit_room(self):
        selected = self.rooms_tree.selection()
        if not selected:
            messagebox.showwarning("Warning", "Please select a room to edit")
            return

        self.edit_context = {
            'selected_item': selected[0],
            'current_name': self.rooms_tree.item(selected[0])['text'],
            'current_width': self.rooms_tree.set(selected[0], "Width"),
            'current_height': self.rooms_tree.set(selected[0], "Height"),
            'current_max_exp': self.rooms_tree.set(selected[0], "Max Expansion"),
            'current_area': self.rooms_tree.set(selected[0], "Area"),
            'need_corridor': self.rooms_tree.set(selected[0], "Need Corridor")

        }

        self.edit_window = tk.Toplevel(self.root)
        self.edit_window.title("Edit Room")
        self.edit_window.geometry("400x300")
        self.edit_window.resizable(False, False)
        self.edit_window.transient(self.root)
        self.edit_window.grab_set()

        self.edit_window.update_idletasks()
        x = (self.edit_window.winfo_screenwidth() // 2) - (self.edit_window.winfo_width() // 2)
        y = (self.edit_window.winfo_screenheight() // 2) - (self.edit_window.winfo_height() // 2)
        self.edit_window.geometry(f"+{x}+{y}")

        main_frame = ttk.Frame(self.edit_window, padding=15)
        main_frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(main_frame, text="Edit Room Properties",
                  font=("Arial", 12, "bold")).pack(pady=(0, 10))

        fields_frame = ttk.Frame(main_frame)
        fields_frame.pack(fill=tk.X, pady=5)

        ttk.Label(fields_frame, text="Room Name:").grid(row=0, column=0, sticky=tk.W, pady=5)
        self.edit_name_var = tk.StringVar(value=self.edit_context['current_name'])
        name_entry = ttk.Entry(fields_frame, textvariable=self.edit_name_var, width=20)
        name_entry.grid(row=0, column=1, padx=(10, 0), pady=5, sticky=tk.W)

        ttk.Label(fields_frame, text="Width:").grid(row=1, column=0, sticky=tk.W, pady=5)
        self.edit_width_var = tk.StringVar(value=self.edit_context['current_width'])
        width_entry = ttk.Entry(fields_frame, textvariable=self.edit_width_var, width=20)
        width_entry.grid(row=1, column=1, padx=(10, 0), pady=5, sticky=tk.W)

        ttk.Label(fields_frame, text="Height:").grid(row=2, column=0, sticky=tk.W, pady=5)
        self.edit_height_var = tk.StringVar(value=self.edit_context['current_height'])
        height_entry = ttk.Entry(fields_frame, textvariable=self.edit_height_var, width=20)
        height_entry.grid(row=2, column=1, padx=(10, 0), pady=5, sticky=tk.W)

        ttk.Label(fields_frame, text="Max Expansion:").grid(row=3, column=0, sticky=tk.W, pady=5)
        self.edit_max_exp_var = tk.StringVar(value=self.edit_context['current_max_exp'])
        max_exp_entry = ttk.Entry(fields_frame, textvariable=self.edit_max_exp_var, width=20)
        max_exp_entry.grid(row=3, column=1, padx=(10, 0), pady=5, sticky=tk.W)

        # Need Corridor checkbox for editing
        try:
            init_need = bool(str(self.edit_context.get('need_corridor', 'Yes')).lower().startswith('y'))
        except Exception:
            init_need = True
        self.edit_need_corr_var = tk.BooleanVar(value=init_need)
        need_corr_chk = ttk.Checkbutton(fields_frame, text="Need Corridor", variable=self.edit_need_corr_var)
        need_corr_chk.grid(row=4, column=0, columnspan=2, sticky=tk.W, pady=5)

        button_frame = ttk.Frame(main_frame)
        button_frame.pack(pady=(15, 10))

        ttk.Button(button_frame, text="Save Changes",
                   command=self.save_room_changes).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Cancel",
                   command=self.cancel_room_edit).pack(side=tk.LEFT, padx=5)

        name_entry.focus()
        name_entry.select_range(0, tk.END)

    def add_bulk_rooms(self):
        """Add multiple rooms with the same dimensions (stores literal width*height area)."""
        try:
            base_name = self.bulk_room_name_var.get().strip()
            quantity = int(self.bulk_room_quantity_var.get())
            width = float(self.bulk_room_width_var.get())
            height = float(self.bulk_room_height_var.get())
            bulk_max_exp_str = self.bulk_room_max_exp_var.get().strip()
            max_exp = int(bulk_max_exp_str) if bulk_max_exp_str != "" else 3

            if not base_name:
                messagebox.showerror("Error", "Please enter a base room name")
                return
            if quantity <= 0:
                messagebox.showerror("Error", "Quantity must be positive")
                return
            if width <= 0 or height <= 0:
                messagebox.showerror("Error", "Width and height must be positive")
                return
            if max_exp < 0:
                messagebox.showerror("Error", "Max expansion cannot be negative")
                return

            existing_names = {self.rooms_tree.item(item)['text'] for item in self.rooms_tree.get_children()}
            new_room_names = []
            for i in range(1, quantity + 1):
                room_name = f"{base_name}{i}"
                if room_name in existing_names:
                    messagebox.showerror("Error", f"Room name '{room_name}' already exists")
                    return
                new_room_names.append(room_name)

            if not hasattr(self, "rooms_area_list"):
                self.rooms_area_list = []

            raw_area = width * height
            added_count = 0

            # NEW: read need_corr value for bulk rooms
            try:
                bulk_need_corr = bool(getattr(self, "bulk_room_need_corr_var", tk.BooleanVar(value=True)).get())
            except Exception:
                bulk_need_corr = True

            for room_name in new_room_names:
                try:
                    item = self.rooms_tree.insert("", "end", text=room_name)
                    # Store as strings to avoid Treeview display quirks and force an immediate UI refresh
                    self.rooms_tree.set(item, "Width", str(int(width)))
                    self.rooms_tree.set(item, "Height", str(int(height)))
                    self.rooms_tree.set(item, "Max Expansion", str(int(max_exp)))
                    self._set_room_tree_area(item, width, height)
                    try:
                        # Force the widget to process pending redraws so values appear immediately
                        self.rooms_tree.update_idletasks()
                    except Exception:
                        pass
                    # Set Need Corridor column using bulk toggle
                    self.rooms_tree.set(item, "Need Corridor", "Yes" if bulk_need_corr else "No")

                    # If a FloorPlan model exists, add the room there too (avoid duplicates)
                    try:
                        floor = getattr(self, "floorplan", None) or getattr(self, "floor_plan", None)
                        if floor is not None:
                            if getattr(floor, 'get_room_by_name', None) and floor.get_room_by_name(room_name) is None:
                                room_obj = floor.add_room(room_name, int(width), int(height), max_exp)
                                try:
                                    room_obj.need_corridor = bool(bulk_need_corr)
                                except Exception:
                                    pass
                    except Exception:
                        pass

                    self.rooms_area_list.append(raw_area)
                    added_count += 1
                except Exception as e:
                    messagebox.showerror("Error", f"Failed to add room '{room_name}': {str(e)}")
                    break

            if added_count > 0:
                # --- Update unified stats (main GUI) ---
                try:
                    self.update_area_stats(
                        regions=getattr(self, "last_regions", None),
                        fixed_rooms=getattr(self, "last_fixed_rooms", None),
                        fixed_area=getattr(self, "fixed_area_total", None),
                        rooms=(getattr(self, "floorplan", None).rooms if getattr(self, "floorplan", None) else None)
                    )
                except Exception as e:
                    try:
                        self.update_area_stats()
                    except Exception:
                        print("add_bulk_rooms -> update_area_stats failed:", e)

                # Clear inputs and refresh combos
                self.bulk_room_name_var.set("")
                self.bulk_room_quantity_var.set("")
                self.bulk_room_width_var.set("")
                self.bulk_room_height_var.set("")
                # keep default visible as 3 so subsequent adds show the default
                self.bulk_room_max_exp_var.set("3")
                self.refresh_room_combos()
                messagebox.showinfo("Success", f"Successfully added {added_count} rooms")

        except ValueError:
            messagebox.showerror("Error", "Please enter valid numbers")
        except Exception as e:
            print("add_bulk_rooms error:", e)

        # In FloorPlanGUI clas

    def add_room(self):
        """Add a single room and update UI stats safely."""
        try:
            name = self.room_name_var.get().strip()
            width = float(self.room_width_var.get())
            height = float(self.room_height_var.get())
            room_max_exp_str = self.room_max_exp_var.get().strip()
            max_exp = int(room_max_exp_str) if room_max_exp_str != "" else 3

            if not name:
                messagebox.showerror("Error", "Please enter a room name")
                return
            if width <= 0 or height <= 0:
                messagebox.showerror("Error", "Width and height must be positive")
                return
            if max_exp < 0:
                messagebox.showerror("Error", "Max expansion cannot be negative")
                return

            existing_names = {self.rooms_tree.item(item)['text'] for item in self.rooms_tree.get_children()}
            if name in existing_names:
                messagebox.showerror("Error", f"Room name '{name}' already exists")
                return

            # Add to UI tree
            item = self.rooms_tree.insert("", "end", text=name)
            # Store numeric values as strings to ensure Treeview displays consistently
            self.rooms_tree.set(item, "Width", str(int(width)))
            self.rooms_tree.set(item, "Height", str(int(height)))
            self.rooms_tree.set(item, "Max Expansion", str(int(max_exp)))
            self._set_room_tree_area(item, width, height)
            try:
                self.rooms_tree.update_idletasks()
            except Exception:
                pass
            # NEW: set Need Corridor according to the toggle (default Yes)
            try:
                need_corr = bool(getattr(self, "room_need_corr_var", tk.BooleanVar(value=True)).get())
            except Exception:
                need_corr = True
            self.rooms_tree.set(item, "Need Corridor", "Yes" if need_corr else "No")
            # If a FloorPlan model exists, also add the room to it so backend knows the flag (avoid duplicates)
            try:
                floor = getattr(self, "floorplan", None) or getattr(self, "floor_plan", None)
                if floor is not None:
                    if getattr(floor, 'get_room_by_name', None) and floor.get_room_by_name(name) is None:
                        room_obj = floor.add_room(name, int(width), int(height), max_exp)
                        try:
                            room_obj.need_corridor = bool(need_corr)
                        except Exception:
                            pass
            except Exception:
                pass

            # --- Update stats from the single source of truth: the rooms_tree ---
            self.update_area_stats()

            # Clear inputs (reset max expansion back to default 3 so it's visible for the next add)
            self.room_name_var.set("")
            self.room_width_var.set("")
            self.room_height_var.set("")
            self.room_max_exp_var.set("3")
            self.refresh_room_combos()
            messagebox.showinfo("Success", f"Room '{name}' added successfully")

        except ValueError:
            messagebox.showerror("Error", "Please enter valid numbers")
        except Exception as e:
            print("add_room error:", e)

    def remove_room(self):
        """Remove selected room(s) from UI, internal lists, floorplan and adjacencies, then update stats."""
        try:
            selected = self.rooms_tree.selection()
            if not selected:
                messagebox.showinfo("Remove room", "Please select one or more rooms to remove.")
                return

            # Floorplan object (support both names)
            floor = getattr(self, "floorplan", None) or getattr(self, "floor_plan", None)

            # Ensure rooms_area_list exists
            if not hasattr(self, "rooms_area_list"):
                self.rooms_area_list = []

            removed_any = False
            tolerance = 1e-3

            # We'll collect room names removed to update adjacencies and graphs
            removed_names = []

            for item in selected:
                try:
                    name = self.rooms_tree.item(item, "text")
                except Exception:
                    # fallback: try getting text differently
                    try:
                        name = self.rooms_tree.item(item)['text']
                    except Exception:
                        name = None

                # Get area shown in the UI (if available)
                area_val = 0.0
                try:
                    area_str = self.rooms_tree.set(item, "Area")
                    if area_str not in (None, ""):
                        area_val = float(area_str)
                except Exception:
                    area_val = 0.0

                # Remove one matching numeric entry from rooms_area_list (closest match)
                try:
                    if isinstance(self.rooms_area_list, (list, tuple)) and self.rooms_area_list:
                        idx = next(
                            i for i, v in enumerate(self.rooms_area_list) if abs(float(v) - area_val) <= tolerance)
                        del self.rooms_area_list[idx]
                except StopIteration:
                    try:
                        # try exact removal
                        self.rooms_area_list.remove(area_val)
                    except Exception:
                        pass
                except Exception:
                    pass

                # Remove from floorplan.rooms if present (match by name attribute or dict name)
                try:
                    if floor is not None and hasattr(floor, "rooms"):
                        room_list = getattr(floor, "rooms")
                        # remove by .name or dict 'name'
                        to_remove = None
                        for r in room_list:
                            try:
                                if getattr(r, "name", None) == name or (isinstance(r, dict) and r.get("name") == name):
                                    to_remove = r
                                    break
                            except Exception:
                                continue
                        if to_remove:
                            room_list.remove(to_remove)
                except Exception:
                    pass

                # Remove node from adjacency graphs if present
                try:
                    if floor is not None:
                        if hasattr(floor, "adjacency_graph"):
                            try:
                                floor.adjacency_graph.remove_node(name)
                            except Exception:
                                pass
                        if hasattr(floor, "non_adjacency_graph"):
                            try:
                                floor.non_adjacency_graph.remove_node(name)
                            except Exception:
                                pass
                except Exception:
                    pass

                # Remove adjacency entries from the listbox (scan and remove any lines containing the name)
                try:
                    items_to_remove = []
                    for i in range(self.adjacencies_listbox.size()):
                        try:
                            adjacency = self.adjacencies_listbox.get(i)
                            if name and name in adjacency:
                                items_to_remove.append(i)
                        except Exception:
                            continue
                    for i in reversed(items_to_remove):
                        try:
                            self.adjacencies_listbox.delete(i)
                        except Exception:
                            pass
                except Exception:
                    pass

                # Finally remove the tree item
                try:
                    self.rooms_tree.delete(item)
                except Exception:
                    pass

                if name:
                    removed_names.append(name)
                removed_any = True

            # Refresh combos/controls
            try:
                self.refresh_room_combos()
            except Exception:
                pass

            # Call the unified stats updater
            try:
                self.update_area_stats(
                    regions=getattr(self, "last_regions", None),
                    fixed_rooms=getattr(self, "last_fixed_rooms", None),
                    fixed_area=getattr(self, "fixed_area_total", None),
                    rooms=(getattr(self, "floorplan", None).rooms if getattr(self, "floorplan", None) else None)
                )
            except Exception:
                try:
                    self.update_area_stats()
                except Exception as e:
                    print("remove_room -> update_area_stats failed:", e)

            if removed_any:
                messagebox.showinfo("Remove room", "Selected room(s) removed.")
            else:
                messagebox.showinfo("Remove room", "No rooms were removed.")
        except Exception as e:
            print("remove_room error:", e)
            messagebox.showerror("Error", f"Failed to remove selected rooms: {e}")

    def clear_rooms(self):
        """Clear all non-fixed rooms from the UI and internal lists, then update stats."""
        try:
            # If you want a confirmation, uncomment the following:
            # if not messagebox.askyesno("Clear all rooms", "Are you sure you want to remove all rooms?"):
            #     return

            # Remove every entry in the rooms tree
            for item in list(self.rooms_tree.get_children()):
                try:
                    # before deleting, attempt to remove area from rooms_area_list
                    try:
                        area_str = self.rooms_tree.set(item, "Area")
                        if area_str not in (None, "") and hasattr(self, "rooms_area_list"):
                            try:
                                val = float(area_str)
                                # remove first close match
                                tol = 1e-3
                                idx = next(i for i, v in enumerate(self.rooms_area_list) if abs(float(v) - val) <= tol)
                                del self.rooms_area_list[idx]
                            except Exception:
                                try:
                                    self.rooms_area_list.remove(float(area_str))
                                except Exception:
                                    pass
                    except Exception:
                        pass
                    self.rooms_tree.delete(item)
                except Exception:
                    pass

            # Clear adjacency listbox
            try:
                self.adjacencies_listbox.delete(0, tk.END)
            except Exception:
                pass

            # Remove rooms from floorplan, but keep fixed rooms if desired
            try:
                floor = getattr(self, "floorplan", None) or getattr(self, "floor_plan", None)
                if floor is not None and hasattr(floor, "rooms"):
                    # keep only fixed rooms (rooms with is_fixed True)
                    try:
                        floor.rooms = [r for r in getattr(floor, "rooms", []) if
                                       getattr(r, "is_fixed", False) or (isinstance(r, dict) and r.get("is_fixed"))]
                    except Exception:
                        # fallback: clear all rooms
                        try:
                            floor.rooms.clear()
                        except Exception:
                            pass
            except Exception:
                pass

            # Reset rooms_area_list fully just to be safe
            try:
                if hasattr(self, "rooms_area_list"):
                    self.rooms_area_list.clear()
            except Exception:
                try:
                    self.rooms_area_list = []
                except Exception:
                    pass

            # Refresh combos/controls
            try:
                self.refresh_room_combos()
            except Exception:
                pass

            # Update stats
            try:
                self.update_area_stats(
                    regions=getattr(self, "last_regions", None),
                    fixed_rooms=getattr(self, "last_fixed_rooms", None),
                    fixed_area=getattr(self, "fixed_area_total", None),
                    rooms=(getattr(self, "floorplan", None).rooms if getattr(self, "floorplan", None) else None)
                )
            except Exception:
                try:
                    self.update_area_stats()
                except Exception as e:
                    print("clear_rooms -> update_area_stats failed:", e)

        except Exception as e:
            print("clear_rooms error:", e)
            messagebox.showerror("Error", f"Failed to clear rooms: {e}")

    def refresh_room_combos(self):
        """Refresh the room combo boxes with current room names and the Entrance."""
        room_names = [self.rooms_tree.item(item)['text'] for item in self.rooms_tree.get_children()]

        # <<< FIX: Add "ENTRANCE" to the list if it has been drawn >>>
        if hasattr(self, 'entrance_grid_coords') and self.entrance_grid_coords:
            room_names.insert(0, "ENTRANCE")

        self.room1_combo['values'] = room_names
        self.room2_combo['values'] = room_names

    def add_adjacency(self):
        """Add a new adjacency"""
        room1 = self.room1_combo.get()
        room2 = self.room2_combo.get()

        if not room1 or not room2:
            messagebox.showerror("Error", "Please select both rooms")
            return

        if room1 == room2:
            messagebox.showerror("Error", "A room cannot be adjacent to itself")
            return

        # Check if adjacency already exists (in either direction)
        adjacency1 = f"{room1} ↔ {room2}"
        adjacency2 = f"{room2} ↔ {room1}"

        for i in range(self.adjacencies_listbox.size()):
            existing = self.adjacencies_listbox.get(i)
            if existing == adjacency1 or existing == adjacency2:
                messagebox.showerror("Error", "This adjacency already exists")
                return

        # Add adjacency
        self.adjacencies_listbox.insert(tk.END, adjacency1)

        # Clear selections
        self.room1_combo.set("")
        self.room2_combo.set("")

    def remove_adjacency(self):
        """Remove selected adjacency"""
        selection = self.adjacencies_listbox.curselection()
        if selection:
            self.adjacencies_listbox.delete(selection[0])

    def clear_adjacencies(self):
        """Clear all adjacencies"""
        self.adjacencies_listbox.delete(0, tk.END)

    def add_fixed_room_to_rooms_tree(self, room, w, h):
        """
        Add one fixed room (room object) into the Rooms Tree UI so it appears
        in comboboxes/lists used for adjacency/non-adjacency.
        """
        try:
            if not hasattr(self, "rooms_tree") or self.rooms_tree is None:
                return

            existing_item = None
            for iid in self.rooms_tree.get_children():
                try:
                    if self.rooms_tree.item(iid, "text") == room.name:
                        existing_item = iid
                        break
                except Exception:
                    continue

            item = self.rooms_tree.insert("", "end", text=room.name) if existing_item is None else existing_item

            wf = float(w) if w is not None else 0.0
            hf = float(h) if h is not None else 0.0

            self.rooms_tree.set(item, "Width", int(round(wf)))
            self.rooms_tree.set(item, "Height", int(round(hf)))
            self.rooms_tree.set(item, "Max Expansion", int(getattr(room, "max_expansion", 0)))
            self._set_room_tree_area(item, wf, hf, room_obj=room)

            # Tag the item as 'fixed'
            try:
                existing_tags = list(self.rooms_tree.item(item).get("tags", ()))
                if "fixed" not in existing_tags:
                    existing_tags.append("fixed")
                self.rooms_tree.item(item, tags=tuple(existing_tags))
            except Exception:
                pass  # Ignore tagging errors

            # NEW: set Need Corridor column from room property (default True)
            try:
                need_corr = bool(getattr(room, "need_corridor", True))
                self.rooms_tree.set(item, "Need Corridor", "Yes" if need_corr else "No")
            except Exception:
                pass

        except Exception as e:
            print("add_fixed_room_to_rooms_tree error:", e)

    def _log_need_corr_flags(self, context=""):
        """Debug helper: print need_corridor flags for rooms in the current FloorPlan."""
        try:
            floor = getattr(self, "floorplan", None) or getattr(self, "floor_plan", None)
            if not floor:
                print(f"[need_corr] {context}: no floor_plan present")
                return
            print(f"[need_corr] {context}: FloorPlan rooms: ")
            for r in getattr(floor, 'rooms', []) + getattr(floor, 'fixed_rooms', []):
                try:
                    print(f"   - {getattr(r,'name',None)}: need_corridor={getattr(r,'need_corridor',None)} is_fixed={getattr(r,'is_fixed',False)}")
                except Exception:
                    continue
        except Exception as e:
            try:
                print("[need_corr] logging error:", e)
            except Exception:
                pass

    def add_all_fixed_rooms_to_rooms_tree(self):
        """
        Scan self.floor_plan.rooms (or self.floor_plan.get_rooms()) and ensure
        all fixed rooms are present in the rooms_tree. Useful to call after a
        bulk import or on startup to sync UI.
        """
        try:
            if not hasattr(self, "floor_plan"):
                return
            rooms = getattr(self.floor_plan, "rooms", None)
            if rooms is None:
                # try a getter method
                try:
                    rooms = self.floor_plan.get_rooms()
                except Exception:
                    rooms = None
            if not rooms:
                return

            for room in rooms:
                try:
                    if getattr(room, "is_fixed", False):
                        # try to obtain width/height from room (fallback to 0)
                        w = getattr(room, "width", None)
                        h = getattr(room, "height", None)
                        # many fixed-room creators pass width/height as kwargs; try bounding box
                        if w is None or h is None:
                            # attempt common names
                            w = w or getattr(room, "w", None) or getattr(room, "W", None) or 0
                            h = h or getattr(room, "h", None) or getattr(room, "H", None) or 0
                        # If still missing, fallback to 0
                        w = 0 if w is None else w
                        h = 0 if h is None else h
                        self.add_fixed_room_to_rooms_tree(room, w, h)
                except Exception:
                    continue
        except Exception as e:
            try:
                print("add_all_fixed_rooms_to_rooms_tree error:", e)
            except Exception:
                pass

    def mark_rooms_tree_fixed_items_readonly(self):
        """
        Optional helper: make fixed rows look/behave different. This only tags them
        and optionally disables selection edits if you have handlers that check the tag.
        It does not change Treeview internals (which is non-trivial).
        Use this if elsewhere you want to prevent editing of fixed rows by checking tag "fixed".
        """
        try:
            if not hasattr(self, "rooms_tree"):
                return
            for iid in self.rooms_tree.get_children():
                try:
                    if "fixed" in self.rooms_tree.item(iid).get("tags", ()):
                        # add a visual tag if your Treeview styles tags, otherwise keep for logic checks
                        # Example: if you use ttk.Style you could style a tag named "fixed" — depends on your app.
                        pass
                except Exception:
                    continue
        except Exception:
            pass

    # --- paste into your main App class (where other methods live) ---

    def init_draw_boundary(self):
        """
        Create and register an embedded 'draw_boundary' screen (Frame + Canvas).
        Safe to call multiple times; will only create once.
        """
        try:
            if "draw_boundary" in getattr(self, "screens", {}):
                return

            # frame that will be shown by self.show_screen("draw_boundary")
            frame = ttk.Frame(self.content_frame)
            # create the canvas that redraw_draw_boundary expects as self.canvas
            canvas = tk.Canvas(frame, bg="white")
            canvas.pack(fill="both", expand=True)

            # store references
            self.screens["draw_boundary"] = frame
            # many of your existing drawing helpers reference self.canvas,
            # so set it here to the embedded canvas (this is intended).
            self.canvas = canvas

            # optional: recreate grid if you have such a helper and want it visible immediately
            try:
                if hasattr(self, "create_grid") and callable(self.create_grid):
                    self.create_grid()
            except Exception:
                pass

        except Exception as e:
            # don't break the app if creation fails
            print("init_draw_boundary error:", e)

    def open_draw_boundary(self):
        """
        Show embedded Draw Boundary screen (creating it if missing) and redraw saved content.
        If anything fails, fallback to opening the CAD toplevel (existing behavior).
        """
        try:
            # ensure storage attributes exist
            try:
                if hasattr(self, "ensure_persistent_draw_state") and callable(self.ensure_persistent_draw_state):
                    self.ensure_persistent_draw_state()
            except Exception:
                pass

            # lazily create embedded draw boundary if it doesn't exist
            try:
                if "draw_boundary" not in getattr(self, "screens", {}):
                    try:
                        self.init_draw_boundary()
                    except Exception as e:
                        print("init_draw_boundary failed:", e)
                        # fallback
                        return self.launch_cad_tool() if hasattr(self, "launch_cad_tool") else None
            except Exception:
                # if anything unexpected, try CAD fallback
                return self.launch_cad_tool() if hasattr(self, "launch_cad_tool") else None

            # attempt to repaint from stored state (this calls your existing routine)
            try:
                if hasattr(self, "redraw_draw_boundary") and callable(self.redraw_draw_boundary):
                    self.redraw_draw_boundary()
            except Exception as e:
                print("redraw_draw_boundary() raised:", e)

            # show the embedded screen using your existing show_screen
            try:
                if hasattr(self, "show_screen") and callable(self.show_screen):
                    self.show_screen("draw_boundary")
                else:
                    # if show_screen isn't available, attempt a simple pack fallback
                    try:
                        # hide other screens (if following your app logic)
                        for k, frm in getattr(self, "screens", {}).items():
                            try:
                                frm.forget()
                            except Exception:
                                pass
                        self.screens["draw_boundary"].pack(fill="both", expand=True)
                    except Exception:
                        # fallback to CAD
                        return self.launch_cad_tool() if hasattr(self, "launch_cad_tool") else None
            except Exception as e:
                print("show_screen('draw_boundary') error:", e)
                return self.launch_cad_tool() if hasattr(self, "launch_cad_tool") else None

        except Exception as e:
            print("open_draw_boundary top-level error:", e)
            try:
                return self.launch_cad_tool() if hasattr(self, "launch_cad_tool") else None
            except Exception:
                pass

    # --- end paste ---
    def ensure_persistent_draw_state(self):
        """
        Ensure the attributes used by redraw are present and have sensible defaults.
        Call this before any read/write to final_area/last_fixed_rooms/boundary_state.
        """
        if not hasattr(self, "final_area") or self.final_area is None:
            self.final_area = []  # list of polygons/lines (user's stored main boundaries)
        if not hasattr(self, "last_fixed_rooms") or self.last_fixed_rooms is None:
            self.last_fixed_rooms = []  # list of fixed room shapes
        if not hasattr(self, "boundary_state") or self.boundary_state is None:
            # optional unified store (if you prefer a single list to replay)
            self.boundary_state = []
        # Keep a pointer to embedded canvas name used by redraw_draw_boundary
        if not hasattr(self, "canvas"):
            # don't create a canvas here; init_draw_boundary() creates it.
            self.canvas = getattr(self, "canvas", None)

    def redraw_draw_boundary(self):
        """
        Robust redraw routine that repaints stored shapes to self.canvas.
        Accepts:
          - dict items: {'type':'polygon'/'line'/'rect'/'oval', 'coords':(...), ...}
          - sequence items: interpreted as coords (polygon if >=6 coords, line if 4)
        """
        # Ensure lists exist
        try:
            self.ensure_persistent_draw_state()
        except Exception:
            pass

        canvas = getattr(self, "canvas", None)
        if canvas is None:
            # no embedded canvas available — nothing to draw
            return

        # Clear canvas
        try:
            canvas.delete("all")
        except Exception:
            pass

        # (Optional) draw grid if you have such helper
        try:
            if hasattr(self, "create_grid") and callable(self.create_grid):
                self.create_grid()
        except Exception:
            pass

        # Combine stores (boundary_state may be authoritative if used)
        items = []
        if getattr(self, "boundary_state", None):
            items.extend(self.boundary_state)
        items.extend(getattr(self, "final_area", []) or [])
        items.extend(getattr(self, "last_fixed_rooms", []) or [])

        # Draw each item defensively
        for it in items:
            try:
                # If it's a dict with explicit type/coords
                if isinstance(it, dict):
                    t = it.get("type", "").lower()
                    coords = list(it.get("coords", ()))
                    width = it.get("width", 2)
                    outline = it.get("outline", "black")
                    fill = it.get("fill", "")
                    if t == "polygon":
                        if len(coords) >= 6:
                            canvas.create_polygon(*coords, outline=outline, fill=fill, width=width)
                    elif t == "line":
                        if len(coords) >= 4:
                            canvas.create_line(*coords, width=width)
                    elif t == "rect":
                        if len(coords) == 4:
                            canvas.create_rectangle(*coords, outline=outline, width=width, fill=fill)
                    elif t == "oval":
                        if len(coords) == 4:
                            canvas.create_oval(*coords, outline=outline, width=width, fill=fill)
                    else:
                        # fallback: try polygon or polyline
                        if len(coords) >= 6:
                            canvas.create_polygon(*coords, outline=outline, fill=fill, width=width)
                        elif len(coords) >= 4:
                            canvas.create_line(*coords, width=width)
                else:
                    # treat as sequence of coords
                    try:
                        coords = list(it)
                    except Exception:
                        continue
                    # coords might be nested like [(x1,y1),(x2,y2),...]
                    if coords and isinstance(coords[0], (list, tuple)):
                        flat = []
                        for p in coords:
                            if len(p) >= 2:
                                flat.extend([p[0], p[1]])
                        coords = flat
                    # now coords is flat list
                    if len(coords) >= 6:
                        canvas.create_polygon(*coords, outline="black", fill="", width=2)
                    elif len(coords) >= 4:
                        canvas.create_line(*coords, width=2)
            except Exception as e:
                # continue on any single-item error
                try:
                    print("redraw item error:", e)
                except Exception:
                    pass

    def transfer_cad_to_main(self, cad):
        """
        Copy drawing state from a CAD Toplevel instance `cad` into the main GUI lists and redraw.
        This is tolerant to several naming conventions used by CADApp (tries multiple attribute names).
        Example usage: called by CAD finalize/OK button with the cad instance as arg.
        """
        if cad is None:
            return

        # Ensure our stores exist
        try:
            self.ensure_persistent_draw_state()
        except Exception:
            pass

        # Helper to try multiple attribute names & return first non-empty
        def try_attrs(obj, *names):
            for n in names:
                if hasattr(obj, n):
                    val = getattr(obj, n)
                    if val:
                        return val
            return None

        try:
            # Try to pull polygon/area lists from CAD by common names
            cad_final = try_attrs(cad,
                                  "final_area", "final_areas", "final_polygons",
                                  "areas", "polygons")
            cad_fixed = try_attrs(cad,
                                  "last_fixed_rooms", "fixed_rooms", "cad_fixed_rooms",
                                  "fixed")
            cad_boundary_state = try_attrs(cad, "boundary_state", "stored_boundary", "boundary")

            # If we got a full boundary_state from CAD prefer that (replace or extend)
            if cad_boundary_state is not None:
                # replace main boundary_state (you can change to extend if preferred)
                self.boundary_state = list(cad_boundary_state)
            # copy final area list items
            if cad_final is not None:
                # replace final_area (safer) — change to extend(...) if you want merging
                self.final_area = list(cad_final)
            if cad_fixed is not None:
                self.last_fixed_rooms = list(cad_fixed)

            # If none of the above yielded anything but CAD has a canvas->items, try one more fallback:
            if (not getattr(self, "final_area", [])) and hasattr(cad, "canvas"):
                try:
                    # attempt to read cad.canvas._items if the CAD stored shapes there as a list
                    c = getattr(cad, "canvas")
                    # NO guarantee about internal format; this is only a last-ditch attempt
                    if hasattr(c, "find_all"):
                        # we cannot reconstruct coords easily here reliably, so skip
                        pass
                except Exception:
                    pass

            # After copying, ensure persistence and redraw
            try:
                self.ensure_persistent_draw_state()
            except Exception:
                pass
            try:
                self.redraw_draw_boundary()
            except Exception as e:
                try:
                    print("transfer redraw error:", e)
                except Exception:
                    pass
        except Exception as e:
            try:
                print("transfer_cad_to_main error:", e)
            except Exception:
                pass

    def cad_finalize_callback(self, cad):
        """
        Convenience wrapper you can pass to CAD as its finalize callback.
        Example: CADApp(..., on_finish=lambda: app.cad_finalize_callback(cad))
        """
        try:
            # Transfer CAD state into main app and then close CAD window if it exposes a .close or .destroy
            self.transfer_cad_to_main(cad)
        except Exception:
            pass
        # attempt to close cad safely (CAD may use .destroy(), .close() or .quit())
        try:
            if hasattr(cad, "destroy"):
                cad.destroy()
            elif hasattr(cad, "close"):
                cad.close()
            elif hasattr(cad, "quit"):
                cad.quit()
        except Exception:
            pass

    def debug_print_boundary_state(self):
        """Small helper to print lengths and a preview of stored geometry (useful while debugging)."""
        try:
            self.ensure_persistent_draw_state()
            print("final_area len:", len(self.final_area))
            if self.final_area:
                print(" final_area[0]:", repr(self.final_area[0])[:300])
            print("last_fixed_rooms len:", len(self.last_fixed_rooms))
            if self.last_fixed_rooms:
                print(" last_fixed_rooms[0]:", repr(self.last_fixed_rooms[0])[:300])
            print("boundary_state len:", len(self.boundary_state))
            if self.boundary_state:
                print(" boundary_state[0]:", repr(self.boundary_state[0])[:300])
        except Exception as e:
            try:
                print("debug_print_boundary_state error:", e)
            except Exception:
                pass

    def generate_floor_plan(self):
        """
        Generate the floor plan, now with robust logic to handle state from a loaded JSON file
        or from the CAD tool.
        """
        try:
            # ### NEW LOGIC: Check if the current state is from a recently loaded JSON file ###
            if hasattr(self, 'loaded_json_data') and self.loaded_json_data:
                print("Generating layout based on loaded JSON data...")
                data = self.loaded_json_data
                placements = data.get("results", {}).get("room_placements", [])
                if not placements:
                    raise ValueError("Loaded JSON has no placement results to work with.")

                # 1. Reconstruct a SOLID boundary from the bounding box of all placed rooms.
                # This IGNORES the faulty 'regions' with holes from the file.
                min_x = min(p['x'] for p in placements)
                min_y = min(p['y'] for p in placements)
                max_x = max(p['x'] + p['width'] for p in placements)
                max_y = max(p['y'] + p['height'] for p in placements)
                solid_region = [{'x': 0, 'y': 0, 'width': max_x, 'height': max_y}]
                self.floor_plan = FloorPlan(solid_region)

                # 2. Intelligently identify which rooms from the file should be FIXED.
                fixed_names = []
                cad_blob = data.get("cad_state") or data.get("cad") or {}
                if cad_blob and cad_blob.get("fixed_names"):
                    # New, non-lossy format: We know exactly which rooms are fixed.
                    fixed_names = cad_blob["fixed_names"]
                else:
                    # Old format: Use a heuristic (a good guess) to find fixed rooms.
                    # Rooms with no expansion capability are considered fixed.
                    for room in data.get("rooms", []):
                        if room.get("max_expansion") == 0:
                            fixed_names.append(room["name"])

                print(f"Identified fixed rooms: {fixed_names}")

                # 3. Add all rooms from the UI, fixing the ones we identified.
                placement_dict = {p['name']: p for p in placements}
                cad_fixed_by_name = {
                    fr.get('name'): fr for fr in (cad_blob.get('cad_fixed_rooms') or [])
                    if isinstance(fr, dict) and fr.get('name')
                }
                all_ui_rooms = {self.rooms_tree.item(item)['text'] for item in self.rooms_tree.get_children()}

                for name in all_ui_rooms:
                    original_room_data = next((r for r in data.get("rooms", []) if r['name'] == name), None)
                    if not original_room_data: continue

                    if name in fixed_names and name in placement_dict:
                        # This is a fixed room. Add it with its saved position and size.
                        p = placement_dict[name]
                        fr_payload = cad_fixed_by_name.get(name, {})
                        poly_payload = _normalize_polygon_points(fr_payload.get('polygon') or [])
                        occ_payload = fr_payload.get('occupied_cells') or None
                        print(f"  -> Adding '{name}' as a FIXED room at its saved position.")
                        # Prefer the original room's max_expansion when available (default to 3)
                        try:
                            orig_max = int(original_room_data.get('max_expansion', 3)) if original_room_data else 3
                        except Exception:
                            orig_max = 3
                        room = self.floor_plan.add_fixed_room(width=p['width'], height=p['height'], fixed_x=p['x'],
                                                              fixed_y=p['y'], name=name, max_expansion=orig_max,
                                                              polygon_coords=poly_payload or None,
                                                              occupied_cells=occ_payload)
                        room.is_fixed = True
                    else:
                        # This is a movable room. Add it with its original (unfed) dimensions.
                        print(f"  -> Adding '{name}' as a MOVABLE room.")
                        self.floor_plan.add_room(name, original_room_data['width'], original_room_data['height'],
                                                 original_room_data['max_expansion'])

                # After this generation, we will rely on the CAD tool again.
                self.loaded_json_data = None

            else:
                # This is the original logic for generating from a user drawing in the CAD tool.
                print("Generating layout based on CAD drawing...")
                regions = self.get_regions_data()
                if not regions:
                    messagebox.showerror("Error", "Please define a boundary from the 'Draw Boundary' tool.")
                    return
                self.floor_plan = FloorPlan(regions)

                # Add fixed rooms from CAD
                cad_fixed = getattr(self, 'cad_fixed_rooms', []) or []
                if cad_fixed:
                    floor_height = max(r['y'] + r['height'] for r in regions) if regions else 0
                    for fr in cad_fixed:
                        w, h, fx, fy = int(fr['width']), int(fr['height']), int(fr['x']), int(fr['y'])
                        fy = floor_height - (fy + h)
                        polygon = fr.get('polygon') or []
                        transformed_polygon = []
                        if polygon:
                            normalized_poly = _normalize_polygon_points(polygon)
                            transformed_polygon = [(px, floor_height - py) for px, py in normalized_poly]

                        occupied_cells = fr.get('occupied_cells') or []
                        transformed_cells = []
                        if occupied_cells:
                            transformed_cells = [(int(cx), int(floor_height - 1 - cy)) for cx, cy in occupied_cells]

                        if transformed_polygon:
                            min_px = min(p[0] for p in transformed_polygon)
                            max_px = max(p[0] for p in transformed_polygon)
                            min_py = min(p[1] for p in transformed_polygon)
                            max_py = max(p[1] for p in transformed_polygon)
                            fx = int(round(min_px))
                            fy = int(round(min_py))
                            w = int(round(max_px - min_px))
                            h = int(round(max_py - min_py))

                        room = self.floor_plan.add_fixed_room(width=w, height=h, fixed_x=fx, fixed_y=fy,
                                                              name=fr.get('name'),
                                                              polygon_coords=transformed_polygon or None,
                                                              occupied_cells=transformed_cells or None)
                        room.is_fixed = True

                # Add rooms from UI — fixed rooms get placed at their stored coordinates
                json_fixed = getattr(self, 'json_fixed_rooms', {}) or {}
                for item in self.rooms_tree.get_children():
                    name = self.rooms_tree.item(item)['text']
                    if 'fixed' in self.rooms_tree.item(item).get('tags', []):
                        # Fixed room from JSON — add with stored coordinates
                        if name in json_fixed:
                            fr = json_fixed[name]
                            room_obj = self.floor_plan.add_fixed_room(
                                width=fr['width'], height=fr['height'],
                                fixed_x=fr['x'], fixed_y=fr['y'], name=name
                            )
                            room_obj.is_fixed = True
                            print(f"DEBUG: Placed fixed room '{name}' at ({fr['x']}, {fr['y']}) size {fr['width']}x{fr['height']}")
                        continue  # Skip adding as movable whether or not coords were found
                    width = int(self.rooms_tree.set(item, "Width"))
                    height = int(self.rooms_tree.set(item, "Height"))
                    max_exp = int(self.rooms_tree.set(item, "Max Expansion"))
                    room_obj = self.floor_plan.add_room(name, width, height, max_exp)
                    try:
                        need_corr_val = self.rooms_tree.set(item, "Need Corridor")
                        room_obj.need_corridor = True if str(need_corr_val).lower().startswith("y") else False
                    except Exception:
                        pass

            # --- The rest of the logic is now common for both paths ---
            # Debug: log need_corr flags before generation
            try:
                if hasattr(self, '_log_need_corr_flags') and callable(self._log_need_corr_flags):
                    self._log_need_corr_flags(context='before_generate')
            except Exception:
                pass
            if not self.floor_plan.rooms:
                messagebox.showerror("Error", "No rooms to place.")
                return

            # Add adjacencies and non-adjacencies
            for i in range(self.adjacencies_listbox.size()):
                room1, room2 = self.adjacencies_listbox.get(i).split(" ↔ ")
                self.floor_plan.add_adjacency(room1, room2)
            for i in range(self.non_adjacencies_listbox.size()):
                room1, room2 = self.non_adjacencies_listbox.get(i).split(" ✗ ")
                self.floor_plan.add_non_adjacency(room1, room2)

            # Run the layout algorithm
            max_attempts = int(self.max_attempts_var.get())
            enable_expansion = self.enable_expansion_var.get()
            success = self.floor_plan.generate_layout(max_attempts=max_attempts, enable_expansion=enable_expansion)
            layout_result = getattr(self.floor_plan, "last_layout_result", {}) or {}

            if success:
                messagebox.showinfo("Success", "Floor plan generated successfully!")
                self.update_output_display()
            else:
                messagebox.showwarning("Generation Failed", "Could not place all rooms with the given constraints.")
                if layout_result.get("best_snapshot") or layout_result.get("partial"):
                    self.update_output_display()
        except Exception as e:
            messagebox.showerror("Error", f"An error occurred during generation: {str(e)}")
            import traceback
            traceback.print_exc()

        def update_output_display(self):
            """Update the output display with statistics and visualization"""
            if not self.floor_plan:
                return

            # Clear the statistics text box
            self.stats_text.delete('1.0', tk.END)

            # *** THE FIX IS HERE ***
            # Instead of summing the regions, we now correctly get the total area
            # that was calculated from the main boundary.
            total_area = self.total_area.get()

            # This part remains the same, calculating the area of placed rooms.
            used_area = sum(room.width * room.height for room in self.floor_plan.rooms if room.x is not None)

            stats = f"FLOOR PLAN STATISTICS (Generated)\n{'=' * 30}\n\n"
            stats += f"Total Floor Area: {total_area} square units\n"
            stats += f"Final Used Area: {used_area} square units\n"
            if total_area > 0:
                stats += f"Space Utilization: {used_area / total_area:.2%}\n\n"

            score, adjacent_pairs, violations = self.floor_plan.evaluate_adjacency_score()
            stats += f"Adjacency Score: {score}/{len(self.floor_plan.adjacency_graph.edges)}\n"
            stats += f"Adjacent Pairs: {adjacent_pairs}\n\n"

            stats += "ROOM EXPANSION STATISTICS:\n" + "-" * 30 + "\n"
            for room in self.floor_plan.rooms:
                if room.x is not None:
                    original_area = room.original_width * room.original_height
                    current_area = room.width * room.height
                    expansion_pct = (current_area - original_area) / original_area * 100 if original_area > 0 else 0
                    stats += f"- {room.name}: {room.original_width}x{room.original_height} → {room.width}x{room.height} ({expansion_pct:.1f}% increase)\n"

            stats += "\nFINAL ROOM PLACEMENTS:\n" + "-" * 20 + "\n"
            for room in self.floor_plan.rooms:
                stats += f"{room}\n"

            # Insert the new stats into the text box on the Output tab
            self.stats_text.insert('1.0', stats)

            # Update visualization plot
            self.ax.clear()
            self.visualize_floor_plan()
            self.safe_draw_canvas()

            # Switch to the output screen
            self.show_screen("output")

    def visualize_floor_plan(self):
        """Create matplotlib visualization of the floor plan optimized for large numbers of rooms"""
        if not self.floor_plan:
            return

        # Clear the axis
        self.ax.clear()

        # Calculate dynamic sizing based on number of rooms and floor dimensions
        num_rooms = len(self.floor_plan.rooms)
        floor_area = self.floor_plan.floor_width * self.floor_plan.floor_height
        avg_room_area = floor_area / max(num_rooms, 1)

        # Dynamic font sizing based on room count and average room size
        base_font_size = max(4, min(12, int(np.sqrt(avg_room_area) / 3)))
        title_font_size = max(8, min(16, base_font_size + 4))

        # Draw floor shape with reduced opacity for large plans
        floor_alpha = max(0.1, min(0.3, 1.0 / np.sqrt(num_rooms / 10 + 1)))
        for region in self.floor_plan.floor_regions:
            rect = Rectangle(
                (region['x'], region['y']),
                region['width'],
                region['height'],
                linewidth=max(0.5, min(2, 10 / np.sqrt(num_rooms))),
                edgecolor='black',
                facecolor='lightgray',
                alpha=floor_alpha,
                linestyle='--'
            )
            self.ax.add_patch(rect)

        # Use a more distinguishable color palette for many rooms
        if num_rooms <= 20:
            colors = plt.cm.tab20(np.linspace(0, 1, num_rooms))
        else:
            # For large numbers, use HSV color space for better distribution
            colors = plt.cm.hsv(np.linspace(0, 1, num_rooms))

        # Calculate constraint violations efficiently
        room_violations = self._calculate_room_violations()

        # Determine room styling based on count
        show_room_details = num_rooms <= 50
        show_expansion_info = num_rooms <= 30
        room_line_width = max(0.3, min(2, 20 / np.sqrt(num_rooms)))
        violation_line_width = max(0.5, min(3, 30 / np.sqrt(num_rooms)))

        # Draw rooms with adaptive styling
        for i, room in enumerate(self.floor_plan.rooms):
            if room.x is not None and room.y is not None:
                # Color coding for violations
                if room_violations[room.name] > 0:
                    face_color = 'lightcoral'
                    edge_color = 'darkred'
                    linewidth = violation_line_width
                    alpha = 0.8
                else:
                    face_color = colors[i]
                    edge_color = 'black'
                    linewidth = room_line_width
                    alpha = max(0.4, min(0.7, 1.0 / np.sqrt(num_rooms / 20 + 1)))

                occupied = room.get_occupied_cells() if hasattr(room, "get_occupied_cells") else set()
                if occupied and getattr(room, "is_fixed", False):
                    # Draw fixed rectilinear shapes as exact occupied cells.
                    for cx, cy in occupied:
                        cell_rect = Rectangle(
                            (cx, cy),
                            1,
                            1,
                            linewidth=max(0.2, linewidth * 0.6),
                            edgecolor=edge_color,
                            facecolor=face_color,
                            alpha=alpha
                        )
                        self.ax.add_patch(cell_rect)
                else:
                    rect = Rectangle(
                        (room.x, room.y),
                        room.width,
                        room.height,
                        linewidth=linewidth,
                        edgecolor=edge_color,
                        facecolor=face_color,
                        alpha=alpha
                    )
                    self.ax.add_patch(rect)

                # Adaptive text display
                self._draw_room_text(room, base_font_size, show_room_details, show_expansion_info)

        # 🚪 Draw the entrance on the visualization
        if hasattr(self, 'entrance_coords') and self.entrance_coords:
            # We assume entrance_coords is a list of (x, y) tuples
            # Draw lines between consecutive points
            for i in range(len(self.entrance_coords) - 1):
                x1, y1 = self.entrance_coords[i]
                x2, y2 = self.entrance_coords[i + 1]

                # Plot the line with a distinct color and width
                self.ax.plot([x1, x2], [y1, y2], color='darkorange', linewidth=5, solid_capstyle='round', zorder=10)

        # Simplified constraint visualization for large plans
        constraint_stats = self._draw_constraints_optimized(num_rooms)

        # Set limits and aspect
        self._set_plot_limits()

        # Adaptive title and labels
        title = self._generate_adaptive_title(constraint_stats, num_rooms)
        self.ax.set_title(title, fontsize=title_font_size, fontweight='bold')

        # Show axes labels only for smaller plans
        if num_rooms <= 100:
            self.ax.set_xlabel('Width', fontsize=max(8, base_font_size))
            self.ax.set_ylabel('Height', fontsize=max(8, base_font_size))

        # Adaptive grid
        grid_alpha = max(0.1, min(0.3, 1.0 / np.sqrt(num_rooms / 25 + 1)))
        self.ax.grid(True, alpha=grid_alpha)

        # Smart legend and summary
        self._create_adaptive_legend_and_summary(constraint_stats, num_rooms, base_font_size)

        plt.tight_layout()

        # Add interactive features for room identification
        self._add_room_identification_features(num_rooms)

    def _add_room_identification_features(self, num_rooms):
        """Add interactive features to help identify rooms"""

        # Add click handler for room identification
        def on_click(event):
            if event.inaxes != self.ax:
                return

            # Find room at click location
            clicked_room = None
            for room in self.floor_plan.rooms:
                if room.x is None or room.y is None:
                    continue

                occupied = room.get_occupied_cells() if hasattr(room, "get_occupied_cells") else set()
                if occupied and getattr(room, "is_fixed", False):
                    if event.xdata is None or event.ydata is None:
                        continue
                    px = int(event.xdata)
                    py = int(event.ydata)
                    if (px, py) in occupied:
                        clicked_room = room
                        break
                elif (room.x <= event.xdata <= room.x + room.width and
                      room.y <= event.ydata <= room.y + room.height):
                    clicked_room = room
                    break

            if clicked_room:
                room_id = self._get_room_id(clicked_room)
                info_text = f"Room {room_id}: {clicked_room.name}"
                if hasattr(clicked_room, 'width'):
                    info_text += f"\nSize: {clicked_room.width}x{clicked_room.height}"
                if hasattr(clicked_room, 'original_width'):
                    info_text += f"\nOriginal: {clicked_room.original_width}x{clicked_room.original_height}"

                # Update title with room info
                current_title = self.ax.get_title()
                if " | Selected: " in current_title:
                    current_title = current_title.split(" | Selected: ")[0]
                self.ax.set_title(f"{current_title} | Selected: {info_text.replace(chr(10), ', ')}")
                plt.draw()

        # Connect the click handler
        if hasattr(self, 'fig'):
            self.fig.canvas.mpl_connect('button_press_event', on_click)

        # For large plans, also create a room index
        if num_rooms > 50:
            self._create_room_index()

    def _create_room_index(self):
        """Create a room index for large floor plans"""
        # Ensure all rooms are mapped before creating index
        self._ensure_all_rooms_mapped()

        print(f"\n=== ROOM INDEX ({len(self.floor_plan.rooms)} rooms) ===")

        # Group rooms by first letter for better organization
        room_groups = {}
        for room in self.floor_plan.rooms:
            first_letter = room.name[0].upper()
            if first_letter not in room_groups:
                room_groups[first_letter] = []
            room_id = self._get_room_id(room)
            room_groups[first_letter].append((room_id, room.name, room.width, room.height))

        # Print organized index
        for letter in sorted(room_groups.keys()):
            print(f"\n{letter}:")
            # Sort by room ID within each letter group
            for room_id, name, width, height in sorted(room_groups[letter]):
                print(f"  {room_id:3d}: {name} ({width}x{height})")

        print(f"\nTotal: {len(self.floor_plan.rooms)} rooms")
        print("Click on any room in the plot to see its details in the title.")

    def get_room_by_id(self, room_id):
        """Helper method to get room by ID number"""
        if not hasattr(self, '_room_id_map'):
            self._room_id_map = {}

        # Ensure all rooms are mapped
        if len(self._room_id_map) != len(self.floor_plan.rooms):
            self._ensure_all_rooms_mapped()

        # Reverse lookup
        for room_name, rid in self._room_id_map.items():
            if rid == room_id:
                return next((r for r in self.floor_plan.rooms if r.name == room_name), None)
        return None

    def _ensure_all_rooms_mapped(self):
        """Ensure all rooms have ID mappings"""
        existing_ids = set(self._room_id_map.values())
        next_id = 1

        for room in self.floor_plan.rooms:
            if room.name not in self._room_id_map:
                while next_id in existing_ids:
                    next_id += 1
                self._room_id_map[room.name] = next_id
                existing_ids.add(next_id)
                next_id += 1

    def print_room_list(self):
        """Print a complete list of rooms with their IDs - useful for debugging"""
        print(f"\n=== COMPLETE ROOM LIST ===")
        for i, room in enumerate(self.floor_plan.rooms, 1):
            print(f"{i:3d}: {room.name} - Size: {room.width}x{room.height} - Position: ({room.x}, {room.y})")
        print(f"Total: {len(self.floor_plan.rooms)} rooms")

    def _calculate_room_violations(self):
        """Efficiently calculate constraint violations for all rooms"""
        room_violations = {}

        for room in self.floor_plan.rooms:
            violations = 0
            if room.name in self.floor_plan.non_adjacency_graph:
                for non_adj_room_name in self.floor_plan.non_adjacency_graph[room.name]:
                    non_adj_room = next((r for r in self.floor_plan.rooms if r.name == non_adj_room_name), None)
                    if non_adj_room and room.has_shared_wall_with(non_adj_room):
                        violations += 1
            room_violations[room.name] = violations

        return room_violations

    # def _draw_room_text(self, room, base_font_size, show_details, show_expansion):
    #     """Draw room text with adaptive scaling, detail level, and identification methods"""
    #     num_rooms = len(self.floor_plan.rooms)

    #     # --- Compute floor area as sum of all rooms ---
    #     floor_area = sum(r.width * r.height for r in self.floor_plan.rooms)
    #     room_area = room.width * room.height

    #     # Relative scale factor (room area / floor area), normalized
    #     rel_scale = np.sqrt(room_area / floor_area) if floor_area > 0 else 1

    #     # Scale font: base size * relative factor * tuning multiplier
    #     scaled_font_size = max(6, base_font_size * (0.5 + rel_scale * 2.5))

    #     # --- Decide if text should be shown ---
    #     min_area_for_text = max(4, num_rooms / 50)  # Adaptive minimum area

    #     if scaled_font_size < 4 or room_area < min_area_for_text:
    #         # For very small rooms, fallback to ID only
    #         room_id = self._get_room_id(room)
    #         if room_area >= 2:  # Only show ID if room is not tiny
    #             self.ax.text(
    #                 room.x + room.width / 2,
    #                 room.y + room.height / 2,
    #                 str(room_id),
    #                 ha='center',
    #                 va='center',
    #                 fontsize=max(6, scaled_font_size),
    #                 fontweight='bold',
    #                 color='black',
    #                 clip_on=True
    #             )
    #         return

    #     # --- For larger rooms, show detailed labels ---
    #     display_text = self._get_room_display_text(room, show_details, show_expansion)

    #     # Adaptive text box styling
    #     bbox_alpha = max(0.6, min(0.9, 1.0 / np.sqrt(num_rooms / 30 + 1)))

    #     self.ax.text(
    #         room.x + room.width / 2,
    #         room.y + room.height / 2,
    #         display_text,
    #         ha='center',
    #         va='center',
    #         fontsize=scaled_font_size,
    #         bbox=dict(boxstyle="round,pad=0.2", facecolor="white", alpha=bbox_alpha),
    #         clip_on=True
    #     )

    def _draw_room_text(self, room, base_font_size, show_details, show_expansion):
        """Draw room text with adaptive scaling, detail level, and identification methods, ensuring text fits within room boundaries"""
        num_rooms = len(self.floor_plan.rooms)

        # --- Compute floor area as sum of all rooms ---
        floor_area = sum(r.width * r.height for r in self.floor_plan.rooms)
        room_area = room.width * room.height

        # Relative scale factor (room area / floor area), normalized
        rel_scale = np.sqrt(room_area / floor_area) if floor_area > 0 else 1

        # Initial font size calculation
        initial_font_size = max(6, base_font_size * (0.5 + rel_scale * 4.0))

        # --- Decide if text should be shown ---
        min_area_for_text = max(4, num_rooms / 50)  # Adaptive minimum area

        if initial_font_size < 4 or room_area < min_area_for_text:
            # For very small rooms, fallback to ID only
            room_id = self._get_room_id(room)
            if room_area >= 2:  # Only show ID if room is not tiny
                self.ax.text(
                    room.x + room.width / 2,
                    room.y + room.height / 2,
                    str(room_id),
                    ha='center',
                    va='center',
                    fontsize=max(6, initial_font_size),
                    fontweight='bold',
                    color='black',
                    clip_on=True
                )
            return

        # --- For larger rooms, show detailed labels with boundary check ---
        display_text = self._get_room_display_text(room, show_details, show_expansion)

        # Calculate maximum font size based on room dimensions
        max_font_size = min(
            (room.width * 0.9) / (0.5 + len(display_text.split('\n'))),  # Width constraint
            (room.height * 0.9) / 1.5  # Height constraint (assuming 1.5x line height)
        ) * 72 / 96  # Convert from inches to points (assuming 96 DPI)

        # Use the smaller of calculated and initial font size to fit within boundaries
        scaled_font_size = min(initial_font_size, max(6, max_font_size))

        # Adaptive text box styling
        bbox_alpha = max(0.6, min(0.9, 1.0 / np.sqrt(num_rooms / 30 + 1)))

        self.ax.text(
            room.x + room.width / 2,
            room.y + room.height / 2,
            display_text,
            ha='center',
            va='center',
            fontsize=scaled_font_size,
            bbox=dict(boxstyle="round,pad=0.2", facecolor="white", alpha=bbox_alpha),
            clip_on=True
        )

    def _get_room_id(self, room):
        """Get a unique ID number for the room"""
        if not hasattr(self, '_room_id_map'):
            self._room_id_map = {}

        # If room not in map, add it
        if room.name not in self._room_id_map:
            # Add all rooms that aren't already mapped
            existing_ids = set(self._room_id_map.values())
            next_id = 1

            for r in self.floor_plan.rooms:
                if r.name not in self._room_id_map:
                    # Find next available ID
                    while next_id in existing_ids:
                        next_id += 1
                    self._room_id_map[r.name] = next_id
                    existing_ids.add(next_id)
                    next_id += 1

        return self._room_id_map[room.name]

    def _get_room_display_text(self, room, show_details, show_expansion):
        """Get the display text for a room based on detail level"""
        num_rooms = len(self.floor_plan.rooms)

        if num_rooms > 200:
            # Very large plans: just room ID
            return str(self._get_room_id(room))
        elif num_rooms > 100:
            # Large plans: ID + abbreviated name
            room_id = self._get_room_id(room)
            short_name = room.name[:8] + "..." if len(room.name) > 8 else room.name
            return f"{room_id}\n{short_name}"
        elif num_rooms > 50:
            # Medium plans: ID + name
            room_id = self._get_room_id(room)
            return f"{room_id}: {room.name}"
        else:
            # Small plans: full detail
            display_text = room.name
            if show_details:
                current_size = f"{room.width}x{room.height}"
                display_text = f"{room.name}\n{current_size}"

                if show_expansion and (room.width != room.original_width or room.height != room.original_height):
                    original_size = f"{room.original_width}x{room.original_height}"
                    if room.rotated:
                        display_text += f"\n(from {room.original_height}x{room.original_width})"
                    else:
                        display_text += f"\n(from {original_size})"
            return display_text

    def _draw_constraints_optimized(self, num_rooms):
        """Draw constraint lines with optimization for large room counts"""
        # For very large plans, skip or simplify constraint visualization
        if num_rooms > 200:
            return self._calculate_constraint_stats_only()

        constraint_stats = {
            'adjacent_pairs': [],
            'unsatisfied_adjacencies': [],
            'non_adjacency_satisfied': [],
            'non_adjacency_violated': []
        }

        # Adaptive line styling
        line_alpha = max(0.3, min(0.8, 1.0 / np.sqrt(num_rooms / 20 + 1)))
        line_width = max(0.5, min(2, 15 / np.sqrt(num_rooms)))

        # Show fewer constraint lines for very large plans
        show_all_constraints = num_rooms <= 100
        show_violations_only = num_rooms > 100

        # Process adjacency relationships
        for room1_name, room2_name in self.floor_plan.adjacency_graph.edges:
            room1 = next((r for r in self.floor_plan.rooms if r.name == room1_name), None)
            room2 = next((r for r in self.floor_plan.rooms if r.name == room2_name), None)

            if room1 and room2 and room1.x is not None and room2.x is not None:
                center1 = (room1.x + room1.width / 2, room1.y + room1.height / 2)
                center2 = (room2.x + room2.width / 2, room2.y + room2.height / 2)

                if room1.has_shared_wall_with(room2):
                    constraint_stats['adjacent_pairs'].append((room1_name, room2_name))
                    if show_all_constraints:
                        self.ax.plot([center1[0], center2[0]], [center1[1], center2[1]], 'g-',
                                     linewidth=line_width, alpha=line_alpha)
                else:
                    constraint_stats['unsatisfied_adjacencies'].append((room1_name, room2_name))
                    if show_all_constraints or show_violations_only:
                        self.ax.plot([center1[0], center2[0]], [center1[1], center2[1]], 'r--',
                                     linewidth=line_width * 1.2, alpha=min(0.9, line_alpha * 1.5))

        # Process non-adjacency relationships
        for room1_name, room2_name in self.floor_plan.non_adjacency_graph.edges:
            room1 = next((r for r in self.floor_plan.rooms if r.name == room1_name), None)
            room2 = next((r for r in self.floor_plan.rooms if r.name == room2_name), None)

            if room1 and room2 and room1.x is not None and room2.x is not None:
                center1 = (room1.x + room1.width / 2, room1.y + room1.height / 2)
                center2 = (room2.x + room2.width / 2, room2.y + room2.height / 2)

                if room1.has_shared_wall_with(room2):
                    # Violation - always show these
                    constraint_stats['non_adjacency_violated'].append((room1_name, room2_name))

                    # Violation lines and markers
                    self.ax.plot([center1[0], center2[0]], [center1[1], center2[1]], 'red',
                                 linewidth=line_width * 1.5, linestyle=':', alpha=min(0.9, line_alpha * 1.5))

                    # Show warning markers only for manageable numbers
                    if num_rooms <= 150:
                        marker_size = max(4, min(12, 60 / np.sqrt(num_rooms)))
                        self.ax.plot(center1[0], center1[1], 'rX', markersize=marker_size, alpha=0.9)
                        self.ax.plot(center2[0], center2[1], 'rX', markersize=marker_size, alpha=0.9)
                else:
                    constraint_stats['non_adjacency_satisfied'].append((room1_name, room2_name))
                    if show_all_constraints:
                        self.ax.plot([center1[0], center2[0]], [center1[1], center2[1]],
                                     color='blue', linewidth=line_width, linestyle=':', alpha=line_alpha * 0.7)

        return constraint_stats

    def _calculate_constraint_stats_only(self):
        """Calculate constraint statistics without drawing (for very large plans)"""
        constraint_stats = {
            'adjacent_pairs': [],
            'unsatisfied_adjacencies': [],
            'non_adjacency_satisfied': [],
            'non_adjacency_violated': []
        }

        # Just calculate stats without drawing
        for room1_name, room2_name in self.floor_plan.adjacency_graph.edges:
            room1 = next((r for r in self.floor_plan.rooms if r.name == room1_name), None)
            room2 = next((r for r in self.floor_plan.rooms if r.name == room2_name), None)

            if room1 and room2 and room1.x is not None and room2.x is not None:
                if room1.has_shared_wall_with(room2):
                    constraint_stats['adjacent_pairs'].append((room1_name, room2_name))
                else:
                    constraint_stats['unsatisfied_adjacencies'].append((room1_name, room2_name))

        for room1_name, room2_name in self.floor_plan.non_adjacency_graph.edges:
            room1 = next((r for r in self.floor_plan.rooms if r.name == room1_name), None)
            room2 = next((r for r in self.floor_plan.rooms if r.name == room2_name), None)

            if room1 and room2 and room1.x is not None and room2.x is not None:
                if room1.has_shared_wall_with(room2):
                    constraint_stats['non_adjacency_violated'].append((room1_name, room2_name))
                else:
                    constraint_stats['non_adjacency_satisfied'].append((room1_name, room2_name))

        return constraint_stats

    def _set_plot_limits(self):
        """Set plot limits with padding"""
        max_width = self.floor_plan.floor_width
        max_height = self.floor_plan.floor_height

        # Adaptive padding based on floor size
        padding = max(1, min(5, max(max_width, max_height) * 0.02))

        self.ax.set_xlim(-padding, max_width + padding)
        self.ax.set_ylim(-padding, max_height + padding)
        self.ax.set_aspect('equal')

    def _generate_adaptive_title(self, constraint_stats, num_rooms):
        """Generate title that adapts to room count"""
        if num_rooms <= 50:
            # Detailed title for smaller plans
            title = f'Floor Plan ({num_rooms} rooms) - '
            title += f'Adjacency: {len(constraint_stats["adjacent_pairs"])}/{len(self.floor_plan.adjacency_graph.edges)}'
            if len(self.floor_plan.non_adjacency_graph.edges) > 0:
                title += f', Non-Adjacency: {len(constraint_stats["non_adjacency_satisfied"])}/{len(self.floor_plan.non_adjacency_graph.edges)} satisfied'
        else:
            # Simplified title for large plans
            violations = len(constraint_stats["unsatisfied_adjacencies"]) + len(
                constraint_stats["non_adjacency_violated"])
            if violations > 0:
                title = f'Floor Plan ({num_rooms} rooms) - {violations} constraint violations'
            else:
                title = f'Floor Plan ({num_rooms} rooms) - All constraints satisfied'

        return title

    def _create_adaptive_legend_and_summary(self, constraint_stats, num_rooms, font_size):
        """Create legend and summary that adapt to room count"""

        # Skip detailed legend for very large plans
        if num_rooms > 200:
            self._create_simple_summary(constraint_stats, font_size)
            return

        # Create legend elements based on what's actually shown
        legend_elements = []

        if num_rooms <= 100:  # Full legend for moderate sizes
            if constraint_stats['adjacent_pairs']:
                legend_elements.append(Line2D([0], [0], color='green', linewidth=2,
                                              label=f'Adjacent (satisfied): {len(constraint_stats["adjacent_pairs"])}'))

            if constraint_stats['unsatisfied_adjacencies']:
                legend_elements.append(Line2D([0], [0], color='red', linewidth=2,
                                              linestyle='--', alpha=0.9,
                                              label=f'Adjacent (unsatisfied): {len(constraint_stats["unsatisfied_adjacencies"])}'))

            if len(self.floor_plan.non_adjacency_graph.edges) > 0:
                legend_elements.append(Line2D([0], [0], color='blue', linewidth=2,
                                              linestyle=':', alpha=0.7,
                                              label=f'Non-adjacent constraint: {len(self.floor_plan.non_adjacency_graph.edges)}'))

            if constraint_stats['non_adjacency_violated']:
                legend_elements.append(Line2D([0], [0], color='red', linewidth=3,
                                              linestyle=':', alpha=0.8,
                                              label=f'Non-adjacent (VIOLATED): {len(constraint_stats["non_adjacency_violated"])}'))

        else:  # Simplified legend for larger plans
            violations = len(constraint_stats["unsatisfied_adjacencies"]) + len(
                constraint_stats["non_adjacency_violated"])
            if violations > 0:
                legend_elements.append(Line2D([0], [0], color='red', linewidth=2,
                                              label=f'Constraint violations: {violations}'))

            satisfied = len(constraint_stats["adjacent_pairs"]) + len(constraint_stats["non_adjacency_satisfied"])
            if satisfied > 0:
                legend_elements.append(Line2D([0], [0], color='green', linewidth=2,
                                              label=f'Constraints satisfied: {satisfied}'))

        # Position legend appropriately
        if legend_elements and num_rooms <= 150:
            self.ax.legend(handles=legend_elements, loc='upper left',
                           bbox_to_anchor=(1.02, 1), borderaxespad=0,
                           fontsize=max(6, font_size - 2))

        # Create summary text
        self._create_constraint_summary(constraint_stats, num_rooms, font_size)

    def _create_constraint_summary(self, constraint_stats, num_rooms, font_size):
        """Create constraint summary text with room identification legend"""
        if num_rooms > 300:  # Skip summary for very large plans
            return

        total_constraints = len(self.floor_plan.adjacency_graph.edges) + len(self.floor_plan.non_adjacency_graph.edges)

        summary_text = f"Rooms: {num_rooms}\n"

        if num_rooms <= 100:
            # Detailed summary
            summary_text += f"Adjacency: {len(constraint_stats['adjacent_pairs'])}/{len(self.floor_plan.adjacency_graph.edges)} satisfied\n"
            summary_text += f"Non-adjacency: {len(constraint_stats['non_adjacency_satisfied'])}/{len(self.floor_plan.non_adjacency_graph.edges)} satisfied"

            if constraint_stats['non_adjacency_violated']:
                summary_text += f"\nViolations: {len(constraint_stats['non_adjacency_violated'])} non-adjacency"
        else:
            # Simplified summary
            total_violations = len(constraint_stats["unsatisfied_adjacencies"]) + len(
                constraint_stats["non_adjacency_violated"])
            total_satisfied = len(constraint_stats["adjacent_pairs"]) + len(constraint_stats["non_adjacency_satisfied"])
            if total_constraints > 0:
                summary_text += f"Constraints: {total_satisfied}/{total_constraints} satisfied"
                if total_violations > 0:
                    summary_text += f"\nViolations: {total_violations}"

        # Add identification help for large plans
        if num_rooms > 50:
            summary_text += f"\n\nRoom IDs shown (1-{num_rooms})"
            summary_text += "\nClick plot for room list"

        # Choose background color based on violations
        has_violations = len(constraint_stats["non_adjacency_violated"]) > 0 or len(
            constraint_stats["unsatisfied_adjacencies"]) > 0
        all_satisfied = (len(constraint_stats["adjacent_pairs"]) == len(self.floor_plan.adjacency_graph.edges) and
                         len(constraint_stats["non_adjacency_satisfied"]) == len(
                    self.floor_plan.non_adjacency_graph.edges))

        bg_color = "lightcoral" if has_violations else "lightgreen" if all_satisfied else "lightyellow"

        # Adaptive text size and positioning
        text_font_size = max(6, min(font_size, 12))
        text_alpha = max(0.7, min(0.9, 1.0 / np.sqrt(num_rooms / 50 + 1)))

        self.ax.text(0.02, 0.98, summary_text, transform=self.ax.transAxes,
                     verticalalignment='top',
                     bbox=dict(boxstyle="round,pad=0.3", facecolor=bg_color, alpha=text_alpha),
                     fontsize=text_font_size, fontweight='bold')

    def _create_simple_summary(self, constraint_stats, font_size):
        """Create very simple summary for extremely large plans"""
        total_violations = len(constraint_stats["unsatisfied_adjacencies"]) + len(
            constraint_stats["non_adjacency_violated"])

        if total_violations > 0:
            summary_text = f"{len(self.floor_plan.rooms)} rooms\n{total_violations} violations"
            bg_color = "lightcoral"
        else:
            summary_text = f"{len(self.floor_plan.rooms)} rooms\nAll constraints OK"
            bg_color = "lightgreen"

        self.ax.text(0.02, 0.98, summary_text, transform=self.ax.transAxes,
                     verticalalignment='top',
                     bbox=dict(boxstyle="round,pad=0.3", facecolor=bg_color, alpha=0.8),
                     fontsize=max(8, font_size), fontweight='bold')

        # REPLACE your existing 'create_rooms_tab' function with this:

    def create_rooms_tab(self, parent):
        """
        Creates the tab for adding, removing, and managing rooms.
        Includes a 'Need Corridor' column and a Toggle button.
        """
        room_tab = ttk.Frame(parent)
        parent.add(room_tab, text='Rooms')

        # ---- List frame ----
        room_list_frame = ttk.Frame(room_tab)
        room_list_frame.pack(pady=10, padx=10, fill='both', expand=True)

        ttk.Label(room_list_frame, text="Rooms:", font=('Arial', 12, 'bold')).pack(anchor='w')

        # Tree with 3 columns: Name / Size / Need Corridor
        self.room_list_tree = ttk.Treeview(
            room_list_frame,
            columns=("name", "size", "corridor"),
            show="headings",
            selectmode="browse",
            height=12
        )
        self.room_list_tree.heading("name", text="Name")
        self.room_list_tree.heading("size", text="Size (w×h)")
        self.room_list_tree.heading("corridor", text="Need Corridor")

        self.room_list_tree.column("name", width=180, anchor="w")
        self.room_list_tree.column("size", width=120, anchor="center")
        self.room_list_tree.column("corridor", width=120, anchor="center")

        self.room_list_tree.pack(fill='both', expand=True)

        # ---- Controls frame ----
        room_controls_frame = ttk.Frame(room_tab)
        room_controls_frame.pack(pady=8, padx=10, fill='x')

        # Existing buttons you already have (example; keep your own)
        ttk.Button(room_controls_frame, text="Add Room", command=self.add_room).pack(side=tk.LEFT, padx=5, pady=5)
        ttk.Button(room_controls_frame, text="Remove Room", command=self.remove_room).pack(side=tk.LEFT, padx=5, pady=5)
        ttk.Button(room_controls_frame, text="Rotate Room", command=self.rotate_room_from_list).pack(side=tk.LEFT,
                                                                                                     padx=5, pady=5)

        # NEW: toggle corridor button
        ttk.Button(room_controls_frame, text="Toggle Corridor", command=self.toggle_corridor).pack(side=tk.LEFT, padx=5,
                                                                                                   pady=5)

        # Initial fill
        self.update_room_list()

        # REPLACE your existing 'update_room_list' function with this:

    def update_room_list(self):
        """
        Refresh the room list Treeview with current rooms and their corridor status.
        """
        if not hasattr(self, "room_list_tree"):
            return

        # Clear
        for iid in self.room_list_tree.get_children():
            self.room_list_tree.delete(iid)

        # Nothing to show if floor_plan not ready
        if not getattr(self, "floor_plan", None):
            return

        # Fill
        for room in getattr(self.floor_plan, "rooms", []):
            size_str = f"{room.width}x{room.height}" + (" (R)" if getattr(room, "rotated", False) else "")
            corridor_str = "Yes" if getattr(room, "need_corridor", False) else "No"
            self.room_list_tree.insert("", "end", values=(room.name, size_str, corridor_str))

    def toggle_corridor(self):
        """
        Toggle the 'need_corridor' flag for the selected room and refresh the row.
        """
        if not getattr(self, "floor_plan", None):
            messagebox.showerror("Error", "Floor plan not initialized.")
            return

        sel = self.rooms_tree.selection()
        if not sel:
            messagebox.showwarning("Select a room", "Please select a room in the list.")
            return

        item = sel[0]
        room_name = self.rooms_tree.item(item, "text")
        if not room_name:
            messagebox.showerror("Error", "Could not read the selected room name.")
            return

        room = self.floor_plan.get_room_by_name(room_name)
        if not room:
            messagebox.showerror("Error", f"Could not find room '{room_name}'.")
            return

        # Flip the flag
        room.need_corridor = not bool(getattr(room, "need_corridor", False))

        # Update the one row in the tree
        self.rooms_tree.set(item, "Need Corridor", "Yes" if room.need_corridor else "No")

    def run_genetic_algorithm(self):
        if not self.floor_plan:
            messagebox.showwarning("No Floor Plan", "Please generate a floor plan first.")
            return

        try:
            initial_grid, region_matrix, room_names, room_dimensions, fixed_room_ids = self.floor_plan.floorplan_to_ga_input()
            corridor_width = self.corridor_width_var.get()

            messagebox.showinfo("GA Start",
                                f"Starting Genetic Algorithm optimization with corridor width {corridor_width}. The Genetic Algorithm will now run. This may take a few moments. Please check the console for progress and the final plot window.")

            FloorPlan.ga_runner(initial_grid, region_matrix, room_names, room_dimensions, corridor_width,
                                fixed_room_ids)

        except Exception as e:
            messagebox.showerror("GA Error", f"An error occurred while running the genetic algorithm: {e}")
            import traceback
            traceback.print_exc()


def main():
    root = tk.Tk()
    root.withdraw()  # This hides the main GUI window

    app = FloorPlanGUI(root)

    app.launch_cad_tool()

    root.mainloop()


if __name__ == "__main__":
    main()