"""
Boundary and region utilities for GPLAN.
Shared logic for converting polygon boundaries to rectangular regions.
"""


def point_inside_polygon(x, y, polygon):
    """
    Ray-casting algorithm to check if point (x, y) is inside polygon.
    
    Args:
        x: X-coordinate of the point
        y: Y-coordinate of the point
        polygon: List of (x, y) tuples representing polygon vertices
        
    Returns:
        True if point is inside polygon, False otherwise
    """
    if not polygon or len(polygon) < 3:
        return False
    
    n = len(polygon)
    inside = False
    
    p1x, p1y = polygon[0]
    for i in range(1, n + 1):
        p2x, p2y = polygon[i % n]
        if y > min(p1y, p2y):
            if y <= max(p1y, p2y):
                if x <= max(p1x, p2x):
                    if p1y != p2y:
                        xinters = (y - p1y) * (p2x - p1x) / (p2y - p1y) + p1x
                    if p1x == p2x or x <= xinters:
                        inside = not inside
        p1x, p1y = p2x, p2y
    
    return inside


def decompose_boundary_into_rectangles(boundary_coords, fixed_rooms=None, unit_spacing=1):
    """
    Decomposes a polygon boundary into rectangular regions, excluding fixed room areas.
    
    This is the core algorithm used by both the UI (CAD tool) and the API.
    
    Args:
        boundary_coords: List of (x, y) tuples representing the main boundary polygon
        fixed_rooms: Optional list of fixed room polygons, each as list of (x, y) tuples
        unit_spacing: Grid spacing multiplier (default 1)
        
    Returns:
        List of region dictionaries with keys: x, y, width, height
        
    Algorithm:
        1. Collect all unique X and Y coordinates from boundary and fixed rooms
        2. Create a grid of cells using these coordinates as divisions
        3. Test center of each cell:
           - Include if inside boundary
           - Exclude if inside any fixed room
        4. Merge adjacent rectangles that share edges
        5. Normalize coordinates (flip Y if needed)
    """
    if not boundary_coords or len(boundary_coords) < 3:
        return []
    
    fixed_rooms = fixed_rooms or []
    
    # Scale coordinates by unit_spacing
    main_polygon = [(x * unit_spacing, y * unit_spacing) for x, y in boundary_coords]
    scaled_fixed_areas = []
    for fixed_room in fixed_rooms:
        if fixed_room and len(fixed_room) >= 3:
            scaled_fixed_areas.append([(x * unit_spacing, y * unit_spacing) for x, y in fixed_room])
    
    # Get all unique x and y coordinates from the main boundary and all fixed shapes
    all_coords = list(main_polygon)
    for area in scaled_fixed_areas:
        all_coords.extend(area)
    
    x_coords = sorted(list(set(p[0] for p in all_coords)))
    y_coords = sorted(list(set(p[1] for p in all_coords)))
    
    # Create a grid of cells and check if the center of each cell is valid
    regions = []
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
            if not point_inside_polygon(mid_x, mid_y, main_polygon):
                continue
            
            # Check if the point is inside any of the fixed shapes (excluded areas)
            is_excluded = False
            for area in scaled_fixed_areas:
                if point_inside_polygon(mid_x, mid_y, area):
                    is_excluded = True
                    break
            
            if not is_excluded:
                regions.append({'x': x_start, 'y': y_start, 'width': width, 'height': height})
    
    # --- Merge adjacent rectangles ---
    merged = True
    while merged:
        merged = False
        for r1 in regions:
            for r2 in regions:
                if r1 == r2:
                    continue
                
                # Merge if they share a vertical edge and have the same height
                if (r1['x'] + r1['width'] == r2['x'] and 
                    r1['y'] == r2['y'] and 
                    r1['height'] == r2['height']):
                    r1['width'] += r2['width']
                    regions.remove(r2)
                    merged = True
                    break
                
                # Merge if they share a horizontal edge and have the same width
                if (r1['y'] + r1['height'] == r2['y'] and 
                    r1['x'] == r2['x'] and 
                    r1['width'] == r2['width']):
                    r1['height'] += r2['height']
                    regions.remove(r2)
                    merged = True
                    break
            
            if merged:
                break
    
    # Normalize coordinates - flip y-coordinates
    if regions:
        max_y = max(r['y'] + r['height'] for r in regions)
        for region in regions:
            region['y'] = max_y - (region['y'] + region['height'])
    
    return regions


def boundary_to_regions(boundary_coords):
    """
    Simplified wrapper for API usage - converts boundary to regions without fixed rooms.
    
    Args:
        boundary_coords: List of [x, y] coordinate pairs
        
    Returns:
        List of region dictionaries with keys: x, y, width, height
    """
    # Convert [[x, y], ...] format to [(x, y), ...] format
    polygon_coords = [(point[0], point[1]) for point in boundary_coords]
    
    # Use the shared decomposition function
    return decompose_boundary_into_rectangles(polygon_coords, fixed_rooms=None, unit_spacing=1)
