from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
DEPLOY_ROOT = REPO_ROOT / "deploy" / "agent.tutou.ai"
SYSTEMD_SERVICE = DEPLOY_ROOT / "systemd" / "tutou-agent-live.service"
CADDY_CONFIG = DEPLOY_ROOT / "caddy" / "agent-tutou-ai.caddy"
DEPLOY_README = DEPLOY_ROOT / "README.md"


def _template_text(path: Path) -> str:
    assert path.is_file(), f"missing deployment template: {path.relative_to(REPO_ROOT)}"
    return path.read_text(encoding="utf-8")


def test_systemd_service_uses_dedicated_identity_paths_and_loopback_bind() -> None:
    service = _template_text(SYSTEMD_SERVICE)

    assert "User=tutou-agent-live" in service
    assert "Group=tutou-agent-live" in service
    assert "WorkingDirectory=/opt/agent.tutou.ai" in service
    assert "EnvironmentFile=/etc/tutou-agent/live.env" in service
    assert (
        "ExecStart=/usr/bin/env uv run --no-sync uvicorn services.live_dashboard.app:app "
        "--host 127.0.0.1 --port 8791" in service
    )
    assert "--host 0.0.0.0" not in service
    assert "8787" not in service


def test_systemd_service_sets_persistent_live_database_path() -> None:
    service = _template_text(SYSTEMD_SERVICE)

    assert (
        "Environment=TUTOU_LIVE_DB=/var/lib/tutou-agent-live/live-events.db"
        in service
    )


def test_systemd_service_is_hardened_and_keeps_only_state_writable() -> None:
    service = _template_text(SYSTEMD_SERVICE)

    required_directives = {
        "StateDirectory=tutou-agent-live",
        "StateDirectoryMode=0750",
        "ReadWritePaths=/var/lib/tutou-agent-live",
        "UMask=0027",
        "NoNewPrivileges=true",
        "PrivateDevices=true",
        "PrivateTmp=true",
        "ProtectSystem=strict",
        "ProtectHome=true",
        "ProtectClock=true",
        "ProtectControlGroups=true",
        "ProtectHostname=true",
        "ProtectKernelLogs=true",
        "ProtectKernelModules=true",
        "ProtectKernelTunables=true",
        "ProtectProc=invisible",
        "ProcSubset=pid",
        "RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6",
        "RestrictNamespaces=true",
        "RestrictRealtime=true",
        "RestrictSUIDSGID=true",
        "LockPersonality=true",
        "MemoryDenyWriteExecute=true",
        "RemoveIPC=true",
        "CapabilityBoundingSet=",
        "AmbientCapabilities=",
        "SystemCallArchitectures=native",
    }
    missing = sorted(
        directive for directive in required_directives if directive not in service
    )
    assert not missing, f"missing systemd hardening directives: {missing}"
    assert "Environment=UV_CACHE_DIR=/var/lib/tutou-agent-live/uv-cache" in service
    assert "PrivateNetwork=true" not in service


def test_systemd_service_restarts_failed_processes() -> None:
    service = _template_text(SYSTEMD_SERVICE)

    assert "Restart=on-failure" in service
    assert "RestartSec=5s" in service
    assert "TimeoutStopSec=30s" in service


def test_caddy_routes_live_requests_to_loopback_and_everything_else_to_static() -> None:
    caddy = _template_text(CADDY_CONFIG)

    assert "agent.tutou.ai {" in caddy
    assert "@live path /live /live/* /api/live/*" in caddy
    assert "@live path /live*" not in caddy
    assert "handle @live {" in caddy
    assert "reverse_proxy 127.0.0.1:8791" in caddy
    assert "8787" not in caddy
    assert "handle {" in caddy
    assert "root * /srv/agent.tutou.ai/current" in caddy
    assert "file_server" in caddy


def test_caddy_disables_live_response_caching_and_proxy_buffering() -> None:
    caddy = _template_text(CADDY_CONFIG)

    assert 'header_down Cache-Control "no-store, no-cache, must-revalidate"' in caddy
    assert 'header_down Pragma "no-cache"' in caddy
    assert 'header_down Expires "0"' in caddy
    assert 'header_down X-Accel-Buffering "no"' in caddy
    assert "flush_interval -1" in caddy


def test_caddy_sets_site_wide_security_headers() -> None:
    caddy = _template_text(CADDY_CONFIG)

    required_headers = {
        'Strict-Transport-Security "max-age=63072000; includeSubDomains; preload"',
        'X-Content-Type-Options "nosniff"',
        'X-Frame-Options "DENY"',
        'Referrer-Policy "strict-origin-when-cross-origin"',
        'Permissions-Policy "camera=(), microphone=(), geolocation=()"',
        'Cross-Origin-Opener-Policy "same-origin"',
        "Content-Security-Policy \"default-src 'self'; connect-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'\"",
        "-Server",
    }
    missing = sorted(header for header in required_headers if header not in caddy)
    assert not missing, f"missing Caddy security headers: {missing}"


def test_readme_documents_nonsecret_live_database_path() -> None:
    readme = _template_text(DEPLOY_README)

    assert "TUTOU_LIVE_DB=/var/lib/tutou-agent-live/live-events.db" in readme


def test_readme_documents_secure_live_token_generation_and_rotation() -> None:
    readme = _template_text(DEPLOY_README)

    required_guidance = {
        "`TUTOU_LIVE_TOKEN`",
        "openssl rand -hex 32",
        "To rotate the token",
        "update every event publisher",
        "sudo systemctl restart tutou-agent-live.service",
    }
    missing = sorted(item for item in required_guidance if item not in readme)
    assert not missing, f"missing live token generation or rotation guidance: {missing}"
    assert "TUTOU_LIVE_TOKEN=" not in readme


def test_readme_has_copy_pasteable_install_and_validation_commands() -> None:
    readme = _template_text(DEPLOY_README)

    required_commands = {
        "getent passwd tutou-agent-live >/dev/null || sudo useradd --system --user-group --home-dir /var/lib/tutou-agent-live --shell /usr/sbin/nologin tutou-agent-live",
        "sudoedit /etc/tutou-agent/live.env",
        "sudo install -D -o root -g root -m 0644 deploy/agent.tutou.ai/systemd/tutou-agent-live.service /etc/systemd/system/tutou-agent-live.service",
        "sudo install -D -o root -g root -m 0644 deploy/agent.tutou.ai/caddy/agent-tutou-ai.caddy /etc/caddy/conf.d/agent-tutou-ai.caddy",
        "sudo systemd-analyze verify /etc/systemd/system/tutou-agent-live.service",
        "sudo caddy validate --adapter caddyfile --config /etc/caddy/Caddyfile",
        "sudo systemctl daemon-reload",
        "sudo systemctl enable --now tutou-agent-live.service",
        "sudo systemctl reload caddy",
    }
    missing = sorted(command for command in required_commands if command not in readme)
    assert not missing, f"missing install or validation commands: {missing}"
    assert "8787" not in readme
    for secret_assignment in ("API_KEY=", "TOKEN=", "PASSWORD=", "SECRET="):
        assert secret_assignment not in readme


def test_readme_has_exact_template_rollback_commands() -> None:
    readme = _template_text(DEPLOY_README)

    required_commands = {
        "sudo test -f /etc/systemd/system/tutou-agent-live.service.previous",
        "sudo test -f /etc/caddy/conf.d/agent-tutou-ai.caddy.previous",
        "sudo install -o root -g root -m 0644 /etc/systemd/system/tutou-agent-live.service.previous /etc/systemd/system/tutou-agent-live.service",
        "sudo install -o root -g root -m 0644 /etc/caddy/conf.d/agent-tutou-ai.caddy.previous /etc/caddy/conf.d/agent-tutou-ai.caddy",
        "sudo systemctl restart tutou-agent-live.service",
    }
    missing = sorted(command for command in required_commands if command not in readme)
    assert not missing, f"missing rollback commands: {missing}"


def test_readme_has_local_and_public_health_commands() -> None:
    readme = _template_text(DEPLOY_README)

    required_commands = {
        "sudo systemctl is-active --quiet tutou-agent-live.service",
        "sudo systemctl is-active --quiet caddy",
        "curl --fail --silent --show-error http://127.0.0.1:8791/api/live/health",
        "curl --fail --silent --show-error https://agent.tutou.ai/api/live/health",
    }
    missing = sorted(command for command in required_commands if command not in readme)
    assert not missing, f"missing health commands: {missing}"
