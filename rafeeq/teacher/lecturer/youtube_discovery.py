"""YouTube video discovery: search real YouTube videos and jump to the exact
timestamp that answers a student's question.

This REPLACES searching the teacher's own sessions (video_discovery.py /
Lab 4) as the source behind the dashboard's search box, per the "Madrasa"
spec's Feature 2 (exact timestamp retrieval + Previous/Next navigation).
video_discovery.py is left in place (final_agent still indexes sessions
quietly) in case a "my own recordings" mode is wanted again later.

Pipeline for one search:
  1. YouTube Data API `search.list` -> a handful of candidate videos
     (restricted to ones that have captions, so step 2 can succeed).
  2. For each NEW candidate (not already cached), fetch its transcript with
     youtube-transcript-api and chunk it into ~45-second windows.
  3. Embed each chunk (Gemini) and store it in Postgres/pgvector, cached by
     video_id -- a video is only ever transcribed/embedded once, no matter
     how many different questions later match it.
  4. Embed the student's question and rank the candidate videos' chunks by
     cosine similarity, picking the best segment per video (so the result
     list is diverse videos, not 5 chunks of the same one).

Every external call (YouTube search, transcript fetch, Gemini) is wrapped so
one failing video/provider never breaks the whole search -- it is just
skipped, consistent with video_discovery.py's "never raises" contract.
"""

import json
import logging
import os
import urllib.parse
import urllib.request

from rafeeq.teacher.lecturer.settings import DATABASE_URL

log = logging.getLogger(__name__)

EMBED_MODEL = "gemini-embedding-001"
EMBED_DIM = 768
CHUNK_SECONDS = 45          # group consecutive captions into ~45s segments
MAX_CANDIDATES = 6          # videos pulled per search (keeps YouTube quota small)
YOUTUBE_SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"


# ---------------------------------------------------------------------------
# Step 1 — YouTube Data API: find candidate videos
# ---------------------------------------------------------------------------
def search_candidates(query: str, max_results: int = MAX_CANDIDATES) -> list[dict]:
    """[] (not an exception) when YOUTUBE_API_KEY is missing or the API call
    fails -- the dashboard then just shows "no results" instead of crashing."""
    api_key = os.getenv("YOUTUBE_API_KEY")
    if not api_key:
        log.warning("youtube_discovery: YOUTUBE_API_KEY is not set in .env")
        return []

    params = {
        "part": "snippet",
        "type": "video",
        "q": query,
        "maxResults": max_results,
        "videoCaption": "closedCaption",  # only videos that actually have captions
        "safeSearch": "strict",
        "relevanceLanguage": "ar",
        "key": api_key,
    }
    url = f"{YOUTUBE_SEARCH_URL}?{urllib.parse.urlencode(params)}"
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.load(resp)
    except Exception as e:
        log.warning("youtube_discovery: search.list failed: %s: %s", type(e).__name__, str(e)[:300])
        return []

    candidates = []
    for item in data.get("items", []):
        vid = item.get("id", {}).get("videoId")
        snippet = item.get("snippet", {})
        if not vid:
            continue
        candidates.append({
            "video_id": vid,
            "title": snippet.get("title", ""),
            "channel": snippet.get("channelTitle", ""),
            "thumbnail": (snippet.get("thumbnails", {}).get("medium")
                          or snippet.get("thumbnails", {}).get("default") or {}).get("url", ""),
        })
    return candidates


# ---------------------------------------------------------------------------
# Step 2 — Transcript + chunking
# ---------------------------------------------------------------------------
def fetch_transcript(video_id: str) -> list[dict] | None:
    """None when the video has no usable transcript (disabled, not found, ...)."""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi

        # Arabic first (most of our students' content), English fallback.
        return YouTubeTranscriptApi.get_transcript(video_id, languages=["ar", "en"])
    except Exception as e:
        log.info("youtube_discovery: no transcript for %s (%s)", video_id, type(e).__name__)
        return None


def chunk_transcript(entries: list[dict], window_seconds: float = CHUNK_SECONDS) -> list[dict]:
    """Merge consecutive caption lines into ~window_seconds chunks, so each
    chunk is long enough to carry a full idea (one caption line alone is
    usually just a few words)."""
    chunks: list[dict] = []
    bucket_start: float | None = None
    bucket_text: list[str] = []
    bucket_end = 0.0

    for entry in entries:
        start = float(entry["start"])
        end = start + float(entry.get("duration", 0))
        if bucket_start is None:
            bucket_start = start
        bucket_text.append(entry["text"])
        bucket_end = end
        if bucket_end - bucket_start >= window_seconds:
            chunks.append({"start_sec": bucket_start, "end_sec": bucket_end,
                            "text": " ".join(bucket_text).strip()})
            bucket_start, bucket_text = None, []

    if bucket_text:
        chunks.append({"start_sec": bucket_start, "end_sec": bucket_end,
                        "text": " ".join(bucket_text).strip()})
    return [c for c in chunks if c["text"]]


# ---------------------------------------------------------------------------
# Embeddings + Postgres (same approach as video_discovery.py)
# ---------------------------------------------------------------------------
def _embed(text: str) -> list[float] | None:
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        return None
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key)
    result = client.models.embed_content(
        model=EMBED_MODEL, contents=text,
        config=types.EmbedContentConfig(output_dimensionality=EMBED_DIM),
    )
    return result.embeddings[0].values


def _to_vector_literal(vector: list[float]) -> str:
    return "[" + ",".join(repr(float(x)) for x in vector) + "]"


def _connect():
    import psycopg
    return psycopg.connect(DATABASE_URL, autocommit=True)


def setup_table() -> None:
    if not DATABASE_URL:
        return
    with _connect() as conn:
        conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS youtube_segments (
                id          SERIAL PRIMARY KEY,
                video_id    TEXT NOT NULL,
                title       TEXT NOT NULL,
                channel     TEXT NOT NULL,
                thumbnail   TEXT NOT NULL,
                start_sec   FLOAT NOT NULL,
                end_sec     FLOAT NOT NULL,
                text        TEXT NOT NULL,
                embedding   VECTOR({EMBED_DIM})
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS youtube_segments_video_idx
            ON youtube_segments (video_id)
        """)


def _index_video(conn, candidate: dict) -> None:
    """Fetches, chunks, embeds and stores one video's transcript -- skipped
    entirely if this video_id is already cached from an earlier search."""
    video_id = candidate["video_id"]
    already = conn.execute(
        "SELECT 1 FROM youtube_segments WHERE video_id = %s LIMIT 1", (video_id,)
    ).fetchone()
    if already:
        return

    entries = fetch_transcript(video_id)
    if not entries:
        return
    for chunk in chunk_transcript(entries):
        vector = _embed(chunk["text"])
        if vector is None:
            log.warning("youtube_discovery: GOOGLE_API_KEY not set, skipping embedding")
            return
        conn.execute(
            """
            INSERT INTO youtube_segments
                (video_id, title, channel, thumbnail, start_sec, end_sec, text, embedding)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s::vector)
            """,
            (video_id, candidate["title"], candidate["channel"], candidate["thumbnail"],
             chunk["start_sec"], chunk["end_sec"], chunk["text"], _to_vector_literal(vector)),
        )


# ---------------------------------------------------------------------------
# Step 3 — Put it all together
# ---------------------------------------------------------------------------
def search(question: str, top_k: int = 5) -> list[dict]:
    """Always returns a list (possibly empty) -- never raises, so the
    dashboard's search box degrades gracefully instead of crashing the page."""
    if not DATABASE_URL:
        return []

    candidates = search_candidates(question, max_results=MAX_CANDIDATES)
    if not candidates:
        return []

    try:
        setup_table()
        with _connect() as conn:
            for candidate in candidates:
                try:
                    _index_video(conn, candidate)
                except Exception as e:
                    log.warning("youtube_discovery: indexing %s failed: %s: %s",
                                candidate["video_id"], type(e).__name__, str(e)[:200])

            query_vector = _embed(question)
            if query_vector is None:
                return []
            video_ids = [c["video_id"] for c in candidates]
            # DISTINCT ON (video_id): the single best-matching chunk per video,
            # so results are diverse videos instead of 5 chunks of one video.
            rows = conn.execute(
                """
                SELECT DISTINCT ON (video_id)
                       video_id, title, channel, thumbnail, start_sec, end_sec, text,
                       1 - (embedding <=> %s::vector) AS score
                FROM youtube_segments
                WHERE video_id = ANY(%s)
                ORDER BY video_id, embedding <=> %s::vector
                """,
                (_to_vector_literal(query_vector), video_ids, _to_vector_literal(query_vector)),
            ).fetchall()
    except Exception as e:
        log.warning("youtube_discovery: search failed: %s: %s", type(e).__name__, str(e)[:200])
        return []

    results = []
    for video_id, title, channel, thumbnail, start_sec, end_sec, text, score in rows:
        results.append({
            "video_id": video_id,
            "title": title,
            "channel": channel,
            "thumbnail": thumbnail,
            "start_sec": start_sec,
            "end_sec": end_sec,
            "open_at": f"{int(start_sec) // 60:02d}:{int(start_sec) % 60:02d}",
            "text": text,
            "score": round(float(score), 3),
            "url": f"https://www.youtube.com/watch?v={video_id}&t={int(start_sec)}s",
        })
    results.sort(key=lambda r: r["score"], reverse=True)
    return results[:top_k]
