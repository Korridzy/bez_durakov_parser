"""Validate the configured operator tool module before deployment.

No connection is opened, because the factory contract forbids connecting during
construction, so this answers whether startup will accept the module even with the
database down.
"""

import sys

from bd_shared.config import DATABASE_URL, DATASET_CONFIG_ERROR, DATASET_TOOLS_MODULE

from agent.engine import build_read_only_engine
from agent.toolmodule import ToolModuleError, load_tool_module


def main() -> int:
    """Validate the tool module through the same loader and engine backend startup uses."""
    if DATASET_CONFIG_ERROR is not None:
        print(DATASET_CONFIG_ERROR, file=sys.stderr)
        return 1

    try:
        engine = build_read_only_engine(DATABASE_URL)
    except Exception as error:
        print(f"Database URL is invalid: {error}", file=sys.stderr)
        return 1

    try:
        _, specs = load_tool_module(DATASET_TOOLS_MODULE, engine)
    except ToolModuleError as error:
        print(f"Tool module is invalid: {error}", file=sys.stderr)
        return 1

    names = ", ".join(spec.name for spec in specs)
    print(f"Tool module is valid: {DATASET_TOOLS_MODULE} ({len(specs)} tools: {names})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
