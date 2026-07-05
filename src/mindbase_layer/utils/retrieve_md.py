import hashlib
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

import tiktoken
from sklearn.feature_extraction.text import TfidfVectorizer

logger = logging.getLogger(__name__)

_TIKTOKEN_ENCODING = "cl100k_base"

# ---------------------------------------------------------------------------
# Text filters – remove noise before embedding / retrieval
# ---------------------------------------------------------------------------

_RE_CODE_BLOCK = re.compile(r"```python\s*\n.*?```", re.DOTALL)
_RE_LATEX_BLOCK = re.compile(r"\$\$.*?\$\$", re.DOTALL)
_RE_LATEX_INLINE = re.compile(r"\$[^$\n]+\$")
_RE_MD_LINK = re.compile(r"\[([^\]]*)\]\(https?://[^\)]+\)")
_RE_BARE_URL = re.compile(r"https?://\S+")


def strip_code_blocks(text: str) -> str:
    """Remove fenced Python code blocks (```python ... ```)."""
    return _RE_CODE_BLOCK.sub("", text)


def strip_latex(text: str) -> str:
    """Remove LaTeX formulas: multi-line $$...$$ and inline $...$."""
    text = _RE_LATEX_BLOCK.sub("", text)
    return _RE_LATEX_INLINE.sub("", text)


def strip_urls(text: str) -> str:
    """Clean URLs: markdown links keep title, bare URLs removed."""
    text = _RE_MD_LINK.sub(r"\1", text)
    return _RE_BARE_URL.sub("", text)
_MERGE_MAX_TOKENS = 512
_OVERLAP_BLOCKS = 3


@dataclass
class Slide:
    num: int
    body: str


@dataclass
class DocumentNode:
    header: str
    body: str | None = None
    source: Path | None = None
    parent: "DocumentNode | None" = None
    line_start: int | None = None
    line_end: int | None = None
    node_name: str = field(init=False)

    def __post_init__(self):
        self.node_name = hashlib.md5((self.header + self.body).encode()).hexdigest()

    def __str__(self):
        return f"{self.header}\n{self.body[:300]}...\n{self.node_name}"


def is_duplicate(body1: str, body2: str, mode: str = "exact") -> bool:
    """Check if two slide bodies are duplicates using the specified mode."""
    if mode == "sparse":
        return set(body1.split()) == set(body2.split())
    return body1 == body2


def run_deduplication(origin_slides: list[Slide], candidate_slides: list[Slide], mode: str) -> int:
    """Run deduplication logic and return the count of duplicates."""
    duplicate_count = 0
    for o_slide in origin_slides:
        for c_slide in candidate_slides:
            if is_duplicate(o_slide.body, c_slide.body, mode=mode):
                duplicate_count += 1
                break
    return duplicate_count


def print_comparison_results(origin_name: str, origin_count: int, candidate_name: str, candidate_count: int, duplicate_count: int):
    """Print the results of the slide comparison."""
    print(f"Loaded {origin_count:4} slides from origin: {origin_name}")
    print(f"Loaded {candidate_count:4} slides from candidate: {candidate_name}")
    print("\n📊 Comparison Results:")
    print(f"  Duplicates found: {duplicate_count:4}")


def read_md_slides(file_path: Path) -> list[Slide]:
    """Read a markdown file and split it into Slide objects."""
    if not file_path.exists():
        print(f"Error: File not found at {file_path}")
        return []

    content = file_path.read_text(encoding="utf-8")
    raw_slides = content.split("\n\n---\n\n")

    slides = []
    for raw in raw_slides:
        raw = raw.strip()
        if not raw:
            continue

        match = re.match(r"## Slide (\d+)\n*(.*)", raw, re.DOTALL)
        if match:
            num = int(match.group(1))
            body = match.group(2).strip()
            slides.append(Slide(num=num, body=body))
        else:
            slides.append(Slide(num=len(slides) + 1, body=raw))

    return slides


def _header_level(header: str) -> int:
    """Return the depth of a markdown header (number of leading #)."""
    m = re.match(r'^(#+)', header)
    return len(m.group(1)) if m else 0


def _parse_sections(content: str) -> list[tuple[int, str, str]]:
    """
    Parse markdown content into sections, skipping headers inside fenced code blocks.
    Returns [(line_num, header_line, body_text), ...].
    """
    sections: list[tuple[int, str, str]] = []
    in_code_block = False
    current_header: str | None = None
    current_line_num = 0
    body_lines: list[str] = []

    for line_num, line in enumerate(content.splitlines(keepends=True), 1):
        if line.strip().startswith("```"):
            in_code_block = not in_code_block
            if current_header is not None:
                body_lines.append(line)
            continue

        if not in_code_block and re.match(r"^#{1,6}\s+", line):
            if current_header is not None:
                sections.append((current_line_num, current_header, "".join(body_lines).strip()))
            current_header = line.rstrip()
            current_line_num = line_num
            body_lines = []
        else:
            if current_header is not None:
                body_lines.append(line)

    if current_header is not None:
        sections.append((current_line_num, current_header, "".join(body_lines).strip()))

    return sections


def check_heading_hierarchy(file_path) -> list[dict]:
    """Check markdown file for heading hierarchy violations."""
    violations = []
    content = Path(file_path).read_text(encoding="utf-8")

    prev_level = 0
    for line_num, header_line, _ in _parse_sections(content):
        current_level = _header_level(header_line)
        heading_text = re.match(r"^#{1,6}\s+(.+)", header_line).group(1).strip()
        if current_level > prev_level + 1:
            violations.append({
                "line": line_num,
                "type": "level_skip",
                "prev_level": prev_level,
                "current_level": current_level,
                "text": heading_text,
                "content": header_line,
            })
        prev_level = current_level

    in_code_block = False
    for line_num, line in enumerate(content.splitlines(), 1):
        if line.strip().startswith("```"):
            in_code_block = not in_code_block
            continue
        if not in_code_block and re.match(r"^(#{1,6})([^\s#])", line):
            violations.append({"line": line_num, "type": "no_space", "content": line.strip()})

    return violations


def read_md_nodes(file_path: Path) -> list[DocumentNode]:
    """Read a markdown file and return a list of DocumentNode, one per header section."""
    if not file_path.exists():
        print(f"Error: File not found at {file_path}")
        return []

    content = file_path.read_text(encoding="utf-8")
    # Parse sections on original content so line numbers stay correct
    sections = _parse_sections(content)
    total_lines = len(content.splitlines())
    nodes = []
    for i, (line_num, header_line, body) in enumerate(sections):
        line_end = sections[i + 1][0] - 1 if i + 1 < len(sections) else total_lines
        # Strip code blocks, LaTeX, and URLs from body text only
        clean_body = strip_urls(strip_latex(strip_code_blocks(body)))
        nodes.append(DocumentNode(
            header=header_line, body=clean_body, source=file_path,
            line_start=line_num, line_end=line_end,
        ))

    stack: list[tuple[int, DocumentNode]] = []
    for node in nodes:
        current_level = _header_level(node.header)
        while stack and stack[-1][0] >= current_level:
            stack.pop()
        if stack:
            node.parent = stack[-1][1]
        stack.append((current_level, node))

    return nodes


def read_srt_nodes(file_path: Path) -> list[DocumentNode]:
    """Parse an SRT file and return a list of DocumentNode, one per subtitle entry."""
    if not file_path.exists():
        print(f"Error: File not found at {file_path}")
        return []

    nodes = []
    content = file_path.read_text(encoding="utf-8")
    all_lines = content.splitlines()
    # Walk through lines to find SRT blocks with their positions
    i = 0
    while i < len(all_lines):
        # Skip blank lines
        if not all_lines[i].strip():
            i += 1
            continue
        block_start = i + 1  # 1-based
        # Collect contiguous non-blank lines as one SRT block
        block_lines = []
        while i < len(all_lines) and all_lines[i].strip():
            block_lines.append(all_lines[i].strip())
            i += 1
        block_end = i  # 1-based (last non-blank line)
        if len(block_lines) < 3:
            continue
        # block_lines[0] = index, [1] = timestamp, [2:] = text
        timestamp = block_lines[1]
        body = " ".join(block_lines[2:])
        if not body:
            continue
        nodes.append(DocumentNode(
            header=timestamp, body=body, source=file_path,
            line_start=block_start, line_end=block_end,
        ))
    return nodes


def squash_srt(file_path: Path, window: int = _MERGE_MAX_TOKENS) -> list[DocumentNode]:
    """Merge fine-grained SRT nodes into larger chunks of up to _MERGE_MAX_TOKENS tokens.

    Iterates over nodes from read_srt_nodes, accumulating text into a buffer.
    When adding the next node would exceed the token limit, flushes the buffer as
    a new DocumentNode and seeds the next buffer with the last _OVERLAP_BLOCKS nodes
    for context overlap.
    """
    enc = tiktoken.get_encoding(_TIKTOKEN_ENCODING)
    raw_nodes = read_srt_nodes(file_path)
    if not raw_nodes:
        return []

    merged: list[DocumentNode] = []
    buffer: list[DocumentNode] = []
    buffer_tokens = 0

    def _flush(buf: list[DocumentNode]) -> DocumentNode:
        start = buf[0].header.split(' --> ')[0]
        end = buf[-1].header.split(' --> ')[-1]
        header = f"{start} --> {end}"
        body = " ".join(n.body for n in buf)
        return DocumentNode(
            header=header, body=body, source=file_path,
            line_start=buf[0].line_start, line_end=buf[-1].line_end,
        )

    for node in raw_nodes:
        node_tokens = len(enc.encode(node.body))
        if buffer and buffer_tokens + node_tokens > window:
            merged.append(_flush(buffer))
            buffer = buffer[-_OVERLAP_BLOCKS:]
            buffer_tokens = sum(len(enc.encode(n.body)) for n in buffer)
        buffer.append(node)
        buffer_tokens += node_tokens

    if buffer:
        merged.append(_flush(buffer))

    logger.info(
        "squash_srt: %d raw blocks → %d merged blocks (%s)",
        len(raw_nodes), len(merged), file_path.name,
    )
    return merged


class _IlocIndexer:
    def __init__(self, nodes: list[DocumentNode]):
        self._nodes = nodes

    def __getitem__(self, index: int) -> DocumentNode:
        return self._nodes[index]


class DocumentIndex:
    def __init__(self, nodes: list[DocumentNode]):
        self._nodes = nodes
        self._vectorizer = TfidfVectorizer()
        corpus = [f"{node.header}\n{node.body}" for node in nodes]
        self._matrix = self._vectorizer.fit_transform(corpus)

    @property
    def iloc(self) -> _IlocIndexer:
        return _IlocIndexer(self._nodes)

    def __getitem__(self, node_name: str) -> DocumentNode:
        for node in self._nodes:
            if node.node_name == node_name:
                return node
        raise KeyError(f"No node with node_name={node_name!r}")

    def describe(self) -> str:
        num_blocks = len(self._nodes)
        num_chapters = sum(1 for n in self._nodes if n.parent is None)
        chars = [len(n.body) for n in self._nodes if n.body]
        num_chars = sum(chars)
        avg_chars = num_chars // len(chars) if chars else 0
        return (
            f"blocks: {num_blocks}, chapters: {num_chapters}, "
            f"chars: {num_chars}, avg chars/block: {avg_chars}"
        )

    def get_childs(self, node_name: str) -> list[DocumentNode]:
        return [node for node in self._nodes if node.parent is not None and node.parent.node_name == node_name]

    def to_md(self) -> str:
        """Re-create plaintext markdown content from nodes."""
        return "\n\n".join(
            f"{node.header}\n{node.body}" for node in self._nodes
        )

    def search(self, query: str, top_k: int = 5) -> list[tuple[float, DocumentNode]]:
        """Return top_k results ranked by TF-IDF cosine similarity."""
        query_vec = self._vectorizer.transform([query])
        scores = (self._matrix @ query_vec.T).toarray().flatten()
        top_indices = scores.argsort()[::-1][:top_k]
        return [(float(scores[i]), self._nodes[i]) for i in top_indices if scores[i] > 0]

    @classmethod
    def from_md_file(cls, file_path: str | Path) -> "DocumentIndex":
        """Factory: build a DocumentIndex from a markdown file."""
        file_path = Path(file_path).expanduser()
        nodes = read_md_nodes(file_path)
        if not nodes:
            raise ValueError(f"No nodes parsed from {file_path}")
        return cls(nodes)

    @classmethod
    def from_srt_file(cls, file_path: Path, window: int = _MERGE_MAX_TOKENS) -> "DocumentIndex":
        """Factory: build a DocumentIndex from an SRT subtitles file.

        Fine-grained SRT entries are merged into larger chunks (up to `window` tokens)
        with a 3-entry overlap between consecutive chunks.
        """
        nodes = squash_srt(file_path, window=window)
        if not nodes:
            raise ValueError(f"No nodes parsed from {file_path}")
        return cls(nodes)

    @classmethod
    def from_jsonl(
        cls,
        file_path: str | Path,
        mapping: dict[str, str] | None = None,
    ) -> "DocumentIndex":
        """Factory: build a DocumentIndex from a JSONL file.

        mapping maps DocumentNode fields to JSONL keys, e.g.
        {"header": "title", "body": "url", "source": "source"}.
        """
        import json
        if mapping is None:
            mapping = {"header": "title", "body": "url", "source": "source"}
        file_path = Path(file_path).expanduser()
        nodes = []
        for line in file_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            header = record[mapping["header"]]
            body = record[mapping["body"]]
            source = Path(record[mapping["source"]])
            nodes.append(DocumentNode(header=header, body=body, source=source))
        if not nodes:
            raise ValueError(f"No records parsed from {file_path}")
        return cls(nodes)

    @classmethod
    def from_dir(cls, dir_path: str | Path, ext: str | None = None) -> "DocumentIndex":
        """Factory: build a DocumentIndex from .md and/or .srt files in a directory tree.

        ext: restrict to 'md', 'srt', or None (both).
        """
        dir_path = Path(dir_path).expanduser()
        nodes = []
        if ext in (None, "md"):
            for md_file in sorted(dir_path.rglob("*.md")):
                nodes.extend(read_md_nodes(md_file))
        if ext in (None, "srt"):
            for srt_file in sorted(dir_path.rglob("*.srt")):
                nodes.extend(squash_srt(srt_file))
        if not nodes:
            raise ValueError(f"No nodes parsed from any .{ext or 'md/.srt'} file in {dir_path}")
        return cls(nodes)


def count_tokens_in_file(file_path, encoding_name="cl100k_base"):
    """Count tokens in a file using tiktoken."""
    try:
        enc = tiktoken.get_encoding(encoding_name)
        with open(file_path, "r", encoding="utf-8") as f:
            text = f.read()
        return len(enc.encode(text))
    except (OSError, UnicodeDecodeError) as e:
        print(f"  ⚠️ Error processing {file_path.name}: {e}")
        return None
