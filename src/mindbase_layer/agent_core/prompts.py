from pathlib import Path

_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"


def _load_prompt(name: str) -> str:
    return (_PROMPTS_DIR / name).read_text(encoding="utf-8")


RETRIEVAL_AGENT_INSTRUCTIONS = (
    'You are a document retrieval specialist. '
    'Use the query_documents tool to find relevant content in indexed markdown or .srt files. '
    'If the search returns no results, rephrase the query using synonyms or simpler terms and call search_documents again (at most 2 retries). '
    'Return the most relevant excerpts you found, or clearly state that nothing was found.'
)

SUMMARIZE_INSTRUCTIONS = _load_prompt("video_summarizer.md")

PROJECT_MANAGER_INSTRUCTIONS = _load_prompt("project_manager.md")

TRANSLATION_INSTRUCTIONS = _load_prompt("translation.md")


def home_dir_prompt(home_dir: Path) -> str:
    return f"The user's home directory is: {home_dir}. Use it to resolve file paths like Downloads, Documents, etc."
