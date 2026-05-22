# Contribution Workflow

This guide describes how changes move through this repository and how to handle the external Space_Optimization and GA sources safely.

The short version is:
- merge working changes into `QA` first
- test and stabilize there
- merge finalized batches from `QA` into `PROD`
- after the `PROD` batch is accepted, move the same set of changes into `backend_master`
- for Space Optimization and GA, compare against the external repository instead of blindly copying files

## Branch Promotion Model

This repository uses a staged promotion path.

### 1. QA

`QA` is the integration branch.

Use it for:
- active development
- reviewable merges
- regression testing
- API contract validation
- checking whether a change works with the rest of the repo

When you are working on a feature or fix, the first merge target should be `QA`.

Do not skip `QA` unless the change is a very small emergency fix and the team has explicitly agreed to bypass the normal path.

### 2. PROD

`PROD` is the stabilization and release branch.

Once multiple related changes are complete and `QA` has been tested, merge the accepted batch into `PROD`.

Use `PROD` when:
- the set of changes is finalized enough to release together
- the API behavior has been checked
- the docs and tests match the implementation
- you want a more stable branch than `QA`

### 3. backend_master

`backend_master` is the final branch used after the `PROD` set has been accepted.

The flow is:
- `QA` receives the work first
- `PROD` receives the finalized batch after testing
- `backend_master` is updated from `PROD` after the release batch is ready

This branch should not receive incomplete feature work directly.

## Contribution Steps

Use this sequence for normal changes.

1. Create or switch to a working branch based on `QA`.
2. Make the code change.
3. Update the closest test file for that feature.
4. Update the matching documentation page if the request or response shape changed.
5. Merge the change into `QA`.
6. Run the targeted tests for the affected area.
7. If the batch is stable and ready with other finalized changes, merge `QA` into `PROD`.
8. After the `PROD` batch is approved, move the same release set into `backend_master`.

If the change affects an API response, the docs and test scripts must move with the code.

## Space Optimization And GA Workflow

Space Optimization and GA are handled differently from the door-connectivity code.

The important point is that these modules are not edited as if they were isolated one-file features. The usual workflow is to compare against the external repository and import only the delta that matters.

### What To Compare First

For most syncs, the main files to inspect are:
- [Space_Optimization/negNew.py](../Space_Optimization/negNew.py)
- [Space_Optimization/uinegNew.py](../Space_Optimization/uinegNew.py)

Start with those files because they contain the core behavior that usually changes between imports.

Only widen the review to helper files when the diff clearly depends on them.

### How To Sync Safely

Use this process when the external repository has new changes.

1. Find the last import point you used in this repository.
2. Diff the external repo against that import point.
3. Inspect the changes in `negNew.py` and `uinegNew.py` first.
4. Identify which changes are real product changes and which changes are just formatting, comments, or upstream-only behavior.
5. Manually apply the useful differences to this repository.
6. Keep any local server-specific patches that make the code work here.
7. Run the space optimization and GA test scripts.
8. If a request/response field changes, update the API docs and the test payloads.

### Why Manual Merging Is Preferred

This repository has a few local adjustments that are needed for our server environment.

Because of that, a raw copy from the external repository can break behavior even when the upstream code is correct in its own repo.

Manual review is better because it lets you:
- keep the local fixes that make this deployment work
- import only the upstream deltas that matter
- avoid breaking the API contract
- keep the UI and backend wrappers aligned

### What Usually Counts As A Real Change

When you compare the external repo to this one, pay attention to changes that affect:
- layout logic
- room placement rules
- corridor generation
- API payload structure
- label or wall serialization
- server compatibility
- any code path that the UI or API wrapper calls directly

Treat comment-only edits or style-only edits as low priority unless they also touch behavior.

## What To Test After A Contribution

For door-connectivity work, run the graph/API harnesses that exercise the door path.

For space optimization and GA, use the dedicated API scripts:
- [test_api_boundary_input.py](../GPLAN/test_api_boundary_input.py)
- [test_api_space_optimization_simple.py](../GPLAN/test_api_space_optimization_simple.py)
- [Test_api_space_optimization.py](../GPLAN/Test_api_space_optimization.py)
- [test_api_ga_optimization_simple.py](../GPLAN/test_api_ga_optimization_simple.py)

The most important rule is to test the exact feature you changed before promoting it beyond `QA`.

## Promotion Checklist

Before merging a batch into `PROD`, confirm:
- the code works in `QA`
- the relevant API scripts pass or produce the expected output
- any request or response contract changes are documented
- any server-specific changes in Space Optimization or GA were preserved
- the change is ready to be bundled with the other finalized work

Before moving the same batch to `backend_master`, confirm:
- `PROD` contains the finalized batch
- there are no pending fixes that should stay in `QA`
- the release notes or docs are up to date

## Common Mistakes To Avoid

- merging directly to `PROD` or `backend_master` from an unfinished feature branch
- copying upstream Space Optimization files without checking local server patches
- changing the API payload without updating the test scripts
- updating `negNew.py` but forgetting `uinegNew.py`
- importing a GA change without checking the matching output contract

## Practical Rule Of Thumb

If you are unsure where to make the change, start with the smallest possible diff:
- `QA` first for the initial merge
- only the files that actually changed upstream
- manual merge for Space Optimization and GA
- tests and docs before promotion

That keeps the repo stable while still letting you bring in upstream work quickly.
