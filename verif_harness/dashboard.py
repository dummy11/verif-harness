"""Local, dependency-free Human dashboard for the verif-harness control plane."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import threading
import time
import urllib.parse
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from .store import HarnessError, ProjectStore


MAX_REQUEST_BYTES = 1_048_576
LOOPBACK_HOSTS = {"127.0.0.1", "localhost"}


class DashboardHTTPServer(ThreadingHTTPServer):
    """Threaded local server whose writes still go through ProjectStore."""

    daemon_threads = True

    def __init__(self, address: tuple[str, int], store: ProjectStore):
        super().__init__(address, DashboardHandler)
        self.store = store
        self.write_token = secrets.token_urlsafe(32)


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

    def _authorized(self) -> bool:
        provided = self.headers.get("X-Verif-Token", "")
        return hmac.compare_digest(provided, self.server.write_token)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
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
                "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; "
                "connect-src 'self'; img-src 'self' data:; base-uri 'none'; form-action 'self'",
            )
            self.end_headers()
            self.wfile.write(payload)
        elif parsed.path == "/api/snapshot":
            self._json(self.server.store.dashboard_snapshot())
        elif parsed.path == "/api/document":
            selector = urllib.parse.parse_qs(parsed.query).get("selector", [""])[0]
            try:
                self._json(self.server.store.document_content(selector))
            except HarnessError as exc:
                self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        elif parsed.path == "/api/events":
            self._events()
        elif parsed.path == "/healthz":
            self._json({"status": "ok", "project": str(self.server.store.root)})
        else:
            self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)

    def _events(self) -> None:
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
                snapshot = self.server.store.dashboard_snapshot()
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
            result = self._mutate(urllib.parse.urlparse(self.path).path, body)
            self._json({"result": result, "snapshot": self.server.store.dashboard_snapshot()})
        except HarnessError as exc:
            self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        except Exception as exc:  # pragma: no cover - safety boundary for the local HTTP surface
            self._json({"error": f"dashboard request failed: {exc}"}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def _mutate(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        store = self.server.store
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
            return store.review_document_delivery(
                str(body.get("node", "")), definition_digest, document_digest,
                verdict, reviewer, notes,
                str(body.get("provisional_owner", "")),
                str(body.get("review_trigger", "")),
            )
        if path == "/api/reviews/node-plan-section":
            verdict = str(body.get("verdict", ""))
            if verdict not in {"approve", "reject", "modify", "clarify"}:
                raise HarnessError("node plan section verdict 必须是 approve/reject/modify/clarify")
            reviewer = str(body.get("reviewer", "")).strip()
            reason = str(body.get("reason", "")).strip()
            digest = str(body.get("definition_digest", "")).strip()
            if not reviewer or not reason or not digest:
                raise HarnessError("文档实施方案区块审批必须填写 reviewer、reason 和 definition_digest")
            return store.review_node_plan_section(
                str(body.get("node", "")), str(body.get("section", "")),
                digest, verdict, reviewer, reason,
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
        raise HarnessError(f"不支持的 Dashboard 写操作: {path}")


def dashboard_url(server: DashboardHTTPServer) -> str:
    host, port = server.server_address[:2]
    display_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
    return f"http://{display_host}:{port}/"


def create_dashboard_server(store: ProjectStore, host: str, port: int) -> DashboardHTTPServer:
    if host not in LOOPBACK_HOSTS:
        raise HarnessError("Dashboard 当前只允许监听 127.0.0.1 或 localhost")
    if port < 0 or port > 65535:
        raise HarnessError("Dashboard port 必须在 0..65535")
    store.require()
    store.ensure_dashboard_schema()
    return DashboardHTTPServer((host, port), store)


def serve_dashboard(
    store: ProjectStore, host: str = "127.0.0.1", port: int = 8765,
    open_browser: bool = False,
) -> int:
    server = create_dashboard_server(store, host, port)
    url = dashboard_url(server)
    print(f"verif-harness dashboard: {url}", flush=True)
    print("只监听本机；按 Ctrl-C 停止。Human 写操作会记录 reviewer 和 reason。", flush=True)
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
