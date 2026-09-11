"""Load the operator's tool module and learn its tool surface from the object it returns.

A strict loader with no dependency on bd_shared.config, the same shape agent/knowledge.py
follows, so the callers supply the values. Discovery is what replaces the fixed tool list:
every public callable of the service object becomes a tool named after the method, described
by its docstring and parameterised by its type hints.
"""

import importlib
import inspect
import re
from dataclasses import dataclass
from datetime import date, datetime
from types import SimpleNamespace, UnionType
from typing import Final, Union, get_args, get_origin, get_type_hints

from sqlalchemy import Engine

FACTORY_NAME: Final = "build_service"

RESERVED_TOOL_NAMES: Final = frozenset({"read_rows", "mark_report", "read_knowledge"})

ENVELOPE_NOTE: Final = (
    "Returns a metadata envelope with a data handle. "
    "Call read_rows with that handle to page the records."
)

# Tool arguments arrive as JSON from the model and travel back inside the handle envelope,
# so the annotations a parameter may carry are the JSON-expressible scalars plus dates.
SUPPORTED_TYPES: Final = (str, int, float, bool, date, datetime)

_BLANK_LINE = re.compile(r"\n\s*\n")


class ToolModuleError(Exception):
    """Every way an operator's tool module can fail to satisfy the contract."""

    def __init__(self, message: str, *, module: str | None = None, method: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.module = module
        self.method = method

    def __str__(self) -> str:
        subject = ".".join(part for part in (self.module, self.method) if part)
        return f"{subject} {self.message}" if subject else self.message


@dataclass(frozen=True)
class ParamSpec:
    """One tool parameter, as the wire sees it and as the method wants it.

    wire_type is what the generated JSON schema declares, so a date parameter is a string
    there. python_type is what the method annotated, which is what the registry coerces an
    ISO string back into just before the call.
    """

    name: str
    wire_type: type
    optional: bool
    needs_date: bool
    has_default: bool
    default: object
    python_type: type


@dataclass(frozen=True)
class ToolSpec:
    """One discovered tool: the method name, its composed description and its parameters."""

    name: str
    description: str
    params: tuple[ParamSpec, ...]


def _describe(docstring: str) -> str:
    """Compose a tool description from the docstring's first paragraph.

    Only the first paragraph is taken: a Google-style Returns block describes the service
    return, while the tool returns a handle envelope, so carrying the whole docstring through
    would tell the model something false.
    """
    paragraph = _BLANK_LINE.split(docstring.strip(), maxsplit=1)[0]
    return f"{' '.join(paragraph.split())}\n{ENVELOPE_NOTE}"


def _param_spec(name: str, parameter: inspect.Parameter, annotation: object, method: str) -> ParamSpec:
    """Turn one annotated parameter into its wire specification."""
    optional = False
    wire = annotation
    if get_origin(annotation) in (Union, UnionType):
        members = [member for member in get_args(annotation) if member is not type(None)]
        optional = len(members) < len(get_args(annotation))
        if len(members) != 1:
            raise ToolModuleError(
                f"parameter '{name}' has an unsupported annotation: {annotation}", method=method
            )
        wire = members[0]

    if wire not in SUPPORTED_TYPES:
        raise ToolModuleError(
            f"parameter '{name}' has an unsupported annotation: {annotation}", method=method
        )

    needs_date = wire in (date, datetime)
    has_default = parameter.default is not inspect.Parameter.empty
    return ParamSpec(
        name=name,
        wire_type=str if needs_date else wire,
        optional=optional,
        needs_date=needs_date,
        has_default=has_default,
        default=parameter.default if has_default else None,
        python_type=wire,
    )


def _parameter_hints(method: object) -> dict[str, object]:
    """Resolve the parameter annotations only.

    A return annotation never reaches the generated schema, so an operator method whose
    parameters are all fine must not fail discovery because its return type happens to be an
    unresolvable forward reference.
    """
    function = inspect.unwrap(method)
    annotations = dict(getattr(function, "__annotations__", {}))
    annotations.pop("return", None)
    probe = SimpleNamespace(__annotations__=annotations)
    return get_type_hints(probe, globalns=getattr(function, "__globals__", {}))


def _tool_spec(name: str, method: object) -> ToolSpec:
    """Validate one discovered method and build its specification."""
    if name in RESERVED_TOOL_NAMES:
        raise ToolModuleError("collides with a reserved tool name", method=name)

    docstring = inspect.getdoc(method)
    if not docstring or not docstring.strip():
        raise ToolModuleError("has no docstring", method=name)

    try:
        hints = _parameter_hints(method)
    except Exception as error:
        raise ToolModuleError(f"has an unresolvable annotation: {error}", method=name) from error

    params = []
    for param_name, parameter in inspect.signature(method).parameters.items():
        if parameter.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
            raise ToolModuleError(
                f"parameter '{param_name}' is variadic, which a tool cannot express", method=name
            )
        if parameter.kind is inspect.Parameter.POSITIONAL_ONLY:
            # Every tool call arrives as keyword arguments, so a positional-only parameter
            # would pass discovery and then fail on every invocation. Refusing at startup
            # turns an unusable tool into one clear line.
            raise ToolModuleError(
                f"parameter '{param_name}' is positional-only, and tools are called by keyword",
                method=name,
            )
        if param_name not in hints:
            raise ToolModuleError(f"parameter '{param_name}' has no type annotation", method=name)
        params.append(_param_spec(param_name, parameter, hints[param_name], name))

    return ToolSpec(name=name, description=_describe(docstring), params=tuple(params))


def discover(service: object) -> tuple[ToolSpec, ...]:
    """Read the tool surface off the service object, in alphabetical order.

    Attributes are read with inspect.getattr_static so descriptors never fire: evaluating a
    property at discovery time would execute operator code at startup and could open a
    connection, which the factory contract forbids. A non-callable attribute and a property
    are skipped silently, because a rejecting rule would make an ordinary service with a
    public instance attribute undiscoverable. A helper that should not be a tool takes a
    leading underscore.
    """
    specs = []
    for name in dir(service):
        if name.startswith("_"):
            continue
        try:
            raw = inspect.getattr_static(service, name)
        except AttributeError:
            continue
        if isinstance(raw, (staticmethod, classmethod)):
            raw = raw.__func__
        if isinstance(raw, property) or not callable(raw):
            continue
        specs.append(_tool_spec(name, getattr(service, name)))
    return tuple(specs)


def load_tool_module(import_path: str, engine: Engine) -> tuple[object, tuple[ToolSpec, ...]]:
    """Import the operator's module, call its factory with the engine and discover its tools."""
    try:
        module = importlib.import_module(import_path)
    except Exception as error:
        raise ToolModuleError(f"could not be imported: {error}", module=import_path) from error

    factory = getattr(module, FACTORY_NAME, None)
    if factory is None:
        raise ToolModuleError(f"has no {FACTORY_NAME} factory", module=import_path)
    if not callable(factory):
        raise ToolModuleError(f"has a {FACTORY_NAME} that is not callable", module=import_path)

    try:
        service = factory(engine)
    except Exception as error:
        raise ToolModuleError(f"{FACTORY_NAME} failed: {error}", module=import_path) from error

    try:
        specs = discover(service)
    except ToolModuleError as error:
        error.module = import_path
        raise

    return service, specs
