import json
import re
import sqlite3
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

    async def _draft(self, topic: str, source_text: str, source_kind: str, candidate_codes: list[str], existing: dict | None) -> dict:
        fallback = self._fallback(topic, source_text, source_kind, candidate_codes, existing)
        if not self.llm.client:
            return fallback
        try:
            content = await self.llm._chat(
                deployment=settings.index_deployment if self.llm.azure else "gpt-4o-mini",
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Compila conocimiento reutilizable para un LLM Wiki de propuestas de ingenieria SHIMIN. "
                            "No copies la respuesta completa: sintetiza reglas, entidades, criterios y gaps. "
                            "Devuelve solo JSON con keys: title, category, tags, operational_value, content. "
                            "content debe ser Markdown con secciones: Resumen, Como usar, Entidades utiles, "
                            "Propuestas o referencias, Criterios de busqueda, Gaps a validar. "
                            "Distingue evidencia de inferencia y conserva codigos O-XXXX si existen."
                        ),
                    },
                    {
                        "role": "user",
                        "content": json.dumps(
                            {
                                "topic": topic,
                                "source_kind": source_kind,
                                "candidate_codes": candidate_codes,
                                "existing_entry": existing,
                                "source_text": source_text[:14000],
                            },
                            ensure_ascii=False,
                        ),
                    },
                ],
                max_completion_tokens=4096,
                response_format={"type": "json_object"},
            )
            data = json.loads(content)
            return {
                "title": str(data.get("title") or fallback["title"])[:120],
                "category": str(data.get("category") or fallback["category"])[:80],
                "tags": [str(tag).strip() for tag in data.get("tags", fallback["tags"]) if str(tag).strip()][:12],
                "operational_value": bool(data.get("operational_value", fallback["operational_value"])),
                "content": str(data.get("content") or fallback["content"]),
            }
        except Exception:
            return fallback

    async def compile_for_proposal(self, codigo: str, force: bool = False) -> dict:
        """Compila una entrada Wiki para una propuesta, usando los chunks RAG ya indexados.

        - Si la página ya existe (`storage/llm_wiki/proposals/{codigo}.md`) y `force=False`, skip.
        - Toma metadata del master + título de la propuesta + 3-5 secciones (parents) más representativas.
        - Llama LLM con el material como `source_text`; el resultado se guarda como entrada
          Wiki + página markdown en `storage/llm_wiki/proposals/`.
        - Idempotente. Devuelve {'codigo', 'status': 'ok'|'skipped'|'no_rag'|'error', ...}.
        """
        codigo_upper = str(codigo).strip().upper()
        if not codigo_upper.startswith("O-"):
            return {"codigo": codigo, "status": "error", "error": "codigo inválido"}

        proposals_dir = settings.resolve_path("storage/llm_wiki/proposals")
        proposals_dir.mkdir(parents=True, exist_ok=True)
        target_file = proposals_dir / f"{codigo_upper}.md"
        if target_file.exists() and not force:
            return {"codigo": codigo_upper, "status": "skipped", "reason": "ya existe", "path": str(target_file)}

        rag_payload = self._collect_rag_material(codigo_upper)
        if not rag_payload["parents"]:
            return {"codigo": codigo_upper, "status": "no_rag", "reason": "sin chunks RAG indexados"}

        master_row = self._master_row(codigo_upper)
        titulo = (master_row or {}).get("titulo") or rag_payload.get("document_title") or codigo_upper
        cliente = (master_row or {}).get("cliente_final") or (master_row or {}).get("cliente_directo") or rag_payload.get("cliente")
        estado = (master_row or {}).get("estado")
        tipo_servicio = (master_row or {}).get("tipo_servicio")

        topic = f"{codigo_upper} — {titulo}"
        source_text = self._format_source_text(codigo_upper, titulo, cliente, estado, tipo_servicio, rag_payload)

        # Path corto: NO buscar "existing" (los archivos faltantes son por definición nuevos).
        # Esto evita el _sync_entries_from_files de 646 .md que satura SQLite con concurrency.
        draft = await self._draft(topic, source_text, "rag_autocompile", [codigo_upper], existing=None)
        filtros = {}
        if estado:
            filtros["estados"] = [estado]
        if tipo_servicio and tipo_servicio != "No data":
            filtros["tipos_servicio"] = [tipo_servicio.split(",")[0].strip()]
        if cliente and cliente != "No data":
            filtros["clientes"] = [cliente]

        entry = self.wiki.upsert_entry(
            title=str(draft.get("title") or topic)[:120],
            content=str(draft.get("content") or ""),
            category=str(draft.get("category") or "propuesta")[:80],
            tags=draft.get("tags", []),
            pinned=False,
            source="rag_autocompile",
            propuestas_referenciadas=[codigo_upper],
            filtros_aplicables=filtros,
            skip_reindex=True,
        )

        page_md = self._page_markdown(codigo_upper, titulo, cliente, estado, tipo_servicio, entry)
        target_file.write_text(page_md, encoding="utf-8")

        return {
            "codigo": codigo_upper,
            "status": "ok",
            "entry_id": entry.get("id"),
            "path": str(target_file),
            "title": titulo,
        }

    def _collect_rag_material(self, codigo: str, max_parents: int = 4, parent_chars: int = 1800) -> dict:
        """Lee hasta `max_parents` secciones más representativas de `rag_parent_sections`."""
        with sqlite3.connect(settings.sqlite_path, timeout=5) as conn:
            rows = conn.execute(
                """
                select parent_id, title, text, page_start, page_end, metadata
                from rag_parent_sections
                where codigo = ?
                order by length(text) desc
                """,
                (codigo,),
            ).fetchall()
        parents = []
        document_title = None
        cliente = None
        for parent_id, title, text, page_start, page_end, meta_json in rows[: max_parents * 3]:
            try:
                meta = json.loads(meta_json or "{}")
            except json.JSONDecodeError:
                meta = {}
            document_title = document_title or meta.get("document_title") or meta.get("titulo")
            cliente = cliente or meta.get("cliente_final") or meta.get("cliente")
            parents.append(
                {
                    "title": title,
                    "text": (text or "")[:parent_chars],
                    "page_start": page_start,
                    "page_end": page_end,
                }
            )
            if len(parents) >= max_parents:
                break
        return {"parents": parents, "document_title": document_title, "cliente": cliente}

    def _master_row(self, codigo: str) -> dict | None:
        try:
            from app.services.master_repository import MasterRepository
            rows = MasterRepository().search(codigo=codigo, limit=1)
            return rows[0] if rows else None
        except Exception:
            return None

    def _format_source_text(self, codigo: str, titulo: str, cliente, estado, tipo, rag: dict) -> str:
        parts = [
            f"Codigo: {codigo}",
            f"Titulo: {titulo}",
            f"Cliente: {cliente or 'N/D'}",
            f"Estado: {estado or 'N/D'}",
            f"Tipo de servicio: {tipo or 'N/D'}",
            "",
            "Secciones más representativas (parents) extraídas del RAG:",
        ]
        for idx, parent in enumerate(rag["parents"], start=1):
            parts.append(f"\n## Sección {idx}: {parent['title']}")
            if parent.get("page_start"):
                parts.append(f"(páginas {parent.get('page_start')}–{parent.get('page_end')})")
            parts.append(parent["text"])
        return "\n".join(parts)

    def _page_markdown(self, codigo: str, titulo: str, cliente, estado, tipo, entry: dict) -> str:
        from datetime import datetime
        return "\n".join(
            [
                "---",
                f"codigo: {codigo}",
                f"titulo: {titulo}",
                f"cliente: {cliente or ''}",
                f"estado: {estado or ''}",
                f"tipo_servicio: {tipo or ''}",
                f"entry_id: {entry.get('id', '')}",
                f"generated_at: {datetime.now().isoformat(timespec='seconds')}",
                f"source: rag_autocompile",
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

    def _fallback(self, topic: str, source_text: str, source_kind: str, candidate_codes: list[str], existing: dict | None) -> dict:
        codes = candidate_codes or re.findall(r"\bO-\d{3,4}\b", source_text.upper())
        keywords = [token for token in re.findall(r"[a-zA-ZáéíóúÁÉÍÓÚñÑ0-9-]{4,}", topic.lower())][:8]
        content = "\n".join(
            [
                "## Resumen",
                f"Entrada compilada automaticamente desde {source_kind} para: {topic}.",
                "",
                "## Como usar",
                "Usar esta entrada como contexto intermedio entre Planilla Master y RAG. Validar evidencia antes de citar en propuesta.",
                "",
                "## Entidades utiles",
                ", ".join(keywords) or "No detectadas.",
                "",
                "## Propuestas o referencias",
                ", ".join(dict.fromkeys(codes)) or "No se detectaron codigos de oferta.",
                "",
                "## Criterios de busqueda",
                "Buscar coincidencias directas, comparables y metodologicas. Separar evidencia de inferencia.",
                "",
                "## Gaps a validar",
                "Confirmar PDF emitido, estado de propuesta, alcance, entregables, HH y tarifas antes de uso comercial.",
            ]
        )
        return {
            "title": existing.get("title") if existing else topic.strip()[:120],
            "category": existing.get("category") if existing else "auto_compilado",
            "tags": list(dict.fromkeys([*keywords, *[code.lower() for code in codes[:5]]]))[:12],
            "operational_value": True,
            "content": content,
        }

    def _norm(self, value: object) -> str:
        return " ".join(str(value or "").lower().split())
