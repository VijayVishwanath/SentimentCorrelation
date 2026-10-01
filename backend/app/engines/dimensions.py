"""Experience dimensions beyond frustration: business impact, urgency and trust in IT.

Frustration (engines/experience.py) says how upset the employee is. These three say why the ticket matters:

  * Business impact: how much work the problem stops (can't work, lost hours, disrupted meetings, team-wide).
  * Urgency: how soon the employee needs it fixed (explicit urgency, asks for action, deadlines, escalation).
  * Trust in IT: whether the employee is losing confidence that IT fixes things (the fix didn't hold,
    recurrence, repeat contacts, reopened tickets).

Each is a transparent rule score (0-100): cue families matched on word boundaries, each family counted once
so one ticket can't stack the same idea, plus behaviour from the ticket record. Every point is traceable to a
cue, like the frustration score. There is no ground truth for these dimensions; /models/metrics reports a
behavioural check instead of an accuracy figure.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

LEVELS = [(60, "High"), (30, "Medium"), (0, "Low")]
DIMENSIONS = {"impact": "Business impact", "urgency": "Urgency", "trust": "Trust in IT"}


@dataclass(frozen=True)
class Family:
    label: str
    weight: int
    pattern: re.Pattern


def _f(label: str, weight: int, *phrases: str) -> Family:
    return Family(label, weight, re.compile(r"\b(?:" + "|".join(phrases) + r")\b"))


FAMILIES: dict[str, list[Family]] = {
    "impact": [
        _f("Can't work", 60, r"can'?t get (?:my|any) work done", r"cannot work(?: at all)?", r"can'?t work(?: like this)?",
           r"unusable", r"completely blocked", r"unable to work", r"stopped me working"),
        _f("Productivity loss", 40, r"losing hours", r"lost (?:an hour|hours|half a day|the morning)",
           r"slowing me down", r"cutting into my \w+", r"wasting (?:time|hours)", r"behind on my work"),
        _f("Meeting or client disruption", 20, r"had to drop off", r"client call", r"customer call", r"mid-presentation",
           r"during (?:a|the|my) (?:presentation|demo)", r"video call", r"mid-meeting", r"meetings?"),
        _f("Team-wide", 25, r"affecting my whole team", r"whole team", r"coworkers", r"colleagues (?:have|are|also)",
           r"everyone on (?:my|the) team"),
        _f("Data loss", 30, r"los(?:e|ing|t) (?:unsaved )?(?:work|drafts?|my session|data|files?)", r"unsaved work"),
    ],
    "urgency": [
        _f("Explicit urgency", 60, r"urgent(?:ly)?", r"asap", r"as soon as possible", r"immediately", r"right away",
           r"critical issue", r"emergency"),
        _f("Asks for action", 20, r"need this looked at", r"needs? to be fixed", r"please fix", r"fix (?:this|it) (?:now|today)",
           r"need a (?:replacement|fix)", r"need help now"),
        _f("Deadline", 15, r"deadline", r"before my (?:presentation|meeting|demo|call)", r"by end of (?:day|today)",
           r"\beod", r"first thing tomorrow"),
    ],
    "trust": [
        _f("The fix didn't hold", 45, r"nothing (?:has )?changed (?:after|since)", r"happening again after",
           r"still not (?:resolved|fixed|working)", r"still (?:crashes|crashing|failing|locked out|broken|slow)",
           r"not fixed", r"same problem after", r"came back after"),
        _f("Recurrence", 20, r"(?:second|third|fourth|fifth|\d+(?:st|nd|rd|th)) time", r"same issue as last week",
           r"again", r"every single day", r"keeps happening", r"yet again"),
    ],
}
# "not urgent", "no rush", "not a big deal": calm language that would otherwise match a cue
NEGATED = re.compile(r"\b(?:not|no|isn'?t|nothing|never)\s+(?:that\s+|very\s+|really\s+|super\s+)?"
                     r"(?:urgent(?:ly)?|critical|asap|an emergency|a big deal|rush(?:ed)?|blocked|unusable)\b")
BEHAVIOUR = {"escalated": 25, "prior_contact": 12, "prior_contact_cap": 36, "reopened": 20}


def level(score: float) -> str:
    return next(name for floor, name in LEVELS if score >= floor)


def _match(text: str, families: list[Family]) -> list[dict]:
    cues = []
    for fam in families:
        hits = [{"phrase": m.group(0), "start": m.start(), "end": m.end()} for m in fam.pattern.finditer(text)]
        if hits:
            cues.append({"family": fam.label, "weight": fam.weight, "kind": "text", "matches": hits})
    return cues


def score_dimensions(text: str | None, prior_contacts: int = 0, escalated: bool = False, reopened: bool = False) -> dict:
    """{impact, urgency, trust} each {score, level, cues}, plus primary_concern (None when all are Low)."""
    t = NEGATED.sub(lambda m: " " * len(m.group(0)), (text or "").lower())  # blank, not delete: spans keep their offsets
    out: dict = {}
    for key, families in FAMILIES.items():
        cues = _match(t, families)
        if key == "urgency" and escalated:
            cues.append({"family": "Escalated", "weight": BEHAVIOUR["escalated"], "kind": "behaviour", "matches": []})
        if key == "trust":
            n = max(0, int(prior_contacts))
            if n:
                pts = min(BEHAVIOUR["prior_contact_cap"], BEHAVIOUR["prior_contact"] * n)
                cues.append({"family": f"{n} prior contact(s)", "weight": pts, "kind": "behaviour", "matches": []})
            if reopened:
                cues.append({"family": "Reopened", "weight": BEHAVIOUR["reopened"], "kind": "behaviour", "matches": []})
        score = min(100, sum(c["weight"] for c in cues))
        out[key] = {"label": DIMENSIONS[key], "score": score, "level": level(score), "cues": cues}
    top = max(DIMENSIONS, key=lambda k: out[k]["score"])
    out["primary_concern"] = DIMENSIONS[top] if out[top]["level"] != "Low" else None
    return out


def flat(d: dict) -> dict:
    """Store columns: impact_score, impact_level, ..., primary_concern."""
    row = {f"{k}_score": d[k]["score"] for k in DIMENSIONS} | {f"{k}_level": d[k]["level"] for k in DIMENSIONS}
    return row | {"primary_concern": d["primary_concern"]}


def _excerpt(text: str, fam: Family, width: int = 34) -> str:
    """The part of a ticket around the cue, so the example shows why it counted."""
    m = fam.pattern.search(NEGATED.sub(lambda x: " " * len(x.group(0)), text.lower()))
    if not m:
        return text[:2 * width]
    a, b = max(0, m.start() - width), min(len(text), m.end() + width)
    return ("…" if a else "") + text[a:b].strip() + ("…" if b < len(text) else "")


def summarize(tk) -> dict:
    """Fleet view for Experience Analytics: per dimension the average, the High and elevated (Medium+High) share,
    a weekly High-share trend, the cue families behind it and the departments most affected."""
    import pandas as pd
    n = len(tk)
    if not n:
        return {}
    texts = tk["ticket_text"].fillna("").str.lower()
    cache: dict[str, set] = {}

    def fams(t: str) -> set:  # cue families present in a text (text cues only; behaviour is in the scores)
        if t not in cache:
            clean = NEGATED.sub(" ", t)
            cache[t] = {(k, f.label) for k, fl in FAMILIES.items() for f in fl if f.pattern.search(clean)}
        return cache[t]
    present = texts.map(fams)
    out = {}
    for key, label in DIMENSIONS.items():
        lvl = tk[f"{key}_level"]
        high = lvl.eq("High")
        weekly = tk.assign(_h=high).groupby("week")["_h"].mean().mul(100).round(1)
        dept = (tk.assign(_h=high).groupby("department")["_h"].mean().mul(100).round(1)
                .sort_values(ascending=False).head(5))
        cues = []
        for fam in FAMILIES.get(key, []):
            hit = present.map(lambda s, f=fam.label: (key, f) in s)
            if hit.any():
                cues.append({"family": fam.label, "weight": fam.weight, "tickets": int(hit.sum()),
                             "share_pct": round(100 * hit.mean(), 1),
                             "example": _excerpt(tk.loc[hit, "ticket_text"].iloc[0], fam)})
        out[key] = {"label": label, "avg_score": round(float(tk[f"{key}_score"].mean()), 1),
                    "high_pct": round(100 * float(high.mean()), 1),
                    "elevated_pct": round(100 * float(lvl.isin(["High", "Medium"]).mean()), 1),
                    "weekly_high_pct": [{"week": int(w), "high_pct": float(v)} for w, v in weekly.items()],
                    "top_departments": [{"department": d, "high_pct": float(v)} for d, v in dept.items()],
                    "cues": sorted(cues, key=lambda c: -c["tickets"])}
    pc = tk["primary_concern"].fillna("None").value_counts()
    out["primary_concern"] = [{"concern": k, "tickets": int(v), "share_pct": round(100 * v / n, 1)} for k, v in pc.items()]
    return out


# outcome each dimension should move with, checked on the text cues alone (behaviour excluded, so it isn't circular)
VALIDITY = {"impact": ("resolution_time_hours", "avg resolution hours"),
            "urgency": ("escalated", "escalation rate %"),
            "trust": ("repeat_number", "avg contacts on the same issue")}


def validity(tk) -> dict:
    """Behavioural check, not accuracy: there is no ground-truth label for these dimensions, so compare each
    dimension's text-only level with an outcome recorded independently in the ticket."""
    if not len(tk):
        return {}
    cache: dict[str, dict] = {}
    text_only = tk["ticket_text"].fillna("").map(lambda t: cache.setdefault(t, score_dimensions(t)))
    out = {}
    for key, (col, label) in VALIDITY.items():
        lv = text_only.map(lambda d, k=key: d[k]["level"])
        v = tk[col].astype(float) * (100 if col == "escalated" else 1)
        rows = [{"level": name, "tickets": int((lv == name).sum()),
                 "value": round(float(v[lv == name].mean()), 2) if (lv == name).any() else None}
                for _, name in reversed(LEVELS)]
        low, top = rows[0]["value"], next((r["value"] for r in reversed(rows) if r["value"] is not None), None)
        out[key] = {"label": DIMENSIONS[key], "metric": label, "by_level": rows,
                    "moves_with_outcome": None if low is None or top is None else bool(top > low)}
    out["note"] = ("Behavioural check, not accuracy: no ground truth exists for these dimensions. Each dimension's "
                   "text-only level is compared with an outcome recorded separately in the ticket.")
    return out


__all__ = ["DIMENSIONS", "FAMILIES", "score_dimensions", "flat", "level", "summarize", "validity"]
