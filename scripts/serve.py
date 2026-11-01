"""
Production entrypoint (the Dockerfile CMD).

  * binds to $PORT (Render sets it; defaults to 8000 locally)
  * trusts the platform proxy's X-Forwarded-* headers so client addresses are real
  * optionally applies database migrations first (RUN_MIGRATIONS=1); a failed migration
    stops the container instead of serving a half-migrated schema

Plain Python on purpose: a shell script saved with Windows line endings fails inside Linux.
"""

import os
import subprocess
import sys
from typing import Mapping


def build_server_kwargs(environ: Mapping[str, str]) -> dict:
    return {
        "host": "0.0.0.0",
        "port": int(environ.get("PORT", "8000")),
        "proxy_headers": True,
        "forwarded_allow_ips": "*",
        "log_level": "info",
    }


def run_migrations() -> None:
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], check=True)


def main(environ: Mapping[str, str] = os.environ) -> None:
    if environ.get("RUN_MIGRATIONS") == "1":
        run_migrations()
    import uvicorn

    uvicorn.run("main:app", **build_server_kwargs(environ))


if __name__ == "__main__":
    main()