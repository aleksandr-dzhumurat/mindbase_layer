"""
Prepare the mindbase_copilot skill for installation at ~/.claude/skills/mindbase_copilot/.

Usage:
    python scripts/prepare_skill.py            # stage to data/mindbase_layer/
    python scripts/prepare_skill.py --install  # also copy to ~/.claude/skills/mindbase_copilot/
"""

import argparse
import shutil
from pathlib import Path

ROOT_DIR = Path(__file__).parent.parent
SRC_DIR = ROOT_DIR / "src" / "mindbase_layer"
STAGE_DIR = ROOT_DIR / "data" / "mindbase_layer"
INSTALL_DIR = Path.home() / ".claude" / "skills" / "mindbase_copilot"


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


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Prepare mindbase_copilot skill")
    parser.add_argument("--install", action="store_true", help=f"Also install to {INSTALL_DIR}")
    args = parser.parse_args()

    stage(STAGE_DIR)
    archive(STAGE_DIR)
    if args.install:
        install(STAGE_DIR, INSTALL_DIR)
