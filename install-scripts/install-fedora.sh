#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

sudo dnf install -y python3 python3-pip python3-tkinter portaudio-devel alsa-plugins-pulseaudio
sudo python3 -m pip install --break-system-packages -r "$SCRIPT_DIR/requirements.txt"

echo "Dependencies installed. Run: python3 $SCRIPT_DIR/ternet_gui.py"