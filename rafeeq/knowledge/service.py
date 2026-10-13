"""M2 knowledge service: the contract-facing side of the knowledge base.

Everything the rest of Rafeeq needs from M2 goes through `KnowledgeService`:

    index_file(room_id, file_id, path)    upload hook (M1 calls it after saving a file)
    search(room_id, query, top_k)         POST /search               -> SearchMaterial
    list_topics(room_id)                  GET  /rooms/{id}/topics    -> RoomTopics
    source_page(room_id, file_name, page) GET  /sources/page        -> SourcePage
    tutor_answer(room_id, question)       grounded answer + citations -> TutorAnswer (optional, needs an LLM)

Retrieval uses the provisional configuration decided in the evaluation work: Hybrid (dense + BM25,
RRF k=60, candidate pool 50) with index-like pages excluded. Reranking is available but off.
Nothing heavy is loaded when this module is imported or when the service is created: the embedding
model (BGE-M3), FAISS and PyMuPDF are only touched by the first call that needs them.

Settings (all optional, environment variables):
    RAFEEQ_KNOWLEDGE_DIR        where the vector store is saved   (default: <RAFEEQ_DATA_DIR or storage>/knowledge/vector_store)
    RAFEEQ_KNOWLEDGE_DEVICE     embedding device                  (default: cpu)
    RAFEEQ_KNOWLEDGE_RETRIEVAL  hybrid | dense                    (default: hybrid)
    RAFEEQ_KNOWLEDGE_EXCLUDE    1 / 0, skip index-like pages       (default: 1)
    RAFEEQ_KNOWLEDGE_RERANK     1 to add the cross-encoder reranker (default: 0)
    GEMINI_API_KEY | GOOGLE_API_KEY, GEMINI_MODEL   only for tutor_answer (Gemini through its OpenAI-compatible endpoint)
"""
from __future__ import annotations

import logging
import os
import threading
from collections import Counter
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable

log = logging.getLogger(__name__)

DEFAULT_TOP_K = 5
MAX_TOP_K = 20  # the contract's SearchRequest.top_k maximum
GEMINI_OPENAI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai"


class KnowledgeError(Exception):
    """Base class; `status` is the HTTP status the router uses."""
    status = 400


class Invalid(KnowledgeError):
    status = 422


class NotFound(KnowledgeError):
    status = 404


class Unavailable(KnowledgeError):
    status = 503


def _flag(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    return default if value is None else value.strip() == "1"


def default_store_dir() -> Path:
    explicit = os.environ.get("RAFEEQ_KNOWLEDGE_DIR")
    if explicit:
        return Path(explicit)
    return Path(os.environ.get("RAFEEQ_DATA_DIR", "storage")) / "knowledge" / "vector_store"


def llm_from_env() -> Any | None:
    """Gemini through its OpenAI-compatible endpoint, or None when no key / model is configured."""
    key_env = "GEMINI_API_KEY" if os.environ.get("GEMINI_API_KEY") else "GOOGLE_API_KEY"
    model = os.environ.get("GEMINI_MODEL", "").strip()
    if not model or not os.environ.get(key_env):
        return None
    from rafeeq.knowledge.evaluation.judge import OpenAICompatibleLLM

    return OpenAICompatibleLLM(GEMINI_OPENAI_BASE_URL, model, key_env, temperature=0.0)


class _LockedAdd:
    """What `ingest_file` sees as the vector store: only the final `add` holds the lock, so searches
    are not blocked for the minutes that parsing and embedding a big PDF can take."""

    def __init__(self, store: Any, lock: threading.RLock) -> None:
        self._store, self._lock = store, lock

    def add(self, embeddings: Any, chunks: list[dict[str, Any]]) -> int:
        with self._lock:
            return self._store.add(embeddings, chunks)

    def save(self, directory: Any) -> None:  # not used: the service saves with save_store_safely
        raise RuntimeError("the service saves the store itself")

    def __len__(self) -> int:
        with self._lock:
            return len(self._store)


class KnowledgeService:
    def __init__(
        self,
        store_dir: str | Path | None = None,
        *,
        embedder: Any = None,
        store_cls: Any = None,
        retrieval_mode: str | None = None,
        exclude_non_content: bool | None = None,
        rerank: bool | None = None,
        status_callback: Callable[[str, str, str], None] | None = None,
        parse: Callable[[str], list[dict[str, Any]]] | None = None,
        llm: Any = None,
    ) -> None:
        self.store_dir = Path(store_dir) if store_dir is not None else default_store_dir()
        self._embedder = embedder
        self._store_cls = store_cls
        self._mode = retrieval_mode or os.environ.get("RAFEEQ_KNOWLEDGE_RETRIEVAL", "hybrid")
        self._exclude = _flag("RAFEEQ_KNOWLEDGE_EXCLUDE", True) if exclude_non_content is None else exclude_non_content
        self._rerank = _flag("RAFEEQ_KNOWLEDGE_RERANK", False) if rerank is None else rerank
        self._status_callback = status_callback
        self._parse = parse
        self._llm = llm
        self._lock = threading.RLock()
        self._store: Any = None
        self._retriever_obj: Any = None
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="knowledge-index")  # one writer at a time

    # ------------------------------------------------------------------ lazy parts

    def describe(self) -> dict[str, Any]:
        return {"retrieval": self._mode, "exclude_non_content": self._exclude, "rerank": self._rerank,
                "candidate_pool": 50 if self._mode == "hybrid" else None, "store_dir": str(self.store_dir)}

    def _get_embedder(self) -> Any:
        with self._lock:
            if self._embedder is None:
                from rafeeq.knowledge.embeddings.embedder import Embedder

                self._embedder = Embedder(device=os.environ.get("RAFEEQ_KNOWLEDGE_DEVICE", "cpu"))
            return self._embedder

    def _existing_store(self) -> Any | None:
        """The loaded store, loading it from disk if it exists. None when nothing was ever indexed
        (this never creates a store and never loads the embedding model)."""
        from rafeeq.knowledge.store_persistence import StoreNotFoundError, load_existing_store

        with self._lock:
            if self._store is None:
                try:
                    self._store = load_existing_store(self.store_dir, store_cls=self._store_cls)
                except StoreNotFoundError:
                    return None
            return self._store

    def _retriever(self) -> Any | None:
        with self._lock:
            store = self._existing_store()
            if store is None:
                return None
            if self._retriever_obj is None:
                from rafeeq.knowledge.retrieval.factory import build_retriever

                self._retriever_obj = build_retriever(store, self._get_embedder(), mode=self._mode,
                                                      exclude_non_content=self._exclude, rerank=self._rerank)
            return self._retriever_obj

    # ------------------------------------------------------------------ indexing (M1 upload hook)

    def _set_status(self, room_id: str, file_id: str, status: str) -> None:
        if self._status_callback is not None:
            self._status_callback(room_id, file_id, status)
            return
        from rafeeq.platform import service as platform

        platform.get_store().set_file_status(room_id, file_id, status)

    def index_file(self, room_id: str, file_id: str, path: str | Path) -> Future:
        """Register with `rafeeq.platform.service.on_upload`. Returns at once: the file is marked
        "indexing", then "ready" or "failed" by a background worker. The Future resolves to the
        chunk count (0 when it failed) and never raises."""
        path = Path(path)
        prefix = f"{file_id}__"
        display_name = path.name[len(prefix):] if path.name.startswith(prefix) else path.name
        if path.suffix.lower() != ".pdf":
            log.warning("knowledge: %s is not a PDF; only PDFs can be indexed", display_name)
            self._set_status(room_id, file_id, "failed")
            done: Future = Future()
            done.set_result(0)
            return done
        self._set_status(room_id, file_id, "indexing")
        return self._pool.submit(self._index, room_id, file_id, path, display_name)

    @staticmethod
    def _unique_name(store: Any, room_id: str, name: str) -> str:
        """A citation is (file_name, page), so two files of one room must not share a name:
        a second "lecture1.pdf" is stored as "lecture1 (2).pdf"."""
        taken = {c["file_name"] for c in store.room_chunks(room_id)}
        if name not in taken:
            return name
        stem, suffix = Path(name).stem, Path(name).suffix
        n = 2
        while f"{stem} ({n}){suffix}" in taken:
            n += 1
        return f"{stem} ({n}){suffix}"

    def _index(self, room_id: str, file_id: str, path: Path, display_name: str) -> int:
        from rafeeq.knowledge.ingestion.pipeline import ingest_file
        from rafeeq.knowledge.store_persistence import document_exists, load_or_create_store, save_store_safely

        try:
            embedder = self._get_embedder()
            with self._lock:
                if self._store is None:
                    if self._store_cls is None:
                        from rafeeq.knowledge.vector_store import FAISSVectorStore

                        self._store_cls = FAISSVectorStore
                    self._store, _ = load_or_create_store(self.store_dir, lambda: embedder.dimension, store_cls=self._store_cls)
                store = self._store
                already = document_exists(store, room_id, file_id)
            if already:  # the hook ran twice for the same upload: the index is already right
                log.info("knowledge: %s is already indexed in room %s", display_name, room_id)
                self._set_status(room_id, file_id, "ready")
                return 0
            with self._lock:
                display_name = self._unique_name(store, room_id, display_name)
            stats = ingest_file(path, room_id, _LockedAdd(store, self._lock), embedder,
                                document_id=file_id, file_name=display_name, parse=self._parse)
            with self._lock:
                save_store_safely(store, self.store_dir, store_cls=self._store_cls)
            self._set_status(room_id, file_id, "ready")
            log.info("knowledge: indexed %s into room %s (%d chunks)", display_name, room_id, stats.chunk_count)
            return stats.chunk_count
        except Exception:
            log.exception("knowledge: indexing %s failed", display_name)
            try:
                self._set_status(room_id, file_id, "failed")
            except Exception:
                log.exception("knowledge: could not mark %s as failed", file_id)
            return 0

    # ------------------------------------------------------------------ contract operations

    @staticmethod
    def _text(value: Any, label: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise Invalid(f"{label} must be a non-empty string")
        return value

    def search(self, room_id: str, query: str, top_k: int = DEFAULT_TOP_K) -> dict[str, Any]:
        """SearchMaterial: `{"chunks": [{file_name, page, text, topic_id}]}`, best first."""
        self._text(room_id, "room_id")
        self._text(query, "query")
        if isinstance(top_k, bool) or not isinstance(top_k, int) or not 1 <= top_k <= MAX_TOP_K:
            raise Invalid(f"top_k must be an integer between 1 and {MAX_TOP_K}")
        with self._lock:
            retriever = self._retriever()
            hits = retriever.retrieve(room_id, query, top_k) if retriever is not None else []
        return {"chunks": [{"file_name": h["file_name"], "page": int(h["page"]), "text": h["text"], "topic_id": h["topic_id"]} for h in hits]}

    def list_topics(self, room_id: str) -> dict[str, Any]:
        """RoomTopics: only the topics that really occur in the room's material, most frequent first."""
        self._text(room_id, "room_id")
        from rafeeq.knowledge.topics import get_default_manager

        with self._lock:
            store = self._existing_store()
            chunks = store.room_chunks(room_id) if store is not None else []
        counts = Counter(c["topic_id"] for c in chunks)
        names = {t["topic_id"]: t["name"] for t in get_default_manager().list_topics(room_id)}
        ordered = sorted(counts, key=lambda topic_id: (-counts[topic_id], topic_id))
        return {"topics": [{"topic_id": t, "name": names.get(t, t)} for t in ordered]}

    def source_page(self, room_id: str, file_name: str, page: int) -> dict[str, Any]:
        """SourcePage: the text of one page of one file, so a citation can be opened."""
        self._text(room_id, "room_id")
        self._text(file_name, "file_name")
        if isinstance(page, bool) or not isinstance(page, int) or page < 1:
            raise Invalid("page must be an integer >= 1")
        with self._lock:
            store = self._existing_store()
            chunks = store.room_chunks(room_id) if store is not None else []
        texts = [c["text"] for c in chunks if c["file_name"] == file_name and c["page"] == page]
        if not texts:
            raise NotFound(f"{file_name} page {page} is not in this room")
        return {"file_name": file_name, "page": page, "text": "\n".join(texts)}

    def tutor_answer(self, room_id: str, question: str) -> dict[str, Any]:
        """TutorAnswer from the grounded Answerer: answers only from the room's material, or says it
        is not covered (grounded=False). Needs an LLM (see `llm_from_env`); `steps` is always empty."""
        self._text(room_id, "room_id")
        self._text(question, "question")
        llm = self._llm or llm_from_env()
        if llm is None:
            raise Unavailable("no answer LLM configured: set GEMINI_API_KEY (or GOOGLE_API_KEY) and GEMINI_MODEL")
        with self._lock:
            retriever = self._retriever()
        from rafeeq.knowledge.answering.answerer import NOT_COVERED_MESSAGE, Answerer
        from rafeeq.knowledge.evaluation.metrics import answer_body

        if retriever is None:
            return {"answer": NOT_COVERED_MESSAGE, "citations": [], "grounded": False, "steps": []}
        result = Answerer(retriever, llm).answer(room_id, question)
        if not result["grounded"]:
            return {"answer": result["answer_md"], "citations": [], "grounded": False, "steps": []}
        return {"answer": answer_body(result["answer_md"]),
                "citations": [{"file_name": c["file_name"], "page": int(c["page"])} for c in result["citations"]],
                "grounded": True, "steps": []}


# ------------------------------------------------------------------ default instance

_service: KnowledgeService | None = None
_service_lock = threading.Lock()


def get_service() -> KnowledgeService:
    global _service
    with _service_lock:
        if _service is None:
            _service = KnowledgeService()
        return _service


def set_service(service: KnowledgeService | None) -> None:
    """Tests use this to point M2 at a temporary store and a fake embedder."""
    global _service
    with _service_lock:
        _service = service
