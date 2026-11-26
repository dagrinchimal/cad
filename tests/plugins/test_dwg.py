import os
import shutil
import stat
import sys
import textwrap

import pytest

from cad.core.model import Circle, Line
from cad.plugins import PluginError, Report, registry
from cad.plugins.formats import dwg
from cad.samples import rich_document

FAKE = textwrap.dedent("""
    import os, shutil, sys
    src, dst, version, out_type, recurse, audit, flt = sys.argv[1:8]
    for f in os.listdir(src):
        if f != flt:
            continue
        stem = os.path.splitext(f)[0]
        if "FAIL" in f:
            open(os.path.join(dst, stem + ".err"), "w").write("bad file " + version)
            continue
        shutil.copy(os.path.join(src, f), os.path.join(dst, stem + "." + out_type.lower()))
""")


@pytest.fixture
def fake_converter(tmp_path, monkeypatch):
    """Stands in for ODAFileConverter: 'converts' by copying (the DXF text is valid for our reader)."""
    script = tmp_path / "fake_oda.py"
    script.write_text(FAKE)
    if sys.platform == "win32":
        exe = tmp_path / "ODAFileConverter.cmd"
        exe.write_text(f'@"{sys.executable}" "{script}" %*\n')
    else:
        exe = tmp_path / "ODAFileConverter"
        exe.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{script}" "$@"\n')
        exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("CAD_ODA_CONVERTER", str(exe))
    return str(exe)


def test_missing_converter_explains_what_to_do(monkeypatch):
    monkeypatch.delenv("CAD_ODA_CONVERTER", raising=False)
    monkeypatch.setattr(dwg, "find_converter", lambda configured=None: None)
    p = registry.get("dwg")
    ok, why = p.available()
    assert not ok and "ODA File Converter" in why and "DXF works" in why
    with pytest.raises(PluginError, match="ODA"):
        p.export(rich_document(), "x.dwg", {}, Report())


def test_dwg_round_trip_through_the_converter(fake_converter, tmp_path):
    p = registry.get("dwg")
    assert p.available()[0]
    doc = rich_document()
    out = tmp_path / "plan.dwg"
    r = Report()
    p.export(doc, str(out), {"version": "R2013"}, r)
    assert out.is_file() and any("DWG R2013" in i for i in r.infos)
    back = p.import_(str(out), {}, Report())
    assert len([e for e in back.entities.values() if isinstance(e, Circle)]) == 3
    assert len([e for e in back.entities.values() if isinstance(e, Line)]) >= 7


def test_converter_failure_is_reported(fake_converter, tmp_path):
    src = tmp_path / "FAIL.dwg"
    src.write_text("x")
    with pytest.raises(PluginError, match="couldn't convert"):
        registry.get("dwg").import_(str(src), {}, Report())


@pytest.mark.skipif(not dwg.find_converter(), reason="ODA File Converter not installed")
def test_real_oda_converter_round_trip(tmp_path):
    p = registry.get("dwg")
    out = tmp_path / "real.dwg"
    p.export(rich_document(), str(out), {}, Report())
    assert out.read_bytes()[:4] == b"AC10"                # a real DWG header
    back = p.import_(str(out), {}, Report())
    assert len([e for e in back.entities.values() if isinstance(e, Circle)]) == 3


def test_example_plugin_from_the_docs_works(tmp_path):
    """The example in docs/PLUGINS.md must keep working."""
    import re
    from pathlib import Path
    from cad.plugins.registry import PluginRegistry
    text = (Path(__file__).parents[2] / "docs" / "PLUGINS.md").read_text(encoding="utf-8")
    code = re.search(r"```python\n(.*?)```", text, re.S).group(1)
    folder = tmp_path / "plugins"
    folder.mkdir()
    (folder / "points_csv.py").write_text(code, encoding="utf-8")
    (folder / "broken.py").write_text("raise RuntimeError('oops')\n")
    reg = PluginRegistry()
    assert reg.load_folder(folder) == ["points_csv"]
    assert any("broken.py" in e for e in reg.load_errors)
    p = reg.get("points_csv")
    from cad.core.model import Circle, Document, Line
    doc = Document()
    with doc.transaction("s"):
        doc.add(Line(p1=(0, 0), p2=(10, 5)))
        doc.add(Circle(center=(3, 4), radius=1))
    out = tmp_path / "p.csv"
    p.export(doc, str(out), {"decimals": 1}, Report())
    lines = out.read_text().splitlines()
    assert lines[0] == "x_mm,y_mm"
    assert [tuple(map(float, ln.split(","))) for ln in lines[1:]] == [(0, 0), (10, 5), (3, 4)]
    back = p.import_(str(out), {}, Report())
    assert len(back.entities) == 3
    assert p.losses(doc)                      # lines and circles aren't kept as such
