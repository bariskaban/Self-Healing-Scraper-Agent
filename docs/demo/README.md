# Demo videos

Real screen recordings of the dashboard, made on 21 Nov 2026 with `record_demo.py` (25 frames a second, a visible cursor, nothing sped up). They run on the demo server (`python -m mock_portal.demo`), which reads only fake portals inside its own process: no request leaves the machine. The repair is a real model call (`gpt-6.2-sol`, 8 calls, about $0.12).

| File | What it is |
| --- | --- |
| `watchtower-demo.mp4` | The demo, 5 min 44 s, with no text on the picture. |

## What the demo shows

1. **Attach.** A portal is added by its address. The dashboard shows `Integrating`, then `Serving` with its 45 tenders.
2. **Proof.** The portal's page, the tender list in its own scroll box, one tender opened with its files, and one downloaded file (a PDF) opened.
3. **Notice.** The fake portal changes its layout. The dashboard goes to `Healing`, with the reason, and still serves the 45 tenders.
4. **Repair.** The model repairs the recipe by itself (about 40 seconds, the waiting can be sped up). The portal is `Serving` again on recipe v2, and the run history lists the repair run with what broke, what the agent did, what changed and how it was verified.
5. **A blocked portal.** A second fake portal puts a login in front of everything. It goes to `Failed` with "Login required ... We do not log in".
6. **Cost.** The model cost to date and the cost per new portal on the dashboard, and the "Cost & scale" page.

## Make it again

You need Brave (or another Chromium), `ffmpeg`, and a throwaway virtual environment with Playwright (not the project's: `uv venv rec-venv && uv pip install --python rec-venv/bin/python playwright`).

```sh
# 1. a clean demo server; the repair needs a key, so give it one of your own in the environment
OPENAI_API_KEY=... python -m mock_portal.demo --port 8791

# 2. record (add --no-captions for the clean version; leave out --repair to skip the model call)
rec-venv/bin/python docs/demo/record_demo.py --repair --no-captions --out watchtower-demo.mp4
```

The browser is started headless; the frames come from Chrome's screencast and `ffmpeg` makes the video. Start the server fresh each time (the script expects no portals). Never put a key in a file in this repository.
