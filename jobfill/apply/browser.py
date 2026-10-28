"""A visible Chromium that outlives each jobfill command.

`apply fill` connects over the Chrome DevTools Protocol, fills, and disconnects; the window stays
open so the candidate can watch, correct and submit, and the next command picks up the same tab.
The profile directory keeps cookies, so a login done once by the candidate is reused.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
import urllib.request
from contextlib import contextmanager
from pathlib import Path


def _port() -> int:
    return int(os.environ.get("JOBFILL_CDP_PORT", "9333"))


def endpoint(port: int | None = None) -> str:
    return f"http://127.0.0.1:{port or _port()}"


def alive(port: int | None = None) -> bool:
    try:
        with urllib.request.urlopen(endpoint(port) + "/json/version", timeout=1):
            return True
    except Exception:
        return False


def chrome_path() -> str:
    if os.environ.get("JOBFILL_CHROME"):
        return os.environ["JOBFILL_CHROME"]
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        return p.chromium.executable_path


def ensure(data_dir: Path, headless: bool = False) -> str:
    """Start the shared browser if it is not running; return its CDP endpoint."""
    port = _port()
    if alive(port):
        return endpoint(port)
    profile = Path(os.environ.get("JOBFILL_BROWSER_PROFILE", data_dir / "browser-profile"))
    profile.mkdir(parents=True, exist_ok=True)
    args = [chrome_path(), f"--remote-debugging-port={port}", f"--user-data-dir={profile}",
            "--no-first-run", "--no-default-browser-check", "--disable-features=Translate", "about:blank"]
    if headless:
        args.insert(1, "--headless=new")
    kwargs = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL,
              "close_fds": True}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    proc = subprocess.Popen(args, **kwargs)
    state = data_dir / "apply" / "browser.json"
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text(json.dumps({"pid": proc.pid, "port": port, "profile": str(profile)}), encoding="utf-8")
    for _ in range(80):
        if alive(port):
            return endpoint(port)
        time.sleep(0.25)
    raise RuntimeError(f"Chromium did not open its debugging port {port}")


def close(data_dir: Path) -> bool:
    state = data_dir / "apply" / "browser.json"
    if not state.exists():
        return False
    pid = json.loads(state.read_text(encoding="utf-8")).get("pid")
    state.unlink()
    if not pid:
        return False
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
    else:
        try:
            os.kill(pid, 15)
        except OSError:
            return False
    return True


@contextmanager
def session(data_dir: Path, headless: bool = False):
    """Yield the shared browser context; disconnecting leaves the window open."""
    from playwright.sync_api import sync_playwright
    ep = ensure(data_dir, headless)
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(ep)
        yield browser.contexts[0] if browser.contexts else browser.new_context()


def find_page(context, tag: str, url: str):
    """The tab used for this application: tagged earlier, else same site, else a new tab."""
    from urllib.parse import urlparse
    host = urlparse(url).netloc
    same_site = None
    for page in context.pages:
        try:
            if page.evaluate("() => window.name") == tag:
                return page, False
        except Exception:
            continue
        if urlparse(page.url).netloc == host:
            same_site = page
    if same_site is not None:
        same_site.evaluate("(t) => { window.name = t; }", tag)
        return same_site, False
    blank = next((p for p in context.pages if p.url in ("about:blank", "chrome://newtab/")), None)
    page = blank or context.new_page()
    return page, True
