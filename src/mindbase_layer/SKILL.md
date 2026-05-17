---
name: mindbase-copilot-tools
description: >
  Personal project-management toolkit. Use when the user asks to find or
  search files, retrieve documents, convert PDFs to Markdown, transcribe
  or summarise videos, download YouTube content, or convert audio files.
license: MIT
allowed-tools: "Bash(*)"
metadata:
  version: 1.0.0
  category: personal-tools
  tags: [retrieval, file-search, pdf, video, youtube, markdown]
---

# Mindbase Copilot

Project management scripts installed at `~/.claude/skills/mindbase_copilot/`.

---

## Prerequisites

The following system binaries must be present on `$PATH`:

| Binary | Required by |
|--------|-------------|
| `uv` | all tools |
| `ffmpeg` | `generate_subtitles`, `m4a_to_mp3`, `summarize_video` |
| `whisper` / `whisper-ctranslate2` | `generate_subtitles`, `summarize_video` |
| `yt-dlp` | `youtube_download` |

The following environment variable must be set for agent-based tools (`summarize_video`, `search_file_content`):

| Variable | Required by |
|----------|-------------|
| `NEBIUS_API_KEY` | `summarize_video`, `search_file_content` |

Verify before running:
```bash
echo "NEBIUS_API_KEY is ${NEBIUS_API_KEY:+set}${NEBIUS_API_KEY:-NOT SET}"
```

---

## Step 0 — Create environment

```bash
SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd)"
[ -z "$SKILL_DIR" ] || [ ! -f "$SKILL_DIR/requirements.txt" ] && SKILL_DIR="$HOME/.claude/skills/mindbase_copilot"
VENV="/tmp/mindbase-copilot-venv"
uv venv "$VENV" -q && VIRTUAL_ENV="$VENV" uv pip install -r "$SKILL_DIR/requirements.txt" -q
```

---

## Step 1 — Run tools directly

```bash
SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd)"
[ -z "$SKILL_DIR" ] || [ ! -f "$SKILL_DIR/requirements.txt" ] && SKILL_DIR="$HOME/.claude/skills/mindbase_copilot"
VENV="/tmp/mindbase-copilot-venv"
# FILE_HOME: directory where the user's files live (Downloads, Documents, etc.)
# Override if the process runs as a different user than the file owner.
if [ -d "/Users" ]; then
    # macOS: find the actual user even when running as root
    _u=$(ls /Users | grep -v Shared | head -1)
    FILE_HOME="/Users/$_u"
else
    FILE_HOME="${FILE_HOME:-$HOME}"
fi
PYTHONPATH="$SKILL_DIR" FILE_HOME="$FILE_HOME" VIRTUAL_ENV="$VENV" uv run python - <<'EOF'
import asyncio
import os
from pathlib import Path
from mindbase_layer import tools

home_dir = Path(os.environ.get("FILE_HOME", str(Path.home())))

# PDF → Markdown conversion
print(tools.pdf_to_md("/path/to/file.pdf"))

# Subtitle generation from video (produces a .srt file next to the video)
print(tools.generate_subtitles("/path/to/video.mp4", language="en"))

# YouTube download — video or audio (async)
print(asyncio.run(tools.youtube_download("https://youtu.be/...", "audio", home_dir / "Downloads/YouTube")))

# Audio conversion (m4a → mp3)
print(tools.m4a_to_mp3("/path/to/file.m4a"))

# Remove a file or directory
print(tools.remove_file("/path/to/artifact"))
EOF
```

---

## Teardown (optional)

Remove the venv to avoid stale environments after a session:

```bash
rm -rf /tmp/mindbase-copilot-venv
```

---

## Step 2 — Run `summarize_video` (requires agent)

`summarize_video` and `search_file_content` need a live `pydantic-ai` agent. Build the minimal agent inline:

```bash
SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd)"
[ -z "$SKILL_DIR" ] || [ ! -f "$SKILL_DIR/requirements.txt" ] && SKILL_DIR="$HOME/.claude/skills/mindbase_copilot"
VENV="/tmp/mindbase-copilot-venv"
PYTHONPATH="$SKILL_DIR" VIRTUAL_ENV="$VENV" uv run python - <<'EOF'
import asyncio
import os
from dataclasses import dataclass
from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.nebius import NebiusProvider
from mindbase_layer import tools

_model = OpenAIChatModel(
    'Qwen/Qwen3-32B',
    provider=NebiusProvider(api_key=os.environ['NEBIUS_API_KEY'])
)

@dataclass
class SummarizeDependencies:
    text: str
    language: str

_summarizer_agent = Agent(
    _model,
    output_type=str,
)

@_summarizer_agent.system_prompt
def _prompt(ctx):
    return f"Respond in: {ctx.deps.language}\n\nTranscript:\n{ctx.deps.text}"

async def main():
    result = await tools.summarize_video(
        "/path/to/video.mp4",
        "en",
        _summarizer_agent,
        SummarizeDependencies,
        None,  # usage — pass None when not tracking tokens
    )
    print(result)  # absolute path to _summary.md

asyncio.run(main())
EOF
```

---

## Tools reference

| Function | Signature | Description |
|----------|-----------|-------------|
| `pdf_to_md` | `(pdf_path)` → str | Convert a PDF to markdown via docling. Skips if output already exists. |
| `generate_subtitles` | `(video_path, language)` → str | Extract audio and transcribe to SRT. `language` is BCP-47 (e.g. `'en'`, `'ru'`). |
| `summarize_video` | `(video_path, spoken_language, summarize_agent, deps_cls, usage)` → str | **NOT CALLABLE DIRECTLY** — requires agent infrastructure. Returns absolute path to `_summary.md` file. Use `generate_subtitles` instead. |
| `youtube_download` | `(url, mode, youtube_dir)` → str | Download YouTube video or audio. `mode` is `'video'` (default) or `'audio'`. **Async.** |
| `m4a_to_mp3` | `(input_path)` → str | Convert m4a (or other audio) to mp3. |
| `search_file_content` | `(md_path, query, retrieval_agent, deps_cls, usage)` → str | **NOT CALLABLE DIRECTLY** — requires agent infrastructure. |
| `remove_file` | `(file_path)` → str | Delete a file (`Path.unlink`) or directory (`shutil.rmtree`). |
