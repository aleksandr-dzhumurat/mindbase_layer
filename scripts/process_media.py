#!/usr/bin/env python3
"""
Process Media - extract audio from video, or compress video for smaller files.

Usage:
    uv run python scripts/process_media.py extract <video_file>
    uv run python scripts/process_media.py compress <video_file> [--bitrate 800]
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from mindbase_layer.utils.media import compress_video_pipeline, extract_audio_pipeline

__all__ = ["extract_audio_pipeline", "compress_video_pipeline"]

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Extract audio from or compress a video file")
    subparsers = parser.add_subparsers(dest="command", required=True)

    extract_parser = subparsers.add_parser("extract", help="Extract audio track to .mp3")
    extract_parser.add_argument("video_file", help="Path to video file")

    compress_parser = subparsers.add_parser("compress", help="Compress video (VideoToolbox H.264)")
    compress_parser.add_argument("video_file", help="Path to video file")
    compress_parser.add_argument(
        "--bitrate", type=int, default=800,
        help="Video bitrate in kbps: 800=aggressive (default), 1200=balanced, 1800=good quality",
    )

    args = parser.parse_args()
    try:
        if args.command == "extract":
            extract_audio_pipeline(args.video_file)
        elif args.command == "compress":
            compress_video_pipeline(args.video_file, args.bitrate)
    except (FileNotFoundError, RuntimeError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
