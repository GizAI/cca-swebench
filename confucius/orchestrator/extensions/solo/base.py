# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-strict

from typing import override

from confucius.core.chat_models.bedrock.api.invoke_model import anthropic as ant
from confucius.core.analect import AnalectRunContext
from confucius.core.memory import CfMemory, CfMessage
from confucius.core import types as cf
from confucius.orchestrator.exceptions import OrchestratorInterruption
from confucius.orchestrator.extensions.solo.prompts import (
    DEFAULT_SOLO_MODE_REMINDER_TEMPLATE,
    SOLO_MODE_DESCRIPTION,
    UPDATE_TASK_PROGRESS_TOOL_DESCRIPTION,
    UPDATE_TASK_PROGRESS_TOOL_NAME,
)
from confucius.orchestrator.extensions.solo.types import MeterData, MeterStatusType
from confucius.orchestrator.extensions.tool_use import ToolUseExtension
from confucius.utils.artifact import set_artifact
from pydantic import Field, PrivateAttr

UpdateTaskProgressInput = MeterData


# Default continue message
DEFAULT_CONTINUE_MESSAGE = """\
Continue working autonomously. Do not pause or ask the user for input unless you are blocked or need authorization. Only stop when the task progress reaches 100%.
"""


class SoloModeExtension(ToolUseExtension):
    """
    Extension for solo mode task execution with progress tracking.

    Solo mode is designed for tasks that can take a long time to complete and require
    the AI to work independently without frequent user interaction. During task execution,
    the AI should regularly update its progress using the update_task_progress tool.

    This extension provides:
    - Progress tracking for long-running tasks
    - Interruption when task is not complete
    - Task completion detection
    - User visibility into task status
    """

    name: str = "solo_mode"
    enable_tool_use: bool = True

    continue_message: str = Field(
        default=DEFAULT_CONTINUE_MESSAGE,
        description="Message to continue working autonomously",
    )

    # Interruption message template
    reminder_message_template: str = Field(
        default=DEFAULT_SOLO_MODE_REMINDER_TEMPLATE,
        description="Template for interruption message when task is not complete",
    )
    artifact_name: str = Field(
        default="Progress",
        description="Name of the artifact to store task progress",
    )

    # Private attributes to track progress
    _current_progress: int = PrivateAttr(default=0)
    _current_title: str = PrivateAttr(default="")
    _current_description: str = PrivateAttr(default="")
    _current_status: MeterStatusType | None = PrivateAttr(default=None)
    _has_continue_message_pending: bool = PrivateAttr(default=False)

    @property
    async def tools(self) -> list[ant.ToolLike]:
        """
        Provide update_task_progress tool.
        """
        tools = []

        if self.enable_tool_use:
            # Add update_task_progress tool
            tools.append(
                ant.Tool(
                    name=UPDATE_TASK_PROGRESS_TOOL_NAME,
                    description=UPDATE_TASK_PROGRESS_TOOL_DESCRIPTION,
                    input_schema=UpdateTaskProgressInput.model_json_schema(),
                )
            )

        return tools

    async def on_tool_use(
        self, tool_use: ant.MessageContentToolUse, context: AnalectRunContext
    ) -> ant.MessageContentToolResult:
        """
        Handle update_task_progress tool.
        """
        if tool_use.name == UPDATE_TASK_PROGRESS_TOOL_NAME:
            try:
                # Validate input using Pydantic model
                inp = UpdateTaskProgressInput.model_validate(tool_use.input)

                # Update progress in class fields
                self._current_progress = inp.progress
                self._current_title = inp.title
                self._current_description = inp.description
                self._current_status = inp.type

                # Store artifact
                attachment = await set_artifact(
                    name=self.__class__.__name__ + "." + self.artifact_name,
                    value={
                        "progress": inp.progress,
                        "title": inp.title,
                        "description": inp.description,
                        "type": inp.type.value,
                    },
                    display_name=self.artifact_name,
                    display_order=-1,
                    hide_actions=True,
                    hide_version=True,
                )

                # Display progress update in console
                await context.io.system(
                    f"[Progress: {inp.progress}%] {inp.title}\n{inp.description}",
                    progress=inp.progress,
                    run_status=cf.RunStatus.IN_PROGRESS if inp.progress < 100 else cf.RunStatus.COMPLETED,
                    run_label="Task Progress",
                )

                return ant.MessageContentToolResult(
                    tool_use_id=tool_use.id,
                    content="Task progress updated successfully",
                )

            except Exception as e:
                msg = f"update_task_progress tool execution failed: {type(e).__name__}: {str(e)}"
                await context.io.system(
                    msg,
                    run_label="Update Task Progress Failed",
                    run_status=cf.RunStatus.WARNING,
                )
                raise

        # Should not reach here as we only have one tool
        return ant.MessageContentToolResult(
            tool_use_id=tool_use.id,
            content=f"Unknown tool: {tool_use.name}",
            is_error=True,
        )

    async def description(self) -> str:
        return SOLO_MODE_DESCRIPTION

    async def on_after_tool_use_result(
        self,
        tool_use: ant.MessageContentToolUse,
        tool_result: ant.MessageContentToolResult,
        context: AnalectRunContext,
    ) -> None:
        if tool_use.name == UPDATE_TASK_PROGRESS_TOOL_NAME:
            # Don't add message if agent is blocked (ERROR status)
            if self._current_status == MeterStatusType.ERROR:
                return  # Agent should stop and wait for user input

            # Don't add message if task is complete
            if self._current_progress == 100:
                return  # Task complete, no need to continue

            # Only add "continue working" message for normal/warning/success states
            self._has_continue_message_pending = True

    async def on_memory(self, memory: CfMemory, context: AnalectRunContext) -> CfMemory:
        if self._has_continue_message_pending:
            msg = CfMessage(
                type=cf.MessageType.SYS,
                content=self.continue_message,
            )
            context.memory_manager.add_messages([msg])
            memory.add_messages([msg])
            self._has_continue_message_pending = False

        return memory

    @override
    async def on_process_messages_complete(self, context: AnalectRunContext) -> None:
        """Check if progress needs to be updated and raise interruption if not complete"""
        # If status is error, don't interrupt - agent is blocked and needs user action
        if self._current_status == MeterStatusType.ERROR:
            return

        # If status is warning, continue checking progress (don't exit early)

        # If progress is not 100, raise interruption to continue working
        if self._current_progress < 100:
            # Format the reminder message with current progress
            reminder_message = self.reminder_message_template.format(
                progress=self._current_progress
            )
            raise OrchestratorInterruption(reminder_message)
