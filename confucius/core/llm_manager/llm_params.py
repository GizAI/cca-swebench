# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-strict
from typing import Any

from pydantic import BaseModel, Field


class LLMParams(BaseModel):
    model: str = Field(None, description="Model name")
    temperature: float | None = Field(default=None)

    # By default, Confucius will start from a small max token value
    # and perform perform exponential backoffs.
    #
    # User can override the starting value with `initial_max_tokens`,
    # and the maximum value with `max_tokens`. This is useful when
    # you already know the output is going to exceed the starting max_token
    # value.
    initial_max_tokens: int | None = Field(default=None)
    max_tokens: int | None = Field(default=None)

    verbose: bool = Field(default=False)
    top_p: float | None = Field(default=None)
    repetition_penalty: float = Field(
        default=1.0,
        ge=0.0,
        le=2.0,
        description="Repetition penalty for the generation.",
    )
    guided_decode_json_schema: str | None = Field(
        None, description="Guided decode json schema"
    )
    strict: bool = Field(
        default=False,
        description="Strict mode where json schema will be enforced whenever possible.",
    )
    stop: list[str] | None = Field(
        None,
        description="Stop sequences to use when generating the output",
    )

    cache: bool = Field(
        default=True,
        description=(
            "If set to true (default), we will prefer to use the cached result. "
            "If set to false, we will perform fresh LLMs even if the input has been seen before."
        ),
    )

    additional_kwargs: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Additional keyword arguments to pass to the LLM call. "
            "This is useful when you want to pass in custom parameters "
            "that are not supported by the LLMParams class."
        ),
    )

    class Config:
        arbitrary_types_allowed = True
