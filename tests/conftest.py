import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

# Keep tests away from the real user profile and make GUI tests headless by default.
os.environ.setdefault("CAD_DATA_DIR", tempfile.mkdtemp(prefix="cad-test-data-"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("CAD_RENDERER", "painter")
os.environ.setdefault("CAD_NO_REPORT_DIALOGS", "1")     # import/export reports go to the command line only
