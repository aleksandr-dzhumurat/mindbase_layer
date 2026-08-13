#!/usr/bin/env python3
"""
daily_pipeline.py — summarize an SRT transcript and translate to English.

Steps:
  1. Parse the SRT file into text chunks.
  2. Summarize using the configured LLM (pydantic-ai agent).
  3. Translate the summary to English (skipped if --lang en).
  4. Save the English summary to --output_dir.

Usage:
  python scripts/daily_pipeline.py --input recording.srt --output_dir ./summaries
  python scripts/daily_pipeline.py --input recording.srt --output_dir ./summaries --lang ru

Requires:
  NEBIUS_API_KEY or GOOGLE_API_KEY in .env (or environment).
"""

import argparse
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR / "src"))

from dotenv import load_dotenv

load_dotenv(ROOT_DIR / ".env")


def run(input_path: str, output_dir: str, lang: str = "ru") -> str:
    srt_path = Path(input_path).resolve()
    out_dir = Path(output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    if not srt_path.exists():
        sys.exit(f"Input file not found: {srt_path}")

    stem = srt_path.stem

    # 1. Parse input
    if srt_path.suffix.lower() == ".srt":
        from mindbase_layer.utils.retrieve_md import squash_srt

        print(f"Parsing SRT: {srt_path}")
        nodes = squash_srt(srt_path)
        if not nodes:
            sys.exit("No text extracted from subtitles")
        full_text = "\n\n".join(f"[{n.header}]\n{n.body}" for n in nodes)
    else:
        print(f"Reading text: {srt_path}")
        full_text = srt_path.read_text(encoding="utf-8")

    # 2. Summarize
    summary_path = out_dir / f"{stem}_summary.md"
    if summary_path.exists():
        print(f"Using existing summary: {summary_path}")
        summary_text = summary_path.read_text(encoding="utf-8")
    else:
        print("Generating summary...")
        from mindbase_layer.agent import SummarizeDependencies, _summarizer_agent

        result = _summarizer_agent.run_sync(
            "Summarize this video transcript.",
            deps=SummarizeDependencies(text=full_text, language=lang),
        )
        summary_text = result.output
        summary_path.write_text(summary_text, encoding="utf-8")
        print(f"Summary saved: {summary_path} ({len(summary_text):,} chars)")
        usage = result.usage
        print(f"Tokens — input: {usage.request_tokens:,}  output: {usage.response_tokens:,}  total: {usage.total_tokens:,}")

    # 3. Translate to English
    if lang == "en":
        en_text = summary_text
        en_path = summary_path
    else:
        en_path = out_dir / f"{stem}_summary_en.md"
        if en_path.exists():
            print(f"Using existing translation: {en_path}")
            en_text = en_path.read_text(encoding="utf-8")
        else:
            print("Translating to English...")
            from mindbase_layer.agent import TranslationDependencies, translation_agent

            tr_result = translation_agent.run_sync(
                summary_text,
                deps=TranslationDependencies(text=summary_text),
            )
            en_text = tr_result.output
            en_path.write_text(en_text, encoding="utf-8")
            print(f"Translation saved: {en_path} ({len(en_text):,} chars)")
            usage = tr_result.usage
            print(f"Tokens — input: {usage.request_tokens:,}  output: {usage.response_tokens:,}  total: {usage.total_tokens:,}")

    print(f"\nDone: {en_path}")
    return str(en_path)


def main():
    parser = argparse.ArgumentParser(
        description="Summarize an SRT transcript and translate to English."
    )
    parser.add_argument("--input", required=True, help="Path to .srt or text file")
    parser.add_argument("--output_dir", required=True, help="Directory for output summaries")
    parser.add_argument("--lang", default="ru", help="Source language (default: ru)")
    args = parser.parse_args()

    run(args.input, args.output_dir, lang=args.lang)


if __name__ == "__main__":
    main()
