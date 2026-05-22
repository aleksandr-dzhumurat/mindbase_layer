# CLI Tool Design: `mindbase`

## Goal

Add a `--cli` scenario to `scripts/prepare_skill.py` that installs the toolkit
as a standalone console command on macOS. After installation the user runs:

```bash
mindbase "summarize /path/to/meeting.mp4"
```

---

## Directory layout

```
~/.local/share/mindbase/          # INSTALL_ROOT
├── mindbase_layer/               # Python package (copied from src/)
│   ├── __init__.py
│   ├── tools.py
│   ├── agent.py
│   ├── utils/
│   └── agent_core/
├── scripts/
│   └── chat.py                   # interactive REPL entry point
├── requirements.txt
├── venv/                         # uv venv, created at install time
├── history/                      # chat history jsonl files (DATA_DIR)
└── .env                          # NEBIUS_API_KEY (written on first run, chmod 600)

~/.local/bin/
└── mindbase -> ~/.local/share/mindbase/mindbase.sh  (symlink)
```

`~/.local/bin/` is on `$PATH` for most macOS shells configured by Homebrew or
`pyenv`. No `sudo` required.

---

## Installation flow (new `--cli` flag)

`python scripts/prepare_skill.py --cli` runs these steps in order:

1. **Stage** — same as today (copies source to `data/mindbase_layer/`)
2. **Deploy** — copies the staged package into `~/.local/share/mindbase/`
3. **Copy scripts** — copies `scripts/chat.py` into `~/.local/share/mindbase/scripts/`
4. **Venv** — runs `uv venv ~/.local/share/mindbase/venv -q` (skipped if venv exists and `--force-venv` not set)
5. **Deps** — runs `VIRTUAL_ENV=~/.local/share/mindbase/venv uv pip install -r requirements.txt -q`
6. **Script** — writes `mindbase.sh` into `~/.local/share/mindbase/`
7. **Link** — creates symlink `~/.local/bin/mindbase → ~/.local/share/mindbase/mindbase.sh`
8. **chmod** — makes `mindbase.sh` executable

Nothing writes outside `~/.local/`. The user's shell must have `~/.local/bin`
on `$PATH` (checked and warned if missing).

---

## `mindbase.sh` behaviour

```bash
#!/usr/bin/env bash
set -euo pipefail

INSTALL_ROOT="$HOME/.local/share/mindbase"
ENV_FILE="$INSTALL_ROOT/.env"

# ── First-run setup ──────────────────────────────────────────────────────────
if [ ! -f "$ENV_FILE" ]; then
    echo "First run — NEBIUS_API_KEY is required."
    printf "Enter NEBIUS_API_KEY (input hidden): "
    read -rs key
    echo
    echo "NEBIUS_API_KEY=$key" > "$ENV_FILE"
    chmod 600 "$ENV_FILE"
    echo "Key saved to: $ENV_FILE"
    echo "To reset it, delete that file and run mindbase again."
    echo
fi

# ── Load env ─────────────────────────────────────────────────────────────────
set -a; source "$ENV_FILE"; set +a

# ── Run interactive REPL (mirrors `make chat`) ───────────────────────────────
DATA_DIR="$INSTALL_ROOT/history"
mkdir -p "$DATA_DIR"

DATA_DIR="$DATA_DIR" \
PYTHONPATH="$INSTALL_ROOT" \
VIRTUAL_ENV="$INSTALL_ROOT/venv" \
uv run python "$INSTALL_ROOT/scripts/chat.py"
```

Key decisions:
- `read -rs` hides the key while typing; the trailing `echo` moves to a new line.
- After saving, the script prints the exact `.env` path so the user knows where
  to find or delete it.
- `.env` lives inside `INSTALL_ROOT`, not in the project repo — keeps secrets
  away from version control.
- `chmod 600` on first write so only the owner can read the key.
- `set -a / source / set +a` exports every variable from `.env` into the
  child process without a `dotenv` dependency.
- Interactive mode runs `scripts/chat.py` — the same REPL as `make chat`,
  with `DATA_DIR` pointing to a history folder inside `INSTALL_ROOT`.
- The script is self-contained: no dependency on the original repo path after
  installation.

---

## Re-running / upgrading

Running `prepare_skill.py --cli` again:
- Overwrites the package files in `INSTALL_ROOT` (same as `shutil.copytree` with
  `dirs_exist_ok=True`).
- Recreates the venv only if `--force` is passed; otherwise skips if
  `venv/` already exists (fast re-deploy).
- Never touches `.env` — the key persists across upgrades.

To reset the key the user deletes `.env` manually:

```bash
rm ~/.local/share/mindbase/.env
mindbase   # prompts again on next run
```

---

## Changes to `scripts/prepare_skill.py`

Add one new function and one CLI flag:

| Addition | Detail |
|---|---|
| `cli_install(stage_dir, install_root, bin_dir)` | Steps 2–7 above |
| `--cli` flag | Runs `stage()` then `cli_install()` |
| `--force-venv` flag | Deletes and recreates the venv even if it exists |

Existing `--install` (Claude skill) behaviour is unchanged.

---

## PATH check

At the end of `cli_install()`, warn if `~/.local/bin` is not on `$PATH`:

```
mindbase installed at ~/.local/bin/mindbase
WARNING: ~/.local/bin is not on your PATH.
Add this line to ~/.zshrc:
    export PATH="$HOME/.local/bin:$PATH"
Then run: source ~/.zshrc
```

---

## Decisions log

| Question | Decision |
|---|---|
| Input mode | Interactive REPL (`scripts/chat.py`), same as `make chat` |
| `.env` location | `~/.local/share/mindbase/.env` |
| Key masking | Hidden (`read -rs`); path printed after save as a tip |
