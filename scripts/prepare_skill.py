"""
Prepare the mindbase_copilot skill for installation at ~/.claude/skills/mindbase_copilot/.

Usage:
    python scripts/prepare_skill.py            # stage to data/mindbase_layer/
    python scripts/prepare_skill.py --install  # also copy to ~/.claude/skills/mindbase_copilot/
    python scripts/prepare_skill.py --cli      # install as `mindbase` console command
    python scripts/prepare_skill.py --cli --force-venv  # rebuild venv from scratch
"""

import argparse
import os
import shutil
import subprocess
from pathlib import Path

ROOT_DIR = Path(__file__).parent.parent
SRC_DIR = ROOT_DIR / "src" / "mindbase_layer"
STAGE_DIR = ROOT_DIR / "data" / "mindbase_layer"
INSTALL_DIR = Path.home() / ".claude" / "skills" / "mindbase_copilot"
CLI_ROOT = Path.home() / ".local" / "share" / "mindbase"
CLI_BIN = Path.home() / ".local" / "bin"

MINDBASE_SH = """\
#!/usr/bin/env bash
set -euo pipefail

INSTALL_ROOT="$HOME/.local/share/mindbase"
ENV_FILE="$INSTALL_ROOT/.env"

# ── Load env ─────────────────────────────────────────────────────────────────
if [ ! -f "$ENV_FILE" ]; then
    echo "ERROR: $ENV_FILE not found. Re-run installation: make cli-install" >&2
    exit 1
fi
set -a; source "$ENV_FILE"; set +a

# ── Run interactive REPL ─────────────────────────────────────────────────────
DATA_DIR="$INSTALL_ROOT/history"
mkdir -p "$DATA_DIR"

echo "Starting mindbase, please wait..."

DATA_DIR="$DATA_DIR" \\
PYTHONPATH="$INSTALL_ROOT" \\
VIRTUAL_ENV="$INSTALL_ROOT/venv" \\
uv run python "$INSTALL_ROOT/scripts/chat.py"
"""


def stage(stage_dir: Path) -> None:
    if stage_dir.exists():
        shutil.rmtree(stage_dir)
    stage_dir.mkdir(parents=True)

    # SKILL.md goes at the top level
    shutil.copy2(SRC_DIR / "SKILL.md", stage_dir / "SKILL.md")
    print(f"Copied SKILL.md → {stage_dir / 'SKILL.md'}")

    # Python source files go into mindbase_layer/ so `from mindbase_layer import ...` works
    pkg_dir = stage_dir / "mindbase_layer"
    pkg_dir.mkdir()
    for src_file in sorted(SRC_DIR.glob("*.py")):
        dest = pkg_dir / src_file.name
        shutil.copy2(src_file, dest)
        print(f"Copied {src_file.name} → {dest}")

    # subdirectories (utils, etc.)
    for sub in ("utils", "agent_core"):
        src_sub = SRC_DIR / sub
        if src_sub.is_dir():
            dest_sub = pkg_dir / sub
            shutil.copytree(src_sub, dest_sub)
            print(f"Copied {sub}/ → {dest_sub}")

    # requirements.txt at top level
    req_src = ROOT_DIR / "requirements.txt"
    if req_src.exists():
        shutil.copy2(req_src, stage_dir / "requirements.txt")
        print(f"Copied requirements.txt → {stage_dir / 'requirements.txt'}")

    print(f"\nStaged skill at: {stage_dir}")


def archive(stage_dir: Path) -> Path:
    """Create a zip archive of the staged skill directory."""
    zip_path = stage_dir.parent / f"{stage_dir.name}.zip"
    shutil.make_archive(str(zip_path.with_suffix("")), "zip", stage_dir.parent, stage_dir.name)
    print(f"Archive created: {zip_path}")
    return zip_path


def install(stage_dir: Path, install_dir: Path) -> None:
    if install_dir.exists():
        shutil.rmtree(install_dir)
    shutil.copytree(stage_dir, install_dir)
    print(f"Installed skill at: {install_dir}")


def _read_masked(prompt: str) -> str:
    """Read a password from stdin, echoing '*' for each character typed."""
    import sys
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
            if ch in ("\x7f", "\x08"):  # backspace / delete
                if chars:
                    chars.pop()
                    sys.stdout.write("\b \b")
                    sys.stdout.flush()
            elif ch == "\x03":  # Ctrl-C
                raise KeyboardInterrupt
            else:
                chars.append(ch)
                sys.stdout.write("*")
                sys.stdout.flush()
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
    sys.stdout.write("\n")
    return "".join(chars)


def cli_install(stage_dir: Path, install_root: Path, bin_dir: Path, force_venv: bool = False) -> None:
    # 1. Deploy package
    pkg_src = stage_dir / "mindbase_layer"
    pkg_dst = install_root / "mindbase_layer"
    if pkg_dst.exists():
        shutil.rmtree(pkg_dst)
    shutil.copytree(pkg_src, pkg_dst)
    print(f"Deployed mindbase_layer/ → {pkg_dst}")

    # 2. Copy requirements.txt
    shutil.copy2(stage_dir / "requirements.txt", install_root / "requirements.txt")
    print(f"Deployed requirements.txt → {install_root / 'requirements.txt'}")

    # 3. Copy scripts/chat.py
    scripts_dst = install_root / "scripts"
    scripts_dst.mkdir(exist_ok=True)
    shutil.copy2(ROOT_DIR / "scripts" / "chat.py", scripts_dst / "chat.py")
    print(f"Deployed chat.py → {scripts_dst / 'chat.py'}")

    # 4. Venv
    venv_dir = install_root / "venv"
    if force_venv and venv_dir.exists():
        shutil.rmtree(venv_dir)
        print(f"Removed existing venv at {venv_dir}")
    if not venv_dir.exists():
        subprocess.run(["uv", "venv", str(venv_dir), "-q"], check=True)
        print(f"Created venv at {venv_dir}")
    else:
        print(f"Venv exists, skipping (use --force-venv to rebuild)")

    # 5. Install deps
    env = {**os.environ, "VIRTUAL_ENV": str(venv_dir)}
    subprocess.run(
        ["uv", "pip", "install", "-r", str(install_root / "requirements.txt"), "-q"],
        check=True, env=env,
    )
    print("Dependencies installed")

    # 6. Write mindbase.sh
    sh_path = install_root / "mindbase.sh"
    sh_path.write_text(MINDBASE_SH)
    sh_path.chmod(0o755)
    print(f"Written {sh_path}")

    # 7. Write .env if not present
    env_file = install_root / ".env"
    if not env_file.exists():
        key = _read_masked("Enter NEBIUS_API_KEY: ")
        env_file.write_text(f"NEBIUS_API_KEY={key}\n")
        env_file.chmod(0o600)
        print(f"Key saved to: {env_file}")
        print(f"To reset it, delete that file and re-run: make cli-install")
    else:
        print(f".env already exists at {env_file}, skipping key prompt")

    # 8. Symlink into bin
    bin_dir.mkdir(parents=True, exist_ok=True)
    link = bin_dir / "mindbase"
    if link.exists() or link.is_symlink():
        link.unlink()
    link.symlink_to(sh_path)
    print(f"Symlink: {link} → {sh_path}")

    # 9. PATH check
    path_dirs = os.environ.get("PATH", "").split(":")
    if str(bin_dir) not in path_dirs:
        print(f"\nWARNING: {bin_dir} is not on your PATH.")
        print(f"Add this line to ~/.zshrc:")
        print(f'    export PATH="$HOME/.local/bin:$PATH"')
        print(f"Then run: source ~/.zshrc")
    else:
        print(f"\nmindbase is ready — type 'mindbase' to start.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Prepare mindbase_copilot skill")
    parser.add_argument("--install", action="store_true", help=f"Also install to {INSTALL_DIR}")
    parser.add_argument("--cli", action="store_true", help=f"Install as console command at {CLI_BIN}/mindbase")
    parser.add_argument("--force-venv", action="store_true", help="Delete and recreate the venv even if it exists")
    args = parser.parse_args()

    stage(STAGE_DIR)
    archive(STAGE_DIR)
    if args.install:
        install(STAGE_DIR, INSTALL_DIR)
    if args.cli:
        cli_install(STAGE_DIR, CLI_ROOT, CLI_BIN, force_venv=args.force_venv)
