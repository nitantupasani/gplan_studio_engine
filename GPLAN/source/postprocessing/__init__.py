"""NBC-aware post-processing of dimensioned floorplans.

`nbc_rules`   - Python mirror of the designer's rulebook
                (gplan-building-designer/src/constants/nbcRules.ts).
`postprocess` - the geometric post-processor: in-tile repair, exterior
                trimming (boundary notches), capped absorption.
"""
