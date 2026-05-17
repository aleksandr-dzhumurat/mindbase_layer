#!/usr/bin/env python3
"""
TF-IDF based document index for markdown and SRT files.

Usage:
    uv run python scripts/retrieval.py --path path/to/file.md --query "your search query"
    uv run python scripts/retrieval.py --path path/to/file.srt --query "fine-tuning" --top-k 3
    
    works with srt
    uv run python scripts/retrieval.py --path /Users/adzhumurat/PycharmProjects/LLM_course/course_materials --query "chain rule"
"""

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from mindbase_layer.utils.formatting import print_search_results  # noqa: E402
from mindbase_layer.utils.retrieve_md import DocumentIndex  # noqa: E402

__all__ = ["DocumentIndex"]


def main():
    logging.basicConfig(level=logging.INFO, format="%(name)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="TF-IDF search over markdown document nodes")
    parser.add_argument("--path", type=Path, required=True, help="Path to markdown or .srt file (or directory of .md files)")
    parser.add_argument("--query", type=str, required=True, help="Search query")
    parser.add_argument("--top-k", type=int, default=5, dest="top_k", help="Number of results (default: 5)")
    parser.add_argument("--ext", type=str, default=None, choices=["md", "srt"], help="Limit directory scan to this extension (md or srt)")
    args = parser.parse_args()

    if args.path.is_dir():
        index = DocumentIndex.from_dir(args.path, ext=args.ext)
    elif args.path.suffix == '.srt':
        index = DocumentIndex.from_srt_file(args.path)
    else:
        index = DocumentIndex.from_md_file(args.path)
    results = index.search(args.query, top_k=args.top_k)

    if not results:
        print("No matching nodes found.")
        return

    print(f"Top {len(results)} results for: \"{args.query}\"\n")
    print_search_results(results, args.query)


if __name__ == "__main__":
    main()
