import re
import threading
import time
import wave
from pathlib import Path

import numpy as np
import sounddevice as sd
import tkinter as tk
from tkinter import messagebox, ttk

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib

try:
    import customtkinter as ctk
except Exception:  # pragma: no cover
    ctk = None


SAMPLE_RATE = 48000
CHUNKS_PER_BUFFER = 1024
DEFAULT_STANDARD_NAME = "TERNET"

AFSK_STANDARDS_TOML = """
[EAS]
BAUD = 520.8333
MARK = 2083.33
SPAC = 1562.5
MOAS = "ASCII"
PRBY = "11010101"
PRTI = 16

[SAME]
BAUD = 520.8333
MARK = 2083.33
SPAC = 1562.5
MOAS = "ASCII"
PRBY = "11010101"
PRTI = 16

[TERNET]
BAUD = 520.8333
MARK = 2083.33
SPAC = 1562.5
MOAS = "ASCII"
PRBY = "11010101"
PRTI = 16

[MORSE]
BAUD = 45.45
MARK = 1200.0
SPAC = 800.0
MOAS = "MORSE"
PRBY = "10101010"
PRTI = 2

[RTTY]
BAUD = 45.45
MARK = 2125.0
SPAC = 2295.0
MOAS = "ASCII"
PRBY = "11000011"
PRTI = 2

[BELL103]
BAUD = 300.0
MARK = 2225.0
SPAC = 2025.0
MOAS = "ASCII"
PRBY = "10101010"
PRTI = 3

[BELL202]
BAUD = 1200.0
MARK = 1200.0
SPAC = 2200.0
MOAS = "ASCII"
PRBY = "10101010"
PRTI = 3

[AFSK300]
BAUD = 300.0
MARK = 1270.0
SPAC = 1070.0
MOAS = "ASCII"
PRBY = "10101010"
PRTI = 3

[AFSK600]
BAUD = 600.0
MARK = 1270.0
SPAC = 1070.0
MOAS = "ASCII"
PRBY = "10101010"
PRTI = 3

[AFSK1200]
BAUD = 1200.0
MARK = 1200.0
SPAC = 2200.0
MOAS = "ASCII"
PRBY = "10101010"
PRTI = 3

[AFSK2400]
BAUD = 2400.0
MARK = 1200.0
SPAC = 2200.0
MOAS = "ASCII"
PRBY = "10101010"
PRTI = 3

[FSK31]
BAUD = 31.25
MARK = 1600.0
SPAC = 1300.0
MOAS = "ASCII"
PRBY = "10101010"
PRTI = 3

[V23]
BAUD = 1200.0
MARK = 1300.0
SPAC = 2100.0
MOAS = "ASCII"
PRBY = "10101010"
PRTI = 3

[SEATTY]
BAUD = 1200.0
MARK = 1200.0
SPAC = 2200.0
MOAS = "ASCII"
PRBY = "10101010"
PRTI = 3

[SETTY]
BAUD = 1200.0
MARK = 1200.0
SPAC = 2200.0
MOAS = "ASCII"
PRBY = "10101010"
PRTI = 3

[SATTY]
BAUD = 1200.0
MARK = 1200.0
SPAC = 2200.0
MOAS = "ASCII"
PRBY = "10101010"
PRTI = 3

[TRUEMORSE]
BAUD = 75
MARK = 1000
SPAC = 0
MOAS = "MORSE"
PRBY = "00000000"
PRTI = 0
"""


def _binary_preamble_to_bits(value):
    if value is None:
        return [1, 1, 0, 1, 0, 1, 0, 1]
    if isinstance(value, (int, float)):
        bits = format(int(value) & 0xFF, "08b")
    else:
        bits = str(value).strip().replace("0b", "").replace(" ", "")
        if bits.startswith("0x") or bits.startswith("0X"):
            try:
                bits = format(int(bits, 16) & 0xFF, "08b")
            except ValueError:
                bits = bits[2:]
        bits = re.sub(r"[^01]", "", bits)
    return [int(ch) for ch in bits[:8].zfill(8)]


def _normalize_standard_record(section_name, section):
    if not isinstance(section, dict):
        return {}
    normalized = dict(section)
    normalized["BAUD_RATE"] = normalized.get("BAUD_RATE", normalized.get("BAUD", 0.0))
    normalized["MARK"] = normalized.get("MARK", normalized.get("FREQ_MARK", 0.0))
    normalized["SPACE"] = normalized.get("SPACE", normalized.get("SPAC", normalized.get("FREQ_SPACE", 0.0)))
    normalized["MORSE_ASCII"] = str(normalized.get("MORSE_ASCII", normalized.get("MOAS", "ASCII"))).upper()
    if normalized["MORSE_ASCII"] not in {"ASCII", "MORSE"}:
        normalized["MORSE_ASCII"] = "ASCII"
    normalized["PRBY"] = _binary_preamble_to_bits(normalized.get("PRBY", "11010101"))
    normalized["PRTI"] = int(normalized.get("PRTI", 16))
    return normalized


def load_afsk_standards(path: Path | str | None = None):
    standards = {}
    try:
        data = tomllib.loads(AFSK_STANDARDS_TOML)
        if isinstance(data, dict):
            standards = {name.upper(): _normalize_standard_record(name, values) for name, values in data.items()}
    except Exception:
        standards = {}

    if path is not None:
        try:
            candidate = Path(path)
            if candidate.exists():
                with candidate.open("rb") as fh:
                    raw = tomllib.load(fh)
                if isinstance(raw, dict):
                    for name, values in raw.items():
                        if isinstance(values, dict):
                            standards[str(name).upper()] = _normalize_standard_record(name, values)
        except Exception:
            pass

    return standards


AFSK_STANDARDS = load_afsk_standards()
BAUD_RATE = AFSK_STANDARDS.get("TERNET", {}).get("BAUD_RATE", 520.8333)
FREQ_MARK = AFSK_STANDARDS.get("TERNET", {}).get("MARK", 2083.33)
FREQ_SPACE = AFSK_STANDARDS.get("TERNET", {}).get("SPACE", 1562.5)


def _resolve_standard(standard_name="TERNET"):
    standards = load_afsk_standards()
    key = str(standard_name or "TERNET").strip().upper()
    normalized_key = re.sub(r"[^A-Z0-9]", "", key)
    if normalized_key in {re.sub(r"[^A-Z0-9]", "", name) for name in standards}:
        for name, values in standards.items():
            if re.sub(r"[^A-Z0-9]", "", name) == normalized_key:
                return values
    return standards.get("TERNET", standards.get("EAS", {}))


MORSE_CODE = {
    "A": ".-", "B": "-...", "C": "-.-.", "D": "-..", "E": ".",
    "F": "..-.", "G": "--.", "H": "....", "I": "..", "J": ".---",
    "K": "-.-", "L": ".-..", "M": "--", "N": "-.", "O": "---",
    "P": ".--.", "Q": "--.-", "R": ".-.", "S": "...", "T": "-",
    "U": "..-", "V": "...-", "W": ".--", "X": "-..-", "Y": "-.--",
    "Z": "--..", "0": "-----", "1": ".----", "2": "..---",
    "3": "...--", "4": "....-", "5": ".....", "6": "-....",
    "7": "--...", "8": "---..", "9": "----.", ".": ".-.-.-",
    ",": "--..--", "?": "..--..", "'": ".----.", "!": "-.-.--",
    "/": "-..-.", "(": "-.--.", ")": "-.--.-", "&": ".-...",
    ":": "---...", ";": "-.-.-.", "=": "-...-", "+": ".-.-.",
    "-": "-....-", "_": "..--.-", '"': ".-..-.", "$": "...-..-",
    "@": ".--.-.",
}


def _rtty_ita2_bits_for_char(char, shift_state):
    def _frame_for_code(code):
        return [0] + [((code >> (4 - bit)) & 1) for bit in range(5)] + [1]

    letters = {
        "A": 0b11000,
        "B": 0b10011,
        "C": 0b01110,
        "D": 0b10010,
        "E": 0b10000,
        "F": 0b10110,
        "G": 0b01011,
        "H": 0b00101,
        "I": 0b01100,
        "J": 0b11010,
        "K": 0b11110,
        "L": 0b01001,
        "M": 0b00111,
        "N": 0b00110,
        "O": 0b00011,
        "P": 0b01101,
        "Q": 0b11101,
        "R": 0b01010,
        "S": 0b10100,
        "T": 0b00001,
        "U": 0b11100,
        "V": 0b01111,
        "W": 0b11001,
        "X": 0b10111,
        "Y": 0b10101,
        "Z": 0b10001,
        " ": 0b00100,
        "\n": 0b01000,
        "\r": 0b00010,
    }
    figures = {
        "0": 0b10110,
        "1": 0b11110,
        "2": 0b01110,
        "3": 0b11010,
        "4": 0b10100,
        "5": 0b10010,
        "6": 0b01010,
        "7": 0b00110,
        "8": 0b00101,
        "9": 0b11001,
        ".": 0b01011,
        ",": 0b01100,
        "?": 0b11000,
        "/": 0b10001,
        "-": 0b00111,
        "=": 0b11100,
        ";": 0b11101,
        "!": 0b01101,
        "(": 0b11001,
        ")": 0b01111,
        " ": 0b00100,
    }
    figs_code = 0b11011
    ltrs_code = 0b11111

    if char == "":
        return [], shift_state

    target_char = char.upper()
    if target_char in letters:
        if shift_state != "LETTERS":
            shift_state = "LETTERS"
            return _frame_for_code(ltrs_code), shift_state
        return _frame_for_code(letters[target_char]), shift_state

    if target_char in figures:
        if shift_state != "FIGURES":
            shift_state = "FIGURES"
            return _frame_for_code(figs_code) + _frame_for_code(figures[target_char]), shift_state
        return _frame_for_code(figures[target_char]), shift_state

    if char.isdigit() or char in ".,?/-=;!()":
        if shift_state != "FIGURES":
            shift_state = "FIGURES"
            return _frame_for_code(figs_code) + _frame_for_code(figures.get(char, figures.get("0"))), shift_state
        return _frame_for_code(figures.get(char, figures.get("0"))), shift_state

    if char.isalpha():
        if shift_state != "LETTERS":
            shift_state = "LETTERS"
            return _frame_for_code(ltrs_code) + _frame_for_code(letters.get(target_char, letters["A"])), shift_state
        return _frame_for_code(letters.get(target_char, letters["A"])), shift_state

    return [], shift_state


def is_ternet_mode(standard_name=None):
    key = str(standard_name or DEFAULT_STANDARD_NAME).strip().upper()
    return re.sub(r"[^A-Z0-9]", "", key) == "TERNET"


def normalize_ternet_text(value, standard_name=None, field="header"):
    if value is None:
        return ""
    text = str(value)
    if not is_ternet_mode(standard_name):
        return text
    if field == "footer":
        return text.strip().upper()
    return text


def text_to_bits(text_string, include_siren=True, siren_gothroughs=4, siren_length=16, siren_only=False, standard_name="TERNET"):
    bit_stream = []
    endamble_byte_1 = [0, 0, 0, 0, 0, 0, 0, 0]
    endamble_byte_2 = [1, 1, 1, 1, 1, 1, 1, 1]
    std = _resolve_standard(standard_name)
    mode = str(std.get("MORSE_ASCII", "ASCII")).upper()
    preamble_bits = std.get("PRBY", [1, 1, 0, 1, 0, 1, 0, 1])
    preamble_repeat = int(std.get("PRTI", 16))

    if siren_only:
        for _ in range(int(siren_gothroughs)):
            for _ in range(int(siren_length)):
                bit_stream.extend(endamble_byte_2)
            for _ in range(int(siren_length)):
                bit_stream.extend(endamble_byte_1)
        return bit_stream

    if include_siren:
        for _ in range(int(siren_gothroughs)):
            for _ in range(int(siren_length)):
                bit_stream.extend(endamble_byte_2)
            for _ in range(int(siren_length)):
                bit_stream.extend(endamble_byte_1)

    std_key = str(standard_name or "TERNET").strip().upper()
    if std_key in {"RTTY", "SEATTY", "SETTY", "SATTY", "NAVTEX"}:
        shift_state = "LETTERS"
        for char in text_string:
            rtty_bits, shift_state = _rtty_ita2_bits_for_char(char, shift_state)
            bit_stream.extend(rtty_bits)
        return bit_stream

    for _ in range(max(1, int(preamble_repeat))):
        bit_stream.extend(preamble_bits)

    for char in text_string:
        byte_val = ord(char)
        for i in range(8):
            bit_stream.append((byte_val >> i) & 1)
    return bit_stream


def _wave_samples(phase, frequency, count, waveform="sine"):
    t = np.arange(count) / SAMPLE_RATE
    phase_values = phase + 2 * np.pi * frequency * t
    if str(waveform).lower() == "square":
        wave = np.where(np.sin(phase_values) >= 0, 1.0, -1.0)
    else:
        wave = np.sin(phase_values)
    next_phase = (phase + 2 * np.pi * frequency * count / SAMPLE_RATE) % (2 * np.pi)
    return (wave * 32767).astype(np.int16), next_phase


def generate_afsk_chunk(bit_stream, standard_name="TERNET", waveform="sine"):
    std = _resolve_standard(standard_name)
    mark_freq = float(std.get("MARK", FREQ_MARK))
    space_freq = float(std.get("SPACE", FREQ_SPACE))
    baud = float(std.get("BAUD_RATE", std.get("BAUD", BAUD_RATE)))
    samples_per_bit = max(1, int(SAMPLE_RATE / baud)) if baud else max(1, int(SAMPLE_RATE / BAUD_RATE))
    chunks = []
    phase = 0.0
    for bit in bit_stream:
        f = mark_freq if bit == 1 else space_freq
        chunk, phase = _wave_samples(phase, f, samples_per_bit, waveform)
        chunks.append(chunk)
    return np.concatenate(chunks) if chunks else np.array([], dtype=np.int16)


def _mix_tone_chunks(first_chunk, second_chunk):
    mixed = (first_chunk.astype(np.int32) + second_chunk.astype(np.int32)) / 2
    return np.clip(mixed, -32768, 32767).astype(np.int16)


def generate_morse_chunk(text, tone_frequency=700.0, words_per_minute=20.0, second_tone_frequency=None, waveform="sine", dual_mode="alternate"):
    unit_samples = max(1, int(SAMPLE_RATE * 1.2 / max(1.0, float(words_per_minute))))
    frequency = max(1.0, float(tone_frequency))
    second_frequency = None if second_tone_frequency in (None, "") else max(1.0, float(second_tone_frequency))
    chunks = []
    phase = 0.0
    tone_index = 0

    def silence(units):
        return np.zeros(unit_samples * units, dtype=np.int16)

    def tone(units):
        nonlocal phase, tone_index
        count = unit_samples * units
        selected_frequency = frequency
        if second_frequency is not None:
            if str(dual_mode).lower() == "simultaneous":
                first_chunk, phase = _wave_samples(phase, frequency, count, waveform)
                second_chunk, _ = _wave_samples(phase, second_frequency, count, waveform)
                return _mix_tone_chunks(first_chunk, second_chunk)
            selected_frequency = frequency if tone_index % 2 == 0 else second_frequency
            tone_index += 1
        chunk, phase = _wave_samples(phase, selected_frequency, count, waveform)
        return chunk

    words = str(text or "").upper().split()
    for word_index, word in enumerate(words):
        for char_index, char in enumerate(word):
            code = MORSE_CODE.get(char)
            if code is None:
                continue
            for symbol_index, symbol in enumerate(code):
                chunks.append(tone(1 if symbol == "." else 3))
                if symbol_index < len(code) - 1:
                    chunks.append(silence(1))
            if char_index < len(word) - 1:
                chunks.append(silence(3))
        if word_index < len(words) - 1:
            chunks.append(silence(7))
    return np.concatenate(chunks) if chunks else np.array([], dtype=np.int16)


def generate_emergency_tone(first_frequency=700.0, second_frequency=None, duration=10.0, waveform="sine", dual_mode="alternate", interval=1.0):
    total_samples = max(1, int(SAMPLE_RATE * max(0.1, float(duration))))
    first_frequency = max(1.0, float(first_frequency))
    second_frequency = None if second_frequency in (None, "") else max(1.0, float(second_frequency))
    if second_frequency is None:
        chunk, _ = _wave_samples(0.0, first_frequency, total_samples, waveform)
        return chunk

    if str(dual_mode).lower() == "simultaneous":
        first_chunk, _ = _wave_samples(0.0, first_frequency, total_samples, waveform)
        second_chunk, _ = _wave_samples(0.0, second_frequency, total_samples, waveform)
        return _mix_tone_chunks(first_chunk, second_chunk)

    interval_samples = max(1, int(SAMPLE_RATE * max(0.1, float(interval))))
    chunks = []
    remaining = total_samples
    tone_index = 0
    while remaining:
        count = min(interval_samples, remaining)
        frequency = first_frequency if tone_index % 2 == 0 else second_frequency
        chunk, _ = _wave_samples(0.0, frequency, count, waveform)
        chunks.append(chunk)
        remaining -= count
        tone_index += 1
    return np.concatenate(chunks)


class BroadcastSystem:
    def __init__(self):
        self.current_array = np.array([], dtype=np.int16)
        self.array_pointer = 0
        self.is_playing = False
        self.lock = threading.Lock()
        self.stream = None
        self.audio_enabled = False
        self.audio_error = None
        self._thread = None
        try:
            output_device = self._find_output_device()
            self.stream = sd.OutputStream(
                device=output_device,
                samplerate=SAMPLE_RATE,
                channels=1,
                dtype="int16",
                blocksize=CHUNKS_PER_BUFFER,
                latency="high",
            )
            self.stream.start()
            self.audio_enabled = True
            self._thread = threading.Thread(target=self._playback_loop, daemon=True)
            self._thread.start()
        except Exception as exc:
            self.audio_error = exc
            self.stream = None
            self.audio_enabled = False

    @staticmethod
    def _find_output_device():
        devices = sd.query_devices()
        for index, device in enumerate(devices):
            name = str(device.get("name", "")).lower()
            if device.get("max_output_channels", 0) > 0 and name.strip() == "pulse":
                return index
        for index, device in enumerate(devices):
            name = str(device.get("name", "")).lower()
            if device.get("max_output_channels", 0) > 0 and "pulse" in name:
                return index
        for index, device in enumerate(devices):
            name = str(device.get("name", "")).lower()
            if device.get("max_output_channels", 0) > 0 and "pipewire" in name:
                return index
        return None

    def _playback_loop(self):
        while self.audio_enabled and self.stream is not None:
            with self.lock:
                if self.current_array.size == 0:
                    out_chunk = np.zeros(CHUNKS_PER_BUFFER, dtype=np.int16)
                else:
                    remaining = len(self.current_array) - self.array_pointer
                    if remaining <= 0:
                        self.current_array = np.array([], dtype=np.int16)
                        self.array_pointer = 0
                        self.is_playing = False
                        out_chunk = np.zeros(CHUNKS_PER_BUFFER, dtype=np.int16)
                    else:
                        n = min(CHUNKS_PER_BUFFER, remaining)
                        out_chunk = self.current_array[self.array_pointer:self.array_pointer + n].copy()
                        self.array_pointer += n
                        if out_chunk.size < CHUNKS_PER_BUFFER:
                            out_chunk = np.pad(out_chunk, (0, CHUNKS_PER_BUFFER - out_chunk.size))
            try:
                self.stream.write(out_chunk)
            except Exception as exc:
                self.audio_error = exc
                self.audio_enabled = False
                self.stream = None
                break

    def trigger_interrupt(self, audio_array):
        with self.lock:
            self.is_playing = True
            self.current_array = np.asarray(audio_array, dtype=np.int16)
            self.array_pointer = 0

    def close(self):
        self.audio_enabled = False
        stream = self.stream
        self.stream = None
        if stream is not None:
            try:
                stream.stop()
            except Exception:
                pass
            try:
                stream.close()
            except Exception:
                pass


SYSTEM_ENGINE = BroadcastSystem()


def build_ternet_audio(message="CQ CQ", callsign="INSERT CALLSIGN HERE", body="", standard_name="TERNET", morse_frequency=700.0, morse_words_per_minute=20.0, morse_second_frequency=None, waveform="sine", morse_dual_mode="alternate"):
    chunks = []
    message = (message or "").strip()
    callsign = (callsign or "").strip()
    body = (body or "").strip()

    if str(_resolve_standard(standard_name).get("MORSE_ASCII", "ASCII")).upper() == "MORSE":
        return generate_morse_chunk(" ".join(part for part in (message, callsign, body) if part), morse_frequency, morse_words_per_minute, morse_second_frequency, waveform, morse_dual_mode)

    if message:
        msg_bits = text_to_bits(message, include_siren=False, siren_gothroughs=0, siren_length=0, siren_only=False, standard_name=standard_name)
        chunks.append(generate_afsk_chunk(msg_bits, standard_name=standard_name, waveform=waveform))
        chunks.append(np.zeros(int(SAMPLE_RATE * 0.25), dtype=np.int16))

    if callsign:
        call_bits = text_to_bits(callsign, include_siren=False, siren_gothroughs=0, siren_length=0, siren_only=False, standard_name=standard_name)
        chunks.append(generate_afsk_chunk(call_bits, standard_name=standard_name, waveform=waveform))

    if not chunks:
        return np.array([], dtype=np.int16)
    return np.concatenate(chunks)


def perform_ternet_broadcast(payload):
    audio = build_ternet_audio_from_payload(payload)
    if audio.size:
        SYSTEM_ENGINE.trigger_interrupt(audio)
    return audio


def build_ternet_audio_from_payload(payload):
    standard_name = str(payload.get("standard_name") or DEFAULT_STANDARD_NAME).strip().upper() or DEFAULT_STANDARD_NAME
    message = normalize_ternet_text(payload.get("header", "CQ CQ"), standard_name, field="header")
    callsign = normalize_ternet_text(payload.get("footer", "INSERT CALLSIGN HERE"), standard_name, field="footer")
    body = normalize_ternet_text(payload.get("body", ""), standard_name, field="body")
    morse_frequency = float(payload.get("morse_frequency", 700.0))
    morse_words_per_minute = float(payload.get("morse_words_per_minute", 20.0))
    morse_second_frequency = payload.get("morse_second_frequency") or None
    waveform = str(payload.get("waveform", "sine")).lower()
    morse_dual_mode = str(payload.get("morse_dual_mode", "alternate")).lower()

    audio = build_ternet_audio(message=message, callsign=callsign, body=body, standard_name=standard_name, morse_frequency=morse_frequency, morse_words_per_minute=morse_words_per_minute, morse_second_frequency=morse_second_frequency, waveform=waveform, morse_dual_mode=morse_dual_mode)
    return audio


def export_wav(audio, filename=None):
    downloads_dir = Path.home() / "Downloads"
    downloads_dir.mkdir(parents=True, exist_ok=True)
    output_path = downloads_dir / (filename or f"ternet_{time.strftime('%Y%m%d_%H%M%S')}.wav")
    with wave.open(str(output_path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(np.dtype(np.int16).itemsize)
        wav_file.setframerate(SAMPLE_RATE)
        wav_file.writeframes(np.asarray(audio, dtype=np.int16).tobytes())
    return output_path


def perform_emergency_tone(payload):
    first_frequency = float(payload.get("first_frequency", 853.0))
    second_frequency = payload.get("second_frequency") or None
    duration = float(payload.get("duration", 8.0))
    waveform = str(payload.get("waveform", "sine")).lower()
    dual_mode = str(payload.get("dual_mode", "alternate")).lower()
    interval = float(payload.get("interval", 1.0))
    audio = generate_emergency_tone(first_frequency, second_frequency, duration, waveform, dual_mode, interval)
    SYSTEM_ENGINE.trigger_interrupt(audio)
    return audio


def _apply_ctk_theme(root):
    if ctk is None:
        root.configure(bg="#0f172a")
        return
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("dark-blue")


class TERNETWindow:
    def __init__(self, master=None):
        self.root = master or (ctk.CTk() if ctk else tk.Tk())
        self.root.title("TERNET Console")
        self.root.geometry("980x760")
        self.root.minsize(820, 620)
        _apply_ctk_theme(self.root)
        self._build_ui()

    def _build_ui(self):
        if ctk is not None:
            self.root.grid_columnconfigure(0, weight=1)
            self.root.grid_rowconfigure(1, weight=1)
            header = ctk.CTkFrame(self.root, corner_radius=16)
            header.grid(row=0, column=0, sticky="nsew", padx=18, pady=(18, 10))
            header.grid_columnconfigure(1, weight=1)
            ctk.CTkLabel(header, text="TERNET Broadcast Console", font=ctk.CTkFont(size=24, weight="bold")).grid(row=0, column=0, columnspan=2, sticky="w", padx=18, pady=(18, 12))

            self.standard_var = tk.StringVar(value=DEFAULT_STANDARD_NAME)
            self.header_var = tk.StringVar(value="CQ CQ")
            self.footer_var = tk.StringVar(value="INSERT CALLSIGN HERE")
            self.morse_frequency_var = tk.StringVar(value="700")
            self.morse_second_frequency_var = tk.StringVar(value="")
            self.morse_wpm_var = tk.StringVar(value="20")
            self.morse_simultaneous_var = tk.BooleanVar(value=False)
            self.waveform_var = tk.StringVar(value="sine")
            self.emergency_first_frequency_var = tk.StringVar(value="853")
            self.emergency_second_frequency_var = tk.StringVar(value="960")
            self.emergency_duration_var = tk.StringVar(value="8")
            self.emergency_interval_var = tk.StringVar(value="1")
            self.emergency_simultaneous_var = tk.BooleanVar(value=True)

            self.standard_combo = ctk.CTkComboBox(header, values=sorted(load_afsk_standards().keys()), variable=self.standard_var, width=220)
            self.standard_combo.grid(row=1, column=0, padx=18, pady=(0, 10), sticky="w")
            self.send_button = ctk.CTkButton(header, text="Transmit TERNET", command=self._send_ternet, hover_color="#0b6e4f", width=180, height=36)
            self.send_button.grid(row=1, column=1, sticky="e", padx=18, pady=(0, 10))

            form = ctk.CTkFrame(self.root, corner_radius=16)
            form.grid(row=1, column=0, sticky="nsew", padx=18, pady=(0, 10))
            form.grid_columnconfigure(1, weight=1)

            ctk.CTkLabel(form, text="Message:").grid(row=0, column=0, sticky="w", padx=18, pady=(18, 6))
            self.header_entry = ctk.CTkEntry(form, textvariable=self.header_var, width=680)
            self.header_entry.grid(row=0, column=1, sticky="ew", padx=(0, 18), pady=(18, 6))

            ctk.CTkLabel(form, text="CALLSIGN:").grid(row=1, column=0, sticky="w", padx=18, pady=(0, 6))
            self.footer_entry = ctk.CTkEntry(form, textvariable=self.footer_var, width=680)
            self.footer_entry.grid(row=1, column=1, sticky="ew", padx=(0, 18), pady=(0, 6))

            ctk.CTkLabel(form, text="Morse tone (Hz):").grid(row=2, column=0, sticky="w", padx=18, pady=(12, 6))
            self.morse_frequency_entry = ctk.CTkEntry(form, textvariable=self.morse_frequency_var, width=140)
            self.morse_frequency_entry.grid(row=2, column=1, sticky="w", padx=(0, 18), pady=(12, 6))
            ctk.CTkLabel(form, text="Morse speed (WPM):").grid(row=3, column=0, sticky="w", padx=18, pady=(0, 12))
            self.morse_wpm_entry = ctk.CTkEntry(form, textvariable=self.morse_wpm_var, width=140)
            self.morse_wpm_entry.grid(row=3, column=1, sticky="w", padx=(0, 18), pady=(0, 12))
            ctk.CTkLabel(form, text="Waveform:").grid(row=4, column=0, sticky="w", padx=18, pady=(0, 6))
            ctk.CTkComboBox(form, values=["sine", "square"], variable=self.waveform_var, width=140).grid(row=4, column=1, sticky="w", padx=(0, 18), pady=(0, 6))
            ctk.CTkLabel(form, text="Second Morse tone (Hz):").grid(row=5, column=0, sticky="w", padx=18, pady=(0, 6))
            self.morse_second_frequency_entry = ctk.CTkEntry(form, textvariable=self.morse_second_frequency_var, width=140)
            self.morse_second_frequency_entry.grid(row=5, column=1, sticky="w", padx=(0, 18), pady=(0, 6))
            ctk.CTkLabel(form, text="Morse dual tone:").grid(row=6, column=0, sticky="w", padx=18, pady=(0, 6))
            self.morse_mode_toggle = ctk.CTkSwitch(form, text="Simultaneous (off = Alternate)", variable=self.morse_simultaneous_var)
            self.morse_mode_toggle.grid(row=6, column=1, sticky="w", padx=(0, 18), pady=(0, 6))
            ctk.CTkLabel(form, text="Emergency tones (Hz):").grid(row=7, column=0, sticky="w", padx=18, pady=(0, 6))
            emergency_frame = ctk.CTkFrame(form, fg_color="transparent")
            emergency_frame.grid(row=7, column=1, sticky="w", padx=(0, 18), pady=(0, 6))
            ctk.CTkEntry(emergency_frame, textvariable=self.emergency_first_frequency_var, width=80).pack(side="left")
            ctk.CTkEntry(emergency_frame, textvariable=self.emergency_second_frequency_var, width=80).pack(side="left", padx=(8, 0))
            ctk.CTkLabel(form, text="Emergency duration (s):").grid(row=8, column=0, sticky="w", padx=18, pady=(0, 6))
            ctk.CTkEntry(form, textvariable=self.emergency_duration_var, width=70).grid(row=8, column=1, sticky="w", padx=(0, 18), pady=(0, 6))
            ctk.CTkLabel(form, text="Emergency interval (s):").grid(row=9, column=0, sticky="w", padx=18, pady=(0, 6))
            ctk.CTkEntry(form, textvariable=self.emergency_interval_var, width=70).grid(row=9, column=1, sticky="w", padx=(0, 18), pady=(0, 6))
            ctk.CTkLabel(form, text="Emergency dual tone:").grid(row=10, column=0, sticky="w", padx=18, pady=(0, 6))
            self.emergency_mode_toggle = ctk.CTkSwitch(form, text="Simultaneous (off = Alternate)", variable=self.emergency_simultaneous_var)
            self.emergency_mode_toggle.grid(row=10, column=1, sticky="w", padx=(0, 18), pady=(0, 6))
            ctk.CTkButton(form, text="Play Emergency Tone", command=self._play_emergency, width=180, height=32).grid(row=11, column=1, sticky="w", padx=(0, 18), pady=(6, 14))
            ctk.CTkButton(form, text="Export WAV", command=self._export_wav, width=140, height=32).grid(row=11, column=1, sticky="e", padx=(0, 18), pady=(6, 14))
            self.morse_second_frequency_var.trace_add("write", self._refresh_morse_controls)
            self._refresh_morse_controls()

            self.preview = tk.Text(self.root, height=8, wrap="word", font=("Courier New", 10), bg="#111827", fg="#d1fae5")
            self.preview.insert("1.0", "TERNET preview will appear here.")
            self.preview.configure(state="disabled")
            self.preview.grid(row=2, column=0, sticky="nsew", padx=18, pady=(0, 18))
            self.root.grid_rowconfigure(2, weight=1)
            self.root.after(200, self._refresh_preview)
            return

        self.root.configure(bg="#0f172a")
        self.root.grid_columnconfigure(0, weight=1)
        self.root.grid_rowconfigure(1, weight=1)

        main = ttk.Frame(self.root, padding=16)
        main.grid(row=0, column=0, sticky="nsew")

        title = ttk.Label(main, text="TERNET Console", font=("Segoe UI", 20, "bold"), foreground="#e2e8f0")
        title.grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 12))

        ttk.Label(main, text="Standard:").grid(row=1, column=0, sticky="w")
        self.standard_var = tk.StringVar(value=DEFAULT_STANDARD_NAME)
        self.standard_combo = ttk.Combobox(main, textvariable=self.standard_var, values=sorted(load_afsk_standards().keys()), state="readonly", width=28)
        self.standard_combo.grid(row=1, column=1, sticky="ew", padx=(8, 8))

        self.send_button = ttk.Button(main, text="Transmit TERNET", command=self._send_ternet)
        self.send_button.grid(row=1, column=2, sticky="e", padx=(0, 0))

        ttk.Label(main, text="Message:").grid(row=2, column=0, sticky="w", pady=(12, 0))
        self.header_var = tk.StringVar(value="CQ CQ")
        self.header_entry = ttk.Entry(main, textvariable=self.header_var)
        self.header_entry.grid(row=2, column=1, columnspan=2, sticky="ew", pady=(12, 0))

        ttk.Label(main, text="CALLSIGN:").grid(row=3, column=0, sticky="w", pady=(8, 0))
        self.footer_var = tk.StringVar(value="INSERT CALLSIGN HERE")
        self.footer_entry = ttk.Entry(main, textvariable=self.footer_var)
        self.footer_entry.grid(row=3, column=1, columnspan=2, sticky="ew", pady=(8, 0))

        ttk.Label(main, text="Morse tone (Hz):").grid(row=4, column=0, sticky="w", pady=(12, 0))
        self.morse_frequency_var = tk.StringVar(value="700")
        self.morse_frequency_entry = ttk.Entry(main, textvariable=self.morse_frequency_var, width=12)
        self.morse_frequency_entry.grid(row=4, column=1, sticky="w", pady=(12, 0))

        ttk.Label(main, text="Morse speed (WPM):").grid(row=5, column=0, sticky="w", pady=(8, 0))
        self.morse_wpm_var = tk.StringVar(value="20")
        self.morse_wpm_entry = ttk.Entry(main, textvariable=self.morse_wpm_var, width=12)
        self.morse_wpm_entry.grid(row=5, column=1, sticky="w", pady=(8, 0))

        ttk.Label(main, text="Waveform:").grid(row=6, column=0, sticky="w", pady=(8, 0))
        self.waveform_var = tk.StringVar(value="sine")
        ttk.Combobox(main, textvariable=self.waveform_var, values=["sine", "square"], state="readonly", width=10).grid(row=6, column=1, sticky="w", pady=(8, 0))

        ttk.Label(main, text="Second Morse tone (Hz):").grid(row=7, column=0, sticky="w", pady=(8, 0))
        self.morse_second_frequency_var = tk.StringVar(value="")
        self.morse_second_frequency_entry = ttk.Entry(main, textvariable=self.morse_second_frequency_var, width=12)
        self.morse_second_frequency_entry.grid(row=7, column=1, sticky="w", pady=(8, 0))

        ttk.Label(main, text="Morse dual tone:").grid(row=8, column=0, sticky="w", pady=(8, 0))
        self.morse_simultaneous_var = tk.BooleanVar(value=False)
        self.morse_mode_toggle = ttk.Checkbutton(main, text="Simultaneous (off = Alternate)", variable=self.morse_simultaneous_var)
        self.morse_mode_toggle.grid(row=8, column=1, sticky="w", pady=(8, 0))

        ttk.Label(main, text="Emergency duration (seconds):").grid(row=9, column=0, sticky="w", pady=(8, 0))
        self.emergency_first_frequency_var = tk.StringVar(value="853")
        self.emergency_second_frequency_var = tk.StringVar(value="960")
        ttk.Label(main, text="Emergency tones (Hz):").grid(row=9, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(main, textvariable=self.emergency_first_frequency_var, width=12).grid(row=9, column=1, sticky="w", pady=(8, 0))
        ttk.Entry(main, textvariable=self.emergency_second_frequency_var, width=12).grid(row=9, column=2, sticky="w", pady=(8, 0))

        ttk.Label(main, text="Emergency duration (seconds):").grid(row=10, column=0, sticky="w", pady=(8, 0))
        self.emergency_duration_var = tk.StringVar(value="8")
        ttk.Entry(main, textvariable=self.emergency_duration_var, width=12).grid(row=10, column=1, sticky="w", pady=(8, 0))

        ttk.Label(main, text="Emergency interval (seconds):").grid(row=11, column=0, sticky="w", pady=(8, 0))
        self.emergency_interval_var = tk.StringVar(value="1")
        ttk.Entry(main, textvariable=self.emergency_interval_var, width=12).grid(row=11, column=1, sticky="w", pady=(8, 0))

        ttk.Label(main, text="Emergency dual tone:").grid(row=12, column=0, sticky="w", pady=(8, 0))
        self.emergency_simultaneous_var = tk.BooleanVar(value=True)
        self.emergency_mode_toggle = ttk.Checkbutton(main, text="Simultaneous (off = Alternate)", variable=self.emergency_simultaneous_var)
        self.emergency_mode_toggle.grid(row=12, column=1, sticky="w", pady=(8, 0))

        ttk.Button(main, text="Play Emergency Tone", command=self._play_emergency).grid(row=12, column=2, sticky="e", pady=(8, 0))

        ttk.Button(main, text="Preview", command=self._refresh_preview).grid(row=13, column=1, sticky="w", pady=(10, 0))
        ttk.Button(main, text="Export WAV", command=self._export_wav).grid(row=13, column=2, sticky="w", pady=(10, 0))
        ttk.Button(main, text="Clear", command=self._clear_fields).grid(row=13, column=2, sticky="e", pady=(10, 0))

        self.preview = tk.Text(main, height=8, wrap="word", font=("Courier New", 10), bg="#111827", fg="#d1fae5")
        self.preview.grid(row=14, column=0, columnspan=3, sticky="nsew", pady=(16, 0))
        self.preview.insert("1.0", "TERNET preview will appear here.")
        self.preview.configure(state="disabled")

        main.grid_columnconfigure(1, weight=1)
        main.grid_rowconfigure(14, weight=1)

        self.morse_second_frequency_var.trace_add("write", self._refresh_morse_controls)
        self._refresh_morse_controls()
        self.root.after(200, self._refresh_preview)

    def _clear_fields(self):
        self.header_var.set("")
        self.footer_var.set("")
        self.preview.configure(state="normal")
        self.preview.delete("1.0", "end")
        self.preview.insert("1.0", "Cleared.")
        self.preview.configure(state="disabled")

    def _refresh_morse_controls(self, *_args):
        morse_mode = str(_resolve_standard(self.standard_var.get()).get("MORSE_ASCII", "ASCII")).upper() == "MORSE"
        has_second_tone = bool(self.morse_second_frequency_var.get().strip())
        morse_state = "normal" if morse_mode else "disabled"
        dual_state = "normal" if morse_mode and has_second_tone else "disabled"
        for control in (self.morse_frequency_entry, self.morse_wpm_entry, self.morse_second_frequency_entry):
            control.configure(state=morse_state)
        self.morse_mode_toggle.configure(state=dual_state)
        if not morse_mode or not has_second_tone:
            self.morse_simultaneous_var.set(False)
        self.root.after(1000, self._refresh_morse_controls)

    def _refresh_preview(self):
        header = self.header_var.get().strip()
        footer = self.footer_var.get().strip()
        std = self.standard_var.get() or DEFAULT_STANDARD_NAME
        preview = [
            "MESSAGE: " + normalize_ternet_text(header, std, field="header"),
            "CALLSIGN: " + normalize_ternet_text(footer, std, field="footer"),
            "MORSE TONE: " + self.morse_frequency_var.get().strip() + " Hz",
            "MORSE SECOND TONE: " + (self.morse_second_frequency_var.get().strip() or "off") + " Hz",
            "MORSE SPEED: " + self.morse_wpm_var.get().strip() + " WPM",
            "MORSE MODE: " + ("simultaneous" if self.morse_simultaneous_var.get() else "alternate"),
            "WAVEFORM: " + self.waveform_var.get().strip(),
        ]
        text = "\n".join(preview)
        try:
            self.preview.configure(state="normal")
            self.preview.delete("1.0", "end")
            self.preview.insert("1.0", text)
            self.preview.configure(state="disabled")
        except Exception:
            pass

    def _play_emergency(self):
        payload = {
            "first_frequency": self.emergency_first_frequency_var.get().strip(),
            "second_frequency": self.emergency_second_frequency_var.get().strip(),
            "duration": self.emergency_duration_var.get().strip(),
            "interval": self.emergency_interval_var.get().strip(),
            "dual_mode": "simultaneous" if self.emergency_simultaneous_var.get() else "alternate",
            "waveform": self.waveform_var.get().strip(),
        }
        try:
            perform_emergency_tone(payload)
        except Exception as exc:  # pragma: no cover
            messagebox.showerror("TERNET", str(exc))

    def _transmission_payload(self):
        return {
            "header": self.header_var.get().strip(),
            "footer": self.footer_var.get().strip(),
            "standard_name": self.standard_var.get() or DEFAULT_STANDARD_NAME,
            "morse_frequency": self.morse_frequency_var.get().strip(),
            "morse_second_frequency": self.morse_second_frequency_var.get().strip(),
            "morse_words_per_minute": self.morse_wpm_var.get().strip(),
            "morse_dual_mode": "simultaneous" if self.morse_simultaneous_var.get() else "alternate",
            "waveform": self.waveform_var.get().strip(),
        }

    def _export_wav(self):
        payload = self._transmission_payload()
        if not payload["header"] and not payload["footer"]:
            messagebox.showwarning("TERNET", "Nothing to export.")
            return
        try:
            audio = build_ternet_audio_from_payload(payload)
            output_path = export_wav(audio)
            messagebox.showinfo("TERNET", f"WAV exported to:\n{output_path}")
        except Exception as exc:  # pragma: no cover
            messagebox.showerror("TERNET", str(exc))

    def _send_ternet(self):
        payload = self._transmission_payload()

        if not payload["header"] and not payload["footer"]:
            messagebox.showwarning("TERNET", "Nothing to transmit.")
            return

        try:
            perform_ternet_broadcast(payload)
        except Exception as exc:  # pragma: no cover
            messagebox.showerror("TERNET", str(exc))


def launch_ternet_gui():
    root = TERNETWindow()
    root.root.protocol("WM_DELETE_WINDOW", lambda: (SYSTEM_ENGINE.close(), root.root.destroy()))
    try:
        root.root.mainloop()
    except Exception:
        pass


if __name__ == "__main__":
    launch_ternet_gui()
