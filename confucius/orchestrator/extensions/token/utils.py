# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-strict
import logging

import math
from typing import Any

from langchain_core.messages import BaseMessage

from ....core.memory import CfMessage

logger: logging.Logger = logging.getLogger(__name__)
EXCLUDE_KEYS: list[str] = ["signature"]


def get_content_str(
    content: str | list[str | dict[str, Any]], exclude_keys: list[str] | None = None
) -> str:
    exclude_keys = exclude_keys or EXCLUDE_KEYS

    if isinstance(content, str):
        return content
    elif isinstance(content, list):
        res = []
        for item in content:
            if isinstance(item, str):
                res.append(item)
            elif isinstance(item, dict):
                res.append(
                    str({k: v for k, v in item.items() if k not in exclude_keys})
                )
            else:
                raise ValueError(f"Unexpected content type: {type(item)}")
        return "\n".join(res)


async def _get_text_attachment_length(msg: BaseMessage | CfMessage) -> int:
    """
    Get the total length of text attachments in a message.
    """
    total_length = 0

    if isinstance(msg, CfMessage):
        # Approximate by summing lengths of file attachments' data/urls if present.
        for att in msg.attachments:
            try:
                content = att.content
                # Cf types union: FileAttachment | LinkAttachment | ArtifactInfoAttachment
                data = getattr(content, "data", None) or getattr(content, "url", None)
                if isinstance(data, str):
                    total_length += len(data)
            except Exception:
                # Be conservative on failures
                continue
        return total_length

    return total_length


async def get_prompt_char_lengths(
    messages: list[BaseMessage] | list[CfMessage],
) -> list[int]:
    """
    Get the lengths of a prompt in characters per message. Text attachments are counted, but image attachments are not counted.

    Args:
        messages (list[BaseMessage]): The list of messages to get the lengths of.

    Returns:
        list[int]: The lengths of the prompt in characters per message.
    """
    lengths = []
    for msg in messages:
        attachment_length = await _get_text_attachment_length(msg)
        lengths.append(len(get_content_str(msg.content)) + attachment_length)

    return lengths


async def get_prompt_token_lengths(
    messages: list[BaseMessage] | list[CfMessage],
    num_chars_per_token: float = 3.0,
) -> list[int]:
    """
    Get the lengths of a prompt in tokens per message. Text attachments are counted, but image attachments are not counted.

    Args:
        messages (list[BaseMessage]): The list of messages to get the lengths of.
        num_chars_per_token (float, optional): The number of characters per token. Defaults to 3.0. This is a rough estimate, based on https://help.openai.com/en/articles/4936856-what-are-tokens-and-how-to-count-them.

    Returns:
        list[int]: The lengths of the prompt in tokens per message.
    """
    # Use rough estimate

    lengths = []
    for msg in messages:
        attachment_length = await _get_text_attachment_length(msg)
        lengths.append(
            math.ceil(
                (len(get_content_str(msg.content)) + attachment_length)
                / num_chars_per_token
            )
        )

    return lengths
