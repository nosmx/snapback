"""Senso Context Layer: trusted shopping context (policies, fees, windows, warranties, reviews).

Real calls: TODO(block 1/2) once the ingestion + query API and citation format are verified (§16).
Mock: searches the same policy markdown by section and returns the identical citation shape,
labeled source="local-mirror" so the audit trail never passes a mock off as Senso.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Dict, List, Optional, Tuple

from backend import clock
from backend.config import DATA_DIR, MOCK_DIR, settings
from backend.integrations.base import call

POLICY_DIR = MOCK_DIR / "policies"
_TOKEN = re.compile(r"[a-z0-9]+")
STOP = {"the", "a", "an", "of", "and", "or", "to", "for", "in", "on", "is", "what", "my", "at", "with", "policy"}


def _slug(text: str) -> str:
    text = re.sub(r"^\d+\.\s*", "", text.strip())
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _sections() -> List[Dict[str, Any]]:
    out = []
    for path in sorted(POLICY_DIR.glob("*.md")):
        store = path.stem
        title, current, buf = "", None, []
        for line in path.read_text().splitlines():
            if line.startswith("# "):
                title = line[2:].strip()
            elif line.startswith("## "):
                if current:
                    out.append({"store": store, "doc": title, "section": current, "text": "\n".join(buf).strip()})
                current, buf = line[3:].strip(), []
            elif current is not None:
                buf.append(line)
        if current:
            out.append({"store": store, "doc": title, "section": current, "text": "\n".join(buf).strip()})
    return out


def _citation(sec: Dict[str, Any], source: str) -> Dict[str, Any]:
    return {
        "doc": sec["doc"], "store": sec["store"], "section": sec["section"],
        "url": f"{settings.merchant_base_url}/s/{sec['store']}/policy#{_slug(sec['section'])}",
        "retrieved_at": clock.iso(clock.now()), "quote": sec["text"][:600], "source": source,
    }


def _mock_query(question: str, store: Optional[str], k: int) -> Dict[str, Any]:
    q = {t for t in _TOKEN.findall(question.lower()) if t not in STOP}
    scored = []
    for sec in _sections():
        if store and sec["store"] != store:
            continue
        words = set(_TOKEN.findall((sec["section"] + " " + sec["text"]).lower()))
        score = len(q & words) + 2 * len(q & set(_TOKEN.findall(sec["section"].lower())))
        if score:
            scored.append((score, sec))
    scored.sort(key=lambda x: x[0], reverse=True)
    top = [s for _, s in scored[:k]]
    return {"answer": top[0]["text"] if top else "", "citations": [_citation(s, "local-mirror") for s in top],
            "found": bool(top)}


# ---------------- real calls (Senso Org API) ----------------
# Base https://apiv2.senso.ai/api/v1, header X-API-Key: tgr_...
#   POST /org/kb/raw              {title, text}           -> 202 {id, kb_node_id, processing_status}
#   GET  /org/kb/nodes/{id}                                -> content.processing_status
#   POST /org/search/context      {query, max_results, search_type, content_ids} -> {results: [chunk]}

REGISTRY = DATA_DIR / "senso_docs.json"   # doc_id -> {content_id, kb_node_id, hash, title, store}


def _api(method: str, path: str, **kw):
    import httpx
    base = (settings.senso_base_url or "https://apiv2.senso.ai/api/v1").rstrip("/")
    r = httpx.request(method, base + path, headers={"X-API-Key": settings.senso_api_key,
                                                    "Accept": "application/json"}, timeout=30, **kw)
    if r.status_code >= 400:
        raise RuntimeError(f"Senso {method} {path} {r.status_code}: {r.text[:200]}")
    return r.json() if r.content else {}


def _registry() -> Dict[str, Any]:
    try:
        return json.loads(REGISTRY.read_text())
    except (FileNotFoundError, ValueError):
        return {}


def _save_registry(reg: Dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    REGISTRY.write_text(json.dumps(reg, indent=2))


def _real_ingest(doc_id: str, title: str, markdown: str, metadata: Dict[str, Any]) -> Dict[str, Any]:
    reg = _registry()
    digest = hashlib.sha256(markdown.encode()).hexdigest()
    old = reg.get(doc_id)
    if old and old.get("hash") == digest:
        return {"doc_id": doc_id, "status": "unchanged", **old}
    content = _api("POST", "/org/kb/raw", json={"title": title, "text": markdown,
                                                 "summary": f"Store policy: {metadata.get('store', doc_id)}"})
    entry = {"content_id": content["id"], "kb_node_id": content.get("kb_node_id"), "hash": digest,
             "title": title, "store": metadata.get("store", doc_id)}
    if old and old.get("kb_node_id"):
        try:
            _api("DELETE", f"/org/kb/nodes/{old['kb_node_id']}")
        except Exception:
            pass
    reg[doc_id] = entry
    _save_registry(reg)
    return {"doc_id": doc_id, "status": content.get("processing_status", "pending"), **entry}


def processing_status(doc_id: str) -> str:
    entry = _registry().get(doc_id)
    if not entry or not entry.get("kb_node_id"):
        return "unknown"
    node = _api("GET", f"/org/kb/nodes/{entry['kb_node_id']}")
    return ((node.get("content") or {}).get("processing_status")) or node.get("processing_status") or "unknown"


def _best_section(text: str, chunk_index: int, question: str) -> Tuple[str, str, int]:
    """A Senso chunk can span several '## ' sections. Return (section, quote, overlap) for the
    section inside the chunk that best matches the question, so citations point at the exact clause."""
    parts: List[Tuple[str, List[str]]] = [("", [])]
    for line in text.splitlines():
        m = re.match(r"^##\s+(.+)$", line)
        if m:
            parts.append((m.group(1).strip(), []))
        elif not line.startswith("# "):
            parts[-1][1].append(line)
    q = {t for t in _TOKEN.findall(question.lower()) if t not in STOP}
    best = ("", "", -1)
    for head, lines in parts:
        body = "\n".join(lines).strip()
        if not body:
            continue
        if not head:
            head = "5. Policy summary" if re.search(r"^-\s*[a-z_]+:", body, re.MULTILINE) else f"chunk {chunk_index}"
        words = set(_TOKEN.findall((head + " " + body).lower().replace("_", " ")))
        overlap = len(q & words) + 2 * len(q & set(_TOKEN.findall(head.lower())))
        if overlap > best[2]:
            best = (head, body, overlap)
    return best


def _real_query(question: str, store: Optional[str], k: int) -> Dict[str, Any]:
    reg = _registry()
    body: Dict[str, Any] = {"query": question, "max_results": max(k, 1), "search_type": "hybrid"}
    if store:
        if store not in reg:
            # no verified policy for this store in Senso -> caller must not act
            return {"answer": "", "citations": [], "found": False}
        body["content_ids"] = [reg[store]["content_id"]]
        body["require_scoped_ids"] = True
    res = _api("POST", "/org/search/context", json=body)
    by_content = {v["content_id"]: (sid, v) for sid, v in reg.items()}
    citations = []
    for ch in res.get("results", []):
        sid, entry = by_content.get(ch.get("content_id"), (store, {}))
        chunk_text = ch.get("chunk_text") or ""
        section, quote, overlap = _best_section(chunk_text, ch.get("chunk_index", 0), question)
        citations.append({
            "doc": ch.get("title") or entry.get("title"), "store": sid, "section": section,
            "url": f"{settings.merchant_base_url}/s/{sid}/policy#{_slug(section)}" if sid else None,
            "retrieved_at": clock.iso(clock.now()), "quote": quote[:800], "chunk_text": chunk_text,
            "source": "senso", "senso_kb_node_id": ch.get("kb_node_id"), "senso_content_id": ch.get("content_id"),
            "chunk_index": ch.get("chunk_index"), "score": ch.get("score"), "_overlap": overlap,
        })
    # prose clauses first for the human-facing citation; Senso's score breaks ties
    citations.sort(key=lambda c: (c["section"].endswith("Policy summary"), -c["_overlap"], -(c["score"] or 0)))
    for c in citations:
        c.pop("_overlap", None)
    return {"answer": citations[0]["quote"] if citations else "", "citations": citations, "found": bool(citations)}


# ---------------- public interface ----------------

def ingest(doc_id: str, title: str, markdown: str, metadata: Optional[Dict[str, Any]] = None):
    return call("senso", lambda: _real_ingest(doc_id, title, markdown, metadata or {}),
                lambda: {"doc_id": doc_id, "status": "mirrored-locally"})


def query(question: str, store: Optional[str] = None, k: int = 5) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    return call("senso", lambda: _real_query(question, store, k), lambda: _mock_query(question, store, k))


def parse_summary(text: str) -> Dict[str, Any]:
    """Parse '- key: value' lines from a cited 'Policy summary' section into typed values."""
    out: Dict[str, Any] = {}
    for m in re.finditer(r"^-\s*([a-z_]+):\s*(.+?)\s*$", text, re.MULTILINE):
        key, raw = m.group(1), m.group(2)
        if raw.lower() in ("true", "false"):
            out[key] = raw.lower() == "true"
        else:
            try:
                out[key] = float(raw) if "." in raw else int(raw)
            except ValueError:
                out[key] = raw
    return out


def policy_summary(store: str) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]], Dict[str, Any]]:
    """Returns (facts, citation, meta). facts is None when no verified policy exists -> do not act.
    Merges summary lines across chunks in case Senso split the list."""
    res, meta = query("Policy summary: return_window_days restocking_fee return_shipping "
                      "price_adjustment_window_days price_adjustment_allowed warranty_days", store=store, k=5)
    facts: Dict[str, Any] = {}
    cite = None
    for cit in res.get("citations", []):
        parsed = parse_summary(cit.get("chunk_text") or cit["quote"])
        if parsed:
            facts.update(parsed)
            if cite is None or "summary" in cit["section"].lower():
                cite = cite if (cite and "summary" in cite["section"].lower()) else cit
    if "return_window_days" in facts and cite:
        return facts, cite, meta
    return None, None, meta
