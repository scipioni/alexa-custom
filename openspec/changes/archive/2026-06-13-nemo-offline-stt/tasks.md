## 1. Config updates

- [ ] 1.1 Add `"nemo-offline"` as valid stage2 backend in `_parse_stt_stage2_config()` in `config.py`
- [ ] 1.2 Add `"nemo-offline"` to valid stage1/stage2 `model_variant` values (optional, for future online use)

## 2. Backend implementation

- [ ] 2.1 Create `NeMoOfflineSTT` class in `stt_backends.py` extending `STTBackend`
- [ ] 2.2 Implement `__init__()`: load model with `OfflineRecognizer.from_nemo_ctc()`, set `num_threads=4`
- [ ] 2.3 Implement `accept_waveform()`: buffer incoming s16le chunks as int16 numpy array, return False
- [ ] 2.4 Implement `text()`: return current result text
- [ ] 2.5 Implement `partial_text()`: return "" (offline — no partial support)
- [ ] 2.6 Implement `reset()`: clear audio buffer, reset result
- [ ] 2.7 Implement `finalize()`: concatenate buffered int16, convert to float32 [-1,1], create `OfflineStream`, feed full audio, call `decode_stream()`, return result text
- [ ] 2.8 Add `"nemo-offline"` branch to `get_stt_backend()` factory function (stage2 only)

## 3. Model download

- [ ] 3.1 Update `_SHERPA_MODELS` in `setup.py`: point to `csukuangfj` NeMo CTC model URL, destination `models/sherpa-onnx/nemo-ctc-it/`
- [ ] 3.2 Update `_SHERPA_FILES` to `["model.onnx", "tokens.txt"]`

## 4. Default path

- [ ] 4.1 Set `_NEMO_OFFLINE_PATH` default in `stt_backends.py` to `"models/sherpa-onnx/nemo-ctc-it"`

## 5. Testing

- [ ] 5.1 Run `task test` to verify existing tests still pass
- [ ] 5.2 Run ruff lint

## 6. On-device verification

- [ ] 6.1 Run `alexa-setup --sherpa-onnx --force` on target board to download the NeMo model
- [ ] 6.2 Configure `stt.stage2.backend: nemo-offline` and run client
- [ ] 6.3 Verify transcription accuracy for Italian commands
- [ ] 6.4 Measure real-time factor for 2s, 4s, 8s utterances
- [ ] 6.5 Tune `num_threads` in `NeMoOfflineSTT` if needed
