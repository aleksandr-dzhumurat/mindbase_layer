"""
Download a YouTube video or audio track using pytubefix.

Usage:
    uv run python scripts/youtube_download.py --url <youtube_url> --mode video
    uv run python scripts/youtube_download.py --url <youtube_url> --mode audio
    uv run python scripts/youtube_download.py --url <youtube_url> --mode audio --output /path/to/dir
"""

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from mindbase_layer.utils.youtube import download_audio, download_video

__all__ = ["download_audio", "download_video"]

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Download YouTube video or audio")
    parser.add_argument("--url", required=True, help="YouTube video URL")
    parser.add_argument("--mode", choices=["video", "audio"], default="video", help="Download mode (default: video)")
    parser.add_argument("--output", type=Path, default=None, help="Output directory (default: current directory)")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    if args.mode == "audio":
        path = download_audio(args.url, output_dir=args.output)
    else:
        path = download_video(args.url, output_dir=args.output)

    print(f"Saved: {path}")
