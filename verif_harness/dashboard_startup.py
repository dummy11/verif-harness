"""Bounded Dashboard readiness checks before setup enters an interactive Agent.

Use existing page/project APIs so a healthy server from an earlier checkout can
be reused. Do not generate a snapshot, evaluate closure, or start Agent work.
"""

from __future__ import annotations

import json
import sqlite3
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from .dashboard import (
    DASHBOARD_ASSETS, _dashboard_health, _dashboard_runtime,
    _is_owned_dashboard_hub, dashboard_access_token, dashboard_project_id,
    ensure_dashboard_running,
)
from .store import HarnessError, ProjectStore, SCHEMA_VERSION


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Never forward the account token to another endpoint.
        return None


def _read_endpoint(origin: str, path: str) -> tuple[bytes, str]:
    request = urllib.request.Request(
        origin + path, headers={"X-Verif-Token": dashboard_access_token()},
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
    try:
        with opener.open(request, timeout=3) as response:
            payload = response.read(2 * 1024 * 1024 + 1)
            if len(payload) > 2 * 1024 * 1024:
                raise HarnessError("Dashboard 启动检查响应过大；请检查服务版本和日志")
            return payload, response.headers.get_content_type()
    except urllib.error.HTTPError as exc:
        # Do not print a server body or request URL containing credentials.
        code = exc.code
        exc.close()
        raise HarnessError(f"Dashboard 访问检查失败（HTTP {code}）；请检查权限和服务日志") from None
    except (OSError, urllib.error.URLError) as exc:
        raise HarnessError("Dashboard 访问检查超时或连接失败；请检查服务日志") from exc


def ensure_dashboard_ready(
    store: ProjectStore, host: str | None = None, port: int | None = None,
) -> dict[str, Any]:
    manifest = store.state / "project.json"
    if not manifest.exists() and not store.database.exists():
        return {
            "schema": "DashboardStartup/1", "status": "SKIPPED",
            "message": "项目尚未初始化；进入 Agent CLI 完成 bootstrap 后再启动 Dashboard。",
        }
    if not store.initialized:
        raise HarnessError("项目初始化记录不完整；请检查项目配置和状态数据库，尚未进入 Agent CLI")
    # Validate the actual database without schema writes, plan reads or exports.
    try:
        with store.read_connect() as connection:
            connection.execute("PRAGMA busy_timeout = 3000")
            version = connection.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
            if version is None or version["value"] != str(SCHEMA_VERSION):
                raise HarnessError("项目状态数据库版本不兼容；尚未进入 Agent CLI")
    except sqlite3.Error as exc:
        raise HarnessError("项目状态数据库无法读取；请检查文件权限或数据库日志，尚未进入 Agent CLI") from exc

    # Pin a recorded port: changing it silently breaks the existing SSH forward.
    try:
        runtime = _dashboard_runtime(store)
        selected_host = host or str((runtime or {}).get("host") or "127.0.0.1")
        selected_port = port if port is not None else (runtime or {}).get("port")
        result = ensure_dashboard_running(store, selected_host, selected_port)
    except OSError as exc:
        raise HarnessError("Dashboard 运行记录或项目注册无法读写；请检查文件权限，尚未进入 Agent CLI") from exc
    except (ValueError, TypeError, AttributeError) as exc:
        raise HarnessError("Dashboard 项目配置或服务响应格式错误；请检查配置和日志，尚未进入 Agent CLI") from exc
    if result.get("status") not in {"STARTED", "REUSED"}:
        raise HarnessError(
            f"Dashboard 尚未恢复：{result.get('message', '服务检查失败')}。"
            "未抢占端口或停止其他服务，尚未进入 Agent CLI。"
        )
    endpoint = urllib.parse.urlsplit(result["url"])
    health = _dashboard_health(endpoint.hostname, endpoint.port)
    project_id = dashboard_project_id(store.root)
    if (
        not _is_owned_dashboard_hub(health)
        or not isinstance(health.get("projects"), list)
        or project_id not in health["projects"]
    ):
        raise HarnessError("Dashboard 服务身份或项目注册检查失败；尚未进入 Agent CLI")
    origin = urllib.parse.urlunsplit((endpoint.scheme, endpoint.netloc, "", "", ""))
    payload, content_type = _read_endpoint(origin, "/api/projects")
    try:
        projects = json.loads(payload)
        registered = projects["projects"]
        matched = [item for item in registered if item.get("id") == project_id]
        if (
            content_type != "application/json" or projects.get("schema") != "DashboardProjectList/1"
            or len(matched) != 1 or matched[0].get("root") != str(store.root)
        ):
            raise ValueError("project identity mismatch")
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise HarnessError("Dashboard 项目接口未返回当前项目；尚未进入 Agent CLI") from exc
    page, content_type = _read_endpoint(origin, "/?" + urllib.parse.urlencode({"project": project_id}))
    if content_type != "text/html" or b"<html" not in page or b"__VERIF_DASHBOARD_TOKEN__" in page:
        raise HarnessError("Dashboard 页面无法正常读取；尚未进入 Agent CLI")
    for path in DASHBOARD_ASSETS:
        payload, content_type = _read_endpoint(origin, path)
        if not payload or content_type not in {"text/javascript", "application/javascript"}:
            raise HarnessError("Dashboard 页面脚本无法正常读取；请检查安装文件，尚未进入 Agent CLI")
    return {
        **result, "schema": "DashboardStartup/1", "status": "READY",
        "launch_status": result["status"],
        "message": "Dashboard 已就绪：服务、项目注册、页面和授权接口检查通过。",
        "checks": {"service": True, "registration": True, "database": True, "page": True, "assets": True},
        "ssh_forward_checked": False,
    }
