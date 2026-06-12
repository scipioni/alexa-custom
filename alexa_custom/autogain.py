from __future__ import annotations

import argparse
import logging
import os
import select
import shutil
import subprocess
import sys
import time

import numpy as np

from alexa_custom.actions import get_similarity_score
from alexa_custom.audio_hw import get_input_gain, set_input_gain
from alexa_custom.config import load_config, load_secrets
from alexa_custom.stt_backends import get_stt_backend
from alexa_custom.tts import get_engine, init_engine

logger = logging.getLogger(__name__)

_CHUNK = 4096

DEFAULT_PHRASE = "ascolta assistente chiama aiuto"
DEFAULT_DURATION = 3.0

COARSE_GAINS = [0.05, 0.15, 0.4, 1.0, 3.0]
EXTENDED_GAINS = [1.0, 3.0, 5.0]
COARSE_THRESHOLD = 30.0


def _rms_level(data: bytes) -> float:
    samples = np.frombuffer(data, dtype=np.int16)
    n = len(samples)
    if n == 0:
        return 0.0
    return float(np.linalg.norm(samples)) / (32768.0 * n**0.5)


def _read_with_timeout(stdout, nbytes: int, timeout: float) -> bytes:
    if stdout is None:
        return b""
    fd = stdout.fileno()
    ready, _, _ = select.select([fd], [], [], timeout)
    if not ready:
        return b""
    try:
        return os.read(fd, nbytes)
    except OSError:
        return b""


def _apply_input_gain(data: bytes) -> bytes:
    gain = get_input_gain()
    if abs(gain - 1.0) < 1e-6:
        return data
    arr = np.frombuffer(data, dtype=np.int16).astype(np.float32)
    return np.clip(arr * gain, -32768, 32767).astype(np.int16).tobytes()


def _downmix_to_mono(data: bytes, channels: int) -> bytes:
    if channels <= 1:
        return data
    frame_bytes = channels * 2
    data = data[: len(data) // frame_bytes * frame_bytes]
    if not data:
        return b""
    samples = np.frombuffer(data, dtype=np.int16).reshape(-1, channels)
    idx = np.argmax(np.abs(samples), axis=1)
    mono = samples[np.arange(len(samples)), idx]
    return mono.tobytes()


def resolve_capture_source(input_spec: str | None = None) -> tuple[str | None, int]:
    if input_spec is None:
        input_spec = os.environ.get("INPUT_DEVICE", "").strip() or None
    channels = 1
    if not input_spec:
        return None, channels
    try:
        out = subprocess.check_output(
            ["pactl", "list", "sources"], text=True, timeout=5
        )
        needle = input_spec.lower()
        source_name = None
        found = False
        for line in out.splitlines():
            if "Name: " in line:
                name = line.split(": ", 1)[1].strip()
                if needle in name.lower() and "monitor" not in name.lower():
                    source_name = name
                    found = True
                elif found:
                    return source_name, channels
            if found and "Sample Specification:" in line:
                for part in line.split():
                    if part.endswith("ch"):
                        try:
                            channels = int(part[:-2])
                        except ValueError:
                            pass
                return source_name, channels
        logger.warning(f"No PipeWire source matching {input_spec!r} — using default")
    except Exception as e:
        logger.warning(f"resolve_capture_source failed: {e} — using default")
    return None, channels


def start_capture(source: str | None, channels: int = 1) -> subprocess.Popen:
    tool = shutil.which("parec")
    if not tool:
        tool = shutil.which("pw-record")
        if not tool:
            raise RuntimeError("Neither parec nor pw-record found on system")

    is_pw = "pw-record" in tool
    cmd = [
        tool,
        "--rate=16000",
        f"--channels={channels}",
        "--format=s16le" if not is_pw else "--format=s16",
    ]
    if is_pw:
        if source:
            cmd.append(f"--target={source}")
    else:
        cmd.append("--latency-msec=1")
        if source:
            cmd.append(f"--device={source}")

    return subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0
    )


def _capture_and_transcribe(
    stt_backend, source: str | None, channels: int, duration: float
) -> tuple[str, bytes]:
    proc = start_capture(source, channels)
    assert proc.stdout is not None

    total_bytes = int(16000 * channels * 2 * duration)
    bytes_read = 0
    all_audio = bytearray()

    stt_backend.reset()
    chunk_size = _CHUNK * channels

    t_end = time.monotonic() + duration
    while bytes_read < total_bytes and time.monotonic() < t_end:
        to_read = min(chunk_size, total_bytes - bytes_read)
        raw_data = _read_with_timeout(proc.stdout, to_read, 0.5)
        if not raw_data:
            if proc.poll() is not None:
                break
            continue
        bytes_read += len(raw_data)
        processed = _apply_input_gain(_downmix_to_mono(raw_data, channels))
        all_audio.extend(processed)
        stt_backend.accept_waveform(processed)

    text = stt_backend.finalize()

    proc.terminate()
    try:
        proc.wait(timeout=2.0)
    except Exception:
        proc.kill()
        proc.wait()

    return text, bytes(all_audio)


def _compute_clipping_ratio(raw_audio: bytes) -> float:
    if not raw_audio:
        return 0.0
    samples = np.frombuffer(raw_audio, dtype=np.int16)
    if len(samples) == 0:
        return 0.0
    return float(np.sum(np.abs(samples) >= 32767)) / len(samples)


def score_transcription(expected: str, actual: str, raw_audio: bytes) -> float:
    stt_score = get_similarity_score(expected, actual, "token_set_ratio")
    clipping = _compute_clipping_ratio(raw_audio)
    if clipping > 0.05:
        return 0.0
    if clipping > 0.01:
        return stt_score * 0.5
    return stt_score


def _compute_zoom_gains(best_gain: float) -> list[float]:
    if best_gain <= 0.05:
        return [0.05, 0.1, 0.2]
    if best_gain >= 3.0:
        return [1.5, 3.0, 5.0]
    return [best_gain / 2, best_gain, best_gain * 2]


<<<<<<< HEAD
=======
def _compute_verify_gains(best_gain: float, dist_index: int) -> list[float]:
    if dist_index >= 1:
        gains = [best_gain, best_gain * 2, best_gain * 4]
        return [min(g, 10.0) for g in gains]
    return [best_gain]


>>>>>>> ade8963 (fix: test wider gain range at far distances (best×4 instead of best×2))
def _save_gain_to_config(gain: float) -> None:
    from ruamel.yaml import YAML

    config_path = "conf/config.yaml"
    yaml = YAML()
    yaml.preserve_quotes = True
    with open(config_path) as f:
        cfg = yaml.load(f)
    if cfg is None:
        cfg = {}
    cfg.setdefault("audio", {})
    cfg["audio"]["input_gain"] = gain
    with open(config_path, "w") as f:
        yaml.dump(cfg, f)


def _print_summary(results: list[dict], winner: float, dry_run: bool) -> None:
    print()
    print("Microfono calibrato")
    print("─────────────────────")
    for r in results:
        marker = "  ← MIGLIORE" if r["gain"] == winner else ""
        clip_pct = r["clipping"] * 100
        print(f"  {r['gain']:<5.2f}  {r['score']:>5.1f}%  {clip_pct:>5.1f}%{marker}")
    print("─────────────────────")
    if dry_run:
        print(f"  Miglior gain: {winner:.2f} (dry-run, non salvato)")
    else:
        print(f"  ✅ Miglior gain: {winner:.2f} — scritto in config.yaml")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Interactive microphone gain calibration."
    )
    parser.add_argument(
        "--text",
        type=str,
        default=DEFAULT_PHRASE,
        help=f"Reference phrase (default: '{DEFAULT_PHRASE}')",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=DEFAULT_DURATION,
        help=f"Recording duration in seconds per rep (default: {DEFAULT_DURATION})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run calibration and show results without writing to config.yaml",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.ERROR, format="%(levelname)s %(name)s: %(message)s"
    )
    logging.getLogger().setLevel(logging.ERROR)
    for name in ["alexa_custom", "urllib3", "httpcore", "httpx", "livekit"]:
        logging.getLogger(name).setLevel(logging.ERROR)

    load_secrets("conf/secrets.yaml")
    config = load_config("conf/config.yaml")
    if config is None:
        print("Error: Could not load conf/config.yaml", file=sys.stderr)
        sys.exit(1)

    init_engine(
        backend_type=config.tts.backend,
        voice=config.tts.voice,
        preroll_ms=config.tts.preroll_ms,
    )
    tts_engine = get_engine()

    _kws_keywords = [p for g in config.wake_words for p in [g.word] + g.aliases]
    stt_backend = get_stt_backend(config.stt.stage1, keywords=_kws_keywords)

    source, channels = resolve_capture_source(config.audio.input_device)

    phrase = args.text
    duration = args.duration
    all_results: list[dict] = []

    def _test_level(gain: float) -> float:
        set_input_gain(None, config.audio.input_device, gain)
        scores = []
        clippings = []
        for rep in range(2):
            msg = f"ripeti: {phrase}"
            tts_engine.say(msg)
            time.sleep(0.2)
            text, raw_audio = _capture_and_transcribe(
                stt_backend, source, channels, duration
            )
            score = score_transcription(phrase, text, raw_audio)
            scores.append(score)
            clippings.append(_compute_clipping_ratio(raw_audio))
        level_score = sum(scores) / len(scores)
        avg_clipping = sum(clippings) / len(clippings)
        all_results.append(
            {"gain": gain, "score": level_score, "clipping": avg_clipping}
        )
        print(
            f"  gain {gain:.2f}: score={level_score:.1f}% clipping={avg_clipping * 100:.1f}%"
        )
        return level_score

    print("Fase 1 — Sweep iniziale")
    coarse_scores = []
    for gain in COARSE_GAINS:
        coarse_scores.append(_test_level(gain))

    if all(s < COARSE_THRESHOLD for s in coarse_scores):
        print("  Score bassi — estendo a gain più alti")
        for gain in EXTENDED_GAINS:
            coarse_scores.append(_test_level(gain))

    best_idx = max(range(len(all_results)), key=lambda i: all_results[i]["score"])
    best_coarse = all_results[best_idx]["gain"]

    print(f"\nMiglior gain fase 1: {best_coarse:.2f}")

    print("\nFase 2 — Zoom fine")
    for gain in _compute_zoom_gains(best_coarse):
        _test_level(gain)

    best_idx = max(range(len(all_results)), key=lambda i: all_results[i]["score"])
    winner = all_results[best_idx]["gain"]

    if not args.dry_run:
        _save_gain_to_config(winner)

    _print_summary(all_results, winner, args.dry_run)


# ── Auto mode (pink noise + loopback) ────────────────────────────────────

_PINK_NOISE_SAMPLERATE = 16000
_PINK_NOISE_DURATION = 1.0
_PINK_NOISE_FADE_MS = 50
_PINK_NOISE_PLAYBACK_VOLUME = 0.5
_HEADROOM_TARGET_DB = 6.0
_CLIPPING_MAX_RATIO = 0.01
_FAR_MIN_SNR_DB = 6.0
_CONFIRM_TOLERANCE = 0.20

_AUTO_PLAY_VOLUMES = [
    ("lontano", 0.06, 5.0),
    ("medio", 0.30, 2.0),
    ("vicino", 0.80, 1.0),
]

TEST_GAINS = [0.3, 0.5, 1.0, 2.0, 3.0, 5.0]


def _generate_pink_noise(duration: float, samplerate: int) -> np.ndarray:
    np.random.seed(42)
    n = int(duration * samplerate)
    n_octaves = 16
    rows = np.zeros((n_octaves, n), dtype=np.float64)
    for i in range(n_octaves):
        step = 1 << i
        blocks = (n + step - 1) // step
        row = np.random.randn(blocks)
        rows[i] = np.repeat(row, step)[:n]
    pink = rows.sum(axis=0)
    pink /= float(np.max(np.abs(pink))) + 1e-12
    return (pink * 0.5 * 32767).astype(np.int16)


def _write_pink_noise_wav(
    path: str,
    duration: float = _PINK_NOISE_DURATION,
    samplerate: int = _PINK_NOISE_SAMPLERATE,
) -> int:
    import wave as _wave

    samples = _generate_pink_noise(duration, samplerate)
    fade_len = int(_PINK_NOISE_FADE_MS * samplerate / 1000)
    if fade_len > 0:
        fade_in = np.linspace(0, 1, fade_len, dtype=np.float64)
        fade_out = np.linspace(1, 0, fade_len, dtype=np.float64)
        samples[:fade_len] = (samples[:fade_len].astype(np.float64) * fade_in).astype(
            np.int16
        )
        samples[-fade_len:] = (
            samples[-fade_len:].astype(np.float64) * fade_out
        ).astype(np.int16)
    with _wave.open(path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(samplerate)
        wf.writeframes(samples.tobytes())
    return samplerate


def _scale_wav_to_playback_volume(
    src: str, dst: str, volume: float = _PINK_NOISE_PLAYBACK_VOLUME
) -> str:
    import wave as _wave

    with _wave.open(src, "rb") as wf:
        params = wf.getparams()
        frames = wf.readframes(wf.getnframes())
    samples = np.frombuffer(frames, dtype=np.int16).astype(np.float32)
    scaled = np.clip(samples * volume, -32768, 32767).astype(np.int16)
    with _wave.open(dst, "wb") as wf:
        wf.setparams(params)
        wf.writeframes(scaled.tobytes())
    return dst


def _measure_noise_floor(source: str | None, channels: int, gain: float) -> list[float]:
    set_input_gain(None, source, gain)
    time.sleep(0.3)
    all_rms: list[list[float]] = []
    for _ in range(3):
        proc = start_capture(source, channels)
        assert proc.stdout is not None
        duration = 0.3
        total = int(_PINK_NOISE_SAMPLERATE * channels * 2 * duration)
        collected = bytearray()
        t_end = time.monotonic() + duration
        while len(collected) < total and time.monotonic() < t_end:
            to_read = min(_CHUNK * channels, total - len(collected))
            raw = _read_with_timeout(proc.stdout, to_read, 0.5)
            if not raw:
                break
            collected.extend(raw)
        proc.terminate()
        try:
            proc.wait(timeout=2.0)
        except Exception:
            proc.kill()
            proc.wait()
        if len(collected) < channels * 2 * 10:
            all_rms.append([0.0] * channels)
        else:
            frame_bytes = channels * 2
            trimmed = bytes(collected[: len(collected) // frame_bytes * frame_bytes])
            samples = (
                np.frombuffer(trimmed, dtype=np.int16)
                .astype(np.float32)
                .reshape(-1, channels)
            )
            per_ch = []
            for c in range(channels):
                rms = float(np.sqrt(np.mean(samples[:, c] ** 2))) / 32768.0
                per_ch.append(rms)
            all_rms.append(per_ch)
        time.sleep(0.1)
    n_channels = len(all_rms[0]) if all_rms else channels
    result = []
    for c in range(n_channels):
        vals = [r[c] for r in all_rms if c < len(r)]
        median_val = float(np.median(vals)) if vals else 0.0
        result.append(median_val)
    return result


def _capture_multi_channel(
    source: str | None, channels: int, duration: float
) -> np.ndarray:
    proc = start_capture(source, channels)
    assert proc.stdout is not None
    total = int(_PINK_NOISE_SAMPLERATE * channels * 2 * duration)
    collected = bytearray()
    t_end = time.monotonic() + duration
    while len(collected) < total and time.monotonic() < t_end:
        to_read = min(_CHUNK * channels, total - len(collected))
        raw = _read_with_timeout(proc.stdout, to_read, 0.5)
        if not raw:
            break
        collected.extend(raw)
    proc.terminate()
    try:
        proc.wait(timeout=2.0)
    except Exception:
        proc.kill()
        proc.wait()
    frame_bytes = channels * 2
    trimmed = bytes(collected[: len(collected) // frame_bytes * frame_bytes])
    return (
        np.frombuffer(trimmed, dtype=np.int16).astype(np.float32).reshape(-1, channels)
    )


def _compute_frequency_weighted_snr(signal: np.ndarray, noise_rms: float) -> float:
    n = len(signal)
    if n < 4:
        return 0.0
    spectrum = np.fft.rfft(signal)
    freqs = np.fft.rfftfreq(n, d=1.0 / _PINK_NOISE_SAMPLERATE)
    power = np.abs(spectrum) ** 2
    low = (freqs >= 0) & (freqs < 300)
    speech = (freqs >= 300) & (freqs <= 3400)
    high = freqs > 3400
    weighted = np.zeros_like(power)
    weighted[low] = power[low] * 0.5
    weighted[speech] = power[speech] * 2.0
    weighted[high] = power[high] * 0.5
    signal_power = float(np.mean(weighted)) if len(weighted) > 0 else 0.0
    signal_rms = float(np.sqrt(signal_power)) / 32768.0 if signal_power > 0 else 0.0
    snr_db = 20.0 * np.log10(signal_rms / noise_rms + 1e-12)
    return snr_db


def _compute_channel_balance(multi: np.ndarray) -> float:
    if multi.shape[1] < 2:
        return 0.0
    rms_per_ch = [
        float(np.sqrt(np.mean(multi[:, c] ** 2))) for c in range(multi.shape[1])
    ]
    sorted_rms = sorted(rms_per_ch, reverse=True)
    if sorted_rms[0] < 1e-12 or sorted_rms[1] < 1e-12:
        return 0.0
    return float(20.0 * np.log10(sorted_rms[0] / sorted_rms[1]))


def _capture_playback_response(
    source: str | None, channels: int, wav_path: str, wav_duration: float
) -> tuple[np.ndarray, list[float]]:
    import threading

    proc = start_capture(source, channels)
    assert proc.stdout is not None

    play_done = threading.Event()

    def _play() -> None:
        try:
            subprocess.run(["pw-play", wav_path], capture_output=True, check=False)
        finally:
            play_done.set()

    play_thread = threading.Thread(target=_play, daemon=True)
    play_thread.start()
    time.sleep(0.05)

    cap_duration = wav_duration + 0.3
    total = int(_PINK_NOISE_SAMPLERATE * channels * 2 * cap_duration)
    collected = bytearray()
    t_end = time.monotonic() + cap_duration
    while len(collected) < total and time.monotonic() < t_end:
        to_read = min(_CHUNK * channels, total - len(collected))
        raw = _read_with_timeout(proc.stdout, to_read, 0.5)
        if not raw:
            break
        collected.extend(raw)

    play_thread.join(timeout=3.0)
    proc.terminate()
    try:
        proc.wait(timeout=2.0)
    except Exception:
        proc.kill()
        proc.wait()

    frame_bytes = channels * 2
    trimmed = bytes(collected[: len(collected) // frame_bytes * frame_bytes])
    multi = (
        np.frombuffer(trimmed, dtype=np.int16).astype(np.float32).reshape(-1, channels)
    )
    peaks = [float(np.max(np.abs(multi[:, c]))) / 32768.0 for c in range(channels)]
    return multi, peaks


def _analyze_channel(signal: np.ndarray, noise_rms: float) -> dict:
    signal_rms = float(np.sqrt(np.mean(signal**2))) / 32768.0
    peak = float(np.max(np.abs(signal))) / 32768.0
    clipping = (
        float(np.sum(np.abs(signal) >= 32767)) / len(signal) if len(signal) > 0 else 0.0
    )
    snr_db = _compute_frequency_weighted_snr(signal, noise_rms)
    headroom_db = 20.0 * np.log10(1.0 / (peak + 1e-12))
    return {
        "rms": signal_rms,
        "peak": peak,
        "clipping": clipping,
        "snr_db": snr_db,
        "headroom_db": headroom_db,
    }


def _analyze_capture(multi: np.ndarray, noise_rms_per_ch: list[float]) -> dict:
    channels = multi.shape[1]
    per_ch = [
        _analyze_channel(multi[:, c], noise_rms_per_ch[c]) for c in range(channels)
    ]
    avg = {k: float(np.mean([ch[k] for ch in per_ch])) for k in per_ch[0]}
    avg["per_channel"] = per_ch
    return avg


def _select_best_gain(results: list[dict]) -> float:
    def _any_clip(r: dict) -> bool:
        return any(v["clipping"] > _CLIPPING_MAX_RATIO for v in r["volumes"].values())

    def _any_headroom(r: dict) -> bool:
        return any(
            v["headroom_db"] >= _HEADROOM_TARGET_DB for v in r["volumes"].values()
        )

    def _far_snr_ok(r: dict) -> bool:
        far = r["volumes"].get("lontano", {})
        return far.get("snr_db", -999.0) >= _FAR_MIN_SNR_DB

    candidates = [
        r for r in results if not _any_clip(r) and _any_headroom(r) and _far_snr_ok(r)
    ]
    if not candidates:
        logger.warning(
            "No gain meets far SNR constraint (>=%.0fdB) — relaxing", _FAR_MIN_SNR_DB
        )
        candidates = [r for r in results if not _any_clip(r) and _any_headroom(r)]
    if not candidates:
        candidates = sorted(results, key=lambda r: (-r["weighted_snr"], r["gain"]))
        logger.warning("No gain passes any constraint — picking best weighted SNR")
    for r in candidates:
        imbalance = _compute_channel_balance(r.get("_multi", np.zeros((1, 1))))
        logger.debug(
            " gain %.2f imbalance=%.1fdB wSNR=%.1f",
            r["gain"],
            imbalance,
            r["weighted_snr"],
        )
        if imbalance > 6.0:
            r["_penalized_snr"] = r["weighted_snr"] * 0.5
        else:
            r["_penalized_snr"] = r["weighted_snr"]
    candidates.sort(key=lambda r: r["_penalized_snr"], reverse=True)
    return candidates[0]["gain"]


def _check_channel_balance(multi: np.ndarray) -> bool:
    if multi.shape[1] < 2:
        return True
    rms_per_ch = [
        float(np.sqrt(np.mean(multi[:, c] ** 2))) for c in range(multi.shape[1])
    ]
    if any(r < 1e-6 for r in rms_per_ch):
        return False
    ratio_db = float(20.0 * np.log10(max(rms_per_ch) / min(rms_per_ch)))
    return bool(ratio_db < 6.0)


def _print_acoustic_summary(
    results: list[dict], winner_gain: float, dry_run: bool, channels: int = 1
) -> None:
    gains = sorted(set(r["gain"] for r in results))
    vol_keys = [k for k, _, _ in _AUTO_PLAY_VOLUMES]
    vol_labels = [k.capitalize() for k in vol_keys]

    snr_cells = "".join(
        f"  {vl[:4] + '/S':>7}  {vl[:4] + '/H':>5}" for vl in vol_labels
    )
    header = f"{'Gain':>6}  {'WSnr':>5}{snr_cells}  {'Clip':>6}  {'Bal':>4}"
    sep_len = len(header)
    print()
    print("Risultati calibrazione acustica (multi-volume)")
    print("=" * sep_len)
    print(header)
    print("-" * sep_len)
    for g in gains:
        e = next((r for r in results if r["gain"] == g), None)
        if not e:
            continue
        vols = e["volumes"]
        any_clip = any(v["clipping"] > _CLIPPING_MAX_RATIO for v in vols.values())
        imbalance = _compute_channel_balance(e.get("_multi", np.zeros((1, 1))))
        marker = "  ←" if g == winner_gain else ""
        print(f"{g:>6.2f}  {e['weighted_snr']:>5.1f}", end="")
        for label, _vol, _w in _AUTO_PLAY_VOLUMES:
            v = vols[label]
            print(f"  {v['snr_db']:>7.1f}  {v['headroom_db']:>5.1f}", end="")
        bal_flag = f"{imbalance:>4.1f}" if imbalance > 0 else "ok"
        print(f"  {'YES!' if any_clip else 'ok':>6}  {bal_flag}{marker}")
    print("=" * sep_len)
    if dry_run:
        print(f"Miglior gain: {winner_gain:.2f} (dry-run, non salvato)")
    else:
        print(f"Miglior gain: {winner_gain:.2f} — scritto in config.yaml")
    print()


def _run_stt_validation(
    actions_config, winner_gain: float, source: str | None, channels: int
) -> bool:
    from alexa_custom.tts import get_engine

    phrase = "ascolta assistente chiama aiuto"
    tts_engine = get_engine()
    tts_engine.say(phrase)
    time.sleep(0.5)

    _kws_keywords = [p for g in actions_config.wake_words for p in [g.word] + g.aliases]
    stt_backend = get_stt_backend(actions_config.stt.stage1, keywords=_kws_keywords)
    text, raw_audio = _capture_and_transcribe(stt_backend, source, channels, 3.0)
    score = score_transcription(phrase, text, raw_audio)
    logger.info(
        "STT validation: gain=%.2f score=%.1f%% text=%r", winner_gain, score, text
    )
    return score >= 50.0


def run_autogain_auto(
    actions_config,
    dry_run: bool = False,
) -> float:
    import tempfile

    input_spec = actions_config.audio.input_device
    source, channels = resolve_capture_source(input_spec)
    logger.info("Autogain auto: source=%s channels=%d", source, channels)

    test_wav = tempfile.mktemp(suffix=".wav", prefix="autogain_pink_")
    scaled_wavs: dict[str, str] = {}

    try:
        _write_pink_noise_wav(test_wav)
        pink_duration = _PINK_NOISE_DURATION

        for label, vol, _w in _AUTO_PLAY_VOLUMES:
            w = tempfile.mktemp(suffix=".wav", prefix=f"autogain_{label}_")
            _scale_wav_to_playback_volume(test_wav, w, volume=vol)
            scaled_wavs[label] = w

        all_results: list[dict] = []

        # ── Coarse pass ────────────────────────────────────────────────
        for gain in TEST_GAINS:
            set_input_gain(None, input_spec, gain)
            time.sleep(0.3)

            noise_rms = _measure_noise_floor(source, channels, gain)
            logger.info(
                "  gain %4.2f noise RMS: %s", gain, [f"{r:.6f}" for r in noise_rms]
            )

            volumes: dict[str, dict] = {}
            any_valid = False
            multi_last: np.ndarray | None = None
            for label, _vol, _w in _AUTO_PLAY_VOLUMES:
                multi, peaks = _capture_playback_response(
                    source, channels, scaled_wavs[label], pink_duration
                )
                if multi.shape[0] < 10:
                    logger.warning("  gain %4.2f %s: insufficient capture", gain, label)
                    volumes[label] = {
                        "snr_db": -240.0,
                        "headroom_db": 240.0,
                        "clipping": 1.0,
                        "peaks": [0.0],
                    }
                    continue
                any_valid = True
                multi_last = multi
                analysis = _analyze_capture(multi, noise_rms)
                volumes[label] = {
                    "snr_db": analysis["snr_db"],
                    "headroom_db": analysis["headroom_db"],
                    "clipping": analysis["clipping"],
                    "peaks": peaks,
                }

            if not any_valid:
                logger.warning("  gain %4.2f: no valid captures — skipping", gain)
                continue

            balanced = _check_channel_balance(multi_last)
            if not balanced:
                logger.warning("  gain %4.2f: channel imbalance >6dB", gain)

            total_w = sum(w for _l, _v, w in _AUTO_PLAY_VOLUMES)
            weighted_snr = (
                sum(volumes[label]["snr_db"] * w for label, _v, w in _AUTO_PLAY_VOLUMES)
                / total_w
                if total_w
                else 0.0
            )

            entry = {
                "gain": gain,
                "volumes": volumes,
                "weighted_snr": weighted_snr,
                "channel_balanced": balanced,
                "_multi": multi_last if multi_last is not None else np.zeros((1, 1)),
            }
            all_results.append(entry)

            logger.info(
                "  gain %4.2f: wSNR=%.1fdB  lont/S=%.1f  medi/S=%.1f  vici/S=%.1f",
                gain,
                weighted_snr,
                volumes["lontano"]["snr_db"],
                volumes["medio"]["snr_db"],
                volumes["vicino"]["snr_db"],
            )

        if not all_results:
            logger.error("No valid capture results — using default gain 1.0")
            return 1.0

        coarse_winner = _select_best_gain(all_results)

        # ── Multi-volume refinement ─────────────────────────────────────
        step = 0.1
        half_range = 0.4
        fine_gains = sorted(
            set(
                round(coarse_winner + i * step, 2)
                for i in range(
                    int(-half_range / step),
                    int(half_range / step) + 1,
                )
            )
        )
        fine_gains = [
            g for g in fine_gains if 0.1 <= g <= 6.0 and abs(g - coarse_winner) > 0.01
        ]

        if fine_gains:
            logger.info(
                "Refining: %.1f-step around %.2f → %s", step, coarse_winner, fine_gains
            )
            fine_candidates: list[dict] = []
            for gain in fine_gains:
                set_input_gain(None, input_spec, gain)
                time.sleep(0.3)
                noise_rms = _measure_noise_floor(source, channels, gain)
                volumes_ref: dict[str, dict] = {}
                any_valid_ref = False
                multi_ref: np.ndarray | None = None
                for label, _vol, _w in _AUTO_PLAY_VOLUMES:
                    multi, peaks = _capture_playback_response(
                        source, channels, scaled_wavs[label], pink_duration
                    )
                    if multi.shape[0] < 10:
                        continue
                    any_valid_ref = True
                    multi_ref = multi
                    analysis = _analyze_capture(multi, noise_rms)
                    volumes_ref[label] = {
                        "snr_db": analysis["snr_db"],
                        "headroom_db": analysis["headroom_db"],
                        "clipping": analysis["clipping"],
                        "peaks": peaks,
                    }
                if not any_valid_ref:
                    continue
                total_w = sum(w for _l, _v, w in _AUTO_PLAY_VOLUMES)
                weighted_snr = (
                    sum(
                        volumes_ref[label]["snr_db"] * w
                        for label, _v, w in _AUTO_PLAY_VOLUMES
                    )
                    / total_w
                    if total_w
                    else 0.0
                )
                fine_candidates.append(
                    {
                        "gain": gain,
                        "volumes": volumes_ref,
                        "weighted_snr": weighted_snr,
                        "_multi": multi_ref
                        if multi_ref is not None
                        else np.zeros((1, 1)),
                    }
                )
                logger.info("  refine %4.2f: wSNR=%.1fdB", gain, weighted_snr)

            if fine_candidates:
                refined_best = max(
                    set(r["gain"] for r in fine_candidates),
                    key=lambda g: max(
                        r["weighted_snr"] for r in fine_candidates if r["gain"] == g
                    ),
                )
                refined_entry = next(
                    r for r in fine_candidates if r["gain"] == refined_best
                )
                coarse_entry = next(
                    r for r in all_results if r["gain"] == coarse_winner
                )
                if refined_entry["weighted_snr"] > coarse_entry["weighted_snr"]:
                    logger.info(
                        "Refined: %.2f → %.2f (wSNR %.1f → %.1f)",
                        coarse_winner,
                        refined_best,
                        coarse_entry["weighted_snr"],
                        refined_entry["weighted_snr"],
                    )
                    winner_gain = refined_best
                else:
                    winner_gain = coarse_winner
            else:
                winner_gain = coarse_winner
        else:
            winner_gain = coarse_winner

        # ── Confirmation with retry ─────────────────────────────────────
        set_input_gain(None, input_spec, winner_gain)
        time.sleep(0.3)
        noise_rms = _measure_noise_floor(source, channels, winner_gain)
        multi_c, _peaks_c = _capture_playback_response(
            source, channels, scaled_wavs["medio"], pink_duration
        )
        confirm = _analyze_capture(multi_c, noise_rms)

        orig_entry = next(r for r in all_results if r["gain"] == winner_gain)
        orig_vol = orig_entry["volumes"]["medio"]
        orig_snr = orig_vol["snr_db"]

        confirm_ok = True
        if orig_snr > 0:
            deviation = abs(confirm["snr_db"] - orig_snr) / orig_snr
            if deviation > _CONFIRM_TOLERANCE:
                logger.warning(
                    "Confirmation SNR deviates %.0f%% (%.1fdB vs %.1fdB) — retrying (1/3)",
                    deviation * 100,
                    confirm["snr_db"],
                    orig_snr,
                )
                retry_ok = False
                for attempt in range(2, 4):
                    noise_rms = _measure_noise_floor(source, channels, winner_gain)
                    multi_c2, _ = _capture_playback_response(
                        source, channels, scaled_wavs["medio"], pink_duration
                    )
                    confirm2 = _analyze_capture(multi_c2, noise_rms)
                    d2 = abs(confirm2["snr_db"] - orig_snr) / orig_snr
                    if d2 <= _CONFIRM_TOLERANCE:
                        logger.info(
                            "  retry %d/3 passed (dev=%.0f%%)", attempt, d2 * 100
                        )
                        retry_ok = True
                        break
                    logger.warning("  retry %d/3 deviates %.0f%%", attempt, d2 * 100)
                if not retry_ok:
                    logger.warning(
                        "All confirmation retries failed — falling back to coarse winner %.2f",
                        coarse_winner,
                    )
                    winner_gain = coarse_winner
                    confirm_ok = False

        # ── STT validation pass ─────────────────────────────────────────
        if confirm_ok and not dry_run:
            passed = _run_stt_validation(actions_config, winner_gain, source, channels)
            if not passed:
                candidates_ranked = sorted(
                    set(r["gain"] for r in all_results),
                    key=lambda g: next(
                        r["weighted_snr"] for r in all_results if r["gain"] == g
                    ),
                    reverse=True,
                )
                for alt_gain in candidates_ranked:
                    if abs(alt_gain - winner_gain) < 0.01:
                        continue
                    logger.info("STT failed — testing next-best gain %.2f", alt_gain)
                    set_input_gain(None, input_spec, alt_gain)
                    time.sleep(0.3)
                    alt_passed = _run_stt_validation(
                        actions_config, alt_gain, source, channels
                    )
                    if alt_passed:
                        winner_gain = alt_gain
                        logger.info("STT validation passed for gain %.2f", alt_gain)
                        break
                    logger.info(
                        "STT also failed for gain %.2f — keeping acoustic winner",
                        alt_gain,
                    )

        if not dry_run:
            _save_gain_to_config(winner_gain)

        _print_acoustic_summary(all_results, winner_gain, dry_run, channels)
        logger.info("Autogain auto complete — best gain: %.2f", winner_gain)
        return winner_gain

    finally:
        for p in list(scaled_wavs.values()) + [test_wav]:
            try:
                os.unlink(p)
            except OSError:
                pass


SPEECH_TEST_PHRASE = "ascolta assistente chiama aiuto"
SPEECH_TEST_WAV = "models/test_phrase.wav"


def main_auto() -> None:
    parser = argparse.ArgumentParser(
        description="Calibra il gain del microfono usando rumore rosa + analisi acustica."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Mostra risultati senza scrivere config.yaml",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(message)s",
    )
    logging.getLogger().setLevel(logging.INFO)
    for name in ["urllib3", "httpcore", "httpx", "livekit"]:
        logging.getLogger(name).setLevel(logging.ERROR)

    load_secrets("conf/secrets.yaml")
    config = load_config("conf/config.yaml")
    if config is None:
        print("Error: Could not load conf/config.yaml", file=sys.stderr)
        sys.exit(1)

    print(f"Calibrazione microfono — rumore rosa, {len(TEST_GAINS)} gain")
    print(f"Gain da testare: {TEST_GAINS}")
    print(f"(dry-run: {'sì' if args.dry_run else 'no'})")
    print()

    run_autogain_auto(config, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
