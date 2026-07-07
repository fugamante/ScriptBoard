#!/usr/bin/env python3
"""Generate pending storyboard panels through ChatGPT in Safari.

This is a UI fallback for when the OpenAI Image API is unavailable. It avoids
the stale-image bug by capturing all current ChatGPT estuary image URLs before
submission and extracting only a URL that appears after the prompt is submitted.
"""

from __future__ import annotations

import argparse
import base64
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import time
from typing import Any

from scriptboard.config import load_config


LEDGER = Path("Storyboard_Image_Jobs.json")
DEFAULT_CHATGPT_URL = "https://chatgpt.com/"

DONE_NOTE = (
    "Generated in ChatGPT Safari fallback with URL-delta extraction; saved only "
    "after detecting an estuary image URL not present before prompt submission; "
    "native Safari JavaScript fetch with credentials, FileReader data URL "
    "conversion, and local base64 decode. No screenshot fallback."
)

MIN_ESTUARY_WIDTH = 1000
FALLBACK_ESTUARY_WIDTH = 512

PROMPT_WRAPPER = (
    "Generate one storyboard image from the exact prompt below. "
    "Return an image, not prose. Do not add text overlays.\n\n"
    "{prompt}"
)

REFUSAL_WORDS = (
    "violate our content policies",
    "may violate",
    "guardrails",
    "acceptable depictions",
    "can't help",
    "cannot help",
    "unable to generate",
    "we're so sorry",
    "we\u2019re so sorry",
)

BLOCKER_WORDS = (
    "log in",
    "login",
    "sign in",
    "usage limit",
    "rate limit",
    "quota",
    "try again later",
)

MULTI_IMAGE_NOTE = (
    "ChatGPT exposed multiple fresh image candidates in the same response; the "
    "generator auto-selected the newest candidate in the current chat session "
    "to avoid stalling on a manual pick step. Saved via native Safari "
    "JavaScript extraction with credentials, FileReader data URL conversion, "
    "and local base64 decode. No screenshot fallback."
)


@dataclass
class PageState:
    href: str
    text: str
    composer: str
    composer_count: int
    images: list[dict[str, Any]]

    @property
    def image_urls(self) -> set[str]:
        return {str(item.get("src") or "") for item in self.images if item.get("src")}

    @property
    def has_composer(self) -> bool:
        return self.composer_count > 0


def run(cmd: list[str], *, input_text: str | None = None, timeout: int = 30) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, input=input_text, text=True, capture_output=True, timeout=timeout)


def osa(script: str, *, timeout: int = 30) -> str:
    proc = run(["osascript", "-e", script], timeout=timeout)
    if proc.returncode:
        raise RuntimeError((proc.stderr or proc.stdout).strip())
    return proc.stdout.strip()


def safari_js(code: str, *, timeout: int = 30, attempts: int = 3) -> str:
    script = (
        'tell application "Safari" to do JavaScript '
        f"{json.dumps(code)} in current tab of front window"
    )
    last = ""
    for attempt in range(1, attempts + 1):
        try:
            last = osa(script, timeout=timeout)
            if last:
                return last
        except Exception as exc:
            last = str(exc)
        time.sleep(0.5 * attempt)
    raise RuntimeError(f"Safari JavaScript returned no usable result: {last[:300]}")


def open_chatgpt(url: str) -> None:
    osa(
        'tell application "Safari" to activate\n'
        f'tell application "Safari" to open location {json.dumps(url)}',
        timeout=10,
    )


def page_state() -> PageState:
    raw = safari_js(
        (
            r"""
(() => {
  const isVisible = (el) => {
    const rect = el.getBoundingClientRect();
    const style = window.getComputedStyle(el);
    return rect.width > 20 && rect.height > 10 && style.visibility !== 'hidden' && style.display !== 'none';
  };
  const inConversation = (el) => !!el.closest(
    'main, article, [data-testid*="conversation"], [data-message-author-role]'
  );
  const inForegroundPane = (el) => {
    const pane = el.closest('[role="dialog"], [aria-modal="true"], [data-testid*="modal"], [data-testid*="image"], [class*="modal"]');
    if (!pane) return false;
    const rect = pane.getBoundingClientRect();
    const style = window.getComputedStyle(pane);
    return rect.width > 200 && rect.height > 200 && style.visibility !== 'hidden' && style.display !== 'none';
  };
  const allComposerNodes = Array.from(document.querySelectorAll(
    '.ProseMirror[contenteditable="true"], textarea, [contenteditable="true"]'
  ));
  const composerNodes = allComposerNodes.filter((el) => {
    return isVisible(el);
  });
  const activeComposer = composerNodes[composerNodes.length - 1] || null;
  const composer = activeComposer ? (activeComposer.innerText || activeComposer.value || '') : '';
  const estuaryImages = Array.from(document.images)
    .map((img, idx) => ({
      idx,
      src: img.currentSrc || img.src || '',
      w: img.naturalWidth || 0,
      h: img.naturalHeight || 0,
      displayW: img.getBoundingClientRect().width || 0,
      displayH: img.getBoundingClientRect().height || 0,
      inConversation: inConversation(img),
      inForegroundPane: inForegroundPane(img)
    }))
    .filter((item) =>
      item.src.includes('/backend-api/estuary/content') &&
      item.displayW >= 180 &&
      item.displayH >= 120 &&
      (item.inConversation || item.inForegroundPane)
    );
  const preferredImages = estuaryImages.filter((item) => item.w >= __MIN_ESTUARY_WIDTH__);
  const fallbackImages = estuaryImages.filter((item) => item.w >= __FALLBACK_ESTUARY_WIDTH__);
  const images = preferredImages.length ? preferredImages : fallbackImages;
  return JSON.stringify({
    href: location.href,
    text: document.body.innerText.slice(-6000),
    composer,
    composerCount: composerNodes.length,
    images
  });
})()
"""
        )
        .replace("__MIN_ESTUARY_WIDTH__", str(MIN_ESTUARY_WIDTH))
        .replace("__FALLBACK_ESTUARY_WIDTH__", str(FALLBACK_ESTUARY_WIDTH)),
        timeout=10,
        attempts=5,
    )
    data = json.loads(raw)
    return PageState(
        href=str(data.get("href") or ""),
        text=str(data.get("text") or ""),
        composer=str(data.get("composer") or ""),
        composer_count=int(data.get("composerCount") or 0),
        images=list(data.get("images") or []),
    )


def wait_ready(timeout_s: int) -> PageState:
    deadline = time.time() + timeout_s
    last = ""
    while time.time() < deadline:
        try:
            state = page_state()
            last = state.text[:500]
            body = state.text.lower()
            if "gateway time-out" in body:
                raise RuntimeError("ChatGPT gateway time-out detected")
            if ("log in" in body or "sign in" in body) and not state.has_composer:
                raise RuntimeError("ChatGPT login/sign-in blocker detected")
            if "chatgpt.com" in state.href and state.has_composer:
                return state
        except Exception as exc:
            last = str(exc)
        time.sleep(2)
    raise RuntimeError(f"ChatGPT composer not ready: {last[:500]}")


def focus_composer() -> None:
    result = safari_js(
        r"""
(() => {
  const nodes = Array.from(document.querySelectorAll(
    '.ProseMirror[contenteditable="true"], textarea, [contenteditable="true"]'
  )).filter((candidate) => {
    const rect = candidate.getBoundingClientRect();
    const style = window.getComputedStyle(candidate);
    return rect.width > 20 && rect.height > 10 && style.visibility !== 'hidden' && style.display !== 'none';
  });
  const el = nodes[nodes.length - 1];
  if (!el) return 'missing';
  el.focus();
  return 'focused';
})()
""",
        timeout=10,
    )
    if "missing" in result:
        raise RuntimeError("ChatGPT composer missing")


def set_composer_text(text: str) -> bool:
    result = safari_js(
        f"""
(text => {{
  const nodes = Array.from(document.querySelectorAll(
    '.ProseMirror[contenteditable="true"], textarea, [contenteditable="true"]'
  )).filter((candidate) => {{
    const rect = candidate.getBoundingClientRect();
    const style = window.getComputedStyle(candidate);
    return rect.width > 20 && rect.height > 10 && style.visibility !== 'hidden' && style.display !== 'none';
  }});
  const el = nodes[nodes.length - 1];
  if (!el) return 'missing';
  el.focus();
  if (el.tagName === 'TEXTAREA' || el.tagName === 'INPUT') {{
    el.value = text;
    el.dispatchEvent(new Event('input', {{bubbles: true}}));
    el.dispatchEvent(new Event('change', {{bubbles: true}}));
    return 'set-control';
  }}
  const selection = window.getSelection();
  const range = document.createRange();
  range.selectNodeContents(el);
  selection.removeAllRanges();
  selection.addRange(range);
  document.execCommand('insertText', false, text);
  el.dispatchEvent(new InputEvent('input', {{
    bubbles: true,
    cancelable: true,
    inputType: 'insertText',
    data: text
  }}));
  return 'set-editable';
}})({json.dumps(text)})
""",
        timeout=20,
    )
    return result in {"set-control", "set-editable"}


def click_send_button() -> bool:
    result = safari_js(
        r"""
(() => {
  const composers = Array.from(document.querySelectorAll(
    '.ProseMirror[contenteditable="true"], textarea, [contenteditable="true"]'
  )).filter((candidate) => {
    const rect = candidate.getBoundingClientRect();
    const style = window.getComputedStyle(candidate);
    return rect.width > 20 && rect.height > 10 && style.visibility !== 'hidden' && style.display !== 'none';
  });
  const composer = composers[composers.length - 1];
  const root = composer ? (composer.closest('form') || document) : document;
  const selectors = [
    'button[data-testid="send-button"]',
    'button[aria-label*="Send"]',
    'button[aria-label*="send"]',
    'form button[type="submit"]'
  ];
  for (const selector of selectors) {
    const button = root.querySelector(selector);
    if (!button) continue;
    const disabled = button.disabled || button.getAttribute('aria-disabled') === 'true';
    if (disabled) continue;
    button.click();
    return 'clicked';
  }
  return 'missing';
})()
""",
        timeout=10,
    )
    return "clicked" in result


def submit_via_dom() -> bool:
    result = safari_js(
        r"""
(() => {
  const composers = Array.from(document.querySelectorAll(
    '.ProseMirror[contenteditable="true"], textarea, [contenteditable="true"]'
  )).filter((candidate) => {
    const rect = candidate.getBoundingClientRect();
    const style = window.getComputedStyle(candidate);
    return rect.width > 20 && rect.height > 10 && style.visibility !== 'hidden' && style.display !== 'none';
  });
  const composer = composers[composers.length - 1];
  if (!composer) return 'missing-composer';

  const form = composer.closest('form');
  if (form) {
    const submitter = form.querySelector(
      'button[data-testid="send-button"]:not([disabled]), ' +
      'button[aria-label*="Send"]:not([disabled]), ' +
      'button[aria-label*="send"]:not([disabled]), ' +
      'button[type="submit"]:not([disabled])'
    );
    if (submitter) {
      submitter.click();
      return 'clicked-submit';
    }
    if (typeof form.requestSubmit === 'function') {
      form.requestSubmit();
      return 'requested-submit';
    }
  }

  for (const type of ['keydown', 'keypress', 'keyup']) {
    composer.dispatchEvent(new KeyboardEvent(type, {
      key: 'Enter',
      code: 'Enter',
      keyCode: 13,
      which: 13,
      bubbles: true,
      cancelable: true
    }));
  }
  return 'enter-dispatched';
})()
""",
        timeout=10,
    )
    return result in {"clicked-submit", "requested-submit", "enter-dispatched"}


def trigger_submit() -> str:
    if click_send_button():
        return "send-button"
    if submit_via_dom():
        return "dom-submit"
    raise RuntimeError("Unable to submit prompt through ChatGPT DOM controls")


def submitted_visible(expected: str) -> bool:
    state = page_state()
    return expected in state.text


def submit_prompt(prompt: str) -> None:
    expected = prompt[:80]

    print("  setting composer text through DOM", flush=True)
    focus_composer()
    if not set_composer_text(prompt):
        raise RuntimeError("Prompt did not appear in composer after DOM injection attempt")
    time.sleep(1)
    text = page_state().composer.strip()
    if expected not in text:
        raise RuntimeError("Prompt did not appear in composer after DOM injection attempt")

    submit_method = trigger_submit()
    time.sleep(3)
    if expected not in page_state().composer.strip():
        return
    print(f"  initial submit via {submit_method} did not clear composer; retrying", flush=True)

    for attempt in range(1, 5):
        submit_method = trigger_submit()
        time.sleep(4)
        text = page_state().composer.strip()
        if expected not in text:
            return
        print(
            f"  composer still holds prompt after submit attempt {attempt}; retried via {submit_method}",
            flush=True,
        )

    if expected in page_state().composer:
        raise RuntimeError("Prompt remained in composer after repeated Return attempts")


def click_image_choice(src: str) -> bool:
    result = safari_js(
        f"""
(src => {{
  const match = Array.from(document.images).find((img) => (img.currentSrc || img.src || '') === src);
  if (!match) return 'missing';
  const target = match.closest('button,[role="button"],a') || match;
  target.click();
  return 'clicked';
}})({json.dumps(src)})
""",
        timeout=10,
    )
    return "clicked" in result


def close_foreground_pane() -> None:
    try:
        safari_js(
            r"""
(() => {
  const selectors = [
    '[role="dialog"] button[aria-label*="Close"]',
    '[aria-modal="true"] button[aria-label*="Close"]',
    '[data-testid*="modal"] button[aria-label*="Close"]',
    'button[aria-label="Close"]'
  ];
  for (const selector of selectors) {
    const button = document.querySelector(selector);
    if (!button) continue;
    const rect = button.getBoundingClientRect();
    if (rect.width <= 0 || rect.height <= 0) continue;
    button.click();
    return 'closed';
  }
  document.dispatchEvent(new KeyboardEvent('keydown', {
    key: 'Escape',
    code: 'Escape',
    keyCode: 27,
    which: 27,
    bubbles: true,
    cancelable: true
  }));
  return 'escape';
})()
""",
            timeout=10,
            attempts=1,
        )
    except Exception:
        pass


def wait_choice_resolution(seen_urls: set[str], chosen_src: str, timeout_s: int) -> tuple[str, dict[str, Any] | None, PageState]:
    deadline = time.time() + timeout_s
    last = page_state()
    while time.time() < deadline:
        state = page_state()
        last = state
        body = state.text.lower()
        new_images = [item for item in state.images if item.get("src") not in seen_urls]
        if any(word in body for word in REFUSAL_WORDS):
            return "refusal", None, state
        if any(word in body for word in BLOCKER_WORDS):
            return "blocker", None, state
        if "gateway time-out" in body:
            return "gateway", None, state
        resolved = next((item for item in new_images if item.get("src") == chosen_src), None)
        if resolved:
            return "image", resolved, state
        if new_images:
            return "image", new_images[-1], state
        time.sleep(2)
    return "timeout", None, last


def wait_new_image(seen_urls: set[str], timeout_s: int) -> tuple[str, dict[str, Any] | None, PageState, bool]:
    deadline = time.time() + timeout_s
    last = page_state()
    while time.time() < deadline:
        state = page_state()
        last = state
        body = state.text.lower()
        new_images = [item for item in state.images if item.get("src") not in seen_urls]
        if len(new_images) >= 2:
            chosen = new_images[-1]
            print(f"  detected {len(new_images)} fresh image candidates; selecting newest", flush=True)
            if click_image_choice(str(chosen.get("src") or "")):
                time.sleep(2)
                return (*wait_choice_resolution(seen_urls, str(chosen.get("src") or ""), timeout_s=30), True)
            return "image", chosen, state, True
        if new_images:
            return "image", new_images[-1], state, False
        if any(word in body for word in REFUSAL_WORDS):
            return "refusal", None, state, False
        if any(word in body for word in BLOCKER_WORDS):
            return "blocker", None, state, False
        if "gateway time-out" in body:
            return "gateway", None, state, False
        time.sleep(5)
    return "timeout", None, last, False


def extract_image_url(src: str, timeout_s: int) -> bytes:
    safari_js(
        f"""
(src => {{
  window.__codexImageExtract = {{status: 'running'}};
  (async () => {{
    try {{
      const res = await fetch(src, {{credentials: 'include'}});
      if (!res.ok) throw new Error('fetch failed ' + res.status);
      const blob = await res.blob();
      const dataUrl = await new Promise((resolve, reject) => {{
        const reader = new FileReader();
        reader.onload = () => resolve(reader.result);
        reader.onerror = () => reject(reader.error || new Error('FileReader failed'));
        reader.readAsDataURL(blob);
      }});
      window.__codexImageExtract = {{status: 'done', dataUrl}};
    }} catch (err) {{
      window.__codexImageExtract = {{status: 'error', error: String(err && err.message || err)}};
    }}
  }})();
  return 'started';
}})({json.dumps(src)})
""",
        timeout=10,
    )

    deadline = time.time() + timeout_s
    while time.time() < deadline:
        raw = safari_js(
            "JSON.stringify(window.__codexImageExtract || {status: 'missing'})",
            timeout=10,
        )
        data = json.loads(raw)
        if data.get("status") == "done":
            match = re.match(r"data:image/(?:png|jpeg|webp);base64,(.*)", data["dataUrl"], re.S)
            if not match:
                raise RuntimeError("Unexpected image data URL format")
            return base64.b64decode(match.group(1))
        if data.get("status") == "error":
            raise RuntimeError(str(data.get("error") or "image extraction failed"))
        time.sleep(1)
    raise RuntimeError("Image extraction timed out")


def image_hashes(raw: dict[str, Any]) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for job in raw["jobs"]:
        path = Path(str(job.get("image_path") or ""))
        if job.get("status") == "done" and path.exists():
            hashes[hashlib.sha256(path.read_bytes()).hexdigest()] = str(path)
    return hashes


def inspect_visible_images(chatgpt_url: str, ledger_path: Path = LEDGER) -> int:
    raw = json.loads(ledger_path.read_text(encoding="utf-8"))
    known = image_hashes(raw)

    open_chatgpt(chatgpt_url)
    state = wait_ready(timeout_s=90)
    if not state.images:
        print(json.dumps({"visible_images": 0, "images": []}, indent=2))
        return 0

    report_images: list[dict[str, Any]] = []
    for index, image in enumerate(state.images, start=1):
        src = str(image.get("src") or "")
        data = extract_image_url(src, timeout_s=90)
        digest = hashlib.sha256(data).hexdigest()
        matched_path = known.get(digest)
        report_images.append(
            {
                "index": index,
                "width": image.get("w"),
                "height": image.get("h"),
                "src": src,
                "sha256": digest,
                "saved_locally": bool(matched_path),
                "saved_path": matched_path,
                "status": "saved_panel" if matched_path else "ui_only_unsaved",
            }
        )

    report = {
        "visible_images": len(report_images),
        "images": report_images,
    }
    print(json.dumps(report, indent=2))
    return 0


def save_ledger(raw: dict[str, Any], ledger_path: Path = LEDGER) -> None:
    jobs = raw["jobs"]
    raw["summary"] = {
        "total": len(jobs),
        "pending": sum(1 for job in jobs if job.get("status") != "done"),
        "done": sum(1 for job in jobs if job.get("status") == "done"),
    }
    raw["generated_at"] = datetime.now(timezone.utc).isoformat()
    ledger_path.write_text(json.dumps(raw, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def pending_jobs(raw: dict[str, Any], *, include_timeouts: bool = False) -> list[dict[str, Any]]:
    jobs = [
        job
        for job in raw["jobs"]
        if job.get("status") != "done"
        and not Path(str(job.get("image_path") or "")).exists()
        and (include_timeouts or "URL-delta timeout" not in str(job.get("notes") or ""))
    ]
    scene_totals: dict[str, int] = {}
    scene_pending: dict[str, int] = {}
    for job in raw["jobs"]:
        scene_id = str(job.get("scene_id") or "")
        scene_totals[scene_id] = scene_totals.get(scene_id, 0) + 1
    for job in jobs:
        scene_id = str(job.get("scene_id") or "")
        scene_pending[scene_id] = scene_pending.get(scene_id, 0) + 1

    def scene_num(scene_id: str) -> int:
        match = re.match(r"scene_(\d+)_", scene_id)
        return int(match.group(1)) if match else 0

    def sort_key(job: dict[str, Any]) -> tuple[float, int, int]:
        scene_id = str(job.get("scene_id") or "")
        total = scene_totals.get(scene_id, 1)
        pending_ratio = scene_pending.get(scene_id, 0) / total
        return (-pending_ratio, scene_num(scene_id), int(job.get("panel_index") or 0))

    return sorted(jobs, key=sort_key)


def run_batch(
    limit: int,
    wait_timeout: int,
    chatgpt_url: str,
    include_timeouts: bool,
    continue_on_timeout: bool,
    ledger_path: Path = LEDGER,
) -> int:
    raw = json.loads(ledger_path.read_text(encoding="utf-8"))
    selected = pending_jobs(raw, include_timeouts=include_timeouts)[:limit]
    completed = 0
    refused = 0
    skipped_duplicate = 0
    timed_out = 0

    print(f"Selected {len(selected)} Safari URL-delta jobs", flush=True)
    open_chatgpt(chatgpt_url)
    current_state = wait_ready(timeout_s=90)
    for index, job in enumerate(selected, start=1):
        print(f"[{index}/{len(selected)}] {job['id']}", flush=True)
        state = current_state
        if not state.has_composer:
            raise RuntimeError("ChatGPT session lost its composer during batch")
        seen_urls = state.image_urls

        submitted_prompt = PROMPT_WRAPPER.format(prompt=str(job["prompt"]))
        submit_prompt(submitted_prompt)
        status, image, end_state, used_choice = wait_new_image(seen_urls, timeout_s=wait_timeout)
        current_state = end_state

        if status == "image" and image:
            data = extract_image_url(str(image["src"]), timeout_s=90)
            digest = hashlib.sha256(data).hexdigest()
            known = image_hashes(raw)
            if digest in known:
                job["updated_at"] = datetime.now(timezone.utc).isoformat()
                job["notes"] = (
                    "Generated image matched an existing referenced panel hash "
                    f"({known[digest]}); output was not saved and job remains pending."
                )
                save_ledger(raw, ledger_path)
                skipped_duplicate += 1
                print(f"  duplicate hash matched {known[digest]}; left pending", flush=True)
                continue

            output = Path(str(job["image_path"]))
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(data)
            job["status"] = "done"
            job["output_path"] = str(output)
            job["updated_at"] = datetime.now(timezone.utc).isoformat()
            job["notes"] = MULTI_IMAGE_NOTE if used_choice else DONE_NOTE
            save_ledger(raw, ledger_path)
            close_foreground_pane()
            current_state = page_state()
            completed += 1
            print(f"  wrote {output} ({image.get('w')}x{image.get('h')})", flush=True)
            continue

        if status == "refusal":
            job["updated_at"] = datetime.now(timezone.utc).isoformat()
            job["notes"] = "ChatGPT Safari fallback refused this prompt; left pending for prompt revision."
            save_ledger(raw, ledger_path)
            refused += 1
            print("  prompt-specific refusal; left pending", flush=True)
            continue

        if status == "gateway":
            raise RuntimeError("ChatGPT returned a gateway timeout during generation")
        if status == "blocker":
            raise RuntimeError(f"ChatGPT UI-wide blocker: {end_state.text[-700:]}")
        job["updated_at"] = datetime.now(timezone.utc).isoformat()
        job["notes"] = (
            "URL-delta timeout: ChatGPT did not expose a new estuary image URL "
            "after submission; left pending and skipped for later manual retry."
        )
        save_ledger(raw, ledger_path)
        timed_out += 1
        print(f"  timeout waiting for new image; left pending: {job['id']}", flush=True)
        if continue_on_timeout:
            close_foreground_pane()
            current_state = page_state()
            continue
        raise RuntimeError(f"Timed out waiting for new image for {job['id']}")

    print(
        json.dumps(
            {
                "completed": completed,
                "refused": refused,
                "skipped_duplicate": skipped_duplicate,
                "timed_out": timed_out,
                "selected": len(selected),
            },
            indent=2,
        ),
        flush=True,
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, help="Optional ScriptBoard_Config.json path.")
    parser.add_argument("--jobs", type=Path, help="Storyboard image-job ledger path.")
    parser.add_argument("--limit", type=int, default=6)
    parser.add_argument("--wait-timeout", type=int, default=360)
    parser.add_argument("--chatgpt-url", default=DEFAULT_CHATGPT_URL)
    parser.add_argument("--include-timeouts", action="store_true")
    parser.add_argument(
        "--continue-on-timeout",
        action="store_true",
        help="Leave timed-out jobs pending and continue through the selected batch.",
    )
    parser.add_argument(
        "--inspect-visible-images",
        action="store_true",
        help="Inspect currently visible ChatGPT estuary images and report whether each is already saved locally.",
    )
    args = parser.parse_args()
    config = load_config(args.config, base_dir=Path.cwd())
    ledger_path = (args.jobs or Path(config.outputs.image_jobs)).expanduser()
    if not ledger_path.is_absolute():
        ledger_path = Path.cwd() / ledger_path
    if args.inspect_visible_images:
        return inspect_visible_images(args.chatgpt_url, ledger_path)
    return run_batch(
        limit=args.limit,
        wait_timeout=args.wait_timeout,
        chatgpt_url=args.chatgpt_url,
        include_timeouts=args.include_timeouts,
        continue_on_timeout=args.continue_on_timeout,
        ledger_path=ledger_path,
    )


if __name__ == "__main__":
    raise SystemExit(main())
