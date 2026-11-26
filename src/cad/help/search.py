"""Help search: names, aliases, titles, synonyms, everyday phrases and body text, typo tolerant."""
from __future__ import annotations

import re
from dataclasses import dataclass

from rapidfuzz import fuzz, process

WORD = re.compile(r"[a-z0-9]+")
STOP = {"a", "an", "the", "to", "of", "in", "on", "and", "or", "how", "do", "i", "is", "it", "my", "for", "with",
        "what", "can", "make", "use", "using", "draw", "get", "into", "from", "by", "at", "you", "your", "this",
        "that", "be", "as", "are", "does", "want", "need"}


def stem(w: str) -> str:
    for suf in ("ings", "ing", "ies", "es", "ed", "s"):
        if len(w) > len(suf) + 2 and w.endswith(suf):
            return w[: -len(suf)] + ("y" if suf == "ies" else "")
    return w


def words(text: str) -> list[str]:
    return [stem(w) for w in WORD.findall(text.lower()) if w not in STOP]


@dataclass(frozen=True)
class SearchHit:
    page_id: str
    title: str
    type: str
    score: float
    summary: str


class SearchIndex:
    def __init__(self, lib) -> None:
        from ..commands import REGISTRY
        self.lib = lib
        self.entries = []
        for p in lib.pages.values():
            names: list[str] = []
            extra: list[str] = list(p.synonyms)
            if p.type == "command" and p.command:
                c = REGISTRY.get(p.command)
                if c is not None:
                    names = [c.name.lower()] + [a.lower() for a in c.aliases]
                    extra += list(c.keywords) + [c.label]
            vocab = set(words(p.title + " " + " ".join(extra) + " " + p.body))
            title_vocab = set(words(p.title + " " + " ".join(extra)))
            self.entries.append((p, names, [p.title.lower()] + [s.lower() for s in extra], vocab, title_vocab))
        self.phrases = {k.lower(): v for k, v in lib.synonyms.items()}
        self.phrase_words = {k: set(words(k)) for k in self.phrases}

    def search(self, text: str, limit: int = 20) -> list[SearchHit]:
        q = text.strip().lower()
        if not q:
            return []
        qwords = words(q) or [w for w in WORD.findall(q)]
        boost: dict[str, float] = {}
        qset = set(qwords)
        for phrase, pwords in self.phrase_words.items():
            # the whole phrase is in the query, or the query is a close (typo) version of the phrase
            score = 100.0 if pwords and pwords <= qset else fuzz.token_sort_ratio(q, phrase)
            if score >= 85:
                for i, pid in enumerate(self.phrases[phrase]):
                    boost[pid] = max(boost.get(pid, 0), 150 - i * 5 + (score - 85))
        hits = []
        for p, names, labels, vocab, title_vocab in self.entries:
            s = 0.0
            if q in names:
                s = 300.0                                    # exact command name or alias
            elif any(n.startswith(q) for n in names) and len(q) >= 2:
                s = 160.0
            label_score = max((fuzz.WRatio(q, lab) for lab in labels), default=0)
            s = max(s, label_score * (1.25 if p.type == "command" else 1.15))
            if qwords:
                found = 0.0
                for w in qwords:
                    if w in vocab:
                        found += 1
                    else:
                        m = process.extractOne(w, vocab, scorer=fuzz.ratio, score_cutoff=82) if len(w) > 3 else None
                        if m:
                            found += 0.8
                in_title = sum(1 for w in qwords if w in title_vocab) / len(qwords)
                s = max(s, 95 * found / len(qwords) + 20 * in_title + (5 if p.type == "command" else 0))
            s = max(s, boost.get(p.id, 0))
            if p.type == "term":
                s *= 0.9                                     # commands and concepts first
            if s >= 60:
                hits.append(SearchHit(p.id, p.title, p.type, s, p.summary))
        hits.sort(key=lambda h: (-h.score, h.title))
        return hits[:limit]
