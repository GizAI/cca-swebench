#!/usr/bin/env python3
# Copyright (c) Meta Platforms, Inc. and affiliates.

from __future__ import annotations

import base64
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from google import genai
from google.oauth2.credentials import Credentials

CODEX_AUTH_PATH = Path.home() / ".codex" / "auth.json"
CODEX_MODELS_CACHE_PATH = Path.home() / ".codex" / "models_cache.json"
CODEX_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
OPENAI_OAUTH_ISSUER = "https://auth.openai.com"
CODEX_RESPONSES_ENDPOINT = "https://chatgpt.com/backend-api/codex/responses"

GEMINI_OAUTH_PATH = Path.home() / ".gemini" / "oauth_creds.json"
GEMINI_DEFAULT_LOCATION = "us-central1"


@dataclass(frozen=True)
class ModelCatalog:
    provider: str
    models: list[str]
    aliases: dict[str, str]


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, content: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(content, indent=2) + "\n", encoding="utf-8")
    path.chmod(0o600)


def _http_form_post(url: str, data: dict[str, str]) -> dict[str, Any]:
    payload = urllib.parse.urlencode(data).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        body = response.read().decode("utf-8")
    return json.loads(body)


def _jwt_claims(jwt_token: str) -> dict[str, Any]:
    parts = jwt_token.split(".")
    if len(parts) != 3:
        return {}
    payload = parts[1]
    padding = "=" * (-len(payload) % 4)
    decoded = base64.urlsafe_b64decode(payload + padding)
    return json.loads(decoded.decode("utf-8"))


def _extract_account_id_from_claims(claims: dict[str, Any]) -> str | None:
    root = claims.get("chatgpt_account_id")
    if isinstance(root, str) and root:
        return root
    auth_claim = claims.get("https://api.openai.com/auth")
    if isinstance(auth_claim, dict):
        nested = auth_claim.get("chatgpt_account_id")
        if isinstance(nested, str) and nested:
            return nested
    return None


def _refresh_openai_oauth(refresh_token: str) -> dict[str, Any]:
    return _http_form_post(
        f"{OPENAI_OAUTH_ISSUER}/oauth/token",
        {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": CODEX_CLIENT_ID,
        },
    )


def _use_codex_runtime(access_token: str, account_id: str | None) -> None:
    os.environ["OPENAI_API_KEY"] = access_token
    os.environ["OPENAI_BASE_URL"] = "https://chatgpt.com/backend-api/codex"
    os.environ["OPENAI_ORIGINATOR"] = os.environ.get("OPENAI_ORIGINATOR", "codex-cli")
    if account_id:
        os.environ["OPENAI_CHATGPT_ACCOUNT_ID"] = account_id


def _prepare_codex_from_codex_cli(codex_auth_path: Path) -> bool:
    if not codex_auth_path.exists():
        return False

    auth = _load_json(codex_auth_path)
    api_key = auth.get("OPENAI_API_KEY")
    if isinstance(api_key, str) and api_key:
        os.environ["OPENAI_API_KEY"] = api_key
        return True

    tokens = auth.get("tokens")
    if not isinstance(tokens, dict):
        return False

    access_token = tokens.get("access_token")
    refresh_token = tokens.get("refresh_token")
    if not isinstance(access_token, str) or not access_token:
        return False

    claims = _jwt_claims(access_token)
    expires_epoch = int(claims.get("exp", 0))
    now_epoch = int(time.time())
    account_id = tokens.get("account_id")
    if not isinstance(account_id, str) or not account_id:
        account_id = _extract_account_id_from_claims(claims)

    if expires_epoch <= now_epoch + 10 and isinstance(refresh_token, str) and refresh_token:
        refreshed = _refresh_openai_oauth(refresh_token)
        new_access = refreshed["access_token"]
        new_refresh = refreshed.get("refresh_token") or refresh_token
        tokens["access_token"] = new_access
        tokens["refresh_token"] = new_refresh
        maybe_account_id = (
            tokens.get("account_id")
            if isinstance(tokens.get("account_id"), str)
            else _extract_account_id_from_claims(_jwt_claims(new_access))
        )
        if maybe_account_id:
            tokens["account_id"] = maybe_account_id
        auth["tokens"] = tokens
        auth["last_refresh"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        _write_json(codex_auth_path, auth)
        _use_codex_runtime(new_access, maybe_account_id)
        return True

    _use_codex_runtime(access_token, account_id)
    return True


def prepare_codex_env(codex_auth_path: Path = CODEX_AUTH_PATH) -> None:
    if os.environ.get("OPENAI_API_KEY"):
        return
    if _prepare_codex_from_codex_cli(codex_auth_path):
        return
    raise FileNotFoundError(
        "No usable Codex/OpenAI auth found. Run `codex login`, or set OPENAI_API_KEY."
    )


def _extract_codex_models(node: Any, result: set[str]) -> None:
    if isinstance(node, dict):
        slug = node.get("slug")
        if isinstance(slug, str) and "codex" in slug:
            result.add(slug)
        for value in node.values():
            _extract_codex_models(value, result)
        return
    if isinstance(node, list):
        for value in node:
            _extract_codex_models(value, result)


def discover_codex_models(cache_path: Path = CODEX_MODELS_CACHE_PATH) -> list[str]:
    if not cache_path.exists():
        return []
    try:
        content = _load_json(cache_path)
    except Exception:
        return []
    models: set[str] = set()
    _extract_codex_models(content, models)
    return sorted(models)


def _codex_model_parts(model_id: str) -> tuple[tuple[int, ...], str]:
    if not model_id.startswith("gpt-") or "-codex" not in model_id:
        return ((), model_id)
    core = model_id[len("gpt-") :]
    version, _, suffix = core.partition("-codex")
    variant = suffix.lstrip("-")
    version_parts: list[int] = []
    for token in version.split("."):
        if token.isdigit():
            version_parts.append(int(token))
    return (tuple(version_parts), variant)


def build_codex_aliases(models: list[str]) -> dict[str, str]:
    aliases: dict[str, str] = {}
    variant_to_models: dict[str, list[str]] = {}

    for model in models:
        versions, variant = _codex_model_parts(model)
        if not versions:
            continue
        version_text = ".".join(str(v) for v in versions)
        aliases[version_text] = model if not variant else aliases.get(version_text, model)
        aliases[f"{version_text}-codex"] = model if not variant else aliases.get(
            f"{version_text}-codex", model
        )
        if variant:
            aliases[f"{version_text}-{variant}"] = model
            variant_to_models.setdefault(variant, []).append(model)

    for variant, variant_models in variant_to_models.items():
        if len(variant_models) == 1:
            aliases[variant] = variant_models[0]

    return aliases


def select_default_codex_model(models: list[str]) -> str:
    if not models:
        raise ValueError(
            "No Codex models discovered in ~/.codex/models_cache.json. Pass --model explicitly."
        )

    def _variant_priority(model_id: str) -> int:
        _, variant = _codex_model_parts(model_id)
        if variant == "spark":
            return 40
        if variant == "":
            return 30
        if variant == "max":
            return 20
        if variant == "mini":
            return 0
        return 10

    candidates = sorted(
        models,
        key=lambda m: (
            _codex_model_parts(m)[0],
            _variant_priority(m),
        ),
        reverse=True,
    )
    return candidates[0]


def resolve_codex_model(model: str | None, discovered_models: list[str]) -> str:
    if not model:
        return select_default_codex_model(discovered_models)
    raw = model.strip()
    if raw in discovered_models:
        return raw
    aliases = build_codex_aliases(discovered_models)
    return aliases.get(raw.lower(), raw)


def _codex_request_headers(codex_auth_path: Path) -> dict[str, str]:
    auth = _load_json(codex_auth_path)
    tokens = auth.get("tokens")
    if not isinstance(tokens, dict):
        raise ValueError("Invalid Codex auth format: missing tokens")
    access = tokens.get("access_token")
    if not isinstance(access, str) or not access:
        raise ValueError("Invalid Codex auth format: missing access_token")
    account = tokens.get("account_id")
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {access}",
        "originator": "codex-cli",
    }
    if isinstance(account, str) and account:
        headers["ChatGPT-Account-Id"] = account
    return headers


def validate_codex_model_live(model: str, codex_auth_path: Path = CODEX_AUTH_PATH) -> tuple[bool, str]:
    payload = {
        "model": model,
        "input": [
            {
                "role": "user",
                "content": [{"type": "input_text", "text": "ping"}],
            }
        ],
        "instructions": "You are terse.",
        "store": False,
        "stream": True,
    }
    request = urllib.request.Request(
        CODEX_RESPONSES_ENDPOINT,
        data=json.dumps(payload).encode("utf-8"),
        headers=_codex_request_headers(codex_auth_path),
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            return (response.status == 200, f"HTTP {response.status}")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "ignore")
        return (False, f"HTTP {exc.code}: {body[:160].replace(chr(10), ' ')}")


def _load_gemini_oauth(gemini_oauth_path: Path) -> dict[str, Any]:
    if not gemini_oauth_path.exists():
        raise FileNotFoundError(
            f"Gemini OAuth credentials not found at {gemini_oauth_path}. Run `gemini` login first."
        )
    oauth = _load_json(gemini_oauth_path)
    if not isinstance(oauth.get("access_token"), str) or not oauth.get("access_token"):
        raise ValueError(f"Invalid Gemini OAuth credentials in {gemini_oauth_path}: missing access_token")
    return oauth


def _build_google_credentials(oauth: dict[str, Any]) -> Credentials:
    scopes = oauth.get("scope")
    return Credentials(
        token=oauth.get("access_token"),
        refresh_token=oauth.get("refresh_token"),
        token_uri=oauth.get("token_uri") or "https://oauth2.googleapis.com/token",
        client_id=oauth.get("client_id"),
        client_secret=oauth.get("client_secret"),
        scopes=scopes.split() if isinstance(scopes, str) else None,
    )


def _discover_google_projects(access_token: str) -> list[dict[str, Any]]:
    request = urllib.request.Request(
        "https://cloudresourcemanager.googleapis.com/v1/projects?pageSize=200",
        headers={"Authorization": f"Bearer {access_token}"},
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))
    projects = payload.get("projects", [])
    if not isinstance(projects, list):
        return []
    return [p for p in projects if isinstance(p, dict)]


def _select_google_project(projects: list[dict[str, Any]]) -> str:
    active = [p for p in projects if p.get("lifecycleState") == "ACTIVE"]
    preferred = []
    for project in active:
        labels = project.get("labels")
        if isinstance(labels, dict) and labels.get("generative-language") == "enabled":
            preferred.append(project)

    candidates = preferred or active
    if not candidates:
        raise ValueError(
            "No ACTIVE Google Cloud project found from OAuth account. "
            "Set GEMINI_OAUTH_PROJECT explicitly."
        )

    project_id = candidates[0].get("projectId")
    if not isinstance(project_id, str) or not project_id:
        raise ValueError("Discovered project is missing projectId")
    return project_id


def prepare_gemini_env(gemini_oauth_path: Path = GEMINI_OAUTH_PATH) -> None:
    if os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY"):
        os.environ.pop("GEMINI_USE_OAUTH", None)
        return

    oauth = _load_gemini_oauth(gemini_oauth_path)
    project = os.environ.get("GEMINI_OAUTH_PROJECT") or os.environ.get("GOOGLE_CLOUD_PROJECT")
    if not project:
        discovered = _discover_google_projects(oauth["access_token"])
        project = _select_google_project(discovered)

    location = (
        os.environ.get("GEMINI_OAUTH_LOCATION")
        or os.environ.get("GOOGLE_CLOUD_LOCATION")
        or GEMINI_DEFAULT_LOCATION
    )

    os.environ["GEMINI_USE_OAUTH"] = "1"
    os.environ["GEMINI_OAUTH_CREDS_PATH"] = str(gemini_oauth_path)
    os.environ["GEMINI_OAUTH_PROJECT"] = project
    os.environ["GEMINI_OAUTH_LOCATION"] = location
    os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "true"
    os.environ["GOOGLE_CLOUD_PROJECT"] = project
    os.environ["GOOGLE_CLOUD_LOCATION"] = location


def _build_gemini_client(gemini_oauth_path: Path = GEMINI_OAUTH_PATH) -> genai.Client:
    if os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY"):
        return genai.Client()

    prepare_gemini_env(gemini_oauth_path)
    oauth = _load_gemini_oauth(gemini_oauth_path)
    credentials = _build_google_credentials(oauth)
    return genai.Client(
        vertexai=True,
        project=os.environ["GEMINI_OAUTH_PROJECT"],
        location=os.environ["GEMINI_OAUTH_LOCATION"],
        credentials=credentials,
    )


def _canonical_gemini_model(model_id: str) -> str:
    if "/models/" in model_id:
        return model_id.split("/models/")[-1]
    return model_id


def discover_gemini_models_live(gemini_oauth_path: Path = GEMINI_OAUTH_PATH) -> list[str]:
    client = _build_gemini_client(gemini_oauth_path)
    models: set[str] = set()
    for model in client.models.list():
        name = getattr(model, "name", None)
        if isinstance(name, str) and "gemini" in name.lower():
            models.add(name)
    return sorted(models)


def build_gemini_aliases(models: list[str]) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for model in models:
        canonical = _canonical_gemini_model(model)
        aliases[model.lower()] = model
        aliases[canonical.lower()] = model
        if canonical.lower().startswith("gemini-"):
            aliases[canonical[len("gemini-") :].lower()] = model
    return aliases


def _gemini_sort_key(model_id: str) -> tuple[tuple[int, ...], bool, bool, str]:
    canonical = _canonical_gemini_model(model_id).lower()
    match = re.match(r"gemini-(\d+(?:\.\d+)*)-(.+)$", canonical)
    version: tuple[int, ...] = ()
    tail = canonical
    if match:
        version = tuple(int(part) for part in match.group(1).split("."))
        tail = match.group(2)
    is_preview = "preview" in tail or "exp" in tail
    is_flash = "flash" in tail
    return (version, not is_preview, is_flash, tail)


def select_default_gemini_model(models: list[str]) -> str:
    if not models:
        raise ValueError("No Gemini models discovered from live API. Pass --model explicitly.")
    return sorted(models, key=_gemini_sort_key, reverse=True)[0]


def resolve_gemini_model(model: str | None, discovered_models: list[str]) -> str:
    if not model:
        return select_default_gemini_model(discovered_models)
    raw = model.strip()
    if raw in discovered_models:
        return raw
    aliases = build_gemini_aliases(discovered_models)
    return aliases.get(raw.lower(), raw)


def validate_gemini_model_live(
    model: str,
    gemini_oauth_path: Path = GEMINI_OAUTH_PATH,
) -> tuple[bool, str]:
    try:
        client = _build_gemini_client(gemini_oauth_path)
        response = client.models.generate_content(model=model, contents="ping")
        text = (getattr(response, "text", "") or "").strip()
        return (True, text[:80] or "OK")
    except Exception as exc:
        return (False, str(exc).replace("\n", " ")[:220])


def list_models(provider: str, codex_auth_path: Path, gemini_oauth_path: Path) -> ModelCatalog:
    if provider == "codex":
        models = discover_codex_models()
        return ModelCatalog(provider=provider, models=models, aliases=build_codex_aliases(models))
    if provider == "gemini":
        models = discover_gemini_models_live(gemini_oauth_path)
        return ModelCatalog(provider=provider, models=models, aliases=build_gemini_aliases(models))
    return ModelCatalog(provider=provider, models=[], aliases={})


def resolve_runtime_model(
    provider: str,
    model: str | None,
    *,
    codex_auth_path: Path = CODEX_AUTH_PATH,
    gemini_oauth_path: Path = GEMINI_OAUTH_PATH,
    discovered_codex_models: list[str] | None = None,
    discovered_gemini_models: list[str] | None = None,
) -> str:
    if provider == "codex":
        prepare_codex_env(codex_auth_path)
        catalog = discovered_codex_models or discover_codex_models()
        return resolve_codex_model(model, catalog)

    if provider == "openai":
        if not os.environ.get("OPENAI_API_KEY"):
            raise ValueError("OPENAI_API_KEY is required for provider=openai")
        return model or "gpt-5.2"

    if provider == "gemini":
        if not (os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")):
            prepare_gemini_env(gemini_oauth_path)
        catalog = discovered_gemini_models or discover_gemini_models_live(gemini_oauth_path)
        return resolve_gemini_model(model, catalog)

    if provider == "bedrock":
        if not os.environ.get("AWS_REGION"):
            raise ValueError("AWS_REGION is required for provider=bedrock")
        return model or "claude-sonnet-4-5"

    if provider == "custom":
        if not model:
            raise ValueError("--model is required for provider=custom")
        return model

    raise ValueError(f"Unsupported provider: {provider}")
