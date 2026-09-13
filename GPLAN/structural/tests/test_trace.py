"""Pins for the one clause-trace sink: registry, capture, isolation, zero-sink silence."""

from __future__ import annotations

from typing import NamedTuple

import pytest

# Relative: see the note in test_model_roundtrip.py.
from ..codes.trace import (
    CLAUSE_REGISTRY,
    ClauseMeta,
    TraceEntry,
    clause,
    current_sink,
    registry_entries,
    trace_into,
)


class Doubly(NamedTuple):
    ast1_mm2: float
    ast2_mm2: float
    asc_mm2: float


@clause(
    code="IS456:2000",
    ref="G-1.1(b)",
    title="Limiting moment of resistance",
    symbol="Mu_lim",
    units="kNm",
    latex=r"M_{u,lim}=0.36\frac{x_u}{d}(1-0.42\frac{x_u}{d})bd^2f_{ck}",
)
def demo_mu_lim(b_mm, d_mm, fck_mpa, fy_mpa=415.0):
    k = {415.0: 0.138, 500.0: 0.133}.get(fy_mpa, 0.138)
    return k * fck_mpa * b_mm * d_mm * d_mm / 1e6


@clause(code="IS456:2000", ref="G-1.2", title="Doubly reinforced section", symbol="Ast", units="mm2")
def demo_doubly(mu_knm, b_mm, d_mm):
    return Doubly(ast1_mm2=mu_knm * 2.0, ast2_mm2=b_mm * 0.01, asc_mm2=d_mm * 0.02)


def test_registry_is_populated_by_the_decorator():
    assert "IS456:2000 G-1.1(b)" in CLAUSE_REGISTRY
    meta = CLAUSE_REGISTRY["IS456:2000 G-1.1(b)"]
    assert isinstance(meta, ClauseMeta)
    assert meta.title == "Limiting moment of resistance"
    assert meta.symbol == "Mu_lim"
    assert meta.units == "kNm"
    assert meta.latex is not None
    assert meta.func == "demo_mu_lim"
    assert demo_mu_lim.clause_meta is meta
    assert meta.clause_id == "IS456:2000 G-1.1(b)"
    ids = [entry.clause_id for entry in registry_entries()]
    assert ids == sorted(ids)


def test_decorated_callable_is_transparent_without_a_sink():
    assert current_sink() is None
    value = demo_mu_lim(230.0, 400.0, 25.0)
    assert value == pytest.approx(0.138 * 25.0 * 230.0 * 400.0 * 400.0 / 1e6)
    assert current_sink() is None
    assert demo_mu_lim.__name__ == "demo_mu_lim"


def test_sink_records_bound_inputs_with_defaults_applied():
    entries = []
    with trace_into(entries) as sink:
        assert sink is entries
        assert current_sink() is entries
        value = demo_mu_lim(230.0, d_mm=400.0, fck_mpa=25.0)
    assert current_sink() is None
    assert len(entries) == 1
    entry = entries[0]
    assert isinstance(entry, TraceEntry)
    assert entry.code == "IS456:2000"
    assert entry.ref == "G-1.1(b)"
    assert entry.units == "kNm"
    assert entry.inputs == {"b_mm": 230.0, "d_mm": 400.0, "fck_mpa": 25.0, "fy_mpa": 415.0}
    assert entry.output == pytest.approx(value)
    assert entry.to_dict()["symbol"] == "Mu_lim"


def test_namedtuple_output_is_stored_as_a_mapping():
    entries = []
    with trace_into(entries):
        out = demo_doubly(120.0, 230.0, 400.0)
    assert isinstance(out, Doubly)
    assert entries[0].output == {
        "ast1_mm2": pytest.approx(240.0),
        "ast2_mm2": pytest.approx(2.3),
        "asc_mm2": pytest.approx(8.0),
    }


def test_entries_accumulate_in_call_order():
    entries = []
    with trace_into(entries):
        demo_mu_lim(230.0, 400.0, 25.0)
        demo_doubly(120.0, 230.0, 400.0)
        demo_mu_lim(230.0, 450.0, 30.0, fy_mpa=500.0)
    assert [e.ref for e in entries] == ["G-1.1(b)", "G-1.2", "G-1.1(b)"]
    assert entries[2].inputs["fy_mpa"] == 500.0


def test_nested_sinks_are_isolated():
    outer = []
    inner = []
    with trace_into(outer):
        demo_mu_lim(230.0, 400.0, 25.0)
        with trace_into(inner):
            demo_doubly(120.0, 230.0, 400.0)
            assert current_sink() is inner
        assert current_sink() is outer
        demo_mu_lim(230.0, 450.0, 30.0)
    assert [e.ref for e in outer] == ["G-1.1(b)", "G-1.1(b)"]
    assert [e.ref for e in inner] == ["G-1.2"]
    assert current_sink() is None


def test_sink_is_released_even_when_the_clause_raises():
    @clause(code="IS456:2000", ref="X-1", title="Raiser", symbol="x", units="")
    def boom(value):
        raise ValueError("no")

    entries = []
    with pytest.raises(ValueError):
        with trace_into(entries):
            boom(1.0)
    assert entries == []
    assert current_sink() is None
