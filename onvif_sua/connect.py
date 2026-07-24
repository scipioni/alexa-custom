"""ONVIF connection layer: service discovery, analytics-rule query, PullPoint
subscribe/close/unsubscribe. Deliberately NOT named `onvif` — it must not shadow
the third-party `onvif` library, which is located on disk via
`__import__("onvif").__file__` for its bundled WSDL directory (preserved verbatim)."""
import asyncio
import os
from typing import Optional

from .config import PULL_NS


# ── servizi ONVIF ─────────────────────────────────────────────────────────────

_SVC_NAMES = {
    "ver10/device":    "Device",
    "ver10/media":     "Media",
    "ver20/media":     "Media2",
    "ver10/events":    "Events",
    "ver20/analytics": "Analytics",
    "ver10/recording": "Recording",
    "ver10/replay":    "Replay",
    "ver10/search":    "Search",
    "ver20/ptz":       "PTZ",
    "ver10/deviceio":  "DeviceIO",
    "ver10/display":   "Display",
    "ver10/receiver":  "Receiver",
    "ver10/imaging":   "Imaging",
}
def _namespaces_to_labels(namespaces: list[str]) -> list[str]:
    seen, labels = set(), []
    for ns in namespaces:
        label = None
        for k, v in _SVC_NAMES.items():
            if k in ns:
                label = v
                break
        if label is None:
            last = ns.rstrip("/").split("/")[-1]
            if last.lower() == "wsdl":
                continue
            label = last
        if label not in seen:
            seen.add(label)
            labels.append(label)
    return labels
async def _get_services(c) -> list[str]:
    try:
        dev = await c.create_devicemgmt_service()
        svcs = await dev.GetServices({"IncludeCapability": False})
        seen, namespaces = set(), []
        for s in (svcs or []):
            ns = getattr(s, "Namespace", None) or ""
            if ns and ns not in seen:
                seen.add(ns)
                namespaces.append(ns)
        return namespaces
    except Exception:
        return []
async def _get_analytics_rules(c, ip: str) -> dict:
    result = {}
    try:
        media = await c.create_media_service()
        profs = await asyncio.wait_for(media.GetProfiles(), timeout=8)
        va_tokens = {}
        for prof in (profs or []):
            va_cfg = getattr(prof, "VideoAnalyticsConfiguration", None)
            if va_cfg is None:
                continue
            tok  = getattr(va_cfg, "token", None) or ""
            name = getattr(prof, "Name", None) or tok
            if tok and tok not in va_tokens:
                va_tokens[tok] = name
        if not va_tokens:
            return {}
        try:
            va_cfgs = await asyncio.wait_for(
                media.GetVideoAnalyticsConfigurations(), timeout=8
            )
            rule_types = []
            for va in (va_cfgs or []):
                for rule in (getattr(va, "Rules", None) or []):
                    for r in (getattr(rule, "Rule", None) or []):
                        rt = str(getattr(r, "Type", "") or "")
                        rn = str(getattr(r, "Name", "") or "")
                        if rt:
                            rule_types.append(f"{rn}:{rt}" if rn else rt)
            if rule_types:
                result["media_va"] = rule_types
        except Exception:
            pass
        try:
            analytics_svc = await c.create_analytics_service()
            supported = await asyncio.wait_for(
                analytics_svc.GetSupportedRules({}), timeout=8
            )
            sup_types = []
            for rt in (getattr(supported, "RuleDescription", None) or []):
                rtype = getattr(rt, "Name", None) or str(rt)
                sup_types.append(rtype)
            if sup_types:
                result["__supported__"] = sup_types
        except Exception:
            pass
    except Exception:
        pass
    return result
class _SubLimitError(Exception):
    def __init__(self, namespaces: list, creds: tuple):
        self.namespaces = namespaces
        self.creds = creds


class _AuthError(Exception):
    """Raised when an ONVIF operation is rejected for AUTHENTICATION reasons (wrong
    credentials) — as opposed to _SubLimitError (auth OK, subscription slot occupied)
    or a plain network/timeout error. The worker treats this as a hard auth failure
    and quarantines the camera instead of retrying (avoids the anti-intrusion lockout)."""
    def __init__(self, creds: tuple):
        self.creds = creds


# Substrings that mark an ONVIF/SOAP fault as an authentication rejection. Kept tight
# (no bare "auth"/"password") to avoid misclassifying a resource/limit fault — the
# Dahua CGI 401/403 path is the guaranteed backstop detector for a wrong password.
_AUTH_MARKERS = (
    "notauthorized", "not authorized", "unauthorized", "sender not authorized",
    "authentication", "http status 401", "http status 403",
    "status code 401", "status code 403", " 401", " 403",
)


def _looks_like_auth_error(exc: Exception) -> bool:
    s = str(exc).lower()
    return any(m in s for m in _AUTH_MARKERS)
async def _safe_close(c):
    if c is not None:
        try:
            await c.close()
        except Exception:
            pass
async def _safe_unsubscribe(pullpoint):
    """Best-effort ONVIF PullPoint Unsubscribe (bounded) so the camera frees the
    subscription slot immediately instead of holding a stale one until PT2M expiry.
    A Dahua has very few PullPoint slots; not releasing ours is why a reconnect or a
    container restart can sit in 'connessione…' for a minute or two."""
    if pullpoint is None:
        return
    try:
        await asyncio.wait_for(pullpoint.Unsubscribe(), timeout=4)
    except Exception:
        pass
async def _try_connect(ip: str, port: int, user: str, pwd: str) -> Optional[tuple]:
    from onvif import ONVIFCamera
    wsdl = os.path.join(os.path.dirname(__import__("onvif").__file__), "wsdl")
    c = ONVIFCamera(ip, port, user, pwd, wsdl_dir=wsdl)
    try:
        await c.update_xaddrs()
        namespaces = await _get_services(c)
        evt = await c.create_events_service()
        try:
            # Nessun filtro topic → riceve tutti gli eventi inclusi AI/analytics
            sub = await evt.CreatePullPointSubscription({
                "InitialTerminationTime": "PT2M",
            })
        except Exception as e:
            # Close the session either way (otherwise aiohttp logs "Unclosed client
            # session" on GC), then classify: a credential rejection is a hard auth
            # failure (_AuthError → quarantine); anything else is an occupied
            # subscription slot with auth OK (_SubLimitError, retried as today).
            await _safe_close(c)
            if _looks_like_auth_error(e):
                raise _AuthError((user, pwd))
            raise _SubLimitError(namespaces, (user, pwd))
        c.xaddrs[PULL_NS] = sub.SubscriptionReference.Address._value_1
        pp = await c.create_pullpoint_service()
        return (c, evt, pp, namespaces)
    except (_SubLimitError, _AuthError):
        raise
    except Exception as e:
        await _safe_close(c)   # never leak the session on any connect failure
        # An auth rejection surfacing from an earlier call (e.g. GetServices) is a
        # hard auth failure too; a network/timeout error stays a plain retry.
        if _looks_like_auth_error(e):
            raise _AuthError((user, pwd))
        raise
