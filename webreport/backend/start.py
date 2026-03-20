import os

import uvicorn

debug_mode = os.getenv("WEBREPORT_DEBUG") == "true"

if debug_mode:
    import pydevd_pycharm

    port = int(os.getenv("WEBREPORT_BACKEND_DEBUG_PORT", 5678))
    pydevd_pycharm.settrace(
        "host.docker.internal", port=port, stdout_to_server=True, stderr_to_server=True
    )

if __name__ == "__main__":
    # Disable reload in debug mode to prevent worker from also connecting to debugger
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=not debug_mode)
