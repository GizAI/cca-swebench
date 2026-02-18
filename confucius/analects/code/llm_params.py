# Copyright (c) Meta Platforms, Inc. and affiliates.
import os

from ...core.chat_models.bedrock.api.invoke_model import anthropic as ant
from ...core.llm_manager.llm_params import LLMParams

CLAUDE_4_5_SONNET_THINKING = LLMParams(
    model="claude-sonnet-4-5",
    initial_max_tokens=16384,
    temperature=0.3,
    top_p=0.7,
    additional_kwargs={
        "thinking": ant.Thinking(
            type=ant.ThinkingType.ENABLED,
            budget_tokens=8192,
        ).dict(),
    },
)

CLAUDE_4_5_OPUS = LLMParams(
    model="claude-opus-4-5",
    initial_max_tokens=16384,
    temperature=0.3,
    top_p=None,
)

GPT5_1_THINKING = LLMParams(
    model="gpt-5.1",
    initial_max_tokens=8192,
    additional_kwargs={
        "thinking": ant.Thinking(
            type=ant.ThinkingType.ENABLED,
            budget_tokens=32768,
        ).dict(),
    },
)

GPT5_2_THINKING = LLMParams(
    model="gpt-5.2",
    initial_max_tokens=8192,
    additional_kwargs={
        "thinking": ant.Thinking(
            type=ant.ThinkingType.ENABLED,
            budget_tokens=32768,
        ).dict(),
    },
)


LLM_PRESETS: dict[str, LLMParams] = {
    "claude-4.5-sonnet-thinking": CLAUDE_4_5_SONNET_THINKING,
    "claude-4.5-opus": CLAUDE_4_5_OPUS,
    "gpt-5.1-thinking": GPT5_1_THINKING,
    "gpt-5.2-thinking": GPT5_2_THINKING,
}


def get_code_llm_params() -> LLMParams:
    model_from_env = os.environ.get("CCA_MODEL")
    if model_from_env:
        return LLMParams(
            model=model_from_env,
            initial_max_tokens=int(os.environ.get("CCA_INITIAL_MAX_TOKENS", "8192")),
            temperature=(
                float(os.environ["CCA_TEMPERATURE"])
                if "CCA_TEMPERATURE" in os.environ
                else None
            ),
            top_p=float(os.environ["CCA_TOP_P"]) if "CCA_TOP_P" in os.environ else None,
        )

    preset = os.environ.get("CCA_MODEL_PRESET", "gpt-5.2-thinking").strip().lower()
    if preset not in LLM_PRESETS:
        available = ", ".join(sorted(LLM_PRESETS.keys()))
        raise ValueError(
            f"Unsupported CCA_MODEL_PRESET '{preset}'. Available presets: {available}"
        )
    return LLM_PRESETS[preset]
