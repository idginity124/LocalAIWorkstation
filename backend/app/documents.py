"""Generate and validate real Office Open XML artifacts without implicit writes."""

from __future__ import annotations

from dataclasses import dataclass
import io
import re
from pathlib import Path
from typing import Any

from .filesystem import atomic_write


MAX_BLOCKS = 2_000
MAX_TEXT_CHARS = 100_000
MAX_SHEETS = 100
MAX_CELLS = 200_000
FORMULA_FUNCTIONS = {
    "SUM", "AVERAGE", "COUNT", "COUNTA", "MIN", "MAX", "IF", "AND", "OR",
    "ROUND", "ABS", "LEN", "LEFT", "RIGHT", "MID", "CONCAT", "CONCATENATE",
    "VLOOKUP", "HLOOKUP", "XLOOKUP", "INDEX", "MATCH", "SUMIF", "COUNTIF",
}

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@dataclass(frozen=True)
class DocumentArtifact:
    filename: str
    mime_type: str
    content: bytes
    preview: dict[str, Any]


def _mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} nesne olmalı.")
    return value


def _reject_extra(value: dict[str, Any], allowed: set[str], label: str) -> None:
    extra = set(value) - allowed
    if extra:
        raise ValueError(f"{label} desteklenmeyen alan içeriyor: {', '.join(sorted(extra))}.")


def _text(value: Any, label: str, limit: int = MAX_TEXT_CHARS) -> str:
    if not isinstance(value, str) or len(value) > limit:
        raise ValueError(f"{label} metin olmalı ve {limit} karakteri aşmamalı.")
    if "\x00" in value:
        raise ValueError(f"{label} NUL karakteri içeremez.")
    return value


def _color(value: Any, label: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9A-Fa-f]{6}", value) is None:
        raise ValueError(f"{label} altı basamaklı RGB hex olmalı.")
    return value.upper()


def _validate_docx_spec(spec: Any) -> tuple[str, list[dict[str, Any]], dict[str, Any]]:
    root = _mapping(spec, "DOCX")
    _reject_extra(root, {"title", "blocks", "page"}, "DOCX")
    title = _text(root.get("title", "Belge"), "Belge başlığı", 200)
    raw_blocks = root.get("blocks")
    if not isinstance(raw_blocks, list) or len(raw_blocks) > MAX_BLOCKS:
        raise ValueError("DOCX blocks listesi gerekli ve en fazla 2000 öğe içerebilir.")
    blocks: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_blocks):
        block = _mapping(raw, f"blocks[{index}]")
        kind = block.get("type")
        if kind in {"paragraph", "heading"}:
            allowed = {"type", "text", "bold", "italic", "underline", "font_size", "color", "alignment"}
            if kind == "heading":
                allowed.add("level")
            _reject_extra(block, allowed, f"blocks[{index}]")
            text = _text(block.get("text"), f"blocks[{index}].text")
            normalized: dict[str, Any] = {"type": kind, "text": text}
            if kind == "heading":
                level = block.get("level", 1)
                if not isinstance(level, int) or isinstance(level, bool) or level not in range(1, 7):
                    raise ValueError("Başlık düzeyi 1–6 arasında olmalı.")
                normalized["level"] = level
            for style in ("bold", "italic", "underline"):
                if style in block and not isinstance(block[style], bool):
                    raise ValueError(f"{style} mantıksal değer olmalı.")
                normalized[style] = block.get(style, False)
            if "font_size" in block:
                size = block["font_size"]
                if not isinstance(size, (int, float)) or isinstance(size, bool) or not 6 <= size <= 72:
                    raise ValueError("Yazı boyutu 6–72 punto aralığında olmalı.")
                normalized["font_size"] = float(size)
            if "color" in block:
                normalized["color"] = _color(block["color"], "Yazı rengi")
            if "alignment" in block:
                alignment = block["alignment"]
                if alignment not in {"left", "center", "right", "justify"}:
                    raise ValueError("Paragraf hizası geçersiz.")
                normalized["alignment"] = alignment
            blocks.append(normalized)
        elif kind == "list":
            _reject_extra(block, {"type", "items", "ordered"}, f"blocks[{index}]")
            items = block.get("items")
            if not isinstance(items, list) or not items or len(items) > 1_000:
                raise ValueError("Liste en az bir, en fazla 1000 öğe içermeli.")
            normalized_items = [_text(item, f"blocks[{index}].items") for item in items]
            ordered = block.get("ordered", False)
            if not isinstance(ordered, bool):
                raise ValueError("ordered mantıksal değer olmalı.")
            blocks.append({"type": "list", "items": normalized_items, "ordered": ordered})
        elif kind == "table":
            _reject_extra(block, {"type", "rows", "header"}, f"blocks[{index}]")
            rows = block.get("rows")
            if not isinstance(rows, list) or not rows or len(rows) > 500:
                raise ValueError("Tablo 1–500 satır içermeli.")
            if any(not isinstance(row, list) or not row or len(row) > 50 for row in rows):
                raise ValueError("Her tablo satırında 1–50 hücre olmalı.")
            width = len(rows[0])
            if any(len(row) != width for row in rows):
                raise ValueError("Tablo satırlarının sütun sayısı aynı olmalı.")
            clean_rows = [[_text(cell, "Tablo hücresi") for cell in row] for row in rows]
            header = block.get("header", True)
            if not isinstance(header, bool):
                raise ValueError("Tablo header alanı mantıksal değer olmalı.")
            blocks.append({"type": "table", "rows": clean_rows, "header": header})
        else:
            raise ValueError(f"blocks[{index}].type desteklenmiyor.")

    page = _mapping(root.get("page", {}), "page")
    _reject_extra(page, {"orientation", "margins_inches"}, "page")
    orientation = page.get("orientation", "portrait")
    if orientation not in {"portrait", "landscape"}:
        raise ValueError("Sayfa yönü portrait veya landscape olmalı.")
    margins = page.get("margins_inches", {})
    margins = _mapping(margins, "page.margins_inches")
    _reject_extra(margins, {"top", "bottom", "left", "right"}, "page.margins_inches")
    clean_margins: dict[str, float] = {}
    for side in ("top", "bottom", "left", "right"):
        value = margins.get(side, 1.0)
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not 0.25 <= value <= 2.0:
            raise ValueError("Kenar boşlukları 0.25–2.0 inç aralığında olmalı.")
        clean_margins[side] = float(value)
    return title, blocks, {"orientation": orientation, "margins_inches": clean_margins}


def _docx_preview(title: str, blocks: list[dict[str, Any]]) -> dict[str, Any]:
    preview_blocks = []
    for block in blocks:
        if block["type"] == "table":
            preview_blocks.append({"type": "table", "rows": block["rows"], "header": block["header"]})
        elif block["type"] == "list":
            preview_blocks.append({"type": "list", "items": block["items"], "ordered": block["ordered"]})
        else:
            preview_blocks.append({key: value for key, value in block.items() if key != "type"} | {"type": block["type"]})
    return {"format": "DOCX", "title": title, "blocks": preview_blocks}


def build_docx(spec: Any) -> DocumentArtifact:
    title, blocks, page = _validate_docx_spec(spec)
    try:
        from docx import Document
        from docx.enum.section import WD_ORIENT
        from docx.enum.text import WD_ALIGN_PARAGRAPH
        from docx.shared import Inches, Pt, RGBColor
    except ImportError as error:
        raise RuntimeError("DOCX için python-docx bağımlılığı kurulu değil.") from error

    document = Document()
    document.add_heading(title, level=0)
    section = document.sections[0]
    section.orientation = WD_ORIENT.LANDSCAPE if page["orientation"] == "landscape" else WD_ORIENT.PORTRAIT
    if page["orientation"] == "landscape":
        section.page_width, section.page_height = section.page_height, section.page_width
    for side, value in page["margins_inches"].items():
        setattr(section, f"{side}_margin", Inches(value))

    alignment_map = {
        "left": WD_ALIGN_PARAGRAPH.LEFT,
        "center": WD_ALIGN_PARAGRAPH.CENTER,
        "right": WD_ALIGN_PARAGRAPH.RIGHT,
        "justify": WD_ALIGN_PARAGRAPH.JUSTIFY,
    }
    for block in blocks:
        kind = block["type"]
        if kind == "heading":
            paragraph = document.add_heading(block["text"], level=block["level"])
            run = paragraph.runs[0] if paragraph.runs else paragraph.add_run("")
        elif kind == "paragraph":
            paragraph = document.add_paragraph()
            run = paragraph.add_run(block["text"])
        elif kind == "list":
            style = "List Number" if block["ordered"] else "List Bullet"
            for item in block["items"]:
                document.add_paragraph(item, style=style)
            continue
        else:
            table = document.add_table(rows=0, cols=len(block["rows"][0]))
            table.style = "Table Grid"
            for row_index, values in enumerate(block["rows"]):
                cells = table.add_row().cells
                for cell_index, value in enumerate(values):
                    cells[cell_index].text = value
                    if row_index == 0 and block["header"]:
                        for cell_run in cells[cell_index].paragraphs[0].runs:
                            cell_run.bold = True
            continue
        run.bold = block["bold"]
        run.italic = block["italic"]
        run.underline = block["underline"]
        if "font_size" in block:
            run.font.size = Pt(block["font_size"])
        if "color" in block:
            color = block["color"]
            run.font.color.rgb = RGBColor(*(int(color[i:i + 2], 16) for i in (0, 2, 4)))
        if "alignment" in block:
            paragraph.alignment = alignment_map[block["alignment"]]

    output = io.BytesIO()
    document.save(output)
    content = output.getvalue()
    validate_docx(content)
    return DocumentArtifact(f"{_filename(title)}.docx", DOCX_MIME, content, _docx_preview(title, blocks))


def validate_docx(content: bytes) -> None:
    try:
        from docx import Document
    except ImportError as error:
        raise RuntimeError("DOCX doğrulaması için python-docx bağımlılığı kurulu değil.") from error
    if not content.startswith(b"PK\x03\x04"):
        raise ValueError("Çıktı ZIP tabanlı DOCX imzasına sahip değil.")
    try:
        document = Document(io.BytesIO(content))
        if not document.sections:
            raise ValueError("DOCX içinde sayfa bölümü bulunamadı.")
    except Exception as error:
        raise ValueError("Üretilen DOCX dosyası açılamadı.") from error


def _validate_formula(formula: Any) -> str:
    value = _text(formula, "Formül", 1_000)
    if not value.startswith("=") or any(token in value for token in ("[", "]", "!", "|", "://", "\n", "\r")):
        raise ValueError("Formül mutlak/dış başvuru veya tehlikeli sözdizimi içeriyor.")
    functions = {name.upper() for name in re.findall(r"([A-Za-z_][A-Za-z0-9_.]*)\s*\(", value)}
    if not functions.issubset(FORMULA_FUNCTIONS):
        raise ValueError("Formülde izin verilmeyen işlev var.")
    if re.fullmatch(r"=[A-Za-z0-9_$().,:+*/^% -]+", value) is None:
        raise ValueError("Formül izin verilen karakter kümesinin dışında.")
    return value


def _validate_cell_value(value: Any) -> Any:
    if isinstance(value, dict):
        if set(value) != {"formula"}:
            raise ValueError("Hücre nesnesi yalnızca formula alanı içerebilir.")
        return _validate_formula(value["formula"])
    if value is None or isinstance(value, (str, bool, int, float)):
        if isinstance(value, str):
            return _text(value, "Hücre değeri", 32_767)
        if isinstance(value, float) and (value != value or value in {float("inf"), float("-inf")}):
            raise ValueError("NaN veya sonsuz hücre değeri kabul edilmiyor.")
        return value
    raise ValueError("Hücre değeri metin, sayı, mantıksal değer veya açık formül olmalı.")


def _validate_xlsx_spec(spec: Any) -> tuple[str, list[dict[str, Any]]]:
    root = _mapping(spec, "XLSX")
    _reject_extra(root, {"title", "sheets"}, "XLSX")
    title = _text(root.get("title", "Çalışma kitabı"), "Çalışma kitabı başlığı", 200)
    raw_sheets = root.get("sheets")
    if not isinstance(raw_sheets, list) or not raw_sheets or len(raw_sheets) > MAX_SHEETS:
        raise ValueError("Çalışma kitabı 1–100 sayfa içermeli.")
    sheets: list[dict[str, Any]] = []
    seen_names: set[str] = set()
    cell_count = 0
    for index, raw in enumerate(raw_sheets):
        sheet = _mapping(raw, f"sheets[{index}]")
        _reject_extra(sheet, {"name", "cells", "tables", "charts", "column_widths", "row_heights"}, f"sheets[{index}]")
        name = _text(sheet.get("name"), "Sayfa adı", 31)
        if not name.strip() or re.search(r"[\[\]:*?/\\]", name) or name.casefold() in seen_names:
            raise ValueError("Excel sayfa adı boş, yinelenmiş veya yasak karakter içeriyor.")
        seen_names.add(name.casefold())
        raw_cells = sheet.get("cells", {})
        if not isinstance(raw_cells, dict):
            raise ValueError("Sayfa cells alanı hücre-koordinat sözlüğü olmalı.")
        cells: dict[str, dict[str, Any]] = {}
        for coordinate, raw_value in raw_cells.items():
            if not isinstance(coordinate, str) or re.fullmatch(r"[A-Za-z]{1,3}[1-9][0-9]{0,6}", coordinate) is None:
                raise ValueError("Hücre koordinatı A1 biçiminde olmalı.")
            clean_coordinate = coordinate.upper()
            _validate_excel_coordinate(clean_coordinate)
            if clean_coordinate in cells:
                raise ValueError("Hücre koordinatı yinelenmiş.")
            if not isinstance(raw_value, dict) or not (set(raw_value) <= {"value", "style"}) or "value" not in raw_value:
                raw_value = {"value": raw_value}
            literal_text = isinstance(raw_value['value'], str)
            value = _validate_cell_value(raw_value["value"])
            style = _mapping(raw_value.get("style", {}), "Hücre stili")
            if set(style) - {"bold", "italic", "font_size", "font_color", "fill_color", "number_format", "horizontal", "wrap_text"}:
                raise ValueError("Desteklenmeyen hücre biçimi alanı.")
            clean_style: dict[str, Any] = {}
            for flag in ("bold", "italic", "wrap_text"):
                if flag in style and not isinstance(style[flag], bool):
                    raise ValueError(f"{flag} mantıksal değer olmalı.")
                if flag in style:
                    clean_style[flag] = style[flag]
            if "font_size" in style:
                size = style["font_size"]
                if not isinstance(size, (int, float)) or isinstance(size, bool) or not 6 <= size <= 72:
                    raise ValueError("Hücre yazı boyutu 6–72 aralığında olmalı.")
                clean_style["font_size"] = float(size)
            for color_key in ("font_color", "fill_color"):
                if color_key in style:
                    clean_style[color_key] = _color(style[color_key], color_key)
            if "number_format" in style:
                clean_style["number_format"] = _text(style["number_format"], "Sayı biçimi", 64)
            if "horizontal" in style:
                if style["horizontal"] not in {"left", "center", "right"}:
                    raise ValueError("Hücre yatay hizası geçersiz.")
                clean_style["horizontal"] = style["horizontal"]
            cells[clean_coordinate] = {"value": value, "style": clean_style, 'literal_text':literal_text}
        cell_count += len(cells)
        tables = _validate_tables(sheet.get("tables", []))
        charts = _validate_charts(sheet.get("charts", []))
        widths = _validate_dimension_map(sheet.get("column_widths", {}), "Sütun genişliği", 1, 255, key_kind="column")
        heights = _validate_dimension_map(sheet.get("row_heights", {}), "Satır yüksekliği", 1, 409, key_kind="row")
        sheets.append({"name": name, "cells": cells, "tables": tables, "charts": charts, "column_widths": widths, "row_heights": heights})
    if cell_count > MAX_CELLS:
        raise ValueError(f"Toplam hücre sayısı {MAX_CELLS} sınırını aşıyor.")
    return title, sheets


def _validate_dimension_map(
    value: Any, label: str, minimum: float, maximum: float, *, key_kind: str
) -> dict[str, float]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} sözlüğü geçersiz.")
    result: dict[str, float] = {}
    for key, measure in value.items():
        valid_column = isinstance(key, str) and len(key) <= 3 and key.isalpha() and key.isascii()
        valid_row = isinstance(key, str) and key.isdigit() and 1 <= int(key) <= 1_048_576
        if not (valid_column if key_kind == "column" else valid_row):
            raise ValueError(f"{label} anahtarı geçersiz.")
        if not isinstance(measure, (int, float)) or isinstance(measure, bool) or not minimum <= measure <= maximum:
            raise ValueError(f"{label} {minimum}–{maximum} aralığında olmalı.")
        result[key.upper() if key_kind == "column" else key] = float(measure)
    return result


def _validate_tables(raw_tables: Any) -> list[dict[str, str]]:
    if not isinstance(raw_tables, list) or len(raw_tables) > 100:
        raise ValueError("Tablolar listesi geçersiz.")
    result = []
    names: set[str] = set()
    for table in raw_tables:
        table = _mapping(table, "Excel tablosu")
        _reject_extra(table, {"name", "ref", "style"}, "Excel tablosu")
        name = _text(table.get("name"), "Tablo adı", 255)
        ref = _text(table.get("ref"), "Tablo aralığı", 32)
        style = _text(table.get("style", "TableStyleMedium2"), "Tablo stili", 64)
        if re.fullmatch(r"TableStyle(?:Medium(?:[1-9]|1[0-9]|2[0-8])|Light(?:[1-9]|[1-2][0-9]|2[0-1])|Dark(?:[1-9]|1[0-1]))", style) is None:
            raise ValueError("Excel tablo stili izin verilen yerleşik stillerden olmalı.")
        if re.fullmatch(r"[A-Za-z]{1,3}[1-9][0-9]{0,6}:[A-Za-z]{1,3}[1-9][0-9]{0,6}", ref) is None:
            raise ValueError("Tablo aralığı A1:B2 biçiminde olmalı.")
        first, last = ref.split(":")
        _validate_excel_coordinate(first.upper())
        _validate_excel_coordinate(last.upper())
        if not _ordered_range(first, last):
            raise ValueError("Tablo aralığının bitiş hücresi başlangıçtan önce olamaz.")
        if not name.isidentifier() or name.casefold() in names:
            raise ValueError("Excel tablo adı geçersiz veya yinelenmiş.")
        names.add(name.casefold())
        result.append({"name": name, "ref": ref.upper(), "style": style})
    return result


def _validate_charts(raw_charts: Any) -> list[dict[str, str]]:
    if not isinstance(raw_charts, list) or len(raw_charts) > 50:
        raise ValueError("Grafik listesi geçersiz.")
    result = []
    for chart in raw_charts:
        chart = _mapping(chart, "Grafik")
        _reject_extra(chart, {"type", "data", "categories", "title"}, "Grafik")
        kind = chart.get("type")
        if kind not in {"bar", "line", "pie"}:
            raise ValueError("Grafik türü bar, line veya pie olmalı.")
        data = _text(chart.get("data"), "Grafik veri aralığı", 64)
        categories = _text(chart.get("categories"), "Grafik kategori aralığı", 64)
        title = _text(chart.get("title", ""), "Grafik başlığı", 200)
        for reference in (data, categories):
            if re.fullmatch(r"\$?[A-Z]{1,3}\$?[1-9][0-9]{0,6}:\$?[A-Z]{1,3}\$?[1-9][0-9]{0,6}", reference.upper()) is None:
                raise ValueError("Grafik aralıkları A1:A5 biçiminde olmalı.")
            first, last = reference.replace("$", "").split(":")
            _validate_excel_coordinate(first.upper())
            _validate_excel_coordinate(last.upper())
            if not _ordered_range(first, last):
                raise ValueError("Grafik aralığının bitiş hücresi başlangıçtan önce olamaz.")
        result.append({"type": kind, "data": data.upper(), "categories": categories.upper(), "title": title})
    return result


def _validate_excel_coordinate(coordinate: str) -> tuple[int, int]:
    match = re.fullmatch(r"([A-Z]{1,3})([1-9][0-9]{0,6})", coordinate)
    if match is None:
        raise ValueError("Excel hücre koordinatı geçersiz.")
    column = 0
    for character in match.group(1):
        column = column * 26 + ord(character) - ord("A") + 1
    row = int(match.group(2))
    if column > 16_384 or row > 1_048_576:
        raise ValueError("Excel hücre koordinatı sayfa sınırlarını aşıyor.")
    return column, row


def _ordered_range(first: str, last: str) -> bool:
    first_col, first_row = _validate_excel_coordinate(first.replace("$", "").upper())
    last_col, last_row = _validate_excel_coordinate(last.replace("$", "").upper())
    return first_col <= last_col and first_row <= last_row


def _xlsx_preview(title: str, sheets: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "format": "XLSX",
        "title": title,
        "sheets": [
            {
                "name": sheet["name"],
                "cells": sheet["cells"],
                "tables": sheet["tables"],
                "charts": sheet["charts"],
            }
            for sheet in sheets
        ],
    }


def build_xlsx(spec: Any) -> DocumentArtifact:
    title, sheets = _validate_xlsx_spec(spec)
    try:
        from openpyxl import Workbook, load_workbook
        from openpyxl.chart import BarChart, LineChart, PieChart, Reference
        from openpyxl.chart.label import DataLabelList
        from openpyxl.styles import Alignment, Font, PatternFill
        from openpyxl.worksheet.table import Table, TableStyleInfo
        from openpyxl.utils.cell import range_boundaries
    except ImportError as error:
        raise RuntimeError("XLSX için openpyxl bağımlılığı kurulu değil.") from error

    workbook = Workbook()
    workbook.remove(workbook.active)
    for sheet_spec in sheets:
        worksheet = workbook.create_sheet(sheet_spec["name"])
        for coordinate, entry in sheet_spec["cells"].items():
            cell = worksheet[coordinate]
            cell.value = entry["value"]
            if entry.get('literal_text'):
                cell.data_type = 's'
            style = entry["style"]
            if style:
                cell.font = Font(
                    bold=style.get("bold", False),
                    italic=style.get("italic", False),
                    size=style.get("font_size"),
                    color=style.get("font_color"),
                )
                if "fill_color" in style:
                    cell.fill = PatternFill(fill_type="solid", fgColor=style["fill_color"])
                cell.alignment = Alignment(
                    horizontal=style.get("horizontal"),
                    wrap_text=style.get("wrap_text", False),
                )
                if "number_format" in style:
                    cell.number_format = style["number_format"]
        for column, width in sheet_spec["column_widths"].items():
            worksheet.column_dimensions[column].width = width
        for row, height in sheet_spec["row_heights"].items():
            worksheet.row_dimensions[int(row)].height = height
        for table_spec in sheet_spec["tables"]:
            min_col, min_row, max_col, max_row = range_boundaries(table_spec["ref"])
            if min_col == max_col or min_row == max_row:
                raise ValueError("Excel tablosu en az iki sütun ve iki satır içermeli.")
            table = Table(displayName=table_spec["name"], ref=table_spec["ref"])
            table.tableStyleInfo = TableStyleInfo(
                name=table_spec["style"], showFirstColumn=False, showLastColumn=False,
                showRowStripes=True, showColumnStripes=False,
            )
            worksheet.add_table(table)
        for chart_spec in sheet_spec["charts"]:
            chart_class = {"bar": BarChart, "line": LineChart, "pie": PieChart}[chart_spec["type"]]
            chart = chart_class()
            chart.title = chart_spec["title"]
            data_bounds = range_boundaries(chart_spec["data"])
            cats_bounds = range_boundaries(chart_spec["categories"])
            data_ref = Reference(
                worksheet, min_col=data_bounds[0], min_row=data_bounds[1],
                max_col=data_bounds[2], max_row=data_bounds[3],
            )
            cats_ref = Reference(
                worksheet, min_col=cats_bounds[0], min_row=cats_bounds[1],
                max_col=cats_bounds[2], max_row=cats_bounds[3],
            )
            chart.add_data(data_ref, titles_from_data=True)
            chart.set_categories(cats_ref)
            if chart_spec["type"] == "pie":
                chart.dataLabels = DataLabelList()
                chart.dataLabels.showPercent = True
            worksheet.add_chart(chart, "H2")

    output = io.BytesIO()
    workbook.save(output)
    content = output.getvalue()
    validate_xlsx(content)
    return DocumentArtifact(f"{_filename(title)}.xlsx", XLSX_MIME, content, _xlsx_preview(title, sheets))


def validate_xlsx(content: bytes) -> None:
    try:
        from openpyxl import load_workbook
    except ImportError as error:
        raise RuntimeError("XLSX doğrulaması için openpyxl bağımlılığı kurulu değil.") from error
    if not content.startswith(b"PK\x03\x04"):
        raise ValueError("Çıktı ZIP tabanlı XLSX imzasına sahip değil.")
    try:
        workbook = load_workbook(io.BytesIO(content), read_only=False, data_only=False)
        if not workbook.sheetnames:
            raise ValueError("XLSX içinde çalışma sayfası bulunamadı.")
        workbook.close()
    except Exception as error:
        raise ValueError("Üretilen XLSX dosyası açılamadı.") from error


def save_artifact(
    root,
    relative_path: str,
    artifact: DocumentArtifact,
    *,
    approved: bool,
    overwrite_approved: bool = False,
):
    if Path(relative_path).suffix.lstrip(".").casefold() != artifact.filename.rsplit(".", 1)[-1].casefold():
        raise ValueError("Dosya uzantısı üretilen biçimle eşleşmiyor.")
    return atomic_write(
        root,
        relative_path,
        artifact.content,
        approved=approved,
        overwrite_approved=overwrite_approved,
    )


def _filename(value: str) -> str:
    cleaned = "".join(character if character.isalnum() or character in "._ -" else "_" for character in value).strip(" ._")
    return (cleaned or "Belge")[:100]
