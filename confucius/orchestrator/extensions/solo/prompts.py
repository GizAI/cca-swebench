# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-strict

UPDATE_TASK_PROGRESS_TOOL_NAME = "update_task_progress"

# Tool description for update_task_progress
UPDATE_TASK_PROGRESS_TOOL_DESCRIPTION = "Updates the current task progress with title, description, completion percentage, and optional status type. This tool should be used to track progress on long-running tasks in solo mode. Update progress regularly as you make meaningful advances toward completing the user's request. The status field is optional - when omitted, it auto-infers to 'loading' for progress < 100 and 'success' at 100. Explicitly set status to 'error' if blocked (stops autonomous work), 'warning' for concerns, or 'success' to force success appearance."

# Description of the extension shown in the system prompt
SOLO_MODE_DESCRIPTION = f"""\
You are operating in SOLO MODE. This means you are expected to work independently on tasks that may take a significant amount of time to complete.

During your work:
- Use the {UPDATE_TASK_PROGRESS_TOOL_NAME} tool regularly to report your progress
- Progress should be reported as an integer from 0-100
- Provide meaningful titles and descriptions of what you're working on
- Mark progress as 100 only when the task is completely finished
- The user might give you complex, multi-step tasks that require sustained effort
- Use status types to indicate your state:
  - Omit status (or set to null) for normal operation - it will auto-infer: "loading" for progress < 100, "success" when progress = 100
  - Explicitly set status to "error" when blocked or need user authorization (stops autonomous work and waits for user input)
  - Explicitly set status to "warning" when there's a concern but you can continue working
  - Explicitly set status to "success" to force success appearance even if progress < 100"""

# Reminder message template shown to the AI between iterations
DEFAULT_SOLO_MODE_REMINDER_TEMPLATE = f"""\
You are in solo mode working on a task that may take a long time to complete. Please check your current progress to see how much you have accomplished for the user task. Current progress is {{progress}}%. If you haven't updated progress yet, use the {UPDATE_TASK_PROGRESS_TOOL_NAME} tool with a 0-100 integer to indicate your progress. If you have completed the task, mark the progress as 100.
"""
