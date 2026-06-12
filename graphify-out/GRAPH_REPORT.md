# Graph Report - progetto  (2026-06-12)

## Corpus Check
<<<<<<< HEAD
- 331 files · ~278,203 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 79 nodes · 169 edges · 12 communities
=======
- 331 files · ~278,562 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 119 nodes · 261 edges · 16 communities (10 shown, 6 thin omitted)
>>>>>>> 1a14599 (fix: dashboard input gain slider no longer resets)
- Extraction: 100% EXTRACTED · 0% INFERRED · 0% AMBIGUOUS
- Token cost: 0 input · 0 output

## Graph Freshness
<<<<<<< HEAD
- Built from commit: `1d9ecbfc`
=======
- Built from commit: `bb320aca`
>>>>>>> 1a14599 (fix: dashboard input gain slider no longer resets)
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- [[_COMMUNITY_Community 0|Community 0]]
- [[_COMMUNITY_Community 1|Community 1]]
- [[_COMMUNITY_Community 2|Community 2]]
- [[_COMMUNITY_Community 3|Community 3]]
- [[_COMMUNITY_Community 4|Community 4]]
- [[_COMMUNITY_Community 5|Community 5]]
- [[_COMMUNITY_Community 6|Community 6]]
- [[_COMMUNITY_Community 7|Community 7]]
- [[_COMMUNITY_Community 8|Community 8]]
- [[_COMMUNITY_Community 9|Community 9]]
- [[_COMMUNITY_Community 10|Community 10]]
- [[_COMMUNITY_Community 11|Community 11]]
<<<<<<< HEAD

## God Nodes (most connected - your core abstractions)
1. `str` - 14 edges
2. `main()` - 10 edges
3. `_capture_and_transcribe()` - 9 edges
4. `int` - 9 edges
5. `set_input_gain()` - 9 edges
6. `_restore_hw_pcm()` - 8 edges
7. `enforce_audio_state()` - 8 edges
8. `check_newpie_ready()` - 8 edges
9. `bytes` - 7 edges
10. `float` - 7 edges
=======
- [[_COMMUNITY_Community 12|Community 12]]
- [[_COMMUNITY_Community 13|Community 13]]
- [[_COMMUNITY_Community 14|Community 14]]
- [[_COMMUNITY_Community 15|Community 15]]

## God Nodes (most connected - your core abstractions)
1. `WebServer` - 24 edges
2. `float` - 15 edges
3. `str` - 14 edges
4. `main()` - 12 edges
5. `str` - 11 edges
6. `_capture_and_transcribe()` - 9 edges
7. `int` - 9 edges
8. `set_input_gain()` - 9 edges
9. `int` - 8 edges
10. `run_web()` - 8 edges
>>>>>>> 1a14599 (fix: dashboard input gain slider no longer resets)

## Surprising Connections (you probably didn't know these)
- `test_all_three_gains_in_summary()` --calls--> `main()`  [EXTRACTED]
  tests/test_autogain.py → alexa_custom/autogain.py
- `test_calibration_writes_config()` --calls--> `main()`  [EXTRACTED]
  tests/test_autogain.py → alexa_custom/autogain.py
- `test_custom_text_used()` --calls--> `main()`  [EXTRACTED]
  tests/test_autogain.py → alexa_custom/autogain.py
- `test_dry_run_skips_write()` --calls--> `main()`  [EXTRACTED]
  tests/test_autogain.py → alexa_custom/autogain.py
<<<<<<< HEAD
- `main()` --calls--> `set_input_gain()`  [EXTRACTED]
  alexa_custom/autogain.py → alexa_custom/audio_hw.py
=======
- `test_summary_shows_all_distances()` --calls--> `main()`  [EXTRACTED]
  tests/test_autogain.py → alexa_custom/autogain.py
- `_capture_and_transcribe()` --references--> `str`  [EXTRACTED]
  alexa_custom/autogain.py → alexa_custom/web.py
>>>>>>> 1a14599 (fix: dashboard input gain slider no longer resets)

## Import Cycles
- None detected.

<<<<<<< HEAD
## Communities (12 total, 0 thin omitted)

### Community 0 - "Community 0"
Cohesion: 0.25
Nodes (18): get_input_gain(), _apply_input_gain(), _capture_and_transcribe(), _compute_clipping_ratio(), _downmix_to_mono(), _print_summary(), _read_with_timeout(), resolve_capture_source() (+10 more)
=======
## Communities (16 total, 6 thin omitted)

### Community 0 - "Community 0"
Cohesion: 0.19
Nodes (25): Set the NewPie microphone gain.      Tries to set the hardware source volume via, set_input_gain(), _apply_input_gain(), _capture_and_transcribe(), _compute_clipping_ratio(), _compute_verify_gains(), _compute_zoom_gains(), _downmix_to_mono() (+17 more)
>>>>>>> 1a14599 (fix: dashboard input gain slider no longer resets)

### Community 1 - "Community 1"
Cohesion: 0.33
Nodes (6): Restore ALSA hardware PCM to 100% after any pulsectl interaction.      Resolves, Set PipeWire default source/sink by matching INPUT_DEVICE/OUTPUT_DEVICE name., Set the in-app output volume scalar.      The system mixer is intentionally not, _restore_hw_pcm(), set_output_volume(), set_pipewire_defaults()

### Community 2 - "Community 2"
<<<<<<< HEAD
Cohesion: 0.36
Nodes (8): check_newpie_ready(), enforce_audio_state(), find_alexa_card(), bool, str, Return the pulsectl card object matching the spec (name, desc, or index)., Find configured card, force profile if it exists, and set default sink/source., Verify configured audio device is connected and ready.

### Community 3 - "Community 3"
Cohesion: 0.33
Nodes (6): find_pipewire_device(), get_pipewire_device(), list_env_devices(), Return the sounddevice index for the PipeWire ALSA device., Cached lookup of the PortAudio index of the PipeWire ALSA device., Print microphone and speaker tables for use in .env.

### Community 4 - "Community 4"
Cohesion: 0.40
Nodes (5): device_from_env(), Resolve a device name substring or numeric index string to a sounddevice index., Return the sounddevice index for INPUT_DEVICE or OUTPUT_DEVICE, or None if unset, resolve_device(), speakerphone()

### Community 5 - "Community 5"
Cohesion: 0.67
Nodes (6): main(), _mock_config(), test_all_three_gains_in_summary(), test_calibration_writes_config(), test_custom_text_used(), test_dry_run_skips_write()
=======
Cohesion: 0.31
Nodes (9): check_newpie_ready(), detect_connection(), enforce_audio_state(), list_devices(), bool, Return 'usb', 'bluetooth', or 'internal' based on the card's device.bus property, Find configured card, force profile if it exists, and set default sink/source., Verify configured audio device is connected and ready. (+1 more)

### Community 3 - "Community 3"
Cohesion: 0.26
Nodes (11): find_pipewire_device(), get_pipewire_device(), get_post_playback_ms(), get_sample_rates(), get_tone_preroll_ms(), list_env_devices(), int, Return the sounddevice index for the PipeWire ALSA device. (+3 more)

### Community 4 - "Community 4"
Cohesion: 0.29
Nodes (8): device_from_env(), find_alexa_card(), get_default_card_name(), str, Resolve a device name substring or numeric index string to a sounddevice index., Return the sounddevice index for INPUT_DEVICE or OUTPUT_DEVICE, or None if unset, Return the pulsectl card object matching the spec (name, desc, or index)., resolve_device()
>>>>>>> 1a14599 (fix: dashboard input gain slider no longer resets)

### Community 6 - "Community 6"
Cohesion: 0.25
Nodes (8): _find_alsa_card(), _find_pipewire_source(), Return (card_index, card_id) for first ALSA card whose id contains needle., Return the PipeWire source name matching input_spec, or None if not found., Return (vendor_id, model_id) by querying udevadm., Set output device PCM hardware volume to 100% and persist it across reboots., setup_audio(), _usb_ids_for_alsa_card()

### Community 7 - "Community 7"
Cohesion: 0.50
Nodes (4): get_post_playback_ms(), get_sample_rates(), get_tone_preroll_ms(), int

### Community 8 - "Community 8"
Cohesion: 0.33
Nodes (5): configure(), get_default_card_name(), invalidate_pipewire_device_cache(), Clear the cached PortAudio device index., Update module-level audio parameters from ActionsConfig.

### Community 9 - "Community 9"
<<<<<<< HEAD
Cohesion: 0.50
Nodes (5): _find_pipewire_source(), Set the NewPie microphone gain.      Tries to set the hardware source volume via, Return the PipeWire source name matching input_spec, or None if not found., set_input_gain(), Pulse

### Community 10 - "Community 10"
Cohesion: 0.50
Nodes (4): get_output_volume(), float, Save volume to config.yaml for persistence (preserves comments)., save_volume_config()

### Community 11 - "Community 11"
Cohesion: 0.67
Nodes (3): detect_connection(), list_devices(), Return 'usb', 'bluetooth', or 'internal' based on the card's device.bus property
=======
Cohesion: 0.36
Nodes (4): Web dashboard for alexa-custom., run_web(), bool, Path

### Community 10 - "Community 10"
Cohesion: 0.33
Nodes (3): _WebLogHandler, LogRecord, WebServer

### Community 11 - "Community 11"
Cohesion: 0.33
Nodes (3): Request, Response, WebSocketResponse

### Community 12 - "Community 12"
Cohesion: 0.40
Nodes (5): get_input_gain(), get_output_volume(), float, Save volume to config.yaml for persistence (preserves comments)., save_volume_config()
>>>>>>> 1a14599 (fix: dashboard input gain slider no longer resets)

## Knowledge Gaps
- **6 isolated node(s):** `WebServer`, `LogRecord`, `Response`, `WebSocketResponse`, `Any` (+1 more)
  These have ≤1 connection - possible missing edges or undocumented components.
<<<<<<< HEAD
=======
- **6 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.
>>>>>>> 1a14599 (fix: dashboard input gain slider no longer resets)

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

<<<<<<< HEAD
- **Why does `set_input_gain()` connect `Community 9` to `Community 0`, `Community 1`, `Community 2`, `Community 5`, `Community 8`, `Community 10`?**
  _High betweenness centrality (0.116) - this node is a cross-community bridge._
- **Why does `main()` connect `Community 5` to `Community 0`, `Community 9`?**
  _High betweenness centrality (0.087) - this node is a cross-community bridge._
- **Why does `str` connect `Community 2` to `Community 1`, `Community 4`, `Community 6`, `Community 7`, `Community 8`, `Community 9`, `Community 11`?**
  _High betweenness centrality (0.056) - this node is a cross-community bridge._
- **What connects `Popen`, `bool`, `Save volume to config.yaml for persistence (preserves comments).` to the rest of the system?**
  _22 weakly-connected nodes found - possible documentation gaps or missing edges._
=======
- **Why does `float` connect `Community 0` to `Community 9`, `Community 10`, `Community 5`?**
  _High betweenness centrality (0.205) - this node is a cross-community bridge._
- **Why does `str` connect `Community 13` to `Community 0`, `Community 9`, `Community 11`?**
  _High betweenness centrality (0.182) - this node is a cross-community bridge._
- **Why does `WebServer` connect `Community 5` to `Community 9`, `Community 10`, `Community 11`, `Community 13`, `Community 14`, `Community 15`?**
  _High betweenness centrality (0.103) - this node is a cross-community bridge._
- **What connects `WebServer`, `LogRecord`, `Response` to the rest of the system?**
  _28 weakly-connected nodes found - possible documentation gaps or missing edges._
>>>>>>> 1a14599 (fix: dashboard input gain slider no longer resets)
