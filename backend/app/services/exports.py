from pathlib import Path
from datetime import datetime
import re
import subprocess

import pandas as pd
from docx import Document
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

from app.core.config import settings
from app.schemas import ExportRequest


class ExportService:
    def create(self, kind: str, request: ExportRequest) -> Path:
        self.export_dir.mkdir(parents=True, exist_ok=True)
        if kind == "xlsx":
            return self._xlsx(request)
        if kind == "docx":
            return self._docx(request)
        if kind in {"typst", "typst-pdf", "report"}:
            return self._typst_pdf(request)
        if kind == "pdf":
            return self._pdf(request)
        raise ValueError("Formato soportado: xlsx, docx, pdf")

    def _xlsx(self, request: ExportRequest) -> Path:
        path = self.export_dir / "respuesta.xlsx"
        with pd.ExcelWriter(path, engine="xlsxwriter") as writer:
            pd.DataFrame([{"respuesta": request.answer}]).to_excel(writer, sheet_name="Respuesta", index=False)
            for table in request.tables:
                rows = table.get("rows", [])
                name = str(table.get("name", "Tabla"))[:31]
                pd.DataFrame(rows).to_excel(writer, sheet_name=name, index=False)
            pd.DataFrame([source.model_dump() for source in request.sources]).to_excel(writer, sheet_name="Fuentes", index=False)
        return path

    def _docx(self, request: ExportRequest) -> Path:
        path = self.export_dir / "respuesta.docx"
        doc = Document()
        doc.add_heading(request.title, 1)
        doc.add_paragraph(request.answer)
        for table in request.tables:
            rows = table.get("rows", [])
            if not rows:
                continue
            doc.add_heading(str(table.get("name", "Tabla")), 2)
            columns = list(rows[0].keys())[:8]
            doc_table = doc.add_table(rows=1, cols=len(columns))
            doc_table.style = "Table Grid"
            for index, column in enumerate(columns):
                doc_table.rows[0].cells[index].text = str(column)
            for row in rows[:40]:
                cells = doc_table.add_row().cells
                for index, column in enumerate(columns):
                    cells[index].text = str(row.get(column, ""))
        if request.sources:
            doc.add_heading("Fuentes", 2)
            for source in request.sources:
                doc.add_paragraph(f"{source.kind}: {source.title}")
        doc.save(path)
        return path

    def _pdf(self, request: ExportRequest) -> Path:
        path = self.export_dir / "respuesta.pdf"
        pdf = canvas.Canvas(str(path), pagesize=letter)
        _, height = letter
        y = height - 50
        pdf.setFont("Helvetica-Bold", 14)
        pdf.drawString(50, y, request.title[:90])
        y -= 30
        pdf.setFont("Helvetica", 10)
        for line in request.answer.splitlines():
            if y < 50:
                pdf.showPage()
                y = height - 50
                pdf.setFont("Helvetica", 10)
            pdf.drawString(50, y, line[:110])
            y -= 14
        pdf.save()
        return path

    def _typst_pdf(self, request: ExportRequest) -> Path:
        typst = self._typst_binary()
        if not typst.exists():
            return self._pdf(request)
        slug = self._slug(request.title)
        typ_path = self.export_dir / f"{slug}.typ"
        pdf_path = self.export_dir / f"{slug}.pdf"
        typ_path.write_text(self._typst_document(request), encoding="utf-8")
        subprocess.run(
            [str(typst), "compile", str(typ_path), str(pdf_path)],
            check=True,
            timeout=90,
            cwd=settings.project_root,
        )
        return pdf_path

    def _typst_document(self, request: ExportRequest) -> str:
        generated_at = datetime.now().strftime("%d-%m-%Y %H:%M")
        parts = [
            '#set document(title: "' + self._typst_inline(request.title) + '")',
            '#let shimin-blue = rgb("0b2239")',
            '#let shimin-cyan = rgb("0097a9")',
            '#let shimin-gray = rgb("f4f6f8")',
            '#set page(',
            '  margin: (left: 1.65cm, right: 1.65cm, top: 2.2cm, bottom: 1.65cm),',
            '  header: rect(width: 100%, height: 1.15cm, fill: shimin-blue, inset: 8pt)[',
            '    #grid(columns: (1fr, auto),',
            '      [#set text(fill: white, size: 10pt); *SHIMIN* | Propuestas y experiencia],',
            '      [#set text(fill: white, size: 8pt); ProyectoHH Agents]',
            '    )',
            '  ],',
            '  footer: grid(columns: (1fr, auto),',
            '    [#set text(size: 7.5pt, fill: rgb("667085")); Documento generado desde Planilla Master / RAG / LLM Wiki],',
            '    [#set text(size: 7.5pt, fill: rgb("667085")); #context counter(page).display("1") ]',
            '  ),',
            ')',
            '#set text(font: "Arial", size: 9.3pt, fill: rgb("202124"))',
            '#show heading: set block(above: 0.8em, below: 0.35em)',
            '#show heading.where(level: 1): set text(size: 18pt, fill: shimin-blue)',
            '#show heading.where(level: 2): set text(size: 13pt, fill: shimin-blue)',
            '#show heading.where(level: 3): set text(size: 10.5pt, fill: rgb("344054"))',
            '#show table.cell: set text(size: 7.0pt)',
            "",
            '#block(fill: shimin-gray, inset: 12pt, radius: 2pt)[',
            "= " + self._typst_inline(request.title),
            "",
            '#text(size: 8pt, fill: rgb("667085"))[' + self._typst_inline(f"Generado: {generated_at}") + "]",
            "]",
            "",
            self._markdownish_to_typst(request.answer),
        ]
        if request.charts:
            parts.append("")
            parts.append("== Graficos")
            for chart in request.charts[:4]:
                parts.append(self._typst_chart(chart))
        for table in request.tables[:8]:
            rows = table.get("rows", [])
            if not rows:
                continue
            parts.append("")
            parts.append("== " + self._typst_inline(str(table.get("name", "Tabla"))))
            parts.append(self._typst_table(rows[:20]))
        if request.sources:
            parts.append("")
            parts.append("== Fuentes")
            for source in request.sources[:20]:
                parts.append(f"- {self._typst_inline(source.kind)}: {self._typst_inline(source.title)}")
        return "\n".join(parts)

    def _typst_table(self, rows: list[dict]) -> str:
        columns = list(rows[0].keys())[:6]
        cells = []
        for column in columns:
            cells.append("[*" + self._typst_inline(str(column)) + "*]")
        for row in rows:
            for column in columns:
                cells.append("[" + self._typst_inline(str(row.get(column, ""))[:260]) + "]")
        return "#table(\n  columns: " + str(len(columns)) + ",\n  inset: 4pt,\n  stroke: 0.35pt + rgb(\"d8dee8\"),\n  " + ",\n  ".join(cells) + ",\n)"

    def _typst_chart(self, chart: dict) -> str:
        rows = chart.get("rows", [])
        if not rows:
            return ""
        x_key = chart.get("x")
        y_key = chart.get("y")
        if chart.get("type") == "line":
            series = chart.get("series") or []
            y_key = series[0] if series else None
        if not x_key or not y_key:
            return ""
        values = [self._number(row.get(y_key)) for row in rows[:12]]
        max_value = max(values) if values else 1
        if max_value <= 0:
            max_value = 1
        bars = []
        for row, value in zip(rows[:12], values):
            label = self._typst_inline(str(row.get(x_key, ""))[:28])
            width = max(3, round((value / max_value) * 100, 2))
            bars.append(
                '#grid(columns: (3.6cm, 1fr, 1.2cm), gutter: 6pt,'
                f'[{label}], [#rect(width: {width}%, height: 7pt, fill: shimin-cyan)], [#align(right)[{value:g}]]'
                ')'
            )
        return "\n".join(
            [
                "=== " + self._typst_inline(str(chart.get("name", "Grafico"))),
                '#block(fill: rgb("fbfcfd"), inset: 8pt, stroke: 0.35pt + rgb("d8dee8"))[',
                *bars,
                "]",
            ]
        )

    def _markdownish_to_typst(self, text: str) -> str:
        lines = []
        for raw in text.splitlines()[:220]:
            line = raw.strip()
            if not line:
                lines.append("")
                continue
            if line.startswith("### "):
                lines.append("=== " + self._typst_inline(line[4:]))
            elif line.startswith("## "):
                lines.append("== " + self._typst_inline(line[3:]))
            elif line.startswith("# "):
                lines.append("= " + self._typst_inline(line[2:]))
            elif line.startswith("- "):
                lines.append("- " + self._typst_inline(line[2:]))
            else:
                lines.append(self._typst_inline(line))
        return "\n".join(lines)

    def _typst_inline(self, value: str) -> str:
        text = str(value or "")
        replacements = {
            "\\": "\\\\",
            "#": "\\#",
            "$": "\\$",
            "%": "\\%",
            "&": "\\&",
            "_": "\\_",
            "*": "\\*",
            "[": "\\[",
            "]": "\\]",
        }
        for old, new in replacements.items():
            text = text.replace(old, new)
        return text

    def _number(self, value: object) -> float:
        try:
            return float(str(value or "0").replace(",", "."))
        except ValueError:
            return 0.0

    def _typst_binary(self) -> Path:
        candidates = [
            settings.project_root / "tools" / "typst" / "typst-x86_64-pc-windows-msvc" / "typst.exe",
            settings.project_root / "tools" / "typst" / "typst",
        ]
        return next((path for path in candidates if path.exists()), candidates[0])

    @property
    def export_dir(self) -> Path:
        return settings.resolve_path(settings.export_dir)

    def _slug(self, value: str) -> str:
        slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", value.strip()).strip("-").lower()
        return (slug or "respuesta")[:70]
