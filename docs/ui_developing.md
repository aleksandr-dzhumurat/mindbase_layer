# UI Development Gotchas (pywebview + macOS WebKit)

## Debug mode

Pass `debug=True` to `webview.start()` to enable WebKit Developer Tools (right-click > Inspect Element). Disable for production builds.

## Drag-and-drop

`file.path` is an **Electron-only** property. In pywebview's WebKit engine it is always `undefined`. Use a fallback that opens a native file dialog via the Python bridge:

```javascript
wfDrop.addEventListener('drop', async e => {
    e.preventDefault();
    if (e.dataTransfer.files.length > 0) {
        const f = e.dataTransfer.files[0];
        if (f.path) { handleFile(f.path); return; }
    }
    // fallback: open native picker
    const fp = await pywebview.api.pick_file();
    if (fp) handleFile(fp);
});
```

## File dialog filters

`create_file_dialog` file_types format is strict. The regex is:

```
^([\w ]+)\((\*(?:\.(?:\w+|\*))*(?:;\*(?:\.(?:\w+|\*))*)*)\)$
```

- Description allows only **word characters and spaces** (no `/`, `-`, etc.)
- Extensions separated by **semicolons** (not spaces)
- Good: `"Video and Audio (*.mp4;*.m4a;*.mp3)"`
- Bad: `"Video/Audio (*.mp4;*.m4a)"` -- slash in description
- Bad: `"Video (*.mp4 *.m4a)"` -- spaces between extensions

## JS API calls run in background threads

`pywebview.api.*` calls from JS execute Python methods in a **background thread**. If the Python method raises an exception, `await` on the JS side may **never resolve**, leaving the UI stuck. Always wrap long-running Python bridge methods in try/except and re-enable UI controls from Python via `evaluate_js`:

```python
def run_workflow(self, ...):
    try:
        ...
    except Exception as e:
        self._wf_update('error', str(e))
        return None
    finally:
        self._window.evaluate_js("runBtn.disabled = false;")
```

## querySelector on dynamic elements

When using `querySelectorAll('.some-class').forEach(...)`, always guard child queries with a null check. Elements may not have the expected children if the DOM was built dynamically:

```javascript
// Bad -- crashes if .wf-detail is missing
el.querySelector('.wf-detail').textContent = '';

// Good
const det = el.querySelector('.wf-detail');
if (det) det.textContent = '';
```

## Settings field order

The Settings tab is split into two sections, each with its own `settings-grid`:

- **LLM Connection** — Model, `NEBIUS_API_KEY`, `GOOGLE_CREDENTIALS`
- **Upstream Connections** — Slack, Confluence, Superhuman fields

The visual order within each section is determined by the HTML `<div class="s-field">` blocks inside that section's `settings-grid`. The `get_settings()` and `save_settings()` dicts are unordered — only the HTML grid order matters for display. To reorder a field, move its `<div class="s-field">` block. To move a field between sections, cut/paste it into the other `settings-grid`.

## Settings and .env reloading

`os.environ` is populated at process startup. If the user saves settings to `.env` at runtime, subsequent code reading `os.environ` will see **stale values**. Two approaches:

1. Re-read `.env` with `dotenv_values()` before each use
2. Update `os.environ` in-memory when saving: `os.environ[key] = value`

Both are used in the codebase for belt-and-suspenders reliability.

## Installed copy vs repo source

The app runs from `~/.local/share/mindbase/src/mindbase_app.py`, not from the repo. After editing the repo source, sync with:

```bash
cp src/mindbase_app.py ~/.local/share/mindbase/src/mindbase_app.py
```

Or re-run `make install`. Forgetting this is the most common reason "the fix doesn't work".

## pywebview API timing (`pywebviewready`)

`pywebview.api` is **not available** when the page's `<script>` first executes. Any immediate call like `(async () => { await pywebview.api.foo(); })()` will silently fail because `pywebview` is `undefined`.

Wait for the `pywebviewready` event:

```javascript
// Bad — runs before pywebview.api is injected
(async () => {
    const data = await pywebview.api.get_data(); // TypeError: pywebview is undefined
})();

// Good — waits for the bridge
window.addEventListener('pywebviewready', async () => {
    const data = await pywebview.api.get_data();
});
```

User-triggered handlers (button clicks, form submits) don't need this because the API is always ready by the time a user interacts.

## Large data URIs in CSS

WebKit may silently ignore very large (>1 MB) `data:` URIs inside CSS `url()` — e.g. `background-image:url(data:image/png;base64,...)`. The style rule is parsed but the image never renders. Use an `<img>` element instead:

```javascript
// Bad — 1.5 MB base64 in CSS, WebKit ignores it
s.textContent = '#el::before { background-image:url(' + bigDataUri + '); }';

// Good — <img> handles large data URIs fine
const img = document.createElement('img');
img.src = bigDataUri;
container.appendChild(img);
```

## Mascot background removal (transparent PNGs)

Pixel-art mascot images ship with a solid dark background. To use them as faded watermarks in the UI, create a transparent copy while preserving interior dark pixels (eyes, outlines).

**Strategy: edge flood-fill, not global threshold.** A naive "remove all dark pixels" approach also removes eyes, pupils, and outlines inside the character. Instead, flood-fill from the image edges to find only the connected background region:

1. Compute per-pixel brightness: `R + G + B`
2. Seed a BFS queue from all edge pixels (top/bottom rows, left/right columns) whose brightness is below a threshold
3. Flood-fill inward through 4-connected neighbors that are also below the threshold
4. Only the filled region becomes transparent — interior dark pixels are untouched

```python
from PIL import Image
import numpy as np
from collections import deque

img = Image.open('assets/mascot.png')
data = np.array(img)  # must be RGBA
h, w = data.shape[:2]
brightness = data[:,:,0].astype(int) + data[:,:,1].astype(int) + data[:,:,2].astype(int)

visited = np.zeros((h, w), dtype=bool)
bg_mask = np.zeros((h, w), dtype=bool)
queue = deque()

THRESH = 40  # tune per image (40 for near-black, 90 for dark gray)

# seed from edges
for x in range(w):
    for y in [0, h-1]:
        if brightness[y, x] < THRESH:
            queue.append((y, x)); visited[y, x] = True
for y in range(h):
    for x in [0, w-1]:
        if brightness[y, x] < THRESH:
            queue.append((y, x)); visited[y, x] = True

while queue:
    cy, cx = queue.popleft()
    bg_mask[cy, cx] = True
    for dy, dx in [(-1,0),(1,0),(0,-1),(0,1)]:
        ny, nx = cy+dy, cx+dx
        if 0 <= ny < h and 0 <= nx < w and not visited[ny, nx] and brightness[ny, nx] < THRESH:
            visited[ny, nx] = True
            queue.append((ny, nx))

data[bg_mask, 3] = 0  # transparent
Image.fromarray(data).save('assets/mascot_transparent.png')
```

**Threshold tuning:** check corner pixel brightness to pick the right value. Near-black backgrounds (RGB ~1,1,1) use `THRESH=40`; dark gray backgrounds (RGB ~26,28,27) need `THRESH=90`.

**Convention:** keep the original file unchanged, save the transparent version with a `2` suffix (e.g. `mascot.png` → `maskot2.png`). The app references the transparent copy.

## Slack SDK error handling

`SlackAdapter.post_message()` catches `SlackApiError` internally and returns `{}`. If you need the actual error (e.g. `channel_not_found`, `not_in_channel`), call `slack_sdk.WebClient.chat_postMessage()` directly and catch `SlackApiError` yourself to get `e.response["error"]`.
