"""One clause = one callable = one traceable record.

`@clause(...)` registers a code-clause callable in CLAUSE_REGISTRY and, whenever a
sink is open, appends a TraceEntry per call. With no sink the wrapper costs one
ContextVar read; argument binding and value flattening happen only when tracing.

    entries = []
    with trace_into(entries):
        tau_c = table_19__tau_c(pt=0.75, fck=25)
    entries[0].inputs   # {"pt": 0.75, "fck": 25}

Decorated callables return plain floats or NamedTuples; a NamedTuple return is
stored as its _asdict(). Rendering (LaTeX substitution) happens in report.py,
never in the hot path.
"""

from __future__ import annotations

import contextvars
import functools
import inspect
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterator, List, Optional


@dataclass
class TraceEntry:
    """One evaluated clause, in emission order."""

    code: str
    ref: str
    title: str
    symbol: str
    inputs: Dict[str, Any]
    output: Any
    units: str
    latex: Optional[str] = None

    @property
    def clause_id(self) -> str:
        return self.code + " " + self.ref

    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "ref": self.ref,
            "title": self.title,
            "symbol": self.symbol,
            "inputs": dict(self.inputs),
            "output": self.output,
            "units": self.units,
            "latex": self.latex,
        }


@dataclass(frozen=True)
class ClauseMeta:
    """Bibliography record for one decorated clause."""

    code: str
    ref: str
    title: str
    symbol: str
    units: str
    latex: Optional[str]
    func: str

    @property
    def clause_id(self) -> str:
        return self.code + " " + self.ref

    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "ref": self.ref,
            "title": self.title,
            "symbol": self.symbol,
            "units": self.units,
            "latex": self.latex,
            "func": self.func,
        }


CLAUSE_REGISTRY = {}  # type: Dict[str, ClauseMeta]

_SINK = contextvars.ContextVar("structural_trace_sink", default=None)  # type: contextvars.ContextVar


def current_sink() -> Optional[List[TraceEntry]]:
    """The list entries are appended to, or None when tracing is off."""
    return _SINK.get()


@contextmanager
def trace_into(entries: List[TraceEntry]) -> Iterator[List[TraceEntry]]:
    """Collect TraceEntry records into `entries` for the duration of the block.

    Nested blocks are isolated: entries recorded inside an inner sink do not
    reach the outer one, and the outer sink resumes on exit.
    """
    token = _SINK.set(entries)
    try:
        yield entries
    finally:
        _SINK.reset(token)


def clause(code: str, ref: str, title: str, symbol: str = "", units: str = "", latex: Optional[str] = None) -> Callable:
    """Register a clause callable and trace its calls while a sink is open."""

    def decorate(func: Callable) -> Callable:
        meta = ClauseMeta(
            code=code,
            ref=ref,
            title=title,
            symbol=symbol,
            units=units,
            latex=latex,
            func=getattr(func, "__name__", "anonymous"),
        )
        CLAUSE_REGISTRY[meta.clause_id] = meta
        signature = inspect.signature(func)

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            output = func(*args, **kwargs)
            sink = _SINK.get()
            if sink is None:
                return output
            bound = signature.bind(*args, **kwargs)
            bound.apply_defaults()
            sink.append(
                TraceEntry(
                    code=code,
                    ref=ref,
                    title=title,
                    symbol=symbol,
                    inputs={name: _plain(value) for name, value in bound.arguments.items()},
                    output=_plain(output),
                    units=units,
                    latex=latex,
                )
            )
            return output

        wrapper.clause_meta = meta
        return wrapper

    return decorate


def registry_entries() -> List[ClauseMeta]:
    """Every registered clause, sorted by clause id; report.py's bibliography."""
    return [CLAUSE_REGISTRY[key] for key in sorted(CLAUSE_REGISTRY)]


def _plain(value: Any) -> Any:
    """JSON-stable view of a traced value; NamedTuple returns become dicts."""
    if isinstance(value, (bool, int, float, str)) or value is None:
        return value
    as_dict = getattr(value, "_asdict", None)
    if callable(as_dict):
        return {key: _plain(item) for key, item in as_dict().items()}
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_plain(item) for item in value]
    return repr(value)
