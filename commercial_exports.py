"""Semantic metre-based office design-study exports from revalidated options.

These formats preserve IDs and assessed scope. Reserved construction and core
envelopes remain explicitly labelled design geometry, never construction BIM.
"""
import io
import json
import textwrap


def _json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False)


def _manifest(brief, option, receipt, validation):
    fit_kind = validation.get("fit_kind", option.get("fit_kind", "requested_programme"))
    modified = fit_kind == "modified_programme"
    fitted_brief = validation.get("fitted_brief", option.get("fitted_brief", brief))
    deviations = validation.get("constraint_deviations", option.get("constraint_deviations", []))
    if modified and (not isinstance(fitted_brief, dict) or not deviations):
        raise ValueError("A modified-programme study must retain its fitted brief and unmet original constraints.")
    if modified:
        # Keep nested option metadata consistent with the independently
        # recomputed validation receipt, without changing the caller's option.
        option = {**option, "fit_kind": fit_kind, "satisfies_original_brief": False,
                  "fitted_brief": fitted_brief, "constraint_deviations": deviations}
    supplementary_spaces = [{"floor_index": floor["index"], **{key: room.get(key) for key in
                            ("id", "name", "role", "support_kind", "provenance", "use_function", "fitout_status", "capacity", "clear_area_m2")}}
                            for floor in option["floors"] for room in floor["rooms"] if room.get("supplementary") is True]
    return {"schema_version": "commercial-study-export-1.0", "units": "m", "area_units": "m2",
            "purpose": "Office design study; specialist assessment and local planning review remain required."
                       + (" Modified programme: the original constraints are not met." if modified else ""),
            "receipt": receipt, "brief": brief, "option": option, "validation": validation,
            "fit_kind": fit_kind, "satisfies_original_brief": not modified,
            "fitted_brief": fitted_brief, "constraint_deviations": deviations,
            "supplementary_spaces": supplementary_spaces,
            "supplementary_capacity": validation.get("supplementary_capacity", option.get("supplementary_capacity", {})),
            "supplementary_scope": "Optional support-space furniture is separate from the original programme and adds no declared occupants. Route-review fit-outs require route redesign before use."}


def _deviation_line(deviation):
    if not isinstance(deviation, dict):
        return str(deviation)
    label = deviation.get("label", deviation.get("path", deviation.get("id", "Requirement")))
    unit = str(deviation.get("unit", ""))
    return "%s: requested %s; fitted %s %s. %s" % (
        label, deviation.get("requested", "unknown"), deviation.get("provided", "unknown"),
        unit, deviation.get("detail", ""))


def _entity_label(entity):
    label = str(entity.get("name", entity.get("kind", entity["id"]))).replace("\n", " ")
    if entity.get("supplementary") is True and entity.get("fitout_status") == "route_review":
        label = "[ROUTE REVIEW] " + label
    return label


def _ring(obj):
    if obj.get("clear_polygon"):
        return obj["clear_polygon"]
    if obj.get("polygon"):
        return obj["polygon"]
    r = obj["rect"]
    x, y, w, h = (r[key] for key in ("x", "y", "width", "height"))
    return [[x, y], [x + w, y], [x + w, y + h], [x, y + h]]


def _entities(floor):
    for group in ("rooms", "corridors", "cores", "walls"):
        for entity in floor.get(group, []):
            yield group, entity
            if group == "rooms":
                for furniture in entity.get("furniture", []):
                    yield "furniture", furniture


def export_commercial(brief, option, receipt, format):
    from GPLAN.commercial import validate_commercial_option
    if format not in {"json", "dxf", "pdf", "ifc"}:
        raise ValueError("Supported commercial export formats are json, dxf, pdf and ifc.")
    # The option must still correspond to its durable brief; the engine also
    # checks required capacity, geometry, routes and source fingerprint.
    validation = validate_commercial_option(option, brief)
    if validation.get("valid") is not True:
        raise ValueError("This option no longer passes its assessed geometry and programme checks. Generate current options before exporting.")
    manifest = _manifest(brief, option, receipt, validation)
    if format == "json":
        return _json(manifest).encode("utf-8"), "application/json"
    if format == "dxf":
        return _dxf(manifest), "application/dxf"
    if format == "pdf":
        return _pdf(manifest), "application/pdf"
    return _ifc(manifest), "application/x-step"


def _dxf(manifest):
    lines = []
    def emit(*items):
        lines.extend(str(item) for item in items)
    def metadata(value):
        encoded = json.dumps(value, ensure_ascii=True, allow_nan=False)
        emit(1001, "GPLAN_COMMERCIAL")
        for i in range(0, len(encoded), 240):
            emit(1000, encoded[i:i + 240])
    emit(0, "SECTION", 2, "HEADER", 9, "$ACADVER", 1, "AC1021", 9, "$INSUNITS", 70, 6,
         9, "$MEASUREMENT", 70, 1, 0, "ENDSEC", 0, "SECTION", 2, "TABLES",
         0, "TABLE", 2, "APPID", 70, 1, 0, "APPID", 2, "GPLAN_COMMERCIAL", 70, 0,
         0, "ENDTAB", 0, "ENDSEC", 0, "SECTION", 2, "ENTITIES")
    # Shared world x/y with real floor elevation preserves vertical identity.
    # Per-floor layers let a CAD viewer isolate one drawing without fake offsets.
    for floor in manifest["option"]["floors"]:
        index, elevation = floor["index"], floor["elevation_m"]
        for group, entity in _entities(floor):
            points = _ring(entity)
            layer = f"F{index}_{group.upper()}"
            emit(0, "LWPOLYLINE", 100, "AcDbEntity", 8, layer, 100, "AcDbPolyline", 90, len(points), 70, 1, 38, elevation)
            for x, y in points:
                emit(10, x, 20, -y)
            metadata({key: value for key, value in entity.items() if key not in {"furniture", "polygon", "clear_polygon", "rect"}})
            if group in {"rooms", "cores"}:
                r = entity["rect"]
                label = _entity_label(entity)
                emit(0, "TEXT", 100, "AcDbEntity", 8, f"F{index}_LABELS", 100, "AcDbText",
                     10, r["x"] + .15, 20, -r["y"] - .35, 30, elevation, 40, .2, 1, label)
        for door in floor.get("doors", []) + floor.get("exits", []):
            a, b = door["segment"]
            emit(0, "LINE", 100, "AcDbEntity", 8, f"F{index}_DOORS", 100, "AcDbLine",
                 10, a[0], 20, -a[1], 30, elevation, 11, b[0], 21, -b[1], 31, elevation)
            metadata(door)
    if not manifest["satisfies_original_brief"]:
        notes = ["MODIFIED PROGRAMME - ORIGINAL CONSTRAINTS NOT MET"]
        for deviation in manifest["constraint_deviations"]:
            notes.extend(textwrap.wrap(_deviation_line(deviation).replace("\n", " "), 100))
        for index, note in enumerate(notes):
            emit(0, "TEXT", 100, "AcDbEntity", 8, "PROGRAMME_DEVIATIONS", 100, "AcDbText",
                 10, 0, 20, 2 + .35 * (len(notes) - index), 30, 0, 40, .2, 1, note)
    if manifest["supplementary_spaces"]:
        notes = [manifest["supplementary_scope"]] + [
            "Floor %s - %s: %s; %s optional places" % (room["floor_index"], room["name"],
                "ROUTE REDESIGN REQUIRED" if room["fitout_status"] == "route_review" else "supplementary fit-out", room["capacity"])
            for room in manifest["supplementary_spaces"]]
        for index, note in enumerate(notes):
            emit(0, "TEXT", 100, "AcDbEntity", 8, "SUPPLEMENTARY_FITOUT", 100, "AcDbText",
                 10, -45, 20, -.4 * index, 30, 0, 40, .2, 1, note)
    # XRECORD avoids the 16 KB per-entity XDATA ceiling for the full immutable
    # brief/assessment/geometry manifest. Individual room XDATA stays compact.
    emit(0, "ENDSEC", 0, "SECTION", 2, "OBJECTS", 0, "DICTIONARY", 5, "C0", 330, "0",
         100, "AcDbDictionary", 281, 1, 3, "GPLAN_COMMERCIAL", 350, "C1",
         0, "XRECORD", 5, "C1", 330, "C0", 100, "AcDbXrecord", 280, 1)
    encoded = json.dumps(manifest, ensure_ascii=True, allow_nan=False)
    for i in range(0, len(encoded), 240):
        emit(1, encoded[i:i + 240])
    emit(0, "ENDSEC", 0, "EOF")
    return ("\n".join(lines) + "\n").encode("utf-8")


def _pdf(manifest):
    from reportlab.pdfgen.canvas import Canvas
    from reportlab.lib.pagesizes import A3, landscape
    from reportlab.lib.colors import HexColor
    output = io.BytesIO()
    page_w, page_h = landscape(A3)
    canvas = Canvas(output, pagesize=(page_w, page_h), pageCompression=1)
    canvas.setTitle("GPLAN office design study")
    canvas.setAuthor("GPLAN")
    option, brief = manifest["option"], manifest["brief"]
    modified = not manifest["satisfies_original_brief"]
    def header(title):
        canvas.setFillColor(HexColor("#252b29"))
        canvas.setFont("Helvetica-Bold", 18)
        canvas.drawString(35, page_h - 42, title)
        canvas.setFont("Helvetica", 9)
        canvas.drawString(35, page_h - 60, "Design study - dimensions in metres - required specialist and local planning reviews remain outstanding")
        if modified:
            canvas.setFont("Helvetica-Bold", 9)
            canvas.drawString(35, page_h - 76, "MODIFIED PROGRAMME - ORIGINAL CONSTRAINTS NOT MET; geometry is checked against the fitted programme")
        canvas.drawString(35, 23, "GPLAN | " + str(option["id"]) + " | brief revision " + str(manifest["receipt"]["revision"]))
    header("Office programme and assessment scope")
    y = page_h - 95
    def rows(text, bold=False):
        nonlocal y
        for line in textwrap.wrap(str(text), 148, break_long_words=True) or [""]:
            if y < 55:
                canvas.showPage()
                header("Office study - assessment scope continued")
                y = page_h - 95
            canvas.setFont("Helvetica-Bold" if bold else "Helvetica", 10)
            canvas.drawString(35, y, line)
            y -= 15
        y -= 5
    rows("Original requested programme" if modified else "Programme", True)
    rows("Declared staff: %s | External visitors: %s | Required desks: %s | Floors in option: %s" % (
        brief["people"]["staff"], brief["people"].get("visitors", 0), brief["people"].get("desks", brief["people"]["staff"]), len(option["floors"])))
    if modified:
        fitted = manifest["fitted_brief"]
        rows("Fitted study programme", True)
        rows("Fitted simultaneous staff: %s | External visitors: %s | Desks: %s" % (
            fitted["people"]["staff"], fitted["people"].get("visitors", 0),
            fitted["people"].get("desks", fitted["people"]["staff"])))
        rows("Original constraints not met", True)
        for deviation in manifest["constraint_deviations"]:
            rows(_deviation_line(deviation))
    rows(("Fitted delivered capacity: " if modified else "Delivered capacity: ") + _json(option.get("capacity", {})))
    if manifest["supplementary_spaces"]:
        rows("Supplementary fit-out - separate from the original programme", True)
        rows(manifest["supplementary_scope"])
        rows("Supplementary furniture by assessed scope: " + _json(manifest["supplementary_capacity"]))
        for room in manifest["supplementary_spaces"]:
            rows("Floor %s - %s (%s), %.2f m2, %s optional places: %s" % (
                room["floor_index"], room["name"], room["support_kind"], room["clear_area_m2"], room["capacity"],
                "ROUTE REDESIGN REQUIRED before use" if room["fitout_status"] == "route_review" else "geometry and operational route checked; statutory review remains required"))
    rows("Area ledger (m2): " + _json(option.get("area_ledger", {})))
    rows("Rule profile: " + str(brief.get("rules_profile", "nl-office-newbuild-2026-09-11-design-basis")))
    rows("Returned assessments", True)
    for check in manifest["validation"].get("assessments", []):
        rows("%s - %s: %s" % (check.get("status", check.get("state", "not_assessed")), check.get("title", check.get("id", "Assessment")), check.get("message", check.get("detail", ""))))
        if check.get("source") or check.get("method"):
            rows("Method/source: " + _json({k: check[k] for k in ("method", "source", "rule", "clause") if k in check}))
    for assumption in option.get("assumptions", []):
        rows("Assumption: " + (assumption if isinstance(assumption, str) else _json(assumption)))
    palette = {"rooms": "#e7efe9", "corridors": "#f2dec0", "cores": "#d5dde6", "walls": "#8d9290", "furniture": "#c6d8d0"}
    for floor in option["floors"]:
        canvas.showPage()
        header("Ground floor" if floor["index"] == 0 else "Floor " + str(floor["index"]))
        envelope = floor["envelope"]
        xs, ys = [p[0] for p in envelope], [p[1] for p in envelope]
        w, h = max(xs) - min(xs), max(ys) - min(ys)
        scale = min((page_w - 340) / w, (page_h - 135) / h)
        x0, y0 = 40 - min(xs) * scale, page_h - 95 + min(ys) * scale
        def line_polygon(points, fill=None):
            path = canvas.beginPath()
            path.moveTo(x0 + points[0][0] * scale, y0 - points[0][1] * scale)
            for x, y in points[1:]:
                path.lineTo(x0 + x * scale, y0 - y * scale)
            path.close()
            canvas.setStrokeColor(HexColor("#65706b"))
            if fill:
                canvas.setFillColor(HexColor(fill))
            canvas.drawPath(path, stroke=1, fill=bool(fill))
        canvas.setLineWidth(.4)
        line_polygon(envelope)
        for group, entity in _entities(floor):
            line_polygon(_ring(entity), palette[group])
            if group == "rooms":
                r = entity["rect"]
                canvas.setFillColor(HexColor("#253c31"))
                canvas.setFont("Helvetica", max(5, min(9, scale * .23)))
                label = _entity_label(entity)
                for n, part in enumerate(textwrap.wrap(label, max(10, int(r["width"] * 7)))[:2]):
                    canvas.drawString(x0 + (r["x"] + .1) * scale, y0 - (r["y"] + .35 + n * .3) * scale, part)
        canvas.setStrokeColor(HexColor("#347b53"))
        canvas.setLineWidth(2)
        for door in floor.get("doors", []) + floor.get("exits", []):
            a, b = door["segment"]
            canvas.line(x0 + a[0] * scale, y0 - a[1] * scale, x0 + b[0] * scale, y0 - b[1] * scale)
        legend_x = page_w - 265
        canvas.setFillColor(HexColor("#252b29"))
        canvas.setFont("Helvetica-Bold", 11)
        canvas.drawString(legend_x, page_h - 100, "Floor scope")
        canvas.setFont("Helvetica", 9)
        canvas.drawString(legend_x, page_h - 119, "Elevation: %.2f m" % floor["elevation_m"])
        canvas.drawString(legend_x, page_h - 136, "Envelope: %.2f x %.2f m" % (w, h))
        legend_y = page_h - 165
        for group, colour in palette.items():
            canvas.setFillColor(HexColor(colour))
            canvas.rect(legend_x, legend_y - 3, 12, 12, fill=1, stroke=0)
            canvas.setFillColor(HexColor("#252b29"))
            canvas.drawString(legend_x + 20, legend_y, group.capitalize())
            legend_y -= 20
        for label, value in floor.get("area_ledger", {}).items():
            canvas.drawString(legend_x, legend_y, "%s: %.2f m2" % (label.replace("_m2", "").replace("_", " "), value))
            legend_y -= 17
        canvas.setFont("Helvetica", 8)
        for part in textwrap.wrap("Reserved wall/core envelopes and doors need construction, fire protection and hardware design. The drawing carries no compliance certificate.", 43):
            legend_y -= 12
            canvas.drawString(legend_x, legend_y, part)
    canvas.save()
    return output.getvalue()


def _ifc(manifest):
    from ifcopenshell.api import run
    f = run("project.create_file", version="IFC4")
    project = run("root.create_entity", f, ifc_class="IfcProject", name="GPLAN office design study")
    units = [run("unit.add_si_unit", f, unit_type=kind) for kind in ("LENGTHUNIT", "AREAUNIT", "VOLUMEUNIT")]
    run("unit.assign_unit", f, units=units)
    model = run("context.add_context", f, context_type="Model")
    body = run("context.add_context", f, context_type="Model", context_identifier="Body", target_view="MODEL_VIEW", parent=model)
    site = run("root.create_entity", f, ifc_class="IfcSite", name="Site")
    building = run("root.create_entity", f, ifc_class="IfcBuilding", name="Office")
    def aggregate(child, parent):
        run("aggregate.assign_object", f, products=[child], relating_object=parent)
    aggregate(site, project)
    aggregate(building, site)
    property_sets = {}
    def properties(entity, values):
        if entity.id() not in property_sets:
            property_sets[entity.id()] = run("pset.add_pset", f, product=entity, name="Pset_GPLANCommercialStudy")
        pset = property_sets[entity.id()]
        run("pset.edit_pset", f, pset=pset, properties={key: value if isinstance(value, (int, float, bool)) else f.createIfcText(value if isinstance(value, str) else _json(value)) for key, value in values.items()})
    properties(project, {"Purpose": manifest["purpose"], "Units": "metres", "RevisionReceipt": manifest["receipt"],
                         "Brief": manifest["brief"], "Validation": manifest["validation"],
                         "FitKind": manifest["fit_kind"], "SatisfiesOriginalBrief": manifest["satisfies_original_brief"],
                         "FittedBrief": manifest["fitted_brief"], "ConstraintDeviations": manifest["constraint_deviations"],
                         "SupplementarySpaces": manifest["supplementary_spaces"], "SupplementaryCapacity": manifest["supplementary_capacity"],
                         "SupplementaryScope": manifest["supplementary_scope"],
                         "OptionMetadata": {k: v for k, v in manifest["option"].items() if k != "floors"}})
    height = manifest["brief"].get("building", {}).get("floor_height_m", 3.3)
    for floor in manifest["option"]["floors"]:
        storey = run("root.create_entity", f, ifc_class="IfcBuildingStorey", name="Ground" if floor["index"] == 0 else "Floor " + str(floor["index"]))
        storey.Elevation = float(floor["elevation_m"])
        aggregate(storey, building)
        properties(storey, {"FloorIndex": floor["index"], "AreaLedger": floor.get("area_ledger", {})})
        for group, entity in _entities(floor):
            # Spatial core reserves stay spatial objects: an unverified shaft
            # envelope must not masquerade as an installed lift or rated stair.
            ifc_class = "IfcSpace" if group in {"rooms", "corridors", "cores"} else "IfcFurnishingElement" if group == "furniture" else "IfcBuildingElementProxy"
            product = run("root.create_entity", f, ifc_class=ifc_class, name=_entity_label(entity))
            if ifc_class == "IfcSpace":
                aggregate(product, storey)
            else:
                run("spatial.assign_container", f, products=[product], relating_structure=storey)
            props = {key: value for key, value in entity.items() if key not in {"rect", "polygon", "clear_polygon", "furniture"}}
            properties(product, {"StableId": entity["id"], "Group": group, "SemanticData": props,
                                 "ConstructionStatus": "unverified_reserved_geometry" if group in {"cores", "walls"} else "design_study"})
            points = _ring(entity)
            ring = points + [points[0]]
            polyline = f.createIfcPolyline([f.createIfcCartesianPoint((float(x), float(-y))) for x, y in ring])
            profile = f.createIfcArbitraryClosedProfileDef("AREA", None, polyline)
            z = float(floor["elevation_m"])
            placement = f.createIfcAxis2Placement3D(f.createIfcCartesianPoint((0., 0., z)), None, None)
            solid = f.createIfcExtrudedAreaSolid(profile, placement, f.createIfcDirection((0., 0., 1.)), float(.75 if group == "furniture" else height - .25))
            representation = f.createIfcShapeRepresentation(body, "Body", "SweptSolid", [solid])
            product.Representation = f.createIfcProductDefinitionShape(None, None, [representation])
            run("geometry.edit_object_placement", f, product=product)
        properties(storey, {"DoorsAndExits": floor.get("doors", []) + floor.get("exits", []),
                           "FloorGeometry": floor})
    return f.to_string().encode("utf-8")
