"""Vercel serverless entry point for the Padhai backend.

This file deliberately contains no application logic. It exists only because
of how Python resolves imports on Vercel.

Locally the app is started with `cd backend && python app.py`, which puts
`backend/` first on `sys.path`, so `app.py`'s absolute imports
(`from config import Config`, `from services import ...`) resolve.

On Vercel the function is invoked from the deployment root, so `backend/` is
never on `sys.path` and those same imports raise
`ModuleNotFoundError: No module named 'services'`.

Adding `backend/` to `sys.path` here reproduces the local import environment
without moving a single file or changing `backend/app.py`. The Flask instance
is then imported — not recreated — so every route, service and configuration
behaves exactly as it does locally.
"""
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent / "backend"

# Prepend so the app's own modules win over any same-named installed package.
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# The existing Flask object, imported as-is. Vercel's Python runtime detects a
# module-level WSGI callable named `app` and serves it. `app.py` guards its
# `app.run(...)` behind `if __name__ == "__main__"`, so importing it never
# starts a development server.
from app import app  # noqa: E402  (path setup must run first)

# Vercel looks for `app`; some templates look for `handler`. Expose both so the
# deployment works regardless of which the runtime picks up.
handler = app

__all__ = ["app", "handler"]
