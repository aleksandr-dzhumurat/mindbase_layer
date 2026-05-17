import logging
import os
from dataclasses import dataclass
from pathlib import Path

from langfuse import get_client
from pydantic_ai import Agent, RunContext
from pydantic_ai.agent import InstrumentationSettings
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.nebius import NebiusProvider

from . import tools
from .agent_core.prompts import (
    PROJECT_MANAGER_INSTRUCTIONS,
    RETRIEVAL_AGENT_INSTRUCTIONS,
    SUMMARIZE_INSTRUCTIONS,
    home_dir_prompt,
)

Agent.instrument_all(InstrumentationSettings(include_content=True, version=1))
langfuse = get_client()
logger = logging.getLogger(__name__)


@dataclass
class SupportDependencies:
    home_dir: Path


@dataclass
class RetrievalDependencies:
    md_path: Path


@dataclass
class SummarizeDependencies:
    text: str
    language: str


_main_model = OpenAIChatModel(
    'Qwen/Qwen3-32B',
    provider=NebiusProvider(api_key=os.getenv('NEBIUS_API_KEY'))
)

_retrieval_model = OpenAIChatModel(
    'Qwen/Qwen3-30B-A3B-Instruct-2507',
    provider=NebiusProvider(api_key=os.getenv('NEBIUS_API_KEY'))
)

retrieval_agent = Agent(
    _retrieval_model,
    instructions=RETRIEVAL_AGENT_INSTRUCTIONS,
    deps_type=RetrievalDependencies,
    output_type=str,
)

_summarizer_agent = Agent(
    _main_model,
    instructions=SUMMARIZE_INSTRUCTIONS,
    deps_type=SummarizeDependencies,
    output_type=str,
)


@_summarizer_agent.system_prompt
def summarize_system_prompt(ctx: RunContext[SummarizeDependencies]) -> str:
    return (
        f"Respond in: {ctx.deps.language}\n\n"
        f"Transcript:\n{ctx.deps.text}"
    )


@retrieval_agent.tool
def query_documents(ctx: RunContext[RetrievalDependencies], query: str) -> str:
    """Search the indexed markdown document(s) using TF-IDF cosine similarity."""
    return tools.query_documents(ctx.deps.md_path, query)


project_manager_agent = Agent(
    _main_model,
    instructions=PROJECT_MANAGER_INSTRUCTIONS,
    deps_type=SupportDependencies
)


@project_manager_agent.system_prompt
def add_home_dir(ctx: RunContext[SupportDependencies]) -> str:
    return home_dir_prompt(ctx.deps.home_dir)


@project_manager_agent.tool
def file_search(ctx: RunContext[SupportDependencies], filename: str) -> str:
    """Search for a file by name across Downloads, Documents and PycharmProjects under home_dir.
    If filename is an absolute path, checks existence directly without searching."""
    return tools.file_search(filename, ctx.deps.home_dir)


@project_manager_agent.tool
def file_fuzzy_search(ctx: RunContext[SupportDependencies], query: str) -> str:
    """Fuzzy search for a file by query across Downloads, Documents and PycharmProjects.
    Indexes all filenames with TF-IDF and returns top-10 matches. Use as fallback when file_search returns nothing."""
    return tools.file_fuzzy_search(query, ctx.deps.home_dir)


@project_manager_agent.tool
def pdf_to_md(_ctx: RunContext[SupportDependencies], pdf_path: str) -> str:
    """Convert a PDF file to markdown. Skips if output already exists."""
    return tools.pdf_to_md(pdf_path)


@project_manager_agent.tool
async def generate_subtitles(_ctx: RunContext[SupportDependencies], video_path: str, language: str = "en") -> str:
    """Generate an SRT subtitles file from a video. language is a BCP-47 code e.g. 'en', 'ru'. Expects a full resolved path."""
    return tools.generate_subtitles(video_path, language)


@project_manager_agent.tool
async def summarize_video(ctx: RunContext[SupportDependencies], video_path: str, spoken_language: str = "en") -> str:
    """Summarize a video lecture. Generates subtitles first if they don't exist.
    spoken_language: language spoken in the video (BCP-47, e.g. 'en', 'ru'). Summary will be in the same language.
    """
    return await tools.summarize_video(video_path, spoken_language, _summarizer_agent, SummarizeDependencies, ctx.usage)


_YOUTUBE_DIR = Path(__file__).parent.parent / "data" / "youtube"


@project_manager_agent.tool
async def youtube_download(_ctx: RunContext[SupportDependencies], url: str, mode: str = "video") -> str:
    """Download a YouTube video or audio track. mode must be 'video' or 'audio'."""
    return await tools.youtube_download(url, mode, _YOUTUBE_DIR)


@project_manager_agent.tool
def m4a_to_mp3(_ctx: RunContext[SupportDependencies], input_path: str) -> str:
    """Convert an m4a (or other audio) file to mp3. Expects a full resolved path."""
    return tools.m4a_to_mp3(input_path)


@project_manager_agent.tool
def remove_file(_ctx: RunContext[SupportDependencies], file_path: str) -> str:
    """Delete a file or directory. Uses shutil.rmtree for directories, Path.unlink for files."""
    return tools.remove_file(file_path)


@project_manager_agent.tool
async def search_file_content(ctx: RunContext[SupportDependencies], md_path: str, query: str) -> str:
    """Search the content of a markdown file or directory using the retrieval agent."""
    return await tools.search_file_content(md_path, query, retrieval_agent, RetrievalDependencies, ctx.usage)
