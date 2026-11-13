"""
The checks that ask outside services, run only when a run is allowed online.

**What is sent, and to whom, is the whole question**, so it is narrow and said in the
results: package names and versions to OSV.dev (known vulnerabilities), and package
names to PyPI, the npm registry and the Go module proxy (latest version and licence).
No code, no file names, nothing about the codebase beyond what it depends on.

A service that cannot be reached is said, not taken for a clean result.
"""

from __future__ import annotations

import asyncio
import re
from collections import defaultdict
from pathlib import PurePosixPath

import httpx
import structlog

from codelith.apps.qa.context import RunContext
from codelith.apps.qa.findings import Finding
from codelith.languages import registry

logger = structlog.get_logger(__name__)

AREAS = frozenset({"dependencies"})
TITLE = "Known vulnerabilities, latest versions and licences (online)"
RULES = {
    "deps.known-vulnerability": "Known vulnerabilities in dependencies",
    "deps.outdated": "Major versions behind",
    "deps.copyleft": "Copyleft licences",
}

OSV = "https://api.osv.dev/v1"
_MAX_PACKAGES = 1000
_MAX_VULNS = 150
_MAX_LOOKUPS = 120
_TIMEOUT = httpx.Timeout(20.0, connect=8.0)
_SEVERITY = {"CRITICAL": "critical", "HIGH": "high", "MODERATE": "medium", "MEDIUM": "medium", "LOW": "low"}
_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
_COPYLEFT = re.compile(r"\b(AGPL|SSPL|GPL|EUPL|OSL|LGPL|MPL|CC-BY-SA)\b", re.IGNORECASE)


def _key(text: str) -> tuple:
    """A version as something comparable: `1.10.2` after `1.9`."""
    return tuple(int(x) if x.isdigit() else -1 for x in re.findall(r"\d+|[a-z]+", text.lower()))


def _later(a: str, b: str, ecosystem: str) -> bool:
    if ecosystem == "PyPI":
        try:
            from packaging.version import Version

            return Version(a) > Version(b)
        except Exception:  # an odd version string falls back to the plain comparison
            pass
    return _key(a) > _key(b)


def _bump(text: str, line: int | None, name: str, version: str, ecosystem: str, path: str) -> str | None:
    """A unified diff raising one dependency's floor to `version` in its manifest."""
    if not line:
        return None
    lines = text.splitlines()
    if line > len(lines):
        return None
    old = lines[line - 1]
    if ecosystem == "npm":
        new = re.sub(r'(:\s*")([^"]*)(")', lambda m: f"{m.group(1)}^{version}{m.group(3)}", old, count=1)
    else:
        new = re.sub(
            rf"({re.escape(name)}\s*(\[[^\]]*\])?)\s*([<>=!~^][^\"',;#\s]*(\s*,\s*[<>=!~^][^\"',;#\s]*)*)?",
            lambda m: f"{m.group(1)}>={version}",
            old,
            count=1,
            flags=re.IGNORECASE,
        )
    if new == old:
        return None
    from codelith.apps.qa.fixes import unified

    after = list(lines)
    after[line - 1] = new
    return unified(path, lines, after)


async def run(ctx: RunContext) -> list[Finding]:
    out: list[Finding] = []
    transport = ctx.cache.get("http_transport")

    # What is in use, with the exact version: lockfiles first, exact pins otherwise.
    declared: dict[tuple[str, str], tuple[str, int | None, str]] = {}  # (eco, norm) -> (manifest, line, spec)
    providers = {p.ecosystem: p for p in reversed(list(registry.providers())) if p.ecosystem}
    for f in ctx.all_files:
        if f.kind == "manifest":
            for provider in registry.manifest_providers(f.path):
                for d in provider.declared(f.path, await ctx.text(f)):
                    norm = provider.normalise_package(d.name)
                    declared.setdefault((d.ecosystem, norm), (f.path, d.line, d.spec))
    used: dict[tuple[str, str], tuple[str, str]] = {}  # (eco, name) -> (version, where)
    for f in ctx.all_files:
        if f.kind != "lockfile":
            continue
        name = PurePosixPath(f.path).name
        for provider in registry.providers():
            if provider.ecosystem and name in getattr(provider, "lock_files", ()):
                for pkg, version in provider.locked(f.path, await ctx.text(f)).items():
                    used.setdefault((provider.ecosystem, pkg), (version, f.path))
    for (eco, norm), (manifest, _line, spec) in declared.items():
        exact = re.match(r"^\s*(?:==|=)?\s*v?(\d[\w.+-]*)\s*$", spec)
        if exact and (eco, norm) not in used and (eco == "Go" or spec.strip().startswith(("==", "=")) or eco == "npm"):
            used[(eco, norm)] = (exact.group(1) if eco != "Go" else spec.strip(), manifest)
    queries = list(used.items())[:_MAX_PACKAGES]
    if not queries and not declared:
        return out

    async with httpx.AsyncClient(timeout=_TIMEOUT, transport=transport, headers={"User-Agent": "codelith-qa"}) as client:
        # Known vulnerabilities, from OSV.dev.
        vulns_by_pkg: dict[tuple[str, str], list[str]] = defaultdict(list)
        sent = 0
        try:
            for i in range(0, len(queries), 500):
                chunk = queries[i : i + 500]
                body = {"queries": [{"package": {"name": n, "ecosystem": e}, "version": v} for (e, n), (v, _) in chunk]}
                response = await client.post(f"{OSV}/querybatch", json=body)
                response.raise_for_status()
                sent += len(chunk)
                for ((e, n), _), result in zip(chunk, response.json().get("results") or [], strict=False):
                    for v in (result or {}).get("vulns") or []:
                        vulns_by_pkg[(e, n)].append(v["id"])
            ctx.notes.append(f"Sent {sent} package names and versions to OSV.dev to look up known vulnerabilities.")
        except (httpx.HTTPError, ValueError) as exc:
            ctx.notes.append(f"OSV.dev could not be reached ({type(exc).__name__}): known vulnerabilities were not checked.")
            vulns_by_pkg.clear()

        ids = sorted({i for ids in vulns_by_pkg.values() for i in ids})[:_MAX_VULNS]
        details: dict[str, dict] = {}
        gate = asyncio.Semaphore(8)

        async def detail(vid: str) -> None:
            async with gate:
                try:
                    r = await client.get(f"{OSV}/vulns/{vid}")
                    r.raise_for_status()
                    details[vid] = r.json()
                except (httpx.HTTPError, ValueError):
                    pass

        await asyncio.gather(*(detail(v) for v in ids))
        await ctx.checkpoint()

        for (eco, name), vids in sorted(vulns_by_pkg.items()):
            version, where = used[(eco, name)]
            worst, fixes, labels = "info", [], []
            for vid in vids:
                data = details.get(vid, {})
                sev = _SEVERITY.get(str((data.get("database_specific") or {}).get("severity") or "").upper(), "medium")
                worst = sev if _RANK[sev] < _RANK[worst] else worst
                cve = next((a for a in data.get("aliases") or [] if a.startswith("CVE-")), None)
                labels.append(f"{vid}{f' ({cve})' if cve else ''}: {(data.get('summary') or '').strip()[:120]}")
                for affected in data.get("affected") or []:
                    pkg = affected.get("package") or {}
                    if providers.get(eco) and providers[eco].normalise_package(str(pkg.get("name", ""))) != name:
                        continue
                    for rng in affected.get("ranges") or []:
                        fixes += [e["fixed"] for e in rng.get("events") or [] if "fixed" in e and _later(e["fixed"], version, eco)]
            fixed = None
            for candidate in fixes:
                if fixed is None or _later(candidate, fixed, eco):
                    fixed = candidate
            direct = declared.get((eco, name))
            path, line, patch = where, None, None
            if direct:
                path, line = direct[0], direct[1]
                manifest = next((f for f in ctx.all_files if f.path == path), None)
                if fixed and manifest is not None:
                    patch = _bump(await ctx.text(manifest), line, name, fixed, eco, path)
            else:
                lock = next((f for f in ctx.all_files if f.path == where), None)
                if lock is not None:
                    text = await ctx.text(lock)
                    at = text.find(name)
                    line = text.count("\n", 0, at) + 1 if at >= 0 else None
            count = len(vids)
            out.append(
                Finding(
                    rule="deps.known-vulnerability",
                    area="dependencies",
                    severity=worst if worst != "info" else "medium",
                    title=f"`{name}` {version} has {count} known vulnerabilit{'y' if count == 1 else 'ies'}",
                    message=("; ".join(labels[:3]) + (f"; and {count - 3} more." if count > 3 else "."))
                    + ("" if direct else f" It is not declared directly: another package brings it in ({where} pins it)."),
                    fix=(f"Upgrade `{name}` to {fixed} or later." if fixed else f"No fixed release is recorded yet: check the advisories for `{name}` and whether the affected code is used.")
                    + ("" if direct or not fixed else " Upgrade whichever direct dependency brings it in, or pin it."),
                    path=path,
                    line=line,
                    confidence="confirmed",
                    source="check",
                    patch=patch,
                    evidence={"ids": vids, "fixed": fixed, "version": version, "ecosystem": eco},
                )
            )

        # Latest versions and licences of what is declared directly.
        lookups = [(eco, norm, info) for (eco, norm), info in declared.items() if eco in ("PyPI", "npm", "Go")][:_MAX_LOOKUPS]
        latest: dict[tuple[str, str], tuple[str | None, str | None]] = {}

        async def look(eco: str, name: str) -> None:
            async with gate:
                try:
                    if eco == "PyPI":
                        r = await client.get(f"https://pypi.org/pypi/{name}/json")
                        r.raise_for_status()
                        info = r.json().get("info") or {}
                        lic = info.get("license_expression") or info.get("license") or next(
                            (c.split("::")[-1].strip() for c in info.get("classifiers") or [] if c.startswith("License ::")), None
                        )
                        latest[(eco, name)] = (info.get("version"), (lic or "")[:80] or None)
                    elif eco == "npm":
                        r = await client.get(f"https://registry.npmjs.org/{name}/latest")
                        r.raise_for_status()
                        data = r.json()
                        lic = data.get("license")
                        latest[(eco, name)] = (data.get("version"), lic if isinstance(lic, str) else None)
                    else:
                        escaped = re.sub(r"[A-Z]", lambda m: "!" + m.group(0).lower(), name)
                        r = await client.get(f"https://proxy.golang.org/{escaped}/@latest")
                        r.raise_for_status()
                        latest[(eco, name)] = (r.json().get("Version"), None)
                except (httpx.HTTPError, ValueError):
                    pass

        await asyncio.gather(*(look(e, n) for e, n, _ in lookups))
        if lookups:
            registries = sorted({"PyPI" if e == "PyPI" else "the npm registry" if e == "npm" else "the Go proxy" for e, _, _ in lookups})
            ctx.notes.append(
                f"Asked {' and '.join(registries)} for the latest version and licence of {len(lookups)} declared packages "
                f"({len(latest)} answered)."
            )

        for eco, name, (manifest, line, spec) in lookups:
            newest, licence = latest.get((eco, name), (None, None))
            have = (used.get((eco, name)) or (None, None))[0] or (re.search(r"\d[\w.]*", spec).group(0) if re.search(r"\d", spec) else None)
            if newest and have:
                majors = (_key(newest)[:1] or (0,))[0] - (_key(have)[:1] or (0,))[0]
                if majors >= 1:
                    out.append(
                        Finding(
                            rule="deps.outdated",
                            area="dependencies",
                            severity="low",
                            title=f"`{name}` is {majors} major version{'s' if majors > 1 else ''} behind ({have} → {newest})",
                            message="Major versions behind is where security fixes stop being backported, and where each "
                            "upgrade gets harder the longer it waits.",
                            fix=f"Plan the upgrade to {newest}: read its changelog for what breaks.",
                            path=manifest,
                            line=line,
                            source="check",
                            evidence={"latest": newest, "version": have},
                        )
                    )
            if licence and (m := _COPYLEFT.search(licence)):
                kind = m.group(1).upper()
                strong = kind in ("AGPL", "SSPL")
                out.append(
                    Finding(
                        rule="deps.copyleft",
                        area="dependencies",
                        severity="medium" if strong else "low" if kind in ("GPL", "EUPL", "OSL", "CC-BY-SA") else "info",
                        title=f"`{name}` is licensed {licence}",
                        message=(
                            "A network-copyleft licence: offering the software over a network can oblige you to publish its source."
                            if strong
                            else "A copyleft licence: distributing software that includes it can oblige you to publish source "
                            "under the same terms. Weak copyleft (LGPL, MPL) mostly allows linking."
                        ),
                        fix="Check it fits how the software is shipped, with whoever looks after licences.",
                        path=manifest,
                        line=line,
                        confidence="likely",
                        source="check",
                        evidence={"licence": licence},
                    )
                )
    return out


__all__ = ["AREAS", "RULES", "TITLE", "run"]
