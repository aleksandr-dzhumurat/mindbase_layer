import logging
import shutil
from pathlib import Path

from .utils.audio import convert_to_mp3, extract_audio_pipeline, transcribe
from .utils.pdf_to_md import convert, reformat_image_links
from .utils.retrieve_md import DocumentIndex, DocumentNode, squash_srt
from .utils.youtube import download_audio as yt_download_audio
from .utils.youtube import download_video as yt_download_video

logger = logging.getLogger(__name__)

SEARCH_DIRS = ["Downloads", "Documents", "PycharmProjects"]


def query_documents(md_path: Path, query: str) -> str:
    """Search the indexed markdown document(s) using TF-IDF cosine similarity."""
    if md_path.is_dir():
        index = DocumentIndex.from_dir(md_path)
    elif md_path.suffix == ".srt":
        index = DocumentIndex.from_srt_file(md_path)
    else:
        index = DocumentIndex.from_md_file(md_path)
    results = index.search(query, top_k=5)
    if not results:
        return f"No results found for query: '{query}'"
    lines = [f"Found {len(results)} matching nodes:"]
    for score, node in results:
        lines.append(f"\n[{score:.4f}] {node.header}")
        if node.body:
            lines.append(node.body[:500])
    return "\n".join(lines)


def file_search(filename: str, home_dir: Path) -> str:
    """Search for a file by name across SEARCH_DIRS under home_dir.
    If filename is an absolute path, checks existence directly without searching."""
    path = Path(filename)
    if path.is_absolute():
        return str(path) if path.exists() else f"File not found: {path}"
    matches = []
    for search_dir in SEARCH_DIRS:
        base = home_dir / search_dir
        if base.is_dir():
            matches.extend(base.rglob(filename))
    if not matches:
        return f"File '{filename}' not found in {SEARCH_DIRS}"
    if len(matches) == 1:
        return str(matches[0])
    return "Multiple files found:\n" + "\n".join(str(p) for p in matches)


def file_fuzzy_search(query: str, home_dir: Path) -> str:
    """Fuzzy search for a file by query across SEARCH_DIRS.
    Indexes all filenames with TF-IDF and returns top-10 matches."""
    nodes = []
    for search_dir in SEARCH_DIRS:
        base = home_dir / search_dir
        if base.is_dir():
            for path in base.rglob("*"):
                if path.is_file():
                    normalized = path.stem.replace("_", " ").replace("-", " ")
                    nodes.append(DocumentNode(header=path.name, body=normalized, source=path))
    if not nodes:
        return "No files found in search directories."
    index = DocumentIndex(nodes)
    results = index.search(query, top_k=10)
    if not results:
        return f"No files matching '{query}' found."
    lines = [f"Top {len(results)} fuzzy matches for '{query}':"]
    for score, node in results:
        lines.append(f"  [{score:.4f}] {node.source}")
    return "\n".join(lines)


def pdf_to_md(pdf_path: str) -> str:
    """Convert a PDF file to markdown. Skips if output already exists."""
    path = Path(pdf_path).resolve()
    output_dir = path.with_suffix("")
    md_path = output_dir.parent / f"{path.stem}.md"
    if md_path.exists():
        return f"Markdown already exists: {md_path}"
    convert(path, start_page=1)
    reformat_image_links(output_dir)
    return f"Markdown saved to: {md_path}"


def generate_subtitles(video_path: str, language: str) -> str:
    """Generate an SRT subtitles file from a video. language is a BCP-47 code e.g. 'en', 'ru'."""
    mp3_path = str(extract_audio_pipeline(video_path))
    srt_path = transcribe(mp3_path, language=language)
    return f"Subtitles saved to: {srt_path}"


async def summarize_video(video_path: str, spoken_language: str, summarizing_agent, deps_cls, usage) -> str:
    """Generate subtitles if missing, then summarise the transcript with summarizing_agent."""
    path = Path(video_path)
    srt_path = path.with_suffix(".srt")
    if not srt_path.exists():
        logger.info("summarize_video: generating subtitles for %s (lang=%s)", path.name, spoken_language)
        mp3_path = str(extract_audio_pipeline(video_path))
        srt_path = Path(transcribe(mp3_path, language=spoken_language))
    else:
        logger.info("summarize_video: using existing subtitles %s", srt_path.name)
    logger.info("summarize_video: indexing %s", srt_path.name)
    nodes = squash_srt(srt_path)
    if not nodes:
        return f"Could not extract text from {srt_path}"
    logger.info("summarize_video: summarizing %d chunks", len(nodes))
    full_text = "\n\n".join(f"[{node.header}]\n{node.body}" for node in nodes)
    result = await summarizing_agent.run(
        "Summarize this video transcript.",
        deps=deps_cls(text=full_text, language=spoken_language),
        usage=usage,
    )
    u = result.usage()
    logger.info("summarize_video tokens: input=%d output=%d total=%d", u.input_tokens, u.output_tokens, u.input_tokens + u.output_tokens)
    summary_path = srt_path.with_name(f"{srt_path.stem}_summary.md")
    summary_path.write_text(result.output, encoding="utf-8")
    logger.info("summarize_video: summary saved to %s", summary_path)
    return str(summary_path.resolve())


async def youtube_download(url: str, mode: str, youtube_dir: Path) -> str:
    """Download a YouTube video or audio track. mode must be 'video' or 'audio'."""
    youtube_dir.mkdir(parents=True, exist_ok=True)
    if mode == "audio":
        path = yt_download_audio(url, output_dir=youtube_dir)
    else:
        path = yt_download_video(url, output_dir=youtube_dir)
    return f"Downloaded to: {path}"


def m4a_to_mp3(input_path: str) -> str:
    """Convert an m4a (or other audio) file to mp3. Expects a full resolved path."""
    output_file = convert_to_mp3(input_path)
    return f"MP3 saved to: {output_file}"


async def translate_file(md_path: str, translating_agent, deps_cls, usage) -> str:
    """Read a markdown file and translate its content from Russian to English using translating_agent.
    Writes the result to a sibling file with _en suffix and returns its path."""
    path = Path(md_path).expanduser().resolve()
    if not path.is_file():
        return f"File not found: {path}"
    text = path.read_text(encoding="utf-8")
    result = await translating_agent.run(
        text,
        deps=deps_cls(text=text),
        usage=usage,
    )
    out_path = path.with_name(f"{path.stem}_en{path.suffix}")
    out_path.write_text(result.output, encoding="utf-8")
    logger.info("translate_file: saved translation to %s", out_path)
    return str(out_path.resolve())


def remove_file(file_path: str) -> str:
    """Delete a file or directory. Uses shutil.rmtree for directories, Path.unlink for files."""
    path = Path(file_path).expanduser().resolve()
    if not path.exists():
        return f"Not found: {path}"
    if path.is_dir():
        shutil.rmtree(path)
        return f"Directory removed: {path}"
    path.unlink()
    return f"File removed: {path}"

