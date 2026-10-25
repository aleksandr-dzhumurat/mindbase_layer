import re
import subprocess
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from tqdm import tqdm

_WHISPER_MODEL = "mlx-community/whisper-medium"

try:
    import mlx_whisper as whisper
except ImportError:
    whisper = None


def extract_audio_pipeline(video_path: str = None):
    if video_path is None:
        if len(sys.argv) < 2:
            print("Usage: python scripts/process_media.py extract <path_to_video_file>")
            sys.exit(1)
        video_path = sys.argv[1]

    input_file = Path(unicodedata.normalize('NFC', str(video_path)))
    if not input_file.is_file():
        # macOS stores filenames in NFD; try alternate normalization
        input_file = Path(unicodedata.normalize('NFD', str(video_path)))
    if not input_file.is_file():
        raise FileNotFoundError(f"File '{video_path}' not found")

    output_file = input_file.with_suffix(".mp3")

    if output_file.is_file():
        print(f"Audio already exists: {output_file}")
        return output_file

    print(f"Extracting audio from: {input_file}")
    print(f"Output file: {output_file}")

    subprocess.run(
        ["ffmpeg", "-i", str(input_file), "-vn", "-acodec", "libmp3lame", "-q:a", "2", str(output_file)],
        check=True,
    )

    print(f"Done! Audio saved to: {output_file}")
    return output_file


def compress_video_pipeline(video_path: str, bitrate_kbps: int = 800) -> Path:
    """Compress a lecture-style video using the VideoToolbox H.264 encoder.

    Downscales to 1280px width at 15fps and re-encodes audio to mono AAC,
    trading quality for size on talking-head/screen-recording content.
    """
    input_file = Path(video_path)
    if not input_file.is_file():
        raise FileNotFoundError(f"File not found: {input_file}")
    output_file = input_file.with_name(input_file.stem + "_compressed.mp4")
    if output_file.is_file():
        print(f"Compressed video already exists: {output_file}")
        return output_file

    print(f"Input:   {input_file}")
    print(f"Output:  {output_file}")
    print(f"Bitrate: {bitrate_kbps}k")

    subprocess.run(
        [
            "ffmpeg", "-nostdin", "-i", str(input_file),
            "-vf", "scale=1280:-2,fps=15",
            "-c:v", "h264_videotoolbox",
            "-b:v", f"{bitrate_kbps}k",
            "-profile:v", "main",
            "-movflags", "+faststart",
            "-c:a", "aac",
            "-ac", "1",
            "-b:a", "96k",
            "-y",
            str(output_file),
        ],
        check=True,
    )

    print(f"Done! Compressed video saved to: {output_file}")
    return output_file


def convert_to_mp3(input_path: str) -> Path:
    """Convert an audio file (e.g. m4a) to mp3 using ffmpeg. Skips if output already exists."""
    input_file = Path(input_path)
    if not input_file.is_file():
        raise FileNotFoundError(f"File not found: {input_file}")
    output_file = input_file.with_suffix(".mp3")
    if output_file.is_file():
        print(f"MP3 already exists: {output_file}")
        return output_file
    subprocess.run(
        ["ffmpeg", "-i", str(input_file), "-acodec", "libmp3lame", "-q:a", "2", str(output_file)],
        check=True,
    )
    print(f"Converted: {output_file}")
    return output_file


def detect_silence(input_path: str, noise: str = "-30dB", duration: float = 2.0) -> Path:
    """Run ffmpeg silencedetect on an audio file and write intervals to a _silence.log file."""
    input_file = Path(input_path)
    if not input_file.is_file():
        raise FileNotFoundError(f"File not found: {input_file}")
    output_file = input_file.parent / (input_file.stem + "_silence.log")
    result = subprocess.run(
        ["ffmpeg", "-i", str(input_file), "-af", f"silencedetect=noise={noise}:d={duration}", "-f", "null", "-"],
        stderr=subprocess.STDOUT,
        stdout=subprocess.PIPE,
        text=True,
    )
    silence_lines = [
        line for line in result.stdout.splitlines()
        if re.search(r"silence_start|silence_end|silence_duration", line)
    ]
    output_file.write_text("\n".join(silence_lines) + "\n")
    print(f"Silence intervals saved to: {output_file}")
    return output_file


@dataclass
class SilencePeriod:
    start: float
    end: float
    duration: float

    @property
    def center(self) -> float:
        return (self.start + self.end) / 2


@dataclass
class Interval:
    start: float
    end: float

    @property
    def duration(self) -> float:
        return self.end - self.start


def parse_silence_log(log_path: Path) -> list[SilencePeriod]:
    """Parse silence detection log file and return list of silence periods."""
    silence_periods = []
    current_start = None
    with open(log_path, 'r') as f:
        for line in f:
            start_match = re.search(r'silence_start:\s*([\d.]+)', line)
            if start_match:
                current_start = float(start_match.group(1))
                continue
            end_match = re.search(r'silence_end:\s*([\d.]+)\s*\|\s*silence_duration:\s*([\d.]+)', line)
            if end_match and current_start is not None:
                silence_periods.append(SilencePeriod(current_start, float(end_match.group(1)), float(end_match.group(2))))
                current_start = None
    return silence_periods


def find_split_points(silence_periods: list[SilencePeriod], total_duration: float,
                      min_interval: float = 300, max_interval: float = 500) -> list[Interval]:
    """Greedy algorithm: split at the longest silence between min_interval and max_interval from each chunk start."""
    intervals = []
    current_start = 0.0
    while current_start < total_duration:
        if total_duration - current_start <= max_interval:
            intervals.append(Interval(current_start, total_duration))
            break
        min_boundary = current_start + min_interval
        max_boundary = current_start + max_interval
        candidates = [sp for sp in silence_periods if sp.start >= min_boundary and sp.end <= max_boundary]
        if candidates:
            best = max(candidates, key=lambda sp: sp.duration)
        else:
            fallback = [sp for sp in silence_periods if sp.start >= min_boundary]
            if fallback:
                best = fallback[0]
            else:
                intervals.append(Interval(current_start, total_duration))
                break
        intervals.append(Interval(current_start, best.center))
        current_start = best.center
    return intervals


def format_time(seconds: float) -> str:
    """Format seconds as HH:MM:SS.mmm"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds % 60
    return f"{hours:02d}:{minutes:02d}:{secs:06.3f}"


def get_audio_duration(audio_path: Path) -> float:
    """Get audio duration in seconds using ffprobe."""
    cmd = [
        'ffprobe', '-v', 'error',
        '-show_entries', 'format=duration',
        '-of', 'default=noprint_wrappers=1:nokey=1',
        str(audio_path)
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {result.stderr}")
    return float(result.stdout.strip())


def split_audio_file(audio_path: Path, intervals: list[Interval]) -> list[Path]:
    """Split audio file into chunks based on intervals using ffmpeg."""
    output_dir = audio_path.parent / audio_path.stem
    output_dir.mkdir(exist_ok=True)
    output_files = []
    for i, interval in enumerate(intervals, 1):
        output_path = output_dir / f"{audio_path.stem}_chunk_{i:02d}.mp3"
        cmd = [
            'ffmpeg', '-y', '-i', str(audio_path),
            '-ss', str(interval.start),
            '-t', str(interval.duration),
            '-acodec', 'copy',
            str(output_path)
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg failed for chunk {i}: {result.stderr}")
        output_files.append(output_path)
        print(f"Created: {output_path.name}")
    return output_files


def fmt(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds % 1) * 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"


def transcribe(audio_path: str, language: str = "en") -> str:
    """Transcribe an audio file to an SRT subtitles file using Whisper."""
    audio_path = audio_path.strip('"').strip("'")
    srt_path = audio_path.rsplit(".", 1)[0] + ".srt"
    if Path(srt_path).is_file():
        print(f"SRT already exists: {srt_path}")
        return srt_path

    if whisper is None:
        raise RuntimeError("mlx_whisper is not installed. Install it with: uv pip install mlx-whisper")

    print(f"Transcribing: {audio_path}")
    print("Loading model and processing audio (this may take a moment)...")

    result = whisper.transcribe(audio_path, path_or_hf_repo=_WHISPER_MODEL, language=language)
    segments = result["segments"]

    idx = 1
    with open(srt_path, "w") as f:
        for seg in tqdm(segments, total=len(segments), desc="Writing .srt"):
            text = seg['text'].strip()
            if len(text) < 10:
                continue
            f.write(f"{idx}\n")
            f.write(f"{fmt(seg['start'])} --> {fmt(seg['end'])}\n")
            f.write(f"{text}\n\n")
            idx += 1

    print(f"Saved: {srt_path}")
    return srt_path

# ====== VIDEO SHOTS =========

#!/usr/bin/env python3
"""rec2doc -- turn a screen recording into a step-by-step Markdown document.

Pipeline:
  1. Extract frames from the video with ffmpeg (scene-change detection or fixed interval).
  2. Analyze each frame with Gemini vision (screen, on-screen text, code, event).
  3. Synthesize an ordered, screenshot-backed walkthrough as Markdown.

Output layout (under the artifact directory, named after the video by default):
  <out>/frames/frame_<index>_<HH-MM-SS>.png   extracted frames
  <out>/frames/manifest.csv                    index,filename,seconds,timestamp
  <out>/<stem>_frames.jsonl                    one row per EXTRACTED frame: manifest fields +
                                               `similarity` (pixel-level vs previous shot) +
                                               `to_drop` (near-duplicate flag)
  <out>/<stem>_rec2doc.md                      the generated document

Usage:
    python scripts/doc_indexing/rec2doc.py --input demo.mp4
    python scripts/doc_indexing/rec2doc.py --input demo.mp4 --mode interval --interval 5
    python scripts/doc_indexing/rec2doc.py --input https://youtu.be/xyz --lang en
"""

import csv
import json
import logging
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class Frame:
    """A single extracted frame and its position in the recording."""

    index: int
    filename: str
    seconds: float
    timestamp: str  # HH:MM:SS


def _require(cmd: str) -> None:
    """Abort with a friendly message if a required binary is missing."""
    if shutil.which(cmd) is None:
        raise SystemExit(
            f"ERROR: '{cmd}' not found on PATH. Install ffmpeg (it provides ffmpeg + ffprobe)."
        )


def _hms(seconds: float) -> str:
    """Seconds -> filename-safe 'HH-MM-SS'."""
    s = int(seconds)
    return f"{s // 3600:02d}-{(s % 3600) // 60:02d}-{s % 60:02d}"


def _parse_scene_times(meta: Path) -> list[float]:
    """Extract pts_time values (one per detected scene change) from ffmpeg metadata output."""
    if not meta.exists():
        return []
    times: list[float] = []
    for line in meta.read_text(encoding="utf-8", errors="ignore").splitlines():
        m = re.search(r"pts_time:([0-9.]+)", line)
        if m:
            times.append(float(m.group(1)))
    return times


def _place(src: Path, index: int, seconds: float, frames_dir: Path) -> Frame:
    """Move a raw ffmpeg frame to its final timestamped filename and return a Frame."""
    stamp = _hms(seconds)
    filename = f"frame_{index:05d}_{stamp}.png"
    shutil.move(str(src), str(frames_dir / filename))
    return Frame(index, filename, seconds, stamp.replace("-", ":"))


def _write_manifest(frames_dir: Path, frames: list[Frame]) -> None:
    """Write an ordered index of frames to manifest.csv."""
    with open(frames_dir / "manifest.csv", "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["index", "filename", "seconds", "timestamp"])
        for fr in frames:
            writer.writerow([f"{fr.index:05d}", fr.filename, fr.seconds, fr.timestamp])


def extract_frames(
    video: str,
    frames_dir: Path,
    mode: str = "scene",
    interval: int = 5,
    scene_threshold: float = 0.3,
    max_width: int = 1280,
) -> list[Frame]:
    """Extract frames with ffmpeg into frames_dir, write manifest.csv, return the frames.

    - interval mode: one frame every `interval` seconds (even, predictable coverage).
    - scene mode: one frame per detected screen change (best for demos/screencasts).
    """
    _require("ffmpeg")
    frames_dir.mkdir(parents=True, exist_ok=True)
    scale = f",scale={max_width}:-2" if max_width and max_width > 0 else ""
    frames: list[Frame] = []

    with tempfile.TemporaryDirectory() as tmp_name:
        tmp = Path(tmp_name)
        if mode == "interval":
            vf = f"fps=1/{interval}{scale}"
            subprocess.run(
                [
                    "ffmpeg",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-i",
                    video,
                    "-vf",
                    vf,
                    "-vsync",
                    "vfr",
                    str(tmp / "f_%05d.png"),
                ],
                check=True,
            )
            for i, raw in enumerate(sorted(tmp.glob("f_*.png"))):
                frames.append(_place(raw, i, float(i * interval), frames_dir))
        else:  # scene
            _require("ffprobe")
            meta = tmp / "meta.txt"
            vf = f"select='gt(scene,{scene_threshold})',metadata=print:file={meta}{scale}"
            subprocess.run(
                [
                    "ffmpeg",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-i",
                    video,
                    "-vf",
                    vf,
                    "-vsync",
                    "vfr",
                    str(tmp / "s_%05d.png"),
                ],
                check=True,
            )
            times = _parse_scene_times(meta)
            for i, raw in enumerate(sorted(tmp.glob("s_*.png"))):
                secs = times[i] if i < len(times) else 0.0
                frames.append(_place(raw, i, secs, frames_dir))

    _write_manifest(frames_dir, frames)
    return frames


def scene_similarity(frames: list[Frame], frames_dir: Path) -> list[float]:
    """Pixel-to-pixel similarity of each frame to the previous one.

    The first frame gets 0.0. For every next frame the similarity is
    1 - mean(|cur - prev|) / 255 over grayscale pixels, so 1.0 means the
    two shots are identical and 0.0 means maximally different.
    """
    # imported here so the ffmpeg-only paths keep working without Pillow/numpy
    import numpy as np
    from PIL import Image

    sims: list[float] = []
    prev: np.ndarray | None = None
    for fr in frames:
        im = Image.open(frames_dir / fr.filename).convert("L")
        if prev is not None and im.size != (prev.shape[1], prev.shape[0]):
            im = im.resize((prev.shape[1], prev.shape[0]))
        cur = np.asarray(im, dtype=np.float32)
        sims.append(0.0 if prev is None else 1.0 - float(np.abs(cur - prev).mean()) / 255.0)
        prev = cur
    return sims


def drop_duplicates(sims: list[float], quantile: float = 0.98) -> list[bool]:
    """Flag near-duplicate shots from scene_similarity output.

    Builds the similarity distribution, takes its `quantile` cut-off (default
    0.98 - the top 2% most-similar shots), and marks every shot whose
    similarity to the previous one is above that threshold as a duplicate.
    The first shot (similarity 0.0) is never flagged. Returns to_drop flags
    aligned with `sims`.

    One property of a quantile threshold worth keeping in mind: it always
    marks the top ~2% relative to this video's own distribution - on a
    recording with no real duplicates it will still flag the most-similar
    ~2% of shots, and on a mostly-static screencast 2% may be far too few.
    If that becomes a problem, an absolute floor
    (e.g. similarity > max(q98, 0.99)) is a one-line tweak.
    """
    import numpy as np

    threshold = float(np.quantile(sims, quantile))
    to_drop = [sim > threshold for sim in sims]
    print(
        f">> Near-duplicate shots: {sum(to_drop)} of {len(sims)} marked for dropping"
        f" (similarity > q{quantile:.2f} = {threshold:.4f})"
    )
    return to_drop

def _write_records_jsonl(path: Path, rows: list[dict]) -> None:
    """Write all extracted frames as JSONL: manifest.csv fields + similarity and to_drop."""
    with open(path, "w", encoding="utf-8") as fh:
        fh.writelines(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)

def _convert_mov_to_mp4(video_path: str) -> str:
    """Convert a .mov recording to .mp4 next to it (same name) and return the new path."""
    src = Path(video_path)
    if src.suffix.lower() != ".mov":
        return video_path
    _require("ffmpeg")
    dst = src.with_suffix(".mp4")
    print(f">> Converting {src.name} -> {dst.name} ...")
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(src),
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            str(dst),
        ],
        check=True,
    )
    return str(dst)


def _resolve_video(input_arg: str) -> str:
    """Return a local video path, downloading first if input is a YouTube/HTTP URL."""
    if input_arg.startswith(("http://", "https://")):
        from mindbase_layer.utils.youtube import download_video as yt_download_video

        logger.info("URL detected, downloading: %s", input_arg)
        return str(yt_download_video(input_arg, output_dir=Path.home() / "Downloads"))
    return str(Path(input_arg).expanduser().resolve())


def retrieve_frames_pipeline(
    video_file: str,
    output_dir: str | Path | None = None,
    mode: str = "scene",
    interval: int = 5,
    scene_threshold: float = 0.3,
    max_width: int = 1280,
) -> list[Frame]:
    """Extract frames from a video or URL, calculate scene similarity, drop duplicates, and save records."""
    video_path = _resolve_video(video_file)
    if not Path(video_path).is_file():
        raise FileNotFoundError(f"Video file '{video_path}' not found")
    video_path = _convert_mov_to_mp4(video_path)

    stem = Path(video_path).stem
    out_dir = (
        Path(output_dir).expanduser().resolve()
        if output_dir
        else (Path(video_path).parent / stem)
    )
    frames_dir = out_dir / "frames"
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f">> Input:  {video_path}")
    print(f">> Output: {out_dir}")
    print(f">> Extracting frames (mode={mode}) ...")
    frames = extract_frames(
        video_path,
        frames_dir,
        mode=mode,
        interval=interval,
        scene_threshold=scene_threshold,
        max_width=max_width,
    )
    if not frames:
        hint = (
            " Try mode='interval', or lower scene_threshold (e.g. 0.15)."
            if mode == "scene"
            else ""
        )
        raise RuntimeError(f"No frames extracted.{hint}")
    print(f">> Extracted {len(frames)} frames -> {frames_dir}")

    sims = scene_similarity(frames, frames_dir)
    to_drop = drop_duplicates(sims)

    rows = [
        {
            "index": f"{fr.index:05d}",
            "filename": fr.filename,
            "seconds": fr.seconds,
            "timestamp": fr.timestamp,
            "similarity": round(sim, 4),
            "to_drop": drop,
        }
        for fr, sim, drop in zip(frames, sims, to_drop)
    ]
    records_path = out_dir / f"{stem}_frames.jsonl"
    _write_records_jsonl(records_path, rows)
    print(f">> Frame records saved to: {records_path}")

    return frames


# ====== AUDIO SPLITTING =========


def audio_split_pipeline(
    audio_file: str,
    min_interval: float = 300,
    max_interval: float = 500,
    dry_run: bool = False,
) -> list[Path]:
    """Split an audio file into chunks at silence points within [min_interval, max_interval] seconds.

    If dry_run is True, detects and exports silence intervals without calculating split points
    or creating chunk files.
    """
    audio_path = Path(audio_file)
    if not audio_path.exists():
        raise FileNotFoundError(f"Audio file '{audio_path}' not found")

    log_path = audio_path.with_name(audio_path.stem + '_silence.log')
    if not log_path.exists():
        print("Silence log not found, running silence detection...")
        detect_silence(str(audio_path))

    if dry_run:
        print(f"\nDry run mode enabled: silence intervals exported to {log_path}; skipping split and chunk creation.")
        return []

    silence_periods = parse_silence_log(log_path)
    if not silence_periods:
        raise RuntimeError("No silence periods found in log file")

    total_duration = get_audio_duration(audio_path)
    print(f"Audio duration: {format_time(total_duration)}")

    intervals = find_split_points(silence_periods, total_duration, min_interval, max_interval)

    output_path = log_path.with_suffix('.split.log')
    with open(output_path, 'w') as f:
        f.write(f"# Audio split points (min={min_interval}s, max={max_interval}s)\n")
        f.write(f"# Total duration: {format_time(total_duration)}\n")
        f.write(f"# Number of intervals: {len(intervals)}\n\n")
        for i, interval in enumerate(intervals, 1):
            line = f"interval_{i:03d}: {format_time(interval.start)} -> {format_time(interval.end)} (duration: {interval.duration:.2f}s)"
            print(line)
            f.write(line + "\n")

    print(f"\nSplit points saved to: {output_path}")

    print(f"\nSplitting audio into {len(intervals)} chunks...")
    output_files = split_audio_file(audio_path, intervals)
    print(f"\nDone! Created {len(output_files)} audio chunks in {audio_path.parent}")
    return output_files

def parse_silence_log(log_path):
  """Parses FFmpeg silencedetect log and extracts silence intervals."""
  silence_intervals = []
  current_start = None

  with open(log_path, "r", encoding="utf-8") as f:
    for line in f:
      start_match = re.search(r"silence_start:\s*([\d.]+)", line)
      end_match = re.search(r"silence_end:\s*([\d.]+)", line)

      if start_match:
        current_start = float(start_match.group(1))
      elif end_match and current_start is not None:
        current_end = float(end_match.group(1))
        silence_intervals.append((current_start, current_end))
        current_start = None

  return silence_intervals


def get_video_duration(video_path):
  """Gets total video duration in seconds using ffprobe."""
  cmd = [
      "ffprobe",
      "-v",
      "error",
      "-show_entries",
      "format=duration",
      "-of",
      "default=noprint_wrappers=1:nokey=1",
      video_path,
  ]
  result = subprocess.run(
      cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True
  )
  return float(result.stdout.strip())


def generate_speech_intervals(silence_intervals, total_duration, min_speech_duration=0.5):
  """Inverts silence intervals to get speech (keep) intervals."""
  speech_intervals = []
  current_time = 0.0

  for start, end in silence_intervals:
    if start > current_time:
      duration = start - current_time
      if duration >= min_speech_duration:
        speech_intervals.append((current_time, start))
    current_time = max(current_time, end)

  # Add final segment from last silence end to video end
  if current_time < total_duration:
    duration = total_duration - current_time
    if duration >= min_speech_duration:
      speech_intervals.append((current_time, total_duration))

  return speech_intervals


def cut_video(video_path, log_path):
    """Cut silence from video using FFmpeg's concat filter."""
    video_path = Path(video_path)
    output_path = video_path.with_name(f"{video_path.stem}_cut{video_path.suffix}")
    total_duration = get_video_duration(video_path)
    silence_intervals = parse_silence_log(log_path)
    speech_intervals = generate_speech_intervals(silence_intervals, total_duration)

    if not speech_intervals:
        print("Error: No speech intervals found to keep.")
        return

    print(f"Total video duration: {total_duration:.2f}s")
    print(f"Found {len(speech_intervals)} speech segments to keep.")

    filter_parts = []
    concat_inputs = ""
    for i, (start, end) in enumerate(speech_intervals):
        filter_parts.append(f"[0:v]trim=start={start}:end={end},setpts=PTS-STARTPTS[v{i}]")
        filter_parts.append(f"[0:a]atrim=start={start}:end={end},asetpts=PTS-STARTPTS[a{i}]")
        concat_inputs += f"[v{i}][a{i}]"

    filter_str = ";".join(filter_parts)
    filter_str += f";{concat_inputs}concat=n={len(speech_intervals)}:v=1:a=1[outv][outa]"

    encoder_list = subprocess.run(
        ["ffmpeg", "-hide_banner", "-encoders"],
        capture_output=True,
        text=True,
        check=False,
    )
    if "h264_videotoolbox" in encoder_list.stdout:
        video_encoder_args = ["-c:v", "h264_videotoolbox", "-b:v", "800k"]
        print("Using VideoToolbox hardware video encoding.")
    else:
        video_encoder_args = ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "23"]
        print("Using libx264 ultrafast software video encoding.")

    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(video_path),
        "-filter_complex",
        filter_str,
        "-map",
        "[outv]",
        "-map",
        "[outa]",
        *video_encoder_args,
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        str(output_path),
    ]

    print("Running FFmpeg processing (this may take a while)...")
    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(
            f"FFmpeg failed while cutting video (exit code {exc.returncode})."
        ) from None
    print(f"Successfully created: {output_path}")


def cut_audio(audio_path, log_path):
    """Cuts out silent sections from an audio file and writes a _cut output."""
    audio_path = Path(audio_path)
    output_path = audio_path.with_name(f"{audio_path.stem}_cut{audio_path.suffix}")
    total_duration = get_video_duration(audio_path)
    silence_intervals = parse_silence_log(log_path)
    speech_intervals = generate_speech_intervals(silence_intervals, total_duration)

    if not speech_intervals:
        print("Error: No speech intervals found to keep.")
        return

    filter_parts = []
    audio_labels = ""
    for i, (start, end) in enumerate(speech_intervals):
        filter_parts.append(
                f"[0:a]atrim=start={start}:end={end},asetpts=PTS-STARTPTS[a{i}]"
        )
        audio_labels += f"[a{i}]"
    filter_str = ";".join(filter_parts)
    filter_str += f";{audio_labels}concat=n={len(speech_intervals)}:v=0:a=1[outa]"

    cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(audio_path),
            "-filter_complex",
            filter_str,
            "-map",
            "[outa]",
            str(output_path),
    ]
    print(f"Found {len(speech_intervals)} speech segments to keep.")
    subprocess.run(cmd, check=True)
    print(f"Successfully created: {output_path}")


def cut_media(media_path, log_path):
    """Cut silence from a video or audio file, preserving its container extension."""
    result = subprocess.run(
            [
                    "ffprobe",
                    "-v",
                    "error",
                    "-select_streams",
                    "v:0",
                    "-show_entries",
                    "stream=codec_type",
                    "-of",
                    "csv=p=0",
                    str(media_path),
            ],
            capture_output=True,
            text=True,
            check=True,
    )
    if result.stdout.strip():
        cut_video(media_path, log_path)
    else:
        cut_audio(media_path, log_path)