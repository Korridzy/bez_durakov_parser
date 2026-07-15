import os
import subprocess
import sys

debug_mode = os.getenv('WEBREPORT_DEBUG') == 'true'
reload_enabled = os.getenv('WEBREPORT_RELOAD', 'true') == 'true' and not debug_mode

if debug_mode:
    import pydevd_pycharm
    port = int(os.getenv('WEBREPORT_FRONTEND_DEBUG_PORT', 5679))
    pydevd_pycharm.settrace('host.docker.internal', port=port, stdout_to_server=True, stderr_to_server=True)

result = subprocess.run([
    "streamlit",
    "run",
    "main.py",
    "--server.port",
    "8501",
    "--server.address",
    "0.0.0.0",
    "--server.runOnSave",
    str(reload_enabled).lower(),
])
sys.exit(result.returncode)
