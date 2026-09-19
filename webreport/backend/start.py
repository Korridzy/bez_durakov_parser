import os

import uvicorn

from bd_shared.config import LOG_LEVEL, SQLALCHEMY_LOGGING
from bd_shared.logging_setup import configure_logging

configure_logging("webreport-backend", level=LOG_LEVEL, logger_levels={"sqlalchemy.engine": LOG_LEVEL} if SQLALCHEMY_LOGGING else None)

debug_mode = os.getenv("WEBREPORT_DEBUG") == "true"
reload_enabled = (
    os.getenv("WEBREPORT_RELOAD", "true") == "true" and not debug_mode
)

if debug_mode:
    import pydevd_pycharm

    port = int(os.getenv("WEBREPORT_BACKEND_DEBUG_PORT", 5678))
    pydevd_pycharm.settrace(
        "host.docker.internal", port=port, stdout_to_server=True, stderr_to_server=True
    )

if __name__ == "__main__":
    # Disable reload in debug mode to prevent worker from also connecting to debugger
    uvicorn.run("main:application", host="0.0.0.0", port=8000, reload=reload_enabled, log_config=None, access_log=False)
