"""RAG retrieval over the remediation knowledge base (markdown runbooks).

Dependency-free Okapi BM25 over section-level chunks, with a metadata boost
when the query's category / sub-cause matches the article. Swap for a vector
store (pgvector, Azure AI Search) behind the same `search()` signature.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

KB_DIR = Path(__file__).parent / "kb"
_TOKEN = re.compile(r"[a-z0-9]+(?:[-/][a-z0-9]+)*")
_STOP = {"the", "a", "an", "and", "or", "to", "of", "in", "on", "for", "is", "it", "with", "at", "by", "be",
         "my", "i", "this", "that", "from", "as", "are", "if", "via", "vs", "not"}


def tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN.findall((text or "").lower()) if t not in _STOP]


@dataclass
class Article:
    id: str
    title: str
    category: str
    subcause: str
    tags: str
    body: str
    sections: dict[str, str] = field(default_factory=dict)

    def as_dict(self, full: bool = False) -> dict:
        d = {"id": self.id, "title": self.title, "category": self.category, "subcause": self.subcause}
        if full:
            d["sections"] = self.sections
            d["markdown"] = self.body
        return d


def _parse(path: Path) -> Article:
    raw = path.read_text(encoding="utf-8")
    meta, body = {}, raw
    if raw.startswith("---"):
        _, fm, body = raw.split("---", 2)
        for line in fm.strip().splitlines():
            k, _, v = line.partition(":")
            meta[k.strip()] = v.strip()
    sections, current = {}, "Overview"
    for line in body.strip().splitlines():
        if line.startswith("## "):
            current = line[3:].strip()
            sections[current] = ""
        elif not line.startswith("# "):
            sections[current] = (sections.get(current, "") + "\n" + line).strip()
    return Article(meta["id"], meta["title"], meta.get("category", ""), meta.get("subcause", ""),
                   meta.get("tags", ""), body.strip(), sections)


class KnowledgeBase:
    k1, b = 1.5, 0.75

    def __init__(self, kb_dir: Path = KB_DIR):
        self.articles = {a.id: a for a in (_parse(p) for p in sorted(kb_dir.glob("*.md")))}
        self.chunks: list[tuple[str, str, str, list[str]]] = []  # (article_id, section, text, tokens)
        for a in self.articles.values():
            header = f"{a.title} {a.subcause} {a.category} {a.tags}"
            for sec, text in a.sections.items():
                self.chunks.append((a.id, sec, text, tokenize(f"{header} {text}")))
        self.df = Counter(t for *_, toks in self.chunks for t in set(toks))
        self.avgdl = sum(len(c[3]) for c in self.chunks) / max(1, len(self.chunks))
        self.tf = [Counter(c[3]) for c in self.chunks]

    def _bm25(self, q: list[str], i: int) -> float:
        n, dl, tf = len(self.chunks), len(self.chunks[i][3]), self.tf[i]
        s = 0.0
        for t in q:
            if t not in tf:
                continue
            idf = math.log(1 + (n - self.df[t] + 0.5) / (self.df[t] + 0.5))
            s += idf * tf[t] * (self.k1 + 1) / (tf[t] + self.k1 * (1 - self.b + self.b * dl / self.avgdl))
        return s

    def search(self, query: str, top_k: int = 3, category: str | None = None,
               subcause: str | None = None) -> list[dict]:
        q = tokenize(query)
        best: dict[str, dict] = {}
        for i, (aid, sec, text, _) in enumerate(self.chunks):
            s = self._bm25(q, i)
            a = self.articles[aid]
            if category and a.category == category:
                s *= 1.35
            if subcause and a.subcause.lower() == subcause.lower():
                s *= 1.8
            if s <= 0:
                continue
            if aid not in best or s > best[aid]["score"]:
                best[aid] = {**a.as_dict(), "score": round(s, 3), "section": sec, "snippet": text[:400]}
        ranked = sorted(best.values(), key=lambda d: d["score"], reverse=True)[:top_k]
        for r in ranked:
            a = self.articles[r["id"]]
            r["remediation"] = a.sections.get("Remediation", "")
        return ranked

    def get(self, article_id: str) -> Article | None:
        return self.articles.get(article_id)


@lru_cache
def get_kb() -> KnowledgeBase:
    return KnowledgeBase()
