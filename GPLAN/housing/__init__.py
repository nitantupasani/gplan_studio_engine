"""Versioned whole-house concepts built with GPLAN's dimensional solver."""

SCHEMA_VERSION = "house_concepts_v1"
ENGINE_VERSION = "gplan_house_orchestrator_v1"


def generate_house_concepts(request_data, progress_callback=None):
    from .concepts import generate_house_concepts as generate
    return generate(request_data, progress_callback=progress_callback)
