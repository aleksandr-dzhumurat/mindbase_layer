#!/usr/bin/env python3
"""
Process Media - extract audio from video, compress video, or extract frames.

Usage:
    uv run python scripts/process_media.py extract <video_file>
    uv run python scripts/process_media.py compress <video_file> [--bitrate 800]
    uv run python scripts/process_media.py autocut <video_or_audio_file>
    uv run python scripts/process_media.py frames <video_file> [--mode scene]
    uv run python scripts/process_media.py frames <video_file> --mode interval [--interval 5]
"""

import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from mindbase_layer.utils.media import (
    compress_video_pipeline,
    cut_media,
    detect_silence,
    extract_audio_pipeline,
    retrieve_frames_pipeline,
)

__all__ = ["compress_video_pipeline", "extract_audio_pipeline", "retrieve_frames_pipeline"]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Extract audio, compress video, or retrieve frames from video")
    subparsers = parser.add_subparsers(dest="command", required=True)

    extract_parser = subparsers.add_parser("extract", help="Extract audio track to .mp3")
    extract_parser.add_argument("video_file", help="Path to video file")

    compress_parser = subparsers.add_parser("compress", help="Compress video (VideoToolbox H.264)")
    compress_parser.add_argument("video_file", help="Path to video file")
    compress_parser.add_argument(
        "--bitrate", type=int, default=800,
        help="Video bitrate in kbps: 800=aggressive (default), 1200=balanced, 1800=good quality",
    )

    autocut_parser = subparsers.add_parser(
        "autocut", help="Remove silent sections from a video or audio file"
    )
    autocut_parser.add_argument("video_file", help="Path to video or audio file")
    autocut_parser.add_argument(
        "--noise", default="-30dB", help="Silence detection threshold (default: -30dB)"
    )
    autocut_parser.add_argument(
        "--silence-duration",
        type=float,
        default=2.0,
        help="Minimum silence duration in seconds (default: 2.0)",
    )

    frames_parser = subparsers.add_parser("frames", help="Extract and retrieve frames from video")
    frames_parser.add_argument("video_file", help="Path to video file or URL")
    frames_parser.add_argument(
        "--output-dir", default=None, help="Artifact directory (default: <video-dir>/<stem>)"
    )
    frames_parser.add_argument(
        "--mode", choices=["scene", "interval"], default="scene", help="Frame sampling mode"
    )
    frames_parser.add_argument(
        "--interval", type=int, default=5, help="Seconds between frames (interval mode)"
    )
    frames_parser.add_argument(
        "--scene-threshold",
        type=float,
        default=0.3,
        help="Scene-change sensitivity 0-1 (scene mode)",
    )
    frames_parser.add_argument(
        "--max-width", type=int, default=1280, help="Downscale frames to this width (0 = original)"
    )

    args = parser.parse_args()
    try:
        if args.command == "extract":
            extract_audio_pipeline(args.video_file)
        elif args.command == "compress":
            compress_video_pipeline(args.video_file, args.bitrate)
        elif args.command == "autocut":
            video_path = Path(args.video_file).expanduser()
            if not video_path.is_file():
                raise FileNotFoundError(f"Video file '{video_path}' not found")
            silence_log = video_path.with_name(f"{video_path.stem}_silence.log")
            if not silence_log.exists():
                silence_log = detect_silence(
                    str(video_path), noise=args.noise, duration=args.silence_duration
                )
            cut_media(str(video_path), str(silence_log))
        elif args.command == "frames":
            retrieve_frames_pipeline(
                args.video_file,
                output_dir=args.output_dir,
                mode=args.mode,
                interval=args.interval,
                scene_threshold=args.scene_threshold,
                max_width=args.max_width,
            )
    except (FileNotFoundError, RuntimeError, subprocess.CalledProcessError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
