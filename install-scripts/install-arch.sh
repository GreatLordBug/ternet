#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

sudo pacman -S --needed --noconfirm python python-pip tk portaudio pulseaudio-alsa
sudo python -m pip install --break-system-packages -r "$SCRIPT_DIR/requirements.txt"

echo "Dependencies installed. Run: python $SCRIPT_DIR/ternet_gui.py"