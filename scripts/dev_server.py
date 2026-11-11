"""Run the app against a fake DealPOS (no network, no keys) for UI work and the smoke test.

  uv run python scripts/dev_server.py            # http://127.0.0.1:8795, password: devpassword
"""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import uvicorn  # noqa: E402

from labelprinter import fonts  # noqa: E402
from labelprinter.catalog import Catalog  # noqa: E402
from labelprinter.designs import DesignStore  # noqa: E402
from labelprinter.server import create_app  # noqa: E402
from tests.fakes import FakeClient  # noqa: E402

PASSWORD = "devpassword"

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8795
    store = DesignStore(Path(tempfile.mkdtemp(prefix="lp-designs-")))  # throwaway: dev runs never touch data/designs
    fonts.default = fonts.FontRegistry(fonts.SYSTEM_DIR, Path(tempfile.mkdtemp(prefix="lp-fonts-")), fonts.BUNDLED_DIR)  # nor data/fonts
    uvicorn.run(create_app(Catalog(FakeClient()), PASSWORD, b"d" * 32, store), host="127.0.0.1", port=port, log_level="warning")
