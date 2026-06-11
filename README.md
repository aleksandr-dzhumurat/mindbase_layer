# Mindbase layer

Token-efficient retrieval layer for agentic pipeline.

## Installation

[![mindbase demo](http://img.youtube.com/vi/uupB2A7dG5k/0.jpg)](http://www.youtube.com/watch?v=uupB2A7dG5k "mindbase demo")


### CLI usage

Install `mindbase` as a standalone console command:

```bash
make cli-install
```

This will:
1. Copy the package and dependencies to `~/.local/share/mindbase/`
2. Create a Python venv and install all requirements there
3. Prompt for an API key and save it to `~/.local/share/mindbase/.env` (chmod 600):
   - First asks for `VERTEX_SA_KEY_FILE` — provide the **absolute path** to a Google service-account `.json` file, or press **Enter** to skip
   - If skipped, asks for `NEBIUS_API_KEY` (input masked with `*`)
   - Only one key is required; if `VERTEX_SA_KEY_FILE` is set, `NEBIUS_API_KEY` is not needed
4. Create a symlink at `~/.local/bin/mindbase`

If `~/.local/bin` is not on your `$PATH`, the installer will warn you and print the line to add to `~/.zshrc`.

**Start the REPL:**

```bash
mindbase
```


### As a Python package (from GitHub)

Install `mindbase_layer` into external project:

```bash
# latest main branch
uv add "mindbase-layer @ git+https://github.com/aleksandr-dzhumurat/automation_toolkit.git"

# pin to a specific tag
uv add "mindbase-layer @ git+https://github.com/aleksandr-dzhumurat/automation_toolkit.git@v0.1.0"

# with local Apple Silicon transcription (mlx-whisper)
uv add "mindbase-layer[whisper] @ git+https://github.com/aleksandr-dzhumurat/automation_toolkit.git"
```

Or add to your `pyproject.toml`:

```toml
dependencies = [
    "mindbase-layer @ git+https://github.com/aleksandr-dzhumurat/automation_toolkit.git@main",
]
```

Or to requirements.txt

```shell
mindbase-layer @ git+https://github.com/aleksandr-dzhumurat/automation_toolkit.git
```

### Local development

```bash
uv venv
source .venv/bin/activate
uv pip install -e ".[whisper]"
```

**Reset the API key:**

```bash
rm ~/.local/share/mindbase/.env
make cli-install
```

**Upgrade after code changes:**

```bash
make cli-install          # keeps the existing venv and .env
make cli-install-fresh    # also rebuilds the venv from scratch
```

---

## Agent usage

Run chat using

```shell
make chat
```

Dialog example


For now, one tool call is shown as an example — extracting an audio track from an .mp4 file

```shell
👨 You: LLM_Architectures_week_1.mp4
🤖 Agent:

The file path has been resolved to:
`/Users/adzhumurat/Downloads/LLM_Architectures_week_1.mp4`
```

Then the ffmpeg magic begins (I'll probably wrap it in a separate background process later)

```shell
🤖 Thinking... ⠴ Input #0, mov,mp4,m4a,3gp,3g2,mj2, from '/Users/adzhumurat/Downloads/LLM_Architectures_week_1.mp4':
  Metadata:
    major_brand     : isom
    minor_version   : 512
    compatible_brands: isomiso2avc1mp41
    encoder         : https://clipchamp.com
    comment         : Create videos with https://clipchamp.com/en/video-editor - free online video editor, video compressor, video converter.
  Duration: 02:30:40.03, start: 0.000000, bitrate: 743 kb/s

🤖 Thinking... ⠹ Done! Audio saved to: /Users/adzhumurat/Downloads/LLM_Architectures_week_1.mp3
```

And after completion the bot waits for the next instructions

```shell
🤖 Agent: The audio has been successfully extracted and saved to:
`/Users/adzhumurat/Downloads/LLM_Architectures_week_1.mp3`

Let me know if you need anything else!
```

Over the next week I'll add more tools for filesystem operations, plus a memory layer and observability (most likely langfuse)



## Tools

### Markdown Validation

Check markdown heading hierarchy:
```bash
python src/check_md_hierarchy.py docs/README.md
```

See `docs/md_checking_rules.md` for validation rules.

### Audio Processing

Requires `ffmpeg` (`brew install ffmpeg` on macOS).

**1. Extract audio from video:**
```bash
python scripts/extract_audio.py ~/Downloads/recording.mp4
```
Output: `~/Downloads/recording.mp3`

**2. Detect silence intervals:**
```bash
python scripts/silence_detector.py ~/Downloads/recording.mp3
```
Output: `~/Downloads/recording_silence.log`

**3. Split audio into 300-500s chunks at silence points:**
```bash
python scripts/audio_splitter.py ~/Downloads/recording.mp3
```
Output:
- `~/Downloads/recording_silence.split.log` - split points log
- `~/Downloads/recording/recording_chunk_01.mp3` - audio chunks
- `~/Downloads/recording/recording_chunk_02.mp3`
- ...

**4. Transcribe audio to text:**

Option A — Whisper (Apple Silicon, no API key required):
```bash
uv run python scripts/whisper_to_srt.py ~/Downloads/recording_chunk_01.mp3
```
Output: `~/Downloads/recording_chunk_01.srt`

Requires `mlx-whisper` and `tqdm`: `uv pip install mlx-whisper tqdm`

Option B — Google API:
```bash
python scripts/cloud_audio_summarizer.py --prefix recording_chunk --limit 10
```
Output: `data/recognized_speech/recording_chunk_01.txt`, ...

Requires `GOOGLE_API_KEY` env var.

**5. Merge transcribed text files:**
```bash
python scripts/text_merger.py --prefix recording_chunk
```
Output: `data/recognized_speech/recording_chunk_merged.txt`



## Services

### Chroma
Version endpoint: http://0.0.0.0:8000/api/v2/version

### Ollama Models
```bash
ollama pull granite3.3:8b
ollama pull nomic-embed-text
```

### Ollama Embeddings Generation
```bash
curl http://localhost:11434/api/embeddings -d '{
  "model": "nomic-embed-text",
  "prompt": "Hello, this is a test"
}'
```
