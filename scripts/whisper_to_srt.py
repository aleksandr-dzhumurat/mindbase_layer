"""
Transcribe audio to .srt subtitles using Whisper on Apple Silicon.

Install:
    pip install mlx-whisper tqdm

Usage:
    uv run python scripts/whisper_to_srt.py audio.mp3 [--language en]
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


if __name__ == "__main__":
    from mindbase_layer.utils.media import transcribe

    parser = argparse.ArgumentParser(description="Transcribe audio to .srt subtitles")
    parser.add_argument("audio_file", help="Path to audio file")
    parser.add_argument(
        "--language",
        default="en",
        help="Transcription language code (default: en)",
    )
    args = parser.parse_args()

    audio_file = args.audio_file
    if audio_file.lower().endswith(".mp4"):
        print(f"Error: {audio_file} is an .mp4 video file.")
        print(f"Please extract the audio first by running: python scripts/process_media.py extract '{audio_file}'")
        expected_mp3 = audio_file.rsplit(".", 1)[0] + ".mp3"
        print(f"After doing that, run: uv run python scripts/whisper_to_srt.py '{expected_mp3}'")
        sys.exit(1)

    transcribe(audio_file, language=args.language)
