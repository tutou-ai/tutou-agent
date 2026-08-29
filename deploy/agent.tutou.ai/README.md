# agent.tutou.ai deployment templates

These files install the live dashboard as a locked-down system service behind
Caddy. The application binds only to `127.0.0.1:8791`; Caddy is the public
entry point. Run every command below from the repository root.

This directory contains templates only. It does not deploy a release. Before
installing them, stage the application at `/opt/agent.tutou.ai`, publish the
static site at `/srv/agent.tutou.ai/current`, and install `uv` and Caddy. The
main `/etc/caddy/Caddyfile` must import
`/etc/caddy/conf.d/*.caddy`.

Install the managed Python inside `/opt/agent.tutou.ai` before starting the
hardened service. A root-owned uv Python under `/root/.local/share` is not
traversable by `tutou-agent-live` and will fail with `Permission denied`:

```bash
cd /opt/agent.tutou.ai
UV_PYTHON_INSTALL_DIR=/opt/agent.tutou.ai/.python /usr/local/bin/uv python install 3.13
UV_PYTHON_INSTALL_DIR=/opt/agent.tutou.ai/.python /usr/local/bin/uv sync --locked --python 3.13
readlink -f /opt/agent.tutou.ai/.venv/bin/python3
```

The resolved interpreter must be under `/opt/agent.tutou.ai/.python/`, not
under `/root` or another user's home.

## Install

Create the unprivileged service identity and the two required directories:

```bash
getent passwd tutou-agent-live >/dev/null || sudo useradd --system --user-group --home-dir /var/lib/tutou-agent-live --shell /usr/sbin/nologin tutou-agent-live
sudo install -d -o root -g tutou-agent-live -m 0750 /etc/tutou-agent
sudo install -d -o root -g root -m 0755 /etc/caddy/conf.d
```

Create the required environment file without truncating an existing one, lock
its permissions, then edit it directly. Keep credentials out of this README
and out of the repository. The service unit sets the nonsecret database
location explicitly as
`TUTOU_LIVE_DB=/var/lib/tutou-agent-live/live-events.db`; keep that path in the
unit rather than duplicating it in the credentials file.

```bash
sudo touch /etc/tutou-agent/live.env
sudo chown root:tutou-agent-live /etc/tutou-agent/live.env
sudo chmod 0640 /etc/tutou-agent/live.env
sudoedit /etc/tutou-agent/live.env
```

Generate a fresh 256-bit bearer token on a trusted deployment host:

```bash
openssl rand -hex 32
```

Store the generated output only as the value of `TUTOU_LIVE_TOKEN` in
`/etc/tutou-agent/live.env`; do not put the token on a command line, in this
README, or in the repository. To rotate the token, generate a replacement with
the same command, update every event publisher and the protected environment
file, then activate the replacement and invalidate the old token by restarting
the service:

```bash
sudoedit /etc/tutou-agent/live.env
sudo systemctl restart tutou-agent-live.service
```

Make timestamp-independent rollback copies of any currently installed
templates, then install the new versions:

```bash
if sudo test -f /etc/systemd/system/tutou-agent-live.service; then sudo cp -a /etc/systemd/system/tutou-agent-live.service /etc/systemd/system/tutou-agent-live.service.previous; fi
if sudo test -f /etc/caddy/conf.d/agent-tutou-ai.caddy; then sudo cp -a /etc/caddy/conf.d/agent-tutou-ai.caddy /etc/caddy/conf.d/agent-tutou-ai.caddy.previous; fi
sudo install -D -o root -g root -m 0644 deploy/agent.tutou.ai/systemd/tutou-agent-live.service /etc/systemd/system/tutou-agent-live.service
sudo install -D -o root -g root -m 0644 deploy/agent.tutou.ai/caddy/agent-tutou-ai.caddy /etc/caddy/conf.d/agent-tutou-ai.caddy
```

If the main Caddyfile does not already import the site directory, add the
import exactly once:

```bash
if ! sudo grep -Fqx 'import /etc/caddy/conf.d/*.caddy' /etc/caddy/Caddyfile; then printf '\nimport /etc/caddy/conf.d/*.caddy\n' | sudo tee -a /etc/caddy/Caddyfile >/dev/null; fi
```

Validate both installed configurations before changing running services:

```bash
sudo systemd-analyze verify /etc/systemd/system/tutou-agent-live.service
sudo caddy validate --adapter caddyfile --config /etc/caddy/Caddyfile
```

Only after both validators succeed, load and start the service, then reload
Caddy:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now tutou-agent-live.service
sudo systemctl reload caddy
```

## Rollback the templates

The install commands preserve the previously installed unit and site file with
a `.previous` suffix. This rollback changes only those templates; release and
static-asset rollback remains the release pipeline's responsibility. Run the
checks first so a first-time install cannot silently roll back to nothing:

```bash
set -euo pipefail
sudo test -f /etc/systemd/system/tutou-agent-live.service.previous
sudo test -f /etc/caddy/conf.d/agent-tutou-ai.caddy.previous
sudo install -o root -g root -m 0644 /etc/systemd/system/tutou-agent-live.service.previous /etc/systemd/system/tutou-agent-live.service
sudo install -o root -g root -m 0644 /etc/caddy/conf.d/agent-tutou-ai.caddy.previous /etc/caddy/conf.d/agent-tutou-ai.caddy
sudo systemd-analyze verify /etc/systemd/system/tutou-agent-live.service
sudo caddy validate --adapter caddyfile --config /etc/caddy/Caddyfile
sudo systemctl daemon-reload
sudo systemctl restart tutou-agent-live.service
sudo systemctl reload caddy
```

## Health checks

Run all four checks. The first two must exit zero, and both HTTP requests must
return `{"status":"ok"}`. The loopback request tests Uvicorn directly; the
HTTPS request also tests DNS, TLS, Caddy routing, and the upstream service.

```bash
sudo systemctl is-active --quiet tutou-agent-live.service
sudo systemctl is-active --quiet caddy
curl --fail --silent --show-error http://127.0.0.1:8791/api/live/health
curl --fail --silent --show-error https://agent.tutou.ai/api/live/health
```

For service diagnostics without exposing the environment file:

```bash
sudo journalctl -u tutou-agent-live.service -n 100 --no-pager
```
