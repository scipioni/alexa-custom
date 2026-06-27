#!/usr/bin/env python3
"""tune_mic.py - Automated coordinate-descent tuning script for serena-stt.

Sweeps through noise suppression, AGC, HPF, RMS threshold, and input gain
parameters by executing 'serena-stt --score' to optimize acoustic accuracy.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys
import yaml

# Parameter search space and candidate values to probe
SEARCH_SPACE = {
    "noise_suppression": [True, False],
    "noise_suppression_level": [0, 1, 2, 3],
    "agc": [True, False],
    "agc_target_level_dbfs": [-3, -6, -10, -15],
    "agc_compression_gain_db": [5, 9, 20, 40, 70],
    "high_pass_filter": [True, False],
    "rms_threshold": [0.005, 0.01, 0.02, 0.04],
    "input_gain": [0.5, 1.0, 1.5, 2.0, 3.0],
}

# Baseline default parameters
DEFAULT_PARAMS = {
    "noise_suppression": True,
    "noise_suppression_level": 2,
    "agc": True,
    "agc_target_level_dbfs": -3,
    "agc_compression_gain_db": 9,
    "high_pass_filter": True,
    "rms_threshold": 0.02,
    "input_gain": 1.0,
}


def load_starting_params() -> dict:
    """Resolve starting parameters from conf/state.yaml and conf/config.yaml, with fallbacks."""
    params = dict(DEFAULT_PARAMS)
    
    # 1. Load active profile name and input_gain from conf/state.yaml
    profile_name = None
    state_input_gain = None
    state_path = pathlib.Path("conf/state.yaml")
    if state_path.exists():
        try:
            with open(state_path) as f:
                state_data = yaml.safe_load(f) or {}
                profile_name = state_data.get("gst_profile")
                state_input_gain = state_data.get("input_gain")
        except Exception as e:
            print(f"Warning: Failed to load conf/state.yaml ({e})", file=sys.stderr)
            
    print(f"Active GStreamer Profile: {profile_name or 'None'}")
    
    # 2. Load config.yaml to get base and profile-level overrides
    config_path = pathlib.Path("conf/config.yaml")
    if config_path.exists():
        try:
            with open(config_path) as f:
                config_data = yaml.safe_load(f) or {}
                
            audio_cfg = config_data.get("audio", {})
            gst_cfg = audio_cfg.get("gstreamer", {})
            stt_cfg = config_data.get("stt", {})
            
            # Resolve profile override dict if profile is active
            profile_cfg = {}
            if profile_name:
                profile_cfg = gst_cfg.get("profiles", {}).get(profile_name, {})
                
            # Helper to resolve parameter with fallbacks
            def resolve_val(key, base_dict, stt_key=None):
                # Try active profile first
                if key in profile_cfg:
                    return profile_cfg[key]
                # Try stt key fallback if applicable
                if stt_key and stt_key in stt_cfg:
                    return stt_cfg[stt_key]
                # Try base dict next
                if key in base_dict:
                    return base_dict[key]
                # Fall back to default
                return DEFAULT_PARAMS[key]
                
            params["noise_suppression"] = resolve_val("noise_suppression", gst_cfg)
            params["noise_suppression_level"] = resolve_val("noise_suppression_level", gst_cfg)
            params["agc"] = resolve_val("agc", gst_cfg)
            params["agc_target_level_dbfs"] = resolve_val("agc_target_level_dbfs", gst_cfg)
            params["agc_compression_gain_db"] = resolve_val("agc_compression_gain_db", gst_cfg)
            params["high_pass_filter"] = resolve_val("high_pass_filter", gst_cfg)
            params["rms_threshold"] = resolve_val("rms_threshold", gst_cfg, stt_key="rms_threshold")
            
            # Resolve input gain starting value with fallbacks
            if state_input_gain is not None:
                params["input_gain"] = float(state_input_gain)
            elif "input_gain" in audio_cfg:
                params["input_gain"] = float(audio_cfg["input_gain"])
            else:
                params["input_gain"] = DEFAULT_PARAMS["input_gain"]
            
        except Exception as e:
            print(f"Warning: Failed to load conf/config.yaml ({e})", file=sys.stderr)
            
    return params


def run_trial(params: dict, play_file: str | None = None, timeout: float = 20.0) -> tuple[int, str]:
    """Execute a single trial of serena-stt --score with the given parameters."""
    cmd = ["uv", "run", "serena-stt", "--score", "--timeout", str(timeout)]
    if play_file:
        cmd += ["--play", play_file]
    if "input_gain" in params:
        cmd += ["--input-gain", str(params["input_gain"])]

    # Map parameters to command-line flags
    if params.get("noise_suppression"):
        cmd += ["--noise-suppression"]
    else:
        cmd += ["--no-noise-suppression"]

    cmd += ["--noise-suppression-level", str(params["noise_suppression_level"])]

    if params.get("agc"):
        cmd += ["--agc"]
    else:
        cmd += ["--no-agc"]

    cmd += ["--agc-target-level-dbfs", str(params["agc_target_level_dbfs"])]
    cmd += ["--agc-compression-gain-db", str(params["agc_compression_gain_db"])]

    if params.get("high_pass_filter"):
        cmd += ["--high-pass-filter"]
    else:
        cmd += ["--no-high-pass-filter"]

    cmd += ["--rms-threshold", str(params["rms_threshold"])]

    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=timeout + 5.0,  # dynamic safety margin
        )
        if proc.returncode != 0:
            return 0, f"[STT Exit Code: {proc.returncode}]"

        stdout = proc.stdout.strip()
        if not stdout:
            return 0, "[No Output]"

        # Parse the printed JSON output
        result = json.loads(stdout)
        return int(result.get("score", 0)), result.get("text", "")
    except subprocess.TimeoutExpired:
        return 0, "[Timeout]"
    except json.JSONDecodeError:
        return 0, f"[Invalid JSON: {proc.stdout[:100]}]"
    except Exception as e:
        return 0, f"[Error: {e}]"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Auto-tune microphone and STT parameters using coordinate-descent sweeps of serena-stt --score"
    )
    parser.add_argument(
        "--play",
        metavar="WAV",
        help="Replay a pre-recorded WAV file instead of using live microphone input",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=20.0,
        metavar="N",
        help="Maximum timeout in seconds per trial (default: 20s)",
    )
    parser.add_argument(
        "--input-gain",
        type=float,
        default=None,
        metavar="F",
        help="Microphone input gain override (default: from config)",
    )

    args = parser.parse_args()

    print("=" * 60)
    print("Microphone Auto-Tuning Tool Starting...")
    if args.play:
        print(f"Mode: Automated Replay (using {args.play})")
    else:
        print("Mode: Autonomous External Speech Loop (listening continuously)")
    if args.input_gain is not None:
        print(f"Input Gain Override: {args.input_gain}")
    print("=" * 60)

    current_best_params = load_starting_params()
    if args.input_gain is not None:
        current_best_params["input_gain"] = args.input_gain
    
    print("\nMeasuring baseline score with profile/default starting parameters...")
    
    baseline_score, baseline_text = run_trial(
        current_best_params,
        play_file=args.play,
        timeout=args.timeout,
    )
    print(f"Baseline: Score={baseline_score} | Text={baseline_text!r}")
    print(f"Baseline Params: {json.dumps(current_best_params)}")
    
    current_best_score = baseline_score
    loop_count = 0

    while True:
        loop_count += 1
        print(f"\n--- Starting Parameter Optimization Loop #{loop_count} ---")
        improved = False

        for param, candidates in SEARCH_SPACE.items():
            print(f"\nOptimizing parameter: '{param}' (current best: {current_best_params[param]})")
            
            for candidate in candidates:
                # Skip the value that is already the current best for this parameter
                if candidate == current_best_params[param]:
                    continue

                trial_params = dict(current_best_params)
                trial_params[param] = candidate

                print(f" -> Testing {param}={candidate}...")

                score, text = run_trial(
                    trial_params,
                    play_file=args.play,
                    timeout=args.timeout,
                )
                print(f"    Result -> Score: {score} | Recognized text: {text!r}")

                if score > current_best_score:
                    print(f"    ⭐ IMPROVEMENT! New Best Score: {score} (was {current_best_score})")
                    current_best_score = score
                    current_best_params[param] = candidate
                    improved = True
                
                print(f"    Current Best Params: {json.dumps(current_best_params)}")
                print(f"    Current Best Score: {current_best_score}")

        if not improved:
            print("\n============================================================")
            print("🎉 Optimization finished! No parameter changes yielded improvement.")
            print(f"Final Optimal Score: {current_best_score}")
            print(f"Final Optimal Parameters: {json.dumps(current_best_params, indent=2)}")
            print("============================================================")
            break
        else:
            print(f"\nCompleted Loop #{loop_count} with improvements. Initiating next loop pass...")


if __name__ == "__main__":
    main()
