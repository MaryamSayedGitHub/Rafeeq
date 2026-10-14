"""A small local index of the room's material (SQLite, BM25 over the page text).

This is the stand-in for M2's indexer until M2's own lands: it reads each uploaded file, keeps its pages, and answers
POST /search, GET /rooms/{id}/topics and GET /sources/page exactly as contracts/openapi.yaml says. When M2's real
routes replace these, nothing in the tutor changes (it only talks to the contract).
"""
from __future__ import annotations

import math
import os
import re
import sqlite3
import threading
from collections import Counter
from contextlib import contextmanager
from pathlib import Path

CHUNK_WORDS = 110
OVERLAP = 25
_lock = threading.Lock()

_SCHEMA = """
CREATE TABLE IF NOT EXISTS files(room_id TEXT, file_id TEXT, file_name TEXT, topic_id TEXT, pages INTEGER, PRIMARY KEY(room_id, file_id));
CREATE TABLE IF NOT EXISTS pages(room_id TEXT, file_id TEXT, file_name TEXT, page INTEGER, text TEXT);
CREATE TABLE IF NOT EXISTS chunks(id INTEGER PRIMARY KEY AUTOINCREMENT, room_id TEXT, file_id TEXT, file_name TEXT, page INTEGER, topic_id TEXT, text TEXT, terms TEXT);
CREATE INDEX IF NOT EXISTS chunks_room ON chunks(room_id);
"""


def _path() -> Path:
    base = Path(os.getenv("KNOWLEDGE_DATA_DIR") or Path(__file__).resolve().parents[2] / "data" / "knowledge")
    base.mkdir(parents=True, exist_ok=True)
    return base / "knowledge.db"


@contextmanager
def db():
    with _lock:
        con = sqlite3.connect(_path(), timeout=30)
        con.row_factory = sqlite3.Row
        con.executescript(_SCHEMA)
        try:
            yield con
            con.commit()
        finally:
            con.close()


# ----------------------------------------------------------------------------- words
_MARKS = re.compile(r"[ً-ْـ]")
_WORD = re.compile(r"[A-Za-z0-9]{2,}|[ء-يٱ-ۓ]{2,}")
_STOP = set("the a an of and or to in on is are was were be for with as by at it its this that from which what how why who when where do does did "
            "في من على الى إلى عن مع هو هي هذا هذه ذلك التي الذي ما ماذا كيف لماذا هل او أو ثم كان كانت يكون تكون هناك".split())


def norm(word: str) -> str:
    w = _MARKS.sub("", word.lower())
    if w.isascii():
        for suf in ("ing", "es", "s"):
            if len(w) > len(suf) + 3 and w.endswith(suf):
                return w[: -len(suf)]
        return w
    w = re.sub("[أإآٱ]", "ا", w).replace("ى", "ي").replace("ة", "ه")
    if w.startswith("وال") and len(w) > 5:
        w = w[1:]
    for pre in ("ال", "لل", "بال", "كال", "فال"):
        if w.startswith(pre) and len(w) > len(pre) + 2:
            w = w[len(pre):]
            break
    return w


def terms(text: str) -> list[str]:
    return [t for t in (norm(w) for w in _WORD.findall(text)) if t and t not in _STOP]


def topic_of(file_name: str) -> tuple[str, str]:
    stem = Path(file_name).stem
    slug = re.sub(r"[^A-Za-z0-9ء-يٱ-ۓ]+", "_", stem).strip("_").lower() or "file"
    return "t_" + slug[:40], re.sub(r"[_\-]+", " ", stem).strip() or stem


# ----------------------------------------------------------------------------- writing
def _chunks(page_text: str) -> list[str]:
    words = page_text.split()
    if len(words) <= CHUNK_WORDS + OVERLAP:
        return [" ".join(words)] if words else []
    out, i = [], 0
    while i < len(words):
        out.append(" ".join(words[i:i + CHUNK_WORDS]))
        if i + CHUNK_WORDS >= len(words):
            break
        i += CHUNK_WORDS - OVERLAP
    return out


def add_file(room_id: str, file_id: str, file_name: str, pages: list[str]) -> int:
    """Replace everything known about this file. -> number of chunks kept."""
    topic_id, _ = topic_of(file_name)
    n = 0
    with db() as con:
        for table in ("files", "pages", "chunks"):
            con.execute(f"DELETE FROM {table} WHERE room_id=? AND file_id=?", (room_id, file_id))
        for number, text in enumerate(pages, 1):
            text = " ".join(text.split())
            if not text:
                continue
            con.execute("INSERT INTO pages VALUES (?,?,?,?,?)", (room_id, file_id, file_name, number, text))
            for piece in _chunks(text):
                con.execute("INSERT INTO chunks(room_id, file_id, file_name, page, topic_id, text, terms) VALUES (?,?,?,?,?,?,?)",
                            (room_id, file_id, file_name, number, topic_id, piece, " ".join(terms(piece))))
                n += 1
        if n:
            con.execute("INSERT INTO files VALUES (?,?,?,?,?)", (room_id, file_id, file_name, topic_id, len(pages)))
    return n


def remove_file(room_id: str, file_id: str) -> None:
    with db() as con:
        for table in ("files", "pages", "chunks"):
            con.execute(f"DELETE FROM {table} WHERE room_id=? AND file_id=?", (room_id, file_id))


def indexed(room_id: str, file_id: str) -> bool:
    with db() as con:
        return con.execute("SELECT 1 FROM files WHERE room_id=? AND file_id=?", (room_id, file_id)).fetchone() is not None


# ----------------------------------------------------------------------------- reading
def search(room_id: str, query: str, top_k: int = 5) -> list[dict]:
    """The best passages of this room for the question (BM25). Nothing shares a word with it -> []."""
    q = set(terms(query))
    if not q:
        return []
    with db() as con:
        rows = con.execute("SELECT id, file_name, page, topic_id, text, terms FROM chunks WHERE room_id=?", (room_id,)).fetchall()
    if not rows:
        return []
    docs = [(r, Counter(r["terms"].split())) for r in rows]
    n = len(docs)
    avg = sum(sum(c.values()) for _, c in docs) / n or 1
    df = {t: sum(1 for _, c in docs if t in c) for t in q}
    scored = []
    for r, c in docs:
        length, score = sum(c.values()), 0.0
        for t in q:
            f = c.get(t, 0)
            if f:
                idf = math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5))
                score += idf * f * 2.2 / (f + 1.2 * (0.25 + 0.75 * length / avg))
        if score > 0:
            scored.append((score, r))
    scored.sort(key=lambda x: -x[0])
    return [{"file_name": r["file_name"], "page": r["page"], "text": r["text"], "topic_id": r["topic_id"]} for _, r in scored[:top_k]]


def topics(room_id: str) -> list[dict]:
    with db() as con:
        rows = con.execute("SELECT DISTINCT file_name, topic_id FROM files WHERE room_id=? ORDER BY file_name", (room_id,)).fetchall()
    return [{"topic_id": r["topic_id"], "name": topic_of(r["file_name"])[1]} for r in rows]


def page(room_id: str, file_name: str, number: int) -> dict | None:
    with db() as con:
        r = con.execute("SELECT file_name, page, text FROM pages WHERE room_id=? AND file_name=? AND page=?", (room_id, file_name, number)).fetchone()
    return dict(r) if r else None
