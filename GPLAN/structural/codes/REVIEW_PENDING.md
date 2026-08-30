# Review pending (codes)

Queue: `GPLAN_Revamp/structural_research/FABLE_REVIEW_QUEUE.md`. Working-tree scaffolding, delete before the first commit.

These are PRINT reviews: the model tier matters less than a line-by-line check against the printed standard. Every `data/*.yaml` entry carrying `verify: print` clears in the same pass, after which the flag is dropped.

| File | Source to check against | Status |
|---|---|---|
| `is456.py` | IS 456:2000 Annex G, Cl 40 and Table 19 and 20, Cl 23.2.1 with Fig 4 to 6, Cl 26, Cl 39, Annex D Table 26 and 27, Cl 34 and 31.6; SP 16 worked examples | PRINT |
| `is1905.py` | IS 1905:1987 Tables 4, 5, 6, 8, 9, 10 and Cl 5.4; SP 20 worked examples (see `tests/vectors/sp20/`) | PRINT |
| `is4326.py` | IS 4326:1993 Tables 4, 6, 7 and the category map | PRINT |
| `is13920.py` | IS 13920:2016 Cl 6 and 7, especially the Ash branches and the confining length | PRINT |
| `is6403.py` | IS 6403:1981 factors, cross-checked against published Vesic values | PRINT |
| `is875.py` | IS 875 Part 1 unit weights, Part 2 Table 1 and the reduction table, Part 3 zones, k2 grid, Cpe and Cpi tables | PRINT |
| `is1893.py` | IS 1893 Part 1:2016 Table 2, 8, 9, 10, the spectra, Cl 7.6 periods and the minimum base shear coefficients | PRINT |

`trace.py` is machinery, no review pending.
