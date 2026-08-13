"""Adapter for the Coda (Superhuman) REST API.

Creates docs inside a folder and writes content to the doc's first page.
Authentication uses a bearer token from ``SUPERHUMAN_API_TOKEN``.
``SUPERHUMAN_PARENT_DIR`` should be a folder ID (fl-...) or folder URL.
"""

from __future__ import annotations

import logging
import os
import re
import time
from typing import Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

_BASE_URL = "https://coda.io/apis/v1"
_MAX_RETRIES = 3
_WRITE_RATE_LIMIT_DELAY = 2.0


class SuperhumanAdapter:

    def __init__(self, api_token: Optional[str] = None):
        self._token = api_token or os.environ.get("SUPERHUMAN_API_TOKEN", "")
        if not self._token:
            raise ValueError("Superhuman API token not provided; set SUPERHUMAN_API_TOKEN.")
        self._session = self._make_session()

    def _make_session(self) -> requests.Session:
        s = requests.Session()
        s.headers.update({
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        })
        return s

    def _request(self, method: str, url: str, **kwargs) -> Optional[requests.Response]:
        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                r = self._session.request(method, url, timeout=30, **kwargs)
                if r.status_code == 429:
                    retry_after = float(r.headers.get("Retry-After", 2 ** attempt))
                    logger.warning("Rate limited, retrying in %.1fs", retry_after)
                    time.sleep(retry_after)
                    continue
                return r
            except requests.RequestException as exc:
                logger.error("Network error (attempt %d): %s", attempt, exc)
                time.sleep(2 ** attempt)
        return None

    def list_docs(self, folder_id: Optional[str] = None) -> List[Dict]:
        r = self._request("GET", f"{_BASE_URL}/docs", params={"limit": 100})
        if not r or not r.ok:
            return []
        docs = r.json().get("items", [])
        if folder_id:
            docs = [d for d in docs if d.get("folderId") == folder_id]
        return docs

    def create_doc(self, title: str, folder_id: Optional[str] = None) -> Optional[Dict]:
        payload: Dict = {"title": title}
        if folder_id:
            payload["folderId"] = folder_id
        r = self._request("POST", f"{_BASE_URL}/docs", json=payload)
        if r and r.status_code in (200, 201, 202):
            doc = r.json()
            logger.info("Created doc '%s' (id=%s)", title, doc.get("id"))
            return doc
        logger.error("Create doc failed: %s", r.text[:300] if r else "no response")
        return None

    def create_page(self, doc_id: str, name: str, content: str) -> Optional[Dict]:
        payload: Dict = {
            "name": name,
            "contentUpdate": {
                "insertionMode": "replace",
                "canvasContent": {"format": "markdown", "content": content},
            },
        }
        r = self._request("POST", f"{_BASE_URL}/docs/{doc_id}/pages", json=payload)
        if r and r.status_code in (200, 201, 202):
            logger.info("Created page '%s' in doc %s", name, doc_id)
            return r.json()
        logger.error("Create page failed: %s", r.text[:300] if r else "no response")
        return None

    def update_page_content(self, doc_id: str, page_id: str, content: str, name: Optional[str] = None) -> bool:
        payload: Dict = {
            "contentUpdate": {
                "insertionMode": "replace",
                "canvasContent": {"format": "markdown", "content": content},
            },
        }
        if name:
            payload["name"] = name
        r = self._request("PUT", f"{_BASE_URL}/docs/{doc_id}/pages/{page_id}", json=payload)
        if r and r.status_code in (200, 202):
            logger.info("Updated page %s in doc %s", page_id, doc_id)
            return True
        logger.error("Update page failed: %s", r.text[:300] if r else "no response")
        return False

    def list_pages(self, doc_id: str) -> List[Dict]:
        r = self._request("GET", f"{_BASE_URL}/docs/{doc_id}/pages", params={"limit": 50})
        if not r or not r.ok:
            return []
        return r.json().get("items", [])

    def _wait_for_page(self, doc_id: str, retries: int = 6) -> Optional[Dict]:
        for i in range(retries):
            time.sleep(2 * (i + 1))
            pages = self.list_pages(doc_id)
            if pages:
                return pages[0]
        return None

    def push(self, folder_id: str, title: str, content: str) -> Optional[Dict]:
        """Create a doc in folder (or update existing with same name), write content."""
        existing = self._find_doc_by_name(folder_id, title)
        if existing:
            doc_id = existing["id"]
            logger.info("Doc '%s' exists (id=%s), updating…", title, doc_id)
            pages = self.list_pages(doc_id)
            if pages:
                self.update_page_content(doc_id, pages[0]["id"], content, name=title)
            return existing

        doc = self.create_doc(title, folder_id=folder_id)
        if not doc:
            return None
        page = self._wait_for_page(doc["id"])
        if page:
            self.update_page_content(doc["id"], page["id"], content, name=title)
        else:
            logger.error("Default page never appeared for doc %s", doc["id"])
        return doc

    def _find_doc_by_name(self, folder_id: str, name: str) -> Optional[Dict]:
        for doc in self.list_docs(folder_id=folder_id):
            if doc.get("name") == name:
                return doc
        return None

    @staticmethod
    def resolve_folder_id(value: str) -> str:
        """Parse SUPERHUMAN_PARENT_DIR into a folder ID.

        Accepts:
        - Folder URL: https://docs.superhuman.com/folders/fl-KY-MQZ1hQt
        - Raw folder ID: fl-KY-MQZ1hQt
        """
        value = value.strip().rstrip("/")
        m = re.search(r'(fl-[A-Za-z0-9_-]+)', value)
        if m:
            return m.group(1)
        return value

    @classmethod
    def from_env(cls) -> Optional["SuperhumanAdapter"]:
        token = os.environ.get("SUPERHUMAN_API_TOKEN", "").strip()
        if not token:
            return None
        return cls(api_token=token)
