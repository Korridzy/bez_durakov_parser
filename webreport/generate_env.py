#!/usr/bin/env python3
"""
Generate .env file for WebReport from config.toml
"""
import sys
import os

# Add parent directory to path to import bd_shared package
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from bd_shared.config import WEBREPORT_BACKEND_PORT, WEBREPORT_FRONTEND_PORT, WEBREPORT_DEBUG, WEBREPORT_BACKEND_DEBUG_PORT, WEBREPORT_FRONTEND_DEBUG_PORT, XLSM_FETCH_TIMEZONE

# Generate .env file
env_content = f"""# Generated from config.toml
WEBREPORT_BACKEND_PORT={WEBREPORT_BACKEND_PORT}
WEBREPORT_FRONTEND_PORT={WEBREPORT_FRONTEND_PORT}
WEBREPORT_DEBUG={str(WEBREPORT_DEBUG).lower()}
WEBREPORT_BACKEND_DEBUG_PORT={WEBREPORT_BACKEND_DEBUG_PORT}
WEBREPORT_FRONTEND_DEBUG_PORT={WEBREPORT_FRONTEND_DEBUG_PORT}
TIMEZONE={XLSM_FETCH_TIMEZONE}
"""

with open('.env', 'w') as f:
    f.write(env_content)

print(f"Generated .env file with ports: backend={WEBREPORT_BACKEND_PORT}, frontend={WEBREPORT_FRONTEND_PORT}, timezone={XLSM_FETCH_TIMEZONE}, debug={WEBREPORT_DEBUG}")
