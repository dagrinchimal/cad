"""Loading help pages and building the text a help viewer shows."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

CONTENT = Path(__file__).parent / "content"
LINK_RE = re.compile(r"\[([^\]]+)\]\(([a-z]+):([^)\s]+)\)")

# ribbon tab (or menu) for each command group, for the "Where" line of command pages
GROUP_PLACE = {
    "Draw": "Home tab › Draw", "Modify": "Home tab › Modify", "Layers": "Home tab › Layers",
    "Block": "Home tab › Block", "Groups": "Home tab › Block", "Utilities": "Home tab › Utilities",
    "Annotation": "Annotate tab", "Parametric": "Parametric tab", "Layout": "Layout tab",
    "Output": "Output tab", "View": "View tab", "Application": "File menu (top left)",
    "Edit": "Quick access: Ctrl+Z / Ctrl+Y", "3D": "3D tab",
}


@dataclass
class Page:
    id: str
    type: str                     # home | command | concept | tutorial | glossary | term
    title: str
    body: str
    command: str = ""             # for command pages: the command name (LINE)
    synonyms: list[str] = field(default_factory=list)
    related: list[str] = field(default_factory=list)
    glossary: list[str] = field(default_factory=list)
    order: int = 100
    summary: str = ""

    def links(self) -> list[tuple[str, str]]:
        """(scheme, target) of every link in the body and header."""
        out = [(m.group(2), m.group(3)) for m in LINK_RE.finditer(self.body)]
        out += [("help", r) for r in self.related]
        out += [("term", g) for g in self.glossary]
        return out


def parse_page(text: str, source: str = "") -> Page:
    if not text.startswith("---"):
        raise ValueError(f"{source}: missing header")
    _, head, body = text.split("---", 2)
    meta: dict = {}
    for line in head.strip().splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key, _, val = line.partition(":")
        val = val.strip()
        if val.startswith("[") and val.endswith("]"):
            meta[key.strip()] = [v.strip() for v in val[1:-1].split(",") if v.strip()]
        else:
            meta[key.strip()] = val
    for k in ("id", "type", "title"):
        if not meta.get(k):
            raise ValueError(f"{source}: header needs '{k}'")
    body = body.strip("\n")
    first = next((ln for ln in body.splitlines() if ln.strip() and not ln.startswith("#")), "")
    return Page(id=meta["id"], type=meta["type"], title=meta["title"], body=body, command=meta.get("command", ""),
                synonyms=list(meta.get("synonyms", [])), related=list(meta.get("related", [])),
                glossary=list(meta.get("glossary", [])), order=int(meta.get("order", 100)),
                summary=meta.get("summary", "") or _plain(first)[:200])


def _plain(md: str) -> str:
    md = LINK_RE.sub(lambda m: m.group(1), md)
    return re.sub(r"[*`_>#]", "", md).strip()


def slug(term: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", term.lower()).strip("-")


def parse_glossary(text: str) -> list[Page]:
    """glossary.md: '### Term' headings, an optional 'Also:' line of synonyms, then the definition."""
    out: list[Page] = []
    for block in re.split(r"^### ", text, flags=re.M)[1:]:
        head, _, rest = block.partition("\n")
        term = head.strip()
        syn: list[str] = []
        lines = rest.strip().splitlines()
        if lines and lines[0].lower().startswith("also:"):
            syn = [s.strip() for s in lines[0][5:].split(",") if s.strip()]
            lines = lines[1:]
        body = "\n".join(lines).strip()
        out.append(Page(id=f"term/{slug(term)}", type="term", title=term, body=body, synonyms=syn,
                        summary=_plain(body.split("\n")[0])[:200]))
    return out


class HelpLibrary:
    def __init__(self, root: Path = CONTENT) -> None:
        self.root = root
        self.pages: dict[str, Page] = {}
        self.errors: list[str] = []
        for sub in ("", "commands", "concepts", "tutorials"):
            for path in sorted((root / sub).glob("*.md")):
                if sub == "" and path.name == "glossary.md":
                    continue
                try:
                    p = parse_page(path.read_text(encoding="utf-8"), str(path))
                except ValueError as exc:
                    self.errors.append(str(exc))
                    continue
                if p.id in self.pages:
                    self.errors.append(f"{path}: duplicate id {p.id}")
                self.pages[p.id] = p
        gpath = root / "glossary.md"
        self.terms: list[Page] = parse_glossary(gpath.read_text(encoding="utf-8")) if gpath.is_file() else []
        for t in self.terms:
            self.pages[t.id] = t
        spath = root / "synonyms.json"
        self.synonyms: dict[str, list[str]] = json.loads(spath.read_text(encoding="utf-8")) if spath.is_file() else {}
        self._index = None

    # -------------------------------------------------------------- lookup
    def get(self, page_id: str) -> Page | None:
        if page_id.startswith("term/") or page_id in self.pages:
            return self.pages.get(page_id)
        return self.pages.get(page_id.lower())

    def term(self, name: str) -> Page | None:
        return self.pages.get(f"term/{slug(name)}")

    def for_command(self, name: str) -> Page | None:
        from ..commands import REGISTRY
        c = REGISTRY.get(name)
        return self.get(c.help_id) if c else None

    def hints_for(self, target: str):
        """Polylines of hint link 'page-id/block' (None if there's no such block)."""
        from .hints import block_hints
        pid, _, idx = target.partition("/")
        page = self.get(pid)
        if page is None or not idx.isdigit():
            return None
        blocks = block_hints(page.body)
        i = int(idx)
        return blocks[i] if i < len(blocks) else None

    def of_type(self, kind: str) -> list[Page]:
        return sorted((p for p in self.pages.values() if p.type == kind), key=lambda p: (p.order, p.title.lower()))

    def search(self, text: str, limit: int = 20):
        from .search import SearchIndex
        if self._index is None:
            self._index = SearchIndex(self)
        return self._index.search(text, limit)

    def resolve(self, scheme: str, target: str) -> bool:
        """Does a link point somewhere real?"""
        from ..commands import REGISTRY
        if scheme == "help":
            return self.get(target.split("#")[0]) is not None
        if scheme == "term":
            return self.term(target) is not None or self.get(f"term/{target}") is not None
        if scheme == "run":
            return REGISTRY.get(target) is not None
        if scheme == "hint":
            return target == "clear" or self.hints_for(target) is not None
        if scheme in ("http", "https"):
            return True
        return False

    # -------------------------------------------------------------- display
    def markdown(self, page: Page) -> str:
        """The Markdown a viewer shows: title, the command's facts, body, glossary and related links."""
        out = [f"# {page.title}", ""]
        if page.type == "command" and page.command:
            from ..commands import REGISTRY
            c = REGISTRY.get(page.command)
            if c is not None:
                facts = [f"**Type:** `{c.name}`"]
                if c.aliases:
                    facts.append("**or:** " + ", ".join(f"`{a}`" for a in c.aliases))
                if c.shortcut:
                    facts.append(f"**Keys:** {c.shortcut}")
                place = GROUP_PLACE.get(c.group)
                if place:
                    facts.append(f"**Where:** {place}")
                out += [" · ".join(facts), "", f"[▶ Start {c.label}](run:{c.name})", ""]
        if page.type == "term":
            out += [page.body, ""]
            if page.synonyms:
                out += ["Also called: " + ", ".join(page.synonyms), ""]
            out += ["[All glossary terms](help:glossary)"]
            return "\n".join(out)
        if page.type == "tutorial":
            from .hints import display_markdown
            out.append(display_markdown(page.id, page.body))
        else:
            out.append(page.body)
        if page.glossary:
            items = []
            for g in page.glossary:
                t = self.term(g) or self.get(f"term/{g}")
                if t:
                    items.append(f"[{t.title}](term:{slug(t.title)})")
            if items:
                out += ["", "**Words used here:** " + ", ".join(items)]
        if page.related:
            items = []
            for r in page.related:
                p = self.get(r)
                if p:
                    items.append(f"[{p.title}](help:{p.id})")
            if items:
                out += ["", "**See also:** " + " · ".join(items)]
        return "\n".join(out)

    def glossary_markdown(self) -> str:
        lines = ["# Glossary", "", "Words you'll meet in CAD, in plain English. Click a word for its page.", ""]
        letter = ""
        for t in sorted(self.terms, key=lambda t: t.title.lower()):
            if t.title[0].upper() != letter:
                letter = t.title[0].upper()
                lines += ["", f"## {letter}", ""]
            lines.append(f"- [{t.title}](term:{slug(t.title)}) — {t.summary}")
        return "\n".join(lines)


@lru_cache(maxsize=1)
def library() -> HelpLibrary:
    return HelpLibrary()
