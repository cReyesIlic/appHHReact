from collections import Counter, defaultdict
from datetime import datetime
from typing import Any

from app.services.master_repository import MasterRepository


class MasterStatsAnalyst:
    def __init__(self) -> None:
        self.master = MasterRepository()

    def should_run(self, text: str) -> bool:
        normalized = text.lower()
        triggers = [
            "estadistica",
            "estadisticas",
            "grafico",
            "graficos",
            "dashboard",
            "distribucion",
            "tendencia",
            "cuantas",
            "cuantos",
            "por estado",
            "por cliente",
            "por año",
            "por ano",
            "ganadas",
            "perdidas",
        ]
        return any(trigger in normalized for trigger in triggers)

    def analyze(self, query: str | None = None, limit: int = 20) -> dict[str, Any]:
        rows = self.master.search(query=query, limit=5000) if query else self.master.all_offers()
        rows = [row for row in rows if str(row.get("codigo", "")).strip()]
        by_status = Counter(str(row.get("estado", "No data")).strip().upper() or "No data" for row in rows)
        by_client = Counter(str(row.get("cliente_final") or row.get("cliente_directo") or "No data").strip() for row in rows)
        by_year_status: dict[str, Counter] = defaultdict(Counter)
        won_by_year = Counter()
        lost_by_year = Counter()

        for row in rows:
            year = self._year(row.get("fecha_recep"))
            status = str(row.get("estado", "")).strip().upper()
            if year:
                by_year_status[year][status or "No data"] += 1
                if status == "PG":
                    won_by_year[year] += 1
                if status in {"PP", "PL", "PE", "NP", "NL", "PD"}:
                    lost_by_year[year] += 1

        status_rows = [{"estado": key, "ofertas": value} for key, value in by_status.most_common()]
        client_rows = [{"cliente": key, "ofertas": value} for key, value in by_client.most_common(limit)]
        year_rows = []
        for year in sorted(by_year_status):
            item = {"anio": year, "total": sum(by_year_status[year].values()), "ganadas": won_by_year[year], "perdidas_o_no_adjudicadas": lost_by_year[year]}
            year_rows.append(item)

        return {
            "query": query or "",
            "summary": {
                "ofertas_analizadas": len(rows),
                "ganadas_pg": by_status.get("PG", 0),
                "perdidas_o_no_adjudicadas": sum(by_status.get(code, 0) for code in ["PP", "PL", "PE", "NP", "NL", "PD"]),
                "clientes_distintos": len(by_client),
            },
            "tables": [
                {"name": "Estadistica por Estado", "rows": status_rows},
                {"name": "Top Clientes Master", "rows": client_rows},
                {"name": "Tendencia Anual Master", "rows": year_rows},
            ],
            "charts": [
                {"name": "Ofertas por estado", "type": "bar", "x": "estado", "y": "ofertas", "rows": status_rows[:12]},
                {"name": "Top clientes por ofertas", "type": "bar", "x": "cliente", "y": "ofertas", "rows": client_rows[:12]},
                {"name": "Ganadas vs perdidas por año", "type": "line", "x": "anio", "series": ["ganadas", "perdidas_o_no_adjudicadas"], "rows": year_rows[-10:]},
            ],
        }

    def _year(self, value: object) -> str:
        text = str(value or "").strip()
        for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%Y/%m/%d", "%d/%m/%Y"):
            try:
                return str(datetime.strptime(text[:10], fmt).year)
            except ValueError:
                continue
        return ""
