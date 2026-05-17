import argparse
import sys
from pathlib import Path
from typing import Iterator, Optional

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from mindbase_layer.utils.common import get_logger
from mindbase_layer.agent_core.llm_adapter import GeminiAdapter

load_dotenv()

logger = get_logger(__name__)


def audio_file_iterator(
    limit: Optional[int] = None,
    prefix: Optional[str] = None,
) -> Iterator[Path]:
    """Iterate over .mp3 files from data directory.

    Args:
        limit: Maximum number of files to yield. None for unlimited.
        prefix: Filter files that contain this prefix in the filename. None for all files.

    Yields:
        Path objects for each .mp3 file.
    """
    script_dir = Path(__file__).parent
    data_dir = script_dir.parent / "data" / "audio"

    count = 0
    for mp3_file in sorted(data_dir.glob("*.mp3")):
        if prefix is not None and prefix not in mp3_file.name:
            continue
        if limit is not None and count >= limit:
            break
        yield mp3_file
        count += 1


llm_adapter = GeminiAdapter()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Summarize audio files using Gemini")
    parser.add_argument(
        "--prefix", help="Filter files containing this prefix in filename"
    )
    parser.add_argument(
        "--limit", type=int, default=1, help="Max files to process (default: 1)"
    )
    args = parser.parse_args()

    # Create output directory
    script_dir = Path(__file__).parent
    output_dir = script_dir.parent / "data" / "recognized_speech"
    output_dir.mkdir(parents=True, exist_ok=True)

    for f in audio_file_iterator(limit=args.limit, prefix=args.prefix):
        print(f"Processing: {f}")
        llm_adapter.audio_to_text_pipeline(f, output_dir)
