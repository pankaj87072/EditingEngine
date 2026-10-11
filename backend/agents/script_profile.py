"""
agents/script_profile.py
------------------------
Deterministic, LLM-free script understanding. Adds to every ScriptScene:
role (hook/intro/body/payoff/cta), intent, editing energy, nouns, verbs,
important words (caption emphasis) and a visual-intent search vocabulary.

Honest limits: there is no part-of-speech tagger here. nouns/verbs are heuristics
(word lists + suffixes) and intent is vocabulary matching. They are good enough to
drive scoring and emphasis, and an optional AI planner can refine them.
"""

from __future__ import annotations

import re
from typing import Dict, List

from models.schema import ScriptScene

STOP = {
    "a", "an", "the", "and", "or", "but", "if", "then", "so", "of", "to", "in", "on", "at", "for", "with", "from",
    "by", "as", "is", "are", "was", "were", "be", "been", "it", "its", "this", "that", "these", "those", "you",
    "your", "we", "our", "they", "their", "i", "my", "me", "he", "she", "him", "her", "them", "us", "do", "does",
    "did", "have", "has", "had", "will", "would", "can", "could", "should", "just", "than", "too", "very", "more",
    "most", "some", "any", "all", "about", "every", "single", "time", "already", "still", "even", "ever", "much", "many", "each", "own", "one", "wrong", "into", "up", "out", "what", "which", "who", "when", "where", "why",
    "how", "also", "there", "here", "not", "no", "yes", "get", "got", "like", "really",
}
INTENSITY = {
    "stop", "never", "secret", "mistake", "mistakes", "worst", "best", "amazing", "insane", "free", "warning",
    "danger", "hate", "love", "wasting", "wasted", "waste", "finally", "biggest", "huge", "shocking", "truth",
    "lie", "lies", "changed", "instantly", "ruin", "destroy", "bad", "terrible", "cheap", "powerful", "easy",
    "fast", "now", "only", "everyone", "nobody", "always",
}
NEGATION = {"stop", "never", "don't", "dont", "no", "not", "without", "avoid", "quit"}
WEAK_EMPHASIS = {"stop", "now", "only", "always", "everyone", "nobody"}
VERB_HINTS = {
    "make", "build", "learn", "try", "start", "use", "write", "edit", "cook", "mix", "add", "follow", "click",
    "tap", "buy", "choose", "pick", "keep", "cut", "show", "watch", "save", "share", "stop", "flip", "take",
    "go", "see", "look", "find", "need", "want", "know", "think", "say", "tell", "work", "run", "grow", "win",
}
ADJ_HINTS = {"bad", "good", "best", "worst", "new", "old", "cheap", "simple", "easy", "hard", "big", "small",
             "great", "better", "fast", "slow", "short", "long", "free", "perfect", "huge"}
CTA_RE = re.compile(
    r"\b(follow|subscribe|comment|share|save this|link in (my )?bio|click|tap|visit|sign up|join|download|order|"
    r"shop|try|get yours|learn more|check (it )?out|dm me|book|call us|available)\b", re.I)
PAYOFF_RE = re.compile(r"\b(finally|result|that'?s why|this is how|and that|the answer|which means|so now)\b", re.I)

INTENT_VOCAB: Dict[str, List[str]] = {
    "problem": ["problem", "issue", "mistake", "wrong", "bad", "wast", "broken", "fail", "struggl", "hate", "worst", "expensive", "slow"],
    "product": ["product", "camera", "phone", "device", "gadget", "tool", "brand", "buy", "price", "review", "feature", "model", "gear", "lens"],
    "action": ["step", "make", "build", "learn", "try", "start", "write", "edit", "cook", "mix", "add", "cut", "choose", "pick"],
    "result": ["result", "finally", "better", "improv", "grow", "save", "success", "boost", "transform", "win"],
    "emotion": ["love", "happy", "feel", "excit", "afraid", "amaz", "shock", "wow", "proud", "stress"],
    "people": ["people", "everyone", "team", "friend", "customer", "creator", "family", "client", "person"],
    "place": ["office", "home", "kitchen", "street", "city", "outside", "outdoor", "beach", "gym", "store", "studio", "room", "park"],
    "screen": ["screen", "app", "website", "dashboard", "online", "software", "laptop", "computer", "code", "click"],
    "food": ["food", "coffee", "recipe", "eat", "meal", "drink", "pizza", "taste"],
}
VISUAL_TERMS: Dict[str, List[str]] = {
    "problem": ["problem", "closeup", "reaction"], "product": ["product", "closeup", "detail", "hands"],
    "action": ["hands", "action", "process"], "result": ["result", "wide", "smile"],
    "emotion": ["face", "reaction", "closeup"], "people": ["person", "face", "group"],
    "place": ["wide", "environment"], "screen": ["screen", "laptop"], "food": ["food", "closeup"], "generic": [],
}


def _tokens(text: str) -> List[str]:
    return [w.strip(".,!?;:\"'()[]").lower() for w in text.split() if w.strip(".,!?;:\"'()[]")]


def classify_intent(tokens: List[str]) -> str:
    scores = {k: 0 for k in INTENT_VOCAB}
    for t in tokens:
        for intent, vocab in INTENT_VOCAB.items():
            if any(t.startswith(v) for v in vocab):
                scores[intent] += 1
    best = max(scores, key=lambda k: scores[k])
    return best if scores[best] > 0 else "generic"


def _split_pos(tokens: List[str]):
    verbs, nouns = [], []
    for t in tokens:
        if t in STOP or len(t) < 3:
            continue
        if t in ADJ_HINTS:
            continue
        if t in VERB_HINTS or (len(t) > 4 and (t.endswith("ing") or t.endswith("ed"))):
            verbs.append(t)
        else:
            nouns.append(t)
    return list(dict.fromkeys(nouns)), list(dict.fromkeys(verbs))


def important_words(text: str, nouns: List[str], keywords: List[str], limit: int = 3) -> List[str]:
    words = text.split()
    scores: Dict[str, float] = {}
    for i, raw in enumerate(words):
        w = raw.strip(".,!?;:\"'()[]")
        lw = w.lower()
        if not lw or lw in STOP or len(lw) < 3:
            continue
        s = 0.0
        if lw in INTENSITY:
            s += 2.0 if lw in WEAK_EMPHASIS else 3.0
        if any(ch.isdigit() for ch in lw):
            s += 2.5
        if w[:1].isupper() and i > 0 and not words[i - 1].endswith((".", "!", "?")):
            s += 2.0
        if lw in nouns:
            s += 1.5
        if len(lw) > 6:
            s += 1.0
        if lw in keywords:
            s += 0.5
        if s > 0:
            scores[lw] = max(scores.get(lw, 0.0), s)
    top = sorted(scores, key=lambda k: -scores[k])[:limit]
    order = {w.strip(".,!?;:\"'()[]").lower(): i for i, w in reversed(list(enumerate(words)))}
    return sorted(top, key=lambda k: order.get(k, 0))


def scene_energy(text: str, tokens: List[str], role: str) -> float:
    e = 0.45
    if "!" in text:
        e += 0.2
    if "?" in text:
        e += 0.1
    hits = sum(1 for t in tokens if t in INTENSITY)
    e += 0.15 if hits >= 1 else 0.0
    e += 0.1 if hits >= 2 else 0.0
    if tokens and (tokens[0] in NEGATION or tokens[0] in VERB_HINTS):
        e += 0.1
    if len(tokens) <= 8:
        e += 0.1
    if any(ch.isdigit() for ch in text):
        e += 0.05
    e += {"hook": 0.2, "cta": -0.1, "payoff": 0.05}.get(role, 0.0)
    return round(max(0.1, min(1.0, e)), 2)


def assign_roles(scenes: List[ScriptScene]) -> List[str]:
    n = len(scenes)
    roles = ["body"] * n
    if n == 0:
        return roles
    roles[0] = "hook"
    cta_idx = None
    if n >= 2 and CTA_RE.search(scenes[-1].text):
        cta_idx = n - 1
    elif n >= 3:
        cta_idx = None
    if cta_idx is not None:
        roles[cta_idx] = "cta"
    if n >= 5:
        roles[1] = "intro"
    pay = (cta_idx - 1) if cta_idx is not None else (n - 1 if n >= 3 else None)
    if pay is not None and pay > 0 and roles[pay] == "body" and (n >= 4 or PAYOFF_RE.search(scenes[pay].text)):
        roles[pay] = "payoff"
    return roles


def enrich_scenes(scenes: List[ScriptScene]) -> List[ScriptScene]:
    roles = assign_roles(scenes)
    out: List[ScriptScene] = []
    for sc, role in zip(scenes, roles):
        toks = _tokens(sc.text)
        nouns, verbs = _split_pos(toks)
        intent = classify_intent(toks)
        out.append(sc.model_copy(update={
            "role": role,
            "intent": intent,
            "energy": scene_energy(sc.text, toks, role),
            "nouns": nouns[:6],
            "verbs": verbs[:6],
            "important_words": important_words(sc.text, nouns, sc.keywords),
            "visual_intent": VISUAL_TERMS.get(intent, []),
        }))
    return out
