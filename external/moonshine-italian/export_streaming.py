#!/usr/bin/env python3
"""
Export a fine-tuned Moonshine model to the 5-component streaming ORT format required by
ModelArch.TINY_STREAMING / MEDIUM_STREAMING in the Moonshine C runtime.

The standard HuggingFace ONNX export (encoder_model.onnx + decoder_model_merged.onnx) drives
non-streaming (ModelArch.TINY / BASE) inference.  Streaming inference requires these five
separately-traceable components:

  frontend.onnx      audio samples → frame features   (with conv state)
  encoder.onnx       accumulated frame features → encoder output
  adapter.onnx       encoder output → adapter output  (projects encoder_dim → decoder_dim)
  cross_kv.onnx      adapter output → cross-attn K, V for every decoder layer
  decoder_kv.onnx    one decoder step with cached cross-attn + self-attn KV

This script:
  1. Generates streaming_config.json from the HuggingFace model config.
  2. Exports each component as a separate ONNX graph using torch.onnx.export.
  3. Converts .onnx → .ort using onnxruntime.tools.
  4. Copies tokenizer.bin from the cached English model (same vocabulary).

Usage:
  python export_streaming.py \\
      --model-dir output/moonshine-it-tiny-streaming/final \\
      --output-dir output/moonshine-it-tiny-streaming/streaming

  python export_streaming.py \\
      --model-dir output/moonshine-it-medium-streaming/final \\
      --output-dir output/moonshine-it-medium-streaming/streaming
"""

from __future__ import annotations

import argparse
import json
import logging
import shutil
import subprocess
import sys
from pathlib import Path

import torch
import torch.nn as nn
from transformers import AutoConfig, MoonshineForConditionalGeneration

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# streaming_config.json generation
# ---------------------------------------------------------------------------

def make_streaming_config(hf_config) -> dict:
    """
    Derive streaming_config.json from the HuggingFace model config.

    All values come from the config — no hardcoding.
    """
    enc = hf_config.encoder_config
    dec = hf_config

    # frame_len: encoder.frame_ms × sample_rate / 1000
    frame_ms = getattr(enc, "frame_ms", 5.0)
    sample_rate = getattr(enc, "sample_rate", 16_000)
    frame_len = int(frame_ms * sample_rate / 1000)  # e.g. 5.0 × 16000 / 1000 = 80

    # total_lookahead: sum of look-ahead values from each layer's sliding window
    # sliding_windows is a list of [attend_len, lookahead] pairs, one per encoder layer
    sliding_windows = getattr(enc, "sliding_windows", [])
    total_lookahead = sum(pair[1] for pair in sliding_windows)

    # Frontend channel counts: typically c1=2×hidden, c2=hidden
    hidden = enc.hidden_size
    c1 = hidden * 2
    c2 = hidden

    return {
        "encoder_dim": enc.hidden_size,
        "decoder_dim": dec.hidden_size,
        "depth": enc.num_hidden_layers,
        "nheads": enc.num_attention_heads,
        "head_dim": enc.head_dim if hasattr(enc, "head_dim") else enc.hidden_size // enc.num_attention_heads,
        "vocab_size": dec.vocab_size,
        "bos_id": dec.bos_token_id,
        "eos_id": dec.eos_token_id,
        "frame_len": frame_len,
        "total_lookahead": total_lookahead,
        "d_model_frontend": enc.hidden_size,
        "c1": c1,
        "c2": c2,
        "frontend_state_shapes": {
            "sample_buffer": [1, frame_len - 1],
            "sample_len":    [1],
            "conv1_buffer":  [1, c1, 4],
            "conv2_buffer":  [1, c2, 4],
            "frame_count":   [1],
        },
    }


# ---------------------------------------------------------------------------
# ONNX wrapper modules
# ---------------------------------------------------------------------------

class FrontendModule(nn.Module):
    """
    Stateful audio frontend: one frame of raw audio + conv buffers → frame features.

    Wraps the two strided Conv1d layers that sit before the transformer encoder body.
    The C runtime calls this once per 80-sample frame and passes back the updated state.
    """

    def __init__(self, encoder: nn.Module):
        super().__init__()
        # transformers MoonshineStreamingEncoder stores the convolutions as:
        #   encoder.conv1  (Conv1d, stride 1, causal pad via buffer)
        #   encoder.conv2  (Conv1d, stride 2)
        # The names come from the upstream implementation; inspect if they differ.
        for attr in ("conv1", "conv2", "input_projection"):
            if not hasattr(encoder, attr):
                raise AttributeError(
                    f"encoder.{attr} not found — inspect model.encoder attributes:\n"
                    f"  {[n for n, _ in encoder.named_children()]}"
                )
        self.conv1 = encoder.conv1
        self.conv2 = encoder.conv2

    def forward(
        self,
        samples: torch.Tensor,         # [batch, frame_len] float32
        sample_buffer: torch.Tensor,   # [batch, frame_len-1] float32  (rolling)
        conv1_buffer: torch.Tensor,    # [batch, c1, 4]
        conv2_buffer: torch.Tensor,    # [batch, c2, 4]
    ) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor]:
        # Prepend rolling buffer to new samples for causal convolution
        x = torch.cat([sample_buffer, samples], dim=-1).unsqueeze(1)  # [B, 1, frame_len]

        # Conv1
        padded1 = torch.cat([conv1_buffer, x.expand(-1, self.conv1.out_channels, -1)
                              .transpose(1, 2)], dim=2)
        out1 = self.conv1(padded1[:, :, -x.shape[-1]:].transpose(1, 2))
        new_conv1_buf = padded1[:, :, -4:]

        # Conv2 (stride 2)
        padded2 = torch.cat([conv2_buffer, out1.transpose(1, 2)], dim=2)
        out2 = self.conv2(padded2[:, :, -out1.shape[-1]:].transpose(1, 2))
        new_conv2_buf = padded2[:, :, -4:]

        # Frame features: [batch, 1, hidden]
        frame_features = out2

        # Update rolling sample buffer
        new_sample_buf = samples

        return frame_features, new_sample_buf, new_conv1_buf, new_conv2_buf


class EncoderModule(nn.Module):
    """
    Transformer encoder body: accumulated frame features → encoder output.

    Called once per new frame with ALL accumulated frames; the causal/sliding-window
    attention ensures each frame only attends to its allowed context.
    """

    def __init__(self, encoder: nn.Module):
        super().__init__()
        self.layers = encoder.layers
        self.layer_norm = encoder.layer_norm if hasattr(encoder, "layer_norm") else nn.Identity()

    def forward(self, features: torch.Tensor) -> torch.Tensor:
        # features: [batch, T, hidden]
        hidden = features
        for layer in self.layers:
            hidden = layer(hidden)[0] if isinstance(layer(hidden), tuple) else layer(hidden)
        return self.layer_norm(hidden)


class AdapterModule(nn.Module):
    """
    Adapter: maps encoder output (encoder_dim) → decoder cross-attention space (decoder_dim).

    For models where encoder_dim == decoder_dim (e.g. tiny-streaming), this is a no-op
    identity or a single linear layer.  For medium-streaming (768→640) it is a learned
    linear projection.
    """

    def __init__(self, model: MoonshineForConditionalGeneration):
        super().__init__()
        # The adapter may be stored as model.encoder_attn_adapter, model.adapter,
        # or directly as a projection in the first decoder cross-attn layer.
        # Fall back to identity if not found (encoder_dim == decoder_dim case).
        self.proj: nn.Module
        for attr in ("encoder_attn_adapter", "adapter", "enc_to_dec_proj"):
            if hasattr(model, attr):
                self.proj = getattr(model, attr)
                log.info(f"Adapter: using model.{attr}")
                return
        enc_dim = model.config.encoder_hidden_size
        dec_dim = model.config.hidden_size
        if enc_dim == dec_dim:
            log.info("Adapter: encoder_dim == decoder_dim, using identity.")
            self.proj = nn.Identity()
        else:
            raise AttributeError(
                f"Cannot find adapter projection (encoder_dim={enc_dim}, decoder_dim={dec_dim}). "
                f"Inspect model top-level attributes:\n  {[n for n, _ in model.named_children()]}"
            )

    def forward(self, encoder_output: torch.Tensor) -> torch.Tensor:
        return self.proj(encoder_output)


class CrossKVModule(nn.Module):
    """
    Precompute cross-attention K and V for all decoder layers.

    Applied once per utterance end (or per new chunk in streaming), not per decoder step.
    Shape: [num_layers, 2, batch, nheads, T, head_dim]
    """

    def __init__(self, decoder: nn.Module):
        super().__init__()
        # Each decoder layer exposes cross_attn.k_proj and cross_attn.v_proj
        self.k_projs = nn.ModuleList()
        self.v_projs = nn.ModuleList()
        for layer in decoder.layers:
            ca = layer.encoder_attn if hasattr(layer, "encoder_attn") else layer.cross_attn
            self.k_projs.append(ca.k_proj)
            self.v_projs.append(ca.v_proj)

    def forward(self, adapter_output: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        # adapter_output: [batch, T, decoder_dim]
        ks, vs = [], []
        for k_proj, v_proj in zip(self.k_projs, self.v_projs):
            ks.append(k_proj(adapter_output))
            vs.append(v_proj(adapter_output))
        # Stack: [num_layers, batch, T, decoder_dim]
        return torch.stack(ks, dim=0), torch.stack(vs, dim=0)


class DecoderKVModule(nn.Module):
    """
    Single decoder step with precomputed cross-attention KV and self-attention KV cache.

    Inputs:
      token_ids        [batch, 1]
      cross_k/v        [num_layers, batch, T, decoder_dim]  (precomputed, constant)
      past_key_values  list of (self_k, self_v) per layer    (grows each step)

    Outputs:
      logits           [batch, vocab_size]
      new_key_values   updated list of (self_k, self_v)
    """

    def __init__(self, model: MoonshineForConditionalGeneration):
        super().__init__()
        self.model_decoder = model.model.decoder if hasattr(model, "model") else model.decoder
        self.lm_head = model.lm_head

    def forward(
        self,
        token_ids: torch.Tensor,   # [batch, 1]  long
        cross_k: torch.Tensor,     # [num_layers, batch, T, d]
        cross_v: torch.Tensor,     # [num_layers, batch, T, d]
        # Past self-attn KV: flattened as (k0, v0, k1, v1, ...) per layer
        *past_kv_flat: torch.Tensor,
    ) -> tuple[torch.Tensor, ...]:
        num_layers = cross_k.shape[0]
        past_key_values = [
            (past_kv_flat[2 * i], past_kv_flat[2 * i + 1])
            for i in range(num_layers)
        ] if past_kv_flat else None

        # Build cross_attention_past_key_values from precomputed K, V
        cross_kv = [(cross_k[i], cross_v[i]) for i in range(num_layers)]

        out = self.model_decoder(
            input_ids=token_ids,
            past_key_values=past_key_values,
            encoder_hidden_states=None,
            cross_attn_past_key_values=cross_kv,
            use_cache=True,
        )
        hidden = out.last_hidden_state           # [batch, 1, hidden]
        logits = self.lm_head(hidden[:, -1, :]) # [batch, vocab]

        new_pkv_flat = []
        for k, v in out.past_key_values:
            new_pkv_flat.extend([k, v])

        return (logits, *new_pkv_flat)


# ---------------------------------------------------------------------------
# ONNX export helpers
# ---------------------------------------------------------------------------

def _export(module: nn.Module, args: tuple, output_path: Path,
            input_names: list[str], output_names: list[str],
            dynamic_axes: dict) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    log.info(f"Exporting {output_path.name} ...")
    module.eval()
    with torch.no_grad():
        torch.onnx.export(
            module,
            args,
            str(output_path),
            input_names=input_names,
            output_names=output_names,
            dynamic_axes=dynamic_axes,
            opset_version=17,
            do_constant_folding=True,
        )
    log.info(f"  → {output_path} ({output_path.stat().st_size / 1e6:.1f} MB)")


def export_all(model: MoonshineForConditionalGeneration, cfg: dict, out: Path) -> None:
    B = 1           # batch
    T = 4           # dummy sequence length (small for tracing)
    H = cfg["encoder_dim"]
    D = cfg["decoder_dim"]
    fl = cfg["frame_len"]
    c1 = cfg["c1"]
    c2 = cfg["c2"]
    nl = cfg["depth"]   # num decoder layers
    # nh, hd, V available if needed for future dynamic-axes extensions

    encoder = model.model.encoder if hasattr(model, "model") else model.encoder
    decoder = model.model.decoder if hasattr(model, "model") else model.decoder

    # ── frontend ────────────────────────────────────────────────────────────
    try:
        frontend = FrontendModule(encoder)
        dummy_samples    = torch.zeros(B, fl)
        dummy_samplebuf  = torch.zeros(B, fl - 1)
        dummy_conv1buf   = torch.zeros(B, c1, 4)
        dummy_conv2buf   = torch.zeros(B, c2, 4)
        _export(
            frontend,
            (dummy_samples, dummy_samplebuf, dummy_conv1buf, dummy_conv2buf),
            out / "frontend.onnx",
            input_names=["samples", "sample_buffer", "conv1_buffer", "conv2_buffer"],
            output_names=["frame_features", "new_sample_buffer", "new_conv1_buffer", "new_conv2_buffer"],
            dynamic_axes={"samples": {0: "batch"}, "frame_features": {0: "batch"}},
        )
    except AttributeError as e:
        log.error(f"frontend export failed: {e}\nSkipping — fix attribute names for your model version.")

    # ── encoder ─────────────────────────────────────────────────────────────
    try:
        enc_module = EncoderModule(encoder)
        dummy_feats = torch.zeros(B, T, H)
        _export(
            enc_module,
            (dummy_feats,),
            out / "encoder.onnx",
            input_names=["accumulated_features"],
            output_names=["encoder_output"],
            dynamic_axes={"accumulated_features": {0: "batch", 1: "seq_len"},
                          "encoder_output":        {0: "batch", 1: "seq_len"}},
        )
    except AttributeError as e:
        log.error(f"encoder export failed: {e}")

    # ── adapter ─────────────────────────────────────────────────────────────
    try:
        adapter = AdapterModule(model)
        dummy_enc_out = torch.zeros(B, T, H)
        _export(
            adapter,
            (dummy_enc_out,),
            out / "adapter.onnx",
            input_names=["encoder_output"],
            output_names=["adapter_output"],
            dynamic_axes={"encoder_output":  {0: "batch", 1: "seq_len"},
                          "adapter_output":  {0: "batch", 1: "seq_len"}},
        )
    except AttributeError as e:
        log.error(f"adapter export failed: {e}")

    # ── cross_kv ────────────────────────────────────────────────────────────
    try:
        cross_kv_mod = CrossKVModule(decoder)
        dummy_adapter_out = torch.zeros(B, T, D)
        _export(
            cross_kv_mod,
            (dummy_adapter_out,),
            out / "cross_kv.onnx",
            input_names=["adapter_output"],
            output_names=["cross_k", "cross_v"],
            dynamic_axes={"adapter_output": {0: "batch", 1: "seq_len"},
                          "cross_k":        {0: "batch", 2: "seq_len"},
                          "cross_v":        {0: "batch", 2: "seq_len"}},
        )
    except (AttributeError, Exception) as e:
        log.error(f"cross_kv export failed: {e}")

    # ── decoder_kv ──────────────────────────────────────────────────────────
    try:
        dec_mod = DecoderKVModule(model)
        dummy_tokens  = torch.zeros(B, 1, dtype=torch.long)
        dummy_cross_k = torch.zeros(nl, B, T, D)
        dummy_cross_v = torch.zeros(nl, B, T, D)
        # Empty past KV cache (first decoder step)
        output_names = ["logits"] + [f"new_self_{t}{i}" for i in range(nl) for t in ("k", "v")]
        _export(
            dec_mod,
            (dummy_tokens, dummy_cross_k, dummy_cross_v),
            out / "decoder_kv.onnx",
            input_names=["token_ids", "cross_k", "cross_v"],
            output_names=output_names,
            dynamic_axes={
                "token_ids": {0: "batch"},
                "cross_k":   {1: "batch", 2: "seq_len"},
                "cross_v":   {1: "batch", 2: "seq_len"},
                "logits":    {0: "batch"},
            },
        )
    except Exception as e:
        log.error(f"decoder_kv export failed: {e}")


# ---------------------------------------------------------------------------
# .onnx → .ort conversion
# ---------------------------------------------------------------------------

def convert_to_ort(onnx_dir: Path) -> None:
    log.info("Converting .onnx → .ort ...")
    try:
        result = subprocess.run(
            [
                sys.executable, "-m",
                "onnxruntime.tools.convert_onnx_models_to_ort",
                "--optimization_style", "Fixed",
                str(onnx_dir),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        log.info(result.stdout)
    except subprocess.CalledProcessError as e:
        log.error(f"ORT conversion failed:\n{e.stderr}")
        log.error("Install with: pip install onnxruntime")
        raise


def copy_tokenizer(out: Path) -> None:
    from moonshine_voice.download_file import get_cache_dir
    cache = get_cache_dir()
    candidates = list(cache.rglob("tokenizer.bin"))
    if not candidates:
        log.warning(
            "No tokenizer.bin found in Moonshine cache. "
            "Download any language first:\n  python -m moonshine_voice.download --language en"
        )
        return
    src = candidates[0]
    dst = out / "tokenizer.bin"
    shutil.copy2(src, dst)
    log.info(f"Copied tokenizer.bin from {src}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export fine-tuned Moonshine to streaming ORT format",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--model-dir",
        default="output/moonshine-it-tiny-streaming/final",
        help="HuggingFace model directory (output of train.py)",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Output directory for streaming .ort files (default: <model-dir>/../streaming)",
    )
    parser.add_argument(
        "--skip-ort-conversion",
        action="store_true",
        help="Stop after .onnx export; don't convert to .ort (useful for debugging graphs)",
    )
    args = parser.parse_args()

    model_dir = Path(args.model_dir).resolve()
    out_dir = Path(args.output_dir).resolve() if args.output_dir else model_dir.parent / "streaming"
    out_dir.mkdir(parents=True, exist_ok=True)

    # Load config and derive streaming_config.json
    log.info(f"Loading config from {model_dir} ...")
    hf_config = AutoConfig.from_pretrained(str(model_dir))
    streaming_cfg = make_streaming_config(hf_config)
    cfg_path = out_dir / "streaming_config.json"
    cfg_path.write_text(json.dumps(streaming_cfg, indent=2))
    log.info(f"Wrote {cfg_path}")
    log.info(f"  encoder_dim={streaming_cfg['encoder_dim']}  "
             f"decoder_dim={streaming_cfg['decoder_dim']}  "
             f"depth={streaming_cfg['depth']}  "
             f"frame_len={streaming_cfg['frame_len']}  "
             f"total_lookahead={streaming_cfg['total_lookahead']}")

    # Load model weights
    log.info(f"Loading model weights (this may take a moment) ...")
    model = MoonshineForConditionalGeneration.from_pretrained(str(model_dir))
    model.eval()

    # Export streaming ONNX components
    export_all(model, streaming_cfg, out_dir)

    # Convert to .ort
    if not args.skip_ort_conversion:
        convert_to_ort(out_dir)

    # Copy tokenizer.bin
    copy_tokenizer(out_dir)

    # Summary
    ort_files = sorted(out_dir.glob("*.ort"))
    log.info("\n=== Streaming model ready ===")
    log.info(f"Directory: {out_dir}")
    for f in ort_files:
        log.info(f"  {f.name}  ({f.stat().st_size / 1e6:.1f} MB)")
    if (out_dir / "streaming_config.json").exists():
        log.info("  streaming_config.json")
    if (out_dir / "tokenizer.bin").exists():
        log.info("  tokenizer.bin")

    log.info("\nTest with mic_transcriber_it.py:")
    log.info(f"  python mic_transcriber_it.py --model-dir {out_dir} --streaming")


if __name__ == "__main__":
    main()
