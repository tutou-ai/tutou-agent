"""Public event schema for the live dashboard."""

from datetime import UTC, datetime
from typing import Annotated
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


class LiveEvent(BaseModel):
    """A bounded, public projection of agent activity."""

    model_config = ConfigDict(extra="ignore", str_max_length=4096)

    id: str = Field(default_factory=lambda: str(uuid4()))
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    goal_id: str | None = None
    workstream: str | None = None
    agent_id: str | None = None
    model: str | None = None
    host: str | None = None
    stage: str | None = None
    status: str | None = None
    action: str | None = None
    output_excerpt: str | None = None
    test_result: str | None = None
    git_sha: str | None = None
    links: list[Annotated[str, Field(max_length=2048)]] = Field(
        default_factory=list,
        max_length=8,
    )
