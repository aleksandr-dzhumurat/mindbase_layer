# Prompt Design

How prompts are structured and injected across the mindbase pipeline.

## Architecture

Prompts live in `src/mindbase_layer/prompts/*.md` and are loaded at import time by `agent_core/prompts.py` via `_load_prompt()`. They become `instructions` for pydantic-ai `Agent` instances defined in `agent.py`.

Runtime-dynamic values (language, transcript text, env-based config) are injected via `@agent.system_prompt` decorator functions that run on every call.

```
Static prompt (*.md)          →  Agent(instructions=...)
                                      ↓
Dynamic system_prompt(ctx)    →  appended at runtime
```

## Prompt files

All prompt files live in `src/mindbase_layer/prompts/`.

| File | Agent | Purpose |
|---|---|---|
| `video_summarizer.md` | `_summarizer_agent` | Summarize video/audio transcripts |
| `translation.md` | `translation_agent` | Translate Russian markdown to English |

`retrieval_agent` and `project_manager_agent` use inline instruction strings defined directly in `agent_core/prompts.py`.

## JIRA link normalization

Standup recordings mention JIRA tickets by voice — the transcriber garbles them (e.g. "SFIA 27", "SF3A2", "SFPI31"). The prompt must tell the model to reconstruct canonical `SFAI-<number>` and render as Markdown links.

### Gotcha: env vars in static prompts

Static `.md` prompts are loaded once at import time — they cannot read environment variables. The solution is a two-layer approach:

1. **Static prompt** (`video_summarizer.md`) defines the *rule* with a placeholder token:

   ```
   JIRA issues: ... rendered as a clickable Markdown link:
   [SFAI-<number>](JIRA_BASE_URL/browse/SFAI-<number>)
   ```

2. **Dynamic system prompt** (`summarize_system_prompt()`) injects the *actual value* at runtime:

   ```python
   jira_base = os.getenv("JIRA_BASE_URL", "")
   if jira_base:
       jira_line = f"\nJIRA_BASE_URL: {jira_base}\n"
   ```

The model sees both — the rule explaining what to do, and the concrete URL to use.

### Gotcha: rule placement matters

Placing the JIRA rule only in the dynamic system prompt (after the transcript) caused the model to ignore it. Moving it into the static prompt's **Formatting Rules** section — which the model reads *before* the transcript — fixed the issue.

Rules that constrain output format belong in the static instructions, not appended after the input data.

### Gotcha: translation preserves, summarization creates

The summarizer must *create* JIRA links from garbled speech. The translator must *preserve* existing links without altering them. These are different rules in different prompts:

- `video_summarizer.md`: "normalise task references and render as Markdown links"
- `translation.md`: "do NOT alter any Markdown links — keep them verbatim"

## Confluence formatting

Summaries pushed to Confluence use `markdown_to_storage()` from `adapters/jira_adapter.py` to convert markdown to Confluence storage format (XHTML). This handles headings, lists, bold/italic, code blocks, and links.
