"""Bounded site/whole-house search around GPLAN's existing floor solver."""
from collections import Counter
from copy import deepcopy
import hashlib
import itertools
import json
import math
import time

from shapely.geometry import LineString, Point, Polygon, box
from shapely.ops import unary_union

from . import ENGINE_VERSION, SCHEMA_VERSION
from .programs import get_profile, profile_fingerprint
from .schema import normalize_request, request_fingerprint
from .solver import (FloorSolveError, SOLVER_LOCK, SOLVER_NAME, build_blueprint,
                     clear_face_shape, polygon_points, solve_floor, _segments)


class HouseCandidateError(ValueError):
    pass


def _polygons(shape):
    if shape.is_empty:
        return []
    if shape.geom_type == "Polygon":
        return [shape]
    return [p for g in getattr(shape, "geoms", ()) for p in _polygons(g)]


def _rect_decompose(shape):
    """Dissect outdoor residuals with holes into ordinary display polygons."""
    for polygon in _polygons(shape):
        if not polygon.interiors:
            yield polygon
            continue
        ys = sorted({round(y, 6) for ring in [polygon.exterior, *polygon.interiors] for _, y in ring.coords})
        xmin, _, xmax, _ = polygon.bounds
        for y0, y1 in zip(ys, ys[1:]):
            yield from _polygons(polygon.intersection(box(xmin, y0, xmax, y1)))


def _front_frame(request):
    points = request["plot"]["polygon"]
    edge = request["plot"]["front_edge"]
    a, b = points[edge], points[(edge + 1) % 4]
    cx, cy = sum(p[0] for p in points)/4, sum(p[1] for p in points)/4
    mx, my = (a[0]+b[0])/2, (a[1]+b[1])/2
    vx, vy = (0, 1 if cy > my else -1) if a[1] == b[1] else (1 if cx > mx else -1, 0)
    ux, uy = vy, -vx
    origin = min((a,b), key=lambda p: p[0]*ux+p[1]*uy)
    width = round(math.dist(a,b))
    depth = round(abs((cx-mx)*vx+(cy-my)*vy)*2)
    return {"origin": origin, "u": (ux,uy), "v": (vx,vy), "width":width, "depth":depth, "front": [a,b]}


def _point_to_world(point, frame, quantize=True):
    coordinates=[frame["origin"][0]+point[0]*frame["u"][0]+point[1]*frame["v"][0],
                 frame["origin"][1]+point[0]*frame["u"][1]+point[1]*frame["v"][1]]
    return [round(c) for c in coordinates] if quantize else coordinates


def enumerate_site_envelopes(request):
    frame = _front_frame(request)
    pw,pd=frame["width"],frame["depth"]
    s=request["setbacks"]
    walls=request["walls"]
    # Cheap lower bounds from the supported ground/upper contact programmes:
    # 2m core + 1.1m circulation + 2.5m bedroom, and 4m core + 1.25m WC +
    # 2.2m rear kitchen. These prune impossible sites without spending a floor
    # solve or a bounded candidate slot; all surviving floors still solve.
    minimum_width=5600+2*walls["exterior_mm"]+2*walls["interior_mm"]
    minimum_depth=7450+2*walls["exterior_mm"]+2*walls["interior_mm"]
    # Preserve the existing catalogue order; frontage-parallel parking is a
    # further supported choice when front-depth/side-width reservations fail.
    parking_modes=["perpendicular","front_access_side","parallel"] if request["parking"]["cars"] else ["none"]
    candidates=[]
    for parking_mode in parking_modes:
        forecourt=max(s["front_mm"],5200 if parking_mode=="perpendicular" else 2800 if parking_mode=="parallel" else 1100)
        side_reserve=3000 if parking_mode=="front_access_side" else 0
        available_w=pw-2*s["side_mm"]-side_reserve
        available_d=pd-forecourt-s["rear_mm"]
        base_w=min(available_w,12800)
        base_d=min(available_d,9500)
        # Deliberate 0.8m changes alter useful room/garden proportions, never
        # tiny coordinate jitter or IDs used to pad the catalogue.
        for shrink_w,shrink_d in [(0,0),(800,0),(0,800),(1600,0),(0,1600)]:
            w,d=base_w-shrink_w,base_d-shrink_d
            if w < minimum_width or d < minimum_depth:
                continue
            x=round((pw-side_reserve-w)/2)
            candidates.append({"frame":frame,"x":x,"y":forecourt,"width":w,"depth":d,"parking_mode":parking_mode,
                "side_reserve":side_reserve,"id":f"{parking_mode}-{w}x{d}"})
    return candidates


def _transform_floor(floor, site, mirror):
    def point(p,quantize=True):
        x=site["width"]-p[0] if mirror else p[0]
        return _point_to_world([site["x"]+x,site["y"]+p[1]],site["frame"],quantize=quantize)
    for room in floor["rooms"]:
        for key in ("polygon","clear_polygon"):
            room[key]=[point(p,quantize=key!="clear_polygon") for p in room[key]]
        room["cells"]=[[point(p) for p in poly] for poly in room["cells"]]
    for opening in floor["doors"]+floor["windows"]:
        opening["segment"]=[point(p) for p in opening["segment"]]
    return point


def _space(identifier, name, kind, role, polygon, frame):
    return {"id":identifier,"name":name,"kind":kind,"role":role,"render":role not in {"vehicle_access","pedestrian_access"},
            "polygon":[_point_to_world(p,frame) for p in polygon_points(polygon)]}


def _build_site(candidate, ground_floor, request, mirror):
    frame=candidate["frame"]
    pw,pd=frame["width"],frame["depth"]
    x,y,w,d=(candidate[k] for k in ("x","y","width","depth"))
    footprint=box(x,y,x+w,y+d)
    entrance=next(door for door in ground_floor["doors"] if door.get("external_role")=="entrance")
    world_entrance=[round(sum(p[i] for p in entrance["segment"])/2) for i in (0,1)]
    local_entrance=[sum((world_entrance[i]-frame["origin"][i])*frame[v][i] for i in (0,1)) for v in ("u","v")]
    walk=box(local_entrance[0]-550,0,local_entrance[0]+550,y)
    site_shapes=[]
    spaces=[]
    if request["parking"]["cars"]:
        parallel=candidate["parking_mode"]=="parallel"
        bw,bd=(5200,2600) if parallel else (2500,5000)
        bx=300 if mirror else pw-300-bw
        bay=box(bx,100,bx+bw,100+bd)
        car=box(bx+150,400,bx+bw-150,100+bd-300) if parallel else box(bx+300,250,bx+bw-300,100+bd-150)
        drive_extra=max(0,(2800-bw)/2)
        drive=box(bx-drive_extra,0,bx+bw+drive_extra,100+bd)
        if not box(0,0,pw,pd).covers(bay) or bay.intersection(footprint).area > 0 or walk.intersection(car).area > 0 or walk.distance(car) < 100:
            raise HouseCandidateError("Parking and a 1.1m entrance path do not fit simultaneously with a parked car.")
        parking=_space("parking_bay",("Parallel" if parallel else "Perpendicular")+" parking bay","parking","parking_bay",bay,frame)
        parking["car_polygon"]=[_point_to_world(p,frame) for p in polygon_points(car)]
        parking["orientation"]="parallel" if parallel else "perpendicular"
        spaces += [parking,_space("vehicle_access","Vehicle approach","open","vehicle_access",drive,frame)]
        site_shapes += [bay,drive]
        # A separate branch reaches the side of the parking bay without
        # crossing the parked car. The clear street-to-door trunk remains open.
        bay_side=bx+bw if mirror else bx
        branch_y=550 if candidate["parking_mode"]=="front_access_side" else 100+bd/2
        walk=unary_union([walk,box(min(local_entrance[0],bay_side),branch_y-550,max(local_entrance[0],bay_side),branch_y+550)])
        if walk.intersection(car).area>0:
            raise HouseCandidateError("The parking-to-entrance path would pass through the represented car.")
    spaces.append(_space("pedestrian_access","Entrance path","open","pedestrian_access",walk,frame))
    site_shapes.append(walk)
    garden=box(0,y+d,pw,pd)
    if garden.area:
        spaces.append(_space("rear_garden","Rear garden","green","garden",garden,frame))
        site_shapes.append(garden)
    else:
        # No rear land means no claimed garden connection beyond the plot.
        ground_floor["doors"]=[door for door in ground_floor["doors"] if door.get("external_role")!="garden"]
    residual=box(0,0,pw,pd).difference(unary_union([footprint,*site_shapes]))
    for i,p in enumerate(_rect_decompose(residual)):
        if p.area:
            spaces.append(_space(f"forecourt_{i}","Forecourt / side access","open","forecourt",p,frame))
    return {"plot_polygon":deepcopy(request["plot"]["polygon"]),
            "footprint":[_point_to_world(p,frame) for p in polygon_points(footprint)],
            "front_boundary":deepcopy(frame["front"]),"entrance_point":world_entrance,"entry":_point_to_world([local_entrance[0],0],frame),"spaces":spaces,
            "parking_access_status":("frontage_access_envelope_reserved" if candidate["parking_mode"]=="parallel" else "straight_clear_approach_reserved") if request["parking"]["cars"] else "not_requested",
            "vehicle_manoeuvring_status":"not_assessed","pedestrian_clear_width_mm":1100}


def _roof_vertical_thickness(roof):
    # The current renderer extrudes 0.35ft normal to the roof slope. Keep
    # headroom conservative at steep pitches even when the requested vertical
    # concept clearance budget is smaller than that physical extrusion.
    return max(roof["thickness_mm"],106.68/math.cos(math.radians(roof["pitch_deg"])))


def _roof_zone(footprint,roof,height):
    x0,y0,x1,y1=footprint.bounds
    inset=max(0,(height-roof["knee_wall_mm"]+_roof_vertical_thickness(roof))/math.tan(math.radians(roof["pitch_deg"]))-roof["overhang_mm"])
    if roof["ridge_axis"]=="x":
        return box(x0,y0+inset,x1,y1-inset) if 2*inset<y1-y0 else Polygon()
    return box(x0+inset,y0,x1-inset,y1) if 2*inset<x1-x0 else Polygon()


def _roof_headroom(point,footprint,roof):
    x0,y0,x1,y1=footprint.bounds
    distance=min(point[1]-y0,y1-point[1]) if roof["ridge_axis"]=="x" else min(point[0]-x0,x1-point[0])
    return roof["knee_wall_mm"]+(distance+roof["overhang_mm"])*math.tan(math.radians(roof["pitch_deg"]))-_roof_vertical_thickness(roof)


def _coordinate_roof(option,request,profile):
    footprint=Polygon(option["site"]["footprint"])
    x0,y0,x1,y1=footprint.bounds
    axis="x" if x1-x0 >= y1-y0 else "y"
    if request["roof"].get("ridge_axis",axis)!=axis:
        raise HouseCandidateError("The requested roof ridge axis conflicts with the supported long-axis gable geometry.")
    roof={**request["roof"],"ridge_axis":axis,"knee_wall_mm":request["roof"].get("knee_wall_mm",1500)}
    roof.update({"thickness_basis":"vertical_clearance","renderer_normal_thickness_mm":106.68,"effective_vertical_thickness_mm":_roof_vertical_thickness(roof)})
    attic=option["floors"][-1]
    roof["base_elevation_mm"]=attic["elevation_mm"]
    span=(y1-y0) if axis=="x" else x1-x0
    roof["ridge_height_mm"]=round(roof["base_elevation_mm"]+roof["knee_wall_mm"]+(span/2+roof["overhang_mm"])*math.tan(math.radians(roof["pitch_deg"])))
    roof["headroom_zones"]=[]
    for height in sorted({2100,2300,profile.get("occupied_headroom_mm",2100)}):
        zone=_roof_zone(footprint,roof,height)
        if not zone.is_empty:
            # Derived roof intersections retain sub-mm precision. Floor tiling,
            # cores, site and physical opening geometry remain integer mm.
            roof["headroom_zones"].append({"min_height_mm":height,"polygon":[list(p) for p in list(zone.exterior.coords)[:-1]]})
    for core in option["cores"]:
        if min(_roof_headroom(p,footprint,roof) for p in core["arrival_polygon"]) < 2100-1e-6:
            raise HouseCandidateError("The requested roof gives insufficient clear attic headroom over the stair arrival.")
    qualified_area=0
    for room in attic["rooms"]:
        if room["role"]=="stair":
            continue
        shape=clear_face_shape(Polygon(room["polygon"]),footprint,option["walls"])
        height=2100 if room["role"]=="attic_landing" else 2300
        zone=_roof_zone(footprint,roof,height)
        occupied=shape.intersection(zone)
        if occupied.is_empty or occupied.geom_type!="Polygon":
            raise HouseCandidateError("The roof leaves no connected occupied attic zone for the requested programme.")
        room["occupied_min_height_mm"]=height
        room["occupied_zone"]=[list(p) for p in list(occupied.exterior.coords)[:-1]]
        room["low_headroom_storage_polygons"]=[[list(p) for p in list(polygon.exterior.coords)[:-1]] for polygon in _polygons(shape.difference(occupied))]
        room["headroom_qualified_area_m2"]=round(occupied.area/1e6,4)
        qualified_area+=occupied.area
    attic["height_mm"]=roof["knee_wall_mm"]
    attic["headroom_qualified_area_m2"]=round(qualified_area/1e6,4)
    # A vertical attic window belongs on an exposed gable, never an imaginary
    # full-height knee wall. Centre its span in the qualified headroom zone.
    attic["windows"]=[]
    for room in attic["rooms"]:
        if room["role"]!="hobby":
            continue
        shape=Polygon(room["polygon"])
        candidates=_segments(shape.boundary.intersection(footprint.boundary))
        for a,b in candidates:
            if (a[0]==b[0]) != (axis=="x") or math.dist(a,b)<1400:
                continue
            middle=((a[0]+b[0])/2,(a[1]+b[1])/2)
            length=math.dist(a,b)
            delta=((b[0]-a[0])/length*500,(b[1]-a[1])/length*500)
            segment=[[round(middle[0]-delta[0]),round(middle[1]-delta[1])],[round(middle[0]+delta[0]),round(middle[1]+delta[1])]]
            if min(_roof_headroom(p,footprint,roof) for p in segment)<2100:
                continue
            attic["windows"].append({"id":"attic:window:hobby","room_id":room["id"],"segment":segment,"sill_mm":900,"height_mm":1200,"type":"gable_window"})
            break
    option["roof"]=roof


def _make_core(option,site,core_dimensions,mirror,request):
    w,d=core_dimensions
    half=request["walls"]["interior_mm"]/2
    def point(p):
        return _point_to_world([site["x"]+(site["width"]-p[0] if mirror else p[0]),site["y"]+p[1]],site["frame"])
    poly=[point(p) for p in polygon_points(box(0,0,w,d))]
    arrival_end=math.floor(d-half)
    arrival_right=math.floor(w-half)
    arrival=[point(p) for p in polygon_points(box(arrival_right-1000,arrival_end-1000,arrival_right,arrival_end))]
    exterior=request["walls"]["exterior_mm"]
    platform=[point(p) for p in polygon_points(box(exterior,arrival_end-1000,arrival_right,arrival_end))]
    opening=[point(p) for p in polygon_points(box(exterior,exterior,arrival_right,arrival_end-1000))]
    orientation=round(math.degrees(math.atan2(-site["frame"]["v"][0],site["frame"]["v"][1])))%360
    core={"id":"main_stair","kind":"stairs","form":"u_return","polygon":poly,"opening_polygon":opening,"arrival_polygon":arrival,"platform_polygon":platform,"top_platform_depth_mm":1000,
        "orientation":orientation,"arrival_orientation":orientation,"handedness":"left" if mirror else "right",
        "width_mm":w,"depth_mm":d,"flight_count":2,"flight_width_mm":900,"well_width_mm":200,"landing_depth_mm":1000,
        "riser_count":18,"riser_height_mm":3000/18,"going_mm":250,"floor_height_mm":3000,
        "floor_ids":[f["id"] for f in option["floors"]],"service_room_ids":{}}
    for floor in option["floors"]:
        floor.update({"stair_orientation":orientation,"stair_opening_polygon":deepcopy(opening),"stair_arrival_polygon":deepcopy(arrival),"stair_platform_polygon":deepcopy(platform)})
        key="ground:wc" if floor["role"]=="ground" else f"{floor['role']}:bath"
        if floor["role"]!="attic":
            core["service_room_ids"][floor["id"]]=key
    sanitary=[Polygon(next(r for r in f["rooms"] if r["id"]==core["service_room_ids"][f["id"]])["polygon"]) for f in option["floors"] if f["id"] in core["service_room_ids"]]
    shared=sanitary[0]
    for shape in sanitary[1:]:
        shared=shared.intersection(shape)
    if shared.is_empty or shared.geom_type!="Polygon":
        raise HouseCandidateError("The chosen upper-floor topology cannot share the required wet-service reservation.")
    sx0,sy0,sx1,sy1=shared.bounds
    if sx1-sx0<100 or sy1-sy0<100:
        raise HouseCandidateError("The sanitary stack has no common 100mm service shaft reservation.")
    core["service_zone"]=polygon_points(box(round((sx0+sx1)/2)-50,round((sy0+sy1)/2)-50,round((sx0+sx1)/2)+50,round((sy0+sy1)/2)+50))
    core["service_status"]="conceptual_reservation"
    option["cores"]=[core]


def solve_house_candidate(candidate,request,profile,mode,mirror,variant,first_bedrooms,cancelled,deadline):
    candidate=deepcopy(candidate)
    if mirror and candidate.get("side_reserve"):
        candidate["x"]+=candidate["side_reserve"]
    roles=["ground","first"]+(["second"] if mode=="g+2_attic" else [])+["attic"]
    if first_bedrooms+(1 if mode=="g+2_attic" else 0)<request["household"]["bedrooms"]:
        raise HouseCandidateError("This floor-count/programme combination does not provide the required bedroom count.")
    option={"id":"pending","title":"","description":"","floors":[],"walls":deepcopy(request["walls"])}
    core_dimensions=None
    for level,role in enumerate(roles):
        if cancelled() or time.monotonic()>=deadline:
            raise InterruptedError("House search stopped between sequential floor solves.")
        floor,core=solve_floor(role,level,candidate["width"],candidate["depth"],request["walls"],profile,variant=variant,bedrooms=first_bedrooms,separate_wc=request["household"]["bathroom_wc"]=="separate")
        if core_dimensions and core!=core_dimensions:
            raise HouseCandidateError("A floor failed to retain the coordinated stair dimensions.")
        core_dimensions=core
        _transform_floor(floor,candidate,mirror)
        option["floors"].append(floor)
    option["site"]=_build_site(candidate,option["floors"][0],request,mirror)
    _make_core(option,candidate,core_dimensions,mirror,request)
    _coordinate_roof(option,request,profile)
    footprint_area=candidate["width"]*candidate["depth"]/1e6
    bedrooms=sum(r["role"]=="bedroom" for f in option["floors"] for r in f["rooms"])
    garden_area=sum(Polygon(s["polygon"]).area for s in option["site"]["spaces"] if s["role"]=="garden")/1e6
    circulation=sum(r["clear_area_m2"] for f in option["floors"] if f["role"]!="attic" for r in f["rooms"] if r["role"] in {"entrance","landing"})
    regular=len(roles)-1
    option["metrics"]={"plot_area_m2":candidate["frame"]["width"]*candidate["frame"]["depth"]/1e6,"footprint_area_m2":footprint_area,
        "regular_floor_area_m2":footprint_area*regular,"garden_area_m2":garden_area,"bedrooms":bedrooms,"regular_storeys":regular,
        "attic_gross_area_m2":footprint_area,"attic_headroom_qualified_area_m2":option["floors"][-1]["headroom_qualified_area_m2"],
        "measurement_status":"concept_estimates_not_NEN_measurement"}
    # Preferences rank already-valid houses; they cannot compensate for gates.
    scores={"garden":round(min(garden_area,80)*.1,3),"compact_circulation":round(15-circulation/(footprint_area*regular)*25,3),
        "bedroom_brief":max(0,10-abs(bedrooms-request["household"]["bedrooms"])*2),"lower_storey_count":4 if regular==2 else 0,
        "kitchen_front":2 if variant=="kitchen_front" else 0}
    option["ranking"]={"score":round(sum(scores.values()),3),"components":scores}
    option["differences"]={"parking":candidate["parking_mode"],"stair_side":"right" if mirror else "left","ground_layout":variant,"first_floor_bedrooms":first_bedrooms,"regular_storeys":regular,"footprint_mm":[candidate["width"],candidate["depth"]]}
    option["title"]=f"{bedrooms} bedrooms · {'G+1' if regular==2 else 'G+2'} + attic · {('garden kitchen' if variant=='living_front' else 'garden living')}"
    parking_description={"front_access_side":"Front-access side parking","perpendicular":"Perpendicular front parking","parallel":"Parallel front parking; vehicle manoeuvring unassessed","none":"No parking requested"}[candidate["parking_mode"]]
    option["description"]=f"{parking_description}; {('right' if mirror else 'left')} stair and wet-service stack; {garden_area:.1f} m² rear garden."
    option["provenance"]={"engine":"GPLAN","engine_version":ENGINE_VERSION,"programme_profile":profile["id"],"programme_hash":profile_fingerprint(profile),"seed":request["search"]["seed"],
        "solver":SOLVER_NAME,"topology_source":"versioned NL concept contact templates","units":"mm","solver_units":"fractional_ft","solver_grid_mm":1,"grid_scope":"physical_partition_and_opening_geometry","derived_coordinate_precision":"fractional_mm_finished_faces_and_roof_zones","generation_source":"engine","hard_constraints_relaxed":False}
    return option


def geometry_fingerprint(option):
    # Canonical polygon orientation/start point avoids treating winding as a
    # layout change. IDs, titles, scores and display names are deliberately absent.
    def ring(points):
        p=[tuple(round(v) for v in a) for a in points]
        if p and p[0]==p[-1]:p.pop()
        return min(tuple(seq[i:]+seq[:i]) for seq in (p,list(reversed(p))) for i in range(len(seq)))
    data={"site":sorted((s["role"],ring(s["polygon"])) for s in option["site"]["spaces"]),
          "floors":[(f["role"],sorted((r["role"],ring(r["polygon"])) for r in f["rooms"]),sorted((d.get("external_role",""),d["kind"],tuple(sorted(tuple(p) for p in d["segment"]))) for d in f["doors"])) for f in option["floors"]],
          "roof":{k:option["roof"][k] for k in ("pitch_deg","knee_wall_mm","ridge_axis")}}
    return hashlib.sha256(json.dumps(data,sort_keys=True,separators=(",", ":")).encode()).hexdigest()


def generate_house_concepts(request_data,progress_callback=None):
    from .validation import validate_house_candidate
    request=normalize_request(request_data)
    profile=get_profile(request["programme_profile"])
    started=time.monotonic()
    deadline=started+request["search"]["budget_ms"]/1000
    def cancelled():
        callback=getattr(progress_callback,"is_cancelled",None)
        return bool(callback()) if callable(callback) else False
    catalogue={"schema_version":SCHEMA_VERSION,"units":"mm","programme_profile":profile["id"],"options":[],"notices":[],"rejections":[],
        "request_fingerprint":request_fingerprint(request),"provenance":{"engine":"GPLAN","engine_version":ENGINE_VERSION,"programme_hash":profile_fingerprint(profile)},"metrics":{}}
    for key in ("design_revision",):
        if key in request:catalogue[key]=request[key]
    candidates=enumerate_site_envelopes(request)
    if not candidates:
        catalogue["notices"].append("No supported footprint fits the plot, required setbacks, front parking and complete floor programme.")
    modes=request["storeys"]["allow"] if request["storeys"]["mode"]=="auto" else [request["storeys"]["mode"]]
    # At most one complete branch retained per attempt. A failed upper floor
    # backtracks to the next explicit programme/core/site combination.
    combinations=[(site,mirror,variant,bedrooms,mode)
                  for site,bedrooms,mode,variant,mirror in itertools.product(
                      candidates,[2,3],modes,["kitchen_front","living_front"],[False,True])]
    # Interleave left/right core AND parking positions, then ground living/
    # kitchen arrangements before adding bedrooms or full storeys. Stopping at
    # five therefore cannot fill a feasible site with only one core side.
    # Seed deterministically rotates the finite search order; no stochastic
    # legacy topology operation is used by this adapter.
    seed=request["search"]["seed"]
    if combinations and seed:
        offset=seed%len(combinations)
        combinations=combinations[offset:]+combinations[:offset]
    fingerprints=set()
    failures=Counter()
    attempted=0
    first_valid_ms=None
    stopped=None
    with SOLVER_LOCK:
        for candidate,mirror,variant,first_bedrooms,mode in combinations:
            if cancelled():stopped="cancelled";break
            if time.monotonic()>=deadline:stopped="time budget reached";break
            if attempted>=request["search"]["max_candidates"]:stopped="candidate budget reached";break
            if len(catalogue["options"])>=request["requested_options"]:break
            attempted+=1
            try:
                option=solve_house_candidate(candidate,request,profile,mode,mirror,variant,first_bedrooms,cancelled,deadline)
                report=validate_house_candidate(option,request,profile)
                if not report.get("valid"):
                    reasons=report.get("violations",[])
                    reason="; ".join(v.get("message",v.get("id","validation failed")) if isinstance(v,dict) else str(v) for v in reasons[:3]) or "A mandatory whole-house validation gate failed."
                    raise HouseCandidateError(reason)
                if cancelled():
                    stopped="cancelled"
                    break
                option["validation"]=report
                fingerprint=geometry_fingerprint(option)
                if fingerprint in fingerprints:
                    failures["Equivalent complete house geometry was deduplicated."]+=1
                    continue
                fingerprints.add(fingerprint)
                option["id"]="house-"+fingerprint[:16]
                option["geometry_fingerprint"]=fingerprint
                catalogue["options"].append(option)
                catalogue["options"].sort(key=lambda o:(-o["ranking"]["score"],o["id"]))
                if first_valid_ms is None:first_valid_ms=round((time.monotonic()-started)*1000,1)
                catalogue["metrics"]={"attempts":attempted,"valid_options":len(catalogue["options"]),"elapsed_ms":round((time.monotonic()-started)*1000,1),"first_valid_ms":first_valid_ms}
                if progress_callback:
                    try:
                        progress_callback(deepcopy(catalogue))
                    except Exception:
                        # An observer cannot invalidate or abort a solved house.
                        pass
            except InterruptedError:
                stopped="cancelled" if cancelled() else "time budget reached"
                break
            except (FloorSolveError,HouseCandidateError) as exc:
                failures[str(exc)]+=1
    catalogue["rejections"]=[{"reason":reason,"count":count} for reason,count in failures.most_common(12)]
    if len(catalogue["options"])<request["requested_options"]:
        reason=stopped or "the supported topology/site alternatives were exhausted"
        catalogue["notices"].append(f"Found {len(catalogue['options'])} of {request['requested_options']} requested valid distinct houses: {reason}. No failed programme or hard constraint was relaxed.")
        if failures:
            catalogue["notices"].append(f"Most frequent rejected constraint: {failures.most_common(1)[0][0]}")
    catalogue["notices"].append("NL_concept_v1 contains concept design assumptions. Regulation, structural design, fire, daylight calculations, NEN area measurement and vehicle manoeuvring remain unassessed.")
    catalogue["metrics"]={"attempts":attempted,"valid_options":len(catalogue["options"]),"elapsed_ms":round((time.monotonic()-started)*1000,1),"first_valid_ms":first_valid_ms,"search_complete":stopped is None,"stop_reason":stopped,"solver_execution":"sequential_in_process"}
    return catalogue
