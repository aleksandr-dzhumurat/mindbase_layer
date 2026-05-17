"""
Transcribe audio to .srt subtitles using Whisper on Apple Silicon.

Install:
    pip install mlx-whisper tqdm

Usage:
    uv run python scripts/whisper_to_srt.py audio.mp3
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from mindbase_layer.utils.audio import transcribe


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python whisper_to_srt.py <audio.mp3>")
        sys.exit(1)

    audio_file = sys.argv[1]
    if audio_file.lower().endswith(".mp4"):
        print(f"Error: {audio_file} is an .mp4 video file.")
        print(f"Please extract the audio first by running: python scripts/extract_audio.py '{audio_file}'")
        expected_mp3 = audio_file.rsplit(".", 1)[0] + ".mp3"
        print(f"After doing that, run: uv run python scripts/whisper_to_srt.py '{expected_mp3}'")
        sys.exit(1)

    transcribe(audio_file)
