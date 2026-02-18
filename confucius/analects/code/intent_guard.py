# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-strict
from __future__ import annotations

import re
from typing import Sequence

from pydantic import Field, PrivateAttr

from ...core import types as cf
from ...core.analect.analect import AnalectRunContext
from ...core.chat_models.bedrock.api.invoke_model import anthropic as ant
from ...core.memory import CfMessage
from ...orchestrator.exceptions import OrchestratorInterruption
from ...orchestrator.extensions.tool_use import ToolUseObserver

DEFAULT_INTENT_GUARD_MESSAGE = (
    "Do not end with intent-only statements. "
    "Use available tools now and return concrete findings or a direct final answer in this turn."
)

_INTENT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b(i(?:'ll| will)|let me)\b.{0,96}\b(check|inspect|review|look)\b", re.IGNORECASE),
    re.compile(r"확인해볼게요|확인하겠습니다|살펴보겠습니다|파악해보겠습니다|잠깐만요|검토해볼게요"),
    re.compile(r"저장소 구조를 빠르게 확인"),
)

_ACTION_KEYWORDS: tuple[str, ...] = (
    "repo",
    "repository",
    "codebase",
    "project",
    "readme",
    "structure",
    "file",
    "fix",
    "implement",
    "refactor",
    "debug",
    "analyze",
    "저장소",
    "코드베이스",
    "구조",
    "파일",
    "정체",
    "수정",
    "구현",
    "디버그",
    "분석",
)


class IntentOnlyResponseGuard(ToolUseObserver):
    name: str = "intent_only_response_guard"
    included_in_system_prompt: bool = False
    max_retries: int = Field(
        default=1,
        description="Maximum interruption retries per user turn for intent-only output.",
    )
    interruption_message: str = Field(
        default=DEFAULT_INTENT_GUARD_MESSAGE,
        description="Reminder message injected when intent-only output is detected.",
    )

    _latest_output: str = PrivateAttr(default="")
    _tool_use_count: int = PrivateAttr(default=0)
    _retry_count: int = PrivateAttr(default=0)

    async def on_llm_output(
        self,
        text: str,
        context: AnalectRunContext,  # noqa: ARG002
    ) -> str:
        self._latest_output = text.strip()
        self._tool_use_count = 0
        return text

    async def on_before_tool_use(
        self, tool_use: ant.MessageContentToolUse, context: AnalectRunContext  # noqa: ARG002
    ) -> None:
        self._tool_use_count += 1

    def _last_user_prompt(self, messages: Sequence[CfMessage]) -> str:
        for msg in reversed(messages):
            if msg.type != cf.MessageType.HUMAN:
                continue
            if not isinstance(msg.content, str):
                continue
            content = msg.content.strip()
            if content:
                return content
        return ""

    def _requires_action(self, user_prompt: str) -> bool:
        lowered = user_prompt.lower()
        return any(keyword in lowered for keyword in _ACTION_KEYWORDS)

    def _looks_intent_only(self, text: str) -> bool:
        stripped = text.strip()
        if not stripped:
            return False
        if len(stripped) > 360:
            return False
        return any(pattern.search(stripped) is not None for pattern in _INTENT_PATTERNS)

    async def on_process_messages_complete(self, context: AnalectRunContext) -> None:
        if self._retry_count >= self.max_retries:
            return
        if self._tool_use_count > 0:
            return
        if not self._looks_intent_only(self._latest_output):
            return

        user_prompt = self._last_user_prompt(context.memory_manager.memory.messages)
        if not self._requires_action(user_prompt):
            return

        self._retry_count += 1
        raise OrchestratorInterruption(self.interruption_message)
