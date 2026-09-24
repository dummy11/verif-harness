"""Local, dependency-free Human dashboard for the verif-harness control plane."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from .store import HarnessError, ProjectStore, atomic_json, now


MAX_REQUEST_BYTES = 1_048_576
LOOPBACK_HOSTS = {"127.0.0.1", "localhost"}
DASHBOARD_RUNTIME_FILE = "dashboard-runtime.json"
DASHBOARD_LOG_FILE = "dashboard.log"
DASHBOARD_ACCESS_TOKEN_FILE = "access-token"
DASHBOARD_HUB_SCHEMA = "DashboardHubHealth/2"
LEGACY_DASHBOARD_HUB_SCHEMA = "DashboardHubHealth/1"
DASHBOARD_RUNTIME_SCHEMA = "DashboardRuntime/3"
DASHBOARD_PROJECT_SCHEMA = "DashboardProjectRegistration/1"
DASHBOARD_REGISTRY_ENV = "VERIF_HARNESS_DASHBOARD_REGISTRY_DIR"
DASHBOARD_DEFAULT_PORT = 8765
DASHBOARD_AUTO_PORT_COUNT = 32
DASHBOARD_ASSETS = {
    "/assets/markdown-it.min.js": "vendor/markdown-it/markdown-it.min.js",
    "/assets/dashboard-markdown.js": "dashboard_markdown.js",
}


def dashboard_registry_dir(registry_dir: Path | None = None) -> Path:
    """Return the machine-local routing registry used by the shared Dashboard."""
    if registry_dir is not None:
        return registry_dir.resolve()
    configured = os.environ.get(DASHBOARD_REGISTRY_ENV, "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return (Path.home() / ".verif-harness" / "dashboard").resolve()


def dashboard_owner_id(registry_dir: Path | None = None) -> str:
    """Return a stable, secret-derived identity for one account registry."""
    token = dashboard_access_token(registry_dir)
    identity = f"verif-harness-dashboard-owner\0{token}"
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]


def dashboard_access_token(registry_dir: Path | None = None) -> str:
    """Return the current account's persistent secret used to protect the local UI."""
    directory = dashboard_registry_dir(registry_dir)
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        directory.chmod(0o700)
    except OSError:
        pass
    path = directory / DASHBOARD_ACCESS_TOKEN_FILE
    if path.is_file():
        try:
            path.chmod(0o600)
        except OSError:
            pass
        token = path.read_text(encoding="utf-8").strip()
        if len(token) < 32:
            raise HarnessError("Dashboard 访问令牌文件无效；请检查账号级 Dashboard 注册目录")
        return token
    token = secrets.token_urlsafe(32)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    try:
        descriptor = os.open(path, flags, 0o600)
    except FileExistsError:
        token = path.read_text(encoding="utf-8").strip()
        if len(token) < 32:
            raise HarnessError("Dashboard 访问令牌文件无效；请检查账号级 Dashboard 注册目录")
        return token
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        stream.write(f"{token}\n")
    return token


def dashboard_project_id(root: Path) -> str:
    """Stable opaque routing id; it does not create a relationship between projects."""
    return hashlib.sha256(str(root.resolve()).encode("utf-8")).hexdigest()[:24]


def _project_registration_path(project_id: str, registry_dir: Path | None = None) -> Path:
    if not project_id or any(character not in "0123456789abcdef" for character in project_id):
        raise HarnessError("Dashboard project id 格式无效")
    return dashboard_registry_dir(registry_dir) / "projects" / f"{project_id}.json"


def register_dashboard_project(
    store: ProjectStore, registry_dir: Path | None = None,
) -> dict[str, Any]:
    """Publish only routing/display metadata; project facts remain in its own store."""
    store.require()
    manifest = json.loads((store.state / "project.json").read_text(encoding="utf-8"))
    project_id = dashboard_project_id(store.root)
    registration = {
        "schema": DASHBOARD_PROJECT_SCHEMA,
        "id": project_id,
        "root": str(store.root),
        "name": str(manifest.get("project_name") or store.root.name),
        "dut_top": str((manifest.get("dut") or {}).get("top_module") or "未登记 DUT"),
        "updated_at": now(),
    }
    atomic_json(_project_registration_path(project_id, registry_dir), registration)
    return registration


def unregister_dashboard_project(
    store: ProjectStore, registry_dir: Path | None = None,
) -> None:
    _project_registration_path(dashboard_project_id(store.root), registry_dir).unlink(missing_ok=True)


def registered_dashboard_projects(registry_dir: Path | None = None) -> list[dict[str, Any]]:
    """List valid independent projects; stale/tampered registrations are ignored."""
    projects_dir = dashboard_registry_dir(registry_dir) / "projects"
    if not projects_dir.is_dir():
        return []
    registrations: list[dict[str, Any]] = []
    for path in sorted(projects_dir.glob("*.json")):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            root = Path(str(value.get("root", ""))).resolve()
            project_id = str(value.get("id", ""))
            store = ProjectStore(root)
            if (
                value.get("schema") != DASHBOARD_PROJECT_SCHEMA
                or path.stem != project_id
                or dashboard_project_id(root) != project_id
                or not store.initialized
            ):
                continue
            registrations.append({
                "id": project_id,
                "name": str(value.get("name") or root.name),
                "dut_top": str(value.get("dut_top") or "未登记 DUT"),
                "root": str(root),
                "updated_at": value.get("updated_at"),
            })
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
            continue
    return sorted(registrations, key=lambda item: (item["name"].lower(), item["root"]))


def dashboard_project_store(
    project_id: str, registry_dir: Path | None = None,
) -> ProjectStore:
    path = _project_registration_path(project_id, registry_dir)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise HarnessError("所选项目未注册到当前 Dashboard") from exc
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HarnessError(f"无法读取 Dashboard 项目注册信息: {exc}") from exc
    root = Path(str(value.get("root", ""))).resolve()
    if (
        value.get("schema") != DASHBOARD_PROJECT_SCHEMA
        or value.get("id") != project_id
        or dashboard_project_id(root) != project_id
    ):
        raise HarnessError("Dashboard 项目注册信息无效")
    store = ProjectStore(root)
    store.require()
    store.ensure_dashboard_schema()
    return store


class DashboardHTTPServer(ThreadingHTTPServer):
    """One local UI/router; every project keeps a completely separate ProjectStore."""

    daemon_threads = True

    def __init__(
        self, address: tuple[str, int], store: ProjectStore,
        registry_dir: Path | None = None,
    ):
        super().__init__(address, DashboardHandler)
        self.registry_dir = dashboard_registry_dir(registry_dir)
        self.owner_id = dashboard_owner_id(self.registry_dir)
        self.write_token = dashboard_access_token(self.registry_dir)
        registration = register_dashboard_project(store, self.registry_dir)
        self.default_project_id = registration["id"]
        # Retained for small third-party integrations; request handling never routes through it.
        self.store = store

    def projects(self) -> list[dict[str, Any]]:
        return registered_dashboard_projects(self.registry_dir)

    def project_store(self, project_id: str) -> ProjectStore:
        return dashboard_project_store(project_id, self.registry_dir)


class DashboardHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server: DashboardHTTPServer

    def log_message(self, _format: str, *_args: object) -> None:
        return

    def _headers(self, status: HTTPStatus, content_type: str, length: int | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        if length is not None:
            self.send_header("Content-Length", str(length))
        self.end_headers()

    def _json(self, value: object, status: HTTPStatus = HTTPStatus.OK) -> None:
        payload = json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")
        self._headers(status, "application/json; charset=utf-8", len(payload))
        self.wfile.write(payload)

    def _body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > MAX_REQUEST_BYTES:
            raise HarnessError("请求正文为空或超过 1 MiB")
        try:
            value = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise HarnessError("请求正文必须是 UTF-8 JSON object") from exc
        if not isinstance(value, dict):
            raise HarnessError("请求正文必须是 JSON object")
        return value

    def _authorized(self, parsed: urllib.parse.ParseResult | None = None) -> bool:
        provided = self.headers.get("X-Verif-Token", "")
        if not provided and parsed is not None:
            provided = urllib.parse.parse_qs(parsed.query).get("token", [""])[0]
        return hmac.compare_digest(provided, self.server.write_token)

    def _selected_project_id(self, supplied: str = "") -> str:
        project_id = supplied.strip()
        if project_id:
            return project_id
        projects = self.server.projects()
        if len(projects) == 1:
            return str(projects[0]["id"])
        if not projects:
            raise HarnessError("当前 Dashboard 没有已注册项目")
        raise HarnessError("请先选择一个项目")

    def _snapshot(self, store: ProjectStore, project_id: str) -> dict[str, Any]:
        return {**store.dashboard_snapshot(), "dashboard_project_id": project_id}

    def do_GET(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/healthz" and not self._authorized(parsed):
            self._json({"error": "invalid dashboard access token"}, HTTPStatus.FORBIDDEN)
            return
        if parsed.path == "/":
            source = Path(__file__).with_name("dashboard.html").read_text(encoding="utf-8")
            source = source.replace("__VERIF_DASHBOARD_TOKEN__", self.server.write_token)
            payload = source.encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'none'; style-src 'unsafe-inline'; script-src 'self' 'unsafe-inline'; "
                "connect-src 'self'; img-src 'self' data:; base-uri 'none'; form-action 'self'",
            )
            self.end_headers()
            self.wfile.write(payload)
        elif parsed.path in DASHBOARD_ASSETS:
            # Exact allowlist, behind the same access-token check as the page.
            payload = (Path(__file__).parent / DASHBOARD_ASSETS[parsed.path]).read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/javascript; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(payload)
        elif parsed.path == "/api/projects":
            projects = self.server.projects()
            self._json({
                "schema": "DashboardProjectList/1",
                "projects": projects,
                "default_project": (
                    self.server.default_project_id
                    if any(item["id"] == self.server.default_project_id for item in projects)
                    else (projects[0]["id"] if projects else None)
                ),
            })
        elif parsed.path == "/api/snapshot":
            try:
                query = urllib.parse.parse_qs(parsed.query)
                project_id = self._selected_project_id(query.get("project", [""])[0])
                self._json(self._snapshot(self.server.project_store(project_id), project_id))
            except HarnessError as exc:
                self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        elif parsed.path == "/api/document":
            try:
                query = urllib.parse.parse_qs(parsed.query)
                project_id = self._selected_project_id(query.get("project", [""])[0])
                selector = query.get("selector", [""])[0]
                self._json(self.server.project_store(project_id).document_content(selector))
            except HarnessError as exc:
                self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        elif parsed.path == "/api/events":
            try:
                query = urllib.parse.parse_qs(parsed.query)
                project_id = self._selected_project_id(query.get("project", [""])[0])
                self._events(self.server.project_store(project_id), project_id)
            except HarnessError as exc:
                self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        elif parsed.path == "/healthz":
            projects = self.server.projects()
            self._json({
                "schema": DASHBOARD_HUB_SCHEMA,
                "status": "ok",
                "pid": os.getpid(),
                "owner_id": self.server.owner_id,
                "project_count": len(projects),
                "projects": [item["id"] for item in projects],
            })
        else:
            self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)

    def _events(self, store: ProjectStore, project_id: str) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        previous = ""
        last_ping = 0.0
        try:
            while True:
                if not _project_registration_path(project_id, self.server.registry_dir).is_file():
                    return
                snapshot = self._snapshot(store, project_id)
                if snapshot["version"] != previous:
                    data = json.dumps(snapshot, ensure_ascii=False, separators=(",", ":"))
                    self.wfile.write(f"event: snapshot\ndata: {data}\n\n".encode("utf-8"))
                    self.wfile.flush()
                    previous = snapshot["version"]
                    last_ping = time.monotonic()
                elif time.monotonic() - last_ping >= 15:
                    self.wfile.write(b": keepalive\n\n")
                    self.wfile.flush()
                    last_ping = time.monotonic()
                time.sleep(1)
        except (BrokenPipeError, ConnectionResetError, OSError):
            return

    def do_POST(self) -> None:  # noqa: N802
        if not self._authorized():
            self._json({"error": "invalid dashboard write token"}, HTTPStatus.FORBIDDEN)
            return
        try:
            body = self._body()
            project_id = self._selected_project_id(str(body.pop("dashboard_project", "")))
            store = self.server.project_store(project_id)
            path = urllib.parse.urlparse(self.path).path
            if path == "/api/registrations/remove":
                unregister_dashboard_project(store, self.server.registry_dir)
                (store.state / DASHBOARD_RUNTIME_FILE).unlink(missing_ok=True)
                remaining = self.server.projects()
                self._json({
                    "result": {
                        "status": "UNREGISTERED", "project_id": project_id,
                        "remaining_projects": len(remaining),
                    },
                    "projects": remaining,
                })
                if not remaining:
                    threading.Timer(0.2, self.server.shutdown).start()
                return
            result = self._mutate(path, body, store)
            self._json({"result": result, "snapshot": self._snapshot(store, project_id)})
        except HarnessError as exc:
            self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        except Exception as exc:  # pragma: no cover - safety boundary for the local HTTP surface
            self._json({"error": f"dashboard request failed: {exc}"}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def _mutate(
        self, path: str, body: dict[str, Any], store: ProjectStore,
    ) -> dict[str, Any]:
        if path == "/api/human-actions":
            return store.add_human_action(
                str(body.get("target", "")), str(body.get("action", "")),
                str(body.get("reviewer", "")), str(body.get("reason", "")),
                body.get("payload") if isinstance(body.get("payload"), dict) else {},
            )
        if path == "/api/human-actions/resolve":
            return store.resolve_human_action(
                str(body.get("id", "")), str(body.get("reviewer", "")),
                str(body.get("resolution", "")), str(body.get("status", "RESOLVED")),
            )
        if path == "/api/agent-questions/answer":
            return store.answer_agent_question(
                str(body.get("id", "")), str(body.get("option", "")),
                str(body.get("reviewer", "")), str(body.get("answer_text", "")),
            )
        if path == "/api/reviews/workstream":
            verdict = str(body.get("verdict", ""))
            if verdict not in {"approve", "reject", "modify", "clarify"}:
                raise HarnessError("workstream verdict 必须是 approve/reject/modify/clarify")
            reviewer = str(body.get("reviewer", "")).strip()
            reason = str(body.get("reason", "")).strip()
            if not reviewer or not reason:
                raise HarnessError("Dashboard Workstream review 必须填写 reviewer 和 reason")
            return store.review_workstream(
                str(body.get("workstream", "")), verdict, reviewer, reason,
            )
        if path == "/api/reviews/document":
            verdict = str(body.get("verdict", ""))
            if verdict not in {"approve", "reject", "modify", "clarify"}:
                raise HarnessError("document verdict 必须是 approve/reject/modify/clarify")
            reviewer = str(body.get("reviewer", "")).strip()
            notes = str(body.get("notes", "")).strip()
            if not reviewer or not notes:
                raise HarnessError("Dashboard 文档评审必须填写 reviewer 和 notes")
            return store.review_document(str(body.get("document", "")), verdict, reviewer, notes)
        if path == "/api/reviews/document-delivery":
            verdict = str(body.get("verdict", ""))
            if verdict not in {"approve", "provisional", "reject", "modify", "clarify"}:
                raise HarnessError(
                    "document delivery verdict 必须是 approve/provisional/reject/modify/clarify"
                )
            reviewer = str(body.get("reviewer", "")).strip()
            notes = str(body.get("notes", "")).strip()
            definition_digest = str(body.get("definition_digest", "")).strip()
            document_digest = str(body.get("document_digest", "")).strip()
            if not reviewer or not notes or not definition_digest or not document_digest:
                raise HarnessError(
                    "文档交付节点评审必须填写 reviewer、notes、definition_digest 和 document_digest"
                )
            change_items = body.get("change_items", [])
            if not isinstance(change_items, list):
                raise HarnessError("文档交付审批的 change_items 必须是数组")
            return store.review_document_delivery(
                str(body.get("node", "")), definition_digest, document_digest,
                verdict, reviewer, notes,
                str(body.get("provisional_owner", "")),
                str(body.get("review_trigger", "")),
                change_items,
            )
        if path == "/api/reviews/agent-check":
            checked_by = str(body.get("checked_by", "")).strip()
            summary = str(body.get("summary", "")).strip()
            if not checked_by or not summary:
                raise HarnessError("Agent 检查必须填写 checked_by 和 summary")
            return store.complete_review_agent_check(
                str(body.get("review_id", "")), checked_by, summary,
            )
        if path == "/api/reviews/node-plan-section":
            verdict = str(body.get("verdict", ""))
            if verdict not in {"approve", "reject", "modify", "clarify"}:
                raise HarnessError("node plan section verdict 必须是 approve/reject/modify/clarify")
            reviewer = str(body.get("reviewer", "")).strip()
            reason = str(body.get("reason", "")).strip()
            digest = str(body.get("definition_digest", "")).strip()
            if not reviewer or not reason or not digest:
                raise HarnessError("文档撰写方案区块审批必须填写评审人、理由和当前方案摘要")
            change_items = body.get("change_items", [])
            if not isinstance(change_items, list):
                raise HarnessError("文档撰写方案审批的 change_items 必须是数组")
            return store.review_node_plan_section(
                str(body.get("node", "")), str(body.get("section", "")),
                digest, verdict, reviewer, reason, change_items,
            )
        if path == "/api/reviews/node-plan-complete":
            reviewer = str(body.get("reviewer", "")).strip()
            reason = str(body.get("reason", "")).strip()
            digest = str(body.get("definition_digest", "")).strip()
            if not reviewer or not reason or not digest:
                raise HarnessError("文档撰写方案审批完成必须填写审批人、完成说明和当前方案摘要")
            return store.complete_node_plan_review(
                str(body.get("node", "")), digest, reviewer, reason,
            )
        if path == "/api/reviews/node-closure":
            verdict = str(body.get("verdict", ""))
            if verdict not in {"approve", "reject", "modify", "clarify"}:
                raise HarnessError("node closure verdict 必须是 approve/reject/modify/clarify")
            reviewer = str(body.get("reviewer", "")).strip()
            reason = str(body.get("reason", "")).strip()
            digest = str(body.get("assessment_digest", "")).strip()
            if not reviewer or not reason or not digest:
                raise HarnessError("节点 Closure 评审必须填写 reviewer、reason 和 assessment_digest")
            return store.review_node_closure(
                str(body.get("node", "")), digest, verdict, reviewer, reason,
            )
        if path == "/api/waive":
            reviewer = str(body.get("reviewer", "")).strip()
            reason = str(body.get("reason", "")).strip()
            if not reviewer or not reason or body.get("confirm") is not True:
                raise HarnessError("waiver 必须填写 reviewer/reason 并显式确认")
            return store.waive_node(str(body.get("node", "")), reviewer, reason)
        if path == "/api/freeze":
            reviewer = str(body.get("reviewer", "")).strip()
            reason = str(body.get("reason", "")).strip()
            if not reviewer or not reason or body.get("confirm") is not True:
                raise HarnessError("freeze 必须填写 reviewer/reason 并显式确认")
            target = str(body.get("target", ""))
            return store.freeze_final(reviewer, reason) if target.lower() == "final" else store.freeze_workstream(
                target, reviewer, reason,
            )
        if path == "/api/workstreams/restart":
            workstream = str(body.get("workstream", "")).upper()
            if workstream != "VDOC":
                raise HarnessError("Dashboard 当前只支持重新启动 VDOC 工作流")
            return store.restart_vdoc_workflow(
                str(body.get("reviewer", "")), str(body.get("reason", "")),
                body.get("confirm") is True,
            )
        raise HarnessError(f"不支持的 Dashboard 写操作: {path}")


def dashboard_url(server: DashboardHTTPServer) -> str:
    host, port = server.server_address[:2]
    display_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
    return f"http://{display_host}:{port}/"


def _dashboard_health(host: str, port: int) -> dict[str, Any] | None:
    try:
        with urllib.request.urlopen(f"http://{host}:{port}/healthz", timeout=0.35) as response:
            value = json.loads(response.read().decode("utf-8"))
        return value if isinstance(value, dict) else None
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None


def _port_accepts_connections(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.25):
            return True
    except OSError:
        return False


def _dashboard_runtime(store: ProjectStore) -> dict[str, Any] | None:
    path = store.state / DASHBOARD_RUNTIME_FILE
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HarnessError(f"无法读取 Dashboard 运行记录: {exc}") from exc
    if not isinstance(value, dict) or value.get("schema") not in {
        "DashboardRuntime/1", "DashboardRuntime/2", DASHBOARD_RUNTIME_SCHEMA,
    }:
        raise HarnessError("Dashboard 运行记录格式无效")
    if str(value.get("project", "")) != str(store.root):
        raise HarnessError("Dashboard 运行记录不属于当前项目")
    runtime_host = value.get("host")
    runtime_port = value.get("port")
    if runtime_host not in LOOPBACK_HOSTS:
        raise HarnessError("Dashboard 运行记录包含无效监听地址")
    if not isinstance(runtime_port, int) or runtime_port <= 0 or runtime_port > 65535:
        raise HarnessError("Dashboard 运行记录包含无效端口")
    if (
        value.get("schema") in {"DashboardRuntime/2", DASHBOARD_RUNTIME_SCHEMA}
        and value.get("project_id") != dashboard_project_id(store.root)
    ):
        raise HarnessError("Dashboard 运行记录的项目标识无效")
    if (
        value.get("schema") == DASHBOARD_RUNTIME_SCHEMA
        and value.get("owner_id") != dashboard_owner_id()
    ):
        raise HarnessError("Dashboard 运行记录不属于当前系统账号")
    return value


def _is_dashboard_hub(health: dict[str, Any] | None) -> bool:
    return bool(health and health.get("schema") in {
        LEGACY_DASHBOARD_HUB_SCHEMA, DASHBOARD_HUB_SCHEMA,
    })


def _is_owned_dashboard_hub(
    health: dict[str, Any] | None, registry_dir: Path | None = None,
) -> bool:
    return bool(
        health
        and health.get("schema") == DASHBOARD_HUB_SCHEMA
        and hmac.compare_digest(
            str(health.get("owner_id", "")), dashboard_owner_id(registry_dir),
        )
    )


def _automatic_dashboard_ports(preferred: int | None = None) -> list[int]:
    ports: list[int] = []
    if isinstance(preferred, int) and 0 < preferred <= 65535:
        ports.append(preferred)
    for candidate in range(
        DASHBOARD_DEFAULT_PORT, DASHBOARD_DEFAULT_PORT + DASHBOARD_AUTO_PORT_COUNT,
    ):
        if candidate <= 65535 and candidate not in ports:
            ports.append(candidate)
    return ports


def _select_dashboard_endpoint(
    host: str, requested_port: int | None, preferred_port: int | None = None,
) -> dict[str, Any]:
    """Find this account's hub first, otherwise select an unoccupied auto port."""
    ports = [requested_port] if requested_port is not None else _automatic_dashboard_ports(
        preferred_port,
    )
    first_free: int | None = None
    skipped_ports: list[dict[str, Any]] = []
    foreign_hubs = 0
    for candidate in ports:
        if candidate is None:
            continue
        health = _dashboard_health(host, candidate)
        if _is_owned_dashboard_hub(health):
            return {
                "port": candidate, "health": health, "conflict": None,
                "skipped_ports": skipped_ports,
            }
        if _is_dashboard_hub(health):
            if health and health.get("schema") == DASHBOARD_HUB_SCHEMA:
                foreign_hubs += 1
                if requested_port is not None:
                    return {
                        "port": candidate, "health": health,
                        "conflict": "OTHER_USER_DASHBOARD",
                    }
                skipped_ports.append({"port": candidate, "reason": "OTHER_USER_DASHBOARD"})
                continue
            if requested_port is not None:
                return {
                    "port": candidate, "health": health,
                    "conflict": "LEGACY_SHARED_DASHBOARD",
                }
            skipped_ports.append({"port": candidate, "reason": "LEGACY_SHARED_DASHBOARD"})
            continue
        if health is not None:
            if requested_port is not None:
                return {
                    "port": candidate, "health": health,
                    "conflict": "LEGACY_SINGLE_PROJECT_DASHBOARD",
                }
            skipped_ports.append({
                "port": candidate, "reason": "LEGACY_SINGLE_PROJECT_DASHBOARD",
            })
            continue
        if _port_accepts_connections(host, candidate):
            if requested_port is not None:
                return {
                    "port": candidate, "health": None,
                    "conflict": "OTHER_SERVICE",
                }
            skipped_ports.append({"port": candidate, "reason": "OTHER_SERVICE"})
            continue
        if first_free is None:
            first_free = candidate
    if first_free is not None:
        return {
            "port": first_free, "health": None, "conflict": None,
            "skipped_ports": skipped_ports,
        }
    return {
        "port": ports[0] if ports else DASHBOARD_DEFAULT_PORT,
        "health": None, "conflict": "AUTO_PORTS_EXHAUSTED",
        "foreign_hubs": foreign_hubs,
    }


def _dashboard_conflict_message(conflict: str) -> str:
    if conflict == "OTHER_USER_DASHBOARD":
        return "该端口属于同机另一个系统账号的 Dashboard；不会跨账号复用"
    if conflict == "LEGACY_SHARED_DASHBOARD":
        return "该端口运行的是升级前的共享 Dashboard；请先停止旧服务再升级"
    if conflict == "LEGACY_SINGLE_PROJECT_DASHBOARD":
        return "该端口运行的是旧版单项目 Dashboard；请先停止旧服务再升级"
    if conflict == "AUTO_PORTS_EXHAUSTED":
        return "Dashboard 自动端口范围内没有可用端口"
    return "该端口由非 Dashboard 服务使用"


def _project_dashboard_url(
    host: str, port: int, project_id: str, registry_dir: Path | None = None,
    *, include_token: bool = True,
) -> str:
    parameters = {"project": project_id}
    if include_token:
        parameters["token"] = dashboard_access_token(registry_dir)
    query = urllib.parse.urlencode(parameters)
    return f"http://{host}:{port}/?{query}"


def _write_dashboard_runtime(
    store: ProjectStore, host: str, port: int, pid: int | None, log_path: Path,
) -> dict[str, Any]:
    project_id = dashboard_project_id(store.root)
    value = {
        "schema": DASHBOARD_RUNTIME_SCHEMA,
        "pid": pid,
        "host": host,
        "port": port,
        # Project state may be shared; keep the account credential out of this file.
        "url": _project_dashboard_url(host, port, project_id, include_token=False),
        "project": str(store.root),
        "project_id": project_id,
        "owner_id": dashboard_owner_id(),
        "shared_service": True,
        "log": str(log_path),
        "started_at": now(),
    }
    atomic_json(store.state / DASHBOARD_RUNTIME_FILE, value)
    return value


def dashboard_status(
    store: ProjectStore, host: str | None = None, port: int | None = None,
) -> dict[str, Any]:
    """Report the managed background Dashboard without starting a service."""
    store.require()
    runtime = _dashboard_runtime(store)
    selected_host = host if host is not None else str((runtime or {}).get("host") or "127.0.0.1")
    if selected_host not in LOOPBACK_HOSTS:
        raise HarnessError("Dashboard 当前只允许监听 127.0.0.1 或 localhost")
    if port is not None and (port <= 0 or port > 65535):
        raise HarnessError("Dashboard port 必须在 1..65535")
    preferred_port = int((runtime or {}).get("port") or DASHBOARD_DEFAULT_PORT)
    endpoint = _select_dashboard_endpoint(selected_host, port, preferred_port)
    selected_port = int(endpoint["port"])
    project_id = dashboard_project_id(store.root)
    url = _project_dashboard_url(selected_host, selected_port, project_id)
    expected_project = str(store.root)
    health = endpoint.get("health")
    conflict = str(endpoint.get("conflict") or "")
    if conflict:
        return {
            "schema": "DashboardStatus/1", "status": "PORT_CONFLICT", "url": url,
            "project": expected_project, "project_id": project_id,
            "owner_scoped": True, "conflict": conflict,
            "message": _dashboard_conflict_message(conflict),
        }
    if health is not None:
        if _is_owned_dashboard_hub(health):
            registered = project_id in health.get("projects", [])
            if not registered:
                return {
                    "schema": "DashboardStatus/1", "status": "NOT_REGISTERED", "url": url,
                    "project": expected_project, "project_id": project_id,
                    "hub_running": True, "pid": health.get("pid"), "owner_scoped": True,
                    "skipped_ports": endpoint.get("skipped_ports", []),
                    "message": "当前账号的共享 Dashboard 正在运行，但当前项目尚未注册",
                }
            return {
                "schema": "DashboardStatus/1", "status": "RUNNING", "url": url,
                "project": expected_project, "project_id": project_id,
                "managed": bool(runtime), "shared_service": True,
                "owner_scoped": True,
                "skipped_ports": endpoint.get("skipped_ports", []),
                "pid": health.get("pid") or (runtime or {}).get("pid"),
                "log": (runtime or {}).get("log"),
                "message": "当前项目已注册到当前系统账号的共享 Dashboard",
            }
        observed_project = str(health.get("project", ""))
        if observed_project != expected_project:
            return {
                "schema": "DashboardStatus/1", "status": "PORT_CONFLICT", "url": url,
                "project": expected_project, "observed_project": observed_project or None,
                "message": "该端口运行的是旧版单项目 Dashboard；请先停止旧服务再升级为共享 Dashboard",
            }
        return {
            "schema": "DashboardStatus/1", "status": "RUNNING", "url": url,
            "project": expected_project, "managed": bool(runtime),
            "pid": (runtime or {}).get("pid"), "log": (runtime or {}).get("log"),
            "message": "Dashboard 正在运行",
        }
    if runtime is not None:
        return {
            "schema": "DashboardStatus/1", "status": "STALE", "url": url,
            "project": expected_project, "pid": runtime.get("pid"),
            "log": runtime.get("log"), "owner_scoped": True,
            "skipped_ports": endpoint.get("skipped_ports", []),
            "message": "Dashboard 已停止，但仍有旧运行记录",
        }
    return {
        "schema": "DashboardStatus/1", "status": "STOPPED", "url": url,
        "project": expected_project, "owner_scoped": True,
        "skipped_ports": endpoint.get("skipped_ports", []),
        "message": "当前系统账号的 Dashboard 尚未运行",
    }


def stop_dashboard(
    store: ProjectStore, host: str | None = None, port: int | None = None,
) -> dict[str, Any]:
    """Unregister one project; stop the shared service only after the last unregister."""
    runtime = _dashboard_runtime(store)
    if runtime is not None:
        runtime_host = str(runtime["host"])
        runtime_port = int(runtime["port"])
        if host is not None and host != runtime_host:
            raise HarnessError("--host 与当前项目的 Dashboard 运行记录不一致")
        if port is not None and port != runtime_port:
            raise HarnessError("--port 与当前项目的 Dashboard 运行记录不一致")
        observed = dashboard_status(store, runtime_host, runtime_port)
    else:
        observed = dashboard_status(store, host, port)
    runtime_path = store.state / DASHBOARD_RUNTIME_FILE
    project_id = dashboard_project_id(store.root)
    observed_url = urllib.parse.urlsplit(str(observed.get("url") or ""))
    selected_host = observed_url.hostname or host or str(
        (runtime or {}).get("host") or "127.0.0.1"
    )
    selected_port = observed_url.port or port or int(
        (runtime or {}).get("port") or DASHBOARD_DEFAULT_PORT
    )
    health = _dashboard_health(selected_host, selected_port)
    if _is_owned_dashboard_hub(health):
        unregister_dashboard_project(store)
        runtime_path.unlink(missing_ok=True)
        remaining = registered_dashboard_projects()
        if remaining:
            return {
                "schema": "DashboardStop/1", "status": "UNREGISTERED",
                "project": str(store.root), "project_id": project_id,
                "url": _project_dashboard_url(selected_host, selected_port, project_id),
                "shared_service": True, "remaining_projects": len(remaining),
                "message": "当前项目已从 Dashboard 注销；其他项目和共享服务不受影响",
            }
        pid = health.get("pid") or (runtime or {}).get("pid")
        if not isinstance(pid, int) or pid <= 0:
            return {
                "schema": "DashboardStop/1", "status": "UNMANAGED",
                "project": str(store.root), "project_id": project_id,
                "shared_service": True,
                "message": "最后一个项目已注销，但无法确认共享 Dashboard 进程；未发送停止信号",
            }
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            return {
                "schema": "DashboardStop/1", "status": "STOPPED",
                "project": str(store.root), "project_id": project_id,
                "pid": pid, "message": "最后一个项目已注销；共享 Dashboard 已经退出",
            }
        except OSError as exc:
            return {
                "schema": "DashboardStop/1", "status": "FAILED",
                "project": str(store.root), "project_id": project_id,
                "pid": pid, "message": f"项目已注销，但无法停止共享 Dashboard: {exc}",
            }
        deadline = time.monotonic() + 4.0
        while time.monotonic() < deadline:
            if _dashboard_health(selected_host, selected_port) is None:
                return {
                    "schema": "DashboardStop/1", "status": "STOPPED",
                    "project": str(store.root), "project_id": project_id,
                    "pid": pid, "message": "最后一个项目已注销；共享 Dashboard 已停止",
                }
            time.sleep(0.1)
        return {
            "schema": "DashboardStop/1", "status": "FAILED",
            "project": str(store.root), "project_id": project_id,
            "pid": pid, "message": "项目已注销，但共享 Dashboard 未在限定时间内停止",
        }
    if _is_dashboard_hub(health):
        return {
            **observed, "schema": "DashboardStop/1", "status": "PORT_CONFLICT",
            "message": "拒绝注销或停止其他系统账号的 Dashboard",
        }
    if observed["status"] in {"STOPPED", "NOT_REGISTERED"}:
        unregister_dashboard_project(store)
        runtime_path.unlink(missing_ok=True)
        return {**observed, "schema": "DashboardStop/1", "status": "STOPPED"}
    if observed["status"] == "STALE":
        runtime_path.unlink(missing_ok=True)
        return {
            **observed, "schema": "DashboardStop/1", "status": "STOPPED",
            "message": "已清理停止服务留下的旧运行记录",
        }
    if observed["status"] == "PORT_CONFLICT":
        return {
            **observed, "schema": "DashboardStop/1",
            "message": "拒绝停止不属于当前项目的端口服务",
        }
    pid = (runtime or {}).get("pid")
    if not isinstance(pid, int) or pid <= 0:
        return {
            **observed, "schema": "DashboardStop/1", "status": "UNMANAGED",
            "message": "Dashboard 正在运行，但没有可验证的后台进程记录；未发送停止信号",
        }
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        runtime_path.unlink(missing_ok=True)
        return {
            **observed, "schema": "DashboardStop/1", "status": "STOPPED",
            "message": "后台进程已经退出，已清理运行记录",
        }
    except OSError as exc:
        return {
            **observed, "schema": "DashboardStop/1", "status": "FAILED",
            "message": f"无法停止 Dashboard 后台进程: {exc}",
        }
    deadline = time.monotonic() + 4.0
    while time.monotonic() < deadline:
        if _dashboard_health(selected_host, selected_port) is None:
            runtime_path.unlink(missing_ok=True)
            return {
                "schema": "DashboardStop/1", "status": "STOPPED",
                "project": str(store.root), "url": f"http://{selected_host}:{selected_port}/",
                "pid": pid, "message": "Dashboard 后台服务已停止",
            }
        time.sleep(0.1)
    return {
        **observed, "schema": "DashboardStop/1", "status": "FAILED",
        "message": "Dashboard 在限定时间内没有停止；未强制终止",
    }


def ensure_dashboard_running(
    store: ProjectStore, host: str | None = None, port: int | None = None,
    open_browser: bool = False,
) -> dict[str, Any]:
    """Start or reuse a detached Dashboard without making bootstrap block."""
    store.require()
    runtime = _dashboard_runtime(store) if host is None or port is None else None
    host = host if host is not None else str((runtime or {}).get("host") or "127.0.0.1")
    if host not in LOOPBACK_HOSTS:
        raise HarnessError("Dashboard 当前只允许监听 127.0.0.1 或 localhost")
    if port is not None and (port <= 0 or port > 65535):
        raise HarnessError("后台 Dashboard port 必须在 1..65535")
    requested_port = port
    preferred_port = int((runtime or {}).get("port") or DASHBOARD_DEFAULT_PORT)
    endpoint = _select_dashboard_endpoint(host, requested_port, preferred_port)
    port = int(endpoint["port"])
    project_id = dashboard_project_id(store.root)
    url = _project_dashboard_url(host, port, project_id)
    expected_project = str(store.root)
    health = endpoint.get("health")
    conflict = str(endpoint.get("conflict") or "")
    if conflict:
        result = {
            "schema": "DashboardLaunch/1", "status": "PORT_CONFLICT", "url": url,
            "project": expected_project, "project_id": project_id,
            "owner_scoped": True, "conflict": conflict,
            "message": _dashboard_conflict_message(conflict),
            "browser_opened": False,
        }
        observed_project = str((health or {}).get("project", ""))
        if observed_project:
            result["observed_project"] = observed_project
        return result
    if health is not None:
        if _is_owned_dashboard_hub(health):
            register_dashboard_project(store)
            log_path = dashboard_registry_dir() / DASHBOARD_LOG_FILE
            runtime_warning = None
            try:
                _write_dashboard_runtime(store, host, port, health.get("pid"), log_path)
            except OSError as exc:
                runtime_warning = f"无法写入当前项目的 Dashboard 运行元数据: {exc}"
            result = {
                "schema": "DashboardLaunch/1", "status": "REUSED", "url": url,
                "project": expected_project, "project_id": project_id,
                "shared_service": True, "owner_scoped": True,
                "auto_selected_port": requested_port is None,
                "skipped_ports": endpoint.get("skipped_ports", []),
                "pid": health.get("pid"),
                "message": "当前项目已注册并复用当前系统账号的共享 Dashboard",
            }
            if runtime_warning:
                result["warning"] = runtime_warning
            if open_browser:
                try:
                    result["browser_opened"] = bool(webbrowser.open(url))
                except webbrowser.Error:
                    result["browser_opened"] = False
            else:
                result["browser_opened"] = False
            return result
        observed_project = str(health.get("project", ""))
        return {
            "schema": "DashboardLaunch/1", "status": "PORT_CONFLICT", "url": url,
            "project": expected_project, "project_id": project_id,
            "observed_project": observed_project or None,
            "message": "端口运行的是旧版单项目 Dashboard；请先停止旧服务，再启动共享 Dashboard",
        }
    else:
        registration = register_dashboard_project(store)
        registry_dir = dashboard_registry_dir()
        log_path = registry_dir / DASHBOARD_LOG_FILE
        module_root = str(Path(__file__).resolve().parents[1])
        environment = os.environ.copy()
        existing_pythonpath = environment.get("PYTHONPATH", "")
        environment["PYTHONPATH"] = (
            module_root if not existing_pythonpath
            else os.pathsep.join((module_root, existing_pythonpath))
        )
        command = [
            sys.executable, "-c",
            "import sys; from verif_harness.cli import main; raise SystemExit(main(sys.argv[1:]))",
            "dashboard", "--project-root", str(store.root),
            "--host", host, "--port", str(port), "--foreground",
        ]
        popen_options: dict[str, Any] = {
            "cwd": str(store.root), "env": environment,
            "stdin": subprocess.DEVNULL, "stderr": subprocess.STDOUT,
            "close_fds": True,
        }
        if os.name == "nt":  # pragma: no cover - Windows runtime boundary
            popen_options["creationflags"] = (
                subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
            )
        else:
            popen_options["start_new_session"] = True
        try:
            with log_path.open("ab") as log:
                process = subprocess.Popen(command, stdout=log, **popen_options)
        except OSError as exc:
            unregister_dashboard_project(store)
            return {
                "schema": "DashboardLaunch/1", "status": "FAILED", "url": url,
                "project": expected_project, "log": str(log_path),
                "message": f"Dashboard 后台进程启动失败: {exc}",
            }
        deadline = time.monotonic() + 4.0
        health = None
        while time.monotonic() < deadline:
            health = _dashboard_health(host, port)
            if (
                health is not None
                and (
                    not _is_owned_dashboard_hub(health)
                    or registration["id"] in health.get("projects", [])
                )
            ):
                break
            time.sleep(0.1)
        if (
            not _is_owned_dashboard_hub(health)
            or registration["id"] not in health.get("projects", [])
        ):
            unregister_dashboard_project(store)
            return {
                "schema": "DashboardLaunch/1", "status": "FAILED", "url": url,
                "project": expected_project, "pid": process.pid, "log": str(log_path),
                "message": (
                    "自动选择端口时检测到另一个系统账号并发启动 Dashboard；请重试"
                    if _is_dashboard_hub(health) else
                    "Dashboard 未能在限定时间内启动；请查看日志"
                ),
            }
        runtime_warning = None
        try:
            _write_dashboard_runtime(store, host, port, health.get("pid") or process.pid, log_path)
        except OSError as exc:
            runtime_warning = f"无法写入当前项目的 Dashboard 运行元数据: {exc}"
        reused_concurrent_service = health.get("pid") not in {None, process.pid}
        result: dict[str, Any] = {
            "schema": "DashboardLaunch/1",
            "status": "REUSED" if reused_concurrent_service else "STARTED", "url": url,
            "project": expected_project, "project_id": project_id,
            "shared_service": True, "owner_scoped": True,
            "auto_selected_port": requested_port is None,
            "skipped_ports": endpoint.get("skipped_ports", []),
            "pid": health.get("pid") or process.pid,
            "log": str(log_path),
            "message": (
                "当前项目已注册并复用当前账号并发启动的共享 Dashboard"
                if reused_concurrent_service else
                "当前系统账号的共享 Dashboard 已启动，当前项目已注册"
            ),
        }
        if runtime_warning:
            result["warning"] = runtime_warning
    if open_browser:
        try:
            result["browser_opened"] = bool(webbrowser.open(url))
        except webbrowser.Error:
            result["browser_opened"] = False
    else:
        result["browser_opened"] = False
    return result


def create_dashboard_server(
    store: ProjectStore, host: str, port: int, registry_dir: Path | None = None,
) -> DashboardHTTPServer:
    if host not in LOOPBACK_HOSTS:
        raise HarnessError("Dashboard 当前只允许监听 127.0.0.1 或 localhost")
    if port < 0 or port > 65535:
        raise HarnessError("Dashboard port 必须在 0..65535")
    store.require()
    store.ensure_dashboard_schema()
    return DashboardHTTPServer((host, port), store, registry_dir)


def serve_dashboard(
    store: ProjectStore, host: str = "127.0.0.1", port: int | None = None,
    open_browser: bool = False,
) -> int:
    endpoint = _select_dashboard_endpoint(host, port, DASHBOARD_DEFAULT_PORT)
    conflict = str(endpoint.get("conflict") or "")
    if conflict:
        raise HarnessError(_dashboard_conflict_message(conflict))
    if _is_owned_dashboard_hub(endpoint.get("health")):
        raise HarnessError("当前系统账号的共享 Dashboard 已经运行；请使用普通 dashboard 命令复用")
    port = int(endpoint["port"])
    server = create_dashboard_server(store, host, port)
    url = _project_dashboard_url(
        host, int(server.server_address[1]), dashboard_project_id(store.root),
        server.registry_dir,
    )
    print(f"verif-harness dashboard: {url}", flush=True)
    print("只监听本机；按 Ctrl-C 停止。负责人提交的意见会记录评审人和理由。", flush=True)
    if open_browser:
        threading.Timer(0.2, webbrowser.open, args=(url,)).start()
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


def snapshot_digest(snapshot: dict[str, Any]) -> str:
    """Stable helper used by tests and alternate dashboard clients."""
    value = {key: item for key, item in snapshot.items() if key != "generated_at"}
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
