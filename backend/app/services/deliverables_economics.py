import re
from datetime import date

from app.services.economic_indicators import EconomicIndicators
from app.services.hh_excel_extractor import HHExcelExtractor
from app.services.structured_wiki import StructuredWikiService


class DeliverablesEconomicsAnalyst:
    def __init__(self) -> None:
        self.indicators = EconomicIndicators()
        self.hh = HHExcelExtractor()
        self.wiki = StructuredWikiService()

    async def analyze(self, master_rows: list[dict], limit: int = 12) -> dict:
        current_uf = await self.indicators.current_uf()
        rows = []
        for row in master_rows[:limit]:
            codigo = str(row.get("codigo", "")).strip().upper()
            fecha = row.get("fecha_recep") or row.get("fecha_recepcion")
            historical_uf = await self.indicators.uf_for_date(fecha)
            monto = self._number(row.get("monto"))
            horas = self._number(row.get("horas_lic"))
            tarifa = self._number(row.get("tarifa_prom"))
            tarifa_calc = self._safe_div(monto, horas)
            factor = self._safe_div(current_uf, historical_uf)
            tarifa_hoy = tarifa * factor if tarifa and factor else None
            monto_hoy = monto * factor if monto and factor else None
            wiki_deliverables = self._deliverables_from_wiki(codigo)
            hh_summary = self.hh.summary(codigo)
            hh_rows = self.hh.query(codigo=codigo, limit=12)
            rows.append(
                {
                    "codigo": codigo,
                    "titulo": row.get("titulo", ""),
                    "estado": row.get("estado", ""),
                    "estado_categoria": row.get("estado_categoria", ""),
                    "fecha": fecha,
                    "monto_original": monto,
                    "horas": horas,
                    "tarifa_master": tarifa,
                    "tarifa_calc_monto_horas": tarifa_calc,
                    "uf_fecha": historical_uf,
                    "uf_hoy": current_uf,
                    "factor_actualizacion": factor,
                    "monto_actualizado_hoy": monto_hoy,
                    "tarifa_actualizada_hoy": tarifa_hoy,
                    "entregables_detectados": wiki_deliverables,
                    "excel_hh_summary": hh_summary,
                    "excel_hh_rows": hh_rows,
                    "nota_actualizacion": self._note(current_uf, historical_uf, monto, tarifa),
                }
            )
        return {"as_of": date.today().isoformat(), "method": "UF ratio cuando hay fecha y UF disponible", "rows": rows}

    def _deliverables_from_wiki(self, codigo: str) -> str:
        if not codigo:
            return ""
        hits = self.wiki.search(f"{codigo} entregables alcance", mode="content", limit=4)
        snippets = []
        for hit in hits:
            content = hit.get("content", "")
            match = re.search(r"### Entregables\s+(.*?)(?:\n### |\Z)", content, flags=re.S | re.I)
            if match:
                snippets.append(" ".join(match.group(1).split())[:500])
        return " | ".join(snippets[:2])

    def _number(self, value) -> float | None:
        if value is None:
            return None
        text = str(value).strip().replace(",", ".")
        if not text or text.lower() in {"no data", "nan", "none"}:
            return None
        try:
            return float(text)
        except ValueError:
            return None

    def _safe_div(self, a: float | None, b: float | None) -> float | None:
        if a is None or b in {None, 0}:
            return None
        return a / b

    def _note(self, current_uf, historical_uf, monto, tarifa) -> str:
        if not current_uf or not historical_uf:
            return "No se pudo actualizar por UF; falta indicador actual o historico."
        if monto is None and tarifa is None:
            return "Sin monto/tarifa en Master para actualizar."
        return "Actualizacion estimada por variacion UF; validar moneda original del monto antes de uso comercial."
