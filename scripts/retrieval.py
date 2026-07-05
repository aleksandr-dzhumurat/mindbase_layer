#!/usr/bin/env python3
"""
TF-IDF based document index for markdown and SRT files.

Usage:
    uv run python scripts/retrieval.py --path path/to/file.md --query "your search query"
    uv run python scripts/retrieval.py --path path/to/file.srt --query "fine-tuning" --top-k 3
    uv run python scripts/retrieval.py --path /Users/adzhumurat/PycharmProjects/LLM_course/course_materials --query "chain rule"

    Interactive REPL mode:
    uv run python scripts/retrieval.py --path path/to/docs --repl
    uv run python scripts/retrieval.py --path path/to/docs --repl --top-k 10
"""

import argparse
import itertools
import logging
import re
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from mindbase_layer.utils.formatting import print_search_results  # noqa: E402
from mindbase_layer.utils.retrieve_md import DocumentIndex, DocumentNode  # noqa: E402

__all__ = ["DocumentIndex"]

# ANSI color codes
_RESET   = "\033[0m"
_BOLD    = "\033[1m"
_DIM     = "\033[2m"
_CYAN    = "\033[36m"
_GREEN   = "\033[32m"
_YELLOW  = "\033[33m"
_RED     = "\033[31m"
_BLUE    = "\033[34m"
_MAGENTA = "\033[35m"
_WHITE   = "\033[97m"


def _clickable(url: str, text: str | None = None) -> str:
    """Wrap text in an OSC 8 hyperlink escape sequence (clickable in modern terminals)."""
    label = text or url
    return f"\033]8;;{url}\033\\{label}\033]8;;\033\\"


def _score_color(score: float) -> str:
    if score >= 0.6:
        return _GREEN
    elif score >= 0.3:
        return _YELLOW
    else:
        return _RED


def _score_bar(score: float, width: int = 8) -> str:
    filled = round(score * width)
    bar = "█" * filled + "░" * (width - filled)
    return f"{_score_color(score)}{bar}{_RESET}"


def _highlight_snippet(text: str, query: str, snippet_length: int = 120) -> str:
    if not text:
        return ""
    terms = [re.escape(t) for t in query.split() if t.strip()]
    if not terms:
        snippet = text[:snippet_length]
        return (snippet + "...") if len(text) > snippet_length else snippet
    pattern = re.compile(r'(' + '|'.join(terms) + r')', re.IGNORECASE)
    match = pattern.search(text)
    if match:
        start = max(0, match.start() - snippet_length // 2)
        end = min(len(text), match.end() + snippet_length // 2)
        snippet = text[start:end]
        if start > 0:
            snippet = "..." + snippet
        if end < len(text):
            snippet += "..."
        highlighted = pattern.sub(lambda m: f"{_BOLD}\033[93m{m.group(0)}{_RESET}", snippet)
        return highlighted.replace("\n", " ")
    snippet = text[:snippet_length]
    if len(text) > snippet_length:
        snippet += "..."
    return snippet.replace("\n", " ")


def _source_label(node: DocumentNode) -> str:
    """Build a (possibly clickable) source label from a DocumentNode."""
    source_name = node.source.name if node.source else "Unknown"
    if node.source and node.line_start is not None:
        file_uri = f"file://{node.source.resolve()}#{node.line_start}"
        label = f"{source_name}:{node.line_start}"
        return _clickable(file_uri, f"{_CYAN}{label}{_RESET}")
    return f"{_CYAN}{source_name}{_RESET}"


def _print_result(rank: int, score: float, node: DocumentNode, snippet: str) -> None:
    divider = f"{_DIM}{'─' * 60}{_RESET}"
    score_bar = _score_bar(score)
    score_val = f"{_score_color(score)}{_BOLD}{score:.3f}{_RESET}"
    rank_tag = f"{_MAGENTA}#{rank}{_RESET}"
    src = _source_label(node)
    hdr = f"{_WHITE}{_BOLD}{node.header.strip()}{_RESET}"

    print(divider)
    print(f"  {rank_tag}  {score_bar} {score_val}  {src}")
    print(f"  {_BLUE}❯{_RESET} {hdr}")
    if snippet:
        print(f"  {_DIM}{snippet}{_RESET}")


def _spinner(stop_event: threading.Event) -> None:
    for frame in itertools.cycle(["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]):
        if stop_event.is_set():
            break
        sys.stdout.write(f"\r{_CYAN}🔍 Searching... {frame}{_RESET} ")
        sys.stdout.flush()
        time.sleep(0.1)
    sys.stdout.write("\r" + " " * 30 + "\r")
    sys.stdout.flush()


def _build_index(path: Path, ext: str | None = None) -> DocumentIndex:
    if path.is_dir():
        return DocumentIndex.from_dir(path, ext=ext)
    elif path.suffix == '.srt':
        return DocumentIndex.from_srt_file(path)
    else:
        return DocumentIndex.from_md_file(path)


def _run_repl(index: DocumentIndex, top_k: int = 5) -> None:
    print(f"\n{_CYAN}{_BOLD}{'═' * 60}{_RESET}")
    print(f"  {_GREEN}✔ Index ready: {_BOLD}{len(index._nodes)}{_RESET}{_GREEN} sections{_RESET}")
    print(f"{_CYAN}{_BOLD}{'═' * 60}{_RESET}")
    print(f"  {_DIM}Type your query or 'exit' to quit.{_RESET}\n")

    try:
        while True:
            user_input = input(f"{_BOLD}{_YELLOW}👤 You:{_RESET} ").strip()
            if not user_input or user_input.lower() == "exit":
                print(f"\n{_CYAN}Goodbye!{_RESET}\n")
                break

            stop = threading.Event()
            spinner = threading.Thread(target=_spinner, args=(stop,), daemon=True)
            spinner.start()
            results = index.search(user_input, top_k=top_k)
            stop.set()
            spinner.join()

            if not results:
                print("No matching nodes found.\n")
                continue

            print(f"\n{_GREEN}{_BOLD}Found {len(results)} results{_RESET}")
            for rank, (score, node) in enumerate(results, start=1):
                snippet = _highlight_snippet(node.body, user_input)
                _print_result(rank, score, node, snippet)
            print(f"{_DIM}{'─' * 60}{_RESET}\n")
    except (KeyboardInterrupt, EOFError):
        print(f"\n{_CYAN}Goodbye!{_RESET}\n")


def main():
    logging.basicConfig(level=logging.INFO, format="%(name)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="TF-IDF search over markdown document nodes")
    parser.add_argument("--path", type=Path, required=True, help="Path to markdown or .srt file (or directory of .md files)")
    parser.add_argument("--query", type=str, default=None, help="Search query")
    parser.add_argument("--top-k", type=int, default=5, dest="top_k", help="Number of results (default: 5)")
    parser.add_argument("--ext", type=str, default=None, choices=["md", "srt"], help="Limit directory scan to this extension (md or srt)")
    parser.add_argument("--repl", action="store_true", help="Run interactive REPL chat mode")
    args = parser.parse_args()

    if args.repl:
        index = _build_index(args.path, ext=args.ext)
        _run_repl(index, top_k=args.top_k)
        return

    if not args.query:
        parser.error("--query is required when not using --repl")

    index = _build_index(args.path, ext=args.ext)
    results = index.search(args.query, top_k=args.top_k)

    if not results:
        print("No matching nodes found.")
        return

    print(f"Top {len(results)} results for: \"{args.query}\"\n")
    print_search_results(results, args.query)


if __name__ == "__main__":
    main()
