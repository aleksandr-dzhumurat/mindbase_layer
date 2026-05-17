# Skill Design: audio-summarization

## Overview

This document specifies the design for an `audio-summarization` Claude skill that automates the full pipeline from raw audio to a searchable, queryable knowledge base.

**Category**: Workflow Automation (Category 2)
**Pattern**: Sequential workflow orchestration (Pattern 1)

---

## Use Cases

### Use Case 1: Transcribe and index a lecture recording

**Trigger**: "Summarize this audio", "transcribe my recording", "index this mp3", "what does this lecture say about X"

**Steps**:
1. Split large audio into manageable chunks (if > 300s)
2. Transcribe chunks to `.srt` via local Whisper model
3. Merge fine-grained SRT blocks into larger semantic chunks (up to 8100 tokens, 3-block overlap)
4. Build TF-IDF index over merged blocks
5. Answer user query against the index

**Result**: User gets ranked text excerpts with timestamps.

### Use Case 2: Summarize audio files via Gemini

**Trigger**: "Summarize audio with Gemini", "upload and summarize mp3", "get AI summary of recording"

**Steps**:
1. Upload `.mp3` to Gemini Files API
2. Call `gemini-2.5-flash` with a summarization prompt
3. Save output `.txt` to `data/recognized_speech/`

**Result**: Concise text summary saved to disk.

### Use Case 3: Query an existing SRT transcript

**Trigger**: "search my srt file", "find segments about X in srt", "query transcript"

**Steps**:
1. Load existing `.srt` file
2. Run `squash_srt` to merge blocks
3. Query index and return top-k results

---

## Skill Folder Structure

```
audio-summarization/
├── SKILL.md                  # Required - main skill instructions
├── scripts/                  # Thin CLI wrappers (already in repo)
│   ├── audio_splitter.py
│   ├── whisper_to_srt.py
│   ├── audio_summarizer.py
│   └── retrieval.py
└── references/
    └── pipeline_overview.md  # Architecture notes for Claude
```

---

## SKILL.md

```markdown
---
name: audio-summarization
description: >
  Full pipeline for processing audio recordings into searchable text.
  Use when the user wants to transcribe, summarize, index, or query audio
  files (.mp3, .wav, .m4a) or existing subtitle files (.srt).
  Trigger phrases: "summarize audio", "transcribe recording", "index mp3",
  "what does the lecture say about", "search transcript", "process audio file".
compatibility: Requires Python environment with uv. Local Whisper transcription
  uses mlx-whisper (Apple Silicon). Gemini summarization requires GOOGLE_API_KEY.
metadata:
  author: home-brain
  version: 1.0.0
---

# audio-summarization

End-to-end pipeline for turning audio recordings into queryable knowledge.

---

## Workflow

### Step 1: Determine input type

| Input          | Next step         |
|----------------|-------------------|
| `.mp3` / audio | Step 2 (split)    |
| `.srt` file    | Step 4 (index)    |
| Query only     | Step 4 (index)    |

### Step 2: Split large audio (optional, skip for files < 5 min)

```bash
uv run python scripts/audio_splitter.py --audio-file PATH [--min-interval 300] [--max-interval 500]
```

Output: chunked `.mp3` files in the same directory.

### Step 3: Transcribe audio to SRT

```bash
uv run python scripts/whisper_to_srt.py --audio-file PATH [--language en]
```

Output: `.srt` file at same path as input audio.

### Step 4: Build index and query

```bash
uv run python scripts/retrieval.py --path PATH_TO_SRT_OR_MD --query "your question" --top-k 3
```

- `--path` accepts `.srt`, `.md`, or a directory of `.md` files
- `--top-k` controls number of results returned (default: 3)

### Step 5 (alternative): Gemini summarization

Use when the user wants a narrative summary rather than search results.

```bash
uv run python scripts/audio_summarizer.py --prefix FILENAME_PREFIX [--limit 1]
```

Audio files are read from `data/audio/`. Summaries are saved to `data/recognized_speech/`.

---

## Examples

### Example 1: Transcribe a lecture and find relevant segments

User: "Transcribe lecture.mp3 and find what it says about attention mechanisms"

Actions:
1. Run `whisper_to_srt.py --audio-file lecture.mp3`
2. Run `retrieval.py --path lecture.srt --query "attention mechanisms" --top-k 3`

Result: Top 3 timestamp-tagged segments about attention mechanisms.

### Example 2: Query an existing SRT directly

User: "Search LLM_Architectures_week_4.srt for mentions of RNN"

Actions:
1. Run `retrieval.py --path LLM_Architectures_week_4.srt --query "rnn" --top-k 3`

Result: Ranked excerpts with merged timeframes (e.g. `00:12:05,000 --> 00:18:42,000`).

### Example 3: Gemini summary

User: "Give me a Gemini summary of today_standup.mp3"

Actions:
1. Confirm file is in `data/audio/`
2. Run `audio_summarizer.py --prefix today_standup --limit 1`

Result: `data/recognized_speech/today_standup.txt` with a concise summary.

---

## Success Criteria

### Triggering
- Triggers on: "transcribe audio", "summarize mp3", "index my srt", "search transcript"
- Does NOT trigger on: general text search, PDF processing, markdown questions

### Functional
- `whisper_to_srt.py` produces a valid `.srt` within 2x audio duration
- `retrieval.py` returns top-k results with correct merged timeframe headers
- `audio_summarizer.py` saves `.txt` to `data/recognized_speech/`

### Performance
- Without skill: user must remember 3 separate scripts and correct arg names
- With skill: single conversation turn runs the right script with the right args

---

## Key Implementation Notes

| Concern | Detail |
|---|---|
| Chunking | `squash_srt` greedy-merges SRT nodes up to `window` tokens (default 8100) |
| Overlap | Last 3 SRT nodes are seeded into the next buffer for context continuity |
| Token counting | Uses tiktoken `cl100k_base` encoding |
| Merged header | Format: `earliest_start --> latest_end` extracted by splitting on ` --> ` |
| Gemini upload | `GeminiAdapter.audio_to_text_pipeline()` in `src/llm_adapter.py` |
| Local transcription | `transcribe()` in `src/utils/audio.py`, uses `mlx-community/whisper-medium` |

---

## uv Virtual Environment Nuances

This section documents the correct patterns for creating and using virtual environments with `uv` in skill runners.

---

### Creating the venv and installing dependencies

```bash
VENV="/tmp/mindbase-copilot-venv"
uv venv "$VENV" -q && VIRTUAL_ENV="$VENV" uv pip install -r "$SKILL_DIR/requirements.txt" -q
```

Key: use the `VIRTUAL_ENV` environment variable to target a specific venv — `uv pip install` respects it automatically. Do **not** use `--python "$VENV/bin/python"`, which causes exit code 2:

```
error: a value is required for '[PATH]' but none was supplied
```

---

### Running Python inside the venv

```bash
VIRTUAL_ENV="$VENV" uv run python - <<'EOF'
# your Python code here
EOF
```

Set `VIRTUAL_ENV` here too — this is consistent with the install step and more reliable than `uv run --python "$VENV"`.

---

### Full two-step pattern

```bash
# Step 0 — create env
SKILL_DIR="$HOME/.claude/skills/mindbase_copilot"
VENV="/tmp/mindbase-copilot-venv"
uv venv "$VENV" -q && VIRTUAL_ENV="$VENV" uv pip install -r "$SKILL_DIR/requirements.txt" -q

# Step 1 — run
PYTHONPATH="$SKILL_DIR" FILE_HOME="$FILE_HOME" VIRTUAL_ENV="$VENV" uv run python - <<'EOF'
import os
from pathlib import Path
from mindbase_layer import tools
# ...
EOF

# Teardown (optional)
rm -rf "$VENV"
```

---

### Alternative: no venv management with `uv run --no-project`

For ephemeral use, skip venv creation entirely:

```bash
PYTHONPATH="$SKILL_DIR" uv run --no-project --with-requirements "$SKILL_DIR/requirements.txt" python - <<'EOF'
# your Python code here
EOF
```

uv resolves and caches dependencies automatically. No `uv venv`, no teardown needed. First run is slightly slower; subsequent runs use uv's cache.

---

## Distribution

1. Place `audio-summarization/` folder in the Claude Code skills directory
2. Or zip and upload via Claude.ai > Settings > Capabilities > Skills
3. The skill folder must **not** contain a `README.md` (docs go in `references/`)
