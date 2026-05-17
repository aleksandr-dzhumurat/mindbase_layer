import logging
import re
from pathlib import Path

import pypdf
from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling.exceptions import ConversionError
from docling_core.types.doc import ImageRefMode, PictureItem, TableItem


def filter_pages(start, end, pdf_path):
    """Extract pages [start, end] (1-indexed) from a PDF and save to a new file."""
    pdf_path = Path(pdf_path).resolve()

    output = pdf_path.with_name(f"{pdf_path.stem}_{start}-{end}.pdf")
    if output.exists():
        print(f"⚠️  Warning: file already exists, skipping extraction → {output}")
        return output

    reader = pypdf.PdfReader(pdf_path)
    total = len(reader.pages)

    if start < 1 or end > total or start > end:
        raise SystemExit(f"Invalid range {start}-{end} (PDF has {total} pages)")

    writer = pypdf.PdfWriter()
    for i in range(start - 1, end):  # convert to 0-indexed
        writer.add_page(reader.pages[i])

    with output.open("wb") as f:
        writer.write(f)

    print(f"Saved {end - start + 1} pages → {output}")
    return output


def get_pdf_num_pages(pdf_path: Path) -> int:
    """Get the total number of pages in a PDF file."""
    reader = pypdf.PdfReader(pdf_path)
    return len(reader.pages)


def remove_images(file_path, output_path):
    """Remove ![Image](...) markers from a markdown file."""
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()

    pattern = r"!\[Image\]\([^)]+\)"
    cleaned_content = re.sub(pattern, "", content)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(cleaned_content)

    print(f"Images removed → {output_path}")


def reformat_image_links(output_dir: Path) -> None:
    """Copy the .md from output_dir one level up and prefix bare image paths with the dir name."""
    md_files = list(output_dir.glob("*.md"))
    if not md_files:
        logging.warning("No .md file found in %s", output_dir)
        return

    md_file = md_files[0]
    dest = output_dir.parent / md_file.name
    content = md_file.read_text(encoding="utf-8")

    dirname_only = output_dir.name
    # Rewrite ![alt](bare_filename) -> ![alt](dirname/bare_filename)
    # Only matches paths without a slash (bare filenames)
    content = re.sub(
        r'!\[([^\]]*)\]\(([^/)][^)]*)\)',
        lambda m: f"![{m.group(1)}]({dirname_only}/{m.group(2)})",
        content,
    )

    dest.write_text(content, encoding="utf-8")
    image_count = content.count("![")
    logging.info("Created: %s (image links updated: %d)", dest, image_count)


def convert(pdf_path: Path, start_page: int) -> None:
    """Convert a PDF to markdown with extracted images, adding slide numbers."""
    pdf_path = Path(pdf_path).resolve()
    output_dir = pdf_path.with_suffix("")  # e.g. data/my_file_148-155/
    output_dir.mkdir(parents=True, exist_ok=True)

    # Get total pages in the filtered PDF
    reader = pypdf.PdfReader(pdf_path)
    num_pages = len(reader.pages)

    md_path = output_dir / f"{pdf_path.stem}.md"
    full_md_content = []

    # Counters for consistent image naming across pages
    pic_counter = 0
    tbl_counter = 0

    # Initialize converter once
    pipeline_options = PdfPipelineOptions()
    pipeline_options.images_scale = 2.0
    pipeline_options.generate_picture_images = True
    pipeline_options.generate_table_images = True

    converter = DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)
        }
    )

    for i in range(1, num_pages + 1):
        actual_slide_no = start_page + i - 1
        logging.info("Processing slide %d (page %d/%d)...", actual_slide_no, i, num_pages)

        # Convert exactly one page at a time using page_range param
        try:
            result = converter.convert(pdf_path, page_range=(i, i))
        except ConversionError as e:
            logging.warning("Skipping page %d: %s", actual_slide_no, e)
            full_md_content.append(f"## Slide {actual_slide_no}\n\n*(page could not be converted)*")
            continue
        doc = result.document
        stem = pdf_path.stem

        # --- save figures and tables as separate PNGs and collect paths ---
        page_image_refs = []
        for element, _level in doc.iterate_items():
            if isinstance(element, PictureItem) and element.image:
                pic_counter += 1
                img_name = f"{stem}-figure-{pic_counter}.png"
                img_path = output_dir / img_name
                with img_path.open("wb") as f:
                    element.image.pil_image.save(f, format="PNG")
                logging.info("Saved figure : %s", img_path)
                page_image_refs.append(f"![Figure]({img_name})")

            elif isinstance(element, TableItem) and element.image:
                tbl_counter += 1
                img_name = f"{stem}-table-{tbl_counter}.png"
                img_path = output_dir / img_name
                with img_path.open("wb") as f:
                    element.image.pil_image.save(f, format="PNG")
                logging.info("Saved table  : %s", img_path)
                page_image_refs.append(f"![Table]({img_name})")

        # --- export Markdown for this single page ---
        page_md = doc.export_to_markdown(image_mode=ImageRefMode.PLACEHOLDER)

        # Replace placeholders with actual image references
        def replace_placeholder(_match):
            return page_image_refs.pop(0) if page_image_refs else _match.group(0)

        # Docling 2.x uses "<!-- image -->" as placeholder
        page_md = re.sub(r"<!-- image -->", replace_placeholder, page_md)

        # Add Slide Header and the content
        full_md_content.append(f"## Slide {actual_slide_no}\n\n{page_md}")

    # Write the combined markdown
    md_path.write_text("\n\n---\n\n".join(full_md_content), encoding="utf-8")
    logging.info("Saved combined markdown: %s", md_path)
    logging.info("Total Figures: %d  Total Tables: %d", pic_counter, tbl_counter)
