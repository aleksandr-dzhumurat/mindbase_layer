#!/usr/bin/env python3
"""
Audio Splitter - Splits audio files into 300-500 second intervals at silence points.

Usage:
    uv run python scripts/audio_splitter.py <audio.mp3> [--min-interval 300] [--max-interval 500]
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from mindbase_layer.utils.audio import audio_split_pipeline


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Split audio into intervals at silence points')
    parser.add_argument('audio_file', help='Path to audio file (.mp3)')
    parser.add_argument('--min-interval', type=float, default=300, help='Minimum interval duration (default: 300)')
    parser.add_argument('--max-interval', type=float, default=500, help='Maximum interval duration (default: 500)')
    args = parser.parse_args()
    try:
        audio_split_pipeline(args.audio_file, args.min_interval, args.max_interval)
    except (FileNotFoundError, RuntimeError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
