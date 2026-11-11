import sys
from pathlib import Path

import pymupdf
import pytest

from labelprinter.catalog import Catalog
from tests.fakes import FakeClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from labels_cli import build  # noqa: E402


async def test_build_writes_pdf_and_excel_and_reports_gaps(tmp_path):
    result = await build(["AMEAMET158", "NOUPASC002", "nope"], Catalog(FakeClient()), tmp_path, copies=2, stem="t")
    assert result["labels"] == 2 and result["missing"] == ["nope"]
    assert result["flagged"] == ["NOUPASC002"]               # no year or genre in its Description
    assert len(pymupdf.open(result["pdf"])) == 4              # 2 rows x 2 copies
    assert result["xlsx"].exists() and result["pdf"].name == "t.pdf"


async def test_build_with_no_match_exits_with_a_message(tmp_path):
    with pytest.raises(SystemExit, match="nope"):
        await build(["nope"], Catalog(FakeClient()), tmp_path)
