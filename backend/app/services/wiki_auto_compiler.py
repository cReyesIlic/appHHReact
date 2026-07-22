"""Compilación de Wiki técnica con evidencia trazable por propuesta."""

from __future__ import annotations

import json
import re
import sqlite3
import unicodedata
from hashlib import sha1
from pathlib import Path

from app.core.config import settings
from app.services.llm import LlmService
from app.services.structured_wiki import StructuredWikiService


class WikiAutoCompiler:
    def __init__(self) -> None:
        self.llm = LlmService()
        self.wiki = StructuredWikiService()

    async def propose(
        self,
        topic: str,
        source_text: str,
        source_kind: str = "analysis",
        candidate_codes: list[str] | None = None,
        pin_if_operational: bool = True,
        existing_entry_id: str | None = None,
    ) -> dict:
        candidate_codes = candidate_codes or []
        existing = self._existing_context(topic, existing_entry_id)
        draft = await self._draft(topic, source_text, source_kind, candidate_codes, existing)
        draft["pinned"] = bool(pin_if_operational and draft.get("operational_value", True))
        draft["existing_entry_id"] = existing.get("id") if existing else None
        draft["action"] = "update" if existing else "create"
        draft["source"] = source_kind
        return draft

    async def create_or_update(
        self,
        topic: str,
        source_text: str,
        source_kind: str = "analysis",
        candidate_codes: list[str] | None = None,
        pin_if_operational: bool = True,
        existing_entry_id: str | None = None,
    ) -> dict:
        proposal = await self.propose(
            topic=topic,
            source_text=source_text,
            source_kind=source_kind,
            candidate_codes=candidate_codes,
            pin_if_operational=pin_if_operational,
            existing_entry_id=existing_entry_id,
        )
        entry = self.wiki.upsert_entry(
            entry_id=proposal.get("existing_entry_id"),
            title=proposal["title"],
            category=proposal["category"],
            tags=proposal["tags"],
            content=proposal["content"],
            pinned=proposal["pinned"],
            source=source_kind,
        )
        return {"action": proposal["action"], "entry": entry, "proposal": proposal}

    async def _draft(
        self,
        topic: str,
        source_text: str,
        source_kind: str,
        candidate_codes: list[str],
        existing: dict | None,
    ) -> dict:
        fallback = self._fallback(topic, source_text, source_kind, candidate_codes, existing)
        if not self.llm.client:
            return fallback
        try:
            response = await self.llm._chat(
                deployment=settings.index_deployment if self.llm.azure else "gpt-4o-mini",
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Compila una ficha técnica AUDITABLE de una propuesta de ingeniería SHIMIN usando "
                            "exclusivamente la evidencia rotulada [F1], [F2], etc. No completes vacíos con "
                            "conocimiento general ni con inferencias sobre el título. No mezcles información "
                            "de códigos O distintos del código objetivo. Devuelve sólo JSON con keys: title, "
                            "category, tags, operational_value, content, rag_quality_score, wiki_quality_score, "
                            "quality_summary, quality_issues. content debe ser Markdown sustantivo con estas "
                            "secciones: Resumen ejecutivo; Alcance del servicio; Entregables; Disciplinas y "
                            "responsabilidades; Datos cuantitativos y plazos; Supuestos, exclusiones y criterios; "
                            "Evidencia y fuentes; Vacíos de información. Omite secciones sin evidencia o indica "
                            "'No identificado en las fuentes'. Cada afirmación factual debe terminar con una cita "
                            "como [F1, pp. 3-4]. Conserva cantidades, unidades, nombres y códigos. No incluyas "
                            "secciones genéricas llamadas 'Cómo usar', 'Entidades útiles' ni 'Criterios de "
                            "búsqueda'. Distingue evidencia de inferencia; normalmente no debe haber inferencias. "
                            "Evalúa de 0 a 100 la suficiencia del RAG y la fidelidad/cobertura de la Wiki. "
                            "Penaliza con menos de 50 si faltan alcance, entregables o citas."
                        ),
                    },
                    {
                        "role": "user",
                        "content": json.dumps(
                            {
                                "topic": topic,
                                "source_kind": source_kind,
                                "candidate_codes": candidate_codes,
                                # No enviamos contenido anterior: puede ser la página contaminada que reparamos.
                                "existing_entry": (
                                    {"id": existing.get("id"), "title": existing.get("title")}
                                    if existing else None
                                ),
                                "source_text": source_text[:48000],
                            },
                            ensure_ascii=False,
                        ),
                    },
                ],
                max_completion_tokens=4096,
                response_format={"type": "json_object"},
            )
            data = json.loads(response)
            draft = {
                "title": str(data.get("title") or fallback["title"])[:120],
                "category": str(data.get("category") or fallback["category"])[:80],
                "tags": [str(tag).strip() for tag in data.get("tags", fallback["tags"]) if str(tag).strip()][:12],
                "operational_value": bool(data.get("operational_value", fallback["operational_value"])),
                "content": str(data.get("content") or fallback["content"]),
                "rag_quality_score": self._score(data.get("rag_quality_score"), fallback["rag_quality_score"]),
                "wiki_quality_score": self._score(data.get("wiki_quality_score"), fallback["wiki_quality_score"]),
                "quality_summary": str(data.get("quality_summary") or fallback["quality_summary"])[:500],
                "quality_issues": [str(item)[:240] for item in data.get("quality_issues", []) if str(item).strip()][:8],
                "quality_mode": "ai",
            }
            return self._quality_gate(draft, fallback, source_text, candidate_codes)
        except Exception:
            return fallback

    async def compile_for_proposal(
        self,
        codigo: str,
        force: bool = False,
        *,
        defer_reindex: bool = False,
    ) -> dict:
        """Compila una página sólo con RAG verificablemente asociado al mismo código."""
        codigo_upper = self._canonical_offer_code(codigo)
        if not codigo_upper:
            return {"codigo": codigo, "status": "error", "error": "código inválido"}

        proposals_dir = settings.resolve_path("storage/llm_wiki/proposals")
        proposals_dir.mkdir(parents=True, exist_ok=True)
        target_file = proposals_dir / f"{codigo_upper}.md"
        if target_file.exists() and not force:
            published = self._published_ai_page(target_file, codigo_upper)
            if published:
                return {
                    "codigo": codigo_upper,
                    "status": "skipped",
                    "reason": "wiki AI evidence-v3 vigente",
                    "path": str(target_file),
                    **published,
                }

        rag_payload = self._collect_rag_material(codigo_upper)
        if not rag_payload["parents"]:
            if rag_payload.get("invalid_parent_count"):
                return {
                    "codigo": codigo_upper,
                    "status": "invalid_rag",
                    "error": "Los chunks RAG apuntan a archivos de otro código; se requiere reingesta desde SharePoint.",
                    "invalid_parent_count": rag_payload["invalid_parent_count"],
                    "invalid_sources": rag_payload.get("invalid_sources") or [],
                }
            return {"codigo": codigo_upper, "status": "no_rag", "reason": "sin chunks RAG válidos"}

        master_row = self._master_row(codigo_upper)
        titulo = (master_row or {}).get("titulo") or rag_payload.get("document_title") or codigo_upper
        cliente = (
            (master_row or {}).get("cliente_final")
            or (master_row or {}).get("cliente_directo")
            or rag_payload.get("cliente")
        )
        estado = (master_row or {}).get("estado")
        tipo_servicio = (master_row or {}).get("tipo_servicio")
        topic = f"{codigo_upper} — {titulo}"
        source_text = self._format_source_text(
            codigo_upper, titulo, cliente, estado, tipo_servicio, rag_payload
        )

        existing_entry_id = sha1(f"rag_autocompile:{codigo_upper}".encode("utf-8")).hexdigest()[:12]
        try:
            existing = self.wiki.get_entry(existing_entry_id)
        except KeyError:
            existing = None
        draft = await self._draft(topic, source_text, "rag_autocompile", [codigo_upper], existing)
        if draft.get("quality_mode") != "ai":
            # La migración técnica no publica resúmenes heurísticos. El
            # extractivo queda sólo como salvaguarda interna y la propuesta se
            # mantiene pendiente para reintentar con Azure OpenAI.
            return {
                "codigo": codigo_upper,
                "status": "ai_retry",
                "error": "Azure OpenAI no generó una ficha que superara el control de evidencia; se reintentará.",
                "sources": rag_payload.get("sources") or [],
                "quality": {
                    "mode": draft.get("quality_mode") or "unavailable",
                    "rag_score": draft.get("rag_quality_score"),
                    "wiki_score": draft.get("wiki_quality_score"),
                    "summary": draft.get("quality_summary"),
                    "issues": draft.get("quality_issues") or [],
                },
            }
        entry_title = str(draft.get("title") or topic)[:120]
        if codigo_upper not in entry_title.upper():
            entry_title = topic[:120]

        filtros = {}
        if estado:
            filtros["estados"] = [estado]
        if tipo_servicio and tipo_servicio != "No data":
            filtros["tipos_servicio"] = [tipo_servicio.split(",")[0].strip()]
        if cliente and cliente != "No data":
            filtros["clientes"] = [cliente]

        entry = self.wiki.upsert_entry(
            title=entry_title,
            content=str(draft.get("content") or ""),
            category=str(draft.get("category") or "propuesta")[:80],
            tags=draft.get("tags", []),
            pinned=False,
            source="rag_autocompile",
            entry_id=existing_entry_id,
            propuestas_referenciadas=[codigo_upper],
            filtros_aplicables=filtros,
            skip_reindex=defer_reindex,
        )
        page_md = self._page_markdown(
            codigo_upper, titulo, cliente, estado, tipo_servicio, entry, draft, rag_payload
        )
        target_file.write_text(page_md, encoding="utf-8")
        duplicate_cleanup = self.wiki.remove_duplicate_proposal_entries(
            codigo_upper,
            str(entry.get("id") or ""),
            protected_paths=[target_file],
        )
        return {
            "codigo": codigo_upper,
            "status": "ok",
            "entry_id": entry.get("id"),
            "path": str(target_file),
            "title": titulo,
            "duplicate_cleanup": duplicate_cleanup,
            "sources": rag_payload.get("sources") or [],
            "invalid_parent_count": rag_payload.get("invalid_parent_count") or 0,
            "quality": {
                "mode": draft.get("quality_mode") or "heuristic",
                "rag_score": draft.get("rag_quality_score"),
                "wiki_score": draft.get("wiki_quality_score"),
                "summary": draft.get("quality_summary"),
                "issues": draft.get("quality_issues") or [],
            },
        }

    def _published_ai_page(self, path, codigo: str) -> dict | None:
        """Recupera identidad/calidad sin degradar una Wiki AI ya publicada."""
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            return None
        if not text.startswith("---"):
            return None
        _, _, rest = text.partition("---")
        frontmatter, separator, _ = rest.partition("---")
        if not separator:
            return None
        meta = {}
        for line in frontmatter.splitlines():
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            meta[key.strip()] = value.strip().strip('"')
        if meta.get("wiki_schema") != "evidence-v3":
            return None
        try:
            wiki_score = float(meta.get("wiki_quality_score") or 0)
        except (TypeError, ValueError):
            wiki_score = 0.0
        return {
            "entry_id": meta.get("entry_id") or sha1(
                f"rag_autocompile:{codigo}".encode("utf-8")
            ).hexdigest()[:12],
            "quality": {
                "mode": "ai",
                "wiki_score": wiki_score,
                "summary": "Wiki AI evidence-v3 ya publicada; se conserva su evaluación.",
                "issues": [],
            },
        }

    def _collect_rag_material(
        self,
        codigo: str,
        max_parents: int = 8,
        parent_chars: int = 12000,
    ) -> dict:
        with sqlite3.connect(settings.sqlite_path, timeout=30) as conn:
            rows = conn.execute(
                """
                select parent_id, title, text, page_start, page_end, metadata
                from rag_parent_sections
                where codigo = ?
                order by parent_id
                """,
                (codigo,),
            ).fetchall()

        candidates = []
        document_title = None
        cliente = None
        invalid_sources: set[str] = set()
        invalid_count = 0
        for parent_id, title, text, page_start, page_end, meta_json in rows:
            try:
                metadata = json.loads(meta_json or "{}")
            except json.JSONDecodeError:
                metadata = {}
            valid, source_identity = self._source_matches_code(codigo, metadata)
            if not valid:
                invalid_count += 1
                invalid_sources.add(source_identity or str(parent_id))
                continue
            clean_text = str(text or "").strip()
            if len(clean_text) < 20:
                continue
            document_title = document_title or metadata.get("document_title") or metadata.get("titulo")
            cliente = cliente or metadata.get("cliente_final") or metadata.get("cliente")
            source_file = (
                metadata.get("archivo_nombre")
                or metadata.get("pdf_name")
                or Path(str(metadata.get("source_path") or "")).name
                or Path(str(metadata.get("url") or "")).name
                or "Documento emitido"
            )
            candidates.append(
                {
                    "parent_id": parent_id,
                    "title": title or "Sección sin título",
                    "text": clean_text[:parent_chars],
                    "page_start": page_start,
                    "page_end": page_end,
                    "source_file": source_file,
                    "score": self._parent_relevance(title, clean_text),
                }
            )
        candidates.sort(
            key=lambda item: (-item["score"], -len(item["text"]), str(item["parent_id"]))
        )
        parents = candidates[:max_parents]
        return {
            "parents": parents,
            "document_title": document_title,
            "cliente": cliente,
            "sources": list(dict.fromkeys(parent["source_file"] for parent in parents)),
            "invalid_parent_count": invalid_count,
            "invalid_sources": sorted(invalid_sources)[:12],
        }

    def _master_row(self, codigo: str) -> dict | None:
        try:
            from app.services.master_repository import MasterRepository

            rows = MasterRepository().search(codigo=codigo, limit=1)
            return rows[0] if rows else None
        except Exception:
            return None

    def _format_source_text(self, codigo: str, titulo: str, cliente, estado, tipo, rag: dict) -> str:
        parts = [
            f"Código objetivo: {codigo}",
            f"Título Master: {titulo}",
            f"Cliente Master: {cliente or 'N/D'}",
            f"Estado Master: {estado or 'N/D'}",
            f"Tipo de servicio Master: {tipo or 'N/D'}",
            "",
            "Evidencia extraída de documentos emitidos del mismo código:",
        ]
        for index, parent in enumerate(rag["parents"], start=1):
            pages = ""
            if parent.get("page_start") is not None:
                end = parent.get("page_end") if parent.get("page_end") is not None else parent.get("page_start")
                pages = f", pp. {parent.get('page_start')}-{end}"
            parts.append(
                f"\n## [F{index}] {parent['source_file']}{pages} · {parent['title']}"
            )
            parts.append(parent["text"])
        return "\n".join(parts)

    def _page_markdown(
        self,
        codigo: str,
        titulo: str,
        cliente,
        estado,
        tipo,
        entry: dict,
        draft: dict,
        rag: dict,
    ) -> str:
        from datetime import datetime

        source_files = ", ".join(rag.get("sources") or [])
        return "\n".join(
            [
                "---",
                f"codigo: {codigo}",
                f"titulo: {json.dumps(str(titulo or ''), ensure_ascii=False)}",
                f"cliente: {json.dumps(str(cliente or ''), ensure_ascii=False)}",
                f"estado: {estado or ''}",
                f"tipo_servicio: {json.dumps(str(tipo or ''), ensure_ascii=False)}",
                f"entry_id: {entry.get('id', '')}",
                f"generated_at: {datetime.now().isoformat(timespec='seconds')}",
                "source: rag_autocompile",
                "wiki_schema: evidence-v3",
                f"wiki_quality_score: {draft.get('wiki_quality_score', '')}",
                f"source_files: {json.dumps(source_files, ensure_ascii=False)}",
                "---",
                "",
                f"# {codigo} — {titulo}",
                "",
                f"**Cliente:** {cliente or 'N/D'} · **Estado:** {estado or 'N/D'} · **Tipo:** {tipo or 'N/D'}",
                "",
                entry.get("content", "") or "_Sin contenido compilado._",
            ]
        )

    def _existing_context(self, topic: str, entry_id: str | None) -> dict | None:
        if entry_id:
            try:
                return self.wiki.get_entry(entry_id)
            except KeyError:
                return None
        hits = self.wiki.search(topic, mode="content", limit=3)
        entries = self.wiki.list_entries()
        hit_titles = {hit["path"][2] for hit in hits if len(hit.get("path", [])) >= 3}
        for entry in entries:
            if entry["title"] in hit_titles or self._norm(entry["title"]) == self._norm(topic):
                return entry
        return None

    def _fallback(
        self,
        topic: str,
        source_text: str,
        source_kind: str,
        candidate_codes: list[str],
        existing: dict | None,
    ) -> dict:
        codes = candidate_codes or sorted(self._offer_codes(source_text))
        keywords = [
            token for token in re.findall(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ0-9-]{4,}", topic.lower())
        ][:8]
        evidence = []
        for match in re.finditer(
            r"(?ms)^## \[(F\d+)\] ([^\n]+)\n(.*?)(?=^## \[F\d+\]|\Z)",
            source_text,
        ):
            label, heading, body = match.groups()
            excerpt = " ".join(body.strip().split())[:1600]
            if excerpt:
                evidence.extend([f"### {heading}", f"{excerpt} [{label}]", ""])
            if len(evidence) >= 12:
                break
        content = "\n".join(
            [
                "## Resumen ejecutivo",
                f"Ficha de evidencia documental para **{topic}**. La síntesis IA no estuvo disponible; se preservan extractos trazables del documento.",
                "",
                "## Alcance, entregables y datos identificados",
                *(evidence or ["No se obtuvo texto documental suficiente para identificar alcance o entregables.", ""]),
                "## Evidencia y fuentes",
                "Los extractos anteriores conservan su identificador [F#] para volver al archivo y sección de origen.",
                "",
                "## Vacíos de información",
                "Los campos no presentes en los extractos deben tratarse como no identificados; no se infieren desde el título.",
            ]
        )
        return {
            "title": existing.get("title") if existing else topic.strip()[:120],
            "category": existing.get("category") if existing else "propuesta",
            "tags": list(dict.fromkeys([*keywords, *[code.lower() for code in codes[:5]]]))[:12],
            "operational_value": True,
            "content": content,
            "rag_quality_score": min(80, 30 + len(source_text) // 700),
            "wiki_quality_score": 52 if evidence else 15,
            "quality_summary": "Fallback extractivo trazable; la síntesis IA no estuvo disponible.",
            "quality_issues": [
                "Reprocesar con IA para sintetizar alcance, entregables y condiciones sin perder citas."
            ],
            "quality_mode": "heuristic",
        }

    def _quality_gate(
        self,
        draft: dict,
        fallback: dict,
        source_text: str,
        candidate_codes: list[str],
    ) -> dict:
        content = str(draft.get("content") or "").strip()
        normalized = self._norm(content)
        required = ("resumen", "alcance", "entregables", "evidencia", "vacios")
        sections = sum(1 for name in required if name in normalized)
        citations = len(
            re.findall(r"\[F\d+(?:,\s*pp?\.[^\]]+)?\]", content, flags=re.IGNORECASE)
        )
        allowed_codes = self._offer_codes(source_text) | {
            code for code in (self._canonical_offer_code(value) for value in candidate_codes) if code
        }
        introduced = self._offer_codes(content) - allowed_codes
        banned = any(
            value in normalized for value in ("como usar", "criterios de busqueda", "entidades utiles")
        )
        issues = list(draft.get("quality_issues") or [])
        if len(content) < 700:
            issues.append("Contenido demasiado breve para una ficha técnica.")
        if sections < 4:
            issues.append("Faltan secciones técnicas obligatorias.")
        if citations < 2:
            issues.append("Faltan citas trazables [F#].")
        if introduced:
            issues.append(f"Códigos ajenos no sustentados: {', '.join(sorted(introduced))}.")
        if banned:
            issues.append("Incluye secciones genéricas prohibidas.")
        if len(content) < 700 or sections < 4 or introduced or banned:
            fallback["quality_issues"] = list(
                dict.fromkeys([*fallback.get("quality_issues", []), *issues])
            )[:8]
            fallback["quality_summary"] = (
                "La salida IA no superó el control de evidencia; se usó fallback extractivo."
            )
            return fallback
        if citations < 2:
            draft["wiki_quality_score"] = min(float(draft.get("wiki_quality_score") or 0), 55.0)
        draft["quality_issues"] = list(dict.fromkeys(issues))[:8]
        return draft

    def _source_matches_code(self, codigo: str, metadata: dict) -> tuple[bool, str]:
        meta_code = str(metadata.get("codigo") or metadata.get("proposal_code") or "").strip()
        if meta_code and self._canonical_offer_code(meta_code) != codigo:
            return False, f"metadata:{meta_code}"

        file_identity = " ".join(
            str(metadata.get(key) or "")
            for key in ("archivo_nombre", "pdf_name", "document_title")
        )
        file_codes = self._offer_codes(file_identity)
        if file_codes and codigo not in file_codes:
            return False, file_identity[:240]

        path_identity = " ".join(
            str(metadata.get(key) or "")
            for key in ("url", "web_url", "source_path", "source")
        )
        path_codes = self._offer_codes(path_identity)
        if path_codes and codigo not in path_codes:
            return False, path_identity[:240]
        return True, (file_identity or path_identity)[:240]

    def _parent_relevance(self, title: object, text: object) -> int:
        heading = self._norm(title)
        sample = self._norm(str(text)[:1600])
        score = min(20, len(str(text)) // 500)
        weights = {
            "alcance": 90,
            "entregable": 85,
            "exclusion": 70,
            "supuesto": 65,
            "plazo": 60,
            "cronograma": 60,
            "metodologia": 55,
            "objetivo": 50,
            "responsabilidad": 45,
            "organizacion": 35,
            "equipo": 35,
            "horas": 35,
            "precio": 25,
            "oferta tecnica": 20,
        }
        for token, weight in weights.items():
            if token in heading:
                score += weight
            elif token in sample:
                score += weight // 4
        for token, penalty in {
            "portada": 90,
            "indice": 55,
            "metadata": 50,
            "tabla de contenido": 60,
        }.items():
            if token in heading:
                score -= penalty
        return score

    def _offer_codes(self, value: object) -> set[str]:
        return {
            code
            for code in (
                self._canonical_offer_code(match)
                for match in re.findall(
                    r"\bO\s*-?\s*\d{2,6}\b", str(value or ""), flags=re.IGNORECASE
                )
            )
            if code
        }

    def _canonical_offer_code(self, value: object) -> str | None:
        match = re.search(r"\bO\s*-?\s*(\d{2,6})\b", str(value or ""), flags=re.IGNORECASE)
        return f"O-{int(match.group(1)):04d}" if match else None

    def _score(self, value: object, fallback: object) -> float:
        try:
            return max(0.0, min(100.0, float(value)))
        except (TypeError, ValueError):
            return max(0.0, min(100.0, float(fallback)))

    def _norm(self, value: object) -> str:
        text = unicodedata.normalize("NFKD", str(value or "").casefold())
        return " ".join("".join(ch for ch in text if not unicodedata.combining(ch)).split())
