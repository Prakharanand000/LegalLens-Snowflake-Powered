"""
dbt wrapper for Windows Microsoft Store Python.
Patches platform.libc_ver() before dbt imports Snowflake connector.
Usage: python run_dbt.py build --profiles-dir .
"""
import platform
import sys

# Patch BEFORE any dbt/snowflake imports
original_libc_ver = platform.libc_ver
def _safe_libc_ver(executable=None):
    try:
        return original_libc_ver(executable)
    except OSError:
        return ('', '')
platform.libc_ver = _safe_libc_ver

# Also add MFA authenticator to Snowflake connections made by dbt
import os
os.environ.setdefault("SNOWFLAKE_AUTHENTICATOR", "username_password_mfa")

# Now run dbt as if called from command line
from dbt.cli.main import cli
cli(sys.argv[1:])
