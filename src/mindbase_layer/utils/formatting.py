import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mindbase_layer.retrieve_md import DocumentNode

_BOLD = "\033[1m"
_YELLOW = "\033[33m"
_RESET = "\033[0m"
_CONTEXT = 40  # chars around the match


def highlight_snippet(body: str, query: str) -> str:
    """Return a snippet of body with query terms highlighted, centred on the first match."""
    terms = [re.escape(t) for t in query.split() if t]
    pattern = re.compile("|".join(terms), re.IGNORECASE)

    flat = body.replace("\n", " ")
    m = pattern.search(flat)
    if not m:
        return flat[:_CONTEXT * 2]

    start = max(0, m.start() - _CONTEXT)
    end = min(len(flat), m.end() + _CONTEXT)
    snippet = flat[start:end]

    highlighted = pattern.sub(
        lambda hit: f"{_BOLD}{_YELLOW}{hit.group()}{_RESET}", snippet
    )
    prefix = "..." if start > 0 else ""
    suffix = "..." if end < len(flat) else ""
    return prefix + highlighted + suffix


def print_search_results(results: list[tuple[float, "DocumentNode"]], query: str) -> None:
    """Print ranked search results with highlighted snippets."""
    for rank, (score, node) in enumerate(results, 1):
        source_name = node.source.name if node.source else "unknown"
        print(f"{rank}. [{score:.4f}] {node.header}  ({source_name})")
        if node.body:
            snippet = highlight_snippet(node.body, query)
            print(f"   {snippet}")
        print()
