# TERNET GUI

`ternet_gui.py` is a Tk-based TERNET audio generator. It uses NumPy for signal generation and PortAudio for playback.

## WHAT IS

TERNET GUI is a small Linux desktop application for generating and playing audio tones. It supports configurable tone frequencies, Morse code generation, and adjustable Morse speed through a simple Tk-based interface.

It is built for experimenting with sound, signals, and terminal-inspired communication. It can also be a messaging service, but only for the nerdiest.

## HOW TO TALK
### DEPENDENCIES:
AFSK Decoder (Like SeaTTY) or knowledge of Morse Code (CW)
Internet audio streaming service, 2 really long aux chords, or Radio transciver (if using an FCC allowed mode like DTTY or CW)
Something that lets you add custom sinks to your audio drivers (like pulseaudio-utils)
The steps listed here will be for using Icecast, Broadcast Using This Tool (BUTT), and pactl and SeaTTY, assuming all are installed. When using SeaTTY, use Wine.
### STEPS
1. Start streaming your icecast stream on both computers
2. Open the other computer's icecast stream in a web browser
3. Run ternet_gui.py on both computers
4. Start SeaTTY on both computers
5. In terminal, run the following command on both computers
``` bash
pactl load-module module-null-sink sink_name=BlackHole sink_properties=device.description="BlackHole"
```
6. Set the following to the following sinks on both computers
`ALSA plug-in (python3.14) > BlackHole`
`SeaTTY > Monitor of [default]`
`Firefox > [default]`
`BUTT > Monitor of BlackHole`
## Install

Run the installer matching your Linux distribution base from this directory:

```bash
./install-debian.sh   # Debian, Ubuntu, Linux Mint
./install-arch.sh     # Arch, EndeavourOS, Manjaro
./install-fedora.sh   # Fedora and compatible distributions
```

The scripts install native audio/Tk packages with the distribution package manager and install Python packages from `requirements.txt` using --break-system-packages`, as requested. The scripts may ask for your sudo password.

The native packages include the PulseAudio-to-ALSA bridge required by PortAudio on Linux.

## Run

```bash
python3 ternet_gui.py
```

If your distribution provides a separate Python command, use `python` instead
of `python3`.

## Manual install

Install the native packages listed in the matching script, then run:

```bash
sudo python3 -m pip install --break-system-packages -r requirements.txt
python3 ternet_gui.py
```

The application can still start without `customtkinter`; it falls back to the
standard Tk widgets. Audio playback prefers the PulseAudio device and falls
back to PipeWire when PulseAudio is unavailable. Selecting `MORSE` generates
real dot-and-dash tones; set the tone frequency and speed in the `Morse tone (Hz)`
and `Morse speed (WPM)` fields.