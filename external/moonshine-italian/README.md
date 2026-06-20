# Moonshine Italian STT — Fine-tuning scripts

Fine-tune [Moonshine](https://github.com/moonshine-ai/moonshine) streaming ASR models for Italian.
Produces Italian ASR models deployable in the Moonshine C++ runtime as either
`ModelArch.TINY` (non-streaming, default) or `ModelArch.TINY_STREAMING` (streaming, lower
latency) — see [Training vs deployment architecture](#training-vs-deployment-architecture).

---

## Overview

Moonshine does not ship Italian ASR models out of the box. These scripts:

1. **`download_dataset.py`** — downloads and merges Italian speech datasets from HuggingFace,
   resamples audio to 16 kHz, normalises transcripts, and saves a combined dataset to disk.

2. **`train.py`** — fine-tunes a pretrained English Moonshine streaming model on the Italian
   dataset using curriculum learning (short clips → medium → full), then optionally exports to
   ONNX for deployment.

3. **`export_streaming.py`** — converts the fine-tuned HuggingFace model to the 5-component
   streaming ORT format required by `ModelArch.TINY_STREAMING` / `MEDIUM_STREAMING`.

4. **`mic_transcriber_it.py`** — microphone transcriber for the fine-tuned Italian model.

A **`Taskfile.yml`** wraps the full pipeline:

```bash
# Full pipeline — tiny streaming, no auth required (FLEURS ~10 h)
task all:tiny

# Full pipeline — medium streaming, with Common Voice (set HF_TOKEN first)
HF_TOKEN=hf_xxx task all:medium

# List all targets
task --list
```

### Models targeted

| Variant | Base checkpoint | Params | VRAM needed | Est. training time |
|---|---|---|---|---|
| `tiny-streaming` | `UsefulSensors/moonshine-tiny-streaming` | 34 M | ~6 GB | ~12 h on RTX 3060 |
| `medium-streaming` | `UsefulSensors/moonshine-medium-streaming` | 245 M | ~24 GB | ~72 h on A100 40 GB |

Training starts from the English checkpoint and adapts it to Italian via supervised fine-tuning
(cross-entropy loss on the decoder token sequence). No training from scratch.

### Training vs deployment architecture

HuggingFace trains the model as a standard **seq2seq encoder-decoder** regardless of the base
checkpoint. After training, two deployment paths are available:

| Path | Script | ModelArch | Inference mode |
|---|---|---|---|
| Non-streaming | `train.py --export-onnx` + ORT conversion | `TINY` | Full-context seq2seq |
| Streaming | `export_streaming.py` | `TINY_STREAMING` | Frame-by-frame, lower latency |

Both paths use the same fine-tuned weights. The streaming path splits the model into five
separately-invocable components (frontend / encoder / adapter / cross\_kv / decoder\_kv) that
the Moonshine C runtime can call incrementally as audio arrives.

---

## Requirements

### Hardware

- **Tiny streaming**: any NVIDIA GPU with ≥ 6 GB VRAM (RTX 3060 / 4060 or better),
  or AMD GPU with ≥ 8 GB VRAM (RX 6700 XT or better).
- **Medium streaming**: ≥ 24 GB VRAM (RTX 3090, A5000, A100 40 GB, RX 7900 XTX, or multi-GPU).
- CPU-only training is possible but impractically slow (days per epoch).

### Software

Python ≥ 3.10, CUDA ≥ 11.8 **or** ROCm ≥ 6.0.

```bash
pip install -r requirements.txt
```

Key packages:

| Package | Purpose |
|---|---|
| `transformers >= 4.48` | `MoonshineForConditionalGeneration` (Moonshine support added in 4.48) |
| `datasets >= 2.18` | Dataset download, caching, audio resampling |
| `evaluate` + `jiwer` | WER metric during training |
| `accelerate` | Multi-GPU / mixed-precision training backend |
| `optimum[exporters]` | ONNX export after training |
| `optimum-onnx` | Required for Optimum 2.0+ ONNX export pipeline |
| `torchcodec` | PyTorch-native audio decoding (replaces torchaudio in HuggingFace datasets) |
| `schedulefree` | Schedule-free AdamW optimizer (optional, alternative to AdamW) |

### HuggingFace account

Mozilla Common Voice requires acceptance of its terms on HuggingFace and a user access token.
FLEURS and MLS do not require authentication.

To create a token:
1. Sign up at [huggingface.co](https://huggingface.co).
2. Go to **Settings → Access Tokens → New token** (read-only scope is sufficient).
3. Accept the [Common Voice 17.0 terms](https://huggingface.co/datasets/mozilla-foundation/common_voice_17_0).

---

## Step 1 — Download the dataset

| Source | Size | Auth |
|---|---|---|
| Mozilla Common Voice 17 | ~200 h validated | HF token required |
| Google FLEURS | ~10 h | None |
| Multilingual LibriSpeech (MLS) | ~230 h | None |

```bash
# No auth — FLEURS only (~10 h, good for smoke-testing)
task download

# Recommended (~210 h) — set HF_TOKEN first
HF_TOKEN=hf_YOUR_TOKEN_HERE task download

# All sources including MLS (~440 h)
HF_TOKEN=hf_YOUR_TOKEN_HERE task download:full
```

<details>
<summary>Direct Python commands</summary>

```bash
# FLEURS only
python download_dataset.py --sources fleurs

# Common Voice + FLEURS
python download_dataset.py \
    --sources common_voice fleurs \
    --hf-token hf_YOUR_TOKEN_HERE

# All sources
python download_dataset.py \
    --sources common_voice fleurs mls \
    --hf-token hf_YOUR_TOKEN_HERE
```

Options:
```
--sources          One or more of: common_voice fleurs mls  [default: common_voice fleurs]
--output-dir       Where to write the merged dataset        [default: ./data/italian]
--cache-dir        HuggingFace download cache               [default: ./data/.hf_cache]
--hf-token         HuggingFace access token
--num-proc         CPU workers for text normalisation        [default: 4]
```

</details>

### What the script does

1. Downloads each requested source via the HuggingFace `datasets` library.
2. Renames transcript columns to a unified `text` field.
3. Drops clips shorter than 0.5 s or longer than 20 s.
4. Drops examples with empty transcripts.
5. Resamples all audio to 16 kHz mono (Moonshine's required input rate).
6. Lowercases and unicode-normalises all transcripts.
7. Shuffles and merges into `train` / `validation` / `test` splits.
8. Saves the merged `DatasetDict` to `<output-dir>/combined/`.

### Output structure

```
data/italian/
  combined/
    dataset_dict.json
    train/
    validation/
    test/
  .hf_cache/          ← raw downloads, safe to delete after training
```

---

## Step 2 — Train

`train.py` uses curriculum learning: three phases that progressively widen the duration window
until the model is trained on the full range of clip lengths.

| Phase | Duration window | Default steps | Advance when WER < |
|---|---|---|---|
| `short` | 0.5 – 6 s | 2 000 | 50 % |
| `medium` | 2 – 12 s | 4 000 | 35 % |
| `full` | 0.5 – 20 s | remaining | — |

```bash
# Tiny streaming — fits on 12 GB VRAM (RTX 3060/3080, RTX 4060/4070 Ti…)
task train:tiny

# Medium streaming — requires ≥ 24 GB VRAM
task train:medium

# Resume from the latest checkpoint after an interruption
task train:tiny:resume
task train:medium:resume

# Pass extra flags with --
task train:tiny -- --fp16 --eval-steps 200 --tensorboard
```

ONNX export runs automatically at the end of each `train:*` task.
Mixed precision is auto-detected (bf16 on Ampere+ / RDNA3+, fp16 otherwise) unless overridden.

<details>
<summary>Direct Python commands and all options</summary>

```bash
# Tiny — effective batch 64 (8 per-device × 8 accumulation)
python train.py \
    --dataset-dir ./data/italian/combined \
    --model tiny-streaming \
    --export-onnx

# Medium — reduce batch size for 24 GB GPUs
python train.py \
    --dataset-dir ./data/italian/combined \
    --model medium-streaming \
    --per-device-batch-size 2 \
    --gradient-accumulation 32 \
    --export-onnx

# Resume from a specific checkpoint
python train.py \
    --dataset-dir ./data/italian/combined \
    --model tiny-streaming \
    --resume-from-checkpoint ./output/moonshine-it-tiny-streaming/phase-medium/checkpoint-1500 \
    --export-onnx

# TensorBoard monitoring
python train.py --dataset-dir ./data/italian/combined --model tiny-streaming --tensorboard
tensorboard --logdir ./output/moonshine-it-tiny-streaming   # separate terminal
```

All options:
```
--model                  tiny-streaming | medium-streaming | tiny | base  [default: tiny-streaming]
--base-model-id          Override HuggingFace model ID (skips registry lookup)
--dataset-dir            Path produced by download_dataset.py              [required]
--output-dir             Where to write checkpoints and final model
--per-device-batch-size  Batch size per GPU                                [model default]
--gradient-accumulation  Gradient accumulation steps                       [model default]
--learning-rate          Peak learning rate                                 [model default]
--max-steps              Override total training steps (splits across phases proportionally)
--warmup-steps           LR warmup steps                                   [default: 500]
--eval-steps             Evaluate and checkpoint every N steps             [default: 500]
--freeze-encoder         Train only the decoder — faster, less VRAM, lower accuracy
--gradient-checkpointing Enabled by default; disable with --no-gradient-checkpointing
--fp16                   Force fp16 mixed precision
--bf16                   Force bf16 mixed precision
--skip-curriculum        Single-phase training on full dataset (faster, lower quality)
--resume-from-checkpoint Path to a checkpoint directory
--export-onnx            Export final model to ONNX after training
--tensorboard            Enable TensorBoard logging
--seed                                                                      [default: 42]
```

</details>

### Output structure

```
output/moonshine-it-tiny-streaming/
  phase-short/
    best/               ← best checkpoint from phase 1
    checkpoint-500/
    checkpoint-1000/
    ...
  phase-medium/
    best/
    ...
  phase-full/
    best/
    ...
  final/                ← final model (HuggingFace format)
    config.json
    model.safetensors
    preprocessor_config.json
    tokenizer.json
    ...
  onnx/                 ← ONNX export (only if --export-onnx)
    encoder_model.onnx
    decoder_model.onnx
    decoder_with_past_model.onnx
    decoder_model_merged.onnx  ← encoder_model.ort + this are the two files needed for ORT conversion
    config.json
    generation_config.json
    preprocessor_config.json
```

---

## VRAM reduction tips

If you run out of memory, apply these in order (each trades speed or accuracy for memory):

1. **Reduce `--per-device-batch-size`** and increase `--gradient-accumulation` proportionally
   to keep effective batch size at 64.

2. **`--freeze-encoder`**: freezes all encoder weights; only the decoder trains.
   Cuts VRAM roughly in half. Slightly lower final accuracy.

3. **`--gradient-checkpointing`** is already on by default. Ensure it is not disabled.

4. Use **bf16 or fp16**: `--bf16` (Ampere+) or `--fp16` (older GPUs). Half-precision cuts
   activation memory roughly in half. Precision is auto-detected if neither flag is set.

5. **Multi-GPU with `accelerate`**: launch via `accelerate launch` instead of `python`:
   ```bash
   accelerate config   # one-time setup
   accelerate launch train.py --dataset-dir ... --model medium-streaming
   ```

---

## Training on AMD GPUs (ROCm)

The training scripts work on ROCm without code changes. Only the environment setup differs.

### Supported hardware

| GPU | Architecture | ROCm gfx | bf16 | fp16 |
|---|---|---|---|---|
| RX 6700 XT / 6800 / 6900 XT | RDNA2 | gfx1030 | No | Yes |
| RX 7700 XT / 7800 XT / 7900 XT / 7900 XTX | RDNA3 | gfx1100 | Yes | Yes |
| RX 9070 / 9070 XT | RDNA4 | gfx1200 | Yes | Yes |
| MI100 | CDNA1 | gfx908 | No | Yes |
| MI200 / MI210 / MI250 | CDNA2 | gfx90a | Yes | Yes |
| MI300X | CDNA3 | gfx942 | Yes | Yes |

### 1. Install ROCm

Follow the [official ROCm install guide](https://rocm.docs.amd.com/projects/install-on-linux/en/latest/)
for your distro. Verify with:

```bash
rocminfo | grep "gfx"
```

### 2. Install ROCm PyTorch

Do **not** run `pip install torch` from `requirements.txt` first — it pulls the CUDA wheel.
Install the ROCm wheel explicitly, then install the rest:

```bash
# ROCm 6.2 — adjust the rocm version suffix to match your install
pip install torch torchvision torchaudio \
    --index-url https://download.pytorch.org/whl/rocm6.2

# Then install all other dependencies (torch is already satisfied)
pip install -r requirements.txt
```

Verify PyTorch sees your GPU:

```bash
python -c "import torch; print(torch.cuda.is_available(), torch.cuda.get_device_name(0))"
# Expected: True  AMD Radeon RX 7900 XTX  (or similar)
```

### 3. Set the gfx version override (consumer GPUs only)

Official ROCm support targets datacenter GPUs (MI series). Consumer RDNA cards often need an
explicit override so that ROCm targets the correct ISA:

```bash
# RDNA3 (RX 7000 series)
export HSA_OVERRIDE_GFX_VERSION=11.0.0

# RDNA2 (RX 6000 series)
export HSA_OVERRIDE_GFX_VERSION=10.3.0

# RDNA4 (RX 9000 series)
export HSA_OVERRIDE_GFX_VERSION=12.0.0
```

Add the relevant line to your shell profile (`~/.bashrc` / `~/.zshrc`) so it persists across
sessions, or prefix every command:

```bash
HSA_OVERRIDE_GFX_VERSION=11.0.0 python train.py ...
```

### 4. Specify precision explicitly

`train.py` auto-detects precision via `torch.cuda.get_device_capability()`. On ROCm this
returns `(0, 0)` for all devices, so auto-detection falls back to fp32. Always pass the
precision flag manually:

```bash
# RDNA3 / CDNA2+ — bf16 preferred
python train.py --dataset-dir ./data/italian/combined --model tiny-streaming --bf16

# RDNA2 / MI100 — fp16 only
python train.py --dataset-dir ./data/italian/combined --model tiny-streaming --fp16
```

### 5. Complete example — tiny streaming on RX 7900 XTX (24 GB)

```bash
export HSA_OVERRIDE_GFX_VERSION=11.0.0

python train.py \
    --dataset-dir ./data/italian/combined \
    --model tiny-streaming \
    --bf16 \
    --per-device-batch-size 8 \
    --gradient-accumulation 8 \
    --export-onnx
```

### 6. Complete example — medium streaming on RX 7900 XTX (24 GB)

The 245 M model is tight on 24 GB without FlashAttention (not available on RDNA via ROCm).
Use batch size 1 and maximum gradient accumulation to compensate:

```bash
export HSA_OVERRIDE_GFX_VERSION=11.0.0

python train.py \
    --dataset-dir ./data/italian/combined \
    --model medium-streaming \
    --bf16 \
    --per-device-batch-size 1 \
    --gradient-accumulation 64 \
    --freeze-encoder \
    --export-onnx
```

Remove `--freeze-encoder` if you have ≥ 32 GB VRAM (MI200/MI300X or multi-GPU).

### 7. Multi-GPU on ROCm

ROCm supports multi-GPU training via `accelerate` exactly as on CUDA:

```bash
accelerate config   # select "multi-GPU", "ROCm" when prompted
accelerate launch train.py \
    --dataset-dir ./data/italian/combined \
    --model medium-streaming \
    --bf16
```

### Known limitations on ROCm

- **No FlashAttention**: `flash-attn` does not build against ROCm for most consumer GPUs.
  Gradient checkpointing (`--gradient-checkpointing`, on by default) partially compensates
  for the higher activation memory, but throughput will be lower than an equivalent NVIDIA GPU.
- **`torch.compile` may be unstable**: avoid `torch.compile()` calls if you extend the scripts.
- **bitsandbytes QLoRA is unsupported on ROCm** at the time of writing. Use full fine-tuning
  or `--freeze-encoder` instead of LoRA-based memory reduction.
- **ONNX export** runs on CPU and is fully ROCm-agnostic — no changes needed.

---

## Using the trained model

Two deployment paths are available from the same fine-tuned weights:

| | Non-streaming (`ModelArch.TINY`) | Streaming (`ModelArch.TINY_STREAMING`) |
|---|---|---|
| Files needed | `encoder_model.ort` + `decoder_model_merged.ort` + `tokenizer.bin` | `frontend.ort` + `encoder.ort` + `adapter.ort` + `cross_kv.ort` + `decoder_kv.ort` + `streaming_config.json` + `tokenizer.bin` |
| Produced by | `train.py --export-onnx` + ORT conversion | `export_streaming.py` |
| Latency | Transcribes after speech ends | Frame-by-frame, lower latency |
| Inference | Full-context attention over whole utterance | Causal sliding-window, incremental |

---

### Non-streaming deployment (ModelArch.TINY)

```bash
# Convert ONNX → ORT and copy tokenizer.bin in one step
task export:ort:tiny     # for tiny-streaming
task export:ort:medium   # for medium-streaming

# Run
task run:tiny
task run:medium
```

<details>
<summary>Manual steps</summary>

**1. Export ONNX** (skip if you used `--export-onnx` / `task train:*` during training)

```bash
optimum-cli export onnx \
    --model output/moonshine-it-tiny-streaming/final \
    --task automatic-speech-recognition-with-past \
    output/moonshine-it-tiny-streaming/onnx
```

Produces `encoder_model.onnx`, `decoder_model_merged.onnx`, and supporting JSON files.
Only the two `.onnx` files are needed for the next step.

**2. Convert `.onnx` → `.ort`**

```bash
python -m onnxruntime.tools.convert_onnx_models_to_ort \
    --optimization_style Fixed \
    output/moonshine-it-tiny-streaming/onnx/
```

**3. Copy `tokenizer.bin`**

Fine-tuning changes weights only — the vocabulary is identical to English.

```bash
cp ~/.cache/moonshine_voice/download.moonshine.ai/model/medium-streaming-en/quantized/tokenizer.bin \
   output/moonshine-it-tiny-streaming/onnx/

# If no English model is cached yet:
python -m moonshine_voice.download --language en
```

**4. Run**

```bash
python mic_transcriber_it.py --model-dir output/moonshine-it-tiny-streaming/onnx
```

</details>

---

### Streaming deployment (ModelArch.TINY_STREAMING / MEDIUM_STREAMING)

The streaming path splits the model into five separately-invocable components that the
Moonshine C runtime calls incrementally as audio frames arrive. `export_streaming.py` traces
each component from the fine-tuned HuggingFace weights and generates `streaming_config.json`.

```bash
# Export streaming ORT files
task export:streaming:tiny     # → output/moonshine-it-tiny-streaming/streaming/
task export:streaming:medium   # → output/moonshine-it-medium-streaming/streaming/

# Run
task run:tiny:streaming
task run:medium:streaming
```

<details>
<summary>Manual steps</summary>

**1. Export streaming components**

```bash
# tiny-streaming
python export_streaming.py \
    --model-dir output/moonshine-it-tiny-streaming/final \
    --output-dir output/moonshine-it-tiny-streaming/streaming

# medium-streaming
python export_streaming.py \
    --model-dir output/moonshine-it-medium-streaming/final \
    --output-dir output/moonshine-it-medium-streaming/streaming
```

</details>

`export_streaming.py` traces each component, converts to `.ort`, and copies `tokenizer.bin`
automatically. Output directory:

```
output/moonshine-it-tiny-streaming/streaming/
  frontend.ort          audio frontend (conv layers + rolling state buffers)
  encoder.ort           causal sliding-window transformer body
  adapter.ort           encoder → decoder dimension projection
  cross_kv.ort          precomputed cross-attention K/V per decoder layer
  decoder_kv.ort        one decoder step with self-attention KV cache
  streaming_config.json architecture parameters for the C runtime
  tokenizer.bin
```

The generated `streaming_config.json` for `tiny-streaming` (all values derived automatically
from `config.json`):

```json
{
  "encoder_dim": 320,  "decoder_dim": 320,  "depth": 6,
  "nheads": 8,  "head_dim": 40,  "vocab_size": 32768,
  "bos_id": 1,  "eos_id": 2,  "frame_len": 80,  "total_lookahead": 16,
  "d_model_frontend": 320,  "c1": 640,  "c2": 320,
  "frontend_state_shapes": {
    "sample_buffer": [1, 79],  "sample_len": [1],
    "conv1_buffer": [1, 640, 4],  "conv2_buffer": [1, 320, 4],  "frame_count": [1]
  }
}
```

For `medium-streaming`: `encoder_dim=768`, `decoder_dim=640`, `depth=14`, `nheads=10`,
`head_dim=64`, `c1=1536`, `c2=768`.

**`mic_transcriber_it.py` options**

```
--model-dir        Path to ORT model directory (non-streaming or streaming)
--streaming        Use TINY_STREAMING or MEDIUM_STREAMING arch  [default: TINY]
--medium           Select MEDIUM_STREAMING instead of TINY_STREAMING (with --streaming)
--device           sounddevice input device index               [default: system default]
--update-interval  Transcription update interval in seconds     [default: 0.5]
```

---

### Option B — HuggingFace ONNX runtime (no ORT conversion needed)

Works directly from the `onnx/` directory produced by `--export-onnx`. Slightly slower than
option A but requires no extra steps.

```bash
pip install optimum[onnxruntime]
```

```python
from optimum.onnxruntime import ORTModelForSpeechSeq2Seq
from transformers import AutoProcessor
import soundfile as sf

model_dir = "./output/moonshine-it-tiny-streaming/onnx"
processor = AutoProcessor.from_pretrained(model_dir)
model = ORTModelForSpeechSeq2Seq.from_pretrained(model_dir)

audio, sr = sf.read("audio_italiano.wav")
inputs = processor(audio, sampling_rate=sr, return_tensors="pt")
ids = model.generate(**inputs)
print(processor.batch_decode(ids, skip_special_tokens=True)[0])
```

---

### Option C — HuggingFace PyTorch (for evaluation / fine-tuning iteration)

```python
from transformers import AutoProcessor, MoonshineForConditionalGeneration
import soundfile as sf

model_dir = "./output/moonshine-it-tiny-streaming/final"
processor = AutoProcessor.from_pretrained(model_dir)
model = MoonshineForConditionalGeneration.from_pretrained(model_dir)

audio, sr = sf.read("audio_italiano.wav")
inputs = processor(audio, sampling_rate=sr, return_tensors="pt")
ids = model.generate(**inputs)
print(processor.batch_decode(ids, skip_special_tokens=True)[0])
```

---

## Expected results

Based on community results for comparable fine-tuning runs (French, ~60 h data):

| Dataset size | Model | Expected Italian WER |
|---|---|---|
| ~10 h (FLEURS only) | tiny-streaming | ~35–45 % |
| ~100 h (CV + FLEURS) | tiny-streaming | ~18–25 % |
| ~200 h (CV + FLEURS) | tiny-streaming | ~14–20 % |
| ~200 h (CV + FLEURS) | medium-streaming | ~10–15 % |
| ~440 h (all sources) | medium-streaming | ~8–12 % |

WER varies significantly with audio quality, domain, and speaker diversity in your dataset.

---

## Troubleshooting

**`ValueError: Common Voice requires a HuggingFace token`**
→ Pass `--hf-token hf_xxx` and make sure you have accepted the dataset terms on HuggingFace.

**`CUDA out of memory`**
→ See the [VRAM reduction tips](#vram-reduction-tips) section above.

**`transformers` reports no `MoonshineForConditionalGeneration`**
→ You need `transformers >= 4.48.0`. Run `pip install --upgrade transformers`.

**Training WER is stuck above 80 %**
→ The tokenizer language prefix may not have been set. This is a known issue if the base model
  uses an English-only tokenizer; try `--skip-curriculum` for the first 500 steps with a very
  low learning rate (`--learning-rate 1e-5`) to warm up the decoder, then resume normally.

**`optimum-cli: command not found`**
→ Install with `pip install optimum[exporters]`.

**`export_streaming.py`: `AttributeError: encoder.conv1 not found`**
→ The attribute names for the frontend conv layers differ in your version of transformers.
  Run `python -c "from transformers import MoonshineForConditionalGeneration; m = MoonshineForConditionalGeneration.from_pretrained('<model-dir>'); print(list(m.model.encoder.named_children()))"` to find the correct names, then update `FrontendModule.__init__` in `export_streaming.py`.

**`export_streaming.py`: `AttributeError: cannot find adapter projection`**
→ For `tiny-streaming` (encoder_dim == decoder_dim == 320), the adapter is an identity and
  this error should not appear. For `medium-streaming` (768 → 640), the adapter projection
  attribute name may differ. Inspect `model.named_children()` and update `AdapterModule.__init__`.

**`mic_transcriber_it.py --streaming` crashes with "invalid model arch"**
→ The streaming `.ort` files may be missing or misnamed. Verify the output of `export_streaming.py`
  contains all seven files. Re-run without `--streaming` to confirm the non-streaming path works first.

**ROCm: `RuntimeError: HIP error: invalid device function`**
→ The gfx override is missing or wrong. Run `rocminfo | grep gfx` to find your GPU's ISA,
  then set `HSA_OVERRIDE_GFX_VERSION` to the matching value (e.g. `11.0.0` for gfx1100).

**ROCm: training runs but produces NaN loss immediately**
→ Switch from `--bf16` to `--fp16`. Some RDNA2 cards advertise bf16 but produce incorrect
  results in practice. fp16 is reliable on all supported AMD GPUs.

**ROCm: `pip install -r requirements.txt` overwrites the ROCm PyTorch wheel with CUDA**
→ Install the ROCm wheel first (step 2 above), then pin torch in requirements.txt or pass
  `--extra-index-url https://download.pytorch.org/whl/rocm6.2` when installing the rest.

---

## Task quick-reference

```bash
task --list   # show all targets with descriptions
```

| Task | Description |
|---|---|
| `task download` | Download FLEURS (+ Common Voice if `HF_TOKEN` is set) |
| `task download:full` | Download all sources including MLS (~440 h) |
| `task train:tiny` | Fine-tune tiny-streaming, export ONNX |
| `task train:medium` | Fine-tune medium-streaming, export ONNX |
| `task train:tiny:resume` | Resume tiny-streaming from latest checkpoint |
| `task train:medium:resume` | Resume medium-streaming from latest checkpoint |
| `task export:ort:tiny` | Convert tiny ONNX → ORT + copy `tokenizer.bin` |
| `task export:ort:medium` | Convert medium ONNX → ORT + copy `tokenizer.bin` |
| `task export:streaming:tiny` | Export tiny to 5-component streaming ORT |
| `task export:streaming:medium` | Export medium to 5-component streaming ORT |
| `task all:tiny` | Full pipeline: download → train → export tiny |
| `task all:medium` | Full pipeline: download → train → export medium |
| `task run:tiny` | Run mic transcriber, tiny non-streaming |
| `task run:tiny:streaming` | Run mic transcriber, tiny streaming |
| `task run:medium` | Run mic transcriber, medium non-streaming |
| `task run:medium:streaming` | Run mic transcriber, medium streaming |

Pass extra arguments to any `train:*` or `run:*` task with `--`:
```bash
task train:tiny -- --fp16 --eval-steps 200
task run:tiny:streaming -- --device 2 --update-interval 0.3
```

---

## References

- [Moonshine GitHub](https://github.com/moonshine-ai/moonshine)
- [Moonshine paper (arXiv:2410.15608)](https://arxiv.org/abs/2410.15608)
- [Moonshine v2 streaming paper (arXiv:2602.12241)](https://arxiv.org/abs/2602.12241)
- [Flavors of Moonshine — monolingual models (arXiv:2509.0553)](https://arxiv.org/abs/2509.0553)
- [Community fine-tuning reference (pierre-cheneau)](https://github.com/pierre-cheneau/finetune-moonshine-asr)
- [UsefulSensors models on HuggingFace](https://huggingface.co/UsefulSensors)
