#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="$ROOT/share/locale"

python3 "$ROOT/scripts/generate_po.py"
mkdir -p "$OUT_DIR"

for po in "$ROOT"/po/*.po; do
  lang="$(basename "$po" .po)"
  dest="$OUT_DIR/$lang/LC_MESSAGES"
  mkdir -p "$dest"
  msgfmt -o "$dest/lcr.mo" "$po"
  echo "Compiled $lang -> $dest/lcr.mo"
done
