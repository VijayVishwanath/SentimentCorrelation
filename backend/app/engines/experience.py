"""Module 1 — Experience Analytics.

Sentiment analysis, frustration scoring, emotion classification and experience
severity for service-desk calls, tickets and chats.

The text scorer is a transparent keyword lexicon ported unchanged from the
validated prototype (93.3% agreement with the hidden ground-truth tier). The
behavioural boost from the requirements spec (repeat contacts x10,
escalations x15) is layered on top to produce the final Frustration Score.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# ---- Validated text lexicon (do not change weights without re-validating) ----
NEG_HIGH_STRONG = ["unacceptable", "can't get my work done"]
NEG_HIGH = ["is urgent", "losing hours", "multiple times", "nothing has changed"]
NEG_MED = ["frustrating", "second time", "keeps happening", "need this looked at", "slowing me down"]
REPEAT_MARKERS = [
    "time i'm reporting",
    "same issue as last week",
    "following up again",
    "still not resolved",
    "no change since",
]
LEXICON_WEIGHTS: list[tuple[list[str], int]] = [
    (NEG_HIGH_STRONG, 54),
    (NEG_HIGH, 35),
    (NEG_MED, 25),
    (REPEAT_MARKERS, 18),
]
TEXT_BASELINE = 8

# Softeners: phrases signalling calm, low-urgency contact (used for polarity only)
SOFTENERS = ["quick question", "not urgent", "just noticed", "wanted to check", "wanted to confirm",
             "double-checking", "general question", "small request", "thanks"]

# ---- Emotion lexicon ----
EMOTION_LEXICON: dict[str, list[str]] = {
    "Anger": ["unacceptable", "can't get my work done", "ridiculous", "fed up"],
    "Frustration": ["frustrating", "keeps happening", "nothing has changed", "multiple times",
                    "still not resolved", "no change since", "same issue", "following up again",
                    "time i'm reporting", "second time", "slowing me down"],
    "Anxiety": ["is urgent", "losing hours", "need this looked at", "deadline", "asap", "soon"],
    "Inquiry": ["quick question", "wanted to confirm", "general question", "double-checking",
                "wanted to check", "small request"],
}
EMOTIONS = ["Anger", "Frustration", "Anxiety", "Inquiry", "Neutral"]


def text_frustration(text: str | None) -> int:
    """Lexicon frustration score (0-100) from free text alone — the validated scorer."""
    t = (text or "").lower()
    score = TEXT_BASELINE
    for words, weight in LEXICON_WEIGHTS:
        for w in words:
            if w in t:
                score += weight
    return min(100, score)


def matched_phrases(text: str | None) -> list[dict]:
    """Explainability: which lexicon entries fired and what they contributed."""
    t = (text or "").lower()
    out = []
    for words, weight in LEXICON_WEIGHTS:
        for w in words:
            if w in t:
                out.append({"phrase": w, "weight": weight})
    return out


def sentiment_tier(text_score: float) -> str:
    """Three-tier label the lexicon was validated against."""
    return "Low" if text_score < 28 else "Medium" if text_score < 62 else "High"


def sentiment_polarity(text: str | None) -> float:
    """Signed sentiment in [-1, 1]; negative = unhappy."""
    t = (text or "").lower()
    neg = (text_frustration(t) - TEXT_BASELINE) / (100 - TEXT_BASELINE)
    pos = min(1.0, 0.25 * sum(1 for s in SOFTENERS if s in t))
    return round(max(-1.0, min(1.0, pos * (1 - neg) - neg)), 3)


def classify_emotion(text: str | None) -> dict:
    t = (text or "").lower()
    hits = {e: sum(1 for w in words if w in t) for e, words in EMOTION_LEXICON.items()}
    # Anger and anxiety are stronger signals than a single frustration marker
    weighted = {"Anger": hits["Anger"] * 2.0, "Frustration": hits["Frustration"] * 1.0,
                "Anxiety": hits["Anxiety"] * 1.5, "Inquiry": hits["Inquiry"] * 0.8}
    total = sum(weighted.values())
    if total == 0:
        return {"primary": "Neutral", "distribution": {e: (1.0 if e == "Neutral" else 0.0) for e in EMOTIONS}}
    dist = {e: round(v / total, 3) for e, v in weighted.items()}
    dist["Neutral"] = 0.0
    primary = max(weighted, key=weighted.get)
    return {"primary": primary, "distribution": dist}


def experience_severity(frustration_score: float) -> str:
    """Four-tier severity from the requirements spec."""
    if frustration_score >= 80:
        return "Critical"
    if frustration_score >= 60:
        return "High"
    if frustration_score >= 40:
        return "Medium"
    return "Low"


def calculate_frustration(text: str | None, repeat_contacts: int = 0, escalation_count: int = 0) -> int:
    """Final Frustration Score (0-100) = validated text score + behavioural boost.

    repeat_contacts = number of *prior* contacts about the same issue.
    """
    boost = 10 * max(0, repeat_contacts) + 15 * max(0, escalation_count)
    return int(min(100, text_frustration(text) + boost))


@dataclass
class ExperienceResult:
    text_score: int
    frustration_score: int
    sentiment: float
    sentiment_tier: str
    severity: str
    emotion: str
    emotion_distribution: dict
    matched_phrases: list[dict] = field(default_factory=list)
    repeat_contacts: int = 0
    escalations: int = 0

    def as_dict(self) -> dict:
        return self.__dict__.copy()


LEXICON_GROUPS = [("Strong negative", NEG_HIGH_STRONG), ("High negative", NEG_HIGH), ("Negative", NEG_MED),
                  ("Repeat marker", REPEAT_MARKERS)]
SEVERITY_BANDS = [("Low", 0, 39), ("Medium", 40, 59), ("High", 60, 79), ("Critical", 80, 100)]
EMOTION_WEIGHTS = {"Anger": 2.0, "Frustration": 1.0, "Anxiety": 1.5, "Inquiry": 0.8}


def _spans(t: str, phrases: list[str], kind: str, taken: list[tuple[int, int]], weight: dict | None = None) -> list[dict]:
    out = []
    for p in sorted(set(phrases), key=len, reverse=True):  # longest first, so "same issue as last week" wins over "same issue"
        i = t.find(p)
        if i < 0 or any(i < b and a < i + len(p) for a, b in taken):
            continue
        taken.append((i, i + len(p)))
        out.append({"start": i, "end": i + len(p), "phrase": p, "kind": kind, **({"weight": weight[p]} if weight else {})})
    return out


def explain(text: str | None, repeat_contacts: int = 0, escalation_count: int = 0) -> dict:
    """Step-by-step derivation of the Frustration Score, emotion and sentiment (the same arithmetic as analyze_text)."""
    raw = text or ""
    t = raw.lower()
    weight = {w: wt for words, wt in LEXICON_WEIGHTS for w in words}
    group = {w: g for g, words in LEXICON_GROUPS for w in words}
    steps = [{"label": "Baseline (every contact)", "group": "Baseline", "points": TEXT_BASELINE}]
    for g, words in LEXICON_GROUPS:
        steps += [{"label": f"“{w}”", "group": g, "points": weight[w]} for w in words if w in t]
    text_raw = sum(s["points"] for s in steps)
    text_score = min(100, text_raw)
    rep, esc = max(0, repeat_contacts), max(0, escalation_count)
    if rep:
        steps.append({"label": f"{rep} prior contact(s) × 10", "group": "Behaviour", "points": 10 * rep})
    if esc:
        steps.append({"label": f"{esc} escalation(s) × 15", "group": "Behaviour", "points": 15 * esc})
    total_raw = text_score + 10 * rep + 15 * esc
    final = int(min(100, total_raw))
    running = 0
    for s in steps:
        running += s["points"]
        s["running_total"] = running

    taken: list[tuple[int, int]] = []
    spans = _spans(t, [w for w in weight if w in t], "score", taken, weight)
    emo_words = [w for words in EMOTION_LEXICON.values() for w in words if w in t and w not in weight]
    spans += _spans(t, emo_words, "emotion", taken) + _spans(t, [s for s in SOFTENERS if s in t], "calm", taken)
    for s in spans:
        s["group"] = group.get(s["phrase"]) or next((e for e, ws in EMOTION_LEXICON.items() if s["phrase"] in ws), "Softener")

    emo = classify_emotion(raw)
    hits = [{"emotion": e, "phrases": [w for w in words if w in t], "weight": EMOTION_WEIGHTS[e],
             "score": round(EMOTION_WEIGHTS[e] * sum(1 for w in words if w in t), 2)} for e, words in EMOTION_LEXICON.items()]
    neg = (text_score - TEXT_BASELINE) / (100 - TEXT_BASELINE)
    softeners = [s for s in SOFTENERS if s in t]
    pos = min(1.0, 0.25 * len(softeners))
    result = analyze_text(raw, repeat_contacts, escalation_count)
    assert result.frustration_score == final  # the explanation must be the score, not a paraphrase of it
    return {
        "text": raw, "spans": sorted(spans, key=lambda s: s["start"]), "steps": steps,
        "text_score": text_score, "text_capped_points": max(0, text_raw - 100),
        "frustration_score": final, "capped_points": running - final,  # points above the 100 cap (text and total)
        "severity": result.severity, "severity_bands": [{"band": b, "from": lo, "to": hi} for b, lo, hi in SEVERITY_BANDS],
        "sentiment_tier": result.sentiment_tier,
        "emotion": {"primary": emo["primary"], "hits": hits, "distribution": emo["distribution"]},
        "sentiment": {"polarity": result.sentiment, "negativity": round(neg, 3), "positivity": round(pos, 3),
                      "softeners": softeners, "formula": "polarity = positivity × (1 − negativity) − negativity"},
        "method": {
            "summary": "Transparent keyword lexicon: every matched phrase adds a fixed weight to a baseline of 8; "
                       "prior contacts add 10 each and escalations 15 each; the total is capped at 100.",
            "validation": "93.3% agreement with the hidden ground-truth tier on the simulated dataset",
            "lexicon": [{"group": g, "weight": next(wt for words, wt in LEXICON_WEIGHTS if words is ws), "phrases": ws}
                        for g, ws in LEXICON_GROUPS],
            "why_rules": "Every point is traceable to a phrase or a behaviour, so the score can be audited, "
                         "challenged and tuned; the ML second opinion in Diagnosis Assist is kept separate.",
        },
    }


def analyze_text(text: str | None, repeat_contacts: int = 0, escalation_count: int = 0) -> ExperienceResult:
    ts = text_frustration(text)
    fs = calculate_frustration(text, repeat_contacts, escalation_count)
    emo = classify_emotion(text)
    return ExperienceResult(
        text_score=ts,
        frustration_score=fs,
        sentiment=sentiment_polarity(text),
        sentiment_tier=sentiment_tier(ts),
        severity=experience_severity(fs),
        emotion=emo["primary"],
        emotion_distribution=emo["distribution"],
        matched_phrases=matched_phrases(text),
        repeat_contacts=repeat_contacts,
        escalations=escalation_count,
    )
