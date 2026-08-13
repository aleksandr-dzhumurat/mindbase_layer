"""
Install the mindbase CLI and desktop app to ~/.local/bin/.

Usage:
    python scripts/prepare_cli.py              # install (reuses existing venv)
    python scripts/prepare_cli.py --force-venv # rebuild venv from scratch

Creates three commands:
    mindbase      — desktop app (pywebview)
    mindbase-cli  — terminal REPL
    mindbase-tool — non-interactive CLI (summarize/transcribe/translate)
"""

import itertools
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT_DIR = Path(__file__).parent.parent
SRC_DIR = ROOT_DIR / "src" / "mindbase_layer"
INSTALL_ROOT = Path.home() / ".local" / "share" / "mindbase"
BIN_DIR = Path.home() / ".local" / "bin"

MINDBASE_CLI_SH = """\
#!/usr/bin/env bash
set -euo pipefail

INSTALL_ROOT="$HOME/.local/share/mindbase"
ENV_FILE="$INSTALL_ROOT/.env"

if [ ! -f "$ENV_FILE" ]; then
    echo "ERROR: $ENV_FILE not found. Re-run installation: make cli-install" >&2
    exit 1
fi
set -a; source "$ENV_FILE"; set +a

DATA_DIR="$INSTALL_ROOT/history"
mkdir -p "$DATA_DIR"

echo "Starting mindbase-cli, please wait..."

DATA_DIR="$DATA_DIR" \\
PYTHONPATH="$INSTALL_ROOT" \\
"$INSTALL_ROOT/venv/bin/python" "$INSTALL_ROOT/scripts/chat.py"
"""

MINDBASE_SH = """\
#!/usr/bin/env bash
set -euo pipefail

INSTALL_ROOT="$HOME/.local/share/mindbase"
ENV_FILE="$INSTALL_ROOT/.env"

if [ ! -f "$ENV_FILE" ]; then
    echo "ERROR: $ENV_FILE not found. Re-run installation: make cli-install" >&2
    exit 1
fi
set -a; source "$ENV_FILE"; set +a

DATA_DIR="$INSTALL_ROOT/history"
mkdir -p "$DATA_DIR"

echo "Log file: $INSTALL_ROOT/workflow.log"
echo "Run 'make follow' (from the repo) to tail it."

DATA_DIR="$DATA_DIR" \\
PYTHONPATH="$INSTALL_ROOT" \\
"$INSTALL_ROOT/venv/bin/python" "$INSTALL_ROOT/src/mindbase_app.py"
"""

MINDBASE_TOOL_SH = """\
#!/usr/bin/env bash
set -euo pipefail

INSTALL_ROOT="$HOME/.local/share/mindbase"
ENV_FILE="$INSTALL_ROOT/.env"

if [ ! -f "$ENV_FILE" ]; then
    echo "ERROR: $ENV_FILE not found. Re-run installation: make cli-install" >&2
    exit 1
fi
set -a; source "$ENV_FILE"; set +a

PYTHONPATH="$INSTALL_ROOT" \\
"$INSTALL_ROOT/venv/bin/python" "$INSTALL_ROOT/scripts/mindbase_tool.py" "$@"
"""


def _run_with_spinner(label: str, cmd: list[str], **kwargs) -> None:
    """Run a subprocess while showing an ASCII spinner."""
    frames = itertools.cycle(["|", "/", "-", "\\"])
    done = threading.Event()

    def _spin() -> None:
        while not done.is_set():
            sys.stdout.write(f"\r{label} {next(frames)}")
            sys.stdout.flush()
            time.sleep(0.1)

    t = threading.Thread(target=_spin, daemon=True)
    t.start()
    try:
        subprocess.run(cmd, check=True, **kwargs)
    finally:
        done.set()
        t.join()
        sys.stdout.write(f"\r{label} done\n")
        sys.stdout.flush()


def _read_masked(prompt: str) -> str:
    """Read a password from stdin, echoing '*' for each character typed."""
    import termios
    import tty

    sys.stdout.write(prompt)
    sys.stdout.flush()
    chars: list[str] = []
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        while True:
            ch = sys.stdin.read(1)
            if ch in ("\r", "\n"):
                break
            if ch in ("\x7f", "\x08"):
                if chars:
                    chars.pop()
                    sys.stdout.write("\b \b")
                    sys.stdout.flush()
            elif ch == "\x03":
                raise KeyboardInterrupt
            else:
                chars.append(ch)
                sys.stdout.write("*")
                sys.stdout.flush()
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
    sys.stdout.write("\n")
    return "".join(chars)


def copy_sources() -> None:
    """Copy mindbase_layer package and support files into the install directory."""
    INSTALL_ROOT.mkdir(parents=True, exist_ok=True)

    # SKILL.md
    shutil.copy2(SRC_DIR / "SKILL.md", INSTALL_ROOT / "SKILL.md")
    print(f"Copied SKILL.md → {INSTALL_ROOT / 'SKILL.md'}")

    # mindbase_layer/ package
    pkg_dst = INSTALL_ROOT / "mindbase_layer"
    if pkg_dst.exists():
        shutil.rmtree(pkg_dst)
    pkg_dst.mkdir()
    for src_file in sorted(SRC_DIR.glob("*.py")):
        shutil.copy2(src_file, pkg_dst / src_file.name)
        print(f"Copied {src_file.name} → {pkg_dst / src_file.name}")
    for sub in ("utils", "agent_core", "adapters", "prompts"):
        src_sub = SRC_DIR / sub
        if src_sub.is_dir():
            dest_sub = pkg_dst / sub
            shutil.copytree(src_sub, dest_sub)
            print(f"Copied {sub}/ → {dest_sub}")

    # requirements.txt
    req_src = ROOT_DIR / "requirements.txt"
    if req_src.exists():
        shutil.copy2(req_src, INSTALL_ROOT / "requirements.txt")
        print(f"Copied requirements.txt → {INSTALL_ROOT / 'requirements.txt'}")

    # scripts/chat.py (for mindbase-cli)
    scripts_dst = INSTALL_ROOT / "scripts"
    scripts_dst.mkdir(exist_ok=True)
    shutil.copy2(ROOT_DIR / "scripts" / "chat.py", scripts_dst / "chat.py")
    print(f"Copied chat.py → {scripts_dst / 'chat.py'}")

    # scripts/mindbase_tool.py (for mindbase-tool)
    shutil.copy2(ROOT_DIR / "scripts" / "mindbase_tool.py", scripts_dst / "mindbase_tool.py")
    print(f"Copied mindbase_tool.py → {scripts_dst / 'mindbase_tool.py'}")

    # src/mindbase_app.py (for mindbase)
    src_dst = INSTALL_ROOT / "src"
    src_dst.mkdir(exist_ok=True)
    shutil.copy2(ROOT_DIR / "src" / "mindbase_app.py", src_dst / "mindbase_app.py")
    print(f"Copied mindbase_app.py → {src_dst / 'mindbase_app.py'}")

    # assets/
    assets_src = ROOT_DIR / "assets"
    if assets_src.is_dir():
        assets_dst = INSTALL_ROOT / "assets"
        if assets_dst.exists():
            shutil.rmtree(assets_dst)
        shutil.copytree(assets_src, assets_dst)
        print(f"Copied assets/ → {assets_dst}")


def create_venv(force: bool = False) -> None:
    """Create venv and install dependencies."""
    venv_dir = INSTALL_ROOT / "venv"
    if force and venv_dir.exists():
        shutil.rmtree(venv_dir)
        print(f"Removed existing venv at {venv_dir}")
    if not venv_dir.exists():
        _run_with_spinner(f"Creating venv at {venv_dir}...", ["uv", "venv", str(venv_dir), "-q"])
    else:
        print(f"Venv exists, skipping (use --force-venv to rebuild)")

    env = {**os.environ, "VIRTUAL_ENV": str(venv_dir)}
    _run_with_spinner(
        "Installing dependencies...",
        ["uv", "pip", "install", "-r", str(INSTALL_ROOT / "requirements.txt"), "-q"],
        env=env,
    )


def write_launchers() -> None:
    """Write bash launchers and symlinks into ~/.local/bin/."""
    BIN_DIR.mkdir(parents=True, exist_ok=True)

    for sh_name, sh_content, bin_name in [
        ("mindbase.sh", MINDBASE_SH, "mindbase"),
        ("mindbase_cli.sh", MINDBASE_CLI_SH, "mindbase-cli"),
        ("mindbase_tool.sh", MINDBASE_TOOL_SH, "mindbase-tool"),
    ]:
        sh_path = INSTALL_ROOT / sh_name
        sh_path.write_text(sh_content)
        sh_path.chmod(0o755)
        print(f"Written {sh_path}")

        link = BIN_DIR / bin_name
        if link.exists() or link.is_symlink():
            link.unlink()
        link.symlink_to(sh_path)
        print(f"Symlink: {link} → {sh_path}")


def setup_env() -> None:
    """Write .env for the install, copying all keys from the repo .env when available."""
    env_file = INSTALL_ROOT / ".env"

    existing_vars = {}
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                existing_vars[k.strip()] = v.strip()

    repo_env = ROOT_DIR / ".env"
    if repo_env.exists():
        from dotenv import load_dotenv
        load_dotenv(repo_env)

    all_keys = ("NEBIUS_API_KEY", "MODEL_NAME",
                "LANGFUSE_SECRET_KEY", "LANGFUSE_PUBLIC_KEY", "LANGFUSE_BASE_URL",
                "GEMINI_API_KEY", "GOOGLE_APPLICATION_CREDENTIALS",
                "SLACK_WEBHOOK_URL", "SLACK_BOT_TOKEN", "SLACK_CHANNEL",
                "CONFLUENCE_USEREMAIL", "CONFLUENCE_TOKEN",
                "CONFLUENCE_PARENT_URL", "JIRA_BASE_URL",
                "SUPERHUMAN_API_TOKEN", "SUPERHUMAN_PARENT_DIR")

    if not existing_vars:
        nebius_key = os.environ.get("NEBIUS_API_KEY", "")
        if nebius_key:
            print(f"Using NEBIUS_API_KEY from {'repo .env' if repo_env.exists() else 'environment'}")
        else:
            nebius_key = _read_masked("Enter NEBIUS_API_KEY (press Enter to skip): ")
        existing_vars["NEBIUS_API_KEY"] = nebius_key

    added = 0
    for key in all_keys:
        if key in existing_vars and existing_vars[key]:
            continue
        val = os.environ.get(key, "")
        if val:
            existing_vars[key] = val
            print(f"Added {key} from {'repo .env' if repo_env.exists() else 'environment'}")
            added += 1

    env_file.write_text("".join(f"{k}={v}\n" for k, v in existing_vars.items()))
    env_file.chmod(0o600)
    if added:
        print(f"Merged {added} new key(s) into {env_file}")
    else:
        print(f"Keys saved to: {env_file}")
    print(f"To reset, delete that file and re-run: make install")


def check_path() -> None:
    """Warn if ~/.local/bin is not on PATH."""
    path_dirs = os.environ.get("PATH", "").split(":")
    if str(BIN_DIR) not in path_dirs:
        print(f"\nWARNING: {BIN_DIR} is not on your PATH.")
        print(f"Add this line to ~/.zshrc:")
        print(f'    export PATH="$HOME/.local/bin:$PATH"')
        print(f"Then run: source ~/.zshrc")
    else:
        print(f"\nReady! Commands:")
        print(f"  mindbase      — desktop app")
        print(f"  mindbase-cli  — terminal REPL")
        print(f"  mindbase-tool — non-interactive CLI (summarize/transcribe/translate)")


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Install the mindbase CLI and desktop app")
    parser.add_argument("--force-venv", action="store_true", help="Delete and recreate the venv")
    args = parser.parse_args()

    copy_sources()
    create_venv(force=args.force_venv)
    write_launchers()
    setup_env()
    check_path()


if __name__ == "__main__":
    main()
