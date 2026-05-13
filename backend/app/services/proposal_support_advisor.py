from __future__ import annotations

from app.rag.parent_child import ParentChildIndexer
from app.services.entity_index import EntityIndex
from app.services.hh_excel_extractor import HHExcelExtractor
from app.services.master_repository import MasterRepository
from app.services.proposal_taxonomy import extract_entities, status_category


class ProposalSupportAdvisor:
    def __init__(self) -> None:
        self.master = MasterRepository()
        self.entities = EntityIndex()
        self.rag = ParentChildIndexer()
        self.hh = HHExcelExtractor()

    def advise(self, query: str, selected_codes: list[str] | None = None, limit: int = 16) -> dict:
        selected_codes = [code.strip().upper() for code in selected_codes or [] if code.strip()]
        query_entities = extract_entities(query)
        entity_expansions = self.entities.expand_query(query, limit=18)
        search_queries = [query, " ".join(entity_expansions), *self._entity_terms(query_entities)]

        master_rows = self.master.search_many(search_queries, limit=max(limit * 2, 24))
        for code in selected_codes:
            if not any(str(row.get("codigo", "")).upper() == code for row in master_rows):
                master_rows.extend(self.master.search(codigo=code, limit=1))

        entity_hits = self.entities.search(" ".join([query, *entity_expansions]), limit=80)
        entity_codes = [hit["codigo"] for hit in entity_hits if hit.get("codigo")]
        candidate_codes = self._candidate_codes(selected_codes, master_rows, entity_codes, limit=max(limit, 18))

        candidates = []
        for code in candidate_codes:
            master_row = self._master_for_code(code, master_rows)
            rag_hits = self.rag.search(" ".join([query, *entity_expansions]), codes=[code], limit=5)
            code_entity_hits = [hit for hit in entity_hits if hit.get("codigo") == code][:8]
            hh_summary = self.hh.summary(code)
            hh_rows = self.hh.query(codigo=code, limit=8)
            candidates.append(self._candidate(query, query_entities, master_row, code, code in selected_codes, rag_hits, code_entity_hits, hh_summary, hh_rows))

        buckets = {
            "referencias_directas": [],
            "referencias_comparables": [],
            "referencias_metodologicas": [],
            "referencias_entregables_hh": [],
            "no_recomendadas": [],
        }
        for candidate in sorted(candidates, key=lambda item: item["score"], reverse=True):
            buckets[candidate["classification"]].append(candidate)

        direct_and_comparable = buckets["referencias_directas"][:4] + buckets["referencias_comparables"][:3]
        return {
            "query": query,
            "intent": "apoyo_armado_propuesta",
            "entity_expansions": entity_expansions,
            "query_entities": query_entities,
            **buckets,
            "texto_sugerido_pdf": self._suggested_texts(direct_and_comparable),
            "gaps_a_validar": self._gaps(candidates),
            "deepening_plan": self._deepening_plan(candidates),
            "tables": self._tables(buckets),
            "coverage": {
                "master_candidates": len(master_rows),
                "candidate_codes": len(candidate_codes),
                "entity_hits": len(entity_hits),
            },
        }

    def _candidate(
        self,
        query: str,
        query_entities: dict[str, list[str]],
        master_row: dict,
        code: str,
        selected: bool,
        rag_hits: list[dict],
        entity_hits: list[dict],
        hh_summary: dict,
        hh_rows: list[dict],
    ) -> dict:
        title = str(master_row.get("titulo") or code)
        estado = str(master_row.get("estado") or "").upper()
        category = status_category(estado)
        title_entities = extract_entities(title)
        overlap = self._overlap(query_entities, title_entities)
        rag_entity_overlap = self._rag_entity_overlap(query_entities, rag_hits)
        evidence_score = len(rag_hits) * 1.5 + min(hh_summary.get("rows") or 0, 20) / 10
        direct_title = self._direct_title_match(query, title)
        selected_relevant = selected and bool(extract_entities(title))
        stage_match = self._stage_match(query, title, rag_hits)
        score = overlap * 5 + rag_entity_overlap * 3 + evidence_score + (8 if direct_title else 0) + (4 if selected_relevant else 0) + (3 if category == "ganada" else 0)

        if direct_title or (selected_relevant and ("relaves" in title.lower() or "dewatering" in title.lower() or "bombeo" in title.lower())) or (overlap >= 2 and stage_match):
            classification = "referencias_directas"
        elif rag_entity_overlap >= 2 or overlap >= 1:
            classification = "referencias_comparables"
        elif stage_match or self._methodology_match(query, title, rag_hits):
            classification = "referencias_metodologicas"
        elif hh_summary.get("rows"):
            classification = "referencias_entregables_hh"
        else:
            classification = "no_recomendadas"

        if classification == "no_recomendadas" and direct_title:
            classification = "referencias_directas"

        reasons = self._reasons(classification, category, direct_title, selected_relevant, overlap, rag_entity_overlap, stage_match, rag_hits, hh_summary)
        limitations = self._limitations(classification, rag_hits, hh_summary, master_row)
        return {
            "codigo": code,
            "classification": classification,
            "score": round(score, 2),
            "titulo": title,
            "cliente_directo": master_row.get("cliente_directo"),
            "cliente_final": master_row.get("cliente_final"),
            "estado": estado or "No data",
            "estado_categoria": category,
            "seleccionada_por_usuario": selected,
            "monto": master_row.get("monto"),
            "horas_master": master_row.get("horas_lic"),
            "tarifa_master": master_row.get("tarifa_prom"),
            "por_que_sirve": reasons,
            "como_usarla_en_propuesta": self._usage_suggestions(classification, category, rag_hits, hh_summary),
            "limitaciones": limitations,
            "evidencia_rag": [self._rag_evidence(hit) for hit in rag_hits],
            "entidades": {
                "master_title": title_entities,
                "rag": self._merge_rag_entities(rag_hits),
                "entity_hits": entity_hits,
            },
            "hh": {
                "summary": hh_summary,
                "sample_rows": [self._hh_row(row) for row in hh_rows],
            },
            "deepening": self._should_deepen(classification, rag_hits, hh_summary, limitations),
        }

    def _candidate_codes(self, selected_codes: list[str], master_rows: list[dict], entity_codes: list[str], limit: int) -> list[str]:
        codes = []
        for code in [*selected_codes, *[str(row.get("codigo", "")).upper() for row in master_rows], *entity_codes]:
            if code and code not in codes:
                codes.append(code)
        return codes[:limit]

    def _master_for_code(self, code: str, rows: list[dict]) -> dict:
        for row in rows:
            if str(row.get("codigo", "")).upper() == code:
                return row
        found = self.master.search(codigo=code, limit=1)
        return found[0] if found else {"codigo": code, "titulo": code}

    def _entity_terms(self, entities: dict[str, list[str]]) -> list[str]:
        return [" ".join(values) for values in entities.values()]

    def _overlap(self, left: dict[str, list[str]], right: dict[str, list[str]]) -> int:
        count = 0
        for group, values in left.items():
            count += len(set(values) & set(right.get(group, [])))
        return count

    def _rag_entity_overlap(self, query_entities: dict[str, list[str]], rag_hits: list[dict]) -> int:
        merged = self._merge_rag_entities(rag_hits)
        return self._overlap(query_entities, merged)

    def _merge_rag_entities(self, rag_hits: list[dict]) -> dict[str, list[str]]:
        merged: dict[str, list[str]] = {}
        for hit in rag_hits:
            entities = hit.get("metadata", {}).get("section_entities") or {}
            for group, values in entities.items():
                bucket = merged.setdefault(group, [])
                for value in values:
                    if value not in bucket:
                        bucket.append(value)
        return merged

    def _direct_title_match(self, query: str, title: str) -> bool:
        q = query.lower()
        t = title.lower()
        strong_terms = ["relaves", "dewatering", "bombeo", "factibilidad", "disposicion", "drenaje", "tranque"]
        return sum(1 for term in strong_terms if term in q and term in t) >= 2

    def _stage_match(self, query: str, title: str, rag_hits: list[dict]) -> bool:
        text = " ".join([query, title, *[hit.get("title", "") for hit in rag_hits]]).lower()
        return any(term in text for term in ["factibilidad", "prefactibilidad", "conceptual", "basica", "detalle"])

    def _methodology_match(self, query: str, title: str, rag_hits: list[dict]) -> bool:
        text = " ".join([query, title, *[hit.get("summary", "") for hit in rag_hits]]).lower()
        return any(term in text for term in ["alternativa", "trade off", "benchmark", "diagnostico", "estudio", "evaluacion"])

    def _reasons(self, classification: str, status: str, direct_title: bool, selected_relevant: bool, overlap: int, rag_overlap: int, stage_match: bool, rag_hits: list[dict], hh_summary: dict) -> list[str]:
        reasons = []
        if direct_title:
            reasons.append("Coincide directamente con conceptos clave del requerimiento en el titulo de la Master.")
        if selected_relevant:
            reasons.append("Fue seleccionada explicitamente por el usuario y su titulo contiene entidades tecnicas utiles.")
        if overlap:
            reasons.append(f"Comparte {overlap} entidades tecnicas con la pregunta segun taxonomia.")
        if rag_overlap:
            reasons.append(f"El RAG encontro secciones con {rag_overlap} entidades tecnicas relevantes.")
        if stage_match:
            reasons.append("Comparte etapa o tipo de estudio de ingenieria.")
        if status == "ganada":
            reasons.append("Es una propuesta ganada; sirve como referencia comercial mas fuerte.")
        if rag_hits:
            reasons.append("Tiene evidencia documental indexada para justificar la mencion.")
        if hh_summary.get("rows"):
            reasons.append("Tiene Excel HH/entregables extraido para usar como benchmark de alcance y esfuerzo.")
        if not reasons:
            reasons.append("Aparece como candidato debil; requiere validacion antes de usarla.")
        return reasons

    def _usage_suggestions(self, classification: str, status: str, rag_hits: list[dict], hh_summary: dict) -> list[str]:
        suggestions = []
        if classification == "referencias_directas":
            suggestions.append("Usarla como antecedente principal de experiencia especifica SHIMIN.")
        if classification == "referencias_comparables":
            suggestions.append("Usarla como respaldo de capacidad tecnica en sistemas, disciplinas o instalaciones relacionadas.")
        if classification == "referencias_metodologicas":
            suggestions.append("Usarla para demostrar metodologia: evaluacion de alternativas, factibilidad, trade-off, diagnostico o estudio multidisciplinario.")
        if hh_summary.get("rows"):
            suggestions.append("Revisar Excel HH para reutilizar estructura de entregables, actividades, roles y distribucion de horas.")
        if rag_hits:
            suggestions.append("Profundizar en las secciones RAG recomendadas antes de citar texto en el PDF.")
        if status == "ganada":
            suggestions.append("Destacarla sobre propuestas presentadas/perdidas cuando se necesite una referencia robusta.")
        return suggestions

    def _limitations(self, classification: str, rag_hits: list[dict], hh_summary: dict, master_row: dict) -> list[str]:
        limitations = []
        if not rag_hits:
            limitations.append("No hay evidencia RAG disponible para esta propuesta; usar solo como referencia Master hasta validar PDF.")
        if not hh_summary.get("rows"):
            limitations.append("No hay Excel HH extraido; no usar como benchmark de horas/entregables sin buscar archivo.")
        if classification == "referencias_comparables":
            limitations.append("No es el mismo tema exacto; mencionar solo el componente comparable.")
        if classification == "referencias_metodologicas":
            limitations.append("Sirve por enfoque de estudio, no como experiencia directa del tema.")
        if not master_row.get("estado"):
            limitations.append("Estado comercial no disponible en Master.")
        return limitations

    def _rag_evidence(self, hit: dict) -> dict:
        metadata = hit.get("metadata", {})
        return {
            "title": hit.get("title"),
            "score": hit.get("score"),
            "page_start": metadata.get("page_start"),
            "page_end": metadata.get("page_end"),
            "section_index": metadata.get("section_index"),
            "child_index": metadata.get("child_index"),
            "entities": metadata.get("section_entities"),
            "summary": hit.get("summary", "")[:800],
        }

    def _hh_row(self, row: dict) -> dict:
        return {
            "workbook_name": row.get("workbook_name"),
            "sheet_name": row.get("sheet_name"),
            "row_number": row.get("row_number"),
            "deliverable": row.get("deliverable"),
            "activity": row.get("activity"),
            "discipline": row.get("discipline"),
            "role": row.get("role"),
            "hours": row.get("hours"),
            "rate": row.get("rate"),
            "amount": row.get("amount"),
            "confidence": row.get("confidence"),
        }

    def _should_deepen(self, classification: str, rag_hits: list[dict], hh_summary: dict, limitations: list[str]) -> dict:
        deep_rag = bool(rag_hits) and classification in {"referencias_directas", "referencias_comparables", "referencias_metodologicas"}
        deep_excel = bool(hh_summary.get("rows"))
        deep_pdf = classification == "referencias_directas" and bool(rag_hits)
        reasons = []
        if deep_rag:
            reasons.append("Hay secciones RAG relevantes para justificar la recomendacion.")
        if deep_excel:
            reasons.append("Hay Excel HH disponible para analizar entregables, actividades y esfuerzo.")
        if not rag_hits:
            reasons.append("Falta evidencia documental; validar PDF emitido antes de citar.")
        if limitations:
            reasons.append("Existen limitaciones que deben explicitarse en la respuesta.")
        priority = 0.8 if classification == "referencias_directas" else 0.55 if classification == "referencias_comparables" else 0.35
        return {"deep_rag": deep_rag, "deep_pdf": deep_pdf, "deep_excel": deep_excel, "priority": priority, "reasons": reasons}

    def _suggested_texts(self, candidates: list[dict]) -> list[dict]:
        texts = []
        for candidate in candidates[:6]:
            code = candidate["codigo"]
            title = candidate["titulo"]
            status = candidate["estado_categoria"]
            if candidate["classification"] == "referencias_directas":
                if status == "ganada":
                    text = (
                        f"SHIMIN cuenta con experiencia directamente relacionada en {title} ({code}), "
                        "referencia adjudicada que puede utilizarse para sustentar alcance, metodologia y criterios de desarrollo del servicio."
                    )
                else:
                    text = (
                        f"Como antecedente tecnico interno, la referencia {code} ({title}) presenta similitud directa con el requerimiento. "
                        "Antes de citarla comercialmente, se recomienda validar estado, documento emitido y alcance exacto."
                    )
            else:
                text = (
                    f"Adicionalmente, la referencia {code} ({title}) puede utilizarse como experiencia comparable, "
                    "en la medida que respalda capacidades tecnicas, metodologicas o multidisciplinarias relacionadas con el requerimiento."
                )
            texts.append({"codigo": code, "texto": text, "uso": candidate["classification"]})
        return texts

    def _gaps(self, candidates: list[dict]) -> list[dict]:
        gaps = []
        for candidate in candidates:
            if candidate["classification"] == "no_recomendadas":
                continue
            for limitation in candidate["limitaciones"]:
                gaps.append({"codigo": candidate["codigo"], "gap": limitation})
        return gaps[:20]

    def _deepening_plan(self, candidates: list[dict]) -> list[dict]:
        plan = []
        for candidate in sorted(candidates, key=lambda item: item["deepening"]["priority"], reverse=True):
            if any([candidate["deepening"]["deep_rag"], candidate["deepening"]["deep_pdf"], candidate["deepening"]["deep_excel"]]):
                plan.append({"codigo": candidate["codigo"], **candidate["deepening"]})
        return plan[:10]

    def _tables(self, buckets: dict[str, list[dict]]) -> list[dict]:
        rows = []
        for bucket, candidates in buckets.items():
            for candidate in candidates[:8]:
                rows.append(
                    {
                        "categoria": bucket,
                        "codigo": candidate["codigo"],
                        "estado": candidate["estado"],
                        "estado_categoria": candidate["estado_categoria"],
                        "titulo": candidate["titulo"],
                        "score": candidate["score"],
                        "tiene_rag": bool(candidate["evidencia_rag"]),
                        "tiene_hh": bool(candidate["hh"]["summary"].get("rows")),
                    }
                )
        return [{"name": "Referencias para propuesta", "rows": rows}]
