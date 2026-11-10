"""ElevenLabs Text-to-Speech integration for PlayAural narrator catalogs."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import tempfile

from dotenv import load_dotenv

# Load ELEVENLABS_API_KEY from the root .env file before importing ElevenLabs
# (whose default argument evaluates os.getenv at import time).
_ENV_PATH = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(_ENV_PATH, override=True)

from elevenlabs import EffectsSpecInput, ElevenLabs, VoiceSettings

DEFAULT_VOICE_ID = "nPczCjzI2devNBz1zQrb"  # Brian - Deep, Resonant baritone with strong presence
DEFAULT_MODEL_ID = "eleven_v4"


def create_elevenlabs_client() -> ElevenLabs:
    """Create an ElevenLabs client reading ELEVENLABS_API_KEY from the environment."""
    load_dotenv(_ENV_PATH, override=True)
    return ElevenLabs(api_key=os.getenv("ELEVENLABS_API_KEY"))


def synthesize_narrator_ogg(
    text: str,
    output_path: Path,
    *,
    voice_id: str = DEFAULT_VOICE_ID,
    model_id: str = DEFAULT_MODEL_ID,
    language_code: str = "es",
    stability: float = 0.55,
    similarity_boost: float = 0.85,
) -> Path:
    """Synthesize a line with ElevenLabs TTS and encode a mono 44.1kHz Ogg for Cosmos HRTF."""
    client = create_elevenlabs_client()
    directed_text = (
        text if text.lstrip().startswith("[") else f"[deep, firm, cold, commanding] {text}"
    )
    audio_chunks = client.text_to_speech.convert(
        text=directed_text,
        voice_id=voice_id,
        model_id=model_id,
        language_code=language_code,
        output_format="mp3_44100_128",
        voice_settings=VoiceSettings(
            stability=stability,
            similarity_boost=similarity_boost,
        ),
        audio_effects=EffectsSpecInput(
            environment_id="small_room",
            send_level=0.28,
            distance=0.15,
        ),
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp_file:
        tmp_mp3 = Path(tmp_file.name)
        for chunk in audio_chunks:
            if chunk:
                tmp_file.write(chunk)

    try:
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                str(tmp_mp3),
                "-af",
                (
                    "silenceremove=start_periods=1:start_silence=0.03:start_threshold=-45dB,"
                    "asetrate=44100*0.93,aresample=44100,atempo=1.14,"
                    "equalizer=f=115:t=q:w=1.1:g=3.5,"
                    "equalizer=f=2800:t=q:w=1.2:g=2.5,"
                    "loudnorm=I=-15:TP=-1.5:LRA=9"
                ),
                "-ar",
                "44100",
                "-ac",
                "1",
                "-c:a",
                "libvorbis",
                "-q:a",
                "5",
                str(output_path),
            ],
            check=True,
        )
    finally:
        tmp_mp3.unlink(missing_ok=True)

    return output_path

