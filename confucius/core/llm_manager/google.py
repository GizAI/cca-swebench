# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-strict

import logging
import os
import json
from pathlib import Path

from google import genai
from google.oauth2.credentials import Credentials
from langchain_core.language_models import BaseChatModel
from pydantic import PrivateAttr

from ..chat_models.google.gemini import GeminiChat

from .base import LLMManager, LLMParams
from .constants import DEFAULT_INITIAL_MAX_TOKEN


logger: logging.Logger = logging.getLogger(__name__)


class GoogleLLMManager(LLMManager):
    """Google Gemini manager using native google-genai SDK only.

    Supports both Gemini Developer API and Vertex AI via env configuration.

    Environment variables:
    - GOOGLE_API_KEY or GEMINI_API_KEY: for Developer API
    - GOOGLE_GENAI_USE_VERTEXAI=true: enable Vertex AI mode
      plus GOOGLE_CLOUD_PROJECT and GOOGLE_CLOUD_LOCATION
    """

    _client: genai.Client | None = PrivateAttr(default=None)

    def _get_oauth_client(self) -> genai.Client:
        oauth_path = Path(
            os.environ.get("GEMINI_OAUTH_CREDS_PATH", str(Path.home() / ".gemini" / "oauth_creds.json"))
        )
        if not oauth_path.exists():
            raise FileNotFoundError(
                f"GEMINI_USE_OAUTH is set, but OAuth credentials are missing at {oauth_path}."
            )

        oauth = json.loads(oauth_path.read_text(encoding="utf-8"))
        token = oauth.get("access_token")
        if not isinstance(token, str) or not token:
            raise ValueError(f"Invalid Gemini OAuth credentials at {oauth_path}: missing access_token")

        scopes = oauth.get("scope")
        credentials = Credentials(
            token=token,
            refresh_token=oauth.get("refresh_token"),
            token_uri=oauth.get("token_uri") or "https://oauth2.googleapis.com/token",
            client_id=oauth.get("client_id"),
            client_secret=oauth.get("client_secret"),
            scopes=scopes.split() if isinstance(scopes, str) else None,
        )

        project = os.environ.get("GEMINI_OAUTH_PROJECT") or os.environ.get("GOOGLE_CLOUD_PROJECT")
        if not project:
            raise ValueError(
                "Gemini OAuth project is not set. Set GEMINI_OAUTH_PROJECT or GOOGLE_CLOUD_PROJECT."
            )
        location = (
            os.environ.get("GEMINI_OAUTH_LOCATION")
            or os.environ.get("GOOGLE_CLOUD_LOCATION")
            or "us-central1"
        )

        return genai.Client(
            vertexai=True,
            project=project,
            location=location,
            credentials=credentials,
        )

    def get_client(self) -> genai.Client:
        if self._client is None:
            if os.environ.get("GEMINI_USE_OAUTH", "").lower() in {"1", "true", "yes"}:
                self._client = self._get_oauth_client()
                return self._client

            use_vertex = os.environ.get("GOOGLE_GENAI_USE_VERTEXAI", "").lower() in {
                "1",
                "true",
                "yes",
            }
            if use_vertex:
                project = os.environ["GOOGLE_CLOUD_PROJECT"]
                location = os.environ["GOOGLE_CLOUD_LOCATION"]
                self._client = genai.Client(
                    vertexai=True, project=project, location=location
                )
            else:
                # API key picked automatically from GOOGLE_API_KEY or GEMINI_API_KEY
                self._client = genai.Client()
        return self._client

    def _get_chat(self, params: LLMParams) -> BaseChatModel:
        model = params.model or os.environ.get("GEMINI_MODEL", "")
        if not model:
            raise ValueError(
                "Gemini model not specified. Set params.model or GEMINI_MODEL env var."
            )
        if "gemini" in model.lower():
            return GeminiChat(
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
            )
        else:
            raise ValueError(
                f"Model: {params.model} is not supported by Google LLM Manager"
            )
