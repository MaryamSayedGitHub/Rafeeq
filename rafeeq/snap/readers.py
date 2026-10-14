"""Readers: classic OCR baselines (EasyOCR, PaddleOCR) and free vision-language models (Gemini, Qwen2.5-VL).

All heavy imports are lazy, so you only install what you use.
Each reader has .read(image) -> str and .use_lines
  use_lines=True  -> the pipeline detects text lines and reads every crop (VLMs)
  use_lines=False -> the reader gets the whole image (classic OCR baseline)
"""
from __future__ import annotations

import io
import os
import re
import time

import cv2
import numpy as np

PROMPT = (
    "Transcribe the handwritten text in this image exactly as written. "
    "The text may be Arabic, English, math steps or code. Keep the original language, "
    "keep numbers, math symbols and code characters exactly. Do not correct mistakes, "
    "do not explain. Output only the transcription."
)


MARK_RULES = (" If a word or part is crossed out, write it as [crossed out: ...]. If a character or word cannot be read with confidence, write [?] in its place. "
              "If a sign (+ or -) is unclear, write ? there. Never guess a character you cannot see.")


def prompt() -> str:
    """The reading prompt. In the app the reader marks what it is unsure of (crossed out, [?]) so the checker asks instead of judging a misread;
    evaluate.py turns this off (SNAP_MARK_UNCERTAIN=0) so the CER is measured on the plain transcription prompt."""
    return PROMPT + (MARK_RULES if os.getenv("SNAP_MARK_UNCERTAIN", "1") == "1" else "")


def _png_bytes(img: np.ndarray) -> bytes:
    return cv2.imencode(".png", img)[1].tobytes()


def _pil(img: np.ndarray):
    from PIL import Image
    return Image.fromarray(img if img.ndim == 2 else cv2.cvtColor(img, cv2.COLOR_BGR2RGB))


def _is_rtl(text: str) -> bool:
    letters = [c for c in text if c.isalpha()]
    return bool(letters) and sum("؀" <= c <= "ۿ" for c in letters) > len(letters) / 2


def _results_to_text(results) -> str:
    """results: [(bbox, text, conf)] -> text lines top to bottom, words in reading order."""
    items = []
    for bbox, text, _ in results:
        ys, xs = [p[1] for p in bbox], [p[0] for p in bbox]
        items.append({"y": sum(ys) / len(ys), "x": sum(xs) / len(xs), "h": max(ys) - min(ys), "t": text})
    items.sort(key=lambda i: i["y"])
    rows: list[list[dict]] = []
    for it in items:
        if rows and abs(it["y"] - np.mean([r["y"] for r in rows[-1]])) < 0.6 * max(it["h"], rows[-1][0]["h"]):
            rows[-1].append(it)
        else:
            rows.append([it])
    lines = []
    for row in rows:
        rtl = _is_rtl(" ".join(i["t"] for i in row))
        lines.append(" ".join(i["t"] for i in sorted(row, key=lambda i: i["x"], reverse=rtl)))
    return "\n".join(lines)


class BaseReader:
    name = "base"
    use_lines = True

    def read(self, img: np.ndarray) -> str:
        raise NotImplementedError


# ----------------------------------------------------------------------------- classic OCR (baseline)
class EasyOCRReader(BaseReader):
    name = "easyocr"
    use_lines = False

    def __init__(self, langs=("ar", "en"), gpu=False):
        import easyocr
        self.reader = easyocr.Reader(list(langs), gpu=gpu)

    def read(self, img):
        return _results_to_text(self.reader.readtext(img, detail=1, paragraph=False))


class PaddleOCRReader(BaseReader):
    name = "paddleocr"
    use_lines = False

    def __init__(self, lang="ar"):
        from paddleocr import PaddleOCR
        self.ocr = PaddleOCR(lang=lang)

    def read(self, img):
        bgr = img if img.ndim == 3 else cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
        if hasattr(self.ocr, "predict"):                       # PaddleOCR 3.x
            res = self.ocr.predict(bgr)
            results = []
            for r in res:
                for poly, txt, sc in zip(r["rec_polys"], r["rec_texts"], r["rec_scores"]):
                    results.append((np.asarray(poly).tolist(), txt, sc))
            return _results_to_text(results)
        res = self.ocr.ocr(bgr, cls=True)                      # PaddleOCR 2.x
        return _results_to_text([(b, t, s) for b, (t, s) in (res[0] or [])])


# ----------------------------------------------------------------------------- VLMs
class GeminiReader(BaseReader):
    """Google AI Studio free tier. Set GEMINI_API_KEY (and optionally GEMINI_MODEL)."""
    name = "gemini"
    use_lines = True

    def __init__(self, model: str | None = None):
        from google import genai
        self.client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
        self.model = model or os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

    def read(self, img):
        from google.genai import types
        part = types.Part.from_bytes(data=_png_bytes(img), mime_type="image/png")
        for attempt in range(5):                               # free tier = rate limits -> back off
            try:
                resp = self.client.models.generate_content(model=self.model, contents=[part, prompt()])
                return (resp.text or "").strip()
            except Exception as e:                             # noqa: BLE001
                if attempt == 4:
                    raise
                time.sleep(2 ** attempt * 2)
        return ""


class QwenVLReader(BaseReader):
    """Local Qwen2.5-VL (open weights). Needs a GPU: Colab/Kaggle T4 works with QWEN_4BIT=1."""
    name = "qwen"
    use_lines = True

    def __init__(self, model_id: str | None = None):
        import torch
        from transformers import AutoProcessor, Qwen2_5_VLForConditionalGeneration
        model_id = model_id or os.getenv("QWEN_MODEL", "Qwen/Qwen2.5-VL-3B-Instruct")
        kw = dict(device_map="auto", torch_dtype=torch.float16)
        if os.getenv("QWEN_4BIT") == "1":
            from transformers import BitsAndBytesConfig
            kw["quantization_config"] = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_compute_dtype=torch.float16)
        self.model = Qwen2_5_VLForConditionalGeneration.from_pretrained(model_id, **kw)
        self.processor = AutoProcessor.from_pretrained(model_id)

    def read(self, img):
        msgs = [{"role": "user", "content": [{"type": "image"}, {"type": "text", "text": prompt()}]}]
        text = self.processor.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True)
        inputs = self.processor(text=[text], images=[_pil(img).convert("RGB")], return_tensors="pt").to(self.model.device)
        out = self.model.generate(**inputs, max_new_tokens=256, do_sample=False)
        out = out[:, inputs["input_ids"].shape[1]:]
        return self.processor.batch_decode(out, skip_special_tokens=True)[0].strip()


class OllamaReader(BaseReader):
    """Local VLM through Ollama (no API key, no Python GPU stack). Run once:  ollama pull qwen2.5vl:7b
    Env: SNAP_VISION_MODEL (default qwen2.5vl:7b; use qwen2.5vl:3b on a weak laptop), OLLAMA_BASE_URL (same variable as the team's text LLM)."""
    name = "ollama"
    use_lines = True

    def __init__(self, model: str | None = None):
        self.model = model or os.getenv("SNAP_VISION_MODEL", "qwen2.5vl:7b")
        self.url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/") + "/api/chat"

    def read(self, img):
        import base64
        import requests
        body = {"model": self.model, "stream": False, "options": {"temperature": 0},
                "messages": [{"role": "user", "content": prompt(),
                              "images": [base64.b64encode(_png_bytes(img)).decode()]}]}
        r = requests.post(self.url, json=body, timeout=300)
        r.raise_for_status()
        return r.json()["message"]["content"].strip()


READERS = {"easyocr": EasyOCRReader, "paddleocr": PaddleOCRReader, "gemini": GeminiReader,
           "qwen": QwenVLReader, "ollama": OllamaReader}
_CACHE: dict[str, BaseReader] = {}


def get_reader(name: str) -> BaseReader:
    if name not in _CACHE:
        _CACHE[name] = READERS[name]()
    return _CACHE[name]
