"""Tests for the web config-editor round-trip logic.

These guard the bugs fixed in the correctness review: the lossy shallow merge
that wiped nested stt.stage1 keys, and action-file triggers leaking into
config.yaml (where they were re-merged and duplicated on the next load).
"""

from __future__ import annotations

import pytest

from alexa_custom.web import WebServer


@pytest.fixture
def server():
    # __init__ only reads dashboard.html and sets attributes — no network/IO loop.
    return WebServer()


class TestDeepUpdateRaw:
    def test_preserves_unrelated_nested_keys(self, server):
        """A partial stt.stage1 update must not drop sibling keys on disk."""
        raw = {
            "stt": {
                "stage1": {
                    "backend": "vosk",
                    "confidence": 0.65,
                    "rms_threshold": 0.02,
                    "model_path": "models/it",
                    "vad_silence_ms": 500,
                    "vosk_grammar": False,
                }
            }
        }
        updates = {
            "stt": {
                "stage1": {"backend": "vosk", "confidence": 0.8, "rms_threshold": 0.03}
            }
        }

        server._deep_update_raw(raw, updates)

        stage1 = raw["stt"]["stage1"]
        # Updated leaf keys take the new value...
        assert stage1["confidence"] == 0.8
        assert stage1["rms_threshold"] == 0.03
        # ...and keys the editor never serializes survive.
        assert stage1["model_path"] == "models/it"
        assert stage1["vad_silence_ms"] == 500
        assert stage1["vosk_grammar"] is False

    def test_overwrites_scalar_and_list_keys(self, server):
        raw = {"wake_words": [{"word": "old"}], "command_timeout": 3.0}
        server._deep_update_raw(
            raw, {"wake_words": [{"word": "new"}], "command_timeout": 5.0}
        )
        assert raw["wake_words"] == [{"word": "new"}]
        assert raw["command_timeout"] == 5.0

    def test_adds_missing_keys(self, server):
        raw = {}
        server._deep_update_raw(raw, {"audio": {"output_volume": 0.4}})
        assert raw == {"audio": {"output_volume": 0.4}}


class TestStripActionDerived:
    def test_removes_global_triggers(self, server):
        payload = {"wake_words": [], "global_triggers": [{"phrase": "x"}]}
        out = server._strip_action_derived(payload)
        assert "global_triggers" not in out

    def test_removes_per_group_triggers(self, server):
        payload = {
            "wake_words": [
                {
                    "word": "galileo",
                    "aliases": ["g"],
                    "triggers": [{"phrase": "chiama"}],
                }
            ]
        }
        out = server._strip_action_derived(payload)
        assert "triggers" not in out["wake_words"][0]
        # editor-owned fields are kept
        assert out["wake_words"][0]["word"] == "galileo"
        assert out["wake_words"][0]["aliases"] == ["g"]

    def test_does_not_mutate_input(self, server):
        payload = {
            "wake_words": [{"word": "g", "triggers": [1]}],
            "global_triggers": [1],
        }
        server._strip_action_derived(payload)
        # original still has the action-derived keys
        assert "triggers" in payload["wake_words"][0]
        assert "global_triggers" in payload


class TestSerializeMergeRoundTrip:
    def test_editor_save_preserves_disk_stage1_keys(self, server, tmp_path):
        """End-to-end of the save path: a full on-disk config + an editor payload
        that only touches a few stage1 fields must not lose the rest."""
        raw = {
            "wake_words": [{"word": "galileo"}],
            "stt": {
                "stage1": {
                    "backend": "vosk",
                    "confidence": 0.65,
                    "rms_threshold": 0.02,
                    "model_path": "models/it",
                    "min_speech_ms": 300,
                }
            },
        }
        editor_payload = {
            "stt": {
                "stage1": {"backend": "vosk", "confidence": 0.9, "rms_threshold": 0.05}
            },
            "global_triggers": [{"phrase": "leaked"}],
            "wake_words": [{"word": "galileo", "triggers": [{"phrase": "leaked"}]}],
        }

        cleaned = server._strip_action_derived(editor_payload)
        server._deep_update_raw(raw, cleaned)

        assert raw["stt"]["stage1"]["confidence"] == 0.9
        assert raw["stt"]["stage1"]["model_path"] == "models/it"
        assert raw["stt"]["stage1"]["min_speech_ms"] == 300
        # action-derived data never reaches disk
        assert "global_triggers" not in raw
        assert "triggers" not in raw["wake_words"][0]


class TestValidateConfig:
    def test_rejects_non_dict(self, server):
        ok, _ = server._validate_config(["not", "a", "dict"])
        assert ok is False

    def test_rejects_empty_wake_word(self, server):
        ok, _ = server._validate_config({"wake_words": [{"word": ""}]})
        assert ok is False

    def test_accepts_minimal_valid(self, server):
        ok, _ = server._validate_config({"wake_words": [{"word": "galileo"}]})
        assert ok is True
