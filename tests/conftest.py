import pytest

from labelprinter import fonts


@pytest.fixture(scope="session")
def _session_fonts(tmp_path_factory):
    """One registry for the whole run (scanning the Windows fonts folder takes a moment), with a throwaway
    folder for uploads, so no test can touch the real data/fonts folder."""
    return fonts.FontRegistry(fonts.SYSTEM_DIR, tmp_path_factory.mktemp("custom-fonts"), fonts.BUNDLED_DIR)


@pytest.fixture(autouse=True)
def isolated_fonts(monkeypatch, _session_fonts):
    monkeypatch.setattr(fonts, "default", _session_fonts)
    return _session_fonts
