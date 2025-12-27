# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-strict

from typing import Any

from langchain_core.embeddings import Embeddings
from langchain_core.language_models import BaseChatModel
from pydantic import PrivateAttr

from .azure import AzureLLMManager
from .base import LLMManager
from .bedrock import BedrockLLMManager
from .constants import AZURE_OPENAI_MODEL_PREFIXES, OPENAI_MODEL_PREFIXES
from .google import GoogleLLMManager
from .openai import OpenAILLMManager
from .llm_params import LLMParams


class AutoLLMManager(LLMManager):
    _bedrock: BedrockLLMManager = PrivateAttr()
    _google: GoogleLLMManager = PrivateAttr()
    _azure: AzureLLMManager = PrivateAttr()
    _openai: OpenAILLMManager = PrivateAttr()

    def __init__(self, **data: Any) -> None:
        super().__init__(**data)
        self._bedrock = BedrockLLMManager()
        self._google = GoogleLLMManager()
        self._azure = AzureLLMManager()
        self._openai = OpenAILLMManager()

    def _use_bedrock(self, params: LLMParams | None) -> bool:
        return params is not None and ("claude" in (params.model or "").lower())

    def _use_google(self, params: LLMParams | None) -> bool:
        return params is not None and ("gemini" in (params.model or "").lower())

    def _use_openai(self, params: LLMParams | None) -> bool:
        return params is not None and any(
            model_prefix in (params.model or "").lower()
            for model_prefix in OPENAI_MODEL_PREFIXES
        )

    def _use_azure(self, params: LLMParams | None) -> bool:
        return params is not None and any(
            model_prefix in (params.model or "").lower()
            for model_prefix in AZURE_OPENAI_MODEL_PREFIXES
        )

    def _get_chat(self, params: LLMParams) -> BaseChatModel:
        if self._use_bedrock(params):
            return self._bedrock._get_chat(params=params)

        if self._use_google(params):
            return self._google._get_chat(params=params)

        if self._use_openai(params):
            return self._openai._get_chat(params=params)

        if self._use_azure(params):
            return self._azure._get_chat(params=params)

        raise ValueError(f"Model: {params.model} is not supported by AutoLLMManager")

    def get_embeddings(self, **kwargs: Any) -> Embeddings:
        raise NotImplementedError(
            f"{self.__class__.__name__} does not support embeddings."
        )
