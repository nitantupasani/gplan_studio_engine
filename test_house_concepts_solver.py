"""Real solver/whole-house regression fixtures; no local rectangle fallback."""
from copy import deepcopy
import math
import os
import sys
import time

import pytest
from shapely.geometry import Polygon

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from GPLAN.housing.concepts import generate_house_concepts, geometry_fingerprint
from GPLAN.housing.programs import get_profile, program_id, profile_fingerprint
from GPLAN.housing.schema import HouseRequestError, normalize_request, request_fingerprint
from GPLAN.housing.solver import (FloorSolveError, feet_to_mm, mm_to_feet,
                                 minimum_dimensioning, solve_floor)
from GPLAN.housing.validation import validate_house_candidate


def house_request(width=11278, depth=11582, front=0, mode="auto", **changes):
    request={"schema_version":"house_concepts_v1","units":"mm","programme_profile":"NL_concept_v1",
             "plot":{"polygon":[[0,0],[width,0],[width,depth],[0,depth]],"front_edge":front},
             "storeys":{"mode":mode,"allow":["g+1_attic","g+2_attic"]},
             "requested_options":5,"search":{"budget_ms":15000}}
    request.update(changes)
    return request


@pytest.mark.parametrize("value",[1,51,850,2250,11278,11582,12192,1234567])
def test_fractional_feet_adapter_retains_integer_millimetres(value):
    assert feet_to_mm(mm_to_feet(value))==value
    if value !=12192:
        assert mm_to_feet(value)!=int(mm_to_feet(value))


def test_explicit_nl_programme_is_versioned_and_footprint_based():
    profile=get_profile()
    assert profile["band_basis"]=="building_footprint_area_m2"
    assert "under60m2" in program_id("ground",59.999)
    assert "60to100m2" in program_id("ground",60)
    assert "100m2plus" in program_id("ground",100)
    original=profile_fingerprint(profile)
    profile["room_rules"]["wc"]["min_width_mm"]+=1
    assert profile_fingerprint(profile)!=original
    assert get_profile()["room_rules"]["wc"]["min_width_mm"]==900


def test_request_precision_constraints_and_fingerprint_are_not_silently_changed():
    request=normalize_request(house_request())
    assert request["plot"]["polygon"][2]==[11278,11582]
    original=request_fingerprint(request)
    request["roof"]["pitch_deg"]=44.5
    assert request_fingerprint(request)!=original
    bad=house_request()
    bad["plot"]["polygon"][1][0]=11278.3
    with pytest.raises(HouseRequestError,match="integer"):
        normalize_request(bad)
    for changes in [
        {"constraint_policy":{"required":[{"kind":"interior_core","x_mm":2500}]}},
        {"locked_cores":[{"x_mm":2500,"y_mm":2500}]},
        {"units":"ft"},
        {"programme_profile":"NBC"},
    ]:
        with pytest.raises(HouseRequestError):
            normalize_request(house_request(**changes))


def test_every_returned_floor_runs_existing_gplan_dimensioner_without_nbc_or_fixed_room_faking(monkeypatch):
    calls=[]
    original=minimum_dimensioning.main
    def measured(data,*args,**kwargs):
        calls.append(deepcopy(data))
        return original(data,*args,**kwargs)
    monkeypatch.setattr(minimum_dimensioning,"main",measured)
    catalogue=generate_house_concepts(house_request(requested_options=1,storeys={"mode":"g+1_attic","allow":["g+1_attic"]}))
    assert len(catalogue["options"])==1
    option=catalogue["options"][0]
    assert len(calls)==len(option["floors"])==3
    for data,floor in zip(calls,option["floors"]):
        assert sum(bool(n["is_fixed"]) for n in data["nodes"])==1  # only the shared stair
        assert all(n["min_width"]<100 and n["min_height"]<100 for n in data["nodes"])
        assert any(n["min_width"]!=int(n["min_width"]) for n in data["nodes"])
        assert floor["solver"]["hard_bounds_relaxed"] is False
        assert floor["solver"]["strict_envelope"] is True
    assert option["provenance"]["engine"]=="GPLAN"
    assert option["provenance"]["programme_profile"]=="NL_concept_v1"
    assert option["validation"]["valid"] is True


def test_actual_solver_dimensions_change_to_fit_fractional_envelope():
    walls={"interior_mm":102,"exterior_mm":152}
    a,core_a=solve_floor("ground",0,9871,8347,walls,get_profile())
    b,core_b=solve_floor("ground",0,10679,9143,walls,get_profile())
    assert core_a==core_b==(2203,4203)
    assert a["rooms"]!=b["rooms"]
    assert sum(Polygon(r["polygon"]).area for r in a["rooms"])==9871*8347
    assert sum(Polygon(r["polygon"]).area for r in b["rooms"])==10679*9143
    with pytest.raises(FloorSolveError):
        solve_floor("ground",0,4800,4800,walls,get_profile())


def test_legacy_minimum_dimensioning_defaults_survive_a_house_in_same_process():
    before=minimum_dimensioning.upper_bound(4,2)
    assert generate_house_concepts(house_request(requested_options=1))["options"]
    data={"nodes":[{"id":i,"min_width":2,"min_height":2,"max_width":4,"max_height":4,
                     "room_x":i*5,"room_y":5,"room_width":5,"room_height":5} for i in range(2)],
          "edges":[{"source":0,"target":1,"color":"red"}],
          "boundary_rooms":{"west":[0],"east":[1],"north":[0,1],"south":[0,1]}}
    status,_=minimum_dimensioning.main(data,20,20)
    assert status
    assert minimum_dimensioning.adjacency_overlap_floor==minimum_dimensioning.DOOR_OVERLAP_FLOOR==3
    assert minimum_dimensioning.upper_bound(4,2)==before


@pytest.mark.parametrize("front",range(4))
@pytest.mark.parametrize("mode",["g+1_attic","g+2_attic"])
def test_screenshot_complete_catalogue_all_frontages_and_both_modes(front,mode):
    request=house_request(front=front,mode=mode)
    result=generate_house_concepts(request)
    assert len(result["options"])==5,result["notices"]
    assert len({geometry_fingerprint(o) for o in result["options"]})==5
    assert {o["differences"]["stair_side"] for o in result["options"]}=={"left","right"}
    assert {o["differences"]["ground_layout"] for o in result["options"]}=={"kitchen_front","living_front"}
    expected=["ground","first"]+(["second"] if mode=="g+2_attic" else [])+["attic"]
    normalized=normalize_request(request)
    for option in result["options"]:
        assert [f["role"] for f in option["floors"]]==expected
        assert option["validation"]["valid"]
        assert validate_house_candidate(option,normalized,get_profile())["valid"]
        assert option["differences"]["parking"]=="front_access_side"
        assert option["floors"][-1]["has_outgoing_stair"] is False
        assert all(f["stair_opening_polygon"]==option["cores"][0]["opening_polygon"] for f in option["floors"])
        assert option["metrics"]["attic_headroom_qualified_area_m2"]<option["metrics"]["attic_gross_area_m2"]


@pytest.mark.parametrize("width,depth",[(7000,24000),(14000,12000)])
@pytest.mark.parametrize("mode",["g+1_attic","g+2_attic"])
def test_equal_area_narrow_deep_and_wide_shallow_plots(width,depth,mode):
    result=generate_house_concepts(house_request(width,depth,mode=mode))
    assert len(result["options"])==5,result["notices"]
    assert all(option["metrics"]["plot_area_m2"]==168 for option in result["options"])
    assert result["metrics"]["elapsed_ms"]<15000


def test_default_canvas_fractional_feet_walls_and_southern_frontage():
    result=generate_house_concepts(house_request(9144,12192,front=2,
        walls={"interior_mm":102,"exterior_mm":152},setbacks={"front_mm":0,"side_mm":0,"rear_mm":0}))
    assert len(result["options"])==5,result["notices"]
    for option in result["options"]:
        assert option["site"]["entry"][1]==12192
        assert option["walls"]=={"interior_mm":102,"exterior_mm":152}


def test_odd_wall_thickness_and_translated_coordinates_preserve_half_mm_faces():
    request=house_request(requested_options=1,walls={"interior_mm":101,"exterior_mm":200})
    request["plot"]["polygon"]=[[x-2501,y+4313] for x,y in request["plot"]["polygon"]]
    result=generate_house_concepts(request)
    assert result["options"],result["notices"]
    option=result["options"][0]
    assert option["site"]["plot_polygon"]==request["plot"]["polygon"]
    assert any(value!=int(value) for floor in option["floors"] for room in floor["rooms"] for point in room["clear_polygon"] for value in point)
    assert validate_house_candidate(option,normalize_request(request),get_profile())["valid"]


def test_steep_roof_uses_actual_renderer_thickness_for_headroom():
    request=house_request(requested_options=1,roof={"pitch_deg":55,"thickness_mm":0})
    result=generate_house_concepts(request)
    assert result["options"],result["notices"]
    option=result["options"][0]
    assert math.isclose(option["roof"]["effective_vertical_thickness_mm"],106.68/math.cos(math.radians(55)))
    assert validate_house_candidate(option,normalize_request(request),get_profile())["valid"]


def test_required_programme_is_not_replaced_with_fewer_bedrooms_or_combined_wc():
    too_many=generate_house_concepts(house_request(household={"bedrooms":5},search={"budget_ms":5000,"max_candidates":12}))
    assert too_many["options"]==[]
    assert any("bedroom count" in rejection["reason"] for rejection in too_many["rejections"])
    separate=generate_house_concepts(house_request(10000,22000,requested_options=1,household={"bedrooms":2,"bathroom_wc":"separate"}))
    assert separate["options"],separate["notices"]
    first=separate["options"][0]["floors"][1]
    assert {r["role"] for r in first["rooms"]}>={"bathroom","wc"}
    assert not any(r["role"]=="bathroom_wc" for r in first["rooms"])


def test_only_complete_valid_options_are_published_and_failure_is_honest():
    progress=[]
    result=generate_house_concepts(house_request(requested_options=2),progress.append)
    assert progress and len(result["options"])==2
    assert all(o["validation"]["valid"] and o["floors"][-1]["role"]=="attic" for s in progress for o in s["options"])
    none=generate_house_concepts(house_request(4500,6500))
    assert none["options"]==[] and none["notices"]
    roof_fail=generate_house_concepts(house_request(roof={"knee_wall_mm":500,"pitch_deg":30},search={"budget_ms":5000,"max_candidates":6}))
    assert roof_fail["options"]==[]
    assert roof_fail["rejections"]


def test_no_parking_and_no_garden_are_explicit_without_invented_outdoor_access():
    request=house_request(10000,10600,requested_options=1,parking={"preference":"none","cars":0},setbacks={"front_mm":0,"side_mm":0,"rear_mm":0})
    result=generate_house_concepts(request)
    assert result["options"],result["notices"]
    option=result["options"][0]
    assert option["metrics"]["garden_area_m2"]==0
    assert not any(s["role"]=="parking_bay" for s in option["site"]["spaces"])
    assert not any(d.get("external_role")=="garden" for d in option["floors"][0]["doors"])


def test_cancel_and_budget_never_publish_partial_floors():
    def cancelled_observer(snapshot):
        raise AssertionError("No cancelled house can be published.")
    cancelled_observer.is_cancelled=lambda:True
    result=generate_house_concepts(house_request(),cancelled_observer)
    assert not result["options"]
    assert result["metrics"]["stop_reason"]=="cancelled"
    result=generate_house_concepts(house_request(search={"budget_ms":1}))
    assert not result["options"]
    assert result["metrics"]["stop_reason"]=="time budget reached"
    # Broken UI observers do not abort already validated work.
    def broken(_):
        raise RuntimeError("Observer disconnected")
    assert generate_house_concepts(house_request(requested_options=1),broken)["options"]


def test_repeatability_deduplicates_semantics_and_geometry_not_display_names():
    request=house_request(requested_options=2)
    first=generate_house_concepts(request)
    second=generate_house_concepts(request)
    assert [o["id"] for o in first["options"]]==[o["id"] for o in second["options"]]
    renamed=deepcopy(first["options"][0])
    renamed["title"]="A different label"
    for floor in renamed["floors"]:
        for room in floor["rooms"]:
            room["name"]="Translated Dutch room"
    assert geometry_fingerprint(renamed)==geometry_fingerprint(first["options"][0])
    assert validate_house_candidate(renamed,normalize_request(request),get_profile())["valid"]
