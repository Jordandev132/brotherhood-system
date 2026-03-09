"""Voiceover — ElevenLabs TTS with character-level timestamp alignment.

Generates ONE continuous voiceover and extracts cue-point timestamps
from the alignment data. The recorder uses these timestamps to fire
actions at the exact moment the voice mentions them.
"""
from __future__ import annotations

import base64
import json
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from elevenlabs import ElevenLabs

# Voice config — Brian (deep, resonant, conversational)
VOICE_ID = "nPczCjzI2devNBz1zQrb"
MODEL_ID = "eleven_multilingual_v2"
VOICE_SETTINGS = {
    "stability": 0.55,
    "similarity_boost": 0.75,
    "style": 0.25,
    "use_speaker_boost": True,
}


@dataclass
class CuePoint:
    """A cue point: an action to fire at an exact timestamp."""
    action: str
    timestamp: float  # seconds from start of voiceover


@dataclass
class VoiceoverResult:
    """Result of voiceover generation with cue sheet."""
    audio_path: Path
    duration_sec: float
    cue_sheet: list[CuePoint]


def _mp3_to_wav(mp3_bytes: bytes, wav_path: Path) -> None:
    """Convert MP3 bytes to WAV via ffmpeg."""
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
        tmp.write(mp3_bytes)
        tmp_mp3 = tmp.name

    subprocess.run(
        ["ffmpeg", "-y", "-i", tmp_mp3, "-ar", "44100", "-ac", "1", str(wav_path)],
        capture_output=True,
        check=True,
    )
    Path(tmp_mp3).unlink(missing_ok=True)


def _wav_duration(path: Path) -> float:
    """Get WAV file duration in seconds."""
    import wave
    with wave.open(str(path), "rb") as wf:
        return wf.getnframes() / wf.getframerate()


def _find_phrase_timestamp(
    text: str,
    char_starts: list[float],
    phrase: str,
) -> float:
    """Find the timestamp when a phrase starts in the alignment data.

    Searches for the phrase in the text and returns the character-level
    start time of the first character of the phrase.
    """
    idx = text.lower().find(phrase.lower())
    if idx == -1:
        raise ValueError(f"Cue phrase '{phrase}' not found in voiceover text")
    # Return the start time of the first character of the phrase
    if idx < len(char_starts):
        return char_starts[idx]
    raise ValueError(f"Cue phrase '{phrase}' found at index {idx} but only {len(char_starts)} timestamps")


def generate_voiceover(
    script_text: str,
    cues: list[dict],
    api_key: str,
    output_dir: Path,
) -> VoiceoverResult:
    """Generate a single voiceover with character-aligned cue timestamps.

    Args:
        script_text: full voiceover script as one continuous string
        cues: list of {"action": "open_chat", "at_phrase": "clicks the chat"}
              each cue maps an action to the phrase whose start time triggers it
        api_key: ElevenLabs API key
        output_dir: directory for output audio

    Returns:
        VoiceoverResult with audio path, duration, and cue sheet
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    client = ElevenLabs(api_key=api_key)

    print("  [ElevenLabs] Generating voiceover with timestamps...")
    result = client.text_to_speech.convert_with_timestamps(
        text=script_text,
        voice_id=VOICE_ID,
        model_id=MODEL_ID,
        voice_settings=VOICE_SETTINGS,
    )

    # Decode audio
    audio_bytes = base64.b64decode(result.audio_base_64)
    wav_path = output_dir / "voiceover_full.wav"
    _mp3_to_wav(audio_bytes, wav_path)

    duration = _wav_duration(wav_path)
    print(f"  [ElevenLabs] Voiceover: {duration:.1f}s")

    # Extract alignment data
    alignment = result.alignment
    chars = alignment.characters
    char_starts = alignment.character_start_times_seconds
    text_from_chars = "".join(chars)

    # Build cue sheet from phrase matching
    cue_sheet: list[CuePoint] = []
    for cue in cues:
        action = cue["action"]
        phrase = cue["at_phrase"]
        try:
            ts = _find_phrase_timestamp(text_from_chars, char_starts, phrase)
            cue_sheet.append(CuePoint(action=action, timestamp=ts))
            print(f"  [cue] {action} @ {ts:.2f}s ('{phrase}')")
        except ValueError as e:
            print(f"  [cue] WARNING: {e}")

    # Sort by timestamp
    cue_sheet.sort(key=lambda c: c.timestamp)

    # Save cue sheet as JSON for debugging/reuse
    cue_json = output_dir / "cue_sheet.json"
    cue_json.write_text(json.dumps(
        [{"action": c.action, "timestamp": c.timestamp} for c in cue_sheet],
        indent=2,
    ))

    return VoiceoverResult(
        audio_path=wav_path,
        duration_sec=duration,
        cue_sheet=cue_sheet,
    )


def load_cached_voiceover(output_dir: Path) -> VoiceoverResult | None:
    """Load cached voiceover + cue sheet if they exist."""
    wav_path = output_dir / "voiceover_full.wav"
    cue_json = output_dir / "cue_sheet.json"

    if not wav_path.exists() or not cue_json.exists():
        return None

    duration = _wav_duration(wav_path)
    cue_data = json.loads(cue_json.read_text())
    cue_sheet = [CuePoint(action=c["action"], timestamp=c["timestamp"]) for c in cue_data]

    return VoiceoverResult(
        audio_path=wav_path,
        duration_sec=duration,
        cue_sheet=cue_sheet,
    )
