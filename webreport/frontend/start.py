import os
import subprocess

if os.getenv('WEBREPORT_DEBUG') == 'true':
    import pydevd_pycharm
    port = int(os.getenv('WEBREPORT_FRONTEND_DEBUG_PORT', 5679))
    pydevd_pycharm.settrace('host.docker.internal', port=port, stdout_to_server=True, stderr_to_server=True)

subprocess.run(["streamlit", "run", "main.py", "--server.port", "8501", "--server.address", "0.0.0.0"])
