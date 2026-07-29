"""A camera entry in `_cameras` carries its working credential inline, and the two
places the registry leaves the process — `data/events.json` and the web API — used to
emit the whole entry. `data/events.json` was found on a live install holding
`"pass": "<the live camera password>"` in plain text.

These tests pin the redaction at the serialization boundary rather than trusting each
call site to remember, and the `_new_cam` test fails if a future credential-ish field
is added to the entry without being added to `_CAM_PRIVATE_KEYS`.
"""
import json

from onvif_sua import state, worker


_SECRET = "not-a-real-password"


def _cam():
    cam = worker._new_cam("10.0.0.1", "bagno", user="admin", pwd=_SECRET)
    cam["creds_tried"] = [f"admin/{'*' * len(_SECRET)}"]
    return cam


# ── the redaction helper itself ───────────────────────────────────────────────────
def test_public_cam_drops_credentials():
    pub = state._public_cam(_cam())
    assert "pass" not in pub
    assert "user" not in pub
    assert _SECRET not in json.dumps(pub)


def test_public_cam_keeps_the_operational_fields():
    # Redaction must not cost the dashboard the fields it renders.
    pub = state._public_cam(_cam())
    for k in ("ip", "port", "name", "status", "services", "topics", "event_count"):
        assert k in pub, f"{k} must survive redaction"


def test_public_cam_keeps_masked_creds_tried():
    # Already masked where it is written, and the main clue for an auth failure.
    pub = state._public_cam(_cam())
    assert pub["creds_tried"] == [f"admin/{'*' * len(_SECRET)}"]


def test_public_cam_does_not_mutate_the_live_entry():
    cam = _cam()
    state._public_cam(cam)
    assert cam["pass"] == _SECRET, "the in-memory entry still needs its credential"


def test_public_cameras_redacts_every_entry():
    cams = {"10.0.0.1": _cam(), "10.0.0.2": _cam()}
    pub = state._public_cameras(cams)
    assert set(pub) == set(cams)
    assert _SECRET not in json.dumps(pub)


# ── the guard against a future leak ───────────────────────────────────────────────
def test_new_cam_exposes_no_unredacted_secret_field():
    """Whitelist review: every key `_new_cam` creates is either public-safe or listed
    in `_CAM_PRIVATE_KEYS`. A new credential-ish key trips this until it is classified."""
    suspicious = {"user", "pass", "password", "pwd", "secret", "token", "credential"}
    leaked = {
        k for k in worker._new_cam("10.0.0.1", "bagno")
        if k.lower() in suspicious and k not in state._CAM_PRIVATE_KEYS
    }
    assert not leaked, f"credential-ish keys not redacted: {leaked}"
