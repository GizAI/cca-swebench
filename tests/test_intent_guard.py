from __future__ import annotations

from types import SimpleNamespace
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from confucius.core import types as cf
from confucius.core.memory import CfMessage
from confucius.orchestrator.exceptions import OrchestratorInterruption
from confucius.analects.code.intent_guard import IntentOnlyResponseGuard


def _context_with_messages(messages: list[CfMessage]) -> SimpleNamespace:
    memory_manager = SimpleNamespace(memory=SimpleNamespace(messages=messages))
    return SimpleNamespace(memory_manager=memory_manager)


def test_intent_only_detection() -> None:
    guard = IntentOnlyResponseGuard()
    assert guard._looks_intent_only("Let me inspect the repository structure first.")
    assert guard._looks_intent_only("Let me check the repository structure first.")
    assert guard._looks_intent_only("I will inspect the project and report back.")
    assert not guard._looks_intent_only("This repository is an Ark monorepo built on Nuxt.")


def test_requires_action_keywords() -> None:
    guard = IntentOnlyResponseGuard()
    assert guard._requires_action("What is this repository?")
    assert guard._requires_action("Please inspect this repository.")
    assert guard._requires_action("Fix this failing test.")
    assert not guard._requires_action("Hello there")


@pytest.mark.asyncio
async def test_interrupts_once_for_intent_only_without_tool_use() -> None:
    guard = IntentOnlyResponseGuard()
    context = _context_with_messages(
        [CfMessage(type=cf.MessageType.HUMAN, content="What is this repository?")]
    )
    await guard.on_llm_output("Let me inspect the repository structure first.", context)
    with pytest.raises(OrchestratorInterruption):
        await guard.on_process_messages_complete(context)

    # second call should not interrupt again due to max_retries=1
    await guard.on_llm_output("Let me inspect the repository structure first.", context)
    await guard.on_process_messages_complete(context)


@pytest.mark.asyncio
async def test_no_interrupt_when_tool_used() -> None:
    guard = IntentOnlyResponseGuard()
    context = _context_with_messages(
        [CfMessage(type=cf.MessageType.HUMAN, content="What is this repository?")]
    )
    await guard.on_llm_output("Let me inspect the repository structure first.", context)
    await guard.on_before_tool_use(SimpleNamespace(name="bash"), context)
    await guard.on_process_messages_complete(context)
