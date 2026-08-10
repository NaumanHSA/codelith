from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml


_HTTP_METHODS = {"get", "post", "put", "patch", "delete", "head", "options"}


@dataclass
class ApiEndpoint:
    method: str
    path: str
    summary: str = ""
    description: str = ""
    tags: list[str] = field(default_factory=list)
    request_schema: str = ""
    response_schema: str = ""


@dataclass
class ParsedApiSpec:
    source_path: str
    title: str
    version: str
    base_url: str
    endpoints: list[ApiEndpoint] = field(default_factory=list)
    schemas: dict[str, str] = field(default_factory=dict)  # name → description

    def summary(self) -> str:
        lines = [
            f"**{self.title}** (v{self.version})",
            f"Base URL: {self.base_url}" if self.base_url else "",
            f"{len(self.endpoints)} endpoints:",
        ]
        for ep in self.endpoints[:20]:
            tag = f"[{ep.tags[0]}] " if ep.tags else ""
            lines.append(f"  {ep.method.upper()} {ep.path} — {tag}{ep.summary}")
        if len(self.endpoints) > 20:
            lines.append(f"  ... and {len(self.endpoints) - 20} more")
        if self.schemas:
            lines.append(f"Schemas: {', '.join(list(self.schemas)[:10])}")
        return "\n".join(l for l in lines if l)


class OpenApiParser:
    def parse_directory(self, root: Path) -> list[ParsedApiSpec]:
        specs: list[ParsedApiSpec] = []
        candidates = list(root.rglob("*.yaml")) + list(root.rglob("*.yml")) + list(root.rglob("*.json"))
        for f in candidates:
            if any(part.startswith(".") or part in {"node_modules", "__pycache__"} for part in f.parts):
                continue
            try:
                spec = self._try_parse(f, root)
                if spec:
                    specs.append(spec)
            except Exception:
                continue
        return specs

    def _try_parse(self, path: Path, root: Path) -> ParsedApiSpec | None:
        text = path.read_text(encoding="utf-8", errors="ignore")

        if path.suffix == ".json":
            try:
                data = json.loads(text)
            except json.JSONDecodeError:
                return None
        else:
            try:
                data = yaml.safe_load(text)
            except yaml.YAMLError:
                return None

        if not isinstance(data, dict):
            return None

        # Must look like an OpenAPI/Swagger spec
        if "openapi" not in data and "swagger" not in data:
            return None
        if "paths" not in data:
            return None

        info = data.get("info", {})
        title = info.get("title", path.stem)
        version = str(info.get("version", ""))

        # Base URL from servers (OpenAPI 3) or host+basePath (Swagger 2)
        base_url = ""
        if "servers" in data and data["servers"]:
            base_url = data["servers"][0].get("url", "")
        elif "host" in data:
            scheme = (data.get("schemes") or ["https"])[0]
            base_url = f"{scheme}://{data['host']}{data.get('basePath', '')}"

        endpoints: list[ApiEndpoint] = []
        for ep_path, methods in (data.get("paths") or {}).items():
            if not isinstance(methods, dict):
                continue
            for method, op in methods.items():
                if method.lower() not in _HTTP_METHODS:
                    continue
                if not isinstance(op, dict):
                    continue
                endpoints.append(ApiEndpoint(
                    method=method.lower(),
                    path=ep_path,
                    summary=op.get("summary", ""),
                    description=op.get("description", ""),
                    tags=op.get("tags", []),
                ))

        schemas: dict[str, str] = {}
        component_schemas = (
            data.get("components", {}).get("schemas", {})        # OpenAPI 3
            or data.get("definitions", {})                        # Swagger 2
        )
        for name, schema_def in list((component_schemas or {}).items())[:30]:
            desc = schema_def.get("description", "") if isinstance(schema_def, dict) else ""
            schemas[name] = desc

        rel_path = path.relative_to(root).as_posix()
        return ParsedApiSpec(
            source_path=rel_path,
            title=title,
            version=version,
            base_url=base_url,
            endpoints=endpoints,
            schemas=schemas,
        )
