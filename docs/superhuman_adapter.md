# Superhuman (Coda) Adapter

Mindbase pushes summaries to [Superhuman Docs](https://docs.superhuman.com) via the Coda REST API. The adapter creates a doc inside a folder and writes markdown content to its first page.

## Getting an API token

1. Sign in at [coda.io](https://coda.io) with the account that owns the target workspace.
2. Open **Account settings** > [API settings](https://coda.io/account#apiSettings).
3. Click **Generate API token**.
4. Copy the token and paste it into Mindbase settings as `SUPERHUMAN_API_TOKEN`.

The token uses bearer authentication and grants access to all docs the account can see. Treat it like a password.

## Getting the folder ID

`SUPERHUMAN_PARENT_DIR` tells the adapter where to create new docs. It accepts either form:

- **Folder URL:** `https://docs.superhuman.com/folders/fl-KY-MQZ1hQt`
- **Raw folder ID:** `fl-KY-MQZ1hQt`

To find it, open the target folder in Superhuman Docs and copy the URL from the browser address bar. The adapter extracts the `fl-...` ID automatically.

## How the adapter works

1. **Lookup** — searches existing docs in the folder by title.
2. **Create or update** — if a doc with the same title exists, updates its first page. Otherwise creates a new doc and waits for the default page to appear.
3. **Content format** — writes markdown via the Coda canvas content API (`canvasContent.format: "markdown"`).

Rate limiting (HTTP 429) and transient network errors are retried up to 3 times with exponential backoff.

## Environment variables

| Variable | Required | Description |
|---|---|---|
| `SUPERHUMAN_API_TOKEN` | Yes | Bearer token from coda.io account settings |
| `SUPERHUMAN_PARENT_DIR` | Yes | Folder URL or ID (`fl-...`) where docs are created |

## References

- [Superhuman Docs Admin API (v1)](https://docs.superhuman.com/developers/apis/admin/v1)
- [Coda API settings page](https://docs.superhuman.com/account#apiSettings)
- [Intro to Superhuman Docs Admin API](https://help.superhuman.com/hc/en-us/articles/46210125237901-Intro-to-Superhuman-Docs-Admin-API)
