import base64
import asyncio
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from fastapi import HTTPException
from starlette.requests import Request

from app.agents.agent_loop import AgentLoop
from app.agents.tools.handlers import get_hh_licitadas
from app.core.config import settings
from app.schemas import Source
from app.services.chat_sessions import ChatSessionService
from app.services.user_context import user_from_request


def _request(principal: dict | None = None, *, raw_header: str | None = None) -> Request:
    headers: list[tuple[bytes, bytes]] = []
    if principal is not None:
        raw_header = base64.b64encode(json.dumps(principal).encode("utf-8")).decode("ascii")
    if raw_header is not None:
        headers.append((b"x-ms-client-principal", raw_header.encode("ascii")))
    return Request(
        {
            "type": "http",
            "method": "GET",
            "scheme": "https",
            "path": "/api/me",
            "raw_path": b"/api/me",
            "query_string": b"",
            "headers": headers,
            "client": ("203.0.113.10", 12345),
            "server": ("test", 443),
        }
    )


class IdentityTests(unittest.TestCase):
    def auth_settings(self):
        return patch.multiple(
            settings,
            auth_required=True,
            auth_allow_local_dev=False,
            auth_allowed_email_domains="shimin.cl",
            auth_admin_emails="cristian.reyes@shimin.cl",
        )

    def test_missing_or_malformed_identity_is_rejected(self):
        with self.auth_settings():
            with self.assertRaises(HTTPException) as missing:
                user_from_request(_request())
            self.assertEqual(missing.exception.status_code, 401)

            with self.assertRaises(HTTPException) as malformed:
                user_from_request(_request(raw_header="not-base64"))
            self.assertEqual(malformed.exception.status_code, 401)

    def test_swa_identity_is_verified_and_admin_is_explicit(self):
        principal = {
            "identityProvider": "aad",
            "userId": "entra-object-id",
            "userDetails": "Cristian.Reyes@SHIMIN.cl",
            "userRoles": ["anonymous", "authenticated"],
        }
        with self.auth_settings():
            user = user_from_request(_request(principal))
        self.assertEqual(user.id, "cristian.reyes@shimin.cl")
        self.assertEqual(user.email, "cristian.reyes@shimin.cl")
        self.assertEqual(user.role, "admin")
        self.assertEqual(user.aliases, ("entra-object-id",))

    def test_non_company_domain_is_rejected(self):
        principal = {
            "identityProvider": "aad",
            "userDetails": "persona@example.com",
            "userRoles": ["authenticated"],
        }
        with self.auth_settings(), self.assertRaises(HTTPException) as denied:
            user_from_request(_request(principal))
        self.assertEqual(denied.exception.status_code, 403)

    def test_app_service_claims_format_is_supported(self):
        principal = {
            "auth_typ": "aad",
            "role_typ": "roles",
            "claims": [
                {"typ": "preferred_username", "val": "persona@shimin.cl"},
                {"typ": "name", "val": "Persona SHIMIN"},
                {"typ": "roles", "val": "authenticated"},
            ],
        }
        with self.auth_settings():
            user = user_from_request(_request(principal))
        self.assertEqual(user.id, "persona@shimin.cl")
        self.assertEqual(user.name, "Persona SHIMIN")
        self.assertEqual(user.role, "user")


class ChatIsolationTests(unittest.TestCase):
    def test_verified_legacy_alias_restores_sessions_and_messages(self):
        with tempfile.TemporaryDirectory() as temp_dir, patch.object(
            settings, "database_dir", str(Path(temp_dir) / "aliases.sqlite")
        ):
            service = ChatSessionService()
            session = service.create_session("entra-object-id", "Conversacion anterior")
            service.append_message("entra-object-id", session["id"], "user", "mensaje conservado")

            result = service.adopt_aliases("owner@shimin.cl", ("entra-object-id",))

            self.assertEqual(result, {"sessions": 1, "messages": 1})
            self.assertEqual(service.list_sessions("entra-object-id"), [])
            restored = service.list_sessions("owner@shimin.cl")
            self.assertEqual(restored[0]["id"], session["id"])
            self.assertEqual(
                service.list_messages("owner@shimin.cl", session["id"])[0]["content"],
                "mensaje conservado",
            )

    def test_sessions_and_messages_are_isolated_by_verified_user(self):
        with tempfile.TemporaryDirectory() as temp_dir, patch.object(
            settings, "database_dir", str(Path(temp_dir) / "chat.sqlite")
        ):
            service = ChatSessionService()
            session_a = service.create_session("a@shimin.cl")
            session_b = service.create_session("b@shimin.cl")
            service.append_message("a@shimin.cl", session_a["id"], "user", "mensaje A")
            service.append_message("b@shimin.cl", session_b["id"], "user", "mensaje B")

            self.assertEqual([s["id"] for s in service.list_sessions("a@shimin.cl")], [session_a["id"]])
            self.assertEqual(service.list_messages("a@shimin.cl", session_a["id"])[0]["content"], "mensaje A")

            for operation in (
                lambda: service.get_session("a@shimin.cl", session_b["id"]),
                lambda: service.list_messages("a@shimin.cl", session_b["id"]),
                lambda: service.append_message("a@shimin.cl", session_b["id"], "user", "intrusión"),
                lambda: service.update_working_context("a@shimin.cl", session_b["id"], {"x": 1}),
                lambda: service.delete_session("a@shimin.cl", session_b["id"]),
            ):
                with self.assertRaises(KeyError):
                    operation()

            self.assertEqual(service.list_messages("b@shimin.cl", session_b["id"])[0]["content"], "mensaje B")
            service.delete_session("a@shimin.cl", session_a["id"])
            self.assertEqual(service.list_sessions("a@shimin.cl"), [])
            self.assertEqual(len(service.list_messages("b@shimin.cl", session_b["id"])), 1)

    def test_legacy_messages_are_backfilled_with_session_owner(self):
        with tempfile.TemporaryDirectory() as temp_dir, patch.object(
            settings, "database_dir", str(Path(temp_dir) / "legacy.sqlite")
        ):
            settings.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
            with closing(sqlite3.connect(settings.sqlite_path)) as conn, conn:
                conn.executescript(
                    """
                    create table chat_sessions (
                        id text primary key, user_id text not null, title text not null,
                        created_at text not null, updated_at text not null, last_message_at text,
                        message_count integer default 0, working_context text default '{}'
                    );
                    create table chat_messages (
                        id integer primary key autoincrement, session_id text not null,
                        role text not null, content text not null, trace text default '[]',
                        sources text default '[]', tables text default '[]', created_at text not null
                    );
                    insert into chat_sessions values (
                        'legacy-session', 'owner@shimin.cl', 'Legacy', '2026-01-01',
                        '2026-01-01', null, 1, '{}'
                    );
                    insert into chat_messages
                        (session_id, role, content, created_at)
                    values ('legacy-session', 'user', 'mensaje heredado', '2026-01-01');
                    """
                )

            service = ChatSessionService()
            messages = service.list_messages("owner@shimin.cl", "legacy-session")
            self.assertEqual(messages[0]["content"], "mensaje heredado")
            with closing(sqlite3.connect(settings.sqlite_path)) as conn:
                owner = conn.execute("select user_id from chat_messages").fetchone()[0]
            self.assertEqual(owner, "owner@shimin.cl")


class AgentEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.loop = AgentLoop.__new__(AgentLoop)

    def test_bad_o1779_answer_requires_same_turn_rag_and_pdf_followup(self):
        bad_answer = (
            "Horas estimadas por entregable: no disponibles. "
            "El siguiente paso sería buscar la tabla en el PDF. Si quieres, lo busco ahora."
        )
        self.assertTrue(
            self.loop._needs_evidence_followup(
                "¿Cuántas HH por entregable tiene O-1779?", bad_answer, {"get_proposal_detail"}
            )
        )
        self.assertFalse(
            self.loop._needs_evidence_followup(
                "¿Cuántas HH por entregable tiene O-1779?",
                bad_answer,
                {"search_rag", "read_pdf_deep"},
            )
        )
        self.assertTrue(
            self.loop._needs_licitada_lookup(
                "¿Tienes las horas estimadas por entregable en O-1779?", set()
            )
        )
        self.assertFalse(
            self.loop._needs_licitada_lookup(
                "¿Tienes las horas estimadas por entregable en O-1779?",
                {"get_hh_licitadas"},
            )
        )
        self.assertEqual(
            self.loop._required_full_detail_call(
                "Dame el detalle de la propuesta O-1779", "O-1779", set()
            )[0],
            "get_proposal_detail",
        )
        self.assertEqual(
            self.loop._required_full_detail_call(
                "Dame el detalle de la propuesta O-1779",
                "O-1779",
                {"get_proposal_detail"},
            )[0],
            "get_hh_licitadas",
        )

    def test_nested_wiki_rag_and_pdf_sources_keep_clickable_links(self):
        sources: list[Source] = []
        seen_codes: list[str] = []
        self.loop._collect_payload(
            "get_proposal_detail",
            {
                "codigo": "O-1779",
                "rag_hits": [
                    {
                        "codigo": "O-1779",
                        "title": "Propuesta O-1779.pdf",
                        "url": "https://sharepoint.example/O-1779.pdf",
                        "score": 0.92,
                    }
                ],
                "wiki_entries": [{"id": "wiki-o1779", "title": "O-1779"}],
            },
            sources,
            [],
            [],
            seen_codes,
        )
        self.loop._collect_payload(
            "read_pdf_deep",
            {
                "codigo": "O-1779",
                "contexts": [
                    {
                        "pdf_name": "Oferta O-1779.pdf",
                        "url": "https://sharepoint.example/O-1779-deep.pdf",
                        "text": "Tabla de entregables",
                    }
                ],
            },
            sources,
            [],
            [],
            seen_codes,
        )

        self.assertIn("O-1779", seen_codes)
        self.assertTrue(any(s.entry_id == "wiki-o1779" for s in sources))
        self.assertTrue(any(s.url == "https://sharepoint.example/O-1779-deep.pdf" for s in sources))
        answer = self.loop._append_source_links("Respuesta cerrada.", sources)
        self.assertIn("[Oferta O-1779.pdf](https://sharepoint.example/O-1779-deep.pdf)", answer)
        self.assertIsNone(self.loop._clickable_url(r"C:\storage\O-1779.pdf"))

    def test_run_forces_licitada_detail_and_source_link_before_closing(self):
        loop = AgentLoop.__new__(AgentLoop)
        loop.max_iterations = 3
        loop.skill_registry = Mock()
        loop.skill_registry.catalog.return_value = ""
        loop.llm = Mock(client=object(), azure=False)
        loop.llm.chat_with_tools = AsyncMock(
            side_effect=[
                SimpleNamespace(
                    tool_calls=[],
                    content="No veo las HH por entregable. Si quieres, reviso el PDF.",
                ),
                SimpleNamespace(
                    tool_calls=[],
                    content="La revisión completa encontró la tabla solicitada.",
                ),
            ]
        )

        dispatcher = Mock()

        async def dispatch(name, args):
            if name == "get_hh_licitadas":
                return {
                    "codigo": "O-1779",
                    "available_rows": 11,
                    "totals": {"rows": 11, "total_hours": 895},
                    "rows": [
                        {
                            "key": "Informe final",
                            "codigo_proyecto": "O-1779",
                            "total_hours": 52,
                        }
                    ],
                    "source_assets": [
                        {
                            "codigo": "O-1779",
                            "title": "O-1779.pdf",
                            "url": "https://sharepoint.example/O-1779.pdf",
                        }
                    ],
                }
            raise AssertionError(name)

        dispatcher.dispatch = AsyncMock(side_effect=dispatch)
        with patch("app.agents.agent_loop.ToolContext.build", return_value=object()), patch(
            "app.agents.agent_loop.ToolDispatcher", return_value=dispatcher
        ):
            result = asyncio.run(loop.run("Busca las HH por entregable de O-1779"))

        self.assertEqual(
            [call.args[0] for call in dispatcher.dispatch.await_args_list],
            ["get_hh_licitadas"],
        )
        self.assertIn("https://sharepoint.example/O-1779.pdf", result.answer)
        self.assertEqual(result.answer.count("https://sharepoint.example/O-1779.pdf"), 1)
        self.assertTrue(any(source.url for source in result.sources))

    def test_empty_licitada_detail_falls_back_to_exact_rag_and_pdf(self):
        loop = AgentLoop.__new__(AgentLoop)
        loop.max_iterations = 3
        loop.skill_registry = Mock()
        loop.skill_registry.catalog.return_value = ""
        loop.llm = Mock(client=object(), azure=False)
        loop.llm.chat_with_tools = AsyncMock(
            side_effect=[
                SimpleNamespace(tool_calls=[], content="No tengo el desglose."),
                SimpleNamespace(tool_calls=[], content="No se encontró en el Excel."),
                SimpleNamespace(tool_calls=[], content="La revisión del PDF terminó."),
            ]
        )
        dispatcher = Mock()

        async def dispatch(name, args):
            if name == "get_hh_licitadas":
                return {"codigo": "O-9999", "available_rows": 0, "rows": []}
            if name == "search_rag":
                return {"hits": []}
            if name == "read_pdf_deep":
                return {"codigo": "O-9999", "contexts": []}
            raise AssertionError(name)

        dispatcher.dispatch = AsyncMock(side_effect=dispatch)
        with patch("app.agents.agent_loop.ToolContext.build", return_value=object()), patch(
            "app.agents.agent_loop.ToolDispatcher", return_value=dispatcher
        ):
            result = asyncio.run(loop.run("HH estimadas por entregable de O-9999"))

        self.assertEqual(
            [call.args[0] for call in dispatcher.dispatch.await_args_list],
            ["get_hh_licitadas", "search_rag", "read_pdf_deep"],
        )
        self.assertEqual(result.answer, "La revisión del PDF terminó.")

    def test_full_proposal_detail_combines_document_and_licitada_tools(self):
        loop = AgentLoop.__new__(AgentLoop)
        loop.max_iterations = 3
        loop.skill_registry = Mock()
        loop.skill_registry.catalog.return_value = ""
        loop.llm = Mock(client=object(), azure=False)
        loop.llm.chat_with_tools = AsyncMock(
            side_effect=[
                SimpleNamespace(tool_calls=[], content="Resumen comercial."),
                SimpleNamespace(tool_calls=[], content="Ficha documental."),
                SimpleNamespace(tool_calls=[], content="Ficha completa con HH por partida."),
            ]
        )
        dispatcher = Mock()

        async def dispatch(name, args):
            if name == "get_proposal_detail":
                return {
                    "codigo": "O-1779",
                    "master_rows": [{"codigo": "O-1779", "titulo": "Restitución"}],
                    "rag_hits": [{"codigo": "O-1779", "title": "Alcance", "summary": "Alcance"}],
                    "wiki_entries": [{"id": "wiki-o1779", "title": "O-1779"}],
                }
            if name == "get_hh_licitadas":
                return {
                    "codigo": "O-1779",
                    "rows": [{"codigo_proyecto": "O-1779", "key": "Informe", "total_hours": 52}],
                    "available_rows": 1,
                    "totals": {"total_hours": 52},
                }
            raise AssertionError(name)

        dispatcher.dispatch = AsyncMock(side_effect=dispatch)
        with patch("app.agents.agent_loop.ToolContext.build", return_value=object()), patch(
            "app.agents.agent_loop.ToolDispatcher", return_value=dispatcher
        ):
            result = asyncio.run(loop.run("Dame el detalle de la propuesta O-1779"))

        self.assertEqual(
            [call.args[0] for call in dispatcher.dispatch.await_args_list],
            ["get_proposal_detail", "get_hh_licitadas"],
        )
        self.assertEqual(result.answer, "Ficha completa con HH por partida.")

    def test_licitada_tool_exposes_rows_table_and_sharepoint_assets(self):
        ctx = Mock()
        ctx.entregables.aggregate_licitadas.return_value = {
            "source": "licitadas",
            "view": "entregable",
            "rows": [
                {
                    "key": "Informe final",
                    "total_hours": 52,
                    "roles": {"jp": 8, "esp": 44},
                }
            ],
            "available_rows": 1,
            "totals": {"rows": 1, "total_hours": 52},
        }
        ctx.sharepoint.list_emitido_files = AsyncMock(
            return_value=[
                {
                    "name": "O-1779.xlsx",
                    "kind": "xlsx",
                    "webUrl": "https://sharepoint.example/O-1779.xlsx",
                }
            ]
        )

        result = asyncio.run(get_hh_licitadas(ctx, "O-1779", view="entregable"))

        self.assertEqual(result["totals"]["total_hours"], 52)
        self.assertEqual(result["source_assets"][0]["url"], "https://sharepoint.example/O-1779.xlsx")
        self.assertEqual(result["tables"][0]["rows"][0]["roles"], "JP: 8, ESP: 44")

    def test_licitada_tool_processes_sharepoint_excel_when_local_detail_is_missing(self):
        ctx = Mock()
        ctx.entregables.aggregate_licitadas.side_effect = [
            {
                "source": "licitadas",
                "view": "entregable",
                "rows": [],
                "available_rows": 0,
                "totals": {"rows": 0, "total_hours": 0},
            },
            {
                "source": "licitadas",
                "view": "entregable",
                "rows": [{"key": "Plano", "total_hours": 20, "roles": {"ib": 20}}],
                "available_rows": 1,
                "totals": {"rows": 1, "total_hours": 20},
            },
        ]
        excel = {
            "name": "O-9999.xlsx",
            "kind": "xlsx",
            "webUrl": "https://sharepoint.example/O-9999.xlsx",
            "lastModifiedDateTime": "2026-07-22T12:00:00Z",
        }
        ctx.sharepoint.list_emitido_files = AsyncMock(return_value=[excel])
        ctx.sharepoint.download_file = AsyncMock(return_value=b"excel")
        ctx.budget_extractor.available = True
        ctx.budget_extractor.extract_normalized = AsyncMock(
            return_value={"proyecto_filas": [{"descripcion": "Plano", "hh": 20}]}
        )
        ctx.budget_extractor.persist.return_value = {"proyecto_filas": 1}

        result = asyncio.run(get_hh_licitadas(ctx, "O-9999", view="entregable"))

        self.assertEqual(result["available_rows"], 1)
        self.assertEqual(result["totals"]["total_hours"], 20)
        self.assertEqual(result["excel_refresh"][0]["file"], "O-9999.xlsx")
        ctx.budget_extractor.persist.assert_called_once()


if __name__ == "__main__":
    unittest.main()
