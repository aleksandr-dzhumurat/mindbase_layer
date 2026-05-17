#!/usr/bin/env python3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from mindbase_layer.utils.audio import extract_audio_pipeline

__all__ = ["extract_audio_pipeline"]

if __name__ == "__main__":
    extract_audio_pipeline()
