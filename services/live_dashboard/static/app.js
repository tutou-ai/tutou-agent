"use strict";

(() => {
  const TOKEN_KEY = "tutou.live.token";
  const MAX_EVENTS = 150;
  const RECONNECT_BASE_MS = 1000;
  const RECONNECT_MAX_MS = 30000;
  const tokenForm = document.getElementById("token-form");
  const tokenInput = document.getElementById("token-input");
  const tokenClear = document.getElementById("token-clear");
  const authStatus = document.getElementById("auth-status");
  const connectionStatus = document.getElementById("connection-status");
  const goalTitle = document.getElementById("goal-title");
  const goalProgress = document.getElementById("goal-progress");
  const goalProgressLabel = document.getElementById("goal-progress-label");
  const activeAgents = document.getElementById("active-agents");
  const queuedWorkstreams = document.getElementById("queued-workstreams");
  const completedWorkstreams = document.getElementById("completed-workstreams");
  const recentEventsList = document.getElementById("recent-events");
  const blockersList = document.getElementById("blockers");
  const shaMatrix = document.getElementById("sha-matrix");
  const lastUpdated = document.getElementById("last-updated");
  const agentCount = document.getElementById("agent-count");
  const queueCount = document.getElementById("queue-count");
  const completedCount = document.getElementById("completed-count");
  const blockerCount = document.getElementById("blocker-count");

  const recentEvents = [];
  let latestPayload = {};
  let streamController = null;
  let reconnectTimer = null;
  let reconnectAttempt = 0;
  let activeToken = "";

  function setStatus(element, message, className) {
    element.textContent = message;
    element.className = `status ${className}`;
  }

  function authHeaders(token, accept) {
    return {
      Accept: accept,
      Authorization: `Bearer ${token}`,
    };
  }

  function rememberToken(token) {
    sessionStorage.setItem(TOKEN_KEY, token);
  }

  function forgetToken() {
    sessionStorage.removeItem(TOKEN_KEY);
  }

  function storedToken() {
    return sessionStorage.getItem(TOKEN_KEY) || "";
  }

  function trimEvents() {
    const newestEvents = orderedEvents(recentEvents).slice(0, MAX_EVENTS);
    recentEvents.splice(0, recentEvents.length, ...newestEvents);
  }

  function clearReconnectTimer() {
    if (reconnectTimer !== null) {
      clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }
  }

  function scheduleReconnect(token) {
    clearReconnectTimer();
    if (!token || token !== activeToken || navigator.onLine === false) return;
    const delay = Math.min(RECONNECT_MAX_MS, RECONNECT_BASE_MS * (2 ** reconnectAttempt));
    reconnectAttempt += 1;
    setStatus(connectionStatus, `${Math.ceil(delay / 1000)} sn sonra yeniden bağlanacak`, "status-waiting");
    reconnectTimer = setTimeout(() => {
      reconnectTimer = null;
      if (token === activeToken) void openStream(token);
    }, delay);
  }

  function safeText(value, fallback = "—") {
    if (value === null || value === undefined || value === "") return fallback;
    if (typeof value === "object") return fallback;
    return String(value);
  }

  function asArray(value) {
    if (Array.isArray(value)) return value;
    if (!value || typeof value !== "object") return [];
    return Object.entries(value).map(([name, details]) => (
      details && typeof details === "object" ? { name, ...details } : { name, status: details }
    ));
  }

  function clearChildren(element) {
    while (element.firstChild) element.removeChild(element.firstChild);
  }

  function addEmptyState(element, message) {
    const item = document.createElement("li");
    item.className = "empty";
    item.textContent = message;
    element.appendChild(item);
  }

  function eventStatus(event) {
    return safeText(event && event.status, "").toLowerCase();
  }

  function isComplete(event) {
    const value = eventStatus(event);
    return ["complete", "completed", "done", "success", "passed"].some((word) => value.includes(word));
  }

  function isFailure(event) {
    const value = `${eventStatus(event)} ${safeText(event && event.test_result, "").toLowerCase()}`;
    return ["error", "failed", "failure", "blocked", "fatal", "timeout"].some((word) => value.includes(word));
  }

  function orderedEvents(events) {
    return [...events].sort((left, right) => {
      const rightTime = Date.parse(right && right.timestamp) || 0;
      const leftTime = Date.parse(left && left.timestamp) || 0;
      return rightTime - leftTime;
    });
  }

  function latestBy(events, field) {
    const records = new Map();
    for (const event of orderedEvents(events)) {
      const key = safeText(event && event[field], "");
      if (key && !records.has(key)) records.set(key, event);
    }
    return [...records.values()];
  }

  function normalizeDashboard(payload, events) {
    const source = payload && typeof payload === "object" && !Array.isArray(payload) ? payload : {};
    const workstreams = latestBy(events, "workstream");
    const goal = source.master_goal && typeof source.master_goal === "object"
      ? source.master_goal
      : source.goal && typeof source.goal === "object"
        ? source.goal
        : {};

    const completed = asArray(source.completed_workstreams || source.completed || source.done);
    const queued = asArray(source.queued_workstreams || source.queued || source.queue);
    const agents = asArray(source.active_agents || source.agents).filter((agent) => !isComplete(agent) && !isFailure(agent));
    const blockers = asArray(source.blockers || source.failures || source.errors);

    const derivedCompleted = workstreams.filter(isComplete);
    const derivedQueued = workstreams.filter((event) => !isComplete(event) && !isFailure(event));
    const derivedAgents = latestBy(events, "agent_id").filter((event) => !isComplete(event) && !isFailure(event));
    const derivedBlockers = orderedEvents(events).filter(isFailure);

    const finalCompleted = completed.length ? completed : derivedCompleted;
    const finalQueued = queued.length ? queued : derivedQueued;
    const totalWorkstreams = finalCompleted.length + finalQueued.length;
    const rawProgress = goal.progress ?? goal.percent ?? source.goal_progress ?? source.progress;
    const derivedProgress = totalWorkstreams ? (finalCompleted.length / totalWorkstreams) * 100 : 0;
    const numericProgress = Number.isFinite(Number(rawProgress)) ? Number(rawProgress) : derivedProgress;
    const progress = Math.min(100, Math.max(0, numericProgress));
    const firstGoalEvent = orderedEvents(events).find((event) => event && event.goal_id);

    return {
      title: safeText(goal.title || goal.name || goal.description || source.goal_title || (firstGoalEvent && firstGoalEvent.goal_id), "Ana hedef tanımlanmadı"),
      progress,
      agents: agents.length ? agents : derivedAgents,
      queued: finalQueued,
      completed: finalCompleted,
      blockers: blockers.length ? blockers : derivedBlockers,
      shaSource: source.sha_matrix || source.shas || source.versions || {},
      updatedAt: source.updated_at || (events[0] && events[0].timestamp),
    };
  }

  function itemHeading(item) {
    if (!item || typeof item !== "object") return safeText(item);
    return safeText(item.name || item.title || item.workstream || item.agent_id || item.action || item.id);
  }

  function itemMetadata(item) {
    if (!item || typeof item !== "object") return "";
    return [item.status, item.stage, item.model, item.host, item.test_result, item.git_sha]
      .map((value) => safeText(value, ""))
      .filter(Boolean)
      .join(" · ");
  }

  function renderInfoList(element, items, emptyMessage) {
    clearChildren(element);
    if (!items.length) {
      addEmptyState(element, emptyMessage);
      return;
    }
    for (const value of items) {
      const item = document.createElement("li");
      const heading = document.createElement("div");
      const metadata = document.createElement("div");
      heading.className = "item-title";
      metadata.className = "item-meta";
      heading.textContent = itemHeading(value);
      metadata.textContent = itemMetadata(value);
      item.appendChild(heading);
      if (metadata.textContent) item.appendChild(metadata);
      element.appendChild(item);
    }
  }

  function displayTime(value) {
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? safeText(value, "Zaman bilinmiyor") : date.toLocaleString("tr-TR");
  }

  function renderEvents(events) {
    clearChildren(recentEventsList);
    if (!events.length) {
      addEmptyState(recentEventsList, "Olay bekleniyor");
      return;
    }
    for (const event of orderedEvents(events)) {
      const item = document.createElement("li");
      const metadata = document.createElement("div");
      const message = document.createElement("div");
      metadata.className = "event-meta";
      message.className = "event-message";
      if (isFailure(event)) item.className = "event-error";

      const context = [
        displayTime(event.timestamp),
        event.agent_id,
        event.model,
        event.host,
        event.workstream,
        event.stage,
        event.status,
      ].map((value) => safeText(value, "")).filter(Boolean);
      metadata.textContent = context.join(" · ");
      message.textContent = safeText(event.output_excerpt || event.action || event.test_result, "Ayrıntı paylaşılmadı");
      item.appendChild(metadata);
      item.appendChild(message);
      recentEventsList.appendChild(item);
    }
  }

  function shaFromSource(source, aliases) {
    for (const alias of aliases) {
      const value = source && source[alias];
      if (value && typeof value === "object") return safeText(value.sha || value.git_sha || value.value, "");
      if (value) return safeText(value, "");
    }
    return "";
  }

  function shaFromEvents(events, aliases) {
    const lowered = aliases.map((alias) => alias.toLowerCase());
    const match = orderedEvents(events).find((event) => {
      const host = safeText(event && event.host, "").toLowerCase();
      return event && event.git_sha && lowered.some((alias) => host.includes(alias));
    });
    return match ? safeText(match.git_sha, "") : "";
  }

  function renderShaMatrix(source, events) {
    const rows = [
      ["PC", ["pc", "local", "workstation"]],
      ["GitHub", ["github", "remote", "origin"]],
      ["VPS", ["vps", "server", "production", "prod"]],
    ].map(([label, aliases]) => ({
      label,
      sha: shaFromSource(source, aliases) || shaFromEvents(events, aliases),
    }));
    const reference = (rows.find((row) => row.label === "GitHub" && row.sha) || rows.find((row) => row.sha) || {}).sha;

    clearChildren(shaMatrix);
    for (const row of rows) {
      const tableRow = document.createElement("tr");
      const labelCell = document.createElement("td");
      const shaCell = document.createElement("td");
      const statusCell = document.createElement("td");
      const code = document.createElement("code");
      labelCell.textContent = row.label;
      code.textContent = safeText(row.sha);
      statusCell.textContent = !row.sha ? "Bekleniyor" : row.sha === reference ? "Uyumlu" : "Farklı";
      statusCell.className = !row.sha || row.sha === reference ? "sha-match" : "sha-mismatch";
      shaCell.appendChild(code);
      tableRow.appendChild(labelCell);
      tableRow.appendChild(shaCell);
      tableRow.appendChild(statusCell);
      shaMatrix.appendChild(tableRow);
    }
  }

  function renderDashboard(payload, events) {
    const view = normalizeDashboard(payload, events);
    goalTitle.textContent = view.title;
    goalProgress.value = view.progress;
    goalProgress.textContent = `${Math.round(view.progress)}%`;
    goalProgressLabel.textContent = `%${Math.round(view.progress)}`;
    agentCount.textContent = String(view.agents.length);
    queueCount.textContent = String(view.queued.length);
    completedCount.textContent = String(view.completed.length);
    blockerCount.textContent = String(view.blockers.length);
    lastUpdated.textContent = view.updatedAt ? `Güncelleme: ${displayTime(view.updatedAt)}` : "Henüz güncellenmedi";

    renderInfoList(activeAgents, view.agents, "Aktif ajan yok");
    renderInfoList(queuedWorkstreams, view.queued, "Bekleyen iş yok");
    renderInfoList(completedWorkstreams, view.completed, "Tamamlanan iş yok");
    renderInfoList(blockersList, view.blockers, "Engel bildirilmedi");
    renderEvents(events);
    renderShaMatrix(view.shaSource, events);
  }

  async function loadHistory(token) {
    const response = await fetch("/api/live/history", {
      method: "GET",
      headers: authHeaders(token, "application/json"),
      credentials: "same-origin",
      cache: "no-store",
    });
    if (token !== activeToken) return;

    if (!response.ok) {
      throw new Error(response.status === 401 ? "Kimlik doğrulama başarısız" : `Geçmiş alınamadı (${response.status})`);
    }

    const payload = await response.json();
    if (token !== activeToken) return;
    const events = Array.isArray(payload)
      ? payload
      : Array.isArray(payload.events)
        ? payload.events
        : Array.isArray(payload.history)
          ? payload.history
          : [];
    latestPayload = Array.isArray(payload) ? {} : payload;
    recentEvents.splice(0, recentEvents.length, ...events.filter((event) => event && typeof event === "object"));
    trimEvents();
    renderDashboard(latestPayload, recentEvents);
    setStatus(authStatus, "Kimlik doğrulandı", "status-connected");
  }

  function parseEventBlock(block, onEvent) {
    const dataLines = [];
    let eventName = "message";

    for (const line of block.split("\n")) {
      if (!line || line.startsWith(":")) continue;
      const colon = line.indexOf(":");
      const field = colon === -1 ? line : line.slice(0, colon);
      let value = colon === -1 ? "" : line.slice(colon + 1);
      if (value.startsWith(" ")) value = value.slice(1);
      if (field === "data") dataLines.push(value);
      if (field === "event") eventName = value;
    }

    if (!dataLines.length) return;
    try {
      onEvent(JSON.parse(dataLines.join("\n")), eventName);
    } catch (_error) {
      // Invalid or partial JSON is ignored; the next valid SSE frame continues.
    }
  }

  async function consumeEventStream(response, onEvent) {
    if (!response.body) throw new Error("Akış gövdesi bulunamadı");
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      buffer = buffer.replace(/\r\n/g, "\n");

      let boundary = buffer.indexOf("\n\n");
      while (boundary !== -1) {
        parseEventBlock(buffer.slice(0, boundary), onEvent);
        buffer = buffer.slice(boundary + 2);
        boundary = buffer.indexOf("\n\n");
      }
    }

    buffer += decoder.decode();
    if (buffer.trim()) parseEventBlock(buffer, onEvent);
  }

  function handleLiveEvent(event, eventName) {
    if (!event || typeof event !== "object") return;
    if ((eventName === "snapshot" || eventName === "history") && Array.isArray(event.events)) {
      latestPayload = event;
      recentEvents.splice(0, recentEvents.length, ...event.events.filter((item) => item && typeof item === "object"));
    } else {
      recentEvents.unshift(event);
    }
    trimEvents();
    reconnectAttempt = 0;
    renderDashboard(latestPayload, recentEvents);
  }

  async function openStream(token) {
    if (!token || token !== activeToken) return;
    clearReconnectTimer();
    if (streamController) streamController.abort();
    const controller = new AbortController();
    streamController = controller;
    let shouldReconnect = true;
    setStatus(connectionStatus, "Canlı akışa bağlanıyor", "status-waiting");

    try {
      const response = await fetch("/api/live/stream", {
        method: "GET",
        headers: authHeaders(token, "text/event-stream"),
        credentials: "same-origin",
        cache: "no-store",
        signal: controller.signal,
      });

      if (!response.ok) {
        if (response.status === 401) shouldReconnect = false;
        throw new Error(response.status === 401 ? "Kimlik doğrulama başarısız" : `Akış açılamadı (${response.status})`);
      }
      const contentType = response.headers.get("content-type") || "";
      if (!contentType.toLowerCase().includes("text/event-stream")) {
        throw new Error("Sunucu geçerli bir olay akışı döndürmedi");
      }

      setStatus(connectionStatus, "Canlı bağlantı açık", "status-connected");
      await consumeEventStream(response, handleLiveEvent);
      setStatus(connectionStatus, "Canlı bağlantı kapandı", "status-error");
    } catch (error) {
      if (error.name === "AbortError") {
        shouldReconnect = false;
      } else {
        const message = error instanceof Error ? error.message : "Bağlantı hatası";
        setStatus(connectionStatus, message, "status-error");
        if (message.includes("Kimlik")) {
          shouldReconnect = false;
          setStatus(authStatus, "Anahtar reddedildi", "status-error");
        }
      }
    } finally {
      if (streamController === controller) streamController = null;
    }

    if (shouldReconnect && token === activeToken) scheduleReconnect(token);
  }

  async function connect(token) {
    clearReconnectTimer();
    reconnectAttempt = 0;
    activeToken = token;
    if (streamController) streamController.abort();
    if (!token) {
      setStatus(authStatus, "Erişim anahtarı gerekli", "status-waiting");
      setStatus(connectionStatus, "Bağlantı bekleniyor", "status-muted");
      return;
    }
    setStatus(authStatus, "Anahtar doğrulanıyor", "status-waiting");
    try {
      await loadHistory(token);
    } catch (error) {
      if (token !== activeToken) return;
      const message = error instanceof Error ? error.message : "Geçmiş alınamadı";
      setStatus(authStatus, message, "status-error");
      return;
    }
    if (token !== activeToken) return;
    void openStream(token);
  }

  tokenForm.addEventListener("submit", (event) => {
    event.preventDefault();
    const token = tokenInput.value.trim();
    if (!token) {
      setStatus(authStatus, "Boş anahtar kullanılamaz", "status-error");
      return;
    }
    rememberToken(token);
    tokenInput.value = "";
    void connect(token);
  });

  tokenClear.addEventListener("click", () => {
    forgetToken();
    tokenInput.value = "";
    activeToken = "";
    reconnectAttempt = 0;
    clearReconnectTimer();
    if (streamController) streamController.abort();
    latestPayload = {};
    recentEvents.splice(0, recentEvents.length);
    renderDashboard(latestPayload, recentEvents);
    setStatus(authStatus, "Anahtar temizlendi", "status-muted");
    setStatus(connectionStatus, "Bağlantı kapalı", "status-muted");
  });

  window.addEventListener("online", () => {
    if (activeToken && !streamController) {
      reconnectAttempt = 0;
      scheduleReconnect(activeToken);
    }
  });

  window.addEventListener("offline", () => {
    clearReconnectTimer();
    if (streamController) streamController.abort();
    setStatus(connectionStatus, "Ağ bağlantısı yok", "status-error");
  });

  void connect(storedToken());
})();
