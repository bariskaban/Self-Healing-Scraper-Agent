"""Records the Watchtower demo as a real video: a browser drives the dashboard, every frame is captured.

    rec-venv/bin/python record_demo.py [--repair] [--out demo.mp4]

Needs the demo server on 127.0.0.1:8791 started fresh (python -m mock_portal.demo --port 8791), with
OPENAI_API_KEY in its environment when --repair is used (the repair is a live model call).
The browser is Brave in headless mode; frames come from Chrome's screencast, and ffmpeg makes the video.
"""
from __future__ import annotations

import argparse
import base64
import json
import re
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8791"
W, H = 1440, 810

CURSOR_JS = """
(() => {
  const add = () => {
    if (document.getElementById('__cur')) return;
    const c = document.createElement('div'); c.id = '__cur';
    c.style.cssText = 'position:fixed;z-index:2147483647;width:26px;height:26px;border-radius:50%;background:rgba(255,90,40,.55);'
      + 'border:3px solid #fff;box-shadow:0 0 8px rgba(0,0,0,.45);pointer-events:none;left:-60px;top:-60px;transform:translate(-50%,-50%)';
    document.documentElement.appendChild(c);
    const k = document.createElement('div'); k.id = '__cap';
    k.style.cssText = 'position:fixed;z-index:2147483646;left:50%;bottom:18px;transform:translateX(-50%);max-width:88%;'
      + 'background:rgba(20,20,40,.88);color:#fff;font:600 22px/1.3 system-ui,sans-serif;padding:10px 22px;border-radius:12px;'
      + 'pointer-events:none;display:none;text-align:center';
    document.documentElement.appendChild(k);
    window.addEventListener('mousemove', e => { c.style.left = e.clientX + 'px'; c.style.top = e.clientY + 'px'; }, true);
    window.addEventListener('mousedown', () => { c.style.transform = 'translate(-50%,-50%) scale(.65)'; }, true);
    window.addEventListener('mouseup', () => { c.style.transform = 'translate(-50%,-50%) scale(1)'; }, true);
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', add); else add();
})();
"""


def api(path: str, method: str = "GET", body: dict | None = None):
    req = urllib.request.Request(BASE + path, method=method, headers={"Content-Type": "application/json"},
                                 data=json.dumps(body).encode() if body is not None else (b"" if method == "POST" else None))
    with urllib.request.urlopen(req, timeout=20) as r:
        raw = r.read()
        return json.loads(raw) if raw else None


class Recorder:
    def __init__(self, page, context):
        self.page, self.frames = page, []
        self.cdp = context.new_cdp_session(page)
        self.cdp.on("Page.screencastFrame", self._frame)

    def _frame(self, event):
        self.frames.append((event["metadata"]["timestamp"], base64.b64decode(event["data"])))
        try:
            self.cdp.send("Page.screencastFrameAck", {"sessionId": event["sessionId"]})
        except Exception:
            pass

    def start(self):
        self.cdp.send("Page.startScreencast", {"format": "jpeg", "quality": 90, "maxWidth": W, "maxHeight": H, "everyNthFrame": 1})

    def stop(self):
        self.cdp.send("Page.stopScreencast")

    def encode(self, out: Path, fps: int = 25):
        folder = Path(tempfile.mkdtemp(prefix="demo-frames-"))
        lines = []
        for i, (ts, data) in enumerate(self.frames):
            (folder / f"{i:06d}.jpg").write_bytes(data)
            nxt = self.frames[i + 1][0] if i + 1 < len(self.frames) else ts + 1.5
            lines.append(f"file '{folder}/{i:06d}.jpg'\nduration {max(nxt - ts, 0.001):.4f}")
        lines.append(f"file '{folder}/{len(self.frames) - 1:06d}.jpg'")
        (folder / "list.txt").write_text("\n".join(lines))
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(folder / "list.txt"),
                        "-vf", f"fps={fps},scale={W}:{H},format=yuv420p", "-c:v", "libx264", "-crf", "20", "-preset", "medium",
                        "-movflags", "+faststart", str(out)], check=True)
        return len(self.frames), self.frames[-1][0] - self.frames[0][0]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repair", action="store_true", help="include the repair (needs OPENAI_API_KEY on the server)")
    ap.add_argument("--out", default="watchtower-demo.mp4")
    ap.add_argument("--no-captions", action="store_true", help="no text on the video, only the dashboard")
    args = ap.parse_args()

    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path="/usr/bin/brave", headless=True,
                                    args=["--no-sandbox", "--headless=new", "--hide-scrollbars", "--force-device-scale-factor=1"])
        context = browser.new_context(viewport={"width": W, "height": H}, device_scale_factor=1)
        context.add_init_script(CURSOR_JS)
        page = context.new_page()
        rec = Recorder(page, context)
        pos = [W / 2, H / 2]

        def wait(ms): page.wait_for_timeout(ms)

        def hold(seconds: float): wait(int(seconds * 1000))

        def caption(text: str | None):
            if args.no_captions:
                return
            page.evaluate("t => { const k = document.getElementById('__cap'); if (!k) return;"
                          " if (t) { k.textContent = t; k.style.display = 'block'; } else k.style.display = 'none'; }", text)

        def say(text: str, minimum: float = 2.5):
            """A caption, held long enough to read."""
            caption(text); hold(1.2 if args.no_captions else max(minimum, len(text) * 0.06))

        def glide(x: float, y: float, seconds: float = 1.1):
            """Move the cursor along an eased path in real time: about 60 steps a second, slow at both ends."""
            x0, y0 = pos
            steps = max(int(seconds * 60), 2)
            for i in range(1, steps + 1):
                k = i / steps
                e = k * k * (3 - 2 * k)                     # smoothstep
                page.mouse.move(x0 + (x - x0) * e, y0 + (y - y0) * e)
                wait(16)
            pos[0], pos[1] = x, y

        def center(target):
            target.scroll_into_view_if_needed()
            box = target.bounding_box()
            return box["x"] + box["width"] / 2, box["y"] + min(box["height"] / 2, 28)

        def go(target, seconds: float = 1.1):
            x, y = center(target)
            glide(x, y, seconds); hold(0.45)
            page.mouse.down(); wait(90); page.mouse.up(); hold(0.5)

        def scroll(pixels: int, seconds: float = 2.0):
            """Scroll the PAGE smoothly in small steps (not the wheel: over the tender list the wheel scrolls the list)."""
            steps = max(int(seconds * 50), 1)
            for i in range(steps):
                page.evaluate("y => window.scrollBy(0, y)", pixels / steps); wait(20)

        def vis(selector: str):
            return page.locator(f"{selector} >> visible=true").first

        def portal_state(part: str):
            for x in api("/portals"):
                if part in x["url"] and not (part == "mock.example" and "login" in x["url"]):
                    return x["id"], x["state"]
            return None, None

        def badge(word: str, part: str, timeout: int = 60_000, settle: float = 5.5):
            """Wait until the server says the portal is in this state, then let the page's own poll show it."""
            until = time.time() + timeout / 1000
            while time.time() < until:
                if (portal_state(part)[1] or "").lower() == word.lower():
                    hold(settle); return
                wait(400)
            raise TimeoutError(f"{part} never became {word}")

        def type_text(text: str):
            page.keyboard.type(text, delay=70); hold(0.8)

        api("/demo/reset", "POST")
        page.goto(BASE + "/"); wait(1500)
        glide(W * 0.55, H * 0.45, 0.1)
        rec.start(); hold(1.0)

        # 1. Attach
        say("Watchtower: it learns a procurement portal, reads it, notices when it breaks, and repairs itself", 4.0)
        say("1. Attach: add a portal by its address", 3.0)
        go(vis("button:has-text('Add portal')"))
        go(page.locator("textarea").first)
        type_text("https://mock.example")
        go(page.get_by_role("dialog").get_by_role("button", name="Add portal"))
        caption("Integrating: the system is learning the portal"); badge("Integrating", "mock.example", 20_000, 3.0); hold(2.0)
        caption("Serving: learned and read, with its tenders delivered"); badge("Serving", "mock.example", 60_000, 5.5)
        pid = next(x["id"] for x in api("/portals") if "login" not in x["url"])
        page.keyboard.press("Escape"); hold(1.5)
        caption("One portal, serving, 45 tenders, no model cost for reading"); hold(7.0)

        # 2. Proof
        say("2. Proof: the tenders, with real fields and documents", 3.0)
        go(page.locator(f"a[href$='/portal/{pid}']").first if page.locator(f"a[href$='/portal/{pid}']").count() else page.get_by_text("mock.example").first)
        hold(4.5)
        caption("The portal's page: state, recipe, cost, and every read"); hold(4.0)
        scroll(520, 2.2); hold(1.5)
        caption("The delivered tenders: buyer, deadline, status and files. The list scrolls on its own."); hold(6.0)
        title = vis("text=/\\(lot \\d+\\)/"); tx, ty = center(title)
        glide(tx + 560, ty, 1.2); hold(0.5); page.mouse.down(); wait(90); page.mouse.up(); hold(3.0)   # the row, not the title link
        caption("Open a tender: its files, with sizes, downloaded and hashed by the system"); hold(6.0)
        go(vis("text=tender-notice.pdf")); hold(1.0)
        caption("One of the downloaded files, opened"); hold(7.0)
        page.go_back(); hold(3.5)

        # 3. Notice
        say("3. Notice: the portal changes its layout (we break it on purpose)", 3.2)
        scroll(-2000, 1.2); hold(1.5)
        api("/demo/layout", "POST"); api(f"/portals/{pid}/refresh", "POST")
        caption("The next read cannot find the list any more"); badge("Healing", "mock.example", 60_000, 5.5)
        caption("Healing: the reason is shown, and the last good tenders are still served"); hold(9.0)

        # 4. Repair
        if args.repair:
            say("4. Repair: the model fixes the recipe by itself", 3.2)
            began = time.time()
            caption("The repair is running (this takes a minute; the footage can be sped up)")
            badge("Serving", "mock.example", 300_000, 5.5)
            caption(f"Serving again after {int(time.time() - began)} s, with no person involved"); hold(7.0)
            caption("Run history: the failed read, and the repair run")
            head = vis("text=/Run history/")
            top = head.bounding_box()["y"]
            scroll(int(top - 140), 2.8); hold(4.0)
            try:
                go(vis("text=/^Repair$/")); hold(1.0)
                caption("The repair run: what broke, what the agent did, what changed, how it was verified"); hold(10.0)
                scroll(500, 2.5); hold(6.0)
                page.keyboard.press("Escape"); hold(1.5)
            except Exception:
                hold(4.0)
        else:
            say("4. Repair: needs the model key (not in this recording)", 4.0)
            api("/demo/reset", "POST")

        # 5. Blocked
        scroll(-3000, 1.2); hold(1.0)
        go(page.get_by_text("Back to portals").first); hold(3.0)
        say("5. A blocked portal: one behind a login", 3.0)
        go(vis("button:has-text('Add portal')"))
        go(page.locator("textarea").first)
        type_text("https://login.mock.example")
        go(page.get_by_role("dialog").get_by_role("button", name="Add portal")); hold(9.0)
        page.keyboard.press("Escape"); hold(1.5)
        lid = next(x["id"] for x in api("/portals") if "login.mock" in x["url"])
        api("/demo/login-wall", "POST"); api(f"/portals/{lid}/refresh", "POST")
        caption("A login wall appears. We never log in or get around it."); badge("Failed", "login.mock.example", 60_000, 5.5)
        caption("Failed, and the reason says exactly why. A person is needed here."); hold(9.0)
        go(page.locator(f"a[href$='/portal/{lid}']").first if page.locator(f"a[href$='/portal/{lid}']").count() else page.get_by_text("login.mock.example").first)
        hold(3.0); caption("The portal's own page: the reason and the failed read"); hold(7.0)
        go(page.get_by_text("Back to portals").first); hold(2.5)

        # 6. Cost
        say("6. Cost: where the model cost is shown", 3.0)
        glide(1130, 430, 1.4); hold(1.0)
        caption("Model cost to date, and the average cost of a new portal"); hold(7.0)
        go(vis("text=Cost & scale")); hold(3.0)
        caption("Cost & scale: cost per portal learned from scratch, and the projection to thousands of portals"); hold(8.0)
        scroll(500, 2.5); hold(6.0)
        caption(None); hold(1.5)

        rec.stop()
        n, seconds = rec.encode(Path(args.out))
        browser.close()
    print(f"frames {n}, {seconds:.0f} s -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
