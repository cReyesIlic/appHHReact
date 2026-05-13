import json
import sqlite3
import unicodedata
from collections import Counter

from app.core.config import settings
from app.services.proposal_taxonomy import extract_entities
from app.services.search_filters import SearchFilters


class EntityIndex:
    def __init__(self) -> None:
        self._ensure_table()

    def rebuild_from_rag(self) -> dict:
        with sqlite3.connect(settings.sqlite_path) as conn:
            rows = conn.execute(
                """
                select parent_id, codigo, title, text, metadata
                from rag_parent_sections
                """
            ).fetchall()
            conn.execute("delete from proposal_entities")
            inserted = 0
            for parent_id, codigo, title, text, metadata_json in rows:
                metadata = json.loads(metadata_json or "{}")
                entities = self._merge_entities(
                    metadata.get("entidades_taxonomia") or {},
                    metadata.get("section_entities") or {},
                    extract_entities(" ".join([str(title), str(text)[:5000]])),
                )
                for group, values in entities.items():
                    for value in values:
                        conn.execute(
                            """
                            insert into proposal_entities
                            (codigo, entity_group, entity_value, source, parent_id, section_title, weight, metadata)
                            values (?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                codigo,
                                group,
                                value,
                                "rag_parent_section",
                                parent_id,
                                title,
                                self._weight(group),
                                json.dumps({"section_title": title}, ensure_ascii=False),
                            ),
                        )
                        inserted += 1
        return {"parents": len(rows), "entities": inserted}

    def search(
        self,
        query: str,
        limit: int = 40,
        filters: SearchFilters | None = None,
    ) -> list[dict]:
        terms = [term for term in self._norm(query).split() if len(term) >= 3]
        if not terms and not (filters and filters.has_metadata_filters()):
            return []
        sql = """
            select e.codigo, e.entity_group, e.entity_value, e.section_title, e.parent_id, e.weight
            from proposal_entities e
        """
        params: list = []
        where: list[str] = []
        if filters and filters.has_metadata_filters():
            sql += " join rag_parent_sections p on p.parent_id = e.parent_id"
            filter_clauses, filter_params = filters.sql_clauses(table_alias="p")
            # ajustar referencias `p.codigo` (codigo está en ambas, usamos p)
            where.extend(filter_clauses)
            params.extend(filter_params)
        if where:
            sql += " where " + " and ".join(where)
        with sqlite3.connect(settings.sqlite_path) as conn:
            rows = conn.execute(sql, params).fetchall()
        hits = []
        for codigo, group, value, section_title, parent_id, weight in rows:
            haystack = self._norm(" ".join([group, value, section_title or ""]))
            score = sum(1 for term in terms if term in haystack) * float(weight or 1)
            if not terms and filters and filters.has_metadata_filters():
                score = float(weight or 1)
            if score:
                hits.append(
                    {
                        "codigo": codigo,
                        "entity_group": group,
                        "entity_value": value,
                        "section_title": section_title,
                        "parent_id": parent_id,
                        "score": score,
                    }
                )
        hits.sort(key=lambda item: item["score"], reverse=True)
        return hits[:limit]

    def expand_query(self, query: str, limit: int = 20, filters: SearchFilters | None = None) -> list[str]:
        hits = self.search(query, limit=200, filters=filters)
        counter: Counter[str] = Counter()
        for hit in hits:
            counter[hit["entity_value"]] += int(hit["score"])
        return [value for value, _ in counter.most_common(limit)]

    def status(self) -> dict:
        with sqlite3.connect(settings.sqlite_path) as conn:
            total = conn.execute("select count(*) from proposal_entities").fetchone()[0]
            proposals = conn.execute("select count(distinct codigo) from proposal_entities").fetchone()[0]
            groups = conn.execute(
                "select entity_group, count(*) from proposal_entities group by entity_group order by count(*) desc"
            ).fetchall()
        return {"entities": total, "proposal_count": proposals, "groups": dict(groups)}

    def _merge_entities(self, *items: dict[str, list[str]]) -> dict[str, list[str]]:
        merged: dict[str, list[str]] = {}
        for item in items:
            for group, values in item.items():
                current = merged.setdefault(group, [])
                for value in values:
                    if value not in current:
                        current.append(value)
        return merged

    def _weight(self, group: str) -> float:
        weights = {
            "procesos_sistemas": 4.0,
            "instalaciones_mineras": 3.5,
            "componentes": 3.0,
            "etapa_ingenieria": 2.5,
            "disciplinas": 2.0,
            "artefactos_propuesta": 1.0,
        }
        return weights.get(group, 1.0)

    def _ensure_table(self) -> None:
        settings.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(settings.sqlite_path) as conn:
            conn.execute(
                """
                create table if not exists proposal_entities (
                    id integer primary key autoincrement,
                    codigo text not null,
                    entity_group text not null,
                    entity_value text not null,
                    source text not null,
                    parent_id text,
                    section_title text,
                    weight real not null,
                    metadata text not null
                )
                """
            )
            conn.execute("create index if not exists idx_proposal_entities_codigo on proposal_entities(codigo)")
            conn.execute("create index if not exists idx_proposal_entities_value on proposal_entities(entity_value)")

    def _norm(self, value: object) -> str:
        text = unicodedata.normalize("NFKD", str(value or "").lower())
        return "".join(ch for ch in text if not unicodedata.combining(ch))
