"""Architecture rules from docs/ARCHITECTURE.md, enforced."""
import subprocess
import sys


def test_core_commands_and_io_never_import_qt():
    code = (
        "import sys, cad.core.model, cad.core.snaps, cad.core.spatial, cad.core.units, "
        "cad.commands, cad.io.native; "
        "bad = [m for m in sys.modules if m.startswith(('PySide6', 'shiboken6', 'moderngl'))]; "
        "print(bad); sys.exit(1 if bad else 0)"
    )
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
