"""Offline help: Markdown pages with a small header, searchable with synonyms and typo tolerance.

    from cad.help import library
    page = library().get("line")
    hits = library().search("copy in a circle")      # -> polar array first

Content lives in cad/help/content/ (commands/, concepts/, tutorials/, glossary.md, synonyms.json).
"""
from .pages import HelpLibrary, Page, library
from .search import SearchHit

__all__ = ["HelpLibrary", "Page", "library", "SearchHit"]
