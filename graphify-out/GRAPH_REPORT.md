# Graph Report - progetto  (2026-06-12)

## Corpus Check
- 331 files · ~278,158 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 80 nodes · 172 edges · 10 communities (8 shown, 2 thin omitted)
- Extraction: 100% EXTRACTED · 0% INFERRED · 0% AMBIGUOUS
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `d1a91ffb`
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

## God Nodes (most connected - your core abstractions)
1. `str` - 14 edges
2. `main()` - 11 edges
3. `int` - 9 edges
4. `set_input_gain()` - 9 edges
5. `_capture_and_transcribe()` - 9 edges
6. `_restore_hw_pcm()` - 8 edges
7. `enforce_audio_state()` - 8 edges
8. `check_newpie_ready()` - 8 edges
9. `float` - 8 edges
10. `Pulse` - 7 edges

## Surprising Connections (you probably didn't know these)
- `test_calibration_writes_config()` --calls--> `main()`  [EXTRACTED]
  tests/test_autogain.py → alexa_custom/autogain.py
- `test_custom_text_used()` --calls--> `main()`  [EXTRACTED]
  tests/test_autogain.py → alexa_custom/autogain.py
- `test_dry_run_skips_write()` --calls--> `main()`  [EXTRACTED]
  tests/test_autogain.py → alexa_custom/autogain.py
- `test_summary_contains_coarse_gains()` --calls--> `main()`  [EXTRACTED]
  tests/test_autogain.py → alexa_custom/autogain.py
- `main()` --calls--> `set_input_gain()`  [EXTRACTED]
  alexa_custom/autogain.py → alexa_custom/audio_hw.py

## Import Cycles
- None detected.

## Communities (10 total, 2 thin omitted)

### Community 0 - "Community 0"
Cohesion: 0.24
Nodes (19): get_input_gain(), _apply_input_gain(), _capture_and_transcribe(), _compute_clipping_ratio(), _compute_zoom_gains(), _downmix_to_mono(), _print_summary(), bool (+11 more)

### Community 1 - "Community 1"
Cohesion: 0.18
Nodes (12): get_output_volume(), float, Restore ALSA hardware PCM to 100% after any pulsectl interaction.      Resolves, Set PipeWire default source/sink by matching INPUT_DEVICE/OUTPUT_DEVICE name., Set the in-app output volume scalar.      The system mixer is intentionally not, Set the NewPie microphone gain.      Tries to set the hardware source volume via, Save volume to config.yaml for persistence (preserves comments)., _restore_hw_pcm() (+4 more)

### Community 2 - "Community 2"
Cohesion: 0.24
Nodes (11): check_newpie_ready(), detect_connection(), enforce_audio_state(), find_alexa_card(), list_devices(), bool, Return the pulsectl card object matching the spec (name, desc, or index)., Return 'usb', 'bluetooth', or 'internal' based on the card's device.bus property (+3 more)

### Community 3 - "Community 3"
Cohesion: 0.36
Nodes (7): find_pipewire_device(), get_pipewire_device(), list_env_devices(), Return the sounddevice index for the PipeWire ALSA device., Cached lookup of the PortAudio index of the PipeWire ALSA device., Print microphone and speaker tables for use in .env., speakerphone()

### Community 4 - "Community 4"
Cohesion: 0.33
Nodes (7): device_from_env(), get_post_playback_ms(), get_tone_preroll_ms(), int, Resolve a device name substring or numeric index string to a sounddevice index., Return the sounddevice index for INPUT_DEVICE or OUTPUT_DEVICE, or None if unset, resolve_device()

### Community 5 - "Community 5"
Cohesion: 0.67
Nodes (6): main(), _mock_config(), test_calibration_writes_config(), test_custom_text_used(), test_dry_run_skips_write(), test_summary_contains_coarse_gains()

### Community 6 - "Community 6"
Cohesion: 0.33
Nodes (6): _find_alsa_card(), _find_pipewire_source(), Return (card_index, card_id) for first ALSA card whose id contains needle., Return the PipeWire source name matching input_spec, or None if not found., Set output device PCM hardware volume to 100% and persist it across reboots., setup_audio()

### Community 7 - "Community 7"
Cohesion: 0.40
Nodes (5): get_default_card_name(), get_sample_rates(), str, Return (vendor_id, model_id) by querying udevadm., _usb_ids_for_alsa_card()

## Knowledge Gaps
- **2 isolated node(s):** `Popen`, `bool`
  These have ≤1 connection - possible missing edges or undocumented components.
- **2 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `set_input_gain()` connect `Community 1` to `Community 0`, `Community 2`, `Community 3`, `Community 5`, `Community 6`, `Community 7`?**
  _High betweenness centrality (0.115) - this node is a cross-community bridge._
- **Why does `main()` connect `Community 5` to `Community 0`, `Community 1`?**
  _High betweenness centrality (0.089) - this node is a cross-community bridge._
- **Why does `str` connect `Community 7` to `Community 1`, `Community 2`, `Community 4`, `Community 6`?**
  _High betweenness centrality (0.055) - this node is a cross-community bridge._
- **What connects `Save volume to config.yaml for persistence (preserves comments).`, `Update module-level audio parameters from ActionsConfig.`, `Restore ALSA hardware PCM to 100% after any pulsectl interaction.      Resolves` to the rest of the system?**
  _22 weakly-connected nodes found - possible documentation gaps or missing edges._