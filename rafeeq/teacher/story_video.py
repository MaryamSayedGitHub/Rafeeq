"""Multi-scene story videos (about 30 seconds) for the Visual & Media Studio.

The video model (Wan) makes one clip of at most a few seconds, so a longer video is a chain:

  1. plan_story()    a text LLM writes ONE character description, ONE setting and N scenes
                     (visual prompt + narration). The same character/setting/style text is repeated
                     in every scene prompt: this is what keeps the look stable.
  2. advance()       one small step per call (the page polls every few seconds): submit scene 1,
                     wait, save the clip, take its LAST FRAME and submit scene 2 with that frame as
                     the first frame (image-to-video) ... so each scene continues the previous one.
  3. stitch()        ffmpeg joins the clips (cross-fade or hard cut), optional narration track.

State lives in the asset record (settings.story): no new storage. The finished video is the asset's
file (kind generated_video), so it appears in My Library like every other video.

Honest limits: continuity is good for background and colours, not perfect for faces/hands over six
hops; every scene is a paid video job; ffmpeg must be installed.
"""

import base64
import hashlib
import json
import logging
import os
import re
import secrets
import shutil
import subprocess
import tempfile
import threading
import urllib.request
from pathlib import Path

from rafeeq.teacher import assets as asset_lib
from rafeeq.teacher import media_tools
from rafeeq.teacher.lecturer import video_gen

log = logging.getLogger(__name__)

MIN_SCENES, MAX_SCENES, DEFAULT_SCENES = 2, 8, 6
SCENE_SECONDS = 5
FADE_SECONDS = 0.5
FFMPEG_TIMEOUT = 600

STYLES = {
    "storybook": "Warm hand-painted children's storybook illustration, soft watercolor textures, gentle light",
    "flat": "Clean flat vector illustration, bold simple shapes, bright educational colour palette",
    "clay": "Soft 3D clay-animation look, rounded friendly shapes, studio lighting",
    "realistic": "Realistic documentary footage, natural light, shallow depth of field, 4K detail",
}

_locks: dict[str, threading.Lock] = {}


class StoryError(ValueError):
    """Bad input, a missing tool, or a failed step (the message is shown to the teacher)."""


# ------------------------------------------------------------------ planning
def _extract_json(text: str):
    """The first JSON object in an LLM answer (drops <think> blocks and code fences)."""
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S)
    start = text.find("{")
    if start == -1:
        raise StoryError("The planner did not return a story")
    try:
        data, _ = json.JSONDecoder().raw_decode(text[start:])
    except ValueError:
        raise StoryError("The planner returned a story that could not be read") from None
    return data


def _clean(value, limit: int) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def plan_story(topic: str, scenes: int = DEFAULT_SCENES, language: str = "ar", style: str = "storybook", llm=None) -> dict:
    """{'style','character','setting','scenes':[{'visual','narration'}]}. Raises StoryError."""
    topic = _clean(topic, 400)
    if len(topic) < 3:
        raise StoryError("Write what the video should explain")
    if style not in STYLES:
        raise StoryError("Unknown style")
    scenes = max(MIN_SCENES, min(MAX_SCENES, int(scenes)))
    if llm is None:
        from rafeeq.teacher.lecturer.llm import get_llm
        llm = get_llm(provider=os.getenv("STORY_LLM_PROVIDER") or None, temperature=0.6)
    lang = "Arabic" if language == "ar" else "English"
    prompt = (
        f"Plan a short educational animated video of exactly {scenes} scenes (about {SCENE_SECONDS} seconds each) "
        f"that explains: {topic}\n"
        "Rules:\n"
        "- 'character': ONE fixed visual description (age, clothes, colours) of the main character or subject; "
        "it will be repeated in every scene.\n"
        "- 'setting': ONE fixed place and colour palette.\n"
        "- each scene: 'visual' = what the camera sees and how things move (English, concrete, no text on screen); "
        f"'narration' = one short sentence of at most 22 words, in {lang}, explaining that moment.\n"
        "Answer with JSON only: "
        '{"character": "...", "setting": "...", "scenes": [{"visual": "...", "narration": "..."}]}')
    try:
        raw = llm.invoke(prompt)
        data = _extract_json(getattr(raw, "content", raw))
    except StoryError:
        raise
    except Exception as e:
        raise StoryError(f"The planner is not available ({type(e).__name__})") from None
    rows = [r for r in data.get("scenes", []) if isinstance(r, dict) and _clean(r.get("visual"), 10)]
    if len(rows) < MIN_SCENES:
        raise StoryError("The planner returned too few scenes")
    return {
        "style": style,
        "character": _clean(data.get("character"), 300),
        "setting": _clean(data.get("setting"), 200),
        "scenes": [{"visual": _clean(r.get("visual"), 300), "narration": _clean(r.get("narration"), 200)} for r in rows[:scenes]],
    }


def scene_prompt(story: dict, index: int, continuity: str = "") -> str:
    """The text sent to the video model for one scene. Style, character and setting come first
    (the model weighs the start most); every scene repeats them."""
    parts = [STYLES.get(story.get("style"), STYLES["storybook"]) + ".",
             f"Main character: {story.get('character', '')}." if story.get("character") else "",
             f"Setting: {story.get('setting', '')}." if story.get("setting") else "",
             f"Scene {index + 1} of {len(story['scenes'])}: {story['scenes'][index]['visual']}.",
             f"The previous scene ended like this: {continuity}." if continuity else "",
             "Keep exactly the same character design, colours and art style. Smooth slow camera motion. "
             "No text, captions or watermarks."]
    return " ".join(p for p in parts if p)[:780]


# ------------------------------------------------------------------ ffmpeg
def _exe(name: str) -> str:
    path = shutil.which(name)
    if path is None:
        raise StoryError("ffmpeg is not installed on the server, so story videos cannot be joined. "
                         "Install ffmpeg (https://ffmpeg.org) and restart Rafeeq.")
    return path


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    try:
        done = subprocess.run(cmd, capture_output=True, text=True, timeout=FFMPEG_TIMEOUT)
    except subprocess.TimeoutExpired:
        raise StoryError("ffmpeg took too long and was stopped") from None
    if done.returncode != 0:
        raise StoryError("ffmpeg failed: " + (done.stderr or "unknown error").strip()[-200:])
    return done


def probe(path: Path) -> tuple[float, int, int]:
    """(seconds, width, height) of a video; sensible defaults if ffprobe cannot tell."""
    try:
        out = _run([_exe("ffprobe"), "-v", "error", "-select_streams", "v:0", "-show_entries",
                    "stream=width,height:format=duration", "-of", "json", str(path)]).stdout
        data = json.loads(out)
        stream = (data.get("streams") or [{}])[0]
        return float(data["format"]["duration"]), int(stream.get("width") or 1280), int(stream.get("height") or 720)
    except (StoryError, KeyError, ValueError, TypeError):
        return float(SCENE_SECONDS), 1280, 720


def stitch_filter(durations: list[float], width: int, height: int, fade: float) -> tuple[str, str]:
    """ffmpeg filter_complex that joins the clips: every clip is scaled/padded to the same size and
    frame rate, then cross-faded (fade > 0) or cut (fade == 0). Returns (filter, output label)."""
    n = len(durations)
    norm = [f"[{i}:v]fps=24,scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,format=yuv420p[v{i}]" for i in range(n)]
    if n == 1:
        return ";".join(norm) + ";[v0]null[out]", "[out]"
    if fade <= 0:
        return ";".join(norm) + ";" + "".join(f"[v{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=0[out]", "[out]"
    parts, last, elapsed = list(norm), "v0", 0.0
    for i in range(1, n):
        elapsed += durations[i - 1]
        offset = max(0.0, elapsed - i * fade)
        label = "out" if i == n - 1 else f"x{i}"
        parts.append(f"[{last}][v{i}]xfade=transition=fade:duration={fade:g}:offset={offset:.3f}[{label}]")
        last = label
    return ";".join(parts), "[out]"


def stitch(clips: list[Path], dst: Path, fade: float = FADE_SECONDS, narration: Path | None = None) -> Path:
    """Join the clips into dst (mp4, h264). With narration (mp3) it becomes the audio track; the video
    length wins: a longer narration is cut at the end of the picture."""
    if not clips:
        raise StoryError("There are no clips to join")
    exe = _exe("ffmpeg")
    durations = []
    for c in clips:
        sec, w, h = probe(c)
        durations.append(sec)
        if c is clips[0]:
            width, height = w - w % 2, h - h % 2
    graph, label = stitch_filter(durations, width, height, fade)
    cmd = [exe, "-y", "-hide_banner", "-loglevel", "error"]
    for c in clips:
        cmd += ["-i", str(c)]
    if narration is not None:
        cmd += ["-i", str(narration)]
    cmd += ["-filter_complex", graph, "-map", label]
    if narration is not None:
        cmd += ["-map", f"{len(clips)}:a", "-c:a", "aac", "-shortest"]
    cmd += ["-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(dst)]
    _run(cmd)
    if not dst.is_file() or dst.stat().st_size == 0:
        raise StoryError("The joined video is empty")
    return dst


def last_frame(clip: Path, dst: Path) -> Path:
    """The final picture of a clip (becomes the first frame of the next scene)."""
    _run([_exe("ffmpeg"), "-y", "-hide_banner", "-loglevel", "error", "-sseof", "-0.2", "-i", str(clip),
          "-frames:v", "1", "-update", "1", "-q:v", "2", str(dst)])
    if not dst.is_file() or dst.stat().st_size == 0:
        raise StoryError("Could not read the last frame of the clip")
    return dst


def to_gif(src: Path, dst: Path, start: float = 0.0, end: float | None = None, fps: int = 12, width: int = 480) -> Path:
    """A short looping GIF (palette-optimised so the colours stay clean) from a video."""
    cmd = [_exe("ffmpeg"), "-y", "-hide_banner", "-loglevel", "error"]
    if start:
        cmd += ["-ss", f"{start:.3f}"]
    if end:
        cmd += ["-to", f"{end:.3f}"]
    cmd += ["-i", str(src), "-vf",
            f"fps={int(fps)},scale={int(width)}:-1:flags=lanczos,split[a][b];[a]palettegen=stats_mode=diff[p];"
            "[b][p]paletteuse=dither=bayer:bayer_scale=4", "-loop", "0", str(dst)]
    _run(cmd)
    if not dst.is_file() or dst.stat().st_size == 0:
        raise StoryError("The GIF could not be made")
    return dst


# ------------------------------------------------------------------ optional local vision (Ollama)
def describe_frame(png: bytes) -> str:
    """One sentence about a picture from a local vision model (Ollama, e.g. qwen2.5vl:7b), used as the
    'previous scene ended like this' line of the next prompt. '' when Ollama is not reachable."""
    base = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
    body = {"model": os.getenv("OLLAMA_VL_MODEL", "qwen2.5vl:7b"), "stream": False,
            "messages": [{"role": "user", "images": [base64.b64encode(png).decode("ascii")],
                          "content": "In one English sentence of at most 30 words, describe the main character "
                                     "(clothes, colours), what they are doing, and the background."}]}
    try:
        req = urllib.request.Request(base + "/api/chat", data=json.dumps(body).encode(), method="POST",
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=90) as resp:
            return _clean(json.load(resp).get("message", {}).get("content"), 300)
    except Exception as e:
        log.info("story_video: vision note skipped (%s)", type(e).__name__)
        return ""


# ------------------------------------------------------------------ the chain
def story_key(teacher_id: str, topic: str, scenes: int, style: str, language: str, voice: str, fade: bool) -> str:
    digest = hashlib.sha1(f"{topic.strip()}|{scenes}|{style}|{language}|{voice}|{fade}".encode()).hexdigest()[:16]
    return f"story:{digest}"


def start_story(store, teacher_id: str, topic: str, *, scenes: int = DEFAULT_SCENES, style: str = "storybook",
                language: str = "ar", voice: str = "", fade: bool = True, vision: bool = False,
                room_id: str = "", llm=None, retry: bool = False) -> dict:
    """Plan the story and create the pending library video. The same request returns the same video
    (no second payment); a failed one is restarted only with retry=True."""
    scenes = max(MIN_SCENES, min(MAX_SCENES, int(scenes)))
    if voice and voice not in media_tools.VOICES:
        raise StoryError("Unknown voice")
    if not os.getenv("DASHSCOPE_API_KEY"):
        raise StoryError("DASHSCOPE_API_KEY is not set in .env")
    key = story_key(teacher_id, topic, scenes, style, language, voice, fade)
    existing = asset_lib.find_by_key(store, teacher_id, key)
    if existing and not (existing["status"] == "failed" and retry) and not asset_lib.is_stale_pending(existing, minutes=240):
        return existing
    plan = plan_story(topic, scenes, language, style, llm=llm)
    story = {**plan, "seed": secrets.randbelow(2_000_000_000), "topic": _clean(topic, 400), "voice": voice, "fade": bool(fade), "vision": bool(vision),
             "scenes": [{**s, "state": "todo", "task_id": "", "clip": "", "frame": "", "note": ""} for s in plan["scenes"]]}
    settings = {"story": story, "duration": SCENE_SECONDS * len(story["scenes"])}
    if existing:
        return asset_lib.update_asset(store, teacher_id, existing["asset_id"], status="pending", error="", settings=settings)
    return asset_lib.register_asset(
        store, teacher_id, kind="generated_video", title=_clean(topic, 80), origin="ai_generated",
        provider="qwencloud", model=video_gen.DEFAULT_I2V_MODEL, settings_used=settings, status="pending",
        room_id=room_id, idempotency_key=key)


def story_view(asset: dict) -> dict:
    story = (asset.get("settings") or {}).get("story") or {}
    scenes = story.get("scenes", [])
    done = sum(1 for s in scenes if s["state"] == "done")
    return {"asset_id": asset["asset_id"], "title": asset["title"], "status": asset["status"], "error": asset.get("error", ""),
            "scene_count": len(scenes), "scenes_done": done, "style": story.get("style", ""),
            "topic": story.get("topic", ""), "voice": story.get("voice", ""), "fade": bool(story.get("fade", True)),
            "vision": bool(story.get("vision", False)), "narrated": bool(story.get("narrated", False)),
            "scenes": [{"n": i + 1, "state": s["state"], "narration": s.get("narration", ""), "visual": s.get("visual", "")}
                       for i, s in enumerate(scenes)],
            "file_url": f"/teacher/assets/{asset['asset_id']}/file" if asset["status"] == "ready" and asset_lib.asset_file(asset) else None}


def _path(ref: str) -> Path:
    return asset_lib._resolve("assets", ref)


def _fail(store, teacher_id, asset, story, message: str) -> dict:
    return asset_lib.update_asset(store, teacher_id, asset["asset_id"], status="failed", error=message[:300],
                                  settings={**asset["settings"], "story": story})


def advance(store, teacher_id: str, asset_id: str) -> dict | None:
    """Do the next small step of the chain and return the (updated) asset. Safe to call repeatedly:
    nothing happens while a scene is still rendering, and a finished story is returned as it is."""
    lock = _locks.setdefault(asset_id, threading.Lock())
    if not lock.acquire(blocking=False):
        return asset_lib.get_asset(store, teacher_id, asset_id)          # another request is already advancing it
    try:
        asset = asset_lib.get_asset(store, teacher_id, asset_id)
        if asset is None or asset["status"] != "pending":
            return asset
        story = (asset.get("settings") or {}).get("story")
        if not story:
            return asset
        scenes = story["scenes"]
        i = next((k for k, s in enumerate(scenes) if s["state"] != "done"), None)
        if i is None:
            return _finish(store, teacher_id, asset, story)
        s = scenes[i]

        if s["state"] == "todo":
            first = None
            if i > 0:
                first = _path(scenes[i - 1]["frame"]).read_bytes()
            prompt = scene_prompt(story, i, scenes[i - 1].get("note", "") if i else "")
            result = video_gen.submit_task(prompt, first, "frame.jpg", duration=SCENE_SECONDS,
                                           prompt_extend=False, seed=story.get("seed"))
            if not result["ok"]:
                return _fail(store, teacher_id, asset, story, f"Scene {i + 1} could not start: {result['error']}")
            s.update(state="running", task_id=result["task_id"], prompt=prompt)
        else:
            result = video_gen.poll_task(s["task_id"])
            if result["status"] in ("FAILED", "CANCELED", "ERROR"):
                return _fail(store, teacher_id, asset, story, f"Scene {i + 1} failed: {result['error'] or result['status']}")
            if result["status"] != "SUCCEEDED" or not result["video_url"]:
                return asset                                              # still rendering
            try:
                _, clip_ref = asset_lib.save_file(teacher_id, asset_id, video_gen.download_video(result["video_url"]), f"scene_{i + 1:02d}.mp4")
                with tempfile.TemporaryDirectory() as tmp:
                    frame = last_frame(_path(clip_ref), Path(tmp) / "last.jpg")
                    frame_bytes = frame.read_bytes()
                _, frame_ref = asset_lib.save_file(teacher_id, asset_id, frame_bytes, f"scene_{i + 1:02d}_last.jpg")
            except (StoryError, asset_lib.AssetError, ValueError, OSError) as e:
                return _fail(store, teacher_id, asset, story, f"Scene {i + 1} could not be saved: {e}")
            s.update(state="done", clip=clip_ref, frame=frame_ref)
            if story.get("vision") and i < len(scenes) - 1:
                s["note"] = describe_frame(frame_bytes)
        return asset_lib.update_asset(store, teacher_id, asset_id, settings={**asset["settings"], "story": story})
    finally:
        lock.release()


def _finish(store, teacher_id: str, asset: dict, story: dict) -> dict:
    """All scenes are saved: join them (and the narration) into the library video."""
    try:
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            narration = None
            text = " ".join(s["narration"] for s in story["scenes"] if s.get("narration")).strip()
            if story.get("voice") and text:
                try:
                    narration = media_tools.synthesize_speech(text[:media_tools.MAX_SPEECH_CHARS], story["voice"], tmp / "narration.mp3")
                except media_tools.MediaError as e:
                    log.warning("story_video: narration skipped: %s", e)       # the silent video is still delivered
            final = stitch([_path(s["clip"]) for s in story["scenes"]], tmp / "story.mp4",
                           fade=FADE_SECONDS if story.get("fade") else 0, narration=narration)
            root, ref = asset_lib.save_file(teacher_id, asset["asset_id"], final.read_bytes(), "story.mp4")
            story["narrated"] = narration is not None
    except (StoryError, asset_lib.AssetError, OSError) as e:
        return _fail(store, teacher_id, asset, story, f"The scenes could not be joined: {e}")
    return asset_lib.update_asset(store, teacher_id, asset["asset_id"], status="ready", storage_root=root, storage_ref=ref,
                                  error="", settings={**asset["settings"], "story": story})
