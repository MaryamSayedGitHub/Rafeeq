"""Lab 5 — Animated video generation from an image or a text prompt.

Uses Alibaba's QwenCloud (formerly DashScope) video-synthesis API with its
"Wan" models:
  - Text only  -> WAN_T2V_MODEL  (default: wan2.6-t2v)
  - + an image -> WAN_I2V_MODEL  (default: wan2.6-i2v-flash, the cheaper
    "flash" variant -- the image becomes the video's first frame and the
    prompt describes how it should move/continue)

Note: QWEN_MODEL/"qwen3.8-max" in .env is a CHAT model (for the lecturer
assistant's text generation) -- it does not do video. Video generation is a
different model family (Wan) on the same QwenCloud account/API key, called
through a different endpoint (video-synthesis instead of chat/completions).

This is an ASYNC, PAID API (billed per second of generated video -- a few
cents per clip at 720P with audio off). A call here only SUBMITS the job and
returns a task_id immediately; the clip itself takes roughly a minute or two
to render. poll_task() is called again later (the dashboard polls it every
few seconds) until the status is no longer "PENDING"/"RUNNING".

Every function degrades to a clear error dict instead of raising, so a
missing key or a transient API error shows up as a message in the teacher
dashboard, not a crashed page.
"""

import base64
import json
import logging
import mimetypes
import os
import urllib.error
import urllib.request

log = logging.getLogger(__name__)

BASE_URL = os.getenv("QWEN_BASE_URL", "https://maas.qwencloudapi.com").rstrip("/")
SYNTHESIS_URL = f"{BASE_URL}/api/v1/services/aigc/video-generation/video-synthesis"
TASK_URL = f"{BASE_URL}/api/v1/tasks/{{task_id}}"

DEFAULT_T2V_MODEL = os.getenv("WAN_T2V_MODEL", "wan2.6-t2v")
DEFAULT_I2V_MODEL = os.getenv("WAN_I2V_MODEL", "wan2.6-i2v-flash")

MAX_DURATION_SECONDS = 6   # kept short on purpose: this is billed per second


def _api_key() -> str | None:
    return os.getenv("DASHSCOPE_API_KEY")


def _post(url: str, body: dict, extra_headers: dict | None = None) -> dict:
    headers = {
        "Authorization": f"Bearer {_api_key()}",
        "Content-Type": "application/json",
        **(extra_headers or {}),
    }
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"),
                                  headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.load(resp)


def _get(url: str) -> dict:
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {_api_key()}"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.load(resp)


def _image_to_data_uri(image_bytes: bytes, filename: str) -> str:
    """The video-synthesis API accepts a public image URL OR a base64 data
    URI -- we use the data URI so the teacher doesn't need to host the image
    anywhere first."""
    mime, _ = mimetypes.guess_type(filename)
    mime = mime or "image/jpeg"
    b64 = base64.b64encode(image_bytes).decode("ascii")
    return f"data:{mime};base64,{b64}"


# ---------------------------------------------------------------------------
# Step 1 — submit the job (returns right away with a task_id)
# ---------------------------------------------------------------------------
def submit_task(
    prompt: str,
    image_bytes: bytes | None = None,
    image_filename: str = "image.jpg",
    duration: int = 5,
    resolution: str = "720P",
) -> dict:
    """Returns {"ok": True, "task_id": ...} or {"ok": False, "error": "..."}."""
    if not _api_key():
        return {"ok": False, "error": "DASHSCOPE_API_KEY is not set in .env"}

    duration = max(2, min(duration, MAX_DURATION_SECONDS))
    body: dict = {
        "input": {"prompt": prompt.strip()[:800]},
        "parameters": {"resolution": resolution, "duration": duration, "prompt_extend": True},
    }

    if image_bytes:
        body["model"] = DEFAULT_I2V_MODEL
        body["input"]["media"] = [{"type": "first_frame", "url": _image_to_data_uri(image_bytes, image_filename)}]
        body["parameters"]["audio"] = False  # keep the cost down (flash model generates audio by default)
    else:
        body["model"] = DEFAULT_T2V_MODEL

    try:
        data = _post(SYNTHESIS_URL, body, extra_headers={"X-DashScope-Async": "enable"})
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:300]
        log.warning("video_gen: submit failed (%s): %s", e.code, detail)
        return {"ok": False, "error": f"HTTP {e.code}: {detail}"}
    except Exception as e:
        log.warning("video_gen: submit failed: %s: %s", type(e).__name__, str(e)[:300])
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}

    task_id = (data.get("output") or {}).get("task_id")
    if not task_id:
        return {"ok": False, "error": f"No task_id in response: {json.dumps(data)[:300]}"}
    return {"ok": True, "task_id": task_id, "model": body["model"]}


# ---------------------------------------------------------------------------
# Step 2 — poll until it's done
# ---------------------------------------------------------------------------
def poll_task(task_id: str) -> dict:
    """Returns {"status": "RUNNING"|"SUCCEEDED"|"FAILED"|"ERROR", "video_url": str|None, "error": str|None}."""
    if not _api_key():
        return {"status": "ERROR", "video_url": None, "error": "DASHSCOPE_API_KEY is not set in .env"}
    try:
        data = _get(TASK_URL.format(task_id=task_id))
    except Exception as e:
        return {"status": "ERROR", "video_url": None, "error": f"{type(e).__name__}: {str(e)[:300]}"}

    output = data.get("output") or {}
    status = output.get("task_status", "UNKNOWN")
    return {
        "status": status,
        "video_url": output.get("video_url"),
        "error": output.get("message") if status in ("FAILED", "ERROR") else None,
    }
