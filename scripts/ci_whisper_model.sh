#!/usr/bin/env bash
set -euo pipefail
model_path="${CUPLIK_TEST_MODEL:-$HOME/.cache/cuplik/ggml-tiny.bin}"
expected=be07e048e1e599ad46341c8d2a135645097a538221678b7acdd1b1919c6e1b21
mkdir -p "$(dirname "$model_path")"
valid_model() { printf '%s  %s\n' "$expected" "$1" | sha256sum --check --status; }
if [[ ! -f "$model_path" ]] || ! valid_model "$model_path"; then
  temporary="${model_path}.download"
  trap 'rm -f "$temporary"' EXIT
  timeout 420s curl --fail --location --connect-timeout 20 --max-time 180 --retry 2 --retry-delay 2 --retry-max-time 360 --max-filesize 80000000 \
    https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-tiny.bin -o "$temporary"
  valid_model "$temporary"
  mv "$temporary" "$model_path"
fi
mkdir -p android/app/src/androidTest/assets
cp "$model_path" android/app/src/androidTest/assets/ggml-tiny.bin
echo 'Whisper test model checksum verified.'
