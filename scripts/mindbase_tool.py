#!/usr/bin/env python3
"""
mindbase-tool — non-interactive CLI for the mindbase pipeline.

Unlike `mindbase-cli` (chat REPL) and `mindbase` (desktop app), this is a
scriptable command in the style of indrive-tools: one shot in, artifacts out.

Commands:
    mindbase-tool summarize  --input <video|audio|youtube-url> [--lang ru]
    mindbase-tool transcribe --input <video|audio|youtube-url> [--lang ru]
    mindbase-tool translate  --input <file.md|.srt|.txt>
"""

import argparse
import asyncio
import logging
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

logging.basicConfig(level=logging.INFO, format="%(name)s %(levelname)s %(message)s", stream=sys.stdout)
logger = logging.getLogger("mindbase-tool")

YOUTUBE_HOSTS = ("youtube.com", "youtu.be")


def _is_youtube_url(value: str) -> bool:
    return any(host in value for host in YOUTUBE_HOSTS)


def _resolve_input(input_arg: str) -> Path:
    if _is_youtube_url(input_arg):
        from mindbase_layer.utils.youtube import download_video
        logger.info("Downloading YouTube video: %s", input_arg)
        return download_video(input_arg, output_dir=Path.home() / "Downloads")
    path = Path(input_arg).expanduser().resolve()
    if not path.is_file():
        print(f"ERROR: file not found: {path}", file=sys.stderr)
        sys.exit(1)
    return path


def _load_full_text(text_path: Path) -> str | None:
    if text_path.suffix.lower() == ".srt":
        from mindbase_layer.utils.retrieve_md import squash_srt
        nodes = squash_srt(text_path)
        if not nodes:
            return None
        return "\n\n".join(f"[{n.header}]\n{n.body}" for n in nodes)
    return text_path.read_text(encoding="utf-8")


def cmd_transcribe(args: argparse.Namespace) -> None:
    from mindbase_layer import tools

    video_path = _resolve_input(args.input)
    print(tools.generate_subtitles(str(video_path), args.lang))


def cmd_summarize(args: argparse.Namespace) -> None:
    from mindbase_layer.agent import SummarizeDependencies, _summarizer_agent
    from mindbase_layer.utils.media import extract_audio_pipeline, transcribe

    path = _resolve_input(args.input)
    lang = args.lang

    srt_path = path.with_suffix(".srt")
    if srt_path.exists():
        logger.info("Using existing subtitles: %s", srt_path)
    else:
        logger.info("Extracting audio + transcribing %s", path.name)
        mp3_path = str(extract_audio_pipeline(str(path)))
        srt_path = Path(transcribe(mp3_path, language=lang))

    summary_path = srt_path.with_name(f"{srt_path.stem}_summary.md")
    if summary_path.exists():
        logger.info("Using existing summary: %s", summary_path)
        summary_text = summary_path.read_text(encoding="utf-8")
    else:
        full_text = _load_full_text(srt_path)
        if not full_text:
            print(f"ERROR: could not extract text from {srt_path}", file=sys.stderr)
            sys.exit(1)
        logger.info("Summarizing transcript (%d chars)", len(full_text))
        result = _summarizer_agent.run_sync(
            "Summarize this video transcript.",
            deps=SummarizeDependencies(text=full_text, language=lang),
        )
        summary_text = result.output
        summary_path.write_text(summary_text, encoding="utf-8")
        logger.info("Summary saved: %s", summary_path)

    en_path = None
    if lang != "en":
        candidate = summary_path.with_name(f"{summary_path.stem}_en.md")
        if candidate.exists():
            logger.info("Using existing translation: %s", candidate)
            en_path = candidate
        else:
            logger.info("Translating summary to English")
            from mindbase_layer.agent_core.llm_adapter import LLMAdapter

            result = asyncio.run(LLMAdapter().translate(summary_text))
            candidate.write_text(result.text, encoding="utf-8")
            en_path = candidate
            logger.info("Translation saved: %s", en_path)

    out_dir = path.parent / path.stem
    out_dir.mkdir(exist_ok=True)
    artifacts = [summary_path, srt_path, path.with_suffix(".mp3")]
    if en_path:
        artifacts.append(en_path)
    for artifact in artifacts:
        if artifact.exists() and artifact.parent != out_dir:
            shutil.move(str(artifact), str(out_dir / artifact.name))

    print(f"Artifacts saved to: {out_dir}")


def cmd_translate(args: argparse.Namespace) -> None:
    from mindbase_layer.agent_core.llm_adapter import LLMAdapter

    path = Path(args.input).expanduser().resolve()
    if not path.is_file():
        print(f"ERROR: file not found: {path}", file=sys.stderr)
        sys.exit(1)

    text = _load_full_text(path)
    if not text:
        print(f"ERROR: could not extract text from {path}", file=sys.stderr)
        sys.exit(1)

    logger.info("Translating %s to English", path.name)
    result = asyncio.run(LLMAdapter().translate(text))
    out_path = path.with_name(f"{path.stem}_en.md")
    out_path.write_text(result.text, encoding="utf-8")
    print(f"Translation saved: {out_path}")


def main() -> None:
    parser = argparse.ArgumentParser(prog="mindbase-tool", description="Non-interactive mindbase pipeline CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    p_summarize = sub.add_parser("summarize", help="Transcribe, summarize, and (if non-English) translate a recording")
    p_summarize.add_argument("--input", required=True, help="Path to video/audio file, or a YouTube URL")
    p_summarize.add_argument("--lang", default="en", help="Spoken language code, e.g. ru, en, sr (default: en)")
    p_summarize.set_defaults(func=cmd_summarize)

    p_transcribe = sub.add_parser("transcribe", help="Extract an .srt subtitles file from a video/audio file")
    p_transcribe.add_argument("--input", required=True, help="Path to video/audio file, or a YouTube URL")
    p_transcribe.add_argument("--lang", default="en", help="Spoken language code (default: en)")
    p_transcribe.set_defaults(func=cmd_transcribe)

    p_translate = sub.add_parser("translate", help="Translate a .md/.srt/.txt file to English")
    p_translate.add_argument("--input", required=True, help="Path to the file to translate")
    p_translate.set_defaults(func=cmd_translate)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
