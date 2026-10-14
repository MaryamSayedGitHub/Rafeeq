"""The M2 routes of the contract, served from the local index."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from . import store

router = APIRouter(tags=["M2 knowledge"])


class SearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    room_id: str
    query: str
    top_k: int = Field(5, ge=1, le=20)


@router.post("/search")
def search_material(body: SearchRequest):
    return {"chunks": store.search(body.room_id, body.query, body.top_k)}


@router.get("/rooms/{room_id}/topics")
def room_topics(room_id: str):
    return {"topics": store.topics(room_id)}


@router.get("/sources/page")
def source_page(room_id: str, file_name: str, page: int):
    found = store.page(room_id, file_name, page)
    if not found:
        raise HTTPException(404, "Page not found")
    return found
