import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.agents.orchestrator import AgentOrchestrator
from app.schemas import ChatRequest


class AgentRequestTimeoutTests(unittest.IsolatedAsyncioTestCase):
    async def test_slow_agent_returns_recoverable_response(self):
        async def slow_run(**_kwargs):
            await asyncio.sleep(1)

        orchestrator = AgentOrchestrator.__new__(AgentOrchestrator)
        orchestrator._memory = Mock(return_value={"summary": "", "codes": []})
        orchestrator.personal_memory = SimpleNamespace(summary=lambda: "")
        slow_loop = SimpleNamespace(run=slow_run)
        request = ChatRequest(message="Compara en detalle la metodología y los entregables")

        with (
            patch("app.agents.orchestrator.AGENT_REQUEST_TIMEOUT_SECONDS", 0.01),
            patch("app.agents.orchestrator.AgentLoop", return_value=slow_loop),
        ):
            response = await orchestrator.run(request)

        self.assertIn("dividirla", response.answer)
        self.assertEqual(response.trace[-1].tool, "agent.loop")
        self.assertEqual(response.trace[-1].status, "warning")