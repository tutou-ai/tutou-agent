from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from services.live_dashboard.schema import LiveEvent


def test_live_event_generates_identity_and_preserves_public_fields():
    event = LiveEvent(
        goal_id="goal-1",
        workstream="backend",
        agent_id="agent-7",
        model="model-x",
        host="worker-a",
        stage="test",
        status="running",
        action="Run focused tests",
        output_excerpt="one passed",
        test_result="passed",
        git_sha="abc123",
        links=["https://example.test/run/1"],
    )

    assert event.id
    assert event.timestamp.tzinfo is not None
    assert event.timestamp <= datetime.now(UTC)
    assert event.model_dump(exclude={"id", "timestamp"}) == {
        "goal_id": "goal-1",
        "workstream": "backend",
        "agent_id": "agent-7",
        "model": "model-x",
        "host": "worker-a",
        "stage": "test",
        "status": "running",
        "action": "Run focused tests",
        "output_excerpt": "one passed",
        "test_result": "passed",
        "git_sha": "abc123",
        "links": ["https://example.test/run/1"],
    }


@pytest.mark.parametrize(
    "field_name",
    [
        "id",
        "goal_id",
        "workstream",
        "agent_id",
        "model",
        "host",
        "stage",
        "status",
        "action",
        "output_excerpt",
        "test_result",
        "git_sha",
    ],
)
def test_live_event_bounds_public_text_fields(field_name):
    maximum = "x" * 4096

    assert getattr(LiveEvent.model_validate({field_name: maximum}), field_name) == maximum
    with pytest.raises(ValidationError):
        LiveEvent.model_validate({field_name: maximum + "x"})


def test_live_event_bounds_each_link_item():
    maximum = "x" * 2048

    assert LiveEvent(links=[maximum]).links == [maximum]
    with pytest.raises(ValidationError):
        LiveEvent(links=[maximum + "x"])


def test_live_event_bounds_link_cardinality():
    links = [f"https://example.test/{index}" for index in range(8)]

    assert LiveEvent(links=links).links == links
    with pytest.raises(ValidationError):
        LiveEvent(links=[*links, "https://example.test/overflow"])
