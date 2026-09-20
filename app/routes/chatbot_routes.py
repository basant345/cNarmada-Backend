"""
Narmada Mitra — the cNARMADA assistant.

Endpoints
---------
  GET  /api/chat/intro          greeting, suggested questions, KB size
  POST /api/chat/ask            {question, lang} -> {answer, links, suggestions}

Design
------
Answers come from a curated knowledge base (app/static/data/chatbot/
knowledge.json, built by scripts/build_chatbot_kb.py), matched with a small
TF-IDF-style scorer written in the standard library. There is no model, no
vector database and no outbound API call, which is what keeps this viable on
a free Render dyno: the knowledge base is well under a megabyte, it is read
once and cached in memory, and a question is answered in microseconds.

The trade-off is deliberate. The assistant can only say things the knowledge
base contains, so it cannot invent a figure or a dataset that does not exist.
When nothing scores well enough it says so and offers the suggestions rather
than guessing.
"""

import json
import math
import os
import re
from collections import Counter

from flask import Blueprint, current_app, jsonify, request

chatbot_bp = Blueprint("chatbot", __name__, url_prefix="/api/chat")

FOLDER = "chatbot"
KB_FILE = "knowledge.json"

# Below this score the best match is not trusted and the fallback is used.
# Off-topic questions score 0.000 here rather than merely low, because the
# index holds no generic vocabulary, so the floor can sit low enough to catch
# terse on-topic questions without letting anything unrelated through.
MIN_SCORE = 0.12
MAX_QUESTION_CHARS = 500

# Words carrying no signal on their own. Bare interrogatives are included:
# they appear in multi-word tags such as "what does this mean", and without
# this a stray "what" or "who" in an off-topic question would score against
# that tag and produce a confident wrong answer. Whole phrases are still
# matched separately, against the raw question text, so nothing is lost.
STOPWORDS = {
    "what", "how", "where", "who", "why", "when", "which", "whom", "whose",
    "a", "an", "and", "are", "as", "at", "be", "by", "can", "do", "does", "for", "from",
    "has", "have", "how", "i", "in", "is", "it", "me", "my", "of", "on", "or", "please",
    "tell", "that", "the", "there", "these", "this", "to", "was", "were", "with", "you",
    "your", "am", "will", "would", "about",
    "क्या", "है", "हैं", "का", "की", "के", "में", "से", "को", "पर", "और", "यह", "वह",
    "मुझे", "मैं", "कैसे", "कहाँ", "कौन", "बताइए", "बताएं", "हो", "था", "थी",
}

_CACHE = {"mtime": None, "kb": None, "index": None, "idf": None}


def _kb_path():
    return os.path.join(current_app.config["DATA_DIR"], FOLDER, KB_FILE)


def tokenize(text):
    """Lowercase word tokens, Devanagari included, stopwords removed."""
    words = re.findall(r"[a-z0-9]+|[ऀ-ॿ]+", str(text).lower())
    return [w for w in words if w not in STOPWORDS and len(w) > 1]


def _build_index(kb):
    """
    Turn each entry into a weighted bag of words.

    An entry's tags are what it is *about*, so they count for much more than
    the prose of its answer, which shares common vocabulary with every other
    entry and would otherwise blur the matches together.
    """
    docs = []
    for entry in kb.get("entries", []):
        counts = Counter()
        for tag in entry.get("tags", []) + entry.get("tags_hi", []):
            for token in tokenize(tag):
                counts[token] += 5
        for lang in ("en", "hi"):
            for token in tokenize(entry.get("answer", {}).get(lang, "")):
                counts[token] += 1
        phrases = [t.lower() for t in entry.get("tags", []) + entry.get("tags_hi", [])
                   if " " in t]
        docs.append({"id": entry["id"], "counts": counts, "phrases": phrases})

    n = len(docs) or 1
    seen = Counter()
    for doc in docs:
        for token in doc["counts"]:
            seen[token] += 1
    idf = {token: math.log((n + 1) / (df + 0.5)) for token, df in seen.items()}

    # Pre-normalise so scoring is a plain dot product at request time.
    for doc in docs:
        weights = {t: c * idf.get(t, 0.0) for t, c in doc["counts"].items()}
        norm = math.sqrt(sum(w * w for w in weights.values())) or 1.0
        doc["weights"] = {t: w / norm for t, w in weights.items()}

    return docs, idf


def load_kb():
    """Read and index the knowledge base, refreshing if the file changed."""
    path = _kb_path()
    if not os.path.exists(path):
        return None, None, None
    mtime = os.path.getmtime(path)
    if _CACHE["mtime"] != mtime:
        with open(path, encoding="utf-8") as fh:
            kb = json.load(fh)
        docs, idf = _build_index(kb)
        _CACHE.update({"mtime": mtime, "kb": kb, "index": docs, "idf": idf})
    return _CACHE["kb"], _CACHE["index"], _CACHE["idf"]


def score(question, docs, idf):
    """Cosine similarity between the question and every entry, best first."""
    counts = Counter(tokenize(question))
    if not counts:
        return []
    weights = {t: c * idf.get(t, 0.0) for t, c in counts.items()}
    norm = math.sqrt(sum(w * w for w in weights.values())) or 1.0
    weights = {t: w / norm for t, w in weights.items()}

    lowered = " " + question.lower().strip() + " "
    ranked = []
    for doc in docs:
        dot = sum(w * doc["weights"].get(t, 0.0) for t, w in weights.items())
        # "river atlas" as a phrase must beat two entries that each happen to
        # contain the word "river".
        # Longer phrases are more specific, so "ground water quality" has to
        # out-rank "water quality" rather than tie with it.
        best_phrase = max((len(p.split()) for p in doc.get("phrases", [])
                           if p in lowered), default=0)
        if best_phrase:
            dot += 0.2 * best_phrase
        if dot > 0:
            ranked.append((dot, doc["id"]))
    ranked.sort(reverse=True)
    return ranked


def pick_lang(value):
    return "hi" if str(value or "").lower().startswith("hi") else "en"


@chatbot_bp.route("/intro")
def intro():
    kb, _, _ = load_kb()
    lang = pick_lang(request.args.get("lang"))
    if kb is None:
        return jsonify({
            "error": "The assistant's knowledge base has not been built on this server.",
            "hint": "Run scripts/build_chatbot_kb.py.",
        }), 404
    return jsonify({
        "name": kb.get("name"),
        "name_hi": kb.get("name_hi"),
        "greeting": kb.get("greeting", {}).get(lang, ""),
        "suggestions": kb.get("suggestions", {}).get(lang, []),
        "topics": len(kb.get("entries", [])),
        "generated_on": kb.get("generated_on"),
    })


@chatbot_bp.route("/ask", methods=["POST"])
def ask():
    kb, docs, idf = load_kb()
    if kb is None:
        return jsonify({"error": "The assistant's knowledge base has not been built "
                                 "on this server."}), 404

    payload = request.get_json(silent=True) or {}
    question = str(payload.get("question", ""))[:MAX_QUESTION_CHARS].strip()
    lang = pick_lang(payload.get("lang"))

    if not question:
        return jsonify({"error": "Ask a question."}), 400

    ranked = score(question, docs, idf)
    entries = {e["id"]: e for e in kb.get("entries", [])}
    suggestions = kb.get("suggestions", {}).get(lang, [])

    if not ranked or ranked[0][0] < MIN_SCORE:
        return jsonify({
            "matched": False,
            "answer": kb.get("fallback", {}).get(lang, ""),
            "links": [],
            "related": [],
            "suggestions": suggestions,
        })

    best_score, best_id = ranked[0]
    entry = entries[best_id]

    # A couple of near misses, offered as follow-ups rather than merged into
    # the answer, so the reply stays short and the reader stays in control.
    related = []
    for s, eid in ranked[1:4]:
        if s >= MIN_SCORE * 0.8 and eid in entries:
            related.extend(entries[eid].get("links", []))
    seen = set()
    related = [l for l in related
               if l.get("to") not in seen and not seen.add(l.get("to"))][:3]

    return jsonify({
        "matched": True,
        "topic": best_id,
        "confidence": round(min(best_score, 1.0), 3),
        "answer": entry.get("answer", {}).get(lang, ""),
        "links": entry.get("links", []),
        "related": related,
        "suggestions": suggestions,
    })
