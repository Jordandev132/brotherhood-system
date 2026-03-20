"""Demo Deployer — pushes custom demos to GitHub Pages.

Handles git clone/pull, folder creation, file writing, video copying,
commit, push, and deployment verification via HEAD request.

Called after demo_builder generates the HTML.
"""
from __future__ import annotations

import fcntl
import logging
import re
import shutil
import subprocess
import time
from pathlib import Path

import requests

log = logging.getLogger(__name__)

REPO_DIR = Path.home() / "chatbot-demos"
REPO_URL = "https://github.com/DarkCode-AI/chatbot-demos.git"
DEMO_BASE_URL = "https://darkcode-ai.github.io/chatbot-demos/"

# Max retries for deployment verification
_DEPLOY_RETRIES = 12
_DEPLOY_WAIT = 20  # seconds between retries

# Exclusive file lock — serializes all git operations across threads/processes
_GIT_LOCK_FILE = Path("/tmp/chatbot-demos-git.lock")
_MIN_PUSH_INTERVAL = 90  # seconds between pushes (GitHub Pages cooldown)
_PUSH_TS_FILE = REPO_DIR.parent / ".chatbot-demos-push-ts"


def _make_slug(business_name: str) -> str:
    """Convert business name to a URL-safe slug.

    "Belmont Periodontics, P.C." → "belmont-periodontics"
    """
    s = business_name.lower().strip()
    for suffix in [", p.c.", " p.c.", ", pllc", " pllc", ", llc", " llc",
                   ", inc.", " inc.", ", inc", " inc", ", dds", " dds",
                   ", dmd", " dmd"]:
        s = s.replace(suffix, "")
    s = re.sub(r"[^a-z0-9\s]", "", s).strip()
    s = re.sub(r"\s+", "-", s)
    return s


def _ensure_repo() -> bool:
    """Ensure the chatbot-demos repo is cloned and up to date. MUST be called inside git lock."""
    if REPO_DIR.exists():
        try:
            subprocess.run(
                ["git", "pull", "--rebase", "origin", "main"],
                cwd=REPO_DIR, capture_output=True, timeout=30, check=True,
            )
            return True
        except subprocess.CalledProcessError as e:
            log.error("[DEPLOYER] git pull failed: %s", e.stderr)
            # Hard reset to remote
            subprocess.run(["git", "checkout", "main"], cwd=REPO_DIR, capture_output=True, timeout=10)
            subprocess.run(["git", "reset", "--hard", "origin/main"], cwd=REPO_DIR, capture_output=True, timeout=10)
            return True
    else:
        try:
            subprocess.run(
                ["git", "clone", REPO_URL, str(REPO_DIR)],
                capture_output=True, timeout=60, check=True,
            )
            return True
        except subprocess.CalledProcessError as e:
            log.error("[DEPLOYER] git clone failed: %s", e.stderr)
            return False


def _copy_videos(demo_dir: Path, niche: str) -> None:
    """Copy video preview files from the generic template."""
    niche_template_map = {
        "real_estate": "realestate-demo",
        "commercial_re": "commercial-re-demo",
    }
    template_slug = niche_template_map.get(niche, "dental-demo")
    src_videos = REPO_DIR / template_slug / "videos"
    if not src_videos.exists():
        log.warning("[DEPLOYER] No video source at %s", src_videos)
        return

    dst_videos = demo_dir / "videos"
    dst_videos.mkdir(exist_ok=True)

    for vid in src_videos.iterdir():
        if vid.is_file() and vid.suffix == ".mp4":
            dst = dst_videos / vid.name
            if not dst.exists():
                shutil.copy2(vid, dst)
                log.info("[DEPLOYER] Copied video %s", vid.name)


def _wait_for_push_window() -> None:
    """Wait until enough time has passed since the last push (GitHub Pages cooldown)."""
    if _PUSH_TS_FILE.exists():
        try:
            last_push = float(_PUSH_TS_FILE.read_text().strip())
            elapsed = time.time() - last_push
            if elapsed < _MIN_PUSH_INTERVAL:
                wait = _MIN_PUSH_INTERVAL - elapsed
                log.info("[DEPLOYER] Waiting %.0fs for GitHub Pages cooldown", wait)
                time.sleep(wait)
        except (ValueError, OSError):
            pass


def _record_push() -> None:
    """Record the timestamp of this push."""
    try:
        _PUSH_TS_FILE.write_text(str(time.time()))
    except OSError:
        pass


def _git_commit_push(demo_dir: Path, business_name: str) -> bool:
    """Stage, commit, and push. MUST be called inside git lock."""
    try:
        subprocess.run(
            ["git", "add", str(demo_dir)],
            cwd=REPO_DIR, capture_output=True, timeout=15, check=True,
        )
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=REPO_DIR, capture_output=True, timeout=10,
        )
        if not result.stdout.strip():
            log.info("[DEPLOYER] No changes to commit for %s (already deployed)", business_name)
            return True

        subprocess.run(
            ["git", "commit", "-m", f"Add custom demo: {business_name}"],
            cwd=REPO_DIR, capture_output=True, timeout=15, check=True,
        )
        _wait_for_push_window()
        push_result = subprocess.run(
            ["git", "push", "origin", "main"],
            cwd=REPO_DIR, capture_output=True, timeout=30,
        )
        if push_result.returncode != 0:
            # Retry once: pull --rebase then push again
            log.warning("[DEPLOYER] Push failed for %s, retrying after rebase: %s",
                        business_name, push_result.stderr[:200])
            subprocess.run(
                ["git", "pull", "--rebase", "origin", "main"],
                cwd=REPO_DIR, capture_output=True, timeout=30, check=True,
            )
            subprocess.run(
                ["git", "push", "origin", "main"],
                cwd=REPO_DIR, capture_output=True, timeout=30, check=True,
            )

        _record_push()
        return True
    except subprocess.CalledProcessError as e:
        log.error("[DEPLOYER] git commit/push failed: %s", e.stderr)
        return False


def _verify_deployment(url: str) -> bool:
    """Wait for GitHub Pages to deploy, then verify with HEAD request."""
    for attempt in range(1, _DEPLOY_RETRIES + 1):
        try:
            resp = requests.head(url, timeout=10, allow_redirects=True)
            if resp.status_code == 200:
                log.info("[DEPLOYER] Demo live at %s (attempt %d)", url, attempt)
                return True
            log.info("[DEPLOYER] Attempt %d: HTTP %d for %s", attempt, resp.status_code, url)
        except Exception as e:
            log.info("[DEPLOYER] Attempt %d: %s for %s", attempt, e, url)

        if attempt < _DEPLOY_RETRIES:
            time.sleep(_DEPLOY_WAIT)

    return False


def deploy_demo(
    business_name: str,
    html: str,
    niche: str = "dental",
) -> tuple[str, bool]:
    """Deploy a custom demo to GitHub Pages.

    Uses an exclusive file lock to serialize all git operations across threads.
    This prevents the concurrent-push race condition that causes 'cannot lock ref' errors.

    Returns:
        (demo_url, success) tuple.
    """
    slug = _make_slug(business_name)
    if not slug:
        log.error("[DEPLOYER] Could not generate slug for: %s", business_name)
        return "", False

    demo_url = f"{DEMO_BASE_URL}{slug}/"

    # Acquire exclusive lock — only one thread/process does git ops at a time
    _GIT_LOCK_FILE.touch(exist_ok=True)
    with open(_GIT_LOCK_FILE, "r+") as lock_fd:
        log.info("[DEPLOYER] Acquiring git lock for %s...", business_name)
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        log.info("[DEPLOYER] Got git lock for %s", business_name)
        try:
            # 1. Pull latest
            if not _ensure_repo():
                return "", False

            # 2. Write HTML (after pulling so no conflicts)
            demo_dir = REPO_DIR / slug
            demo_dir.mkdir(exist_ok=True)
            (demo_dir / "index.html").write_text(html, encoding="utf-8")
            log.info("[DEPLOYER] Wrote index.html to %s", demo_dir)

            # 3. Copy videos
            _copy_videos(demo_dir, niche)

            # 4. Commit and push
            if not _git_commit_push(demo_dir, business_name):
                return "", False
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            log.info("[DEPLOYER] Released git lock for %s", business_name)

    # 5. Verify deployment (outside lock — just waiting for GitHub Pages)
    success = _verify_deployment(demo_url)
    if not success:
        log.warning("[DEPLOYER] Deployment verification timed out for %s — "                    "URL may still become available shortly", business_name)
        return demo_url, True

    return demo_url, True
