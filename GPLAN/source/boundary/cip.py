"""Corner Implying Path Module

This module allows user to find corner implying paths (refer Documentation)
in the given input graph.

This module contains the following functions:

    * find_cip - finds corner implying paths in the graph.
"""

def find_cip(bdy_ordered, shortcuts):
    """Returns cips in the input graph.

    Args:
        bdy_ordered: A list containing boundary nodes in circular order.
        shortcuts: A list containing shortcuts of the input graph.

    Returns:
        cip: A list containing cips of the input graph.
    """
    shortcut_endpts = []
    for shortcut in shortcuts:
        shortcut_endpts.append(shortcut[0])
        shortcut_endpts.append(shortcut[1])
    cip = []
    for shortcut in shortcuts:
        pos_1 = bdy_ordered.index(shortcut[0])
        pos_2 = bdy_ordered.index(shortcut[1])
        if(pos_1 > pos_2):
            pos_1, pos_2 = pos_2, pos_1
            shortcut[0], shortcut[1] = shortcut[1], shortcut[0]
        path_1 = bdy_ordered[pos_1+1:pos_2]
        path_2 = bdy_ordered[pos_2+1:len(bdy_ordered)]
        path_2 = path_2 + bdy_ordered[0:pos_1]
        path_1_cip = 1
        path_2_cip = 1
        for node in path_1:
            if node in shortcut_endpts:
                path_1_cip = 0
                break
        for node in path_2:
            if node in shortcut_endpts:
                path_2_cip = 0
                break
        if(path_1_cip == 1):
            path_1.insert(0, shortcut[0])
            path_1.append(shortcut[1])
            cip.append(path_1)
        if(path_2_cip == 1):
            path_2.insert(0, shortcut[1])
            path_2.append(shortcut[0])
            cip.append(path_2)
    return cip
