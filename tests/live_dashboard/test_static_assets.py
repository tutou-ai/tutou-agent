"""Static contract tests for the secure Tutou Agent live dashboard."""

from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "services" / "live_dashboard" / "static"


class _DashboardParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: set[str] = set()
        self.links: list[dict[str, str | None]] = []
        self.scripts: list[dict[str, str | None]] = []
        self.lang: str | None = None
        self.text: list[str] = []

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        values = dict(attrs)
        if values.get("id"):
            self.ids.add(values["id"] or "")
        if tag == "html":
            self.lang = values.get("lang")
        elif tag == "link":
            self.links.append(values)
        elif tag == "script":
            self.scripts.append(values)

    def handle_data(self, data: str) -> None:
        if data.strip():
            self.text.append(data.strip())


def _read(name: str) -> str:
    return (STATIC / name).read_text(encoding="utf-8")


def test_dashboard_shell_exposes_required_sections_and_responsive_assets() -> None:
    html = _read("index.html")
    css = _read("style.css")
    javascript = _read("app.js")
    parser = _DashboardParser()
    parser.feed(html)

    required_ids = {
        "connection-status",
        "auth-status",
        "token-form",
        "token-input",
        "token-clear",
        "goal-title",
        "goal-progress",
        "goal-progress-label",
        "active-agents",
        "queued-workstreams",
        "completed-workstreams",
        "recent-events",
        "blockers",
        "sha-matrix",
        "last-updated",
    }
    assert parser.lang == "tr"
    assert required_ids <= parser.ids
    assert any(link.get("href") == "/live/style.css" for link in parser.links)
    assert any(
        script.get("src") == "/live/app.js" and "defer" in script
        for script in parser.scripts
    )

    labels = " ".join(parser.text)
    for label in (
        "Ana Hedef",
        "Aktif Ajanlar",
        "Bekleyen İş Akışları",
        "Tamamlanan İşler",
        "Son Olaylar",
        "Hatalar ve Engeller",
        "Sürüm Matrisi",
        "Erişim Anahtarı",
    ):
        assert label in labels

    assert "@media" in css
    assert "prefers-reduced-motion" in css
    assert html.strip() and css.strip() and javascript.strip()


def test_authenticated_transport_keeps_token_ephemeral_and_out_of_urls() -> None:
    javascript = _read("app.js")

    assert "sessionStorage.getItem" in javascript
    assert "sessionStorage.setItem" in javascript
    assert "sessionStorage.removeItem" in javascript
    assert "localStorage" not in javascript
    assert "URLSearchParams" not in javascript
    assert "location.search" not in javascript
    assert "location.hash" not in javascript

    assert 'fetch("/api/live/history"' in javascript
    assert 'fetch("/api/live/stream"' in javascript
    assert "Authorization" in javascript
    assert "Bearer ${token}" in javascript
    assert "/api/live/history?" not in javascript
    assert "/api/live/stream?" not in javascript

    # Native EventSource cannot attach a Bearer header. The stream must use an
    # authenticated fetch + ReadableStream parser without leaking the token.
    assert "EventSource" not in javascript
    assert '"text/event-stream"' in javascript
    assert ".body.getReader()" in javascript
    assert "TextDecoder" in javascript
    assert "AbortController" in javascript


def test_remote_payload_uses_safe_dom_sinks_for_every_dashboard_region() -> None:
    javascript = _read("app.js")

    for unsafe_sink in (
        "innerHTML",
        "outerHTML",
        "insertAdjacentHTML",
        "document.write",
        "eval(",
        "new Function",
    ):
        assert unsafe_sink not in javascript

    assert "document.createElement" in javascript
    assert ".textContent" in javascript
    for target_id in (
        "goal-title",
        "goal-progress",
        "goal-progress-label",
        "active-agents",
        "queued-workstreams",
        "completed-workstreams",
        "recent-events",
        "blockers",
        "sha-matrix",
        "last-updated",
    ):
        assert f'"{target_id}"' in javascript

    # These are the complete public event-schema fields the UI may project.
    for field in (
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
        "timestamp",
    ):
        assert field in javascript

    assert "Math.max(0" in javascript
    assert "Math.min(100" in javascript


def test_history_finishes_before_live_stream_is_opened() -> None:
    javascript = _read("app.js")
    connect = javascript[
        javascript.index("async function connect") : javascript.index(
            'tokenForm.addEventListener("submit"'
        )
    ]

    assert "async function connect(token)" in connect
    assert "await loadHistory(token);" in connect
    assert connect.index("await loadHistory(token);") < connect.index("openStream(token)")


def test_token_clear_wipes_current_data_and_blocks_stale_history() -> None:
    javascript = _read("app.js")
    load_history = javascript[
        javascript.index("async function loadHistory") : javascript.index(
            "function parseEventBlock"
        )
    ]
    connect = javascript[
        javascript.index("function connect") : javascript.index(
            'tokenForm.addEventListener("submit"'
        )
    ]
    clear_handler = javascript[
        javascript.index('tokenClear.addEventListener("click"') : javascript.index(
            'window.addEventListener("online"'
        )
    ]

    assert load_history.count("if (token !== activeToken) return;") == 2
    assert "if (token !== activeToken) return;" in connect
    assert "latestPayload = {};" in clear_handler
    assert "recentEvents.splice(0, recentEvents.length);" in clear_handler
    assert "renderDashboard(latestPayload, recentEvents);" in clear_handler


def test_stream_reconnects_with_backoff_and_keeps_event_memory_bounded() -> None:
    javascript = _read("app.js")

    max_events = re.search(r"const MAX_EVENTS = (\d+);", javascript)
    assert max_events, "The browser event cap must be explicit and auditable"
    assert int(max_events.group(1)) == 150
    assert "orderedEvents(recentEvents).slice(0, MAX_EVENTS)" in javascript
    assert "recentEvents.splice(0, recentEvents.length" in javascript

    assert "scheduleReconnect" in javascript
    assert "reconnectAttempt" in javascript
    assert "RECONNECT_BASE_MS" in javascript
    assert "RECONNECT_MAX_MS" in javascript
    assert "Math.min(RECONNECT_MAX_MS" in javascript
    assert "setTimeout" in javascript
    assert "clearTimeout" in javascript
    assert 'addEventListener("online"' in javascript
