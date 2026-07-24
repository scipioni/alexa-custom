"""FastAPI application: the app instance, the unauthenticated `/static` mount, the
Jinja2 template environment, and the session-auth helpers (ephemeral HMAC cookie).
The routes themselves live in `routes.py` and are registered on import."""
import hashlib
import hmac
import secrets
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from ..config import _cfg

# Segreto ephemero per HMAC cookie — rigenerato ad ogni avvio
_WEB_SECRET = secrets.token_bytes(32)


def _session_token() -> str:
    return hmac.new(_WEB_SECRET, b"onvif-session-v1", hashlib.sha256).hexdigest()


def _valid_session(request: Request) -> bool:
    token = request.cookies.get("onvif_session", "")
    return bool(token) and hmac.compare_digest(token, _session_token())


app = FastAPI(title="ONVIF Events")

# Resolve template/static dirs from the PACKAGE location (never CWD) so a
# non-editable install serves them from site-packages too (design RM1).
_WEB_DIR = Path(__file__).resolve().parent

# The /static mount is a SEPARATE StaticFiles sub-app, unauthenticated by default
# and deliberately NOT gated by _valid_session (design RM3): assets carry no
# secrets, and the login page (itself un-gated) needs its stylesheet.
app.mount("/static", StaticFiles(directory=str(_WEB_DIR / "static")), name="static")

templates = Jinja2Templates(directory=str(_WEB_DIR / "templates"))
# Cache-busting token exposed to every template as {{ asset_version }}. Each page
# route also passes the live _cfg value in its render context (so a settings bump
# applies without a process restart); this global is the safe default.
templates.env.globals["asset_version"] = _cfg.get("asset_version", "1")

_401 = {"status": "error", "detail": "Non autenticato"}
