from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class ServiceSpec:
    name: str
    image: str = ""
    ports: list[str] = field(default_factory=list)
    environment: list[str] = field(default_factory=list)
    volumes: list[str] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)
    kind: str = "container"  # container | k8s_deployment | k8s_service


@dataclass
class ParsedInfra:
    source_path: str
    infra_type: str          # dockerfile | compose | kubernetes
    services: list[ServiceSpec] = field(default_factory=list)
    base_image: str = ""     # Dockerfile only
    exposed_ports: list[str] = field(default_factory=list)
    entry_cmd: str = ""

    def summary(self) -> str:
        if self.infra_type == "dockerfile":
            parts = [f"Dockerfile — base: {self.base_image}"]
            if self.exposed_ports:
                parts.append(f"ports: {', '.join(self.exposed_ports)}")
            if self.entry_cmd:
                parts.append(f"cmd: {self.entry_cmd}")
            return "  ".join(parts)

        lines = [f"{self.infra_type} ({len(self.services)} services):"]
        for svc in self.services:
            port_str = ", ".join(svc.ports[:3])
            lines.append(f"  {svc.name}: {svc.image or '?'}" + (f" [{port_str}]" if port_str else ""))
        return "\n".join(lines)


class InfraParser:
    def parse_directory(self, root: Path) -> list[ParsedInfra]:
        results: list[ParsedInfra] = []
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if any(p in {"node_modules", ".git", "__pycache__", "venv", ".venv"} for p in path.parts):
                continue
            try:
                parsed = self._try_parse(path, root)
                if parsed:
                    results.append(parsed)
            except Exception:
                continue
        return results

    def _try_parse(self, path: Path, root: Path) -> ParsedInfra | None:
        name = path.name.lower()
        rel = path.relative_to(root).as_posix()

        if name == "dockerfile" or name.startswith("dockerfile."):
            return self._parse_dockerfile(path, rel)
        if name in ("docker-compose.yml", "docker-compose.yaml",
                    "docker-compose.override.yml", "compose.yml", "compose.yaml"):
            return self._parse_compose(path, rel)
        if name.endswith((".yaml", ".yml")) and path.stat().st_size < 200_000:
            return self._try_parse_k8s(path, rel)
        return None

    def _parse_dockerfile(self, path: Path, rel: str) -> ParsedInfra | None:
        text = path.read_text(encoding="utf-8", errors="ignore")
        infra = ParsedInfra(source_path=rel, infra_type="dockerfile")
        for line in text.splitlines():
            line = line.strip()
            if line.upper().startswith("FROM "):
                infra.base_image = line.split(None, 1)[1].strip()
            elif line.upper().startswith("EXPOSE "):
                infra.exposed_ports.extend(line.split()[1:])
            elif line.upper().startswith(("CMD ", "ENTRYPOINT ")):
                infra.entry_cmd = line.split(None, 1)[1].strip()[:100]
        return infra if infra.base_image else None

    def _parse_compose(self, path: Path, rel: str) -> ParsedInfra | None:
        text = path.read_text(encoding="utf-8", errors="ignore")
        data = yaml.safe_load(text)
        if not isinstance(data, dict) or "services" not in data:
            return None

        infra = ParsedInfra(source_path=rel, infra_type="compose")
        for svc_name, svc_def in (data.get("services") or {}).items():
            if not isinstance(svc_def, dict):
                continue
            ports: list[str] = []
            raw_ports = svc_def.get("ports", [])
            for p in raw_ports:
                ports.append(str(p).split(":")[0])

            env: list[str] = []
            raw_env = svc_def.get("environment", {})
            if isinstance(raw_env, dict):
                env = [k for k in list(raw_env.keys())[:10]]
            elif isinstance(raw_env, list):
                env = [str(e).split("=")[0] for e in raw_env[:10]]

            depends = svc_def.get("depends_on", [])
            if isinstance(depends, dict):
                depends = list(depends.keys())

            infra.services.append(ServiceSpec(
                name=svc_name,
                image=svc_def.get("image", ""),
                ports=ports,
                environment=env,
                volumes=[str(v).split(":")[0] for v in (svc_def.get("volumes") or [])[:5]],
                depends_on=depends[:5] if isinstance(depends, list) else [],
            ))
        return infra if infra.services else None

    def _try_parse_k8s(self, path: Path, rel: str) -> ParsedInfra | None:
        text = path.read_text(encoding="utf-8", errors="ignore")
        try:
            docs = list(yaml.safe_load_all(text))
        except yaml.YAMLError:
            return None

        services: list[ServiceSpec] = []
        for doc in docs:
            if not isinstance(doc, dict):
                continue
            kind = doc.get("kind", "")
            meta = doc.get("metadata", {}) or {}
            name = meta.get("name", "unknown")

            if kind == "Deployment":
                containers = (
                    (doc.get("spec") or {})
                    .get("template", {})
                    .get("spec", {})
                    .get("containers", [])
                ) or []
                for c in containers[:3]:
                    if not isinstance(c, dict):
                        continue
                    ports = [str(p.get("containerPort", "")) for p in (c.get("ports") or [])[:5]]
                    services.append(ServiceSpec(
                        name=c.get("name", name),
                        image=c.get("image", ""),
                        ports=ports,
                        kind="k8s_deployment",
                    ))

            elif kind == "Service":
                ports = []
                for p in ((doc.get("spec") or {}).get("ports") or [])[:5]:
                    if isinstance(p, dict):
                        ports.append(str(p.get("port", "")))
                services.append(ServiceSpec(name=name, ports=ports, kind="k8s_service"))

        if not services:
            return None
        return ParsedInfra(source_path=rel, infra_type="kubernetes", services=services)
