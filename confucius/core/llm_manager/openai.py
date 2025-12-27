# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-strict

import logging
import os

from langchain_core.language_models import BaseChatModel
from openai import AsyncOpenAI
from pydantic import PrivateAttr

from ..chat_models.openai.openai import OpenAIChat

from .base import LLMManager, LLMParams
from .constants import DEFAULT_INITIAL_MAX_TOKEN

logger: logging.Logger = logging.getLogger(__name__)


class OpenAILLMManager(LLMManager):
    """OpenAI manager using native AsyncOpenAI client only.

    Environment variables used:
    - OPENAI_API_KEY: API key
    """

    _client: AsyncOpenAI | None = PrivateAttr(default=None)

    def get_client(self) -> AsyncOpenAI:
        """Create/cache AsyncOpenAI client configured via env vars."""
        if self._client is None:
            api_key = os.environ["OPENAI_API_KEY"]
            self._client = AsyncOpenAI(api_key=api_key)
        return self._client

    def _get_chat(self, params: LLMParams) -> BaseChatModel:
        """Get OpenAI chat model using native client configured by env."""
        model = params.model
        if not model:
            raise ValueError("OpenAI model not specified. Set params.model.")

        return OpenAIChat(
            client=self.get_client(),
            model=model,
            temperature=params.temperature,
            top_p=params.top_p,
            max_tokens=(
                params.max_tokens
                or params.initial_max_tokens
                or DEFAULT_INITIAL_MAX_TOKEN
            ),
            stop=params.stop,
            cache=params.cache,
            **(params.additional_kwargs or {}),
            use_responses_api=True,
        )
