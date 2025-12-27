# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-strict

from enum import Enum

from pydantic import BaseModel, Field


class MeterStatusType(str, Enum):
    """Status type for meter data"""

    INFO = "INFO"
    SUCCESS = "SUCCESS"
    WARNING = "WARNING"
    ERROR = "ERROR"


class MeterData(BaseModel):
    """Data model for task progress updates"""

    progress: int = Field(
        ..., ge=0, le=100, description="Progress percentage (0-100)"
    )
    title: str = Field(..., description="Brief title describing current work")
    description: str = Field(
        ..., description="Detailed description of what has been accomplished"
    )
    type: MeterStatusType = Field(
        default=MeterStatusType.INFO, description="Status type of the progress update"
    )
