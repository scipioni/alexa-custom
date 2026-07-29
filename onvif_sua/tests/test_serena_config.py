"""Tasks 5.1a / 5.1c (config layer): boolean/numeric coercion, template validation,
voice-name normalization, reserved-word + voice-collision validators, and the
config-load warnings for hand-edited YAML."""
import pytest

from onvif_sua import config


# ── 5.1a: boolean coercion ───────────────────────────────────────────────────────
@pytest.mark.parametrize("val", ["false", "0", "no", "off", "", "FALSE", "random", "  "])
def test_coerce_bool_falsey(val):
    assert config._coerce_bool(val) is False


@pytest.mark.parametrize("val", ["true", "1", "yes", "on", "TRUE", "Yes", "On"])
def test_coerce_bool_truthy(val):
    assert config._coerce_bool(val) is True


def test_coerce_bool_native():
    assert config._coerce_bool(True) is True
    assert config._coerce_bool(False) is False


# ── 5.1a: numeric coercion + clamping ─────────────────────────────────────────────
def test_coerce_nonneg_float_fallback_and_clamp():
    assert config._coerce_nonneg_float("abc", 300.0) == 300.0
    assert config._coerce_nonneg_float(None, 60.0) == 60.0
    assert config._coerce_nonneg_float("-5", 60.0) == 0.0   # negative clamps to 0
    assert config._coerce_nonneg_float("45", 300.0) == 45.0


def test_normalize_interval_floor(restore_globals, capsys):
    config._cfg["serena_announce_fault_interval_s"] = "5"   # below the 30 s floor
    config._normalize_serena_config()
    assert config._cfg["serena_announce_fault_interval_s"] == 30.0
    assert "sotto il minimo" in capsys.readouterr().out


def test_normalize_grace_zero_preserved_and_warns(restore_globals, capsys):
    config._cfg["serena_announce_fault_grace_s"] = "0"
    config._normalize_serena_config()
    assert config._cfg["serena_announce_fault_grace_s"] == 0.0   # NOT clamped
    assert "soppressione" in capsys.readouterr().out            # warning printed


def test_normalize_nonnumeric_falls_back(restore_globals):
    config._cfg["serena_announce_fault_interval_s"] = "not-a-number"
    config._cfg["serena_announce_fault_grace_s"] = "xx"
    config._cfg["serena_startup_alarm_max_age_s"] = "yy"
    config._normalize_serena_config()
    assert config._cfg["serena_announce_fault_interval_s"] == 300.0
    assert config._cfg["serena_announce_fault_grace_s"] == 60.0
    assert config._cfg["serena_startup_alarm_max_age_s"] == 300.0


# ── 5.1a: template validation ─────────────────────────────────────────────────────
def test_valid_cam_name_template():
    assert config._valid_cam_name_template("caduta {cam_name}") is True
    assert config._valid_cam_name_template("solo testo") is True
    assert config._valid_cam_name_template("caduta {room}") is False       # unknown placeholder
    assert config._valid_cam_name_template("caduta {") is False            # malformed braces
    assert config._valid_cam_name_template("caduta {}") is False           # positional


def test_invalid_template_falls_back_to_default(restore_globals, capsys):
    config._cfg["serena_command_template"] = "caduta {room}"
    config._cfg["serena_announce_template"] = "attivo {"
    config._normalize_serena_config()
    assert config._cfg["serena_command_template"] == "caduta_{cam_name}"
    assert config._cfg["serena_announce_template"] == "sensore uomo a terra {cam_name} attivo"
    assert "non valido" in capsys.readouterr().out


# ── 5.1c: voice-name normalization ────────────────────────────────────────────────
@pytest.mark.parametrize("raw,expected", [
    ("Salotto", "salotto"),
    ("salotto-1", "salotto 1"),
    ("cucina_piano_terra", "cucina piano terra"),
    ("cucina", "cucina"),
    ("  Doppio   Spazio ", "doppio spazio"),
])
def test_serena_voice_name(raw, expected):
    assert config._serena_voice_name(raw) == expected


def test_serena_voice_name_idempotent():
    once = config._serena_voice_name("salotto-1")
    assert config._serena_voice_name(once) == once


def test_serena_voice_name_all_separators_falls_back(capsys):
    # all-separator name normalizes to empty → falls back to the raw (never empty)
    out = config._serena_voice_name("___")
    assert out == "___"
    assert "normalizza a vuoto" in capsys.readouterr().out


# ── 5.1d: trigger-name slug (space-free fall command) ─────────────────────────────
@pytest.mark.parametrize("raw,expected", [
    ("Salotto", "salotto"),
    ("salotto-1", "salotto_1"),
    ("cucina_piano_terra", "cucina_piano_terra"),
    ("  Doppio   Spazio ", "doppio_spazio"),
])
def test_serena_trigger_name(raw, expected):
    assert config._serena_trigger_name(raw) == expected


def test_serena_trigger_name_never_contains_space():
    # The whole point: the rendered command must stay a single unutterable token,
    # so the SOS trigger can only ever arrive over MQTT and never via the STT matcher.
    for raw in ("salotto-1", "cucina piano terra", "Doppio  Spazio"):
        assert " " not in config._serena_trigger_name(raw)


# ── 5.1c: reserved-word validator ─────────────────────────────────────────────────
@pytest.mark.parametrize("name", ["camera0", "Camera 0", "telecamera-2", "MyCamera"])
def test_reserved_word_rejected(name):
    assert config._name_has_reserved_word(name) is True


@pytest.mark.parametrize("name", ["cucina", "salotto", "bagno-1"])
def test_reserved_word_accepted(name):
    assert config._name_has_reserved_word(name) is False


# ── 5.1c: voice-collision validator ───────────────────────────────────────────────
def test_name_voice_collision(restore_globals):
    config._settings_doc.clear()
    config._settings_doc["cameras"] = {"list": [
        {"ip": "10.0.0.1", "name": "salotto-1"},
        {"ip": "10.0.0.2", "name": "cucina"},
    ]}
    # saving 10.0.0.2 as 'salotto_1' collides (both normalize to 'salotto 1')
    assert config._name_voice_collision("10.0.0.2", "salotto_1") == "10.0.0.1"
    # a fresh distinct name does not collide
    assert config._name_voice_collision("10.0.0.2", "bagno") is None
    # renaming the SAME camera to its own normalized form is not a self-collision
    assert config._name_voice_collision("10.0.0.1", "salotto 1") is None
    config._settings_doc.clear()


# ── 5.1c: config-load warnings for hand-edited YAML ───────────────────────────────
def test_config_load_warns_reserved_and_collision(restore_globals, capsys):
    config._settings_doc.clear()
    config._settings_doc["cameras"] = {
        "credentials": {"port": 80},
        "list": [
            {"ip": "10.0.0.1", "name": "camera0"},     # reserved word
            {"ip": "10.0.0.2", "name": "salotto-1"},
            {"ip": "10.0.0.3", "name": "salotto_1"},   # collides with salotto-1
        ],
    }
    config._load_static_cameras()
    out = capsys.readouterr().out
    assert "contiene 'camera'" in out
    assert "stesso nome vocale" in out
    config._settings_doc.clear()


def test_config_add_camera_rejects_reserved_and_collision(restore_globals):
    config._settings_doc.clear()
    config._settings_doc["cameras"] = {"credentials": {"port": 80}, "list": [
        {"ip": "10.0.0.1", "name": "salotto-1"},
    ]}
    ok, msg = config._config_add_camera("10.0.0.9", "camera-test", 80)
    assert ok is False and "camera" in msg.lower()
    ok, msg = config._config_add_camera("10.0.0.9", "salotto_1", 80)
    assert ok is False and "normalizzazione" in msg
    config._settings_doc.clear()
