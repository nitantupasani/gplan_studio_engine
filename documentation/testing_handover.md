# GPLAN Testing Handover

The files in [GPLAN/](../GPLAN/) that start with `Test_` or `test_` are direct-run scripts. They are not pytest test cases. They exist so you can exercise the API methods with realistic payloads and inspect the printed output.

## Why These Scripts Matter

These scripts are the fastest way to verify a change without going through a network service. They call `Documents` methods directly, so they let you debug the request shape, the response shape, and the algorithmic output in one place.

## File-By-File Guide

### [GPLAN/Test_api.py](../GPLAN/Test_api.py)

This is the general graph-floorplan harness.

What it does:
- builds an `InputGraph` from a request payload
- maps node and edge data into the legacy graph API format
- sets flags such as `rectangular`, `corridor`, `dimensioned`, `minDimEnabled`, and `non_adj`
- calls `Documents.get_floorplans(...)`
- prints the serialized floorplan document

This is the best file for understanding the legacy door-connectivity flow end to end.

### [GPLAN/test_api_boundary_input.py](../GPLAN/test_api_boundary_input.py)

This file focuses on the boundary-to-regions path in the space optimization API.

It demonstrates:
- a rectangular boundary
- an L-shaped boundary
- backward compatibility with the older `regions` input
- a more complex polygon case

Use this file when you change boundary conversion or region decomposition logic.

### [GPLAN/Test_api_space_optimization.py](../GPLAN/Test_api_space_optimization.py)

This is the multi-scenario space optimization suite.

It includes examples for:
- a simple single-region plan
- fixed rooms such as stairs or lifts
- a larger multi-region layout
- no-expansion mode
- an L-shaped region

Use this file for regression testing after changes to `handle_space_optimization` or `Space_Optimization/negNew.py`.

### [GPLAN/test_api_space_optimization_simple.py](../GPLAN/test_api_space_optimization_simple.py)

This is the editable single-request runner for space optimization.

It includes:
- a request template at the top of the file
- a `validate_request(...)` helper
- a `run_test()` helper that prints a human-friendly summary

Use this file when you want to tweak one payload repeatedly and inspect the results quickly.

### [GPLAN/test_api_ga_optimization_simple.py](../GPLAN/test_api_ga_optimization_simple.py)

This is the editable GA runner.

It includes:
- a request template with rooms, walls, labels, windows, and doors
- a printed summary of the GA configuration
- output formatting for the chromosome and optimized bounds

This script is the best quick check for `Space_Optimization/ga_current.py` and `handle_ga_optimization`.

## How To Run Them

From the repository root on Windows:

```bash
py GPLAN\Test_api.py
py GPLAN\test_api_boundary_input.py
py GPLAN\Test_api_space_optimization.py
py GPLAN\test_api_space_optimization_simple.py
py GPLAN\test_api_ga_optimization_simple.py
```

On Unix-like systems, use `python3` and forward slashes instead.

## What To Inspect In The Output

When a script runs, check the following first:
- `status`
- `error.message`
- `ptpg_graph` for the graph floorplan path
- `floor`, `placements`, and `metrics` for space optimization
- `ga_optimization`, `rooms`, and `layout_matrix` for GA

If a result looks wrong, compare the printed request payload with the API reference before you change the algorithm.

## Common Environment Issues

The most common local failures are:
- running the script from the wrong working directory
- missing DLLs for the GA path
- missing `Space_Optimization` imports
- using request keys that do not match the API contract

If the GA script fails during import, check the repo root for the native DLLs first.

## How To Add A New Regression Case

If you need a new test case, copy the closest existing script and keep these rules in mind:
- keep the request shape identical to the API reference
- keep red edges marked as `color = "red"`
- keep boundary polygons rectilinear when testing boundary conversion
- keep wall ids consistent between room objects and the flattened walls list for GA
- keep the request small enough to debug quickly, then scale it up after the shape is correct

## Practical Rule

If you are debugging a change and the algorithm output is confusing, start with the matching script in this folder rather than the GUI. The script output is usually easier to diff against the expected contract.
