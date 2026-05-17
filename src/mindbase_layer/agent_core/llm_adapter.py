import os
from pathlib import Path

from google import genai


class GeminiAdapter:
    """Adapter for Google Gemini API."""

    def __init__(self, model: str = "gemini-2.5-flash"):
        self._model = model
        self._client = genai.Client(
            api_key=os.environ.get("GOOGLE_API_KEY"),
            vertexai=False,
        )

    def audio_to_text_pipeline(self, audio_path: Path, output_dir: Path) -> Path:
        """Upload an audio file to Gemini, generate a summary, and save it as a .txt file."""
        audio_file = self._client.files.upload(
            file=audio_path,
            config={"mime_type": "audio/mpeg"},
        )
        print(f"Uploaded: {audio_file.name}")

        response = self._client.models.generate_content(
            model=self._model,
            contents=[
                "Please provide a concise summary of this audio recording. "
                "Highlight the main topics discussed and any significant conclusions.",
                audio_file,
            ],
        )

        output_file = output_dir / f"{audio_path.stem}.txt"
        output_file.write_text(response.text, encoding="utf-8")
        print(f"Saved: {output_file}")
        return output_file
