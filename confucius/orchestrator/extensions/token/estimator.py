# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-strict

from typing import cast

from langchain_core.messages import BaseMessage
from loguru import logger
from pydantic import PrivateAttr

from ....core.analect import AnalectRunContext, get_current_context

from ....core.chat_models.bedrock.api.invoke_model import anthropic as ant

from ....core.memory import CfMessage
from ..base import Extension

from .utils import get_prompt_char_lengths, get_prompt_token_lengths

NUM_CHARS_PER_TOKEN_ESTIMATE_KEY = "num_chars_per_token_estimate"
DEFAULT_NUM_CHARS_PER_TOKEN = 3.0
MAX_NUM_CHARS_PER_TOKEN = 4.0


class TokenEstimatorExtension(Extension):
    _last_prompt_char_length: int | None = PrivateAttr(default=None)
    _last_prompt_token_length: int | None = PrivateAttr(default=None)

    async def _on_invoke_llm(
        self,
        messages: list[BaseMessage],
        context: AnalectRunContext,
    ) -> list[BaseMessage]:
        return messages

    async def on_invoke_llm(
        self,
        messages: list[BaseMessage],
        context: AnalectRunContext,
    ) -> list[BaseMessage]:
        messages = await self._on_invoke_llm(messages, context)
        self._last_prompt_char_length = sum(await get_prompt_char_lengths(messages))
        return messages

    async def on_llm_response(
        self,
        message: BaseMessage,
        context: AnalectRunContext,
    ) -> BaseMessage:
        try:
            response = ant.Response.parse_obj(message.response_metadata)
            usage = response.usage
            self._last_prompt_token_length = (
                usage.input_tokens
                + (usage.cache_creation_input_tokens or 0)
                + (usage.cache_read_input_tokens or 0)
            )
            if self._last_prompt_char_length and self._last_prompt_token_length:
                num_chars_per_token = (
                    self._last_prompt_char_length / self._last_prompt_token_length
                )
                logger.debug(
                    f"Estimated number of characters per token: {num_chars_per_token}"
                )
                self.set_num_chars_per_token_estimate(num_chars_per_token)
        except Exception as e:
            logger.warning(f"Failed to parse response metadata: {e}")

        return message

    def get_last_prompt_char_length(self) -> int | None:
        """
        Get the character length of the last processed prompt.

        Returns:
            int | None: The total number of characters in the last prompt messages
                       that were sent to the LLM, or None if no prompt has been
                       processed yet.
        """
        return self._last_prompt_char_length

    def get_last_prompt_token_length(self) -> int | None:
        """
        Get the token length of the last processed prompt as reported by the LLM.

        This value is extracted from the LLM response metadata and includes
        input tokens, cache creation tokens, and cache read tokens.

        Returns:
            int | None: The total number of tokens in the last prompt as reported
                       by the LLM provider, or None if no response has been
                       processed yet or if response metadata was unavailable.
        """
        return self._last_prompt_token_length

    def get_num_chars_per_token_estimate(self) -> float | None:
        """
        Retrieve the learned characters-per-token ratio from session storage.

        This function accesses the session storage to get the current estimate of how many
        characters correspond to one token, based on previous LLM interactions. This ratio
        is learned adaptively from actual LLM responses and is used to improve token
        estimation accuracy for future prompts.

        Returns:
            float | None: The estimated number of characters per token if available,
                         None if no estimate has been learned yet (e.g., first interaction).
        """
        context = get_current_context()
        return cast(
            float,
            context.session_storage[self.__class__.__name__].get(
                NUM_CHARS_PER_TOKEN_ESTIMATE_KEY
            ),
        )

    def set_num_chars_per_token_estimate(self, value: float) -> None:
        """
        Store the learned characters-per-token ratio in session storage.

        This function saves the calculated characters-per-token ratio based on actual
        LLM response metadata. The stored value persists across orchestrator calls
        within the same session and is used to improve token estimation accuracy
        for subsequent prompts.

        The ratio is automatically calculated by comparing the character length of
        prompts with the actual token usage reported by the LLM provider.

        Args:
            value (float): The characters-per-token ratio to store. This should be
                          a positive number representing how many characters typically
                          correspond to one token for the current LLM model.
        """
        context = get_current_context()
        context.session_storage[self.__class__.__name__][
            NUM_CHARS_PER_TOKEN_ESTIMATE_KEY
        ] = value

    async def get_prompt_token_lengths(
        self,
        messages: list[BaseMessage] | list[CfMessage],
    ) -> list[int]:
        num_chars_per_token = (
            self.get_num_chars_per_token_estimate() or DEFAULT_NUM_CHARS_PER_TOKEN
        )
        num_chars_per_token = min(num_chars_per_token, MAX_NUM_CHARS_PER_TOKEN)
        return await get_prompt_token_lengths(messages, num_chars_per_token)
