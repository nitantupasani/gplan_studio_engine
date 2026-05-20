# Door Connectivity Update Guide

This is the file to read before you change the door-connectivity pipeline.

The door-connectivity path is the most stateful part of the repository. It starts with a graph of rooms and edge colors, turns that graph into a valid floorplan structure, removes or remaps irregular pieces, and then serializes the result back to the legacy document format.

## What Door Connectivity Means In This Repo

In this codebase:
- black edges mean adjacency
- red edges mean non-adjacency constraints or door-connectivity restrictions
- the algorithm is responsible for preserving the user's intent while still producing a usable floorplan

The algorithm does not just draw edges. It augments the graph, triangulates it, checks for separating triangles, handles irregular rooms, and then reserializes the final graph and floorplan output.

## Files That Own The Pipeline

The most important files are:
- [GPLAN/pythongui/gui.py](../GPLAN/pythongui/gui.py)
- [main.py](../main.py)
- [GPLAN/handlers.py](../GPLAN/handlers.py)
- [GPLAN/source/inputgraph.py](../GPLAN/source/inputgraph.py)
- [GPLAN/source/graphoperations/](../GPLAN/source/graphoperations/)
- [GPLAN/source/irregular/septri.py](../GPLAN/source/irregular/septri.py)
- [GPLAN/source/dimensioning/minimum_dimensioning.py](../GPLAN/source/dimensioning/minimum_dimensioning.py)
- [GPLAN/api.py](../GPLAN/api.py)
- [GPLAN/Test_api.py](../GPLAN/Test_api.py)

If you are changing how the feature behaves, one of these files is almost certainly the ownership boundary.

## End-To-End Flow

### 1. Command Selection

The GUI button in [GPLAN/pythongui/gui.py](../GPLAN/pythongui/gui.py) sets the active command to `door_connectivity`.

From there the flow splits into two entry points:
- GUI mode via [main.py](../main.py)
- API/script mode via [GPLAN/api.py](../GPLAN/api.py) and [GPLAN/Test_api.py](../GPLAN/Test_api.py)

### 2. Handler Setup

`handle_door_connectivity` in [GPLAN/handlers.py](../GPLAN/handlers.py) is the bridge between the UI/API state and the graph algorithms.

It does three important things before the core algorithm runs:
- checks whether the graph is already connected
- collects non-adjacency edges when `ui.get_isNonAdj() == 1`
- writes the final graph state back into the UI object after the algorithm returns

If a change affects how non-adjacency is read, this is the first place to update.

### 3. Graph Augmentation

`InputGraph.door_connectivity` in [GPLAN/source/inputgraph.py](../GPLAN/source/inputgraph.py) is the real algorithmic entry point.

It currently does the following:
- adds biconnectivity edges when needed
- triangulates the graph
- removes or rewrites separating triangles
- checks the embedding for intersections
- tracks `extraedges`
- returns the mutated graph and the PTPG flag

The function may return two values or three values depending on whether the non-adjacency path is active. The handler already knows how to accept both shapes. If you change the return contract, update the handler at the same time.

### 4. Separating Triangle Removal

The heavy lifting for triangle cleanup lives in [GPLAN/source/irregular/septri.py](../GPLAN/source/irregular/septri.py).

This file has separate helpers for:
- standard door connectivity
- door connectivity with non-adjacency edges

This is where the algorithm decides whether it can remove an edge, whether it must replace it with another edge, and whether the resulting graph is still planar and better than the previous state.

### 5. Dummy-Node Cleanup And Edge Preservation

The final cleanup path is in [GPLAN/source/dimensioning/minimum_dimensioning.py](../GPLAN/source/dimensioning/minimum_dimensioning.py).

That file maintains two important globals:
- `irreg_nodes_map`
- `door_connectivity_edges`

Those two structures are how the repo preserves red-edge intent when irregular rooms are split through dummy nodes. The `Door_connectivity_cleanup` block rebuilds the edge list while keeping the user-visible non-adjacency intent intact.

If you touch this cleanup path, make sure you understand why the code maps irregular room pairs back to dummy-node edges before rebuilding `data['edges']`.

## Critical Data Contracts

The following values must stay consistent across the pipeline:

- `graph.matrix`: adjacency matrix used by the algorithm
- `graph.coordinates`: node positions after each augmentation step
- `graph.edgecnt`: edge count after graph changes
- `graph.extraedges`: edges added by augmentation beyond the original graph
- `ui.set_ptpg_graph(...)`: matrix exposed to the API response
- `ui.set_edges(...)`: edge list that gets written back to the UI and document output
- `ui.set_nodeCoordinates(...)`: coordinates used by downstream layout steps
- `door_connectivity_edges`: set of edges that must survive dummy-node remapping
- `irreg_nodes_map`: mapping from irregular-room pairs to merged dummy-node ids

If any of these drift apart, the later serialization steps will look correct in isolation but the overall response will be wrong.

## What To Change For Common Tasks

### If you are changing adjacency or non-adjacency parsing

Update:
- [GPLAN/pythongui/gui.py](../GPLAN/pythongui/gui.py)
- [GPLAN/handlers.py](../GPLAN/handlers.py)
- [GPLAN/api.py](../GPLAN/api.py)
- [GPLAN/Test_api.py](../GPLAN/Test_api.py)

Keep the request shape and the UI state shape aligned.

### If you are changing the graph augmentation algorithm

Update:
- [GPLAN/source/inputgraph.py](../GPLAN/source/inputgraph.py)
- [GPLAN/source/graphoperations/](../GPLAN/source/graphoperations/)
- [GPLAN/source/irregular/septri.py](../GPLAN/source/irregular/septri.py)

Do not change the handlers first. Change the algorithm and then adjust the wrapper around it.

### If you are changing how irregular rooms or dummy nodes are handled

Update:
- [GPLAN/source/irregular/septri.py](../GPLAN/source/irregular/septri.py)
- [GPLAN/source/dimensioning/minimum_dimensioning.py](../GPLAN/source/dimensioning/minimum_dimensioning.py)

These two files need to move together because one creates or preserves the irregular structure and the other cleans it up for output.

### If you are changing the API output

Update:
- [GPLAN/api.py](../GPLAN/api.py)
- [GPLAN/Test_api.py](../GPLAN/Test_api.py)
- [documentation/api_reference.md](api_reference.md)

The output format in the API wrapper should match what the tests print and what the docs promise.

## Safe Edit Procedure

When you change the pipeline, use this sequence:

1. Reproduce the current behavior with [GPLAN/Test_api.py](../GPLAN/Test_api.py) or the GUI path.
2. Decide which layer owns the change.
3. Change only that layer first.
4. Verify the graph still returns a valid PTPG result.
5. Verify the final serialized output still matches the expected edge colors, coordinates, and room list.
6. Only then make follow-up edits in the wrappers or docs.

This repo becomes hard to debug when multiple layers are changed at once.

## Common Failure Modes

These are the problems I would check first if the output looks wrong:
- forgetting to clear `door_connectivity_edges` in `reinitialize`
- forgetting to update `graph.edgecnt` after matrix mutation
- losing a red edge during `dummy_node_adj` cleanup
- mixing 0-based and 1-based node numbering
- returning a graph that is structurally valid but no longer matches the serialized edge list
- updating the matrix but not updating the coordinate list

## Regression Checklist

Before you ship a door-connectivity change, verify all of these:
- a simple connected graph still works
- a graph with red non-adj edges still works
- a graph that needs dummy-node cleanup still preserves the intended edge colors
- the API response still includes `ptpg_graph` when expected
- the GUI path still returns a floorplan
- the test harness still prints the expected document structure

## Rule Of Thumb

If you are unsure where to edit, start from the closest control point:
- parsing or dispatch issues go in [GPLAN/handlers.py](../GPLAN/handlers.py) or [GPLAN/api.py](../GPLAN/api.py)
- graph math goes in [GPLAN/source/inputgraph.py](../GPLAN/source/inputgraph.py)
- triangle cleanup goes in [GPLAN/source/irregular/septri.py](../GPLAN/source/irregular/septri.py)
- dummy-node and red-edge preservation goes in [GPLAN/source/dimensioning/minimum_dimensioning.py](../GPLAN/source/dimensioning/minimum_dimensioning.py)

That is the fastest way to avoid chasing symptoms in the wrong layer.
