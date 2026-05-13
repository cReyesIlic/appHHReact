"""Suite de tests integral para el sistema rediseñado.

Cubre:
  1. SearchFilters (schema, SQL, dict-match)
  2. HybridRagStore (legacy + filtros + filtros vacíos)
  3. ParentChildIndexer
  4. RagStore (legacy)
  5. MasterRepository (legacy + filtros)
  6. EntityIndex
  7. StructuredWikiService (CRUD curado + search_entries + bump_usage + validate)
  8. ToolContext + handlers individuales
  9. AgentLoop con tool calling
 10. Routes API (carga, schema, dispatcher)

Imprime un resumen final con PASS/FAIL por sección.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class TestRunner:
    def __init__(self) -> None:
        self.results: list[tuple[str, str, str]] = []
        self.t0 = time.time()

    def record(self, name: str, status: str, detail: str = "") -> None:
        self.results.append((name, status, detail))
        marker = "PASS" if status == "ok" else ("FAIL" if status == "error" else "WARN")
        line = f"[{marker:>4}] {name}"
        if detail:
            line += f" — {detail[:160]}"
        print(line)

    def run(self, name: str, fn):
        try:
            detail = fn()
            self.record(name, "ok", detail or "")
        except AssertionError as exc:
            self.record(name, "error", f"assertion: {exc}")
        except Exception as exc:  # noqa: BLE001
            self.record(name, "error", f"{type(exc).__name__}: {exc}")
            traceback.print_exc()

    async def run_async(self, name: str, fn):
        try:
            detail = await fn()
            self.record(name, "ok", detail or "")
        except AssertionError as exc:
            self.record(name, "error", f"assertion: {exc}")
        except Exception as exc:  # noqa: BLE001
            self.record(name, "error", f"{type(exc).__name__}: {exc}")
            traceback.print_exc()

    def summary(self) -> int:
        ok = sum(1 for _, s, _ in self.results if s == "ok")
        warn = sum(1 for _, s, _ in self.results if s == "warning")
        err = sum(1 for _, s, _ in self.results if s == "error")
        total = len(self.results)
        print()
        print("=" * 72)
        print(f"TOTAL: {total} | PASS: {ok} | WARN: {warn} | FAIL: {err}  ({time.time()-self.t0:.1f}s)")
        print("=" * 72)
        if err:
            print("FALLOS:")
            for name, status, detail in self.results:
                if status == "error":
                    print(f"  - {name}: {detail}")
        return err


# ----- Test fixtures --------

def fixture_filters_ganada_vale():
    from app.services.search_filters import SearchFilters
    return SearchFilters(estado_categoria=["ganada"], clientes=["VALE"])


def fixture_filters_perdida_relaves():
    from app.services.search_filters import SearchFilters
    return SearchFilters(estado_categoria=["perdida"], procesos_sistemas=["relaves"])


# ----- Section 1: SearchFilters --------

def test_filters_schema(runner: TestRunner) -> None:
    from app.services.search_filters import SearchFilters, valid_estados, valid_categorias

    def t1():
        f = SearchFilters()
        assert f.is_empty()
        assert not f.has_metadata_filters()
        return "vacío detecta empty"

    def t2():
        f = SearchFilters(codigos=["o-1376", "O-1377"], estados="PG")
        assert f.codigos == ["O-1376", "O-1377"]
        assert f.estados == ["PG"]
        return "normaliza upper y string→list"

    def t3():
        f = SearchFilters(estado_categoria=["ganada"], clientes=["VALE"])
        clauses, params = f.sql_clauses("c")
        assert any("estado_categoria" in c for c in clauses)
        assert any("cliente" in c for c in clauses)
        assert "ganada" in params
        return f"{len(clauses)} clauses, {len(params)} params"

    def t4():
        f = SearchFilters(estado_categoria=["ganada"])
        assert f.matches_row_metadata({"estado_categoria": "ganada"}, "O-1")
        assert not f.matches_row_metadata({"estado_categoria": "perdida"}, "O-1")
        return "matches_row_metadata"

    def t5():
        f = SearchFilters.from_codes(["O-1", "O-2"])
        assert f.codigos == ["O-1", "O-2"]
        return "from_codes helper"

    def t6():
        cats = valid_categorias()
        ests = valid_estados()
        assert "ganada" in cats and "perdida" in cats
        assert "PG" in ests and "PP" in ests
        return f"categorias={len(cats)}, estados={len(ests)}"

    runner.run("filters.empty_detect", t1)
    runner.run("filters.normalize", t2)
    runner.run("filters.sql_clauses", t3)
    runner.run("filters.matches_row", t4)
    runner.run("filters.from_codes", t5)
    runner.run("filters.taxonomia_helpers", t6)


# ----- Section 2: RAG stores --------

async def test_hybrid_rag(runner: TestRunner) -> None:
    from app.rag.hybrid_store import HybridRagStore
    from app.services.search_filters import SearchFilters

    store = HybridRagStore()
    status = store.fast_status()
    runner.record(
        "hybrid.status",
        "ok",
        f"chunks={status['embedded_chunks']} | model={status['embedding_model']}",
    )

    async def t_legacy():
        hits = await store.search("barragem", codes=["O-1376"], limit=3)
        assert isinstance(hits, list)
        return f"{len(hits)} hits con codes legacy"

    async def t_filtered():
        f = SearchFilters(estado_categoria=["perdida"], clientes=["VALE"], query="barragem")
        hits = await store.search(f.query, filters=f, limit=3)
        if hits:
            for h in hits:
                meta = h.get("metadata") or {}
                assert meta.get("estado_categoria") == "perdida", f"row {h['codigo']} no es perdida"
                cliente = (meta.get("cliente") or meta.get("cliente_final") or "").upper()
                assert "VALE" in cliente, f"cliente {cliente} no contiene VALE"
        return f"{len(hits)} hits VALE+perdida con filtros aplicados"

    async def t_filter_only():
        f = SearchFilters(estado_categoria=["ganada"], limit=2)
        hits = await store.search("", filters=f, limit=2)
        for h in hits:
            assert (h.get("metadata") or {}).get("estado_categoria") == "ganada"
        return f"{len(hits)} hits solo con filtros, sin query"

    async def t_empty_query_empty_filters():
        hits = await store.search("", filters=None, limit=2)
        assert hits == [] or all((h.get("score") or 0) > 0 for h in hits)
        return f"vacío retorna {len(hits)} (esperado 0)"

    await runner.run_async("hybrid.legacy_codes", t_legacy)
    await runner.run_async("hybrid.with_filters", t_filtered)
    await runner.run_async("hybrid.filter_only_no_query", t_filter_only)
    await runner.run_async("hybrid.empty_safe", t_empty_query_empty_filters)


def test_parent_child(runner: TestRunner) -> None:
    from app.rag.parent_child import ParentChildIndexer
    from app.services.search_filters import SearchFilters

    idx = ParentChildIndexer()
    status = idx.status()
    runner.record(
        "parent_child.status",
        "ok",
        f"parents={status['parent_count']} children={status['child_count']}",
    )

    def t1():
        hits = idx.search("relaves", limit=3)
        assert isinstance(hits, list)
        return f"{len(hits)} hits lexical"

    def t2():
        f = SearchFilters(estado_categoria=["ganada"], query="")
        hits = idx.search("", filters=f, limit=3)
        for h in hits:
            assert h.get("metadata", {}).get("estado_categoria") == "ganada"
        return f"{len(hits)} hits filtros-only"

    runner.run("parent_child.lexical", t1)
    runner.run("parent_child.filters_only", t2)


def test_rag_store(runner: TestRunner) -> None:
    from app.services.rag_store import RagStore
    from app.services.search_filters import SearchFilters

    store = RagStore()

    def t1():
        s = store.status()
        return f"chunks={s['chunk_count']} proposals={s['proposal_count']}"

    def t2():
        hits = store.search("relaves", limit=3)
        return f"{len(hits)} hits"

    def t3():
        f = SearchFilters(codigos=["O-1376"])
        hits = store.search("", filters=f, limit=3)
        return f"{len(hits)} hits con codigos filter"

    runner.run("rag_store.status", t1)
    runner.run("rag_store.legacy", t2)
    runner.run("rag_store.filters", t3)


# ----- Section 3: Master --------

def test_master(runner: TestRunner) -> None:
    from app.services.master_repository import MasterRepository
    from app.services.search_filters import SearchFilters

    repo = MasterRepository()

    def t_count():
        n = repo.count_offers()
        assert n > 0
        return f"{n} ofertas"

    def t_legacy():
        rows = repo.search(query="relaves", limit=3)
        assert isinstance(rows, list)
        return f"{len(rows)} filas legacy"

    def t_codigo():
        rows = repo.search(codigo="O-1376", limit=2)
        if rows:
            assert all(r.get("codigo", "").upper().startswith("O-") for r in rows)
        return f"{len(rows)} fila por código"

    def t_filtered_ganada():
        f = SearchFilters(estado_categoria=["ganada"], clientes=["VALE"])
        rows = repo.search_filtered(f, limit=5)
        for r in rows:
            assert r.get("estado") == "PG", f"esperaba PG, got {r.get('estado')}"
        return f"{len(rows)} ganadas VALE"

    def t_filtered_tipo():
        f = SearchFilters(tipos_servicio=["IP"], limit=3)
        rows = repo.search_filtered(f, limit=3)
        for r in rows:
            assert "IP" in r.get("tipo_servicio", "").upper(), f"esperaba IP en {r.get('tipo_servicio')}"
        return f"{len(rows)} con IP"

    runner.run("master.count", t_count)
    runner.run("master.legacy_search", t_legacy)
    runner.run("master.by_codigo", t_codigo)
    runner.run("master.filtered_ganada_vale", t_filtered_ganada)
    runner.run("master.filtered_tipo", t_filtered_tipo)


# ----- Section 4: Entity index --------

def test_entity_index(runner: TestRunner) -> None:
    from app.services.entity_index import EntityIndex
    from app.services.search_filters import SearchFilters

    idx = EntityIndex()

    def t_status():
        s = idx.status()
        return f"entities={s['entities']} proposals={s['proposal_count']}"

    def t_search():
        hits = idx.search("relaves", limit=10)
        return f"{len(hits)} hits"

    def t_search_filtered():
        f = SearchFilters(estado_categoria=["ganada"])
        hits = idx.search("relaves", limit=10, filters=f)
        return f"{len(hits)} hits con filtros ganada"

    def t_expand():
        terms = idx.expand_query("dewatering")
        return f"expansión = {len(terms)} términos"

    runner.run("entity.status", t_status)
    runner.run("entity.search", t_search)
    runner.run("entity.search_filtered", t_search_filtered)
    runner.run("entity.expand", t_expand)


# ----- Section 5: Wiki librería curada --------

def test_wiki_library(runner: TestRunner) -> None:
    from app.services.structured_wiki import StructuredWikiService

    wiki = StructuredWikiService()

    def t_status():
        s = wiki.status()
        return f"entries={s['entries']} sections={s['sections']}"

    def t_create():
        entry = wiki.upsert_entry(
            title="__test_entry_full_system__",
            content="Lección de prueba sobre dewatering en rajos.",
            category="test",
            tags=["test", "dewatering"],
            propuestas_referenciadas=["O-1376", "O-9999", "O-1377"],
            filtros_aplicables={"clientes": ["VALE"]},
        )
        assert entry["title"] == "__test_entry_full_system__"
        assert entry["propuestas_referenciadas"] == ["O-1376", "O-9999", "O-1377"]
        return f"creada id={entry['id']}"

    def t_search():
        hits = wiki.search_entries(query="dewatering", limit=5)
        titles = [h["title"] for h in hits]
        assert any("__test_entry_full_system__" in t for t in titles), f"no se encontró: {titles}"
        return f"{len(hits)} hits"

    def t_search_codigos():
        hits = wiki.search_entries(codigos=["O-1376"], limit=5)
        return f"{len(hits)} entries que referencian O-1376"

    def t_bump():
        # Encuentra la entry recién creada
        entries = wiki.search_entries(query="__test_entry_full_system__", limit=1)
        assert entries, "no se encontró entrada test"
        before = entries[0]["times_used"]
        wiki.bump_usage(entries[0]["id"])
        after = wiki.get_entry(entries[0]["id"])["times_used"]
        assert after == before + 1
        return f"times_used {before}→{after}"

    def t_validate():
        entries = wiki.search_entries(query="__test_entry_full_system__", limit=1)
        entry_id = entries[0]["id"]
        # Validar contra códigos parciales (O-1376 sí, O-9999 no)
        result = wiki.validate_proposals(entry_id, ["O-1376", "O-1377"])
        assert result["status"] == "partial"
        assert "O-1376" in result["existing"]
        assert "O-9999" in result["missing"]
        return f"status={result['status']} existing={len(result['existing'])} missing={len(result['missing'])}"

    def t_delete():
        entries = wiki.search_entries(query="__test_entry_full_system__", limit=1)
        if entries:
            wiki.delete_entry(entries[0]["id"])
        # Confirmar borrado
        again = wiki.search_entries(query="__test_entry_full_system__", limit=1)
        assert not any(e["title"] == "__test_entry_full_system__" for e in again)
        return "cleanup ok"

    runner.run("wiki.status", t_status)
    runner.run("wiki.create_curated", t_create)
    runner.run("wiki.search_entries", t_search)
    runner.run("wiki.search_by_codigos", t_search_codigos)
    runner.run("wiki.bump_usage", t_bump)
    runner.run("wiki.validate_proposals", t_validate)
    runner.run("wiki.delete_cleanup", t_delete)


# ----- Section 6: Tools handlers individuales --------

async def test_tools(runner: TestRunner) -> None:
    from app.agents.tools import TOOL_SCHEMAS, ToolDispatcher
    from app.agents.tools.handlers import ToolContext

    runner.record("tools.schemas", "ok", f"{len(TOOL_SCHEMAS)} tools registradas")
    expected = {
        "search_master",
        "search_rag",
        "search_proposal_index",
        "search_wiki_entries",
        "search_entities",
        "compute_master_stats",
        "compute_economics",
        "compute_proposal_support",
        "get_proposal_detail",
        "read_pdf_deep",
        "save_library_entry",
    }
    actual = {schema["function"]["name"] for schema in TOOL_SCHEMAS}
    missing = expected - actual
    runner.record(
        "tools.coverage",
        "ok" if not missing else "error",
        f"faltan: {missing}" if missing else f"todas presentes ({len(actual)})",
    )

    ctx = ToolContext.build()
    disp = ToolDispatcher(ctx)

    async def t_search_master():
        result = await disp.dispatch("search_master", {"filters": {"estado_categoria": ["ganada"]}, "limit": 3})
        assert result.get("count", 0) >= 0
        return f"count={result.get('count', 0)}"

    async def t_search_rag():
        result = await disp.dispatch("search_rag", {"query": "relaves", "limit": 2})
        return f"count={result.get('count', 0)}"

    async def t_search_wiki():
        result = await disp.dispatch("search_wiki_entries", {"query": "relaves", "limit": 3})
        return f"count={result.get('count', 0)}"

    async def t_search_entities():
        result = await disp.dispatch("search_entities", {"query": "dewatering", "limit": 5})
        return f"count={result.get('count', 0)}"

    async def t_get_detail():
        result = await disp.dispatch("get_proposal_detail", {"codigo": "O-1376"})
        assert result.get("codigo") == "O-1376"
        return f"master_rows={len(result.get('master_rows', []))} rag={len(result.get('rag_hits', []))}"

    async def t_unknown_tool():
        result = await disp.dispatch("nonexistent_tool", {})
        assert "error" in result
        return "tool desconocido manejado"

    async def t_invalid_args():
        # save_library_entry requiere title + content; sin ellos debe dar error
        result = await disp.dispatch("save_library_entry", {})
        assert "error" in result
        return "args inválidos manejados"

    await runner.run_async("tools.search_master", t_search_master)
    await runner.run_async("tools.search_rag", t_search_rag)
    await runner.run_async("tools.search_wiki_entries", t_search_wiki)
    await runner.run_async("tools.search_entities", t_search_entities)
    await runner.run_async("tools.get_proposal_detail", t_get_detail)
    await runner.run_async("tools.unknown_dispatch", t_unknown_tool)
    await runner.run_async("tools.invalid_args", t_invalid_args)


# ----- Section 7: AgentLoop --------

async def test_agent_loop(runner: TestRunner) -> None:
    from app.agents.agent_loop import AgentLoop
    from app.services.search_filters import SearchFilters

    loop = AgentLoop(max_iterations=4)

    async def t_simple_filter():
        result = await loop.run(
            question="Listame 2 propuestas ganadas de VALE con su código.",
            filters=SearchFilters(clientes=["VALE"], estado_categoria=["ganada"]),
        )
        assert result.answer
        assert any("agent" in t.tool for t in result.trace)
        # Idealmente llamó search_master
        called = [t.tool for t in result.trace if t.status == "ok" and "agent." in t.tool]
        assert any("search_master" in c for c in called) or any("get_proposal_detail" in c for c in called)
        return f"answer={len(result.answer)}c trace={len(result.trace)} codes={len(result.suggested_codes)}"

    async def t_no_filter_freeform():
        result = await loop.run(
            question="¿Cuántas propuestas hay en total en master?",
        )
        assert result.answer
        return f"answer={len(result.answer)}c trace={len(result.trace)}"

    async def t_with_history():
        from app.schemas import ChatMessage
        history = [
            ChatMessage(role="user", content="Hablemos de relaves"),
            ChatMessage(role="assistant", content="Claro, ¿qué quieres saber?"),
        ]
        result = await loop.run(question="Dime una propuesta perdida sobre eso.", history=history)
        return f"answer={len(result.answer)}c"

    await runner.run_async("agent.simple_filter", t_simple_filter)
    await runner.run_async("agent.no_filter_freeform", t_no_filter_freeform)
    await runner.run_async("agent.with_history", t_with_history)


# ----- Section 8: Orchestrator --------

async def test_orchestrator(runner: TestRunner) -> None:
    from app.agents.orchestrator import AgentOrchestrator
    from app.schemas import ChatRequest
    from app.services.search_filters import SearchFilters

    orch = AgentOrchestrator()

    async def t_basic():
        req = ChatRequest(message="Dame 1 propuesta perdida de VALE.", filters=SearchFilters(clientes=["VALE"], estado_categoria=["perdida"]))
        resp = await orch.run(req)
        assert resp.answer
        return f"answer={len(resp.answer)}c suggested={len(resp.suggested_codes)} trace={len(resp.trace)}"

    async def t_no_filters():
        req = ChatRequest(message="Qué tipos de servicio hay en SHIMIN?")
        resp = await orch.run(req)
        return f"answer={len(resp.answer)}c"

    await runner.run_async("orchestrator.with_filters", t_basic)
    await runner.run_async("orchestrator.no_filters", t_no_filters)


# ----- Section 9: API routes --------

def test_api_routes(runner: TestRunner) -> None:
    from app.api.routes import router

    paths = sorted({r.path for r in router.routes if hasattr(r, "path")})
    must = ["/chat", "/master/search", "/library/search", "/search/filter-options", "/wiki/entries/{entry_id}/validate", "/wiki/entries"]
    missing = [p for p in must if p not in paths]
    runner.record(
        "api.routes_present",
        "ok" if not missing else "error",
        f"total={len(paths)} faltan={missing}",
    )

    # Schemas
    from app.schemas import ChatRequest, MasterSearchRequest, WikiEntryRequest, WikiValidateRequest

    def t_chat_schema():
        req = ChatRequest(message="hola", filters={"clientes": ["VALE"]})
        assert req.filters.clientes == ["VALE"]
        return "ChatRequest acepta filters"

    def t_master_schema():
        req = MasterSearchRequest(query="x", filters={"estado_categoria": ["ganada"]})
        assert req.filters.estado_categoria == ["ganada"]
        return "MasterSearchRequest acepta filters"

    def t_wiki_schema():
        req = WikiEntryRequest(title="t", content="c", propuestas_referenciadas=["O-1"])
        assert req.propuestas_referenciadas == ["O-1"]
        return "WikiEntryRequest extendido"

    runner.run("api.chat_schema", t_chat_schema)
    runner.run("api.master_schema", t_master_schema)
    runner.run("api.wiki_schema", t_wiki_schema)


# ----- Section 10: SQL index integrity --------

def test_sql_indexes(runner: TestRunner) -> None:
    from app.core.config import settings

    def t():
        with sqlite3.connect(settings.sqlite_path, timeout=5) as conn:
            rows = conn.execute(
                "select name from sqlite_master where type='index' and name like 'idx_%meta%'"
            ).fetchall()
        names = [r[0] for r in rows]
        expected = ["idx_child_meta_estado", "idx_child_meta_categoria", "idx_parent_meta_estado"]
        for e in expected:
            assert e in names, f"falta índice {e}"
        return f"{len(names)} índices de metadata"

    runner.run("sql.metadata_indexes", t)


# ----- Main --------

async def main() -> int:
    runner = TestRunner()
    print("=" * 72)
    print("Suite de tests integral — sistema SHIMIN rediseñado")
    print("=" * 72)
    print()

    print("\n--1. SearchFilters")
    test_filters_schema(runner)

    print("\n--2. SQL indexes")
    test_sql_indexes(runner)

    print("\n--3. RAG hybrid store")
    await test_hybrid_rag(runner)

    print("\n--4. RAG parent-child")
    test_parent_child(runner)

    print("\n--5. RAG store (legacy)")
    test_rag_store(runner)

    print("\n--6. Master repository")
    test_master(runner)

    print("\n--7. Entity index")
    test_entity_index(runner)

    print("\n--8. Wiki librería curada")
    test_wiki_library(runner)

    print("\n--9. Tools (registry + dispatcher + handlers)")
    await test_tools(runner)

    print("\n--10. AgentLoop (tool calling)")
    await test_agent_loop(runner)

    print("\n--11. Orchestrator")
    await test_orchestrator(runner)

    print("\n--12. API routes y schemas")
    test_api_routes(runner)

    return runner.summary()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
