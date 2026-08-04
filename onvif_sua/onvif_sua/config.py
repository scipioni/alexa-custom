"""Configuration: env vars, settings.yaml load/save, runtime config dict,
credential + static-camera resolution, password hashing, and packaging-related
scalar constants. Leaf module — imports nothing from the rest of the package."""
import hashlib
import hmac
import os
import re
import secrets
import socket
import string
from typing import Optional

# Load the .env secret file BEFORE any os.getenv below runs. This is the leaf
# module every other module imports, so placing load_dotenv here guarantees .env
# is applied before ANY config value is read — including the module-level reads in
# this file (which run at import, i.e. before __main__.main() would get a chance).
# override=False: an explicitly-exported process env var still wins over .env.
from dotenv import load_dotenv, dotenv_values, find_dotenv
# Resolve the .env path the same way load_dotenv() would, BEFORE loading it, so the
# diagnostic below can compare "what .env declares" against "what actually won".
_DOTENV_PATH = find_dotenv()
load_dotenv(override=False)
# Snapshot of what .env DECLARES, independent of precedence. Used only to diagnose the
# "I changed .env but nothing happened" trap: because load_dotenv runs with
# override=False, a variable already exported in the process environment WINS and the
# edited .env line is silently ignored. Comparing the two is the only way to tell the
# operator to run `unset` instead of re-editing a file that is already correct.
_DOTENV_DECLARED: dict = dict(dotenv_values(_DOTENV_PATH)) if _DOTENV_PATH else {}


# ── config ────────────────────────────────────────────────────────────────────
# NOTE: cameras come from settings.yaml, not from discovery. Automatic subnet scanning is
# OFF by default: SCAN_SUBNET / SCAN_CONCUR / ONVIF_PORTS serve the manual,
# operator-triggered GUI rescan, and the scanner runs on its own ONLY when
# scan.rescan_time_interval is set to a non-zero number of seconds (see _rescan_interval).
#
# CONFIG PRECEDENCE: env var (if set) is the DEFAULT; the value in settings.yaml
# is AUTHORITATIVE and overrides it when the key is present (see _load_settings_yaml).
# The path settings below stay env-only (SETTINGS_FILE can't live inside the file it
# points at). Their defaults are CWD-relative so `uv run onvif-sua` works natively
# from the repo with zero env; Docker sets absolute /app,/data paths in compose.
SCAN_SUBNET    = os.getenv("SCAN_SUBNET", "192.168.110.0/24")
SCAN_CONCUR    = int(os.getenv("SCAN_CONCUR", "48"))       # probe paralleli (manual scan only)
# Automatic periodic rescan: seconds that must pass SINCE THE LAST SCAN (manual or
# automatic) before another one starts. 0 = disabled, which is the default and the
# historical behaviour — the scanner then runs only when the operator asks.
RESCAN_TIME_INTERVAL = os.getenv("RESCAN_TIME_INTERVAL", "0")
ONVIF_PORTS    = [80, 8080, 8899]                          # candidate ports (manual scan only)
RESULTS_FILE   = os.getenv("RESULTS_FILE", "data/events.json")
ALARM_FILE     = os.getenv("ALARM_FILE",   "data/alarm.json")
WEB_PORT       = int(os.getenv("WEB_PORT", "8080"))

# ── single config file (settings.yaml): MQTT, manual-scan, web password, tuning
#    AND the static camera list + common credential. Read at boot, written by the GUI. ──
SETTINGS_FILE  = os.getenv("SETTINGS_FILE", "settings.yaml")

# ── detection-liveness tuning ────────────────────────────────────────────────────
# These are the DEFAULTS (env-overridable); settings.yaml `tuning:` is authoritative
# and overrides them at load (see _load_settings_yaml). N=5s heartbeat, gap factor 3
# (→ 15s of total silence flags a stalled stream), rule re-check every 5 min. Firmware
# that ignores heartbeat=N is handled by liveness_mode=keepalive.
LIVENESS_MODE        = os.getenv("LIVENESS_MODE", "heartbeat").strip().lower()  # heartbeat | keepalive
HEARTBEAT_INTERVAL   = int(os.getenv("HEARTBEAT_INTERVAL", "5"))     # N seconds
HEARTBEAT_GAP_FACTOR = float(os.getenv("HEARTBEAT_GAP_FACTOR", "3")) # not-alive after factor × N of silence
RULE_CHECK_INTERVAL  = int(os.getenv("RULE_CHECK_INTERVAL", "300"))  # seconds between rule-enabled checks
KEEPALIVE_INTERVAL   = int(os.getenv("KEEPALIVE_INTERVAL", "30"))    # fallback-mode probe interval (seconds)

# Auth-failure backoff (capped exponential) shared by all common-credential paths.
AUTH_BACKOFF_START = 30.0
AUTH_BACKOFF_CAP   = 300.0
# Startup auth gate: at most one auth attempt / camera / this window until first success.
AUTH_GATE_WINDOW   = 5.0

# detection_ok freshness: expire_after must exceed both the republish interval and
# the heartbeat gap (+ margin) so a steadily-healthy camera never lapses to unavailable.
_gap_seconds     = HEARTBEAT_GAP_FACTOR * HEARTBEAT_INTERVAL
DETECTION_EXPIRE = max(120, int(_gap_seconds) + 60, KEEPALIVE_INTERVAL + 60)
DETECTION_REPUBLISH = max(30, DETECTION_EXPIRE // 2)
# Configurazione runtime (default da env, sovrascritta/persistita in settings.yaml).
# NOTE: the three passwords (camera/scan/web) are NOT persisted here — they are
# sourced from the environment (.env); see the secrets block further below.
_cfg: dict = {
    "scan_subnet":      SCAN_SUBNET,   # subnet for the manual GUI scan + the periodic rescan
    # Seconds since the last scan before an automatic rescan runs; 0 disables it.
    "rescan_time_interval": RESCAN_TIME_INTERVAL,
    "cam_credentials":  None,          # None = usa _DEFAULT_CREDS (manual scan only)
    "mqtt_host":        os.getenv("MQTT_HOST",   ""),
    "mqtt_port":        int(os.getenv("MQTT_PORT", "1883")),
    "mqtt_user":        os.getenv("MQTT_USER",   ""),
    "mqtt_pass":        os.getenv("MQTT_PASS",   ""),
    "mqtt_prefix":      os.getenv("MQTT_PREFIX", "onvif"),
    "web_password":     "",   # riempito da _load_settings_yaml
    # Static-asset cache-busting token (settings.yaml web.asset_version). Bumped by
    # an operator after editing CSS/JS so long-running kiosks re-fetch; every
    # /static/* URL carries ?v=<asset_version>. Default "1" when the key is absent.
    "asset_version":    "1",
    # ── Serena fall-alarm bridge (opt-in) — see settings.yaml `serena:` block ──
    # Env values are DEFAULTS; the settings.yaml `serena:` block is authoritative.
    # Raw values are stored here and normalized in-place by _normalize_serena_config()
    # (bool coercion, numeric clamping, template validation) at import and after each
    # settings load, so a downstream reader never sees an un-coerced string.
    "serena_enabled":                  os.getenv("SERENA_ENABLED", ""),
    "serena_topic_prefix":             os.getenv("SERENA_TOPIC_PREFIX", "alexa"),
    "serena_node_id":                  os.getenv("SERENA_NODE_ID", ""),
    "serena_command_template":         os.getenv("SERENA_COMMAND_TEMPLATE", "caduta_{cam_name}"),
    "serena_announce_ready":           os.getenv("SERENA_ANNOUNCE_READY", "true"),
    "serena_announce_template":        os.getenv("SERENA_ANNOUNCE_TEMPLATE",
                                                  "sensore uomo a terra {cam_name} attivo"),
    "serena_announce_fault":           os.getenv("SERENA_ANNOUNCE_FAULT", ""),
    "serena_announce_fault_template":  os.getenv("SERENA_ANNOUNCE_FAULT_TEMPLATE",
                                                  "attenzione, sensore uomo a terra {cam_name} non attivo"),
    "serena_announce_fault_interval_s": os.getenv("SERENA_ANNOUNCE_FAULT_INTERVAL_S", "300"),
    "serena_announce_fault_grace_s":    os.getenv("SERENA_ANNOUNCE_FAULT_GRACE_S", "60"),
    "serena_startup_alarm_max_age_s":   os.getenv("SERENA_STARTUP_ALARM_MAX_AGE_S", "300"),
}

_INT_KEYS  = {"mqtt_port", "rescan_time_interval"}
_LIST_KEYS = {"cam_credentials"}
_STR_KEYS_OPAQUE = {"web_password"}   # salvate ma non restituite mai in chiaro

# ── Serena bridge config normalization (tasks 1.2 / 1.4) ─────────────────────────
# Booleans use EXPLICIT coercion (a raw non-empty string is NOT truthy-by-accident);
# the three time knobs are non-negative floats with a per-key clamp; the three
# templates may reference ONLY {cam_name}. Applied to both env defaults and YAML.
_BOOL_KEYS = {"serena_enabled", "serena_announce_ready", "serena_announce_fault"}
# key → default (used as the fallback when a template is invalid).
_SERENA_TEMPLATE_DEFAULTS = {
    "serena_command_template":        "caduta_{cam_name}",
    "serena_announce_template":       "sensore uomo a terra {cam_name} attivo",
    "serena_announce_fault_template": "attenzione, sensore uomo a terra {cam_name} non attivo",
}
_SERENA_INTERVAL_FLOOR = 30.0


def _coerce_bool(val) -> bool:
    """Explicit truthiness: a native bool passes through; a string is true ONLY when
    it is (case-insensitively) one of 1/true/yes/on. Everything else — including
    0/false/no/off and the empty string — is false. A raw non-empty string is never
    truthy by accident."""
    if isinstance(val, bool):
        return val
    return str(val).strip().lower() in ("1", "true", "yes", "on")


def _coerce_nonneg_float(val, default: float) -> float:
    """Coerce to a float ≥ 0; fall back to `default` on a non-numeric value; clamp a
    negative value up to 0."""
    try:
        n = float(val)
    except (TypeError, ValueError):
        return float(default)
    return n if n >= 0 else 0.0


# ── automatic periodic rescan interval ───────────────────────────────────────────
# A subnet sweep authenticates against every host, so a very short interval would be a
# repeated credential burst across the whole network — the exact pattern that trips the
# Dahua anti-intrusion lockout. Anything above 0 but below this floor is clamped up.
_RESCAN_INTERVAL_FLOOR = 60.0
_rescan_floor_warned = False


def _rescan_interval() -> float:
    """Seconds that must pass since the last subnet scan before an automatic rescan
    runs; 0.0 when automatic rescanning is disabled (the default).

    Read on every check so a change via `POST /api/config` or a settings reload takes
    effect without a restart. A non-numeric value disables the feature rather than
    guessing an interval."""
    global _rescan_floor_warned
    raw = _cfg.get("rescan_time_interval", 0)
    val = _coerce_nonneg_float(raw, 0.0)
    if val <= 0:
        return 0.0
    if val < _RESCAN_INTERVAL_FLOOR:
        if not _rescan_floor_warned:
            print(f"[scanner] rescan_time_interval {val:.0f}s sotto il minimo — forzato a "
                  f"{_RESCAN_INTERVAL_FLOOR:.0f}s (uno scan sonda ogni host della subnet: "
                  f"troppo frequente rischia il blocco anti-intrusione)", flush=True)
            _rescan_floor_warned = True
        return _RESCAN_INTERVAL_FLOOR
    _rescan_floor_warned = False
    return val


def _valid_cam_name_template(tmpl: str) -> bool:
    """True iff `tmpl` is a well-formed str.format template that references only the
    `{cam_name}` placeholder (no other field name, no positional `{}`)."""
    try:
        tmpl.format(cam_name="x")
    except Exception:
        return False
    try:
        for _lit, field, _spec, _conv in string.Formatter().parse(tmpl):
            if field is not None and field != "cam_name":
                return False
    except Exception:
        return False
    return True


def _serena_voice_name(name: str) -> str:
    """Normalize a camera name for Serena phrase-matching + Piper TTS: lowercase,
    replace `-`/`_` with a single space, collapse/trim whitespace. Never returns an
    empty string — if normalization empties the name (e.g. an all-separator name), it
    falls back to the raw (stripped) name and logs, so a phrase never loses its name."""
    raw = str(name or "")
    s = re.sub(r"\s+", " ", raw.lower().replace("-", " ").replace("_", " ")).strip()
    if not s:
        print(f"[serena] nome '{raw}' normalizza a vuoto — uso il nome grezzo", flush=True)
        return raw.strip()
    return s


def _serena_trigger_name(name: str) -> str:
    """Camera name as it appears in the *fall command* sent to Serena's `trigger/run`:
    the voice name with every space turned into `_`, so the whole payload stays a single
    space-free token (`caduta_salotto_1`). Such a token can only ever arrive over MQTT —
    it is not utterable — which keeps the SOS trigger out of reach of the STT matcher.
    The spoken announcements keep `_serena_voice_name` (spaces) so Piper reads them."""
    return _serena_voice_name(name).replace(" ", "_")


def _name_has_reserved_word(name: str) -> bool:
    """True if the (case-insensitive) name contains the reserved substring 'camera'
    (also blocks 'telecamera') — pushes operators toward room names for the voice phrase."""
    return "camera" in str(name or "").lower()


def _hostname_key(hostname) -> str:
    """Canonical comparison form of an ONVIF hostname: trimmed + lowercased. Must
    stay identical to state._hostname_key / the resolver's match (duplicated here
    only because config.py is the leaf module and cannot import state)."""
    return str(hostname or "").strip().lower()


def _entry_matches(e: dict, ip: str, hostname: Optional[str] = None) -> bool:
    """True when the `cameras.list` entry `e` is the camera addressed by (ip, hostname).

    A hostname-configured entry has NO `ip` key at all, so `str(e.get("ip")) == ip`
    renders the literal `"None"` and never matches — which silently classifies the
    entry as *a different camera* in every helper that compares that way. Callers
    that hold a runtime IP therefore pass the configured `hostname` (resolved from
    the runtime cache by the caller — config.py cannot import state) and the match
    is made on it. With no hostname the behaviour is exactly the pre-existing
    static-`ip` match.
    """
    if not isinstance(e, dict):
        return False
    if hostname:
        eh = _hostname_key(e.get("hostname"))
        return bool(eh) and eh == _hostname_key(hostname)
    # Static path: an entry carrying a `hostname` is addressed by hostname only,
    # never by a runtime IP that happens to be passed in.
    if e.get("hostname"):
        return False
    return str(e.get("ip", "")).strip() == str(ip)


def _entry_label(e: dict) -> str:
    """How to name a `cameras.list` entry in an operator-facing diagnostic: its `ip`
    when static, else its `hostname` (falling back to `name`). Never the literal
    `"None"` that `str(e.get("ip"))` yields for a hostname entry."""
    if not isinstance(e, dict):
        return "?"
    ip = str(e.get("ip", "") or "").strip()
    if ip:
        return ip
    return (str(e.get("hostname", "") or "").strip()
            or str(e.get("name", "") or "").strip() or "?")


def _name_voice_collision(ip: str, name: str, hostname: Optional[str] = None) -> Optional[str]:
    """If another already-configured camera normalizes to the same voice name as
    `name`, return that camera's label (its ip, or its hostname when it has no ip);
    else None. Serena distinguishes cameras only by the rendered phrase, so two names
    that normalize alike collide. `hostname` identifies the *caller's own* entry when
    it is hostname-configured, so a camera is never reported as colliding with itself."""
    target = _serena_voice_name(name)
    cams = _settings_doc.get("cameras")
    if not isinstance(cams, dict):
        return None
    lst = cams.get("list")
    if not isinstance(lst, list):
        return None
    for e in lst:
        if not isinstance(e, dict):
            continue
        if _entry_matches(e, ip, hostname):
            continue   # the caller's own entry
        if _serena_voice_name(str(e.get("name", ""))) == target:
            return _entry_label(e)
    return None


def _normalize_serena_config():
    """Coerce/validate the serena_* values in `_cfg` IN PLACE. Idempotent — safe to
    call at import (env defaults) and again after each settings.yaml load."""
    for k in _BOOL_KEYS:
        _cfg[k] = _coerce_bool(_cfg.get(k))
    _cfg["serena_announce_fault_interval_s"] = _coerce_nonneg_float(
        _cfg.get("serena_announce_fault_interval_s"), 300.0)
    _cfg["serena_announce_fault_grace_s"] = _coerce_nonneg_float(
        _cfg.get("serena_announce_fault_grace_s"), 60.0)
    _cfg["serena_startup_alarm_max_age_s"] = _coerce_nonneg_float(
        _cfg.get("serena_startup_alarm_max_age_s"), 300.0)
    # Interval floor: a 0/near-zero interval would flood announcements.
    if _cfg["serena_announce_fault_interval_s"] < _SERENA_INTERVAL_FLOOR:
        print(f"[serena] announce_fault_interval_s "
              f"{_cfg['serena_announce_fault_interval_s']:.0f}s sotto il minimo — "
              f"forzato a {_SERENA_INTERVAL_FLOOR:.0f}s", flush=True)
        _cfg["serena_announce_fault_interval_s"] = _SERENA_INTERVAL_FLOOR
    # grace 0 is legitimate (disables the suppression window) but is worth a warning.
    if _cfg["serena_announce_fault_grace_s"] == 0:
        print("[serena] announce_fault_grace_s=0 — finestra di soppressione disabilitata: "
              "possibili falsi 'non attivo' all'avvio o durante brevi flap", flush=True)
    for key, default in _SERENA_TEMPLATE_DEFAULTS.items():
        tmpl = str(_cfg.get(key, default))
        if not _valid_cam_name_template(tmpl):
            print(f"[serena] template '{key}' non valido ({tmpl!r}) — uso il default "
                  f"{default!r}", flush=True)
            tmpl = default
        _cfg[key] = tmpl
    _cfg["serena_topic_prefix"] = str(_cfg.get("serena_topic_prefix") or "alexa")
    # Serena itself defaults to socket.gethostname() when its own node_id is
    # unset, so mirroring that default here makes the bridge line up automatically
    # when ONVIF_SUA and Serena run on the same host — no manual node_id needed.
    _cfg["serena_node_id"] = str(_cfg.get("serena_node_id") or "") or socket.gethostname()


# Normalize the env-sourced defaults immediately (before any settings.yaml load).
_normalize_serena_config()

# Documento completo di settings.yaml così com'è stato caricato — usato per
# preservare il blocco `cameras` (e altre chiavi) quando la GUI risalva il file.
_settings_doc: dict = {}
def _hash_password(plain: str) -> str:
    salt = secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", plain.encode(), salt.encode(), 260000)
    return f"pbkdf2:sha256:260000:{salt}:{h.hex()}"

def _check_password(plain: str, stored: str) -> bool:
    try:
        _, algo, iters_s, salt, expected = stored.split(":")
        h = hashlib.pbkdf2_hmac(algo, plain.encode(), salt.encode(), int(iters_s))
        return hmac.compare_digest(h.hex(), expected)
    except Exception:
        return False
def _load_settings_yaml():
    """Carica TUTTE le impostazioni da SETTINGS_FILE (unico file di config, al posto
    di config.json + il vecchio cameras.yaml): broker MQTT, subnet/credenziali per lo scan
    manuale, password web e la lista statica delle telecamere (`cameras`). Il file è
    modificabile dalla GUI (vedi `_save_settings_yaml`) e persistente tra i riavvii.
    Il documento completo è conservato in `_settings_doc` così che un salvataggio da
    GUI (che riscrive mqtt/scan/web) preservi il blocco `cameras` e ogni altra chiave."""
    global _settings_doc
    # Tuning/port/scan-concurrency live in settings.yaml (authoritative); the module
    # constants above are the env-overridable defaults, reassigned here when present.
    global LIVENESS_MODE, HEARTBEAT_INTERVAL, HEARTBEAT_GAP_FACTOR, RULE_CHECK_INTERVAL
    global KEEPALIVE_INTERVAL, SAVE_INTERVAL, SCAN_CONCUR, WEB_PORT
    global DETECTION_EXPIRE, DETECTION_REPUBLISH
    import yaml
    data = None
    try:
        with open(SETTINGS_FILE) as f:
            data = yaml.safe_load(f)
    except FileNotFoundError:
        print(f"[settings] {SETTINGS_FILE} non trovato — uso i default da env", flush=True)
    except Exception as e:
        print(f"[settings] YAML illeggibile ({SETTINGS_FILE}): {e} — uso i default da env", flush=True)

    _settings_doc = dict(data) if isinstance(data, dict) else {}

    if isinstance(data, dict):
        mqtt = data.get("mqtt") or {}
        if isinstance(mqtt, dict):
            if "host" in mqtt:   _cfg["mqtt_host"]   = str(mqtt["host"] or "")
            if "port" in mqtt:   _cfg["mqtt_port"]   = int(mqtt["port"])
            if "user" in mqtt:   _cfg["mqtt_user"]   = str(mqtt["user"] or "")
            if "pass" in mqtt:   _cfg["mqtt_pass"]   = str(mqtt["pass"] or "")
            if "prefix" in mqtt: _cfg["mqtt_prefix"] = str(mqtt["prefix"] or "onvif")
        scan = data.get("scan") or {}
        if isinstance(scan, dict):
            if "subnet" in scan:
                _cfg["scan_subnet"] = str(scan["subnet"] or SCAN_SUBNET)
            if "concurrency" in scan:
                SCAN_CONCUR = int(scan["concurrency"])
            if "rescan_time_interval" in scan:
                _cfg["rescan_time_interval"] = scan["rescan_time_interval"]
            # scan.credentials is intentionally NOT read: the scan credential comes
            # from SCAN_USER/SCAN_PASSWORD (.env). Any legacy block is ignored.
        web = data.get("web") or {}
        if isinstance(web, dict):
            # web.password is intentionally NOT read: the login password comes from
            # GUI_PASSWORD (.env). A legacy hash here is ignored and stripped on save.
            # Static-asset cache-busting token; default "1" when absent (task 2.1a).
            _cfg["asset_version"] = str(web.get("asset_version", _cfg.get("asset_version", "1")))
            if "port" in web:
                WEB_PORT = int(web["port"])
            if "skip_login" in web:
                _cfg["web_skip_login"] = _coerce_bool(web["skip_login"])
        # Behaviour-tuning knobs — authoritative here, env vars are only the defaults.
        tuning = data.get("tuning") or {}
        if isinstance(tuning, dict):
            if "liveness_mode" in tuning:
                LIVENESS_MODE = str(tuning["liveness_mode"]).strip().lower()
            if "heartbeat_interval" in tuning:
                HEARTBEAT_INTERVAL = int(tuning["heartbeat_interval"])
            if "heartbeat_gap_factor" in tuning:
                HEARTBEAT_GAP_FACTOR = float(tuning["heartbeat_gap_factor"])
            if "rule_check_interval" in tuning:
                RULE_CHECK_INTERVAL = int(tuning["rule_check_interval"])
            if "keepalive_interval" in tuning:
                KEEPALIVE_INTERVAL = int(tuning["keepalive_interval"])
            if "save_interval" in tuning:
                SAVE_INTERVAL = int(tuning["save_interval"])
        # Serena fall-alarm bridge (authoritative over env; normalized below).
        serena = data.get("serena") or {}
        if isinstance(serena, dict):
            if "enabled" in serena:                   _cfg["serena_enabled"] = serena["enabled"]
            if "topic_prefix" in serena:              _cfg["serena_topic_prefix"] = str(serena["topic_prefix"] or "alexa")
            if "node_id" in serena:                   _cfg["serena_node_id"] = str(serena["node_id"] or "")
            if "command_template" in serena:          _cfg["serena_command_template"] = str(serena["command_template"] or "")
            if "announce_ready" in serena:            _cfg["serena_announce_ready"] = serena["announce_ready"]
            if "announce_template" in serena:         _cfg["serena_announce_template"] = str(serena["announce_template"] or "")
            if "announce_fault" in serena:            _cfg["serena_announce_fault"] = serena["announce_fault"]
            if "announce_fault_template" in serena:   _cfg["serena_announce_fault_template"] = str(serena["announce_fault_template"] or "")
            if "announce_fault_interval_s" in serena: _cfg["serena_announce_fault_interval_s"] = serena["announce_fault_interval_s"]
            if "announce_fault_grace_s" in serena:    _cfg["serena_announce_fault_grace_s"] = serena["announce_fault_grace_s"]
            if "startup_alarm_max_age_s" in serena:   _cfg["serena_startup_alarm_max_age_s"] = serena["startup_alarm_max_age_s"]
        print(f"[settings] caricato da {SETTINGS_FILE}: mqtt_host='{_cfg['mqtt_host']}' "
              f"port={_cfg['mqtt_port']} prefix={_cfg['mqtt_prefix']} "
              f"web_port={WEB_PORT} liveness={LIVENESS_MODE} N={HEARTBEAT_INTERVAL}", flush=True)

    # Recompute detection windows from the (possibly overridden) tuning values so
    # consumers reading config.DETECTION_EXPIRE at runtime see the effective value.
    DETECTION_EXPIRE = max(120, int(HEARTBEAT_GAP_FACTOR * HEARTBEAT_INTERVAL) + 60, KEEPALIVE_INTERVAL + 60)
    DETECTION_REPUBLISH = max(30, DETECTION_EXPIRE // 2)

    # Coerce/validate the (possibly YAML-overridden) serena_* values in place.
    _normalize_serena_config()

    # The web login password is set at module load from GUI_PASSWORD (.env); it is
    # never seeded into or read from settings.yaml.

def _save_settings_yaml():
    """Persiste la configurazione su SETTINGS_FILE (unico file, scrivibile dalla GUI).

    Parte dal documento caricato (`_settings_doc`) e aggiorna SOLO i blocchi gestiti
    dalla GUI (mqtt / scan / web), così il blocco `cameras` (e qualsiasi altra chiave)
    viene preservato e non azzerato da un salvataggio.

    Tenta una sostituzione atomica (tmp + os.replace); se il file è un bind-mount
    a singolo file di Docker (rename non consentito → OSError), ricade su una
    scrittura in-place. Così l'edit da GUI persiste sia in dev che in container."""
    import yaml
    doc = dict(_settings_doc)   # preserva cameras/ecc.
    doc["mqtt"] = {
        "host":   _cfg.get("mqtt_host", ""),
        "port":   int(_cfg.get("mqtt_port", 1883)),
        "user":   _cfg.get("mqtt_user", ""),
        "pass":   _cfg.get("mqtt_pass", ""),
        "prefix": _cfg.get("mqtt_prefix", "onvif"),
    }
    scan_block = dict(doc.get("scan") or {})
    scan_block["subnet"] = _cfg.get("scan_subnet", SCAN_SUBNET)
    # Round-trip the automatic-rescan interval so a GUI save never drops it (0 = off).
    scan_block["rescan_time_interval"] = int(_coerce_nonneg_float(
        _cfg.get("rescan_time_interval", 0), 0.0))
    # scan.credentials is env-sourced now — never write it, and strip any legacy key.
    scan_block.pop("credentials", None)
    doc["scan"] = scan_block
    web_block = dict(doc.get("web") or {})
    # web.password is env-sourced now — never write it, and strip any legacy hash.
    web_block.pop("password", None)
    # Round-trip the cache-busting token so a GUI save never drops it (task 2.1a).
    web_block["asset_version"] = _cfg.get("asset_version", "1")
    doc["web"] = web_block
    # cameras.credentials keeps only `port` — user/pass are env-sourced; strip any
    # legacy user/pass left over from a pre-.env settings.yaml.
    # `cameras.list` is written back VERBATIM from _settings_doc: a `hostname` entry
    # keeps its hostname and never gains the runtime-resolved `ip` (the resolved
    # address lives only in state._hostname_ips). The only mutations of that list go
    # through _config_add_camera / _config_remove_camera.
    cams_block = doc.get("cameras")
    if isinstance(cams_block, dict):
        cams_block = dict(cams_block)
        cams_cred = cams_block.get("credentials")
        if isinstance(cams_cred, dict):
            cams_cred = {"port": int(cams_cred.get("port", 80))}
            cams_block["credentials"] = cams_cred
        doc["cameras"] = cams_block
    # This header is re-emitted on every save and is therefore the ONLY comment that
    # survives one: yaml.safe_dump drops everything else. Say so here, so an operator
    # who loses their annotations knows why and where the documented copy lives.
    header = ("# settings.yaml — file di configurazione unico (modificabile dalla GUI).\n"
              "# Le password (telecamere / scan / login GUI) NON stanno qui: vivono in .env.\n"
              "# Ogni voce di 'cameras.list' ha un 'name' e UNO fra 'ip:' e 'hostname:'.\n"
              "# NOTA: l'app riscrive questo file e ne rimuove i commenti (non le chiavi).\n"
              "#       La copia commentata di riferimento è settings.yaml.example.\n")
    text = header + yaml.safe_dump(doc, default_flow_style=False, sort_keys=False, allow_unicode=True)
    d = os.path.dirname(SETTINGS_FILE) or "."
    tmp = os.path.join(d, ".settings.yaml.tmp")
    try:
        with open(tmp, "w") as f:
            f.write(text)
        os.replace(tmp, SETTINGS_FILE)   # atomico su fs normale
    except OSError:
        # Bind-mount a singolo file (Docker): os.replace non può rinominare sopra
        # il mount point → scrittura in-place.
        try:
            os.remove(tmp)
        except OSError:
            pass
        try:
            with open(SETTINGS_FILE, "w") as f:
                f.write(text)
        except Exception as e:
            print(f"[settings] errore scrittura in-place: {e}", flush=True)
    except Exception as e:
        print(f"[settings] errore scrittura: {e}", flush=True)
PULL_NS        = "http://www.onvif.org/ver10/events/wsdl/PullPointSubscription"
MAX_LOG_GLOBAL = 2000
MAX_LOG_CAM    = 100
RETRY_SLEEP    = 30
RENEW_EVERY    = 90
SAVE_INTERVAL  = int(os.getenv("SAVE_INTERVAL", "30"))
# Mapping topic ONVIF → nome allarme.
# Pattern case-insensitive sul topic string o sul valore di RuleName nel data.
# Dahua IPC-HDW8441-BV-3D pubblica fall detection come tns1:RuleEngine/... con
# RuleName=FallDetect (o simile); catturiamo qualsiasi variante.
FALL_TOPICS = [
    "falldetect", "fall_detect", "falldown", "fall_down",
    "falldetection", "fall_detection", "fallalarm", "fall_alarm",
    "PersonFall", "personfall",
]
_DEFAULT_CREDS = [
    {"user": "admin", "pass": "Admin123"},
]

# Placeholder password shipped in the golden settings.yaml. While ANY credential the
# app would authenticate with still equals this value, camera workers and the manual
# scan are SUPPRESSED: a repeated wrong-password auth burst trips the Dahua
# anti-intrusion lockout and would block the cameras. The operator replaces it with a
# real password (per deployment) to enable connections.
DEFAULT_PASSWORD_SENTINEL = "default_to_change"


def _is_placeholder_pw(pw) -> bool:
    return str(pw or "").strip() == DEFAULT_PASSWORD_SENTINEL


# ── secrets sourced ONLY from the environment (.env) ─────────────────────────────
# The three passwords no longer live in settings.yaml. They are read here (after
# load_dotenv at module top) and are the single source of truth:
#   * CAMERA_USER/CAMERA_PASSWORD — the common credential for the static workers.
#   * SCAN_USER/SCAN_PASSWORD      — the manual-scan credential (defaults to the
#                                    camera credential when unset).
#   * GUI_PASSWORD                 — the web login password (hashed in memory below).
# Passwords default to DEFAULT_PASSWORD_SENTINEL when unset, so a fresh install with
# no .env fails SAFE: the placeholder guard suppresses workers/scan and login uses
# a value the operator must deliberately replace.
CAMERA_USER     = os.getenv("CAMERA_USER", "admin")
CAMERA_PASSWORD = os.getenv("CAMERA_PASSWORD", DEFAULT_PASSWORD_SENTINEL)
SCAN_USER       = os.getenv("SCAN_USER") or CAMERA_USER
SCAN_PASSWORD   = os.getenv("SCAN_PASSWORD") or CAMERA_PASSWORD
GUI_PASSWORD    = os.getenv("GUI_PASSWORD", DEFAULT_PASSWORD_SENTINEL)
# Bypasses the /login gate entirely (every route behaves as already authenticated) —
# e.g. a LAN-only deployment behind its own reverse-proxy auth. Default false so a
# fresh install still requires GUI_PASSWORD. settings.yaml `web.skip_login` overrides
# this at load (see _load_settings_yaml).
GUI_SKIP_LOGIN  = _coerce_bool(os.getenv("GUI_SKIP_LOGIN", "false"))

# The manual-scan credential is a single env-sourced entry (no multi-credential list).
_cfg["cam_credentials"] = [{"user": SCAN_USER, "pass": SCAN_PASSWORD}]
# Web login password: hash GUI_PASSWORD in memory at load. Never read/written to
# settings.yaml; changing it means editing .env and restarting.
_cfg["web_password"] = _hash_password(GUI_PASSWORD)
_cfg["web_skip_login"] = GUI_SKIP_LOGIN


def _env_shadows_dotenv(var: str) -> bool:
    """True when `var` is declared in .env but the value that actually WON is a different
    one — i.e. the variable was already exported in the process environment and
    load_dotenv(override=False) let the export win, so the .env line is ignored.

    This is the failure mode behind "I changed the password in .env and nothing
    happened": a stale `export CAMERA_PASSWORD=default_to_change` in the shell that
    launches the service silently shadows the real value in the file. A variable
    exported with the SAME value as .env is not reported — it changes nothing."""
    declared = _DOTENV_DECLARED.get(var)
    if declared is None:
        return False   # .env says nothing about this variable — nothing to shadow
    actual = os.environ.get(var)
    if actual is None:
        return False   # nothing is set at all, so nothing can be shadowing
    return actual != declared


def _placeholder_pw_hint(var: str = "CAMERA_PASSWORD") -> str:
    """Operator-facing explanation of WHERE the placeholder value came from, so the
    advice matches reality. Telling someone to edit .env is actively misleading when
    .env is the thing being ignored."""
    if _env_shadows_dotenv(var):
        return (f"la variabile d'ambiente esportata {var} ha PRECEDENZA su .env (che "
                f"contiene un valore diverso, ignorato): esegui `unset {var}` nella shell "
                f"che avvia il servizio, oppure esportane il valore reale")
    if os.environ.get(var) is not None and var not in _DOTENV_DECLARED:
        return (f"{var} è esportata nell'ambiente con il valore placeholder e ha "
                f"precedenza su .env: esegui `unset {var}` e imposta il valore reale "
                f"in .env, oppure esportane uno reale")
    return f"imposta {var} in .env e riavvia"


def _placeholder_pw_var(kind: str = "cameras") -> str:
    """Which variable actually supplies the placeholder for a given gate — SCAN_PASSWORD
    falls back to CAMERA_PASSWORD when unset, so naming the wrong one sends the operator
    to edit a variable that has no effect."""
    if kind == "scan" and os.getenv("SCAN_PASSWORD"):
        return "SCAN_PASSWORD"
    return "CAMERA_PASSWORD"


def _password_placeholder_flags() -> dict:
    """{'cameras': bool, 'scan': bool, ...} — True where the placeholder password is
    still set. 'cameras' gates the persistent workers (ONVIF connect + CGI attach + rule
    check); 'scan' gates the manual subnet scan (which also tries the common cred) and
    the periodic hostname-resolution sweep. Evaluates the .env-sourced camera/scan
    passwords (an unset password defaults to the sentinel, so it reads as
    not-yet-configured).

    Additive keys (existing consumers ignore them): `var` names the variable actually
    responsible, `hint` explains where its value came from, and `env_shadowed` is True
    when an exported variable is overriding a different value in .env."""
    cameras = _is_placeholder_pw(CAMERA_PASSWORD)
    scan = cameras or _is_placeholder_pw(SCAN_PASSWORD)
    var = _placeholder_pw_var("cameras" if cameras else "scan")
    return {
        "cameras":      cameras,
        "scan":         scan,
        "var":          var,
        "hint":         _placeholder_pw_hint(var),
        "env_shadowed": _env_shadows_dotenv(var),
    }


def _get_cred_fallbacks() -> list[tuple[str, str]]:
    """Credential list for the MANUAL subnet scanner only (unknown-device discovery).

    The persistent static workers use the single common credential directly; the
    scanner tries it FIRST (so a discovered kit camera gets the working password
    and can be renamed), then any extra scan credentials / the built-in default.
    """
    creds: list[tuple[str, str]] = []
    cu, cp = _COMMON_CRED.get("user", ""), _COMMON_CRED.get("pass", "")
    if cu and cp:   # skip an empty-password common cred (pointless failed auth)
        creds.append((cu, cp))
    for c in (_cfg.get("cam_credentials") or _DEFAULT_CREDS):
        t = (c["user"], c["pass"])
        if t not in creds:
            creds.append(t)
    return creds
# ── static camera config (blocco `cameras` di settings.yaml) ────────────────────
# Single set of common credentials applied to every statically-configured camera.
# user/pass come from the environment (.env); only `port` is read from settings.yaml.
_COMMON_CRED = {"user": CAMERA_USER, "pass": CAMERA_PASSWORD, "port": 80}
_static_cameras: list[dict] = []   # [{"ip"|"hostname":..., "name":...}]

def _load_static_cameras() -> tuple[dict, list[dict]]:
    """Legge il blocco `cameras` di settings.yaml (già caricato in `_settings_doc`)
    → (common_credentials, [{ip,name} | {hostname,name}, ...]).

        cameras:
          credentials: {port}   # only the port; user/pass come from .env
          list:
            - {ip, name}        # static address — behaves exactly as before
            - {hostname, name}  # ONVIF device hostname — resolved to an IP at runtime

    Ogni voce richiede `name` ed ESATTAMENTE UNA fra `ip` e `hostname` (nessuna delle
    due, o entrambe → voce ignorata con diagnostica). `hostname` NON è un indirizzo:
    non viene mai trattato come IP, viene solo trasportato fino al risolutore
    (worker._hostname_resolve_loop), che ne ricava l'IP corrente via scan ONVIF.

    Ritorna lista vuota (e logga un errore chiaro) se il blocco manca / è malformato
    o su un name/ip/hostname duplicato — non fa mai fallback allo scan della subnet.
    """
    block = _settings_doc.get("cameras")
    if not isinstance(block, dict):
        print("[cameras] blocco 'cameras' assente/non valido in settings.yaml — "
              "nessuna telecamera configurata", flush=True)
        return dict(_COMMON_CRED), []

    # user/pass are env-sourced (CAMERA_USER/CAMERA_PASSWORD); only `port` is taken
    # from settings.yaml (not a secret). Any user/pass still present in the file is
    # ignored here and stripped on the next save.
    cred_in = block.get("credentials") or {}
    cred = {
        "user": CAMERA_USER,
        "pass": CAMERA_PASSWORD,
        "port": int(cred_in.get("port", 80)),
    }

    raw = block.get("list")
    if raw is None:
        print("[cameras] chiave 'cameras.list' assente in settings.yaml — nessuna telecamera", flush=True)
        return cred, []
    if not isinstance(raw, list):
        print("[cameras] 'cameras.list' deve essere una lista in settings.yaml — nessuna telecamera", flush=True)
        return cred, []
    if len(raw) == 0:
        print("[cameras] lista telecamere vuota in settings.yaml — nessun worker avviato", flush=True)
        return cred, []

    # Validate: every entry needs `name` + exactly one of ip/hostname; names, ips and
    # hostnames must each be unique (fail loud — drop BOTH duplicates).
    seen_ip: dict[str, int] = {}
    seen_hostname: dict[str, int] = {}
    seen_name: dict[str, int] = {}
    valid: list[dict] = []
    for idx, entry in enumerate(raw):
        if not isinstance(entry, dict):
            print(f"[cameras] voce #{idx} non è un mapping — ignorata", flush=True)
            continue
        ip       = str(entry.get("ip", "")).strip()
        hostname = str(entry.get("hostname", "")).strip()
        name     = str(entry.get("name", "")).strip()
        if not name:
            print(f"[cameras] voce #{idx} manca 'name' — ignorata", flush=True)
            continue
        if ip and hostname:
            print(f"[cameras] voce #{idx} ('{name}') ha sia 'ip' che 'hostname' — indica solo "
                  f"uno dei due (ip statico OPPURE hostname ONVIF) — ignorata", flush=True)
            continue
        if not ip and not hostname:
            print(f"[cameras] voce #{idx} ('{name}') manca sia 'ip' che 'hostname' — ignorata", flush=True)
            continue
        if ip and ip in seen_ip:
            print(f"[cameras] ERRORE config: ip duplicato '{ip}' (voci #{seen_ip[ip]} e #{idx}) — "
                  f"nessuna delle due avviata", flush=True)
            valid = [c for c in valid if c.get("ip") != ip]
            seen_ip[ip] = -1   # poison: blocca eventuali ulteriori duplicati
            continue
        hkey = _hostname_key(hostname)
        if hostname and hkey in seen_hostname:
            print(f"[cameras] ERRORE config: hostname duplicato '{hostname}' (voci "
                  f"#{seen_hostname[hkey]} e #{idx}) — nessuna delle due avviata", flush=True)
            valid = [c for c in valid if _hostname_key(c.get("hostname")) != hkey]
            seen_hostname[hkey] = -1
            continue
        if name in seen_name:
            print(f"[cameras] ERRORE config: name duplicato '{name}' (voci #{seen_name[name]} e #{idx}) — "
                  f"nessuna delle due avviata", flush=True)
            valid = [c for c in valid if c["name"] != name]
            seen_name[name] = -1
            continue
        if ip:
            seen_ip[ip] = idx
        else:
            seen_hostname[hkey] = idx
        seen_name[name] = idx
        # The resolved IP of a hostname entry is attached at RUNTIME (state._hostname_ips),
        # never here and never in settings.yaml — the hostname stays authoritative.
        valid.append({"ip": ip, "name": name} if ip else {"hostname": hostname, "name": name})

    # Serena bridge naming warnings (hand-edited YAML bypasses the web validation).
    # Non-fatal: the bridge simply derives an awkward/ambiguous voice name until renamed.
    seen_voice: dict[str, str] = {}
    for c in valid:
        nm = c["name"]
        if _name_has_reserved_word(nm):
            print(f"[serena] ATTENZIONE: il nome telecamera '{nm}' contiene 'camera' — "
                  f"il bridge vocale preferisce un nome di stanza (es. 'cucina')", flush=True)
        voice = _serena_voice_name(nm)
        if voice in seen_voice:
            print(f"[serena] ATTENZIONE: i nomi '{seen_voice[voice]}' e '{nm}' normalizzano "
                  f"allo stesso nome vocale '{voice}' — Serena non li distingue", flush=True)
        else:
            seen_voice[voice] = nm

    return cred, valid
ALARM_KEEPALIVE = 60  # secondi tra le ripubblicazioni periodiche dello stato allarme
# ── add/remove a camera in the settings.yaml `cameras` block ─────────────────────
def _config_name_conflict(ip: str, name: str, hostname: Optional[str] = None) -> Optional[str]:
    """If another saved camera already uses `name`, return that camera's label (ip, or
    hostname when it has no ip); otherwise None. Guards the unique MQTT/HA identity.
    `hostname` identifies the caller's own entry when it is hostname-configured."""
    cams = _settings_doc.get("cameras")
    if not isinstance(cams, dict):
        return None
    lst = cams.get("list")
    if not isinstance(lst, list):
        return None
    for e in lst:
        if (isinstance(e, dict) and e.get("name") == name
                and not _entry_matches(e, ip, hostname)):
            return _entry_label(e)
    return None


def _config_hostname_conflict(name: str, own_hostname: Optional[str] = None) -> Optional[str]:
    """If renaming a camera to `name` would make it answer to ANOTHER entry's configured
    `hostname`, return that entry's label; else None.

    A rename sets the camera's ONVIF device hostname — the very value the resolution
    sweep matches on — so renaming camera A to camera B's configured hostname would
    make A answer B's resolution (and, with two devices then reporting it, make B
    permanently ambiguous). Compared trimmed + case-insensitively, exactly like the
    resolver's match. `own_hostname` is the renamed camera's own hostname, which is
    always allowed."""
    cams = _settings_doc.get("cameras")
    if not isinstance(cams, dict):
        return None
    lst = cams.get("list")
    if not isinstance(lst, list):
        return None
    target = _hostname_key(name)
    if not target:
        return None
    own = _hostname_key(own_hostname)
    for e in lst:
        if not isinstance(e, dict):
            continue
        eh = _hostname_key(e.get("hostname"))
        if not eh or eh == own:
            continue
        if eh == target:
            return _entry_label(e)
    return None


def _configured_camera_names() -> set[str]:
    """Set of camera names currently declared in settings.yaml `cameras.list` (read
    from the already-loaded `_settings_doc`). Empty when the block is absent/malformed.
    Used to prune orphaned persisted alarms at load (a renamed/removed camera)."""
    names: set[str] = set()
    cams = _settings_doc.get("cameras")
    if not isinstance(cams, dict):
        return names
    lst = cams.get("list")
    if not isinstance(lst, list):
        return names
    for e in lst:
        if isinstance(e, dict):
            nm = str(e.get("name", "")).strip()
            if nm:
                names.add(nm)
    return names


def _config_has_ip_entry(ip: str) -> bool:
    """True when `cameras.list` already holds a static-`ip` entry for `ip`. Lets the save
    path leave an existing static entry static instead of silently converting its address
    form under the operator."""
    cams = _settings_doc.get("cameras")
    if not isinstance(cams, dict):
        return False
    lst = cams.get("list")
    if not isinstance(lst, list):
        return False
    return any(_entry_matches(e, ip) for e in lst)


def _config_add_camera(ip: str, name: str, port: int, hostname: Optional[str] = None,
                       set_hostname: Optional[str] = None,
                       append_hostname: Optional[str] = None):
    """Add (or update the name of) a camera in `_settings_doc['cameras']` and
    persist settings.yaml. Returns (ok, message). Credentials are env-sourced
    (.env), so only `port` is taken here.

    `hostname` (the caller's runtime IP → configured hostname lookup) locates an
    existing hostname-configured entry, which is UPDATED IN PLACE — a hostname entry
    is never matched by IP and must never be appended to as a second `{ip, name}` row
    (that would mean two entries for one physical camera, a resolved IP persisted
    against the never-persist rule, and a duplicate-name rejection dropping both at
    the next load). `set_hostname`, when given, rewrites that entry's `hostname` in
    the same save — the rename path uses it because renaming sets the device's ONVIF
    hostname, so the discovery key changes with the name. A static-`ip` entry never
    gains a `hostname` key.

    `append_hostname` applies to a camera with NO existing entry: the new row is written
    as `{hostname, name}` instead of `{ip, name}`, so the periodic resolution keeps its
    address current across DHCP lease changes. The hostname must be unused by any other
    entry — a duplicate is refused HERE, because `_load_static_cameras` treats duplicate
    hostnames as a config error and drops BOTH entries, which would silently take two
    working cameras offline at the next restart. Factory-default hostnames (e.g. Dahua's
    `IPC`) are identical across cameras of a model, so this is the common case: rename
    one of the two from the dashboard first, which gives it a distinct ONVIF hostname.
    """
    cams = _settings_doc.get("cameras")
    if not isinstance(cams, dict):
        cams = {}
    creds = cams.get("credentials")
    # Only `port` lives in settings.yaml; user/pass are env-sourced (.env), never written.
    if not isinstance(creds, dict) or "port" not in creds:
        cams["credentials"] = {"port": int(port)}
    lst = cams.get("list")
    if not isinstance(lst, list):
        lst = []
    # A name must be unique across entries (it is the MQTT/HA identity).
    for e in lst:
        if (isinstance(e, dict) and e.get("name") == name
                and not _entry_matches(e, ip, hostname)):
            return False, f"Nome '{name}' già usato dalla telecamera {_entry_label(e)}"
    # Serena bridge naming rules (chokepoint for every caller — task 3b.3):
    # no reserved word 'camera', and no normalized-voice-name collision.
    if _name_has_reserved_word(name):
        return False, "Il nome non può contenere 'camera' (usa il nome della stanza, es. 'cucina')"
    coll = _name_voice_collision(ip, name, hostname)
    if coll:
        return False, (f"Il nome '{name}' coincide (dopo normalizzazione) con "
                       f"la telecamera {coll}")
    updated = False
    for e in lst:
        if _entry_matches(e, ip, hostname):
            e["name"] = name
            if hostname and set_hostname:
                e["hostname"] = str(set_hostname).strip()
            updated = True
            break
    if not updated:
        if hostname:
            # The caller resolved this IP to a configured hostname, so an entry MUST
            # exist. Appending would create the duplicate described above — fail loud.
            return False, (f"Nessuna voce con hostname '{hostname}' in settings.yaml — "
                           f"configurazione non aggiornata")
        if append_hostname:
            hkey = _hostname_key(append_hostname)
            for e in lst:
                if isinstance(e, dict) and _hostname_key(e.get("hostname")) == hkey:
                    # Name the OTHER camera by its `name`: _entry_label would echo the
                    # hostname already quoted in this message, which tells the operator
                    # nothing about which camera to go and rename.
                    other = str(e.get("name", "") or "").strip() or _entry_label(e)
                    return False, (
                        f"L'hostname ONVIF '{append_hostname}' è già usato dalla telecamera "
                        f"'{other}': due voci con lo stesso hostname vengono scartate "
                        f"ENTRAMBE al prossimo avvio, e la risoluzione non saprebbe quale "
                        f"device è quale. Rinomina prima una delle due dalla dashboard (la "
                        f"rinomina imposta l'hostname ONVIF sul device)")
            lst.append({"hostname": str(append_hostname).strip(), "name": name})
        else:
            lst.append({"ip": ip, "name": name})
    cams["list"] = lst
    _settings_doc["cameras"] = cams
    _save_settings_yaml()
    return True, ("aggiornata" if updated else "aggiunta")


def _config_remove_camera(ip: str, hostname: Optional[str] = None) -> bool:
    """Remove a camera from the settings.yaml `cameras.list`. Returns True if an entry
    was removed. `hostname` (resolved from the runtime IP by the caller) selects a
    hostname-configured entry — matching it by IP removes nothing, and since the ENTRY
    is what drives resolution, the periodic sweep would respawn the camera within one
    interval (it would come back by itself, with no restart)."""
    cams = _settings_doc.get("cameras")
    if not isinstance(cams, dict):
        return False
    lst = cams.get("list")
    if not isinstance(lst, list):
        return False
    kept = [e for e in lst if not _entry_matches(e, ip, hostname)]
    removed = len(kept) != len(lst)
    cams["list"] = kept
    _settings_doc["cameras"] = cams
    if removed:
        _save_settings_yaml()
    return removed


# ── in-memory static list upkeep (the list the runtime loops iterate) ────────────
# `_static_cameras` is loaded once at boot; the runtime loops (hostname resolution,
# the Serena fault driver) iterate IT, not `_settings_doc`. A GUI rename/removal that
# only touched settings.yaml would leave those loops acting on stale entries — a
# removed hostname camera would be resolved and respawned, and a renamed one would be
# resolved by its OLD hostname. These two helpers keep the list in step.
def _update_static_camera_entry(ip: str, name: str, hostname: Optional[str] = None,
                                set_hostname: Optional[str] = None):
    """Mirror a persisted rename into `_static_cameras`."""
    for c in _static_cameras:
        if _entry_matches(c, ip, hostname):
            c["name"] = name
            if hostname and set_hostname:
                c["hostname"] = str(set_hostname).strip()
            return True
    return False


def _register_static_camera(ip: str, name: str, hostname: Optional[str] = None) -> bool:
    """Mirror a persisted save into `_static_cameras`, adding the entry when it is new.
    Without this a camera saved by hostname is invisible to the resolution loop until a
    restart, so its IP would not be tracked until then. True when a new entry was added."""
    for c in _static_cameras:
        if _entry_matches(c, ip, hostname):
            c["name"] = name
            return False
    _static_cameras.append({"hostname": str(hostname).strip(), "name": name} if hostname
                           else {"ip": ip, "name": name})
    return True


def _drop_static_camera_entry(ip: str, hostname: Optional[str] = None):
    """Mirror a persisted removal into `_static_cameras`."""
    global _static_cameras
    kept = [c for c in _static_cameras if not _entry_matches(c, ip, hostname)]
    dropped = len(kept) != len(_static_cameras)
    _static_cameras = kept
    return dropped
