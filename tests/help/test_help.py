import math

import pytest

from cad.commands import REGISTRY
from cad.help.pages import HelpLibrary
from cad.help.tutorial_runner import command_blocks, run_tutorial


@pytest.fixture(scope="module")
def lib():
    return HelpLibrary()


def test_pages_load_without_errors(lib):
    assert not lib.errors
    assert lib.get("home") and lib.get("glossary") and lib.get("commands")
    assert len(lib.terms) >= 60


def test_every_command_has_its_own_page(lib):
    missing, wrong = [], []
    for c in REGISTRY.all():
        p = lib.get(c.help_id)
        if p is None:
            missing.append(c.name)
        elif p.type != "command" or p.command != c.name:
            wrong.append((c.name, p.id, p.command))
    assert not missing, f"commands without a help page: {missing}"
    assert not wrong
    # and no orphan command pages for commands that don't exist
    names = {c.name for c in REGISTRY.all()}
    assert {p.command for p in lib.of_type("command")} <= names


def test_every_link_points_somewhere(lib):
    bad = [(p.id, s, t) for p in lib.pages.values() for s, t in p.links() if not lib.resolve(s, t)]
    assert not bad, bad


def test_every_page_is_reachable_from_home(lib):
    """Home links to concepts and tutorials; commands come from the command list, terms from the glossary."""
    seen, todo = set(), ["home", "commands", "glossary"]
    seen.update(f"term/{t.id.split('/', 1)[1]}" for t in lib.terms)
    seen.update(p.id for p in lib.of_type("command"))
    while todo:
        pid = todo.pop()
        if pid in seen and pid not in ("home", "commands", "glossary"):
            continue
        seen.add(pid)
        page = lib.get(pid)
        for s, t in page.links():
            if s == "help" and t.split("#")[0] not in seen:
                todo.append(t.split("#")[0])
    assert set(lib.pages) <= seen, set(lib.pages) - seen


def test_every_page_renders(lib):
    for p in lib.pages.values():
        md = lib.markdown(p)
        assert md.startswith(f"# {p.title}") and len(md) > 40
    md = lib.markdown(lib.get("line"))
    assert "`LINE`" in md and "`L`" in md and "run:LINE" in md and "Home tab" in md
    assert "Object snap" in md                           # glossary chips
    assert "LIVING" not in lib.glossary_markdown() and "## A" in lib.glossary_markdown()


@pytest.mark.parametrize("query,expected", [
    ("copy in a circle", "arraypolar"),
    ("polar aray", "arraypolar"),                         # typo
    ("make a wall thicker", "offset"),
    ("TR", "trim"),
    ("trimm", "trim"),
    ("print", "plot"),
    ("round corner", "fillet"),
    ("feet and inches", "units-and-typing"),
    ("delete", "erase"),
    ("dwg", "file-formats"),
    ("hatch not working", "troubleshooting"),
    ("osnap", "snaps"),
    ("viewport", "mview"),
    ("what is a fillet", "fillet"),
    ("bolt hole pattern", "arraypolar"),
    ("lock a size", "dclinear"),
    ("save as pdf", "exportpdf"),
    ("zom extents", "zoomextents"),
])
def test_search_finds_the_right_page(lib, query, expected):
    hits = [h.page_id for h in lib.search(query, 5)]
    assert expected in hits[:3], (query, hits)


def test_search_edge_cases(lib):
    assert lib.search("") == []
    assert lib.search("qwxzv") == [] or lib.search("qwxzv")[0].score < 100
    assert lib.search("L")[0].page_id == "line"


def test_floor_plan_tutorial_runs(lib):
    from cad.core.model import Arc, Dimension, Hatch, Text
    from cad.core.units import UnitMode
    page = lib.get("tutorial-floor-plan")
    assert len(command_blocks(page.body)) >= 9
    doc, msgs = run_tutorial(page.body)
    assert doc.header.units.mode is UnitMode.ARCHITECTURAL
    dims = sorted(round(d.measurement() / 304.8, 6) for d in doc.entities.values() if isinstance(d, Dimension))
    assert dims == [16, 26]                               # 24' stretched to 26'
    assert {t.text for t in doc.entities.values() if isinstance(t, Text)} == {"LIVING ROOM", "KITCHEN"}
    h = next(e for e in doc.entities.values() if isinstance(e, Hatch))
    assert h.sources and h.pattern == "ANSI31"
    wall_area = (26 * 16 - 25 * 15) * 304.8 ** 2
    assert h.area() == pytest.approx(wall_area, rel=1e-3)
    assert any(isinstance(e, Arc) and e.layer == "Doors" for e in doc.entities.values())
    assert "A-101" in doc.layouts


def test_machined_part_tutorial_runs(lib):
    from cad.core.model import ArrayEntity, Circle, Dimension, Polyline
    doc, msgs = run_tutorial(lib.get("tutorial-machined-part").body)
    plate = next(e for e in doc.entities.values() if isinstance(e, Polyline))
    assert plate.closed and sum(1 for v in plate.vertices if abs(v[2]) > 1e-9) == 4
    (c,) = [e for e in doc.entities.values() if isinstance(e, Circle)]
    assert c.radius == pytest.approx(7)
    arr = next(e for e in doc.entities.values() if isinstance(e, ArrayEntity))
    assert len(doc.geometry(arr).centers) == 2
    dia = next(d for d in doc.entities.values() if isinstance(d, Dimension) and d.dimtype == "diameter")
    assert dia.measurement() == pytest.approx(14)
    ords = sorted(d.measurement() for d in doc.entities.values() if isinstance(d, Dimension) and d.dimtype == "ordinate")
    assert ords == [20, 50, 80]
    assert "dia1" in {k.name for k in doc.constraints.values()}


def test_machined_part_tutorial_goes_3d(lib):
    import math
    from cad.commands.drawing_views import view_settings
    from cad.core import solids as S
    from cad.core.model import BlockReference, Solid
    doc, msgs = run_tutorial(lib.get("tutorial-machined-part").body)
    (part,) = [e for e in doc.entities.values() if isinstance(e, Solid)]
    plate = (100 * 60 - (4 - math.pi) * 10 ** 2) * 10
    holes = 3 * math.pi * 7 ** 2 * 10
    pocket = 30 * 10 * 4
    assert S.mass_properties(part.shape)["volume"] == pytest.approx(plate - holes - pocket, rel=1e-6)
    assert len(S.faces(part.shape)) == 18            # true round holes and fillets, not facets
    assert any("volume" in m for m in msgs)
    views = sorted(view_settings(doc.blocks[e.name])["view"] for e in doc.entities.values()
                   if isinstance(e, BlockReference) and e.name in doc.blocks and view_settings(doc.blocks[e.name]))
    assert views == ["Front", "SE Iso", "Top"]
