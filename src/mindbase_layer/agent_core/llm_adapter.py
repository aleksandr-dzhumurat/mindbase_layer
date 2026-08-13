"""Lightweight LLM adapter using pydantic-ai Model layer directly (no Agent overhead)."""

import logging
import os
from dataclasses import dataclass
from pathlib import Path

from pydantic_ai.messages import ModelRequest, SystemPromptPart, UserPromptPart
from pydantic_ai.models import Model, ModelRequestParameters

logger = logging.getLogger(__name__)

_DEFAULT_PARAMS = ModelRequestParameters(function_tools=[], allow_text_output=True, output_mode=None)


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0

    def add(self, other: "Usage") -> None:
        self.input_tokens += other.input_tokens
        self.output_tokens += other.output_tokens
        self.total_tokens += other.total_tokens


@dataclass
class LLMResult:
    text: str
    usage: Usage


class LLMAdapter:
    """Thin wrapper over pydantic-ai Model for simple prompt→text calls with token tracking."""

    def __init__(self, model: Model | None = None):
        self._model = model or _build_model()
        self._cumulative = Usage()

    @property
    def cumulative_usage(self) -> Usage:
        return self._cumulative

    async def generate(self, prompt: str, system: str = "") -> LLMResult:
        parts = []
        if system:
            parts.append(SystemPromptPart(content=system))
        parts.append(UserPromptPart(content=prompt))

        resp = await self._model.request(
            [ModelRequest(parts=parts)],
            model_settings=None,
            model_request_parameters=_DEFAULT_PARAMS,
        )
        usage = Usage(
            input_tokens=resp.usage.input_tokens,
            output_tokens=resp.usage.output_tokens,
            total_tokens=resp.usage.total_tokens,
        )
        self._cumulative.add(usage)
        logger.info(
            "LLM call: in=%d out=%d total=%d (cumulative=%d)",
            usage.input_tokens, usage.output_tokens, usage.total_tokens,
            self._cumulative.total_tokens,
        )
        return LLMResult(text=resp.text.strip(), usage=usage)

    async def translate(self, text: str, system_prompt: str = "") -> LLMResult:
        if not system_prompt:
            prompt_path = Path(__file__).parent.parent / "prompts" / "translation.md"
            system_prompt = prompt_path.read_text(encoding="utf-8")
        return await self.generate(prompt=text, system=system_prompt)


def _build_model() -> Model:
    model_name = os.getenv("MODEL_NAME", "")

    if model_name.startswith("gemini"):
        from pydantic_ai.models.google import GoogleModel

        api_key = os.getenv("GOOGLE_API_KEY")
        if os.getenv("GOOGLE_APPLICATION_CREDENTIALS"):
            from pydantic_ai.providers.google_cloud import GoogleCloudProvider
            provider = GoogleCloudProvider(
                project=os.getenv("GOOGLE_CLOUD_PROJECT"),
                location=os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1"),
            )
        elif api_key:
            from pydantic_ai.providers.google import GoogleProvider
            provider = GoogleProvider(api_key=api_key)
        else:
            raise RuntimeError("Gemini model requires GOOGLE_APPLICATION_CREDENTIALS or GOOGLE_API_KEY")
        return GoogleModel(model_name, provider=provider)

    from pydantic_ai.models.openai import OpenAIChatModel
    from pydantic_ai.providers.nebius import NebiusProvider

    api_key = os.getenv("NEBIUS_API_KEY")
    if not api_key:
        raise RuntimeError("NEBIUS_API_KEY environment variable is not set")
    if not model_name:
        model_name = "Qwen/Qwen3-32B"
    return OpenAIChatModel(model_name, provider=NebiusProvider(api_key=api_key))
