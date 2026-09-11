"""Versioned design-basis ledger, deliberately not an operative-law certificate.

2026-09-11 research could not retrieve the operative wetten.overheid.nl text.
The profile pins its assumptions and applicability; that evidence limitation
always appears in the assessment. Future amendments in a working PDF are never
silently promoted to effective law.
"""

from .models import RULE_PROFILE, assessment

SOURCE_LEDGER = {
    "profile": RULE_PROFILE, "research_date": "2026-09-11", "effective_date_verified": False,
    "regime": "new_build", "primary_function": "kantoorfunctie",
    "status": "design_basis_only", "standards_templates_certified": False,
    "sources": [
        {"id": "bbl-original", "url": "https://zoek.officielebekendmakingen.nl/stb-2018-291.pdf",
         "publication": "Staatsblad 2018, 291", "scope": "Original statutory publication; amendments not incorporated"},
        {"id": "bbl-working", "url": "https://iplo.nl/publish/pages/245245/besluit-bouwwerken-leefomgeving-werkversie_1.pdf",
         "publication": "IPLO working consolidation, research snapshot 2026-09-10",
         "scope": "Research reference includes future amendments; not evidence of effective 2026 law"},
        {"id": "free-passage", "url": "https://iplo.nl/regelgeving/regels-voor-activiteiten/technische-bouwactiviteit/nieuwbouw/rijksregels/vrije-doorgang/",
         "retrieved": "2026-09-11", "scope": "Official guidance: free passage and lift exclusion from escape routes"},
        {"id": "ventilation", "url": "https://iplo.nl/regelgeving/regels-voor-activiteiten/technische-bouwactiviteit/nieuwbouw/rijksregels/ventilatie/",
         "retrieved": "2026-09-11", "scope": "Official guidance; installed system performance remains unassessed"},
    ],
}


def office_distance_limit(people, subcompartment_go_m2, allow_low_density=False):
    """Pure threshold helper for independently tested design-basis boundaries."""
    return 45.0 if allow_low_density and subcompartment_go_m2 > 0 and people * 12 < subcompartment_go_m2 else 30.0


def exit_requirement(people):
    return {"minimum_exits": 2 if people > 150 else 1,
            "minimum_separation_m": 5.0 if people > 150 else 0.0,
            "outward_swing_required": people > 37, "panic_hardware_required": people > 100}


def single_route_protection(people, stair_height_m):
    if people > 150:
        return "safety_route"
    if people > 37 or stair_height_m > 8:
        return "extra_protected"
    return "protected"


def accessibility_sector_trigger(office_go_by_floor):
    """Aggregate the relevant office GO; never use an isolated floor threshold."""
    return sum(office_go_by_floor) > 400


def rule_assessments(brief, plan):
    floors = plan["floors"]
    gross = sum(f["area_ledger"]["gross_m2"] for f in floors)
    occupied = [r for f in floors for r in f["rooms"] if r["role"] not in {"wc", "accessible_wc", "storage", "it", "cleaning"}]
    office_vg = sum(r["clear_area_m2"] for r in occupied if r.get("use_function") == "kantoorfunctie")
    peak = brief["people"]["staff"] + brief["people"]["visitors"]
    height = (len(floors) - 1) * brief["building"]["floor_height_m"]
    checks = [
        assessment("nl-effective-source", "needs_input", "rules", "Confirm the operative Dutch rule version",
                   "The profile is pinned to the 11 September 2026 research design basis. An effective-date-verified consolidation and applicable NEN editions are still required.", rule=RULE_PROFILE),
        assessment("nl-compartmentation", "not_assessed", "escape", "Fire and smoke compartment design needs review",
                   f"The {gross:.1f} m² building has reserved partitions and stair enclosures. Fire resistance, smoke separation, compartment boundaries and route independence are not verified.",
                   rule="Bbl 4.49–4.81, design basis", measured=gross, required=1000),
        assessment("nl-corrected-distance", "not_assessed", "escape", "Prescribed corrected escape distance needs compartment design",
                   "Operational path samples do not establish the prescribed distance to a qualifying subbrandcompartment exit. Freely divisible areas and the 1.5 correction need their own confirmed geometry.",
                   rule="Bbl 4.66, design basis", required=30),
        assessment("nl-route-protection", "not_assessed", "escape", "Specify the required route protection",
                   f"The conservative single-route design basis requires {single_route_protection(peak, height).replace('_', ' ')} construction for the assigned occupancy/height. Ratings, self-closing doors and independent routes require fire design.",
                   rule="Bbl 4.68–4.71, design basis"),
        assessment("nl-accessible-sector", "not_assessed", "accessibility", "Confirm the aggregated accessibility-sector calculation",
                   f"Office room clear area is {office_vg:.1f} m²; measured GO and classified VG must be established for the aggregate 400 m² trigger and 40% sector provision. The selected step-free policy is assessed separately.",
                   rule="Bbl 4.183–4.190, design basis", measured=gross, required=400),
        assessment("nl-daylight", "not_assessed", "environment", "Calculate equivalent daylight",
                   "Facade adjacency is a planning preference. Openings, boundary distances, shading and a NEN 2057 calculation are not part of this geometric fit."),
        assessment("nl-ventilation", "not_assessed", "environment", "Design the room ventilation system",
                   f"Office design demand starts at 6.5 dm³/s per assigned person ({6.5 * peak:.1f} dm³/s for the population before use-specific checks). This is a demand estimate, not a verified plant, duct or room-airflow design.",
                   rule="Bbl 4.122 and applicable use-function table, design basis"),
        assessment("nl-sanitary-policy", "needs_input", "services", "Confirm the sanitary operating policy",
                   f"Provision uses the {brief['amenities']['wc_policy']} policy with {brief['amenities']['policy_people_per_wc']} people per ordinary WC when automatic; accessible fixtures are additional. This is not a statutory Bbl office ratio; sufficient nearby facilities and separate facilities or use need confirmation.",
                   rule="Arbobesluit 3.24; project provisioning policy"),
        assessment("nl-site-planning", "needs_input", "planning", "Confirm site planning permission and restrictions",
                   "Address-specific permitted use, buildable envelope, height, parking and access need project evidence; confirming dimensions alone does not establish municipal permission."),
        assessment("nl-detection-hardware", "not_assessed", "escape", "Specify door hardware, detection and evacuation arrangements",
                   "Single-direction routes and room counts may trigger detection. Door operation, access control, signage, emergency lighting and alarm-system design remain unassessed."),
    ]
    if any(r.get("use_function") == "bijeenkomstfunctie" for r in occupied):
        checks.append(assessment("nl-supporting-assembly", "not_assessed", "rules", "Review the supporting meeting and lunch use functions",
                                 "Meeting and staff lunch rooms retain bijeenkomstfunctie classification and local seat maxima. Assembly ventilation, occupancy, fire and accessibility applicability is not inferred from the office row."))
    if len(floors) > 1:
        checks += [assessment("nl-stair-construction", "not_assessed", "escape", "Review stair construction and headroom",
                              "Flights, risers, landings, openings and aligned portals are reserved geometrically. Structural design, guards, finished headroom, fire rating and stair-standard review remain outstanding."),
                   assessment("nl-assisted-evacuation", "needs_input", "accessibility", "Confirm assisted evacuation from upper floors",
                              "An ordinary passenger lift provides access and is excluded from the escape graph. A strategy for people unable to use stairs remains required.")]
    if brief["amenities"]["pantry"] == "cooking":
        checks.append(assessment("nl-cooking-extract", "not_assessed", "services", "Design cooking extract and fire separation",
                                 "Cooking equipment and operating space are reserved; extraction, grease/fire provisions and the applicable supporting-use rules need specialist design."))
    if brief["amenities"]["lunch_seats"] == 0:
        checks.append(assessment("workplace-break-space", "needs_input", "services", "Confirm suitable eating and rest provision",
                                 "No lunch seats were requested. A separate suitable eating/rest arrangement must be confirmed; toilets do not substitute for rest space."))
    return checks
