#!/usr/bin/env python3
"""Generate a GitLab CI or Jenkins verification fragment from JSON."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_-]*")
SECRET_WORDS = re.compile(r"(?:password|passwd|secret|token|private[_-]?key|license[_-]?key)", re.I)
ALLOWED = {"provider", "job_name", "stage", "tags", "agent", "timeout", "variables", "commands", "artifacts"}


def scalar(value: object, where: str) -> str:
    text = str(value)
    if "\n" in text or "\r" in text:
        raise SystemExit(f"ERROR: multiline value not allowed for {where}")
    if SECRET_WORDS.search(where) or SECRET_WORDS.search(text):
        raise SystemExit(f"ERROR: possible secret material in {where}")
    return text


def quote_yaml(value: object, where: str) -> str:
    return json.dumps(scalar(value, where), ensure_ascii=False)


def validate(spec: dict) -> None:
    unknown = set(spec) - ALLOWED
    required = {"provider", "job_name", "commands"} - set(spec)
    if unknown or required:
        raise SystemExit(f"ERROR: unknown={sorted(unknown)} missing={sorted(required)}")
    if spec["provider"] not in {"gitlab", "jenkins"}:
        raise SystemExit("ERROR: provider must be gitlab or jenkins")
    if not IDENTIFIER.fullmatch(spec["job_name"]):
        raise SystemExit("ERROR: unsafe job_name")
    if not isinstance(spec["commands"], list) or not spec["commands"]:
        raise SystemExit("ERROR: commands must be non-empty")
    for index, command in enumerate(spec["commands"]):
        if not isinstance(command, str) or not command:
            raise SystemExit(f"ERROR: commands[{index}] must be a non-empty string")
        scalar(command, f"commands[{index}]")
        if re.search(r"\bgit\s+(?:pull|checkout|reset|clean)\b", command):
            raise SystemExit("ERROR: CI commands must use pipeline checkout, not mutate git state")
    for field in ("tags", "artifacts"):
        values = spec.get(field, [])
        if not isinstance(values, list) or not all(isinstance(value, str) and value for value in values):
            raise SystemExit(f"ERROR: {field} must be a string list")
    variables = spec.get("variables", {})
    if not isinstance(variables, dict):
        raise SystemExit("ERROR: variables must be an object")
    for key, value in variables.items():
        if not isinstance(key, str):
            raise SystemExit("ERROR: variable names must be strings")
        scalar(value, f"variables.{key}")


def render_gitlab(spec: dict) -> str:
    lines = [f"{spec['job_name']}:", f"  stage: {quote_yaml(spec.get('stage', 'verify'), 'stage')}"]
    tags = spec.get("tags", [])
    if tags:
        lines.append("  tags:")
        lines.extend(f"    - {quote_yaml(tag, 'tag')}" for tag in tags)
    if spec.get("timeout"):
        lines.append(f"  timeout: {quote_yaml(spec['timeout'], 'timeout')}")
    variables = spec.get("variables", {})
    if variables:
        lines.append("  variables:")
        for key, value in variables.items():
            if not IDENTIFIER.fullmatch(key):
                raise SystemExit(f"ERROR: unsafe variable name: {key}")
            lines.append(f"    {key}: {quote_yaml(value, f'variables.{key}')}")
    lines.append("  script:")
    lines.extend(f"    - {quote_yaml(command, 'command')}" for command in spec["commands"])
    artifacts = spec.get("artifacts", [])
    if artifacts:
        lines.extend(["  artifacts:", "    when: always", "    paths:"])
        lines.extend(f"      - {quote_yaml(path, 'artifact')}" for path in artifacts)
    return "\n".join(lines) + "\n"


def groovy_quote(value: object, where: str) -> str:
    text = scalar(value, where)
    return "'" + text.replace("\\", "\\\\").replace("'", "\\'") + "'"


def render_jenkins(spec: dict) -> str:
    agent = scalar(spec.get("agent", "eda"), "agent")
    lines = ["pipeline {", f"  agent {{ label {groovy_quote(agent, 'agent')} }}"]
    if spec.get("timeout"):
        timeout = scalar(spec["timeout"], "timeout")
        match = re.fullmatch(r"(\d+)([mh])", timeout)
        if not match:
            raise SystemExit("ERROR: Jenkins timeout must look like 30m or 2h")
        unit = "MINUTES" if match.group(2) == "m" else "HOURS"
        lines.append(f"  options {{ timeout(time: {match.group(1)}, unit: '{unit}') }}")
    variables = spec.get("variables", {})
    if variables:
        lines.append("  environment {")
        for key, value in variables.items():
            if not IDENTIFIER.fullmatch(key):
                raise SystemExit(f"ERROR: unsafe variable name: {key}")
            lines.append(f"    {key} = {groovy_quote(value, f'variables.{key}')}")
        lines.append("  }")
    lines.extend(["  stages {", f"    stage({groovy_quote(spec['job_name'], 'job_name')}) {{", "      steps {"])
    lines.extend(f"        sh {groovy_quote(command, 'command')}" for command in spec["commands"])
    lines.extend(["      }", "    }", "  }"])
    artifacts = spec.get("artifacts", [])
    if artifacts:
        pattern = ",".join(scalar(path, "artifact") for path in artifacts)
        lines.extend(["  post {", f"    always {{ archiveArtifacts artifacts: {groovy_quote(pattern, 'artifacts')}, allowEmptyArchive: true }}", "  }"])
    lines.extend(["}", ""])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    if args.out.exists() and not args.force:
        raise SystemExit(f"ERROR: refusing to overwrite: {args.out}")
    spec = json.loads(args.spec.read_text(encoding="utf-8"))
    validate(spec)
    output = render_gitlab(spec) if spec["provider"] == "gitlab" else render_jenkins(spec)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(output, encoding="utf-8")
    print(args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
