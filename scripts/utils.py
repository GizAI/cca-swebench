# Copyright (c) Meta Platforms, Inc. and affiliates.
import sys
import traceback

from confucius.core.entry.base import EntryInput
from confucius.core.entry.entry import Entry
from confucius.lib.confucius import Confucius


async def run_agent_with_prompt(
    prompt: str, entry_name="Code", verbose: bool = False
) -> None:
    """
    Run the Confucius Code agent with a given prompt and wait for completion.

    Args:
        prompt: The input prompt to send to the agent
        verbose: Enable verbose logging
    """
    cf: Confucius = Confucius(verbose=verbose)

    try:
        # Use Entry with EntryInput to run the Code entry
        await cf.invoke_analect(
            Entry(), EntryInput(question=prompt, entry_name=entry_name)
        )

    except Exception as e:
        print(f"Error running agent: {e}", file=sys.stderr)
        print(f"Stack trace:\n{traceback.format_exc()}", file=sys.stderr)
        raise
    finally:
        # Dump message trajectory after completion
        cf.dump_trajectory()

        # Save session state like the REPL does
        await cf.save(raise_exception=False)
