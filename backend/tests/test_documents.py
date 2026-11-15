import tempfile
import unittest
from pathlib import Path

from backend.app.documents import (
    DOCX_MIME,
    DocumentArtifact,
    _validate_docx_spec,
    _validate_formula,
    _validate_xlsx_spec,
    save_artifact,
)


class OfficeSpecificationTests(unittest.TestCase):
    def test_docx_spec_preserves_text_and_accepts_layout_and_styles(self) -> None:
        text = "  Türkçe başlık\r\nve devamı 😀  "
        title, blocks, page = _validate_docx_spec(
            {
                "title": "Örnek",
                "page": {"orientation": "landscape", "margins_inches": {"left": 0.5}},
                "blocks": [
                    {"type": "heading", "level": 2, "text": text, "bold": True},
                    {"type": "list", "ordered": True, "items": ["bir", "iki"]},
                    {"type": "table", "rows": [["A", "B"], ["1", "2"]]},
                ],
            }
        )
        self.assertEqual(title, "Örnek")
        self.assertEqual(blocks[0]["text"], text)
        self.assertEqual(page["orientation"], "landscape")
        self.assertEqual(page["margins_inches"]["left"], 0.5)

    def test_docx_rejects_unsupported_and_malformed_values(self) -> None:
        with self.assertRaisesRegex(ValueError, "desteklenmeyen alan"):
            _validate_docx_spec({"blocks": [], "shell": "ignored"})
        with self.assertRaisesRegex(ValueError, "sütun sayısı aynı"):
            _validate_docx_spec({"blocks": [{"type": "table", "rows": [["a", "b"], ["c"]]}]})
        with self.assertRaisesRegex(ValueError, "1–6"):
            _validate_docx_spec({"blocks": [{"type": "heading", "level": 7, "text": "x"}]})

    def test_xlsx_validates_sheets_formulas_charts_and_dimensions(self) -> None:
        title, sheets = _validate_xlsx_spec(
            {
                "title": "Satışlar",
                "sheets": [
                    {
                        "name": "Özet",
                        "cells": {
                            "A1": {"value": "Ay", "style": {"bold": True, "fill_color": "AABBCC"}},
                            "B1": "Tutar",
                            "A2": "Ocak",
                            "B2": 12.5,
                            "B3": {"formula": "=SUM(B2:B2)"},
                        },
                        "tables": [{"name": "SatisTablosu", "ref": "A1:B3"}],
                        "charts": [{"type": "bar", "data": "B1:B3", "categories": "A2:A3", "title": "Aylık"}],
                        "column_widths": {"A": 18},
                        "row_heights": {"1": 24},
                    }
                ],
            }
        )
        self.assertEqual(title, "Satışlar")
        self.assertEqual(sheets[0]["cells"]["B3"]["value"], "=SUM(B2:B2)")
        self.assertEqual(sheets[0]["row_heights"]["1"], 24.0)

    def test_xlsx_rejects_external_or_unapproved_formulas_and_bad_coordinates(self) -> None:
        for formula in (
            "=HYPERLINK(\"https://example.invalid\",\"x\")",
            "=[other.xlsx]Sheet1!A1",
            "=WEBSERVICE(1)",
        ):
            with self.subTest(formula=formula), self.assertRaises(ValueError):
                _validate_formula(formula)
        with self.assertRaisesRegex(ValueError, "sınırlarını"):
            _validate_xlsx_spec({"sheets": [{"name": "S", "cells": {"XFE1": 1}}]})
        with self.assertRaisesRegex(ValueError, "yinelenmiş"):
            _validate_xlsx_spec({"sheets": [{"name": "S", "cells": {}}, {"name": "s", "cells": {}}]})

    def test_saving_requires_explicit_approval_and_correct_extension(self) -> None:
        artifact = DocumentArtifact("Örnek.docx", DOCX_MIME, b"placeholder", {"format": "DOCX"})
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with self.assertRaisesRegex(PermissionError, "Kullanıcı onayı"):
                save_artifact(root, "out.docx", artifact, approved=False)
            with self.assertRaisesRegex(ValueError, "uzantısı"):
                save_artifact(root, "out.xlsx", artifact, approved=True)
            self.assertFalse((root / "out.docx").exists())


if __name__ == "__main__":
    unittest.main()
