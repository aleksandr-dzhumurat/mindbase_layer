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


REC2DOC_FRAME_ANALYSIS_PROMPT =  (
    "You are analyzing a SINGLE frame from a screen recording so it can later be turned "
    "into documentation. Describe only what is visible in this one frame.\n\n"
    "Output exactly these four labelled lines:\n"
    "SCREEN: which application or surface is shown (IDE, terminal, browser + which site, "
    "notebook, dialog, settings page, ...). Name the specific app/page if identifiable.\n"
    "LITERALS: exact on-screen text that identifies state — window/page titles, file names, "
    "menu paths, button labels, URLs, config values, visible numbers. Quote verbatim.\n"
    "CODE: transcribe any code, command, SQL, JSON or YAML visible, verbatim, inside a "
    "fenced code block. If there is none, write 'none'.\n"
    "EVENT: one sentence on what is happening (editing a file, running a command, a dialog "
    "appeared, a chart/result rendered, an error is shown, ...).\n\n"
    "Rules:\n"
    "- Report only what you can actually see. If the frame is blurry, cropped or ambiguous, "
    "write 'UNVERIFIABLE' for that field and briefly say why.\n"
    "- Redact any visible secret, token, password or API key as <redacted>.\n"
    "- Do not guess intent or narrate beyond this frame."
)

