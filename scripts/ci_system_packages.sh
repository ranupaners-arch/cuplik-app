#!/usr/bin/env bash
# Avoid refreshing every system repository when the runner already has our tools.
set -euo pipefail
missing_packages=()
for package in "$@"; do
  case "$package" in
    ffmpeg|redis-server|espeak-ng) ;;
    *) echo "Unsupported CI package: $package" >&2; exit 2 ;;
  esac
  if ! command -v "$package" >/dev/null 2>&1; then
    missing_packages+=("$package")
  fi
done
if ((${#missing_packages[@]} == 0)); then
  echo 'Required system tools are already available.'
  exit 0
fi
apt_options=(-o Acquire::Retries=2 -o Acquire::http::Timeout=20 -o Acquire::https::Timeout=20)
timeout 240s sudo apt-get "${apt_options[@]}" update
timeout 240s sudo env DEBIAN_FRONTEND=noninteractive apt-get "${apt_options[@]}" install --no-install-recommends -y "${missing_packages[@]}"
for package in "$@"; do command -v "$package" >/dev/null; done
