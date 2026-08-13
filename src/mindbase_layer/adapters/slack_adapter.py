"""Slack adapters.

- ``SlackAdapter``  -- full Web API client, needs a bot user + ``SLACK_BOT_TOKEN``.
- ``SlackWebHook``  -- posts to an Incoming Webhook / Workflow Builder trigger URL. No
  bot user, token, or OAuth scopes; just the secret webhook URL from the environment.

Also exposes a small ``publish()`` helper and a CLI (Python rewrite of the old
``publisher.sh``) for posting a Jira URL to the webhook:

    python src/adapters/slack_adapter.py <jira-url>
"""

from __future__ import annotations

import logging
import os
import sys
from typing import TYPE_CHECKING, Dict, List, Optional

import requests
from dotenv import load_dotenv
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

if TYPE_CHECKING:
    from src.models import FinalTaskReport


logger = logging.getLogger(__name__)


class SlackAdapter:
    """Adapter for Slack Web API with business logic."""

    def __init__(self, bot_token: str, email_to_user_id: Dict[str, str]):
        self._client = WebClient(token=bot_token)
        self._email_to_user_id = email_to_user_id

    # ==================== High-level business methods ====================

    def send_standup_reminder(self, channel: str, tasks_by_email: Dict[str, List]) -> str:
        """Send standup reminder and return thread_ts."""
        blocks = self._format_standup_message(tasks_by_email)
        response = self.post_message(
            channel=channel,
            text="Daily Standup Reminder",
            blocks=blocks,
        )
        return response.get("ts", "")

    def post_task_alert(
        self, channel: str, thread_ts: str, report: FinalTaskReport
    ) -> Optional[Dict]:
        """Post an action-required alert in a thread."""
        user_id = self._email_to_user_id.get(report.assignee)
        if not user_id:
            logger.warning(
                "No Slack user ID found for assignee %s. Cannot post task alert.",
                report.assignee,
            )

        text = f"<@{user_id}>, :eyes: <{os.environ['JIRA_BASE_URL']}/browse/{report.issue_key}|{report.issue_key}>\n{report.message_to_assignee}"
        return self.post_thread_reply(channel, thread_ts, text)

    def post_summary(self, channel: str, thread_ts: str, manager_email: str) -> Optional[Dict]:
        """Post a summary message when no incidents found."""
        user_id = self._email_to_user_id.get(manager_email)
        if not user_id:
            return None

        text = f"<@{user_id}>, робот всё проверил! По задачкам к ребятам замечаний нет"
        return self.post_thread_reply(channel, thread_ts, text)

    # ==================== Low-level API methods ====================

    def post_message(
        self,
        channel: str,
        text: str,
        blocks: Optional[List] = None,
        **kwargs,
    ) -> Dict:
        """Post a message to a Slack channel."""
        try:
            response = self._client.chat_postMessage(
                channel=channel,
                text=text,
                blocks=blocks,
                **kwargs,
            )
            return response.data or {}
        except SlackApiError as e:
            logger.error(f"Error posting message to {channel}: {e.response['error']}")
            return {}

    def post_thread_reply(
        self,
        channel: str,
        thread_ts: str,
        text: str,
        **kwargs,
    ) -> Dict:
        """Post a reply in a thread."""
        try:
            response = self._client.chat_postMessage(
                channel=channel,
                text=text,
                thread_ts=thread_ts,
                **kwargs,
            )
            return response.data or {}
        except SlackApiError as e:
            logger.error(f"Error posting thread reply to {channel}: {e.response['error']}")
            return {}

    # ==================== Private helper methods ====================

    def _format_standup_message(self, tasks_by_email: Dict[str, List]) -> List[Dict]:
        """Format tasks into Slack blocks."""
        blocks = [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "<!channel> Доброе утро, команда! 🌅\nЖелаю всем отличного дня! ☀️",
                },
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "_📝 Дружеское напоминание: Пожалуйста, заполните свои стендап-заметки, когда будет возможность._",
                },
            },
            {"type": "divider"},
            {
                "type": "header",
                "text": {"type": "plain_text", "text": "📋 Активные задачи"},
            },
        ]

        for email, tickets in sorted(tasks_by_email.items()):
            user_id = self._email_to_user_id.get(email)

            if user_id:
                mention = f"<@{user_id}>"
            else:
                mention = email

            sorted_tickets = sorted(
                tickets,
                key=lambda ticket: (
                    (ticket.get("status") or ticket.get("task_status") or "").lower(),
                    ticket.get("key", ""),
                ),
            )
            ticket_lines = []
            for ticket in sorted_tickets:
                status = ticket.get("status") or ticket.get("task_status")
                status_prefix = f"[{status}] " if status else ""
                ticket_lines.append(
                    f"• {status_prefix}<{os.environ['JIRA_BASE_URL']}/browse/{ticket['key']}|{ticket['key']}>: "
                    f"{ticket['summary']}"
                )
            ticket_text = "\n".join(ticket_lines)

            blocks.append(
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": f"*{mention}*\n{ticket_text}"},
                }
            )

        blocks.append({"type": "divider"})
        blocks.append(
            {
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": "Продуктивного дня! 💪"}],
            }
        )

        return blocks


class SlackWebHook:
    """Post messages to Slack through a webhook URL -- no bot user or token required.

    Works with both webhook flavours Slack offers:

    - **Incoming Webhooks** (``https://hooks.slack.com/services/...``) expect a message
      payload such as ``{"text": "..."}`` or ``{"blocks": [...]}``.
    - **Workflow Builder triggers** (``https://hooks.slack.com/triggers/...``) expect the
      custom variables the workflow declares, e.g. ``{"jira_url": "..."}``.

    The URL is the only secret involved, so treat it like a password. It is read from the
    ``WEBHOOK_URL`` (or ``SLACK_WEBHOOK_URL``) environment variable when not passed in.
    """

    ENV_VARS = ("WEBHOOK_URL", "SLACK_WEBHOOK_URL")

    def __init__(self, webhook_url: Optional[str] = None, timeout: float = 10.0):
        url = (webhook_url or self._url_from_env() or "").strip()
        if not url:
            raise ValueError(
                f"Slack webhook URL not provided; set one of {', '.join(self.ENV_VARS)}."
            )
        self._webhook_url = url
        self._timeout = timeout

    @classmethod
    def _url_from_env(cls) -> Optional[str]:
        """Return the first non-empty webhook URL found in the environment."""
        for name in cls.ENV_VARS:
            value = os.environ.get(name, "").strip()
            if value:
                return value
        return None

    @classmethod
    def from_env(cls, timeout: float = 10.0) -> Optional["SlackWebHook"]:
        """Build from the environment, or return None if no webhook URL is configured."""
        if cls._url_from_env() is None:
            return None
        return cls(timeout=timeout)

    def send(self, payload: Dict) -> bool:
        """POST a raw JSON payload to the webhook.

        Returns True on an HTTP 2xx response and False otherwise. Never raises -- a failed
        notification must not break the calling pipeline.
        """
        try:
            response = requests.post(self._webhook_url, json=payload, timeout=self._timeout)
        except requests.RequestException as exc:
            logger.error("Slack webhook request failed: %s", exc)
            return False

        if response.ok:
            return True

        logger.error(
            "Slack webhook returned HTTP %s: %s",
            response.status_code,
            response.text[:200],
        )
        return False

    def send_text(self, text: str, blocks: Optional[List[Dict]] = None) -> bool:
        """Post a plain message to an Incoming Webhook (payload ``{"text": ...}``)."""
        payload: Dict = {"text": text}
        if blocks:
            payload["blocks"] = blocks
        return self.send(payload)


# Preserved from publisher.sh so behaviour is unchanged when no env var is set. This URL is
# secret-like (anyone with it can trigger the workflow); prefer setting WEBHOOK_URL in .env.
_DEFAULT_WEBHOOK_URL = (
    "https://hooks.slack.com/triggers/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"
)


def publish(jira_url: str, webhook_url: str | None = None) -> bool:
    """Send ``{"jira_url": jira_url}`` to the Slack webhook. Returns True on success."""
    url = (
        webhook_url
        or os.environ.get("WEBHOOK_URL")
        or os.environ.get("SLACK_WEBHOOK_URL")
        or _DEFAULT_WEBHOOK_URL
    )
    return SlackWebHook(url).send({"jira_url": jira_url})


def main(argv: list[str]) -> int:
    """CLI entry point: expects a single Jira URL argument."""
    if len(argv) != 1 or not argv[0].strip():
        print("Usage: slack_adapter.py <jira-url>", file=sys.stderr)
        return 2
    load_dotenv()
    if publish(argv[0].strip()):
        print("✓ Posted to Slack webhook.")
        return 0
    print("✗ Failed to post to Slack webhook (see logs).", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
