"""
rag.py — JSON-native grouped TF-IDF retrieval for SAP Reusable Artifacts.

Ported from FASTAPI_AI_Tool/core/rag.py (the version that fixed retrieval quality).
"""
import re
from collections import defaultdict
from typing import List

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


def retrieve_top_methods(json_classes: dict, json_fms: dict,
                         query: str, top_k: int = 5) -> List[dict]:
    """
    Gold-standard RAG that works directly on the raw OData JSON responses.

    Why this beats text-chunking:
    - OData returns ONE ROW PER PARAMETER, so a method with 4 params = 4 rows.
      Fixed-char chunking mixes ~10 unrelated methods per chunk — wrong.
    - Method names like ADD_RECIPIENTS_WITH_EMAILID are never tokenised by
      stop-word-aware TF-IDF because underscores are not whitespace.

    This function:
    1. Groups all rows by (ClassName, MethodName) or FMName.
    2. Builds ONE rich text document per unique method/FM.
    3. Expands underscores/slashes to spaces so TF-IDF sees individual tokens.
    4. Runs TF-IDF with no stop-word removal (words like 'email', 'id', 'to'
       are meaningful in SAP context).
    5. Applies a name-match bonus so that query words appearing directly in the
       class/method name push the score up.

    Returns a list of dicts:
        {'type': 'Class'|'Function Module', 'name': str, 'method': str, 'text': str}
    """

    def _records(js: dict) -> list:
        if isinstance(js, dict):
            return js.get("value", []) or js.get("results", [])
        return js or []

    def _expand(name: str) -> str:
        """Replace / and _ with spaces so TF-IDF sees individual word tokens."""
        return re.sub(r'[/_]', ' ', name).strip()

    # ── Group class records by (ClassName, MethodName) ──────────────────────
    class_groups: dict = defaultdict(list)
    for rec in _records(json_classes):
        if not isinstance(rec, dict):
            continue
        cname = rec.get("ClassName", "").strip()
        mname = rec.get("MethodName", "").strip()
        if cname:
            class_groups[(cname, mname)].append(rec)

    # ── Group FM records by FMName ───────────────────────────────────────────
    fm_groups: dict = defaultdict(list)
    for rec in _records(json_fms):
        if not isinstance(rec, dict):
            continue
        fname = rec.get("FMName", "").strip()
        if fname:
            fm_groups[fname].append(rec)

    docs: List[str] = []
    metas: List[dict] = []

    for (cname, mname), rows in class_groups.items():
        r0 = rows[0]
        parts = [
            f"ClassName: {cname}",
            f"ClassExpanded: {_expand(cname)}",
            f"MethodName: {mname}",
            f"MethodExpanded: {_expand(mname)}",
            f"ClassPurpose: {r0.get('ClassPurpose', '')}",
            f"MethodPurpose: {r0.get('MethodPurpose', '')}",
        ]
        for row in rows:
            p = row.get("ParameterName", "")
            t = row.get("ParameterType", "")
            d = row.get("ParameterPurpose", "")
            if p:
                parts.append(f"Param {p} {t} {d}")
        text = "\n".join(parts)
        docs.append(text)
        metas.append({"type": "Class", "name": cname, "method": mname, "text": text})

    for fname, rows in fm_groups.items():
        r0 = rows[0]
        parts = [
            f"FMName: {fname}",
            f"FMExpanded: {_expand(fname)}",
            f"FMPurpose: {r0.get('FMPurpose', '')}",
        ]
        for row in rows:
            p = row.get("FMParameter", "")
            t = row.get("FMParameterType", "")
            d = row.get("FMParameterPurpose", "")
            if p:
                parts.append(f"Param {p} {t} {d}")
        text = "\n".join(parts)
        docs.append(text)
        metas.append({"type": "Function Module", "name": fname, "method": "", "text": text})

    if not docs:
        return []

    vec = TfidfVectorizer(
        max_features=10000,
        ngram_range=(1, 2),
        stop_words=None,                  # keep ALL words — 'email', 'id', 'to' are meaningful
        lowercase=True,
        token_pattern=r'[a-zA-Z0-9]+',   # splits on _ / spaces — tokenises expanded names
    )
    try:
        matrix = vec.fit_transform(docs)
    except ValueError:
        return metas[:top_k]

    q_vec = vec.transform([query])
    scores = cosine_similarity(q_vec, matrix)[0]

    # ── Name-match bonus ─────────────────────────────────────────────────────
    # TF-IDF alone misses when query tokens appear in the class/method name
    # but not in the TF-IDF document body. Each matching token adds 0.35.
    _NOISE = {'from', 'with', 'call', 'make', 'that', 'this', 'have', 'will'}
    q_tokens = {t for t in re.findall(r'[a-zA-Z0-9]+', query.lower())
                if len(t) >= 4 and t not in _NOISE}
    for i, meta in enumerate(metas):
        name_str = (meta["name"] + " " + meta.get("method", "")).lower()
        name_toks = set(re.findall(r'[a-zA-Z0-9]+', name_str))
        hits = q_tokens & name_toks
        if hits:
            scores[i] += len(hits) * 0.35

    top_idx = np.argsort(scores)[::-1][:top_k]
    return [metas[i] for i in top_idx if scores[i] > 0.001]
