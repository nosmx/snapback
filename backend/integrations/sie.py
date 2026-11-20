"""Superlinked SIE Serverless: image embeddings, field extraction, reranking.

Real calls: TODO(block 2) once the endpoint, auth and model IDs are verified at kickoff (§16).
Until then `real` mode raises NotImplementedError and falls back to the mock, labeled `degraded`.

Mock behavior (honest, deterministic):
  - embed_image: product images get a vector seeded by their SKU; demo photos listed in
    mock/photos/labels.json are mixed toward their labeled SKU. Unlabeled images get an
    unrelated vector, so they produce LOW confidence (exercising the self-recovery path).
  - embed_text: feature-hashed bag of words (real lexical similarity).
  - extract: regex over the labeled lines in our order emails.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from backend.config import MOCK_DIR, settings
from backend.integrations.base import call

LABELS_FILE = MOCK_DIR / "photos" / "labels.json"


# ---------------- mock helpers ----------------

def _seeded_vec(key: str, dim: int) -> np.ndarray:
    seed = int.from_bytes(hashlib.sha256(key.encode()).digest()[:8], "big")
    v = np.random.default_rng(seed).standard_normal(dim)
    return v / np.linalg.norm(v)


def _mock_embed_image(path: str) -> List[float]:
    dim = settings.image_embed_dim
    p = Path(path)
    labels = json.loads(LABELS_FILE.read_text()) if LABELS_FILE.exists() else {}
    if p.name in labels:
        lab = labels[p.name]
        v = _seeded_vec("img:" + lab["ref"], dim)
        for ref, w in (lab.get("similar") or {}).items():
            v = v + w * _seeded_vec("img:" + ref, dim)
        noise_key = hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else p.name
        v = v + 0.25 * _seeded_vec("noise:" + noise_key, dim)
    elif p.parent.name == "products":
        v = _seeded_vec("img:" + p.stem.upper(), dim)
    else:
        key = hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else p.name
        v = _seeded_vec("unlabeled:" + key, dim)
    return (v / np.linalg.norm(v)).tolist()


_TOKEN = re.compile(r"[a-z0-9]+")


def _mock_embed_text(text: str) -> List[float]:
    dim = settings.text_embed_dim
    v = np.zeros(dim)
    toks = _TOKEN.findall(text.lower())
    grams = toks + [a + "_" + b for a, b in zip(toks, toks[1:])]
    for g in grams:
        h = int.from_bytes(hashlib.md5(g.encode()).digest()[:8], "big")
        v[h % dim] += 1.0 if (h >> 63) & 1 else -1.0
    n = np.linalg.norm(v)
    return (v / n).tolist() if n else v.tolist()


_PATTERNS = {
    "order_no": r"^Order #:\s*([A-Z]{2,4}-\d+)",
    "order_date": r"^Order date:\s*(.+)$",
    "item_name": r"^Item:\s*(.+?)\s*\(SKU",
    "sku": r"\(SKU\s+([A-Z0-9-]+)\)",
    "price": r"^Price:\s*\$([\d,]+\.\d{2})",
    "ship_zip": r"^Ship to:.*?\b(\d{5})\b\s*$",
    "tracking": r"^Carrier tracking:\s*(\S+)",
    "return_by": r"^Return by:\s*([A-Za-z]+ \d{1,2}, \d{4})",
    "delivered_on": r"delivered on ([A-Za-z]+ \d{1,2}, \d{4})",
}


def _mock_extract(text: str, sender: str = "") -> Dict[str, Any]:
    fields: Dict[str, Any] = {}
    for name, pat in _PATTERNS.items():
        m = re.search(pat, text, re.MULTILINE)
        fields[name] = m.group(1).strip() if m else None
    if fields["price"]:
        fields["price"] = float(fields["price"].replace(",", ""))
    m = re.match(r"\s*([^<]+?)\s*<", sender or "")
    fields["merchant"] = m.group(1) if m else None
    expected = ["merchant", "order_no", "order_date", "item_name", "price", "ship_zip"]
    gaps = [f for f in expected if not fields.get(f)]
    confidence = round(1.0 - 0.12 * len(gaps), 2)
    return {"fields": fields, "gaps": gaps, "confidence": confidence}


def _cos(a: Sequence[float], b: Sequence[float]) -> float:
    return float(np.dot(np.asarray(a), np.asarray(b)))


# ---------------- real calls (hosted SIE: https://api.superlinked.com) ----------------
# POST /v1/{encode|score|extract}/{url-encoded model id}, Authorization: Bearer sk-sie-...
# Serverless cold starts return 503 PROVISIONING / 429 with Retry-After: wait and retry.

DEFAULT_MODELS = {
    "image": "google/siglip-so400m-patch14-384",   # dense 1152
    "text": "BAAI/bge-m3",                          # dense 1024
    "rerank": "Qwen/Qwen3-Reranker-0.6B",
    "extract": "fastino/gliner2-large-v1",
}

EXTRACT_LABELS = {
    "order number": "order_no", "order date": "order_date", "product name": "item_name", "price": "price",
    "zip code": "ship_zip", "tracking number": "tracking", "return deadline": "return_by", "store name": "merchant",
}


def model_name(kind: str) -> str:
    configured = {"image": settings.sie_image_embed_model, "text": settings.sie_text_embed_model,
                  "extract": settings.sie_extract_model, "rerank": settings.sie_rerank_model}.get(kind)
    return configured or DEFAULT_MODELS[kind]


def _post(endpoint: str, kind: str, body: Dict[str, Any], max_wait_s: float = 120.0) -> Dict[str, Any]:
    import time
    from urllib.parse import quote

    import httpx

    base = (settings.sie_base_url or "https://api.superlinked.com").rstrip("/")
    url = f"{base}/v1/{endpoint}/{quote(model_name(kind), safe='')}"
    headers = {"Authorization": f"Bearer {settings.sie_api_key}", "Content-Type": "application/json",
               "Accept": "application/json"}
    deadline = time.time() + max_wait_s
    while True:
        r = httpx.post(url, headers=headers, json=body, timeout=60)
        if r.status_code in (429, 503) and time.time() < deadline:
            time.sleep(min(float(r.headers.get("Retry-After") or 5), 10))
            continue
        if r.status_code != 200:
            raise RuntimeError(f"SIE {endpoint} {r.status_code}: {r.text[:200]}")
        return r.json()


def _real_embed_image(path: str) -> List[float]:
    import base64
    p = Path(path)
    fmt = {".jpg": "jpeg", ".jpeg": "jpeg", ".png": "png", ".webp": "webp"}.get(p.suffix.lower(), "png")
    body = {"items": [{"images": [{"data": base64.b64encode(p.read_bytes()).decode(), "format": fmt}]}],
            "params": {"output_types": ["dense"]}}
    vec = _post("encode", "image", body)["items"][0]["dense"]["values"]
    if len(vec) != settings.image_embed_dim:
        raise RuntimeError(f"image dim {len(vec)} != IMAGE_EMBED_DIM {settings.image_embed_dim}")
    return vec


def _real_embed_text(text: str, is_query: bool = False) -> List[float]:
    params: Dict[str, Any] = {"output_types": ["dense"]}
    if is_query:
        params["options"] = {"is_query": True}
    vec = _post("encode", "text", {"items": [{"text": text}], "params": params})["items"][0]["dense"]["values"]
    if len(vec) != settings.text_embed_dim:
        raise RuntimeError(f"text dim {len(vec)} != TEXT_EMBED_DIM {settings.text_embed_dim}")
    return vec


def _real_rerank(query: str, docs: List[str]) -> List[Tuple[int, float]]:
    body = {"query": {"text": query}, "items": [{"id": str(i), "text": d} for i, d in enumerate(docs)]}
    scores = _post("score", "rerank", body)["scores"]
    return sorted(((int(s["item_id"]), float(s["score"])) for s in scores), key=lambda x: x[1], reverse=True)


def _real_extract(text: str, sender: str = "") -> Dict[str, Any]:
    """GLiNER2 spans via SIE, then validated against the email text. A field is kept only if its
    value literally appears in the email; fields the model misses fall back to the labeled line in
    the email (source: pattern). Nothing is ever invented: missing stays missing (a 'gap')."""
    body = {"items": [{"text": text}], "params": {"labels": list(EXTRACT_LABELS)}}
    entities = _post("extract", "extract", body)["items"][0].get("entities") or []
    best: Dict[str, Dict[str, Any]] = {}
    for e in entities:
        field = EXTRACT_LABELS.get(e.get("label", ""))
        if field and e.get("text") and (field not in best or e.get("score", 0) > best[field].get("score", 0)):
            best[field] = e
    pattern = _mock_extract(text, sender)["fields"]
    fields: Dict[str, Any] = {}
    sources: Dict[str, str] = {}
    for field in list(EXTRACT_LABELS.values()) + ["sku", "delivered_on"]:
        value: Any = None
        e = best.get(field)
        if e and (e["text"] in text or e["text"] in (sender or "")):
            value, sources[field] = e["text"].strip(), "sie"
            if field == "price":
                m = re.search(r"[\d,]+\.\d{2}", value)
                value = float(m.group(0).replace(",", "")) if m else None
            elif field == "ship_zip":
                # must be exactly a 5-digit span on the "Ship to" line, never digits from another field
                ship_line = next((l for l in text.splitlines() if l.startswith("Ship to:")), "")
                value = value if re.fullmatch(r"\d{5}", value) and value in ship_line else None
            elif field == "order_no" and not re.fullmatch(r"[A-Z]{2,4}-\d+", value):
                value = None
        if value is None and pattern.get(field) is not None:
            value, sources[field] = pattern[field], "pattern"
        if value is None:
            sources.pop(field, None)
        fields[field] = value
    expected = ["merchant", "order_no", "order_date", "item_name", "price", "ship_zip"]
    gaps = [f for f in expected if not fields.get(f)]
    sie_share = sum(1 for f in expected if sources.get(f) == "sie") / len(expected)
    return {"fields": fields, "gaps": gaps, "confidence": round(max(0.0, sie_share - 0.1 * len(gaps)), 2),
            "field_sources": sources, "entities": [{k: e.get(k) for k in ("label", "text", "score")} for e in entities]}


# ---------------- public interface ----------------

def embed_image(path: str) -> Tuple[List[float], Dict[str, Any]]:
    return call("sie", lambda: _real_embed_image(path), lambda: _mock_embed_image(path))


def embed_text(text: str, is_query: bool = False) -> Tuple[List[float], Dict[str, Any]]:
    return call("sie", lambda: _real_embed_text(text, is_query), lambda: _mock_embed_text(text))


def extract(text: str, sender: str = "") -> Tuple[Dict[str, Any], Dict[str, Any]]:
    return call("sie", lambda: _real_extract(text, sender), lambda: _mock_extract(text, sender))


def rerank(query: str, docs: List[str]) -> Tuple[List[Tuple[int, float]], Dict[str, Any]]:
    def mock():
        q = _mock_embed_text(query)
        scores = [(i, _cos(q, _mock_embed_text(d))) for i, d in enumerate(docs)]
        return sorted(scores, key=lambda x: x[1], reverse=True)
    return call("sie", lambda: _real_rerank(query, docs), mock)
