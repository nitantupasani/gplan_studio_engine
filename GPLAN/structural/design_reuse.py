"""Internal, process-local reuse of identical Housing engineering passes.

Column fingerprints describe pictures, never engineering cache identity. Keys
here retain exact SI values, member identities, support topology, architecture,
all request and resolved options, and the engine source/data/rate fingerprint.
Only the requested variant and the explicitly named search telemetry are omitted.

The cache holds at most 12 completed passes. Matching in-flight computations
share a Future; different keys compute independently. Exceptions are never kept.
Operational counters are deliberately outside the deterministic wire response.
There is no cross-process, disk or Redis cache and no cached response envelope.
"""
from __future__ import annotations

import copy
import hashlib
import json
from collections import OrderedDict
from concurrent.futures import Future
from dataclasses import fields, is_dataclass
from enum import Enum
from fractions import Fraction
from threading import RLock
from typing import Any, Callable, Dict


def _exact(value: Any) -> Any:
    """Canonical, lossless primitive state; never use rounded wire geometry."""
    if isinstance(value, Enum):
        return _exact(value.value)
    if isinstance(value, Fraction):
        return {"__fraction__": [value.numerator, value.denominator]}
    if is_dataclass(value):
        return {field.name: _exact(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, dict):
        # Type-tag keys: integer storey keys must not alias string identifiers.
        return {"__mapping__": sorted(
            [[_exact(key), _exact(item)] for key, item in value.items()],
            key=lambda row: json.dumps(row[0], sort_keys=True, allow_nan=False),
        )}
    if isinstance(value, (tuple, list)):
        return [_exact(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError("unsupported engineering signature value: " + type(value).__name__)


def engineering_signature(model: Any, request: Dict[str, Any], resolved: Dict[str, Any],
                          system: str, valid: bool, engine_fingerprint: str,
                          referral: bool = False) -> str:
    """Signature after final placement, recomputed after every referral repair.

Everything unrecognized stays in the key. Request output and option origins
are retained conservatively even when they only affect presentation.
"""
    model_state = copy.deepcopy(vars(model))
    frame_meta = model_state.get("meta", {}).get("frame_placement", {})
    frame_meta.get("metrics", {}).pop("housing_search", None)
    request_state = copy.deepcopy(request)
    request_state.get("params", {}).pop("housing_column_variant", None)
    option_state = copy.deepcopy(resolved)
    option_state.pop("housing_column_variant", None)
    option_state.get("params", {}).pop("housing_column_variant", None)
    option_state.get("origins", {}).pop("housing_column_variant", None)
    state = {
        "version": "housing-engineering-pass-1", "model": model_state,
        "request": request_state, "resolved": option_state,
        "system": system, "valid": valid, "engine": engine_fingerprint,
        "referral": referral,
    }
    encoded = json.dumps(_exact(state), sort_keys=True, separators=(",", ":"), allow_nan=False)
    return "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class EngineeringCache:
    """Bounded completed state, one producer per exact signature."""

    def __init__(self, limit: int = 12) -> None:
        if limit < 1:
            raise ValueError("cache limit must be positive")
        self.limit = limit
        self._lock = RLock()
        self._completed = OrderedDict()
        self._pending = {}
        self._counts = self._empty_counts()

    @staticmethod
    def _empty_counts() -> Dict[str, int]:
        return dict.fromkeys(("requests", "cache_hits", "expensive_design_invocation_count",
                              "failed_invocation_count", "referral_requests", "referral_cache_hits"), 0)

    def clear(self) -> None:
        with self._lock:
            if self._pending:
                raise RuntimeError("cannot clear engineering cache during active computation")
            self._completed.clear()
            self._counts = self._empty_counts()

    def diagnostics(self) -> Dict[str, int]:
        with self._lock:
            return dict(self._counts, cache_entries=len(self._completed),
                        cache_limit=self.limit, in_flight=len(self._pending))

    def run(self, key: str, compute: Callable[[], Any], referral: bool = False) -> Any:
        with self._lock:
            self._counts["requests"] += 1
            self._counts["referral_requests"] += int(referral)
            if key in self._completed:
                saved = self._completed.pop(key)
                self._completed[key] = saved
                self._counts["cache_hits"] += 1
                self._counts["referral_cache_hits"] += int(referral)
                return copy.deepcopy(saved)
            future = self._pending.get(key)
            producer = future is None
            if producer:
                future = Future()
                self._pending[key] = future
                self._counts["expensive_design_invocation_count"] += 1
            else:
                self._counts["cache_hits"] += 1
                self._counts["referral_cache_hits"] += int(referral)
        if not producer:
            try:
                saved = future.result()
            except Exception:
                # A producer may have stopped after mutating its own partial
                # model. Sharing only its exception would give this caller a
                # different, incomplete refusal geometry. Run this caller's
                # pass independently; failed work is never reused.
                with self._lock:
                    self._counts["cache_hits"] -= 1
                    self._counts["referral_cache_hits"] -= int(referral)
                    self._counts["expensive_design_invocation_count"] += 1
                try:
                    return copy.deepcopy(compute())
                except BaseException:
                    with self._lock:
                        self._counts["failed_invocation_count"] += 1
                    raise
            return copy.deepcopy(saved)
        try:
            saved = copy.deepcopy(compute())
        except BaseException as error:
            with self._lock:
                self._counts["failed_invocation_count"] += 1
                self._pending.pop(key)
                future.set_exception(error)
            raise
        with self._lock:
            self._completed[key] = saved
            while len(self._completed) > self.limit:
                self._completed.popitem(last=False)
            self._pending.pop(key)
            future.set_result(saved)
        return copy.deepcopy(saved)


_DESIGN_CACHE = EngineeringCache()


def design_cache_diagnostics() -> Dict[str, int]:
    """Operational evidence only; counts may vary with process/cache history."""
    return _DESIGN_CACHE.diagnostics()


def clear_design_cache() -> None:
    """Start an isolated evidence measurement; refuses while work is running."""
    _DESIGN_CACHE.clear()


def _delta(before: Dict[str, Any], after: Dict[str, Any]) -> Dict[str, Any]:
    nested = {key: _delta(before[key], value) for key, value in after.items()
              if key in before and isinstance(before[key], dict) and isinstance(value, dict)
              and before[key] != value}
    return {"set": {key: value for key, value in after.items()
                    if key not in nested and (key not in before or before[key] != value)},
            "nested": nested,
            "delete": sorted(set(before) - set(after))}


def _apply(target: Dict[str, Any], delta: Dict[str, Any]) -> None:
    for key in delta["delete"]:
        target.pop(key, None)
    target.update(delta["set"])
    for key, patch in delta["nested"].items():
        _apply(target[key], patch)


def reuse_design_pass(key: str, model: Any, opts: Any, log: Any,
                      compute: Callable[[Any], Any], referral: bool = False) -> Any:
    """Replay engineering mutations only; keep the actual request provenance.

The independent pass log merges into the current caller's placement log.
Metadata deltas are per key so cached foundations cannot replace the current
candidate's frame-placement telemetry. Every returned object is a deep copy.
"""
    def calculate() -> Dict[str, Any]:
        before_model = copy.deepcopy(vars(model))
        before_meta = before_model.pop("meta")
        before_opts = copy.deepcopy(vars(opts))
        pass_log = type(log)()
        result = compute(pass_log)
        after_model = dict(vars(model))
        after_meta = after_model.pop("meta")
        return {"pass": result, "model": _delta(before_model, after_model),
                "meta": _delta(before_meta, after_meta),
                "options": _delta(before_opts, vars(opts)), "log": pass_log.entries}

    saved = _DESIGN_CACHE.run(key, calculate, referral=referral)
    _apply(vars(model), saved["model"])
    _apply(model.meta, saved["meta"])
    _apply(vars(opts), saved["options"])
    log.extend(saved["log"])
    return saved["pass"]
