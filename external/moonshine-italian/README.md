# Moonshine Italian STT — Fine-tuning scripts

Fine-tune [Moonshine](https://github.com/moonshine-ai/moonshine) streaming ASR models for Italian.
Produces `moonshine-tiny-streaming` and `moonshine-medium-streaming` models ready to drop into
the Moonshine C++ runtime.

---

## Overview

Moonshine does not ship Italian ASR models out of the box. These scripts:

1. **`download_dataset.py`** — downloads and merges Italian speech datasets from HuggingFace,
   resamples audio to 16 kHz, normalises transcripts, and saves a combined dataset to disk.

2. **`train.py`** — fine-tunes a pretrained English Moonshine streaming model on the Italian
   dataset using curriculum learning (short clips → medium → full), then optionally exports to
   ONNX for deployment.

### Models targeted

| Variant | Base checkpoint | Params | VRAM needed | Est. training time |
|---|---|---|---|---|
| `tiny-streaming` | `UsefulSensors/moonshine-tiny-streaming` | 34 M | ~6 GB | ~12 h on RTX 3060 |
| `medium-streaming` | `UsefulSensors/moonshine-medium-streaming` | 245 M | ~24 GB | ~72 h on A100 40 GB |

Training starts from the English checkpoint and adapts it to Italian via supervised fine-tuning
(cross-entropy loss on the decoder token sequence). No training from scratch.

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

### HuggingFace account

Mozilla Common Voice requires acceptance of its terms on HuggingFace and a user access token.
FLEURS and MLS do not require authentication.

To create a token:
1. Sign up at [huggingface.co](https://huggingface.co).
2. Go to **Settings → Access Tokens → New token** (read-only scope is sufficient).
3. Accept the [Common Voice 17.0 terms](https://huggingface.co/datasets/mozilla-foundation/common_voice_17_0).

---

## Step 1 — Download the dataset

`download_dataset.py` supports three Italian speech sources:

| Source | Flag | Size | Auth |
|---|---|---|---|
| Mozilla Common Voice 17 | `common_voice` | ~200 h validated | HF token required |
| Google FLEURS | `fleurs` | ~10 h | None |
| Multilingual LibriSpeech | `mls` | ~230 h | None |

### Quickstart (no auth, FLEURS only)

Suitable for smoke-testing the pipeline. ~10 h of data.

```bash
python download_dataset.py --sources fleurs
```

### Recommended (~210 h)

```bash
python download_dataset.py \
    --sources common_voice fleurs \
    --hf-token hf_YOUR_TOKEN_HERE
```

### Maximum coverage (~440 h)

```bash
python download_dataset.py \
    --sources common_voice fleurs mls \
    --hf-token hf_YOUR_TOKEN_HERE
```

### Options

```
--sources          One or more of: common_voice fleurs mls  [default: common_voice fleurs]
--output-dir       Where to write the merged dataset        [default: ./data/italian]
--cache-dir        HuggingFace download cache               [default: ./data/.hf_cache]
--hf-token         HuggingFace access token
--num-proc         CPU workers for text normalisation        [default: 4]
```

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

`train.py` fine-tunes either `tiny-streaming` or `medium-streaming` using curriculum learning.

### Curriculum learning

Training proceeds in three phases, each restricting the dataset to a duration window:

| Phase | Duration window | Default steps | Advance when WER < |
|---|---|---|---|
| `short` | 0.5 – 6 s | 2 000 | 50 % |
| `medium` | 2 – 12 s | 4 000 | 35 % |
| `full` | 0.5 – 20 s | remaining | — |

Short clips are easier to overfit correctly; starting there accelerates convergence before the
model is exposed to longer, noisier samples.

### Tiny streaming

Fits on a single 12 GB GPU (RTX 3060/3080, RTX 4060/4070 Ti, etc.).

```bash
python train.py \
    --dataset-dir ./data/italian/combined \
    --model tiny-streaming
```

Mixed precision is auto-detected (bf16 on Ampere+, fp16 otherwise). Gradient checkpointing is
on by default.

Effective batch size: `8 (per-device) × 8 (accumulation) = 64`.

### Medium streaming

Requires ≥ 24 GB VRAM. Reduce `per-device-batch-size` to 1 if you only have 24 GB.

```bash
python train.py \
    --dataset-dir ./data/italian/combined \
    --model medium-streaming \
    --per-device-batch-size 2 \
    --gradient-accumulation 32
```

### With ONNX export

Automatically exports the final model to ONNX after training, ready for the Moonshine runtime:

```bash
python train.py \
    --dataset-dir ./data/italian/combined \
    --model tiny-streaming \
    --export-onnx
```

### With TensorBoard

```bash
python train.py \
    --dataset-dir ./data/italian/combined \
    --model tiny-streaming \
    --tensorboard

# In a separate terminal:
tensorboard --logdir ./output/moonshine-it-tiny-streaming
```

### Resume after interruption

Each curriculum phase saves checkpoints every `--eval-steps` steps. Resume from the last one:

```bash
python train.py \
    --dataset-dir ./data/italian/combined \
    --model tiny-streaming \
    --resume-from-checkpoint ./output/moonshine-it-tiny-streaming/phase-medium/checkpoint-1500
```

### All options

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
    decoder_model_merged.onnx
    ...
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

## Manual ONNX export

If you skipped `--export-onnx` during training, export at any time:

```bash
optimum-cli export onnx \
    --model ./output/moonshine-it-tiny-streaming/final \
    --task automatic-speech-recognition-with-past \
    ./output/moonshine-it-tiny-streaming/onnx
```

---

## Using the trained model

### Python (HuggingFace transformers)

```python
from transformers import AutoProcessor, MoonshineForConditionalGeneration
import soundfile as sf

processor = AutoProcessor.from_pretrained("./output/moonshine-it-tiny-streaming/final")
model = MoonshineForConditionalGeneration.from_pretrained(
    "./output/moonshine-it-tiny-streaming/final"
)

audio, sr = sf.read("audio_italiano.wav")
inputs = processor(audio, sampling_rate=sr, return_tensors="pt")
predicted_ids = model.generate(**inputs)
transcript = processor.batch_decode(predicted_ids, skip_special_tokens=True)[0]
print(transcript)
```

### Moonshine C++ runtime (ONNX)

Place the contents of the `onnx/` directory alongside a `tokenizer.bin` and
`streaming_config.json` (copy from the original English model directory) and load with the
standard Moonshine C API or Python bindings.

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

## References

- [Moonshine GitHub](https://github.com/moonshine-ai/moonshine)
- [Moonshine paper (arXiv:2410.15608)](https://arxiv.org/abs/2410.15608)
- [Moonshine v2 streaming paper (arXiv:2602.12241)](https://arxiv.org/abs/2602.12241)
- [Flavors of Moonshine — monolingual models (arXiv:2509.0553)](https://arxiv.org/abs/2509.0553)
- [Community fine-tuning reference (pierre-cheneau)](https://github.com/pierre-cheneau/finetune-moonshine-asr)
- [UsefulSensors models on HuggingFace](https://huggingface.co/UsefulSensors)
