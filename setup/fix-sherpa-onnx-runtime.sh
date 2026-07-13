#!/bin/bash
# sherpa-onnx==1.13.3's aarch64 wheel does NOT bundle libonnxruntime.so — it
# dlopens an unversioned "libonnxruntime.so" that must define ELF symbol-version
# node VERS_1.24.4 (onnxruntime tags each release's exported symbols with its
# own version string, so only the exact matching pip release satisfies it —
# neither the apt libonnxruntime1.21 package nor newer onnxruntime pip
# releases work). See pyproject.toml's dependencies comment.
#
# uv installs onnxruntime==1.24.4 into site-packages, but pip's onnxruntime
# wheel only ships the versioned filename (libonnxruntime.so.1.24.4) — no
# unversioned symlink. This script creates that symlink inside
# sherpa_onnx.libs/, which is already on _sherpa_onnx.so's RPATH
# ($ORIGIN/../../sherpa_onnx.libs), so no LD_LIBRARY_PATH is needed anywhere.
#
# Idempotent — safe to re-run after every `uv sync` (pip reinstalling the
# sherpa-onnx wheel wipes sherpa_onnx.libs/, which drops this symlink).
# No-op if sherpa-onnx / onnxruntime aren't installed.

set -u

VENV="${1:-.venv}"

SITE_PACKAGES=$("$VENV/bin/python3" -c "import sysconfig; print(sysconfig.get_paths()['purelib'])" 2>/dev/null)
if [ -z "$SITE_PACKAGES" ]; then
  echo "fix-sherpa-onnx-runtime: could not resolve venv site-packages (missing $VENV?) — skipping"
  exit 0
fi

LIBS_DIR="$SITE_PACKAGES/sherpa_onnx.libs"
if [ ! -d "$LIBS_DIR" ]; then
  echo "fix-sherpa-onnx-runtime: sherpa_onnx not installed — skipping"
  exit 0
fi

ORT_SO=$(find "$SITE_PACKAGES/onnxruntime/capi" -maxdepth 1 -name 'libonnxruntime.so.*' 2>/dev/null | sort -V | tail -1)
if [ -z "$ORT_SO" ]; then
  echo "fix-sherpa-onnx-runtime: onnxruntime not installed — skipping"
  exit 0
fi

ln -sf "../onnxruntime/capi/$(basename "$ORT_SO")" "$LIBS_DIR/libonnxruntime.so"
echo "fix-sherpa-onnx-runtime: linked $LIBS_DIR/libonnxruntime.so -> $(basename "$ORT_SO")"
