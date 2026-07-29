"""The placeholder-password guard must name WHERE the value came from.

`load_dotenv(override=False)` means a variable already exported in the process
environment WINS over `.env`, so an operator who edits `.env` sees no change and the
old advice ("cambia CAMERA_PASSWORD in .env e riavvia") pointed at the one file that
was being ignored."""
import pytest

from onvif_sua import config


@pytest.fixture
def dotenv_declares(monkeypatch):
    """Control both sides of the precedence: what `.env` declares and what actually
    won (os.environ)."""

    def _setup(declared: dict, environ: dict):
        monkeypatch.setattr(config, "_DOTENV_DECLARED", dict(declared))
        for k in ("CAMERA_PASSWORD", "SCAN_PASSWORD"):
            monkeypatch.delenv(k, raising=False)
        for k, v in environ.items():
            monkeypatch.setenv(k, v)

    return _setup


# ── _env_shadows_dotenv ───────────────────────────────────────────────────────────
def test_export_with_a_different_value_is_reported_as_shadowing(dotenv_declares):
    dotenv_declares({"CAMERA_PASSWORD": "vera-password"},
                    {"CAMERA_PASSWORD": config.DEFAULT_PASSWORD_SENTINEL})
    assert config._env_shadows_dotenv("CAMERA_PASSWORD") is True


def test_export_with_the_same_value_is_not_reported(dotenv_declares):
    """Exporting the same value changes nothing — reporting it would be noise."""
    dotenv_declares({"CAMERA_PASSWORD": "vera-password"},
                    {"CAMERA_PASSWORD": "vera-password"})
    assert config._env_shadows_dotenv("CAMERA_PASSWORD") is False


def test_variable_absent_from_dotenv_is_not_shadowing(dotenv_declares):
    dotenv_declares({}, {"CAMERA_PASSWORD": config.DEFAULT_PASSWORD_SENTINEL})
    assert config._env_shadows_dotenv("CAMERA_PASSWORD") is False


def test_no_export_is_not_shadowing(dotenv_declares):
    """With no pre-existing export, load_dotenv leaves the .env value in os.environ —
    the two agree and nothing is shadowed."""
    dotenv_declares({"CAMERA_PASSWORD": "vera-password"},
                    {"CAMERA_PASSWORD": "vera-password"})
    assert config._env_shadows_dotenv("CAMERA_PASSWORD") is False


def test_nothing_set_at_all_is_not_shadowing(dotenv_declares):
    """Defensive: called before load_dotenv (or with a stream-based load), the variable
    may be absent from os.environ entirely. Nothing set → nothing shadowed."""
    dotenv_declares({"CAMERA_PASSWORD": "vera-password"}, {})
    assert config._env_shadows_dotenv("CAMERA_PASSWORD") is False


# ── _placeholder_pw_hint: the advice must match the actual source ─────────────────
def test_hint_tells_the_operator_to_unset_when_env_shadows_dotenv(dotenv_declares):
    dotenv_declares({"CAMERA_PASSWORD": "vera-password"},
                    {"CAMERA_PASSWORD": config.DEFAULT_PASSWORD_SENTINEL})
    hint = config._placeholder_pw_hint("CAMERA_PASSWORD")
    assert "unset CAMERA_PASSWORD" in hint
    assert "PRECEDENZA" in hint
    assert "ignorato" in hint


def test_hint_for_an_export_not_declared_in_dotenv_also_says_unset(dotenv_declares):
    dotenv_declares({}, {"CAMERA_PASSWORD": config.DEFAULT_PASSWORD_SENTINEL})
    assert "unset CAMERA_PASSWORD" in config._placeholder_pw_hint("CAMERA_PASSWORD")


def test_hint_points_at_dotenv_when_dotenv_really_holds_the_placeholder(dotenv_declares):
    dotenv_declares({"CAMERA_PASSWORD": config.DEFAULT_PASSWORD_SENTINEL},
                    {"CAMERA_PASSWORD": config.DEFAULT_PASSWORD_SENTINEL})
    hint = config._placeholder_pw_hint("CAMERA_PASSWORD")
    assert hint == "imposta CAMERA_PASSWORD in .env e riavvia"


# ── _placeholder_pw_var: name the variable that actually supplies the value ────────
def test_scan_var_falls_back_to_camera_password_when_scan_password_is_unset(dotenv_declares):
    dotenv_declares({}, {})
    assert config._placeholder_pw_var("scan") == "CAMERA_PASSWORD"


def test_scan_var_is_scan_password_when_it_is_set(dotenv_declares):
    dotenv_declares({}, {"SCAN_PASSWORD": config.DEFAULT_PASSWORD_SENTINEL})
    assert config._placeholder_pw_var("scan") == "SCAN_PASSWORD"


def test_cameras_var_is_always_camera_password(dotenv_declares):
    dotenv_declares({}, {"SCAN_PASSWORD": "x"})
    assert config._placeholder_pw_var("cameras") == "CAMERA_PASSWORD"


# ── _password_placeholder_flags keeps its existing shape and adds the diagnosis ────
def test_flags_keep_the_two_original_keys(monkeypatch, dotenv_declares):
    dotenv_declares({}, {})
    monkeypatch.setattr(config, "CAMERA_PASSWORD", config.DEFAULT_PASSWORD_SENTINEL)
    monkeypatch.setattr(config, "SCAN_PASSWORD", "reale")
    flags = config._password_placeholder_flags()
    assert flags["cameras"] is True
    assert flags["scan"] is True          # cameras gates scan too, as before


def test_flags_carry_the_hint_and_shadow_flag(monkeypatch, dotenv_declares):
    dotenv_declares({"CAMERA_PASSWORD": "vera-password"},
                    {"CAMERA_PASSWORD": config.DEFAULT_PASSWORD_SENTINEL})
    monkeypatch.setattr(config, "CAMERA_PASSWORD", config.DEFAULT_PASSWORD_SENTINEL)
    monkeypatch.setattr(config, "SCAN_PASSWORD", config.DEFAULT_PASSWORD_SENTINEL)
    flags = config._password_placeholder_flags()
    assert flags["var"] == "CAMERA_PASSWORD"
    assert flags["env_shadowed"] is True
    assert "unset CAMERA_PASSWORD" in flags["hint"]


def test_flags_report_no_placeholder_when_a_real_password_is_set(monkeypatch, dotenv_declares):
    dotenv_declares({"CAMERA_PASSWORD": "reale"}, {"CAMERA_PASSWORD": "reale"})
    monkeypatch.setattr(config, "CAMERA_PASSWORD", "reale")
    monkeypatch.setattr(config, "SCAN_PASSWORD", "reale")
    flags = config._password_placeholder_flags()
    assert flags["cameras"] is False and flags["scan"] is False
    assert flags["env_shadowed"] is False
