#!/usr/bin/env python3
"""
mindbase_app.py — native desktop chat app for the mindbase agent.

Uses pywebview to render a chat interface directly — no Streamlit dependency.
The agent runs in background threads via pywebview's JS-to-Python bridge.

Run with: PYTHONPATH=src python src/mindbase_app.py
"""

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR in sys.path:
    sys.path.remove(_SCRIPT_DIR)

import webview

VIDEO_EXTENSIONS = {".mp4", ".m4a", ".mp3", ".mov", ".webm"}
TEXT_EXTENSIONS = {".txt", ".md", ".srt"}
DOCUMENT_EXTENSIONS = {".pdf"}


class _StdoutCapture:
    """Intercepts stdout/stderr and pushes each line to the UI via evaluate_js."""

    def __init__(self, window, original):
        self._window = window
        self._original = original
        self._buf = ""
        self._last_push = 0

    def write(self, s):
        self._original.write(s)
        self._original.flush()
        self._buf += s
        import re
        parts = re.split(r'[\r\n]+', self._buf)
        self._buf = parts[-1]
        for part in parts[:-1]:
            self._push(part)
        if self._buf.strip() and (time.time() - self._last_push > 0.3):
            self._push(self._buf)
            self._buf = ""

    def _push(self, text):
        text = text.strip()
        if not text:
            return
        self._last_push = time.time()
        safe = json.dumps(text)
        try:
            self._window.evaluate_js(f"updateProgress({safe})")
        except Exception:
            pass

    def flush(self):
        self._original.flush()

    def fileno(self):
        return self._original.fileno()

    def isatty(self):
        return False


class Api:
    def __init__(self):
        self._window = None
        self._lock = threading.Lock()
        self._agent = None
        self._langfuse = None
        self._message_history = None
        self._deps = None
        self._total_input_tokens = 0
        self._total_output_tokens = 0

    def set_window(self, window):
        self._window = window

    def _ensure_loaded(self):
        with self._lock:
            if self._agent is not None:
                return
            from mindbase_layer.agent import (
                SupportDependencies,
                langfuse,
                project_manager_agent,
            )
            from mindbase_layer.agent_core.memory_layer import MessageHistory

            self._agent = project_manager_agent
            self._langfuse = langfuse
            self._message_history = MessageHistory()
            self._deps = SupportDependencies(home_dir=Path.home())

    def preload(self):
        threading.Thread(target=self._ensure_loaded, daemon=True).start()

    def _accumulate_usage(self, result):
        u = result.usage
        self._total_input_tokens += u.input_tokens
        self._total_output_tokens += u.output_tokens

    def get_usage(self):
        return {
            "input": self._total_input_tokens,
            "output": self._total_output_tokens,
            "total": self._total_input_tokens + self._total_output_tokens,
        }

    def _with_progress(self, fn):
        old_stdout, old_stderr = sys.stdout, sys.stderr
        sys.stdout = _StdoutCapture(self._window, old_stdout)
        sys.stderr = _StdoutCapture(self._window, old_stderr)
        try:
            return fn()
        finally:
            sys.stdout = old_stdout
            sys.stderr = old_stderr

    def send_message(self, text):
        self._ensure_loaded()
        def _run():
            return self._agent.run_sync(
                text,
                deps=self._deps,
                message_history=self._message_history,
            )
        result = self._with_progress(_run)
        self._accumulate_usage(result)
        self._message_history.update_history(result.new_messages())
        self._save_history()
        self._langfuse.flush()
        return result.output

    def pick_file(self):
        result = self._window.create_file_dialog(
            webview.FileDialog.OPEN,
            allow_multiple=False,
            file_types=(
                "Video/Audio (*.mp4;*.m4a;*.mp3;*.mov;*.webm)",
                "PDF (*.pdf)",
            ),
        )
        if result:
            path = result[0] if isinstance(result, (list, tuple)) else result
            return str(path)
        return None

    def get_file_type(self, file_path):
        suffix = Path(file_path).suffix.lower()
        if suffix in VIDEO_EXTENSIONS:
            return "video"
        if suffix in DOCUMENT_EXTENSIONS:
            return "document"
        return "other"

    def process_file(self, file_path, language=None):
        self._ensure_loaded()
        path = Path(file_path)
        suffix = path.suffix.lower()
        if suffix in VIDEO_EXTENSIONS:
            lang = language or "en"
            prompt = f"Summarize this video: {path} (spoken language: {lang})"
        elif suffix in DOCUMENT_EXTENSIONS:
            prompt = f"Convert this PDF to markdown: {path}"
        else:
            prompt = f"I uploaded a file: {path}"

        def _run():
            return self._agent.run_sync(
                prompt,
                deps=self._deps,
                message_history=self._message_history,
            )
        result = self._with_progress(_run)
        self._accumulate_usage(result)
        self._message_history.update_history(result.new_messages())
        self._save_history()
        self._langfuse.flush()
        return result.output

    def _env_path(self):
        install_env = Path.home() / ".local" / "share" / "mindbase" / ".env"
        if install_env.exists():
            return install_env
        script_dir = Path(os.path.abspath(__file__))
        repo_env = script_dir.parent.parent / ".env"
        return repo_env

    def get_settings(self):
        env_file = self._env_path()
        vals = {}
        if env_file.exists():
            for line in env_file.read_text().splitlines():
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    k, v = line.split("=", 1)
                    vals[k.strip()] = v.strip()
        return {
            "nebius_api_key": vals.get("NEBIUS_API_KEY", ""),
            "slack_webhook_url": vals.get("SLACK_WEBHOOK_URL", ""),
            "slack_bot_token": vals.get("SLACK_BOT_TOKEN", ""),
            "slack_channel": vals.get("SLACK_CHANNEL", ""),
            "model_name": vals.get("MODEL_NAME", "Qwen/Qwen3-32B"),
            "confluence_useremail": vals.get("CONFLUENCE_USEREMAIL", ""),
            "confluence_token": vals.get("CONFLUENCE_TOKEN", ""),
            "google_creds_path": vals.get("GOOGLE_APPLICATION_CREDENTIALS", ""),
            "superhuman_api_token": vals.get("SUPERHUMAN_API_TOKEN", ""),
            "superhuman_parent_dir": vals.get("SUPERHUMAN_PARENT_DIR", ""),
            "confluence_parent_url": vals.get("CONFLUENCE_PARENT_URL", ""),
            "jira_base_url": vals.get("JIRA_BASE_URL", ""),
        }

    def save_settings(self, nebius_api_key, slack_webhook_url, slack_bot_token, slack_channel, model_name,
                       confluence_useremail='', confluence_token='',
                       google_creds_path='',
                       superhuman_api_token='', superhuman_parent_dir='',
                       confluence_parent_url='', jira_base_url=''):
        env_file = self._env_path()
        vals = {}
        if env_file.exists():
            for line in env_file.read_text().splitlines():
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    k, v = line.split("=", 1)
                    vals[k.strip()] = v.strip()
        updates = {
            "NEBIUS_API_KEY": nebius_api_key,
            "SLACK_WEBHOOK_URL": slack_webhook_url,
            "SLACK_BOT_TOKEN": slack_bot_token,
            "SLACK_CHANNEL": slack_channel,
            "MODEL_NAME": model_name,
            "CONFLUENCE_USEREMAIL": confluence_useremail,
            "CONFLUENCE_TOKEN": confluence_token,
            "GOOGLE_APPLICATION_CREDENTIALS": google_creds_path,
            "SUPERHUMAN_API_TOKEN": superhuman_api_token,
            "SUPERHUMAN_PARENT_DIR": superhuman_parent_dir,
            "CONFLUENCE_PARENT_URL": confluence_parent_url,
            "JIRA_BASE_URL": jira_base_url,
        }
        for k, v in updates.items():
            if v:
                vals[k] = v
                os.environ[k] = v
        env_file.write_text("".join(f"{k}={v}\n" for k, v in vals.items()))
        env_file.chmod(0o600)
        return True

    def _prompts_dir(self):
        from mindbase_layer.agent_core import prompts as _pm
        return Path(_pm.__file__).parent.parent / "prompts"

    def get_prompts(self):
        d = self._prompts_dir()
        def _read(name):
            p = d / name
            return p.read_text(encoding="utf-8") if p.exists() else ""
        return {
            "summarize": _read("video_summarizer.md"),
            "translation": _read("translation.md"),
        }

    def save_prompts(self, summarize_text, translation_text):
        d = self._prompts_dir()
        (d / "video_summarizer.md").write_text(summarize_text, encoding="utf-8")
        (d / "translation.md").write_text(translation_text, encoding="utf-8")
        return True

    def workflow_pick_video(self):
        result = self._window.create_file_dialog(
            webview.FileDialog.OPEN,
            allow_multiple=False,
            file_types=(
                "Supported files (*.mp4;*.m4a;*.mp3;*.mov;*.webm;*.txt;*.md;*.srt)",
            ),
        )
        if result:
            path = result[0] if isinstance(result, (list, tuple)) else result
            return str(path)
        return None

    def workflow_save_pasted_text(self, text):
        if not text or not text.strip():
            return None
        pasted_dir = Path.home() / ".local" / "share" / "mindbase" / "pasted"
        pasted_dir.mkdir(parents=True, exist_ok=True)
        path = pasted_dir / f"pasted_{time.strftime('%Y%m%d_%H%M%S')}.txt"
        path.write_text(text, encoding="utf-8")
        return str(path)

    def _wf_update(self, step, status, detail='', links=None):
        safe = json.dumps({"step": step, "status": status, "detail": detail, "links": links or []})
        self._window.evaluate_js(f"wfUpdate({safe})")

    def reveal_in_finder(self, file_path):
        try:
            subprocess.run(["open", "-R", file_path], check=False)
            return True
        except Exception as e:
            self._wf_log(f"reveal_in_finder failed: {e}")
            return False

    def open_url(self, url):
        try:
            import webbrowser
            webbrowser.open(url)
            return True
        except Exception as e:
            self._wf_log(f"open_url failed: {e}")
            return False

    def _wf_log(self, msg):
        log_file = Path.home() / ".local" / "share" / "mindbase" / "workflow.log"
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%H:%M:%S')}] {msg}\n")

    def _load_full_text(self, text_path):
        if text_path.suffix.lower() == '.srt':
            from mindbase_layer.utils.retrieve_md import squash_srt
            nodes = squash_srt(text_path)
            if not nodes:
                return None
            return "\n\n".join(f"[{n.header}]\n{n.body}" for n in nodes)
        return text_path.read_text(encoding="utf-8")

    def run_workflow(self, video_path, language, steps_json='{}'):
        try:
            steps = json.loads(steps_json)
            self._wf_log(f"=== Pipeline start: {video_path} lang={language} steps={steps}")
            path = Path(video_path)
            is_text = path.suffix.lower() in TEXT_EXTENSIONS
            summary_text = None

            if is_text:
                text_path = path
                summary_path = path.with_name(f"{path.stem}_summary.md")
                self._wf_update('transcribe', 'skip', 'Text file — no transcription needed')
                self._wf_log(f"Text input: {path.name}, skipping transcribe")
            else:
                srt_path = path.with_suffix('.srt')
                text_path = srt_path
                summary_path = srt_path.with_name(f"{srt_path.stem}_summary.md")

                if steps.get('transcribe', True):
                    self._wf_update('transcribe', 'running', f'Processing {path.name}...')
                    if not srt_path.exists():
                        self._wf_log(f"Transcribing {path.name}")
                        from mindbase_layer.utils.media import extract_audio_pipeline, transcribe
                        mp3_path = str(extract_audio_pipeline(video_path))
                        srt_path = Path(transcribe(mp3_path, language=language))
                        text_path = srt_path
                    else:
                        self._wf_log(f"Using existing subtitles: {srt_path}")
                        self._wf_update('transcribe', 'running', 'Using existing subtitles')
                    self._wf_update('transcribe', 'done', str(srt_path))
                else:
                    self._wf_update('transcribe', 'skip', 'Disabled')

            if steps.get('summarize', True):
                if summary_path.exists():
                    self._wf_log(f"Using existing summary: {summary_path}")
                    self._wf_update('summarize', 'running', 'Using existing summary')
                    summary_text = summary_path.read_text(encoding="utf-8")
                else:
                    if not text_path.exists():
                        self._wf_update('summarize', 'error', 'No text source — enable Transcribe first')
                        return None
                    self._wf_log("Generating summary with LLM")
                    self._wf_update('summarize', 'running', 'Generating summary...')
                    self._ensure_loaded()
                    from mindbase_layer.agent import _summarizer_agent, SummarizeDependencies

                    full_text = self._load_full_text(text_path)
                    if full_text is None:
                        self._wf_log("ERROR: No text extracted from subtitles")
                        self._wf_update('summarize', 'error', 'No text extracted from subtitles')
                        return None

                    result = _summarizer_agent.run_sync(
                        "Summarize this video transcript.",
                        deps=SummarizeDependencies(text=full_text, language=language),
                    )
                    self._accumulate_usage(result)
                    summary_text = result.output
                    summary_path.write_text(summary_text, encoding="utf-8")
                    self._wf_log(f"Summary saved: {summary_path}")
                self._wf_update('summarize', 'done', str(summary_path))
            else:
                self._wf_update('summarize', 'skip', 'Disabled')
                if summary_path.exists():
                    summary_text = summary_path.read_text(encoding="utf-8")

            _env_file = self._env_path()
            self._wf_log(f"Reading env from: {_env_file} (exists={_env_file.exists()})")
            if _env_file.exists():
                from dotenv import dotenv_values
                _live = dotenv_values(_env_file)
            else:
                _live = {}

            en_path = None
            translating_summary = False
            if steps.get('translate', False):
                if summary_text:
                    translating_summary = True
                    source_text = summary_text
                    target_stem = summary_path.stem
                else:
                    translating_summary = False
                    source_text = self._load_full_text(text_path) if text_path.exists() else None
                    target_stem = text_path.stem

                if not source_text:
                    self._wf_update('translate', 'error', 'No text source — enable Transcribe or Summarize first')
                else:
                    candidate_en_path = path.parent / f"{target_stem}_en.md"
                    if candidate_en_path.exists():
                        self._wf_log(f"Using existing translation: {candidate_en_path}")
                        en_path = candidate_en_path
                        translated_text = en_path.read_text(encoding="utf-8")
                    else:
                        kind = "summary" if translating_summary else "transcript"
                        self._wf_log(f"Translating {kind} to English via LLMAdapter...")
                        self._wf_update('translate', 'running', 'Translating to English...')
                        translated_text = None
                        try:
                            import asyncio
                            from mindbase_layer.agent_core.llm_adapter import LLMAdapter
                            llm = LLMAdapter()
                            self._wf_log(f"Using {llm._model.__class__.__name__} (not translation_agent)")
                            tr_result = asyncio.run(llm.translate(source_text))
                            self._accumulate_usage(tr_result)
                            self._wf_log(f"Translation tokens: in={tr_result.usage.input_tokens} out={tr_result.usage.output_tokens}")
                            translated_text = tr_result.text
                            candidate_en_path.write_text(translated_text, encoding="utf-8")
                            en_path = candidate_en_path
                            self._wf_log(f"Translation saved: {en_path}")
                        except Exception as e:
                            self._wf_log(f"Translation failed: {e}")
                            self._wf_update('translate', 'error', str(e))
                    if translated_text:
                        if translating_summary:
                            summary_text = translated_text
                        self._wf_update('translate', 'done', str(en_path))
            else:
                self._wf_update('translate', 'skip', 'Disabled')

            confluence_page_url = None
            if steps.get('confluence', False):
                from urllib.parse import urlparse
                parent_url = _live.get("CONFLUENCE_PARENT_URL", "") or os.environ.get("CONFLUENCE_PARENT_URL", "")
                conf_user = _live.get("CONFLUENCE_USEREMAIL", "") or os.environ.get("CONFLUENCE_USEREMAIL", "")
                conf_token = _live.get("CONFLUENCE_TOKEN", "") or os.environ.get("CONFLUENCE_TOKEN", "")
                conf_base = ""
                conf_space = ""
                parent_id = None
                if parent_url:
                    parsed = urlparse(parent_url)
                    conf_base = f"{parsed.scheme}://{parsed.netloc}"
                    parts = parsed.path.rstrip("/").split("/")
                    for segment in reversed(parts):
                        if segment.isdigit():
                            parent_id = segment
                            break
                    for i, p in enumerate(parts):
                        if p == "spaces" and i + 1 < len(parts):
                            conf_space = parts[i + 1]
                            break
                if not summary_text:
                    self._wf_update('confluence', 'error', 'No summary — enable Summarize first')
                elif conf_base and conf_user and conf_token:
                    page_title = f"Summary: {path.stem}"
                    self._wf_update('confluence', 'running', f'Creating page under parent...')
                    self._wf_log(f"Confluence: creating page '{page_title}' base={conf_base} space={conf_space} parent={parent_id}")
                    try:
                        import requests as req
                        from requests.auth import HTTPBasicAuth
                        from mindbase_layer.adapters.jira_adapter import markdown_to_storage
                        html_body = markdown_to_storage(summary_text)
                        url = f"{conf_base}/wiki/rest/api/content"
                        page_payload = {
                            "type": "page",
                            "title": page_title,
                            "body": {"storage": {"value": html_body, "representation": "storage"}},
                        }
                        if conf_space:
                            page_payload["space"] = {"key": conf_space}
                        if parent_id:
                            page_payload["ancestors"] = [{"id": parent_id}]
                        resp = req.post(
                            url,
                            json=page_payload,
                            auth=HTTPBasicAuth(conf_user, conf_token),
                            headers={"Content-Type": "application/json"},
                            timeout=15,
                        )
                        if resp.ok:
                            webui = resp.json().get("_links", {}).get("webui", "")
                            confluence_page_url = f"{conf_base}/wiki{webui}" if webui else None
                            self._wf_log(f"Confluence page created: {confluence_page_url}")
                            self._wf_update('confluence', 'done', f'Page created')
                        elif resp.status_code == 400 and "already exists" in resp.text:
                            self._wf_log("Confluence: page already exists, searching for it...")
                            auth = HTTPBasicAuth(conf_user, conf_token)
                            search_params = {"title": page_title, "expand": "version"}
                            if conf_space:
                                search_params["spaceKey"] = conf_space
                            sr = req.get(url, params=search_params, auth=auth,
                                         headers={"Accept": "application/json"}, timeout=15)
                            if sr.ok:
                                results = sr.json().get("results", [])
                                existing = next((p for p in results if p.get("title") == page_title), None)
                                if existing:
                                    eid = existing["id"]
                                    ver = existing["version"]["number"]
                                    update_payload = {
                                        "type": "page",
                                        "title": page_title,
                                        "version": {"number": ver + 1},
                                        "body": {"storage": {"value": html_body, "representation": "storage"}},
                                    }
                                    if conf_space:
                                        update_payload["space"] = {"key": conf_space}
                                    ur = req.put(f"{url}/{eid}", json=update_payload,
                                                 auth=auth, headers={"Content-Type": "application/json"}, timeout=15)
                                    if ur.ok:
                                        webui = ur.json().get("_links", {}).get("webui", "")
                                        confluence_page_url = f"{conf_base}/wiki{webui}" if webui else None
                                        self._wf_log(f"Confluence page updated: {confluence_page_url}")
                                        self._wf_update('confluence', 'done', f'Page updated')
                                    else:
                                        webui = existing.get("_links", {}).get("webui", "")
                                        confluence_page_url = f"{conf_base}/wiki{webui}" if webui else None
                                        self._wf_log(f"Confluence update failed, using existing URL: {confluence_page_url}")
                                        self._wf_update('confluence', 'done', f'Page exists (update failed)')
                                else:
                                    self._wf_log("Confluence: could not find existing page by title")
                                    self._wf_update('confluence', 'error', 'Page exists but could not locate it')
                            else:
                                self._wf_log(f"Confluence search failed: HTTP {sr.status_code}")
                                self._wf_update('confluence', 'error', 'Page exists but search failed')
                        else:
                            err = resp.json().get("message", f"HTTP {resp.status_code}")
                            self._wf_log(f"Confluence error: {err}")
                            self._wf_update('confluence', 'error', err)
                    except Exception as e:
                        self._wf_log(f"Confluence exception: {e}")
                        self._wf_update('confluence', 'error', str(e))
                else:
                    missing = []
                    if not conf_base and not parent_url:
                        missing.append('CONFLUENCE_PARENT_URL')
                    if not conf_user:
                        missing.append('CONFLUENCE_USEREMAIL')
                    if not conf_token:
                        missing.append('CONFLUENCE_TOKEN')
                    self._wf_update('confluence', 'skip', f'Missing: {", ".join(missing)}')
            else:
                self._wf_update('confluence', 'skip', 'Disabled')

            if steps.get('superhuman', False):
                sh_token = _live.get("SUPERHUMAN_API_TOKEN", "") or os.environ.get("SUPERHUMAN_API_TOKEN", "")
                sh_parent = _live.get("SUPERHUMAN_PARENT_DIR", "") or os.environ.get("SUPERHUMAN_PARENT_DIR", "")
                if not summary_text:
                    self._wf_update('superhuman', 'error', 'No summary — enable Summarize first')
                elif sh_token:
                    page_title = f"Summary: {path.stem}"
                    self._wf_update('superhuman', 'running', 'Creating page...')
                    self._wf_log(f"Superhuman: creating page '{page_title}'")
                    try:
                        from mindbase_layer.adapters.superhuman import SuperhumanAdapter
                        adapter = SuperhumanAdapter(api_token=sh_token)
                        folder_id = SuperhumanAdapter.resolve_folder_id(sh_parent)
                        result = adapter.push(
                            folder_id=folder_id,
                            title=page_title,
                            content=summary_text,
                        )
                        if result:
                            sh_browser_link = result.get('browserLink', '')
                            if sh_browser_link and not confluence_page_url:
                                confluence_page_url = sh_browser_link
                            self._wf_log(f"Superhuman page created: {result.get('name', page_title)}")
                            sh_links = [{"label": "Open in Superhuman", "path": sh_browser_link, "kind": "url"}] if sh_browser_link else None
                            self._wf_update('superhuman', 'done', f'Page created', links=sh_links)
                        else:
                            self._wf_update('superhuman', 'error', 'Failed to create page')
                    except Exception as e:
                        self._wf_log(f"Superhuman exception: {e}")
                        self._wf_update('superhuman', 'error', str(e))
                else:
                    self._wf_update('superhuman', 'skip', 'Missing: SUPERHUMAN_API_TOKEN')
            else:
                self._wf_update('superhuman', 'skip', 'Disabled')

            if steps.get('slack', True):
                if not confluence_page_url:
                    self._wf_log("Slack: no page URL from Confluence or Superhuman")
                    self._wf_update('slack', 'skip', 'No page URL — enable Confluence or Superhuman first')
                else:
                    slack_message = confluence_page_url
                    webhook_url = _live.get("SLACK_WEBHOOK_URL", "") or os.environ.get("SLACK_WEBHOOK_URL", "")
                    bot_token = _live.get("SLACK_BOT_TOKEN", "") or os.environ.get("SLACK_BOT_TOKEN", "")
                    channel = _live.get("SLACK_CHANNEL", "") or os.environ.get("SLACK_CHANNEL", "")
                    self._wf_log(f"Slack: webhook={'yes' if webhook_url else 'NO'} token={'yes' if bot_token else 'NO'} channel={channel or 'MISSING'}")
                    if webhook_url:
                        self._wf_update('slack', 'running', 'Posting via webhook...')
                        try:
                            import requests
                            resp = requests.post(webhook_url, json={"jira_url": slack_message}, timeout=10)
                            if resp.ok:
                                self._wf_log("Slack webhook posted successfully")
                                self._wf_update('slack', 'done', 'Posted via webhook')
                            else:
                                err = f"HTTP {resp.status_code}: {resp.text[:100]}"
                                self._wf_log(f"Slack webhook error: {err}")
                                self._wf_update('slack', 'error', err)
                        except Exception as e:
                            self._wf_log(f"Slack webhook exception: {e}")
                            self._wf_update('slack', 'error', str(e))
                    elif bot_token and channel:
                        self._wf_update('slack', 'running', f'Posting to #{channel}...')
                        try:
                            from slack_sdk import WebClient
                            from slack_sdk.errors import SlackApiError
                            client = WebClient(token=bot_token)
                            response = client.chat_postMessage(channel=channel, text=slack_message)
                            self._wf_log(f"Slack response: ok={response.get('ok')} ts={response.get('ts')}")
                            if response.get("ok"):
                                self._wf_log(f"Slack posted to #{channel}")
                                self._wf_update('slack', 'done', f'Posted to #{channel}')
                            else:
                                err = response.get("error", "unknown")
                                self._wf_log(f"Slack error: {err}")
                                self._wf_update('slack', 'error', err)
                        except SlackApiError as e:
                            err = e.response.get("error", str(e))
                            self._wf_log(f"Slack API error: {err}")
                            self._wf_update('slack', 'error', err)
                        except Exception as e:
                            self._wf_log(f"Slack exception: {e}")
                            self._wf_update('slack', 'error', str(e))
                    else:
                        missing = []
                        if not bot_token and not webhook_url:
                            missing.append('SLACK_WEBHOOK_URL or SLACK_BOT_TOKEN')
                        if not channel and not webhook_url:
                            missing.append('SLACK_CHANNEL')
                        self._wf_log(f"Slack skipped: missing {missing}")
                        self._wf_update('slack', 'skip', f'Missing: {", ".join(missing)}')
            else:
                self._wf_update('slack', 'skip', 'Disabled')

            import shutil
            if path.parent.name == path.stem:
                out_dir = path.parent
            else:
                out_dir = path.parent / path.stem
                out_dir.mkdir(exist_ok=True)
            artifacts = [summary_path]
            if en_path:
                artifacts.append(en_path)
            if is_text:
                artifacts.append(path)
            else:
                artifacts.extend([text_path, path.with_suffix('.mp3')])
            moved = []
            for artifact in artifacts:
                if artifact.exists() and artifact.parent != out_dir:
                    shutil.move(str(artifact), str(out_dir / artifact.name))
                    moved.append(artifact.name)
            if moved:
                self._wf_log(f"Moved {len(moved)} artifact(s) to {out_dir}: {', '.join(moved)}")

            final_summary = out_dir / summary_path.name
            if final_summary.exists():
                self._wf_update('summarize', 'done', str(final_summary), links=[
                    {"label": f"{language.upper()} summary", "path": str(final_summary), "kind": "file"},
                ])
            if en_path:
                final_en = out_dir / en_path.name
                if final_en.exists():
                    label = "EN summary" if translating_summary else "EN transcript"
                    self._wf_update('translate', 'done', str(final_en), links=[
                        {"label": label, "path": str(final_en), "kind": "file"},
                    ])

            self._wf_log("=== Pipeline done")
            self._wf_update('done', 'done', str(out_dir))
            return str(out_dir)
        except Exception as e:
            self._wf_log(f"=== Pipeline ERROR: {e}")
            self._wf_update('pipeline', 'error', str(e))
            return None
        finally:
            self._window.evaluate_js("wfRunBtn.disabled = false;")

    def get_mascot(self):
        script_dir = Path(os.path.abspath(__file__)).parent
        for base in [script_dir.parent / "assets", script_dir.parent.parent / "assets"]:
            p = base / "maskot2.png"
            if p.exists():
                import base64
                data = base64.b64encode(p.read_bytes()).decode()
                return f"data:image/png;base64,{data}"
        return None

    def open_path(self, file_path):
        p = Path(file_path)
        if not p.exists():
            return False
        subprocess.Popen(["open", "-R", str(p)])
        return True

    def _save_history(self):
        data_dir = os.environ.get("DATA_DIR")
        if data_dir:
            history_path = Path(data_dir) / f"{int(time.time())}_chat_history.jsonl"
            self._message_history.dump_history(history_path)


HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Mindbase</title>
<style>
:root {
    --bg: #f7f7f8;
    --bg-sidebar: #ffffff;
    --bg-user: #e3f2fd;
    --bg-bot: #ffffff;
    --bg-input: #ffffff;
    --bg-modal: #ffffff;
    --overlay: rgba(0,0,0,0.4);
    --text: #1a1a1a;
    --text2: #666;
    --border: #e0e0e0;
    --accent: #2196f3;
    --accent-h: #1976d2;
    --shadow: 0 1px 3px rgba(0,0,0,0.08);
    --r: 12px;
    --font: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    --mono: "SF Mono", Monaco, "Cascadia Code", monospace;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #1e1e1e; --bg-sidebar: #252525; --bg-user: #1a3a5c;
    --bg-bot: #2d2d2d; --bg-input: #2d2d2d; --bg-modal: #333;
    --overlay: rgba(0,0,0,0.6); --text: #e0e0e0; --text2: #999;
    --border: #444; --accent: #64b5f6; --accent-h: #90caf9;
    --shadow: 0 1px 3px rgba(0,0,0,0.3);
  }
}
* { margin:0; padding:0; box-sizing:border-box; }
body { font-family:var(--font); background:var(--bg); color:var(--text);
       height:100vh; display:flex; overflow:hidden; }

#sidebar {
    width:240px; background:var(--bg-sidebar); border-right:1px solid var(--border);
    padding:20px 14px; display:flex; flex-direction:column; gap:16px; flex-shrink:0;
}
#sidebar h2 { font-size:18px; font-weight:600; }
#sidebar label { font-size:13px; color:var(--text2); display:block; margin-bottom:4px; }
#sidebar select {
    width:100%; padding:7px 8px; border:1px solid var(--border); border-radius:8px;
    background:var(--bg-input); color:var(--text); font-size:14px; outline:none;
}

#main { flex:1; display:flex; flex-direction:column; min-width:0; position:relative; }
#mascot-bg { position:absolute; inset:0; display:flex; align-items:center; justify-content:center;
    pointer-events:none; z-index:0; overflow:hidden; }
#mascot-bg img { width:100%; height:100%; object-fit:contain; opacity:0.06; }
#main > *:not(#mascot-bg) { position:relative; z-index:1; }

#header { padding:14px 24px; border-bottom:1px solid var(--border); }
#header p { font-size:13px; color:var(--text2); }

#messages {
    flex:1; overflow-y:auto; padding:16px 24px;
    display:flex; flex-direction:column; gap:12px;
}
.msg {
    max-width:85%; padding:12px 16px; border-radius:var(--r);
    line-height:1.5; font-size:14px; box-shadow:var(--shadow);
    word-wrap:break-word; overflow-wrap:break-word;
}
.msg.user { background:var(--bg-user); align-self:flex-end; border-bottom-right-radius:4px; }
.msg.bot  { background:var(--bg-bot);  align-self:flex-start; border-bottom-left-radius:4px; }
.msg.thinking { background:var(--bg-bot); align-self:flex-start;
                border-bottom-left-radius:4px; color:var(--text2); font-style:italic; }
.msg.thinking .progress-line { font-family:var(--mono); font-size:12px; color:var(--text2);
    font-style:normal; margin-top:6px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.msg.thinking .progress-bar-wrap { margin-top:8px; background:var(--border); border-radius:4px;
    height:6px; overflow:hidden; max-width:300px; }
.msg.thinking .progress-bar-fill { height:100%; background:var(--accent); border-radius:4px;
    transition:width .2s ease; }
.msg.thinking .progress-label { font-size:12px; color:var(--accent); font-style:normal; margin-top:4px; font-weight:500; }
.msg h1,.msg h2,.msg h3 { margin:8px 0 4px; }
.msg h1 { font-size:16px; } .msg h2 { font-size:15px; } .msg h3 { font-size:14px; }
.msg p { margin:4px 0; }
.msg pre {
    background:#1e1e1e; color:#d4d4d4; padding:10px 12px; border-radius:8px;
    overflow-x:auto; margin:8px 0; font-family:var(--mono); font-size:13px; line-height:1.4;
}
.msg code { background:rgba(0,0,0,0.08); padding:2px 5px; border-radius:4px;
            font-family:var(--mono); font-size:13px; }
.msg pre code { background:none; padding:0; }
.msg ul,.msg ol { padding-left:20px; margin:4px 0; }
.msg li { margin:2px 0; }
.msg a { color:var(--accent); text-decoration:none; }
.msg a:hover { text-decoration:underline; }
.msg a.fpath { cursor:pointer; text-decoration:underline; text-decoration-style:dotted; }
.msg a.fpath:hover { text-decoration-style:solid; }

.dots::after { content:''; animation:dots 1.5s steps(4,end) infinite; }
@keyframes dots { 0%{content:''} 25%{content:'.'} 50%{content:'..'} 75%{content:'...'} }

#input-area {
    padding:12px 24px 16px; border-top:1px solid var(--border);
    display:flex; gap:8px; align-items:flex-end;
}
#input-area button {
    border:none; background:none; cursor:pointer; font-size:20px;
    padding:8px; border-radius:8px; color:var(--text2); transition:background .15s;
    margin-bottom:4px;
}
#input-area button:hover { background:var(--border); }
#msg-input {
    flex:1; padding:12px 14px; border:1px solid var(--border); border-radius:10px;
    background:var(--bg-input); color:var(--text); font-size:14px;
    font-family:var(--font); outline:none; transition:border-color .15s;
    min-height:112px; max-height:240px; resize:none; overflow-y:auto;
    line-height:1.5;
}
#msg-input:focus { border-color:var(--accent); }
#send-btn { background:var(--accent)!important; color:#fff!important;
            font-size:14px!important; padding:8px 16px!important; font-weight:500; }
#send-btn:hover { background:var(--accent-h)!important; }
#send-btn:disabled { opacity:.5; cursor:not-allowed; }

#modal-overlay {
    position:fixed; inset:0; background:var(--overlay);
    display:flex; align-items:center; justify-content:center; z-index:100;
}
#modal-overlay.hidden { display:none; }
#modal { background:var(--bg-modal); border-radius:var(--r); padding:24px;
         width:360px; box-shadow:0 8px 32px rgba(0,0,0,0.2); }
#modal h3 { font-size:16px; margin-bottom:12px; }
#modal-fn { font-size:13px; color:var(--text2); margin-bottom:16px; }
.ml { display:flex; flex-direction:column; gap:8px; margin-bottom:20px; }
.ml label { display:flex; align-items:center; gap:8px; font-size:14px;
            cursor:pointer; padding:6px 8px; border-radius:6px; transition:background .15s; }
.ml label:hover { background:var(--border); }
.ma { display:flex; gap:8px; justify-content:flex-end; }
.ma button { padding:8px 16px; border-radius:8px; border:1px solid var(--border);
             background:var(--bg-input); color:var(--text); font-size:14px;
             cursor:pointer; transition:all .15s; }
.ma button.pr { background:var(--accent); color:#fff; border-color:var(--accent); }
.ma button.pr:hover { background:var(--accent-h); }
.ma button.pr:disabled { opacity:.5; cursor:not-allowed; }

.tabs { display:flex; flex-direction:column; gap:2px; margin-bottom:12px; }
.tab-btn {
    padding:8px 10px; border:none; background:none; color:var(--text2);
    font-size:13px; font-weight:500; cursor:pointer; border-left:3px solid transparent;
    transition: color .15s, border-color .15s, background .15s; font-family:var(--font);
    text-align:left; border-radius:0 6px 6px 0;
}
.tab-btn.active { color:var(--accent); border-left-color:var(--accent); background:rgba(99,102,241,.08); }
.tab-btn:hover { color:var(--text); background:rgba(99,102,241,.05); }
.tab-panel { display:none; flex-direction:column; gap:12px; flex:1; }
.tab-panel.active { display:flex; }
.s-field { display:flex; flex-direction:column; gap:4px; }
.s-field label { font-size:12px; color:var(--text2); }
.s-field input {
    width:100%; padding:7px 8px; border:1px solid var(--border); border-radius:8px;
    background:var(--bg-input); color:var(--text); font-size:13px; font-family:var(--mono);
    outline:none; transition:border-color .15s;
}
.s-field input:focus, .s-field textarea:focus { border-color:var(--accent); }
#save-btn {
    padding:8px 16px; border-radius:8px; border:none;
    background:var(--accent); color:#fff; font-size:13px; font-weight:500;
    cursor:pointer; transition:background .15s; align-self:flex-start;
}
#save-btn:hover { background:var(--accent-h); }
#save-msg { font-size:12px; color:var(--accent); min-height:16px; }

#workflow-view { flex:1; display:none; flex-direction:column; padding:24px; gap:16px;
    max-width:680px; margin:0 auto; width:100%; }
#workflow-view.active { display:flex; }
#settings-view { flex:1; display:none; flex-direction:column; padding:24px; gap:16px; overflow-y:auto; }
#settings-view.active { display:flex; }
#settings-view h2 { font-size:18px; font-weight:600; margin:0 0 8px; }
.settings-grid { display:grid; grid-template-columns:1fr 1fr; gap:12px 24px; max-width:700px; }
.settings-grid .s-field label { font-size:13px; color:var(--text2); display:block; margin-bottom:4px; }
.settings-grid .s-field input {
    width:100%; padding:8px 10px; border:1px solid var(--border); border-radius:8px;
    background:var(--bg-input); color:var(--text); font-size:14px; font-family:var(--mono); outline:none;
    box-sizing:border-box;
}
.settings-grid .s-field input:focus { border-color:var(--accent); }
.hint { display:inline-flex; align-items:center; justify-content:center;
    width:15px; height:15px; border-radius:50%; background:var(--border); color:var(--text2);
    font-size:10px; font-weight:600; cursor:help; margin-left:4px; position:relative; font-style:normal; }
.hint:hover::after { content:attr(data-tip); position:absolute; left:calc(100% + 6px); top:50%;
    transform:translateY(-50%); background:var(--bg); color:var(--text); border:1px solid var(--border);
    border-radius:6px; padding:6px 10px; font-size:12px; font-weight:400; white-space:nowrap;
    box-shadow:0 2px 8px rgba(0,0,0,.15); z-index:10; }
.wf-steps { display:flex; flex-direction:column; gap:16px; }
.wf-group { background:var(--bg-bot); border-radius:var(--r); box-shadow:var(--shadow); overflow:hidden; }
.wf-links { display:flex; flex-wrap:wrap; gap:6px 14px; margin-top:-8px; padding:0 4px; }
.wf-links a { font-size:12px; color:var(--accent); text-decoration:none; cursor:pointer; }
.wf-links a:hover { text-decoration:underline; }
.wf-group-header { font-size:11px; text-transform:uppercase; letter-spacing:0.5px;
    color:var(--text2); padding:10px 14px 4px; font-weight:600; }
.wf-step {
    display:flex; flex-wrap:wrap; align-items:center; gap:6px 10px; padding:10px 14px;
    font-size:14px;
}
.wf-step + .wf-step { border-top:1px solid var(--border); }
.wf-row-label { display:flex; align-items:center; gap:8px; cursor:pointer; font-size:14px;
    min-height:28px; }
.wf-check { width:16px; height:16px; cursor:pointer; flex-shrink:0; accent-color:var(--accent); }
.wf-check:disabled { cursor:not-allowed; opacity:0.4; }
.wf-step.dep-disabled { opacity:0.5; }
.wf-step.dep-disabled .wf-row-label { cursor:default; }
.wf-dot {
    width:8px; height:8px; border-radius:50%; flex-shrink:0; margin-left:auto;
    background:var(--border); transition:background .2s;
}
.wf-step.running .wf-dot { background:var(--accent); animation:pulse 1s infinite; }
.wf-step.done .wf-dot { background:#4caf50; }
.wf-step.error .wf-dot { background:#e53935; }
.wf-step.skip .wf-dot { background:var(--border); }
.wf-step .wf-detail { font-size:12px; color:var(--text2); max-width:50%; text-align:right;
    overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.wf-hint { font-size:12px; color:var(--text2); font-style:italic; }
.wf-params { width:100%; padding:2px 0 4px 34px; display:flex; align-items:center; gap:8px; }
.wf-params label { font-size:12px; color:var(--text2); display:flex; align-items:center; gap:6px; cursor:pointer; }
.wf-params select, .wf-params input[type="text"] {
    padding:4px 6px; border:1px solid var(--border); border-radius:6px;
    background:var(--bg-input); color:var(--text); font-size:12px;
}
.wf-params input[type="text"] { width:180px; }
.wf-step.dep-disabled .wf-params { opacity:0.45; pointer-events:none; }
.wf-edit-prompt { background:none; border:none; color:var(--text2); font-size:11px;
    cursor:pointer; padding:2px 6px; border-radius:4px; font-family:var(--font); }
.wf-edit-prompt:hover { background:var(--border); color:var(--text); }
#prompt-modal-overlay {
    position:fixed; inset:0; background:var(--overlay);
    display:flex; align-items:center; justify-content:center; z-index:100;
}
#prompt-modal-overlay.hidden { display:none; }
#prompt-modal { background:var(--bg-modal); border-radius:var(--r); padding:24px;
    width:560px; max-height:80vh; display:flex; flex-direction:column;
    box-shadow:0 8px 32px rgba(0,0,0,0.2); }
#prompt-modal h3 { font-size:15px; margin:0 0 12px; }
#prompt-modal textarea {
    flex:1; width:100%; min-height:200px; padding:8px 10px; border:1px solid var(--border);
    border-radius:6px; background:var(--bg-input); color:var(--text); font-size:12px;
    font-family:var(--mono); resize:vertical; box-sizing:border-box; outline:none;
}
#prompt-modal textarea:focus { border-color:var(--accent); }
#prompt-modal .ma { margin-top:12px; }
:focus-visible { outline:2px solid var(--accent); outline-offset:2px; }
@keyframes pulse { 0%,100%{opacity:1} 50%{opacity:.4} }

#wf-log {
    flex:1; overflow-y:auto; padding:12px; border-radius:var(--r);
    background:var(--bg-bot); box-shadow:var(--shadow); font-family:var(--mono);
    font-size:12px; color:var(--text2); min-height:100px;
    display:flex; flex-direction:column; align-items:center; justify-content:center;
}
#wf-log div { padding:2px 0; }
#wf-log.has-output { display:block; align-items:normal; justify-content:normal; }
.wf-log-placeholder {
    font-family:var(--font); font-style:italic; text-align:center; opacity:.7;
}

#wf-dropzone {
    position:relative;
    border:2px dashed var(--border); border-radius:var(--r); padding:32px 24px;
    display:flex; flex-direction:column; align-items:center; justify-content:center;
    gap:6px; cursor:pointer; transition:border-color .2s, background .2s;
    min-height:140px;
}
#wf-dropzone:hover, #wf-dropzone.drag-over {
    border-color:var(--accent); background:rgba(33,150,243,0.04);
}
#wf-dropzone.has-file { border-style:solid; border-color:var(--accent); }
#wf-clear-btn {
    display:none; position:absolute; top:8px; right:8px; width:22px; height:22px;
    border-radius:50%; border:none; background:#e53935; color:#fff;
    font-size:15px; line-height:1; cursor:pointer; align-items:center; justify-content:center;
    transition:background .15s, color .15s;
}
#wf-dropzone.has-file #wf-clear-btn { display:flex; }
#wf-clear-btn:hover { background:#c62828; }
.wf-drop-icon { font-size:36px; opacity:.5; line-height:1; }
.wf-drop-title { font-size:14px; color:var(--text); font-weight:500; }
.wf-drop-sub { font-size:12px; color:var(--text2); }
#wf-filename { font-size:13px; color:var(--accent); font-weight:500; margin-top:4px;
    max-width:100%; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
#wf-run-btn {
    width:100%; padding:8px 12px; border-radius:8px; border:none;
    background:var(--accent); color:#fff; font-size:13px; font-weight:500;
    cursor:pointer; transition:background .15s; font-family:var(--font);
}
#wf-run-btn:hover { background:var(--accent-h); }
#wf-run-btn:disabled { opacity:.5; cursor:not-allowed; }
</style>
</head>
<body>

<div id="sidebar">
    <h2>Mindbase</h2>
    <div class="tabs">
        <button class="tab-btn active" data-tab="chat">Chat</button>
        <button class="tab-btn" data-tab="workflow">Workflow</button>
        <button class="tab-btn" data-tab="settings">Settings</button>
    </div>

    <div id="tab-chat" class="tab-panel active">
        <div id="usage" style="margin-top:auto; font-size:12px; color:var(--text2); line-height:1.6;">
            <div style="font-size:11px; text-transform:uppercase; letter-spacing:0.5px; margin-bottom:4px; opacity:0.7;">Session tokens</div>
            <div>In: <span id="u-in">0</span></div>
            <div>Out: <span id="u-out">0</span></div>
            <div style="border-top:1px solid var(--border); margin-top:4px; padding-top:4px; font-weight:500;">
                Total: <span id="u-total">0</span>
            </div>
        </div>
    </div>

    <div id="tab-workflow" class="tab-panel">
        <div id="wf-usage" style="margin-top:auto; font-size:12px; color:var(--text2); line-height:1.6;">
            <div style="font-size:11px; text-transform:uppercase; letter-spacing:0.5px; margin-bottom:4px; opacity:0.7;">Session tokens</div>
            <div>In: <span id="wf-in">0</span></div>
            <div>Out: <span id="wf-out">0</span></div>
            <div style="border-top:1px solid var(--border); margin-top:4px; padding-top:4px; font-weight:500;">
                Total: <span id="wf-tkn">0</span>
            </div>
        </div>
    </div>

    <div id="tab-settings" class="tab-panel"></div>
</div>

<div id="main">
    <div id="mascot-bg"></div>
    <div id="chat-view" style="display:flex; flex-direction:column; flex:1; min-height:0;">
        <div id="header"><p>Type a message or attach a file to get started.</p></div>
        <div id="messages"></div>
        <div id="input-area">
            <button id="attach-btn" title="Attach file">&#x1F4CE;</button>
            <textarea id="msg-input" placeholder="Type a message..." rows="4" autocomplete="off"></textarea>
            <button id="send-btn">Send</button>
        </div>
    </div>
    <div id="workflow-view">
        <div id="wf-dropzone">
            <button id="wf-clear-btn" title="Clear selection" type="button">&times;</button>
            <div class="wf-drop-icon">&#x1F3AC;</div>
            <div class="wf-drop-title">Click to select a file, or paste text</div>
            <div class="wf-drop-sub">.mp4, .m4a, .mp3, .mov, .webm, .txt, .md, .srt &middot; or paste plaintext directly</div>
            <div id="wf-filename"></div>
        </div>
        <div class="wf-steps">
            <div class="wf-group">
                <div class="wf-group-header">Process</div>
                <div class="wf-step" id="wf-transcribe">
                    <label class="wf-row-label"><input type="checkbox" class="wf-check" data-step="transcribe" checked><span>Transcribe</span></label>
                    <span class="wf-dot"></span>
                    <span class="wf-detail"></span>
                    <div class="wf-params">
                        <label>Source language
                            <select id="wf-lang">
                                <option value="en">English</option>
                                <option value="ru" selected>Russian</option>
                                <option value="sr">Serbian</option>
                            </select>
                        </label>
                    </div>
                </div>
                <div class="wf-step" id="wf-summarize">
                    <label class="wf-row-label"><input type="checkbox" class="wf-check" data-step="summarize" checked><span>Summarize</span></label>
                    <button class="wf-edit-prompt" data-prompt="summary" title="Edit summarization prompt">edit prompt</button>
                    <span class="wf-dot"></span>
                    <span class="wf-detail"></span>
                </div>
                <div class="wf-step" id="wf-translate">
                    <label class="wf-row-label"><input type="checkbox" class="wf-check" data-step="translate" checked><span>Translate to English</span></label>
                    <button class="wf-edit-prompt" data-prompt="translation" title="Edit translation prompt">edit prompt</button>
                    <span class="wf-dot"></span>
                    <span class="wf-detail"></span>
                </div>
            </div>
            <div id="wf-process-links" class="wf-links"></div>
            <div class="wf-group">
                <div class="wf-group-header">Deliver to</div>
                <div class="wf-step" id="wf-confluence">
                    <label class="wf-row-label"><input type="checkbox" class="wf-check" data-step="confluence"><span>Confluence</span></label>
                    <span class="wf-dot"></span>
                    <span class="wf-detail"></span>
                    <div class="wf-params">
                        <label>Parent page
                            <input type="text" id="wf-conf-parent" placeholder="https://...">
                        </label>
                    </div>
                </div>
                <div class="wf-step" id="wf-superhuman">
                    <label class="wf-row-label"><input type="checkbox" class="wf-check" data-step="superhuman"><span>Superhuman</span></label>
                    <span class="wf-dot"></span>
                    <span class="wf-detail"></span>
                    <div class="wf-params">
                        <label>Destination folder
                            <input type="text" id="wf-sh-parent" placeholder="fl-...">
                        </label>
                    </div>
                </div>
                <div class="wf-step dep-disabled" id="wf-slack">
                    <label class="wf-row-label"><input type="checkbox" class="wf-check" data-step="slack" disabled><span>Slack</span></label>
                    <span class="wf-hint" id="wf-slack-hint">Not connected</span>
                    <span class="wf-dot"></span>
                    <span class="wf-detail"></span>
                </div>
            </div>
            <div id="wf-deliver-links" class="wf-links"></div>
        </div>
        <button id="wf-run-btn" disabled>Run pipeline</button>
        <div id="wf-log"><div class="wf-log-placeholder">Output will appear here once you run the pipeline.</div></div>
    </div>
    <div id="settings-view">
        <h2>Settings</h2>
        <h3 style="margin:0 0 8px; font-size:14px; color:var(--text2); text-transform:uppercase; letter-spacing:0.5px;">LLM Connection</h3>
        <div class="settings-grid">
            <div class="s-field">
                <label for="s-model">Model <i class="hint" data-tip="LLM model name. Default: Qwen/Qwen3-32B (Nebius). Use gemini-2.5-flash for Google Gemini">?</i></label>
                <input type="text" id="s-model" placeholder="Qwen/Qwen3-32B">
            </div>
            <div class="s-field">
                <label for="s-nebius">NEBIUS_API_KEY <i class="hint" data-tip="API key from Nebius AI Studio console">?</i></label>
                <input type="password" id="s-nebius" placeholder="Enter key...">
            </div>
            <div class="s-field">
                <label for="s-google-creds">GOOGLE_CREDENTIALS <i class="hint" data-tip="Path to Google service account JSON file for Vertex AI / Gemini">?</i></label>
                <input type="text" id="s-google-creds" placeholder="/path/to/service-account.json">
            </div>
        </div>
        <h3 style="margin:24px 0 8px; font-size:14px; color:var(--text2); text-transform:uppercase; letter-spacing:0.5px;">Upstream Connections</h3>
        <div class="settings-grid">
            <div class="s-field">
                <label for="s-slack-webhook">SLACK_WEBHOOK_URL <i class="hint" data-tip="Incoming Webhook URL — if set, used instead of bot token">?</i></label>
                <input type="password" id="s-slack-webhook" placeholder="https://hooks.slack.com/services/...">
            </div>
            <div class="s-field">
                <label for="s-slack-bot">SLACK_BOT_TOKEN <i class="hint" data-tip="Bot token from Slack App settings (xoxb-...). Used only if webhook is not set">?</i></label>
                <input type="password" id="s-slack-bot" placeholder="xoxb-...">
            </div>
            <div class="s-field">
                <label for="s-slack-channel">SLACK_CHANNEL <i class="hint" data-tip="Slack channel name without # prefix">?</i></label>
                <input type="text" id="s-slack-channel" placeholder="#general">
            </div>
            <div class="s-field">
                <label for="s-conf-email">CONFLUENCE_USEREMAIL <i class="hint" data-tip="Email of the Atlassian account used for API auth">?</i></label>
                <input type="text" id="s-conf-email" placeholder="you@company.com">
            </div>
            <div class="s-field">
                <label for="s-conf-token">CONFLUENCE_TOKEN <i class="hint" data-tip="API token from id.atlassian.com/manage-profile/security">?</i></label>
                <input type="password" id="s-conf-token" placeholder="API token">
            </div>
            <div class="s-field">
                <label for="s-conf-parent">CONFLUENCE_PARENT_URL <i class="hint" data-tip="Confluence parent page URL — new pages are created as children of this page">?</i></label>
                <input type="text" id="s-conf-parent" placeholder="https://your-org.atlassian.net/wiki/spaces/ENG/pages/123456">
            </div>
            <div class="s-field">
                <label for="s-jira-base">JIRA_BASE_URL <i class="hint" data-tip="Jira base URL for building ticket links, e.g. https://your-org.atlassian.net">?</i></label>
                <input type="text" id="s-jira-base" placeholder="https://your-org.atlassian.net">
            </div>
            <div class="s-field">
                <label for="s-sh-token">SUPERHUMAN_API_TOKEN <i class="hint" data-tip="API token from coda.io/account (bearer auth)">?</i></label>
                <input type="password" id="s-sh-token" placeholder="API token">
            </div>
            <div class="s-field">
                <label for="s-sh-parent">SUPERHUMAN_PARENT_DIR <i class="hint" data-tip="Folder URL or ID (e.g. https://docs.superhuman.com/folders/fl-...)">?</i></label>
                <input type="text" id="s-sh-parent" placeholder="page-id">
            </div>
        </div>
        <h3 style="margin:24px 0 8px; font-size:14px; color:var(--text2); text-transform:uppercase; letter-spacing:0.5px;">Prompts</h3>
        <div style="display:flex; flex-direction:column; gap:12px; max-width:700px;">
            <div class="s-field">
                <label for="s-prompt-summary">Summarization prompt</label>
                <textarea id="s-prompt-summary" rows="8" style="width:100%; padding:8px 10px; border:1px solid var(--border);
                    border-radius:8px; background:var(--bg-input); color:var(--text); font-size:13px;
                    font-family:var(--mono); resize:vertical; box-sizing:border-box; outline:none;"></textarea>
            </div>
            <div class="s-field">
                <label for="s-prompt-translation">Translation prompt</label>
                <textarea id="s-prompt-translation" rows="6" style="width:100%; padding:8px 10px; border:1px solid var(--border);
                    border-radius:8px; background:var(--bg-input); color:var(--text); font-size:13px;
                    font-family:var(--mono); resize:vertical; box-sizing:border-box; outline:none;"></textarea>
            </div>
        </div>
        <div style="margin-top:16px; display:flex; align-items:center; gap:12px;">
            <button id="save-btn">Save</button>
            <span id="save-msg"></span>
        </div>
    </div>
</div>

<div id="modal-overlay" class="hidden">
    <div id="modal">
        <h3>Select the language spoken in the recording</h3>
        <p id="modal-fn"></p>
        <div class="ml">
            <label><input type="radio" name="ml" value="en"> English</label>
            <label><input type="radio" name="ml" value="ru"> Russian</label>
            <label><input type="radio" name="ml" value="sr"> Serbian</label>
        </div>
        <div class="ma">
            <button id="m-cancel">Cancel</button>
            <button id="m-ok" class="pr" disabled>Process</button>
        </div>
    </div>
</div>

<div id="prompt-modal-overlay" class="hidden">
    <div id="prompt-modal">
        <h3 id="prompt-modal-title">Edit prompt</h3>
        <textarea id="prompt-modal-text"></textarea>
        <div class="ma">
            <button id="pm-cancel">Cancel</button>
            <button id="pm-save" class="pr">Save</button>
        </div>
    </div>
</div>

<script>
const msgsEl  = document.getElementById('messages');
const inp     = document.getElementById('msg-input');
const sendBtn = document.getElementById('send-btn');
const overlay = document.getElementById('modal-overlay');
const mFn     = document.getElementById('modal-fn');
const mOk     = document.getElementById('m-ok');
const mCancel = document.getElementById('m-cancel');

let busy = false, pendingPath = null;

function fmt(n) {
    if (n >= 1e6) return (n/1e6).toFixed(1) + 'M';
    if (n >= 1e3) return (n/1e3).toFixed(1) + 'K';
    return n.toString();
}
async function refreshUsage() {
    try {
        const u = await pywebview.api.get_usage();
        document.getElementById('u-in').textContent = fmt(u.input);
        document.getElementById('u-out').textContent = fmt(u.output);
        document.getElementById('u-total').textContent = fmt(u.total);
        document.getElementById('wf-in').textContent = fmt(u.input);
        document.getElementById('wf-out').textContent = fmt(u.output);
        document.getElementById('wf-tkn').textContent = fmt(u.total);
    } catch(_) {}
}

function md(text) {
    let h = text.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
    h = h.replace(/```\w*\n([\s\S]*?)```/g, (_, c) => '<pre><code>' + c.trimEnd() + '</code></pre>');
    h = h.replace(/`([^`\n]+)`/g, '<code>$1</code>');
    h = h.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
    h = h.replace(/^### (.+)$/gm, '<h3>$1</h3>');
    h = h.replace(/^## (.+)$/gm, '<h2>$1</h2>');
    h = h.replace(/^# (.+)$/gm, '<h1>$1</h1>');
    h = h.replace(/^[*\-] (.+)$/gm, '<li>$1</li>');
    h = h.replace(/^\d+\. (.+)$/gm, '<li>$1</li>');
    h = h.replace(/((?:<li>[^]*?<\/li>\n?)+)/g, '<ul>$1</ul>');
    h = h.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank">$1</a>');
    h = h.replace(/(\/[\w./@~:-]*\/[\w.\/À-ɏЀ-ӿ«»—:;,()\[\]{}|' @~#!+-]+)/g,
        (_, p) => '<a class="fpath" data-path="' + p.replace(/&amp;/g,'&') + '">' + p + '</a>');
    return h.split(/\n{2,}/).map(b => {
        b = b.trim();
        if (!b) return '';
        if (/^<(h[1-6]|pre|ul|ol)/.test(b)) return b;
        return '<p>' + b.replace(/\n/g, '<br>') + '</p>';
    }).join('\n');
}

function addMsg(role, html) {
    const d = document.createElement('div');
    d.className = 'msg ' + role;
    d.innerHTML = html;
    msgsEl.appendChild(d);
    msgsEl.scrollTop = msgsEl.scrollHeight;
    return d;
}

function updateProgress(line) {
    const t = document.querySelector('.msg.thinking');
    if (!t) return;
    const pctMatch = line.match(/([\d.]+)%/);
    if (pctMatch) {
        const pct = parseFloat(pctMatch[1]);
        let wrap = t.querySelector('.progress-bar-wrap');
        if (!wrap) {
            let lbl = t.querySelector('.progress-label');
            if (!lbl) { lbl = document.createElement('div'); lbl.className = 'progress-label'; t.appendChild(lbl); }
            lbl.textContent = 'Downloading...';
            wrap = document.createElement('div'); wrap.className = 'progress-bar-wrap';
            const fill = document.createElement('div'); fill.className = 'progress-bar-fill';
            wrap.appendChild(fill); t.appendChild(wrap);
        }
        wrap.querySelector('.progress-bar-fill').style.width = pct + '%';
        const lbl = t.querySelector('.progress-label');
        if (lbl) lbl.textContent = 'Downloading... ' + pct + '%';
    } else {
        let wrap = t.querySelector('.progress-bar-wrap');
        let lbl = t.querySelector('.progress-label');
        if (wrap) { wrap.remove(); }
        if (lbl) { lbl.remove(); }
        let pl = t.querySelector('.progress-line');
        if (!pl) { pl = document.createElement('div'); pl.className = 'progress-line'; t.appendChild(pl); }
        pl.textContent = line;
    }
    msgsEl.scrollTop = msgsEl.scrollHeight;
}

function setLock(locked) {
    busy = locked;
    inp.disabled = locked;
    sendBtn.disabled = locked;
}

async function send() {
    const text = inp.value.trim();
    if (!text || busy) return;
    addMsg('user', md(text));
    inp.value = '';
    inp.style.height = 'auto';
    setLock(true);
    const t = addMsg('thinking', 'Thinking<span class="dots"></span>');
    try {
        const r = await pywebview.api.send_message(text);
        t.remove();
        addMsg('bot', md(r));
        await refreshUsage();
    } catch (e) {
        t.remove();
        addMsg('bot', '<p style="color:#e53935">Error: ' + e + '</p>');
    }
    setLock(false);
    inp.focus();
}

async function upload() {
    if (busy) return;
    const fp = await pywebview.api.pick_file();
    if (!fp) return;
    const name = fp.split('/').pop();
    const ft = await pywebview.api.get_file_type(fp);
    if (ft === 'video') {
        pendingPath = fp;
        mFn.textContent = name;
        document.querySelectorAll('input[name="ml"]').forEach(r => r.checked = false);
        mOk.disabled = true;
        overlay.classList.remove('hidden');
        return;
    }
    addMsg('user', '📎 ' + name);
    setLock(true);
    const t = addMsg('thinking', 'Processing<span class="dots"></span>');
    try {
        const r = await pywebview.api.process_file(fp);
        t.remove();
        addMsg('bot', md(r));
        await refreshUsage();
    } catch (e) {
        t.remove();
        addMsg('bot', '<p style="color:#e53935">Error: ' + e + '</p>');
    }
    setLock(false);
    inp.focus();
}

document.querySelectorAll('input[name="ml"]').forEach(r =>
    r.addEventListener('change', () => { mOk.disabled = false; }));

mCancel.addEventListener('click', () => {
    overlay.classList.add('hidden'); pendingPath = null;
});

mOk.addEventListener('click', async () => {
    const lang = document.querySelector('input[name="ml"]:checked');
    if (!lang || !pendingPath) return;
    const fp = pendingPath, name = fp.split('/').pop();
    pendingPath = null;
    overlay.classList.add('hidden');
    addMsg('user', '📎 ' + name + ' (' + lang.value + ')');
    setLock(true);
    const t = addMsg('thinking', 'Processing<span class="dots"></span>');
    try {
        const r = await pywebview.api.process_file(fp, lang.value);
        t.remove();
        addMsg('bot', md(r));
        await refreshUsage();
    } catch (e) {
        t.remove();
        addMsg('bot', '<p style="color:#e53935">Error: ' + e + '</p>');
    }
    setLock(false);
    inp.focus();
});

msgsEl.addEventListener('click', e => {
    const a = e.target.closest('.fpath');
    if (a) { e.preventDefault(); pywebview.api.open_path(a.dataset.path); }
});
sendBtn.addEventListener('click', send);
document.getElementById('attach-btn').addEventListener('click', upload);
inp.addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); }
});
inp.addEventListener('input', () => {
    inp.style.height = 'auto';
    inp.style.height = Math.min(inp.scrollHeight, 160) + 'px';
});
document.addEventListener('keydown', e => {
    if (e.key === 'Escape' && !overlay.classList.contains('hidden')) {
        overlay.classList.add('hidden'); pendingPath = null;
    }
});

document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.addEventListener('click', () => {
        document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
        document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
        btn.classList.add('active');
        document.getElementById('tab-' + btn.dataset.tab).classList.add('active');
        const cv = document.getElementById('chat-view');
        const wv = document.getElementById('workflow-view');
        const sv = document.getElementById('settings-view');
        cv.style.display = 'none';
        wv.classList.remove('active');
        sv.classList.remove('active');
        if (btn.dataset.tab === 'chat') {
            cv.style.display = 'flex';
        } else if (btn.dataset.tab === 'workflow') {
            wv.classList.add('active');
        } else if (btn.dataset.tab === 'settings') {
            sv.classList.add('active');
            loadSettings();
        }
    });
});

async function loadSettings() {
    try {
        const s = await pywebview.api.get_settings();
        document.getElementById('s-model').value = s.model_name || '';
        document.getElementById('s-nebius').value = s.nebius_api_key || '';
        document.getElementById('s-slack-webhook').value = s.slack_webhook_url || '';
        document.getElementById('s-slack-bot').value = s.slack_bot_token || '';
        document.getElementById('s-slack-channel').value = s.slack_channel || '';
        document.getElementById('s-conf-email').value = s.confluence_useremail || '';
        document.getElementById('s-conf-token').value = s.confluence_token || '';
        document.getElementById('s-conf-parent').value = s.confluence_parent_url || '';
        document.getElementById('s-jira-base').value = s.jira_base_url || '';
        document.getElementById('s-google-creds').value = s.google_creds_path || '';
        document.getElementById('s-sh-token').value = s.superhuman_api_token || '';
        document.getElementById('s-sh-parent').value = s.superhuman_parent_dir || '';
        document.getElementById('wf-conf-parent').value = s.confluence_parent_url || '';
        document.getElementById('wf-sh-parent').value = s.superhuman_parent_dir || '';
        syncWorkflowVisibility(s);
        const p = await pywebview.api.get_prompts();
        document.getElementById('s-prompt-summary').value = p.summarize || '';
        document.getElementById('s-prompt-translation').value = p.translation || '';
        if (window._prompts) {
            window._prompts.summary = p.summarize || '';
            window._prompts.translation = p.translation || '';
        }
    } catch(_) {}
}

function syncWorkflowVisibility(s) {
    const confStep = document.getElementById('wf-confluence');
    const shStep = document.getElementById('wf-superhuman');
    const slackStep = document.getElementById('wf-slack');
    const hint = document.getElementById('wf-slack-hint');
    const hasConf = !!(s.confluence_parent_url);
    const hasSh = !!(s.superhuman_api_token);
    const hasSlack = !!(s.slack_webhook_url || s.slack_bot_token);
    confStep.style.display = hasConf ? '' : 'none';
    shStep.style.display = hasSh ? '' : 'none';
    if (!hasConf) confStep.querySelector('.wf-check').checked = false;
    if (!hasSh) shStep.querySelector('.wf-check').checked = false;
    if (!hasSlack) {
        slackStep.style.display = 'none';
    } else {
        slackStep.style.display = '';
    }
    syncSlackDep();
}

document.getElementById('save-btn').addEventListener('click', async () => {
    const model = document.getElementById('s-model').value.trim();
    const nebius = document.getElementById('s-nebius').value.trim();
    const slackWebhook = document.getElementById('s-slack-webhook').value.trim();
    const slackBot = document.getElementById('s-slack-bot').value.trim();
    const slackChannel = document.getElementById('s-slack-channel').value.trim();
    const confEmail = document.getElementById('s-conf-email').value.trim();
    const confToken = document.getElementById('s-conf-token').value.trim();
    const confParent = document.getElementById('s-conf-parent').value.trim();
    const jiraBase = document.getElementById('s-jira-base').value.trim();
    const googleCreds = document.getElementById('s-google-creds').value.trim();
    const shToken = document.getElementById('s-sh-token').value.trim();
    const shParent = document.getElementById('s-sh-parent').value.trim();
    const promptSummary = document.getElementById('s-prompt-summary').value;
    const promptTranslation = document.getElementById('s-prompt-translation').value;
    const msg = document.getElementById('save-msg');
    try {
        await pywebview.api.save_settings(nebius, slackWebhook, slackBot, slackChannel, model, confEmail, confToken, googleCreds, shToken, shParent, confParent, jiraBase);
        await pywebview.api.save_prompts(promptSummary, promptTranslation);
        if (window._prompts) {
            window._prompts.summary = promptSummary;
            window._prompts.translation = promptTranslation;
        }
        msg.style.color = 'var(--accent)';
        msg.textContent = 'Saved.';
        syncWorkflowVisibility({confluence_parent_url: confParent, superhuman_api_token: shToken, slack_webhook_url: slackWebhook, slack_bot_token: slackBot});
    } catch(e) {
        msg.style.color = '#e53935';
        msg.textContent = 'Error: ' + e;
    }
    setTimeout(() => { msg.textContent = ''; }, 4000);
});

let wfVideoPath = null;
const wfRunBtn = document.getElementById('wf-run-btn');
const wfDrop = document.getElementById('wf-dropzone');

const _TEXT_EXTS = ['.txt', '.md', '.srt'];
const _WF_DROP_TITLE = 'Click to select a file, or paste text';
const _WF_DROP_SUB = '.mp4, .m4a, .mp3, .mov, .webm, .txt, .md, .srt · or paste plaintext directly';

function wfClearFile() {
    wfVideoPath = null;
    document.getElementById('wf-filename').textContent = '';
    wfDrop.classList.remove('has-file');
    wfDrop.querySelector('.wf-drop-title').textContent = _WF_DROP_TITLE;
    wfDrop.querySelector('.wf-drop-sub').textContent = _WF_DROP_SUB;
    wfRunBtn.disabled = true;
    const trCheck = document.querySelector('.wf-check[data-step="transcribe"]');
    const trStep = document.getElementById('wf-transcribe');
    trCheck.disabled = false;
    trCheck.checked = true;
    trStep.classList.remove('dep-disabled');
    const det = trStep.querySelector('.wf-detail');
    if (det) det.textContent = '';
    syncSummarizeDep();
}

document.getElementById('wf-clear-btn').addEventListener('click', e => {
    e.stopPropagation();
    wfClearFile();
});

function wfSetFile(fp) {
    wfVideoPath = fp;
    const name = fp.split('/').pop();
    document.getElementById('wf-filename').textContent = name;
    wfDrop.classList.add('has-file');
    wfDrop.querySelector('.wf-drop-title').textContent = 'Selected:';
    wfDrop.querySelector('.wf-drop-sub').textContent = 'Click to change';
    wfRunBtn.disabled = false;
    const ext = '.' + name.split('.').pop().toLowerCase();
    const isText = _TEXT_EXTS.includes(ext);
    const trCheck = document.querySelector('.wf-check[data-step="transcribe"]');
    const trStep = document.getElementById('wf-transcribe');
    if (isText) {
        trCheck.checked = false;
        trCheck.disabled = true;
        trStep.classList.add('dep-disabled');
        const det = trStep.querySelector('.wf-detail');
        if (det) det.textContent = 'Text file — no transcription needed';
    } else {
        trCheck.disabled = false;
        trCheck.checked = true;
        trStep.classList.remove('dep-disabled');
        const det = trStep.querySelector('.wf-detail');
        if (det) det.textContent = '';
    }
    syncSummarizeDep();
}

wfDrop.addEventListener('click', async () => {
    const fp = await pywebview.api.workflow_pick_video();
    if (fp) wfSetFile(fp);
});

wfDrop.addEventListener('dragover', e => { e.preventDefault(); wfDrop.classList.add('drag-over'); });
wfDrop.addEventListener('dragleave', () => { wfDrop.classList.remove('drag-over'); });
wfDrop.addEventListener('drop', async e => {
    e.preventDefault();
    wfDrop.classList.remove('drag-over');
    if (e.dataTransfer.files.length > 0) {
        const f = e.dataTransfer.files[0];
        if (f.path) { wfSetFile(f.path); return; }
    }
    const fp = await pywebview.api.workflow_pick_video();
    if (fp) wfSetFile(fp);
});

document.addEventListener('paste', async e => {
    const wv = document.getElementById('workflow-view');
    if (!wv.classList.contains('active')) return;
    const target = e.target;
    if (target && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable)) return;
    const cd = e.clipboardData || window.clipboardData;
    if (!cd) return;
    if (cd.files && cd.files.length > 0) return;
    const text = cd.getData('text/plain');
    if (!text || !text.trim()) return;
    e.preventDefault();
    const fp = await pywebview.api.workflow_save_pasted_text(text);
    if (fp) wfSetFile(fp);
});

function wfReset() {
    document.querySelectorAll('.wf-step').forEach(el => {
        el.classList.remove('running', 'done', 'error', 'skip');
        const det = el.querySelector('.wf-detail');
        if (det) det.textContent = '';
    });
    const log = document.getElementById('wf-log');
    log.classList.remove('has-output');
    log.innerHTML = '<div class="wf-log-placeholder">Output will appear here once you run the pipeline.</div>';
    document.getElementById('wf-process-links').innerHTML = '';
    document.getElementById('wf-deliver-links').innerHTML = '';
}

const _WF_LINK_CONTAINER = {
    summarize: 'wf-process-links',
    translate: 'wf-process-links',
    confluence: 'wf-deliver-links',
    superhuman: 'wf-deliver-links',
};

function wfRenderLinks(step, links) {
    const containerId = _WF_LINK_CONTAINER[step];
    if (!containerId) return;
    const container = document.getElementById(containerId);
    container.querySelectorAll(`a[data-step="${step}"]`).forEach(a => a.remove());
    links.forEach(link => {
        const a = document.createElement('a');
        a.textContent = link.label;
        a.href = '#';
        a.dataset.step = step;
        a.dataset.kind = link.kind;
        a.dataset.path = link.path;
        container.appendChild(a);
    });
}

document.getElementById('wf-process-links').addEventListener('click', wfLinkClick);
document.getElementById('wf-deliver-links').addEventListener('click', wfLinkClick);

async function wfLinkClick(e) {
    const a = e.target.closest('a');
    if (!a) return;
    e.preventDefault();
    if (a.dataset.kind === 'file') {
        await pywebview.api.reveal_in_finder(a.dataset.path);
    } else if (a.dataset.kind === 'url') {
        await pywebview.api.open_url(a.dataset.path);
    }
}

function wfUpdate(d) {
    const el = document.getElementById('wf-' + d.step);
    if (el) {
        el.classList.remove('running', 'done', 'error', 'skip');
        el.classList.add(d.status);
        const det = el.querySelector('.wf-detail');
        if (d.detail && det) det.textContent = d.detail;
    }
    if (d.detail) {
        const log = document.getElementById('wf-log');
        if (!log.classList.contains('has-output')) {
            log.classList.add('has-output');
            log.innerHTML = '';
        }
        const line = document.createElement('div');
        line.textContent = '[' + d.step + '] ' + d.detail;
        log.appendChild(line);
        log.scrollTop = log.scrollHeight;
    }
    if (d.links && d.links.length) {
        wfRenderLinks(d.step, d.links);
    }
}

function _isTextFile() {
    if (!wfVideoPath) return false;
    const ext = '.' + wfVideoPath.split('.').pop().toLowerCase();
    return _TEXT_EXTS.includes(ext);
}

function syncSummarizeDep() {
    const transcribe = document.querySelector('.wf-check[data-step="transcribe"]');
    const textInput = _isTextFile();
    const hasSource = transcribe.checked || textInput;
    [
        ['summarize', 'wf-summarize'],
        ['translate', 'wf-translate'],
    ].forEach(([stepName, stepId]) => {
        const cb = document.querySelector(`.wf-check[data-step="${stepName}"]`);
        const step = document.getElementById(stepId);
        if (!hasSource) {
            cb.disabled = true;
            cb.checked = false;
            step.classList.add('dep-disabled');
        } else {
            cb.disabled = false;
            step.classList.remove('dep-disabled');
        }
    });
    syncSlackDep();
}

function syncSlackDep() {
    const conf = document.querySelector('.wf-check[data-step="confluence"]');
    const sh = document.querySelector('.wf-check[data-step="superhuman"]');
    const slack = document.querySelector('.wf-check[data-step="slack"]');
    const slackStep = document.getElementById('wf-slack');
    const hint = document.getElementById('wf-slack-hint');
    const hasTarget = conf.checked || sh.checked;
    slack.disabled = !hasTarget;
    if (!hasTarget) {
        slack.checked = false;
        slackStep.classList.add('dep-disabled');
        hint.textContent = 'Requires Confluence or Superhuman';
    } else {
        slack.checked = true;
        slackStep.classList.remove('dep-disabled');
        hint.textContent = '';
    }
}
document.querySelector('.wf-check[data-step="transcribe"]').addEventListener('change', syncSummarizeDep);
document.querySelector('.wf-check[data-step="confluence"]').addEventListener('change', syncSlackDep);
document.querySelector('.wf-check[data-step="superhuman"]').addEventListener('change', syncSlackDep);

wfRunBtn.addEventListener('click', async () => {
    if (!wfVideoPath) return;
    wfReset();
    wfRunBtn.disabled = true;
    const lang = document.getElementById('wf-lang').value;
    const steps = {};
    document.querySelectorAll('.wf-check').forEach(cb => { steps[cb.dataset.step] = cb.checked; });
    try {
        if (window._prompts) {
            await pywebview.api.save_prompts(window._prompts.summary, window._prompts.translation);
        }
        const outDir = await pywebview.api.run_workflow(wfVideoPath, lang, JSON.stringify(steps));
        if (outDir) {
            // Pipeline moves source + outputs into outDir; repoint so a re-run finds them.
            wfVideoPath = outDir + '/' + wfVideoPath.split('/').pop();
        }
        await refreshUsage();
    } catch(e) {
        wfUpdate({step:'pipeline', status:'error', detail:String(e)});
    } finally {
        wfRunBtn.disabled = false;
    }
});

window.addEventListener('pywebviewready', async () => {
    try {
        const src = await pywebview.api.get_mascot();
        if (src) {
            const img = document.createElement('img');
            img.src = src;
            document.getElementById('mascot-bg').appendChild(img);
        }
    } catch(e) { console.error('mascot load error', e); }
    loadSettings();
    try {
        const p = await pywebview.api.get_prompts();
        window._prompts = { summary: p.summarize || '', translation: p.translation || '' };
    } catch(_) {
        window._prompts = { summary: '', translation: '' };
    }
});

const pmOverlay = document.getElementById('prompt-modal-overlay');
const pmText = document.getElementById('prompt-modal-text');
const pmTitle = document.getElementById('prompt-modal-title');
let _pmKey = null;

document.querySelectorAll('.wf-edit-prompt').forEach(btn => {
    btn.addEventListener('click', e => {
        e.preventDefault();
        _pmKey = btn.dataset.prompt;
        pmTitle.textContent = _pmKey === 'summary' ? 'Summarization prompt' : 'Translation prompt';
        pmText.value = window._prompts[_pmKey] || '';
        pmOverlay.classList.remove('hidden');
        pmText.focus();
    });
});

document.getElementById('pm-cancel').addEventListener('click', () => {
    pmOverlay.classList.add('hidden');
    _pmKey = null;
});

document.getElementById('pm-save').addEventListener('click', async () => {
    if (!_pmKey) return;
    window._prompts[_pmKey] = pmText.value;
    await pywebview.api.save_prompts(window._prompts.summary, window._prompts.translation);
    pmOverlay.classList.add('hidden');
    _pmKey = null;
});

pmOverlay.addEventListener('click', e => {
    if (e.target === pmOverlay) { pmOverlay.classList.add('hidden'); _pmKey = null; }
});

document.addEventListener('keydown', e => {
    if (e.key === 'Escape' && !pmOverlay.classList.contains('hidden')) {
        pmOverlay.classList.add('hidden'); _pmKey = null;
    }
});
</script>
</body>
</html>
"""


def _set_macos_icon():
    try:
        from AppKit import (
            NSApplication, NSBezierPath, NSColor, NSFont,
            NSFontAttributeName, NSForegroundColorAttributeName,
            NSImage, NSMutableParagraphStyle, NSParagraphStyleAttributeName,
        )
        from Foundation import NSAttributedString, NSMakeRect, NSMakeSize

        s = 256
        img = NSImage.alloc().initWithSize_(NSMakeSize(s, s))
        img.lockFocus()

        NSColor.colorWithSRGBRed_green_blue_alpha_(0.13, 0.59, 0.95, 1.0).setFill()
        NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
            NSMakeRect(0, 0, s, s), 48, 48,
        ).fill()

        style = NSMutableParagraphStyle.alloc().init()
        style.setAlignment_(1)
        attrs = {
            NSFontAttributeName: NSFont.boldSystemFontOfSize_(180),
            NSForegroundColorAttributeName: NSColor.whiteColor(),
            NSParagraphStyleAttributeName: style,
        }
        t = NSAttributedString.alloc().initWithString_attributes_("M", attrs)
        t.drawInRect_(NSMakeRect(0, 24, s, s - 24))

        img.unlockFocus()
        NSApplication.sharedApplication().setApplicationIconImage_(img)
    except Exception:
        pass


def main():
    api = Api()
    window = webview.create_window(
        "Mindbase", html=HTML, width=1100, height=850,
        js_api=api, text_select=True,
    )
    api.set_window(window)
    api.preload()
    webview.start(func=_set_macos_icon)


if __name__ == "__main__":
    main()
