"""Single dispatch surface over the operator's discovered service for every agent consumer."""
import asyncio
import importlib
from collections.abc import Callable, Mapping
from datetime import date, datetime, timedelta
from decimal import Decimal
from functools import partial
from typing import Any

from agent.toolmodule import discover

# Resolved at import time exactly like a static import - a missing package still
# raises ModuleNotFoundError here - but not as a static resolution target, because
# these live in the backend image only and the host checker cannot see them.
np = importlib.import_module("numpy")
pd = importlib.import_module("pandas")

ONE_SECOND = np.timedelta64(1, "s")
ONE_FEMTOSECOND = np.timedelta64(1, "fs")
SECONDS_PER_FEMTOSECOND = float(ONE_FEMTOSECOND / ONE_SECOND)

# The synthesised column name for a bare list result. Deliberately neutral, and chosen so it
# cannot collide with a real column of an operator's own table.
ID_COLUMN = "item"


class ToolError(Exception):
    """Every failure a tool consumer is expected to handle instead of crashing."""


def _json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, np.datetime64):
        # .item() yields a date/datetime only down to microsecond precision;
        # finer units return raw integer ticks, so those are re-cast first.
        moment = value.item()
        if not isinstance(moment, (datetime, date)):
            moment = value.astype("datetime64[us]").item()
        return _json_safe(moment)
    if isinstance(value, np.timedelta64):
        if np.isnat(value):
            return None
        try:
            return float(value / ONE_SECOND)
        except TypeError:
            # Calendar units (Y, M) have no fixed second length; numpy's own cast
            # is what defines the average year and month.
            return float(value.astype("timedelta64[s]") / ONE_SECOND)
        except OverflowError:
            # Sub-femtosecond units cannot reach seconds in int64 at all, and casting
            # to a coarser unit would truncate the value away, so the tick count is
            # scaled instead - both ratios still come from numpy's own arithmetic.
            unit, step = np.datetime_data(value)
            femtoseconds_per_tick = float(np.timedelta64(step, unit) / ONE_FEMTOSECOND)
            return float(value.astype("int64")) * femtoseconds_per_tick * SECONDS_PER_FEMTOSECOND
    if isinstance(value, np.generic):
        # Blanket recursion here would never terminate: longdouble.item() returns
        # itself, since Python has no extended-precision equivalent.
        return value.item()
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, timedelta):
        return value.total_seconds()
    if isinstance(value, Mapping):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def _normalize_result(name: str, result: Any) -> tuple[list[dict[str, Any]], list[str]]:
    if result is None:
        return [], []
    if isinstance(result, pd.DataFrame):
        if result.empty:
            return [], []
        return [_json_safe(row) for row in result.to_dict(orient="records")], list(result.columns)
    if isinstance(result, Mapping):
        if not result:
            return [], []
        return [_json_safe(dict(result))], list(result)
    if isinstance(result, list):
        if not result:
            return [], []
        return [{ID_COLUMN: _json_safe(item)} for item in result], [ID_COLUMN]
    raise ToolError(f"Tool '{name}' returned an unsupported result type: {type(result).__name__}")


def _as_response(result: Any) -> Any:
    if isinstance(result, (dict, list)) or result is None:
        return result

    to_dict_method = getattr(result, "to_dict", None)
    if callable(to_dict_method):
        return to_dict_method(orient="records")

    return result


class ToolRegistry:
    """Validated, off-loop access to every tool discovered on the operator's service."""

    def __init__(self, service: Any):
        self.service = service
        self.specs = {spec.name: spec for spec in discover(service)}
        self.names = frozenset(self.specs)
        self.param_specs = {
            name: tuple(param.name for param in spec.params) for name, spec in self.specs.items()
        }

    def validate_args(self, name: str, args: Mapping[str, Any]) -> None:
        if name not in self.names:
            raise ToolError(f"Unknown tool: {name}")

        unsupported = sorted(set(args) - set(self.param_specs[name]))
        if unsupported:
            raise ToolError(f"Tool '{name}' does not accept: {', '.join(unsupported)}")

    def _adapt_args(self, name: str, args: Mapping[str, Any]) -> dict[str, Any]:
        """Turn the ISO strings the model sends back into the dates the method annotated."""
        adapted = dict(args)
        for param in self.specs[name].params:
            if not param.needs_date:
                continue
            value = adapted.get(param.name)
            if isinstance(value, str):
                try:
                    adapted[param.name] = param.python_type.fromisoformat(value)
                except ValueError as error:
                    raise ToolError(
                        f"Tool '{name}' got an invalid ISO date for {param.name}: {value!r}"
                    ) from error
        return adapted

    def _call_and_convert(
        self,
        name: str,
        call_args: Mapping[str, Any],
        convert: Callable[[Any], Any],
    ) -> Any:
        try:
            # Resolved per call so a method patched after construction still wins.
            method = getattr(self.service, name)
            result = method(**call_args)
        except Exception as error:
            raise ToolError(f"Tool '{name}' failed: {error}") from error
        # Converting here keeps every pandas traversal on the worker thread that
        # already ran the query, instead of handing a frame back to the event loop.
        return convert(result)

    async def _execute(
        self, name: str, args: Mapping[str, Any], convert: Callable[[Any], Any]
    ) -> Any:
        self.validate_args(name, args)
        call_args = self._adapt_args(name, args)
        return await asyncio.to_thread(self._call_and_convert, name, call_args, convert)

    async def execute_raw(self, name: str, args: Mapping[str, Any]) -> Any:
        return await self._execute(name, args, lambda result: result)

    async def execute_normalized(
        self, name: str, args: Mapping[str, Any]
    ) -> tuple[list[dict[str, Any]], list[str]]:
        return await self._execute(name, args, partial(_normalize_result, name))

    async def execute_response(self, name: str, args: Mapping[str, Any]) -> Any:
        return await self._execute(name, args, _as_response)
