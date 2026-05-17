import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import mlx_whisper as whisper
from tqdm import tqdm

_WHISPER_MODEL = "mlx-community/whisper-medium"


def extract_audio_pipeline(video_path: str = None):
    if video_path is None:
        if len(sys.argv) < 2:
            print("Usage: python scripts/extract_audio.py <path_to_video_file>")
            sys.exit(1)
        video_path = sys.argv[1]

    input_file = Path(video_path)

    if not input_file.is_file():
        print(f"Error: File '{input_file}' not found")
        sys.exit(1)

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


def audio_split_pipeline(audio_file: str, min_interval: float = 300, max_interval: float = 500) -> list[Path]:
    """Split an audio file into chunks at silence points within [min_interval, max_interval] seconds."""
    audio_path = Path(audio_file)
    if not audio_path.exists():
        raise FileNotFoundError(f"Audio file '{audio_path}' not found")

    log_path = audio_path.with_name(audio_path.stem + '_silence.log')
    if not log_path.exists():
        print("Silence log not found, running silence detection...")
        detect_silence(str(audio_path))

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
