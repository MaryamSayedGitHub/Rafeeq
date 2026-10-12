"""The teacher's asset library: one record per file/video/moment a teacher saved or generated.

Records live in the same LangGraph Store as the profile and the finished sessions, under
    ("lecturer", <teacher_id>, "assets")     key = asset_id ("a_" + 8 hex)
so one teacher_id links profile, sessions and assets, and nothing new has to be migrated.
Files stay on disk (never in the database). A record only holds a reference:

    storage_root  "sessions" -> settings.OUTPUT_DIR   (files made by a Lesson Studio session)
                  "assets"   -> settings.ASSET_DIR    (videos/images saved or generated later)
                  ""         -> external material (e.g. a YouTube moment): nothing on our disk
    storage_ref   path relative to that root

Reuse = reference the asset_id from lessons/slides. Editing never overwrites: new_version() adds a
new record whose parent_asset_id points at the original.

Plain functions with the store as first argument (like long_term_store.py): easy to test with a fake store.
"""

import logging
import re
import secrets
from datetime import datetime, timezone
from pathlib import Path

from rafeeq.teacher.lecturer import settings
from rafeeq.teacher.lecturer.long_term_store import lecturer_key

log = logging.getLogger(__name__)

KINDS = ("pptx", "code", "quiz", "image", "source_video", "generated_video", "audio")
ORIGINS = ("upload", "external", "edited", "ai_generated")
STATUSES = ("pending", "ready", "failed")
ROOTS = ("sessions", "assets", "")
MAX_ASSETS = 1000

# Fields update_asset() may change. Identity, owner, kind, origin and version never change.
_MUTABLE = {"title", "status", "storage_root", "storage_ref", "source_url", "start_sec", "end_sec",
            "settings", "error", "room_id", "session_id", "slide_index"}


class AssetError(ValueError):
    """Bad input (unknown kind, path outside the storage folders, ...)."""


def _ns(teacher_id: str) -> tuple:
    return ("lecturer", lecturer_key(teacher_id), "assets")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_asset_id() -> str:
    return f"a_{secrets.token_hex(4)}"


def _root_dir(root: str) -> Path | None:
    return {"sessions": settings.OUTPUT_DIR, "assets": settings.ASSET_DIR}.get(root)


def _safe_part(text: str, fallback: str) -> str:
    """One folder/file name part: no slashes, no leading dot."""
    part = re.sub(r"[^\w.\-]+", "_", text.strip(), flags=re.UNICODE).strip("._")
    return part[:80] or fallback


# ------------------------------------------------------------------ read
def _all(store, teacher_id: str) -> list[dict]:
    if store is None or not teacher_id:
        return []
    items = store.search(_ns(teacher_id), limit=MAX_ASSETS)
    return [{"asset_id": i.key, **i.value} for i in items]


def get_asset(store, teacher_id: str, asset_id: str) -> dict | None:
    """The asset, or None. Another teacher's asset_id is simply not found."""
    if store is None or not teacher_id or not asset_id:
        return None
    item = store.get(_ns(teacher_id), asset_id)
    return {"asset_id": asset_id, **item.value} if item else None


def list_assets(store, teacher_id: str, kind: str = "", room_id: str = "", session_id: str = "",
                status: str = "") -> list[dict]:
    """Newest first. Empty filters match everything."""
    found = [a for a in _all(store, teacher_id)
             if (not kind or a["kind"] == kind) and (not room_id or a.get("room_id") == room_id)
             and (not session_id or a.get("session_id") == session_id)
             and (not status or a["status"] == status)]
    return sorted(found, key=lambda a: (a.get("created_at", ""), a["asset_id"]), reverse=True)


# ------------------------------------------------------------------ write
def register_asset(store, teacher_id: str, *, kind: str, title: str, origin: str,
                   storage_root: str = "", storage_ref: str = "", source_url: str = "",
                   start_sec: float | None = None, end_sec: float | None = None,
                   provider: str = "", model: str = "", settings_used: dict | None = None,
                   status: str = "ready", room_id: str = "", session_id: str = "",
                   slide_index: int | None = None, parent_asset_id: str = "", version: int = 1,
                   idempotency_key: str = "") -> dict:
    """Create an asset record. With an idempotency_key, repeating the call returns the existing
    record instead of a duplicate (retries, double clicks, re-running a backfill)."""
    if store is None or not teacher_id:
        raise AssetError("A teacher is required")
    if kind not in KINDS:
        raise AssetError(f"Unknown asset kind '{kind}'")
    if origin not in ORIGINS:
        raise AssetError(f"Unknown origin '{origin}'")
    if status not in STATUSES:
        raise AssetError(f"Unknown status '{status}'")
    if storage_root not in ROOTS:
        raise AssetError(f"Unknown storage root '{storage_root}'")
    if storage_ref and not storage_root:
        raise AssetError("storage_ref needs a storage_root")
    if storage_ref:
        _resolve(storage_root, storage_ref)  # raises if it points outside the folder
    if idempotency_key:
        for existing in _all(store, teacher_id):
            if existing.get("idempotency_key") == idempotency_key:
                return existing
    if parent_asset_id and get_asset(store, teacher_id, parent_asset_id) is None:
        raise AssetError("The parent asset does not exist")

    asset_id = new_asset_id()
    now = _now()
    record = {
        "kind": kind, "title": (title or "").strip()[:200] or kind, "origin": origin,
        "storage_root": storage_root, "storage_ref": storage_ref, "source_url": source_url,
        "start_sec": start_sec, "end_sec": end_sec,
        "provider": provider, "model": model, "settings": settings_used or {},
        "status": status, "error": "",
        "room_id": room_id, "session_id": session_id, "slide_index": slide_index,
        "parent_asset_id": parent_asset_id, "version": version,
        "idempotency_key": idempotency_key,
        "created_at": now, "updated_at": now,
    }
    store.put(_ns(teacher_id), asset_id, record)
    return {"asset_id": asset_id, **record}


def update_asset(store, teacher_id: str, asset_id: str, **changes) -> dict | None:
    """Change allowed fields of the teacher's own asset. None if it does not exist."""
    current = get_asset(store, teacher_id, asset_id)
    if current is None:
        return None
    bad = set(changes) - _MUTABLE
    if bad:
        raise AssetError(f"Cannot change: {', '.join(sorted(bad))}")
    merged = {**current, **changes}
    if merged["status"] not in STATUSES:
        raise AssetError(f"Unknown status '{merged['status']}'")
    if merged["storage_root"] not in ROOTS:
        raise AssetError(f"Unknown storage root '{merged['storage_root']}'")
    if merged["storage_ref"]:
        if not merged["storage_root"]:
            raise AssetError("storage_ref needs a storage_root")
        _resolve(merged["storage_root"], merged["storage_ref"])
    merged["updated_at"] = _now()
    merged.pop("asset_id")
    store.put(_ns(teacher_id), asset_id, merged)
    return {"asset_id": asset_id, **merged}


def new_version(store, teacher_id: str, parent_id: str, **overrides) -> dict | None:
    """Add version N+1 of an asset (origin 'edited' unless overridden). The original is kept as is.
    overrides: any register_asset field, e.g. title=..., storage_root=..., storage_ref=..."""
    parent = get_asset(store, teacher_id, parent_id)
    if parent is None:
        return None
    fields = {k: parent[k] for k in ("kind", "title", "storage_root", "storage_ref", "source_url",
                                     "start_sec", "end_sec", "provider", "model", "room_id",
                                     "session_id", "slide_index")}
    fields["settings_used"] = parent.get("settings") or {}
    fields["origin"] = "edited"
    fields.update(overrides)
    return register_asset(store, teacher_id, parent_asset_id=parent_id,
                          version=parent["version"] + 1, **fields)


# ------------------------------------------------------------------ files
def _resolve(root: str, ref: str) -> Path:
    base = _root_dir(root)
    if base is None:
        raise AssetError("This asset has no stored file")
    path = (base / ref).resolve()
    if not path.is_relative_to(base):
        raise AssetError("File path is outside the storage folder")
    return path


def asset_file(asset: dict) -> Path | None:
    """The file on disk for an asset, or None when there is none (external, pending, missing)."""
    if not asset.get("storage_ref"):
        return None
    try:
        path = _resolve(asset["storage_root"], asset["storage_ref"])
    except AssetError:
        return None
    return path if path.is_file() else None


def save_file(teacher_id: str, asset_id: str, data: bytes, filename: str) -> tuple[str, str]:
    """Write bytes to ASSET_DIR/<teacher>/<asset_id>/<filename>. Returns (storage_root, storage_ref)."""
    ref = f"{_safe_part(lecturer_key(teacher_id), 'teacher')}/{_safe_part(asset_id, 'asset')}/{_safe_part(filename, 'file')}"
    path = _resolve("assets", ref)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return "assets", ref
