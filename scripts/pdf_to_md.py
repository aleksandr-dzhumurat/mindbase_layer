"""
Extract a page range from a PDF and optionally clean image markers from a markdown file.

To install dependencies:
    uv pip install pypdf docling
    uv pip install paddleocr           # for --backend paddle

Usage:
    uv run python scripts/pdf_to_md.py --input $(pwd)/data/long_boring_demo.pdf
    uv run python scripts/pdf_to_md.py --start 148 --end 155 --input $(pwd)/data/long_boring_demo.pdf
    uv run python scripts/pdf_to_md.py --input $(pwd)/file.pdf --backend paddle
"""

import argparse
import logging
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from mindbase_layer.utils.pdf_to_md import convert, convert_paddle, filter_pages, get_pdf_num_pages, reformat_image_links, remove_images

__all__ = ["convert", "convert_paddle", "filter_pages", "get_pdf_num_pages", "reformat_image_links", "remove_images"]

def _process_single(pdf_path: Path, start: int, end: int | None, clear: bool = False, backend: str = "docling") -> None:
    end_provided = end is not None
    if end is None:
        end = get_pdf_num_pages(pdf_path)

    if not end_provided and start == 1:
        extracted_pdf = pdf_path
    else:
        extracted_pdf = filter_pages(start, end, pdf_path)

    if backend == "paddle":
        convert_paddle(extracted_pdf)
    else:
        convert(extracted_pdf, start)
        output_dir = extracted_pdf.resolve().with_suffix("")
        reformat_image_links(output_dir)
        if clear and output_dir.exists():
            shutil.rmtree(output_dir)
            logging.info("Removed output dir %s", output_dir)

    logging.info("Done! Processed %d pages from %s.", end - start + 1, pdf_path.name)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Extract PDF pages and clean markdown images")
    parser.add_argument("--start", type=int, default=1, help="First page to extract (1-indexed)")
    parser.add_argument("--end", type=int, help="Last page to extract (1-indexed)")
    parser.add_argument("--input", type=Path, required=True, help="Path to source PDF file or directory")
    parser.add_argument("--clear", action="store_true", help="Remove output_dir after reformatting image links")
    parser.add_argument("--backend", type=str, default="docling", choices=["docling", "paddle"], help="Conversion backend (default: docling)")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    def _maybe_clear(pdf_path: Path) -> None:
        output_dir = pdf_path.resolve().with_suffix("")
        if output_dir.exists():
            shutil.rmtree(output_dir)
            logging.info("Removed output dir %s", output_dir)

    if args.input.is_dir():
        for pdf_file in sorted(args.input.glob("*.pdf")):
            md_output = pdf_file.with_suffix(".md")
            if md_output.exists():
                logging.info("Skipping %s (already converted)", pdf_file.name)
                if args.clear:
                    _maybe_clear(pdf_file)
                continue
            logging.info("Converting %s ...", pdf_file.name)
            _process_single(pdf_file, start=1, end=None, clear=args.clear, backend=args.backend)
    else:
        md_output = args.input.with_suffix(".md")
        if md_output.exists():
            logging.info("Skipping %s (already converted)", args.input.name)
            if args.clear:
                _maybe_clear(args.input)
        else:
            _process_single(args.input, args.start, args.end, clear=args.clear, backend=args.backend)
