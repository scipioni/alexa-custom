"""MCP server for Serena GStreamer calibration.

Keeps the Vosk model and TTS engine resident between tool calls, eliminating
the ~5 s per-trial startup cost of the subprocess-based CLI approach.

Register in .claude/settings.json, then call tools in order:
    calibrate_init  → one-time setup (loads model + TTS)
    calibrate_trial → one trial per parameter variant
    calibrate_summary → ranked table of all results
    calibrate_reset → clear for a new session

Start directly:
    uv run --active serena-calibrate-mcp
"""

from __future__ import annotations

import json
import sys
import time
from typing import Any

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("serena-calibrate")

# ---------------------------------------------------------------------------
# Session state — shared across all tool calls within one server process.
# ---------------------------------------------------------------------------
_s: dict[str, Any] = {
    "phrase": None,
    "listen_seconds": 4.0,
    "rms_threshold": None,
    "backend": None,        # VoskSTT instance — reset() between trials
    "tts_ready": False,
    "config": None,
    "results": [],          # list of result dicts, appended each trial
}


def _composite(r: dict) -> float:
    return (60.0 if r["exact_match"] else 0.0) + r["match_score"] * 0.3 + r["speech_ratio"] * 100.0


# ---------------------------------------------------------------------------
# Tool: calibrate_init
# ---------------------------------------------------------------------------

@mcp.tool()
def calibrate_init(
    phrase: str,
    listen_seconds: float = 4.0,
    rms_threshold: float | None = None,
) -> str:
    """Load config, Vosk model and TTS engine once.  Call before calibrate_trial.

    phrase         - the exact phrase the user will say during each trial.
    listen_seconds - capture window length in seconds (default 4.0).
    rms_threshold  - override RMS gate (None = use config value).

    Returns a JSON status dict.
    """
    _s["phrase"] = phrase
    _s["listen_seconds"] = listen_seconds
    _s["results"] = []

    # --- Load config ---
    try:
        import os
        from pathlib import Path
        conf_dir = Path(os.getcwd()) / "conf"
        from alexa_custom.config import load_config, load_secrets
        secrets = load_secrets(conf_dir / "secrets.yaml")
        config = load_config(conf_dir / "config.yaml", secrets=secrets)
        if config is None:
            return json.dumps({"error": f"Config load failed: {conf_dir / 'config.yaml'} not found"})
        _s["config"] = config
    except Exception as e:
        return json.dumps({"error": f"Config load failed: {e}"})

    _s["rms_threshold"] = rms_threshold if rms_threshold is not None else config.stt.rms_threshold

    # --- Load Vosk model (the expensive part — ~3 s) ---
    try:
        from alexa_custom.stt_backends import get_stt_backend
        _s["backend"] = get_stt_backend(config.stt)
    except Exception as e:
        return json.dumps({"error": f"STT backend load failed: {e}"})

    # --- Init TTS ---
    try:
        import alexa_custom.tts as _tts_module
        tts_cfg = config.tts if hasattr(config, "tts") else None
        backend_type = tts_cfg.backend if tts_cfg else "piper"
        voice = tts_cfg.voice if tts_cfg else "it_IT-paola-medium"
        _tts_module.init_engine(backend_type, voice=voice)
        _s["tts_ready"] = True
    except Exception as e:
        print(f"[mcp_calibrate] TTS init failed ({e}); will skip prompts", file=sys.stderr)
        _s["tts_ready"] = False

    return json.dumps({
        "status": "ready",
        "phrase": phrase,
        "listen_seconds": listen_seconds,
        "rms_threshold": _s["rms_threshold"],
        "vosk_model": config.stt.model_path,
        "tts_ready": _s["tts_ready"],
    })


# ---------------------------------------------------------------------------
# Tool: calibrate_trial
# ---------------------------------------------------------------------------

@mcp.tool()
def calibrate_trial(
    noise_suppression: bool = True,
    noise_suppression_level: int = 2,
    agc: bool = True,
    agc_target_level_dbfs: int = -3,
    agc_compression_gain_db: int = 9,
    high_pass_filter: bool = True,
    compressor: bool = False,
    compressor_threshold: float = 0.1,
    compressor_ratio: float = 3.0,
) -> str:
    """Run one calibration trial with the given GStreamer parameters.

    Speaks the phrase via TTS, plays a ready tone, waits for the user to
    speak, captures audio, runs Vosk STT, scores the result.

    Returns the JSON result dict (same schema as serena-stt --calibrate-gstreamer).
    The result is also stored in the session for calibrate_summary().
    """
    if _s["backend"] is None or _s["config"] is None:
        return json.dumps({"error": "Call calibrate_init first."})

    config = _s["config"]
    backend = _s["backend"]
    phrase = _s["phrase"]
    listen_seconds = _s["listen_seconds"]
    rms_threshold = _s["rms_threshold"]

    # Reset the recognizer so prior trial audio doesn't bleed through.
    backend.reset()

    # --- Build GStreamer config ---
    import dataclasses
    gst_cfg = dataclasses.replace(
        config.audio.gstreamer,
        noise_suppression=noise_suppression,
        noise_suppression_level=noise_suppression_level,
        agc=agc,
        agc_target_level_dbfs=agc_target_level_dbfs,
        agc_compression_gain_db=agc_compression_gain_db,
        high_pass_filter=high_pass_filter,
        compressor=compressor,
        compressor_threshold=compressor_threshold,
        compressor_ratio=compressor_ratio,
    )

    # --- Announce phrase ---
    if _s["tts_ready"]:
        try:
            import alexa_custom.tts as _tts_module
            _tts_module.get_engine().say(f"Di' questo: {phrase}")
        except Exception as e:
            print(f"[mcp_calibrate] TTS say failed: {e}", file=sys.stderr)

    print(f"[mcp_calibrate] phrase  : {phrase!r}", file=sys.stderr)

    time.sleep(0.3)
    try:
        from alexa_custom.audio_ops import play_tone
        play_tone("wake")
    except Exception:
        pass
    time.sleep(0.5)

    # --- Capture ---
    try:
        from alexa_custom.stt_gst_capture import start_capture_gst
    except ImportError as e:
        return json.dumps({"error": f"GStreamer unavailable: {e}"})

    from alexa_custom.stt_gating import resolve_capture_source, _rms_level
    source, _ = resolve_capture_source(config.audio.input_device)

    print(f"[mcp_calibrate] capturing {listen_seconds}s …", file=sys.stderr)
    try:
        proc = start_capture_gst(source, gst_cfg)
    except RuntimeError as e:
        return json.dumps({"error": str(e)})

    import numpy as np

    target_bytes = int(listen_seconds * 16000 * 2)
    collected = bytearray()
    rms_chunks: list[float] = []
    deadline = time.monotonic() + listen_seconds + 2.0

    while len(collected) < target_bytes and time.monotonic() < deadline:
        want = min(4096, target_bytes - len(collected))
        try:
            chunk = proc.stdout.read(want)
        except OSError:
            break
        if not chunk:
            break
        collected += chunk
        if len(chunk) >= 2:
            rms_chunks.append(_rms_level(chunk))

    proc.terminate()
    try:
        proc.wait(timeout=2)
    except Exception:
        pass

    captured_bytes = len(collected)
    captured_s = captured_bytes / (16000 * 2)
    print(f"[mcp_calibrate] captured : {captured_s:.2f}s", file=sys.stderr)

    # --- STT decode (reuse loaded model) ---
    chunk_size = 4096
    for i in range(0, len(collected), chunk_size):
        backend.accept_waveform(bytes(collected[i : i + chunk_size]))
    transcript = backend.finalize().strip()
    print(f"[mcp_calibrate] transcript: {transcript!r}", file=sys.stderr)

    # --- Score ---
    from alexa_custom.stt_phonetics import _match_wake_word
    from alexa_custom.actions import match_trigger_with_score

    wake_phrase, _ = _match_wake_word(transcript, config.wake_words)
    trig, score = match_trigger_with_score(
        transcript,
        config.triggers,
        algorithm=config.recognition.matching_algorithm,
        threshold=0.0,
    )

    exact_ok = False
    if wake_phrase and any(w == phrase for w in config.wake_words):
        exact_ok = True
    elif trig and phrase in (trig.commands or [trig.phrase]):
        exact_ok = True

    rms_peak = max(rms_chunks, default=0.0)
    rms_mean = float(np.mean(rms_chunks)) if rms_chunks else 0.0
    chunks_above = sum(1 for r in rms_chunks if r > rms_threshold)

    result = {
        "phrase_played": phrase,
        "transcript": transcript,
        "exact_match": exact_ok,
        "matched_trigger": trig.phrase if trig else None,
        "matched_wake": wake_phrase,
        "match_score": round(score, 1),
        "production_threshold": config.recognition.matching_threshold,
        "rms_peak": round(rms_peak, 4),
        "rms_mean": round(rms_mean, 4),
        "rms_threshold": rms_threshold,
        "chunks_above_rms": chunks_above,
        "total_chunks": len(rms_chunks),
        "speech_ratio": round(chunks_above / len(rms_chunks), 3) if rms_chunks else 0.0,
        "captured_seconds": round(captured_s, 2),
        "composite_score": round(_composite({
            "exact_match": exact_ok,
            "match_score": round(score, 1),
            "speech_ratio": round(chunks_above / len(rms_chunks), 3) if rms_chunks else 0.0,
        }), 1),
        "gst_params": {
            f.name: getattr(gst_cfg, f.name)
            for f in dataclasses.fields(gst_cfg)
            if f.name != "profiles"
        },
    }
    _s["results"].append(result)
    return json.dumps(result, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Tool: calibrate_summary
# ---------------------------------------------------------------------------

@mcp.tool()
def calibrate_summary() -> str:
    """Return a ranked table of all trials in this session.

    Rows are sorted by composite_score descending.
    """
    if not _s["results"]:
        return json.dumps({"error": "No trials recorded yet."})

    rows = []
    for r in _s["results"]:
        gp = r.get("gst_params", {})
        rows.append({
            "composite_score": r["composite_score"],
            "exact_match": r["exact_match"],
            "match_score": r["match_score"],
            "speech_ratio": r["speech_ratio"],
            "transcript": r["transcript"],
            "noise_suppression": gp.get("noise_suppression"),
            "noise_suppression_level": gp.get("noise_suppression_level"),
            "agc": gp.get("agc"),
            "agc_target_level_dbfs": gp.get("agc_target_level_dbfs"),
            "agc_compression_gain_db": gp.get("agc_compression_gain_db"),
            "high_pass_filter": gp.get("high_pass_filter"),
            "compressor": gp.get("compressor"),
            "compressor_threshold": gp.get("compressor_threshold"),
            "compressor_ratio": gp.get("compressor_ratio"),
        })

    rows.sort(key=lambda x: x["composite_score"], reverse=True)
    best = rows[0]

    winning_yaml = f"""\
audio:
  gstreamer:
    noise_suppression: {str(best['noise_suppression']).lower()}
    noise_suppression_level: {best['noise_suppression_level']}
    agc: {str(best['agc']).lower()}
    agc_target_level_dbfs: {best['agc_target_level_dbfs']}
    agc_compression_gain_db: {best['agc_compression_gain_db']}
    high_pass_filter: {str(best['high_pass_filter']).lower()}
    compressor: {str(best['compressor']).lower()}
    compressor_threshold: {best['compressor_threshold']}
    compressor_ratio: {best['compressor_ratio']}"""

    return json.dumps({
        "total_trials": len(rows),
        "ranked_results": rows,
        "winning_config_yaml": winning_yaml,
    }, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Tool: calibrate_reset
# ---------------------------------------------------------------------------

@mcp.tool()
def calibrate_reset() -> str:
    """Clear session results so a new calibrate_init can start fresh.

    Does NOT unload the Vosk model or TTS — call calibrate_init again to
    change phrase or other init parameters.
    """
    _s["results"] = []
    _s["phrase"] = None
    _s["backend"] = None
    _s["tts_ready"] = False
    _s["config"] = None
    return json.dumps({"status": "reset"})


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
