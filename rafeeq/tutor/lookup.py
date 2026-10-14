"""A term lookup: "what is X" / a photo of a word or two. The room's material did not have it, so the web is searched and the answer is given right
away, in the chat, with its sources. No study file is made (that is what Level 2 is for).

term_of() decides whether a text is a term lookup; web_lookup() does the search (cached, credit-guarded: web_search.py) and the answer.
"""
from __future__ import annotations

import re

from . import llm, memory, safety, web_search

# "what is X", "define X", "meaning of X", Arabic: "ما هو X", "يعني ايه X", "ايه ده X", "عرّف X", "تعريف X", "ما معنى X"
_ASK = re.compile(
    r"^\s*(?:(?:what|who)\s*(?:is|are|'s)|what\s+does\s+(.+?)\s+mean|define|definition\s+of|meaning\s+of|explain\s+the\s+term|"
    r"ما\s+(?:هو|هي|هم|معنى|المقصود\s+ب\w*)|ماذا\s+يعني|يعني\s+[ايإأ]يه|[ايإأ]يه\s+(?:هو|هي|ده|دا|هذا|معنى)|[ايإأ]يه\s+معنى|عر[ّف]+ف?|تعريف|ما\s+تعريف)\s*", re.I)
_TRAIL = re.compile(r"\s*(?:\bmean\b|\?|؟|يعني\s*[ايإأ]يه|[ايإأ]يه\s*(?:ده|دا)?)\s*$", re.I)
MAX_TERM_WORDS = 4


def term_of(text: str, photo: bool = False) -> str | None:
    """The term, when `text` is a short "what is this term" question (photo=True: any very short text is a term, e.g. a word photographed)."""
    t = " ".join(text.split())
    if not t or "\n" in text.strip() and len([l for l in text.splitlines() if l.strip()]) > 2:
        return None
    m = _ASK.match(t)
    if m:
        term = (m.group(1) or t[m.end():]).strip()
    elif photo:
        term = t
    else:
        return None
    term = _TRAIL.sub("", term).strip(" .,:;؟?!\"'«»")
    words = term.split()
    return term if term and len(words) <= MAX_TERM_WORDS and not re.search(r"[=+*/^]\s*\d|\d\s*[=+*/^]", term) else None


def web_lookup(term: str, question: str, lang: str, keep_terms: bool = False) -> dict | None:
    """-> {"answer", "web_sources": [{n, title, url}], "cache_hits", "api_calls"}, or None when the web has nothing / cannot be searched."""
    from .answer import wants_detail
    detail = wants_detail(question)
    field = memory.search_field()                                  # what the student studies narrows the search ("osmosis medicine")
    try:
        res = web_search.multi_search([f"{term} {field}".strip()], top=7 if detail else 4, per_query=8 if detail else 5)
    except safety.Blocked:
        raise                                                      # illegal or 18+: the caller tells the student
    except Exception:                                              # noqa: BLE001  quota, key, network: the caller says "not found"
        return None
    sources = res["sources"]
    if not sources:
        return None
    src = "\n".join(f"[{s['n']}] {s['title']}\n{s['content'][:1400 if detail else 700]}" for s in sources)
    name = "Arabic" if lang == "ar" else "English"
    terms = " Keep every technical term in English (Latin letters), the rest in Arabic." if lang == "ar" and keep_terms else ""
    length = ("the student asked for it IN DETAIL: a full, organised explanation of about 350-500 words (what it is, how it works step by step, the important points, one example)."
              if detail else "simple short words, EXACTLY about 3 short lines (3 sentences) that answer the question directly.")
    out = llm.ask_json(f"""A student asked: {question}
Answer the question about "{term}" using only the numbered web sources below.

{src}

Return JSON only: {{"answer": "..."}}
Rules: write in {name}, {length} Cite the sources you used like [1].{terms}
Do not invent facts or links.""", max_tokens=2000 if detail else 700)
    answer = str(out.get("answer", "")).strip() if isinstance(out, dict) else ""
    if not answer:                                                 # no model: the best snippet itself, with its source
        answer = f"{sources[0]['content'][:300].strip()} [1]"
    return {"answer": answer, "web_sources": [{"n": s["n"], "title": s["title"], "url": s["url"]} for s in sources],
            "cache_hits": res["cache_hits"], "api_calls": res["api_calls"]}
