"""
What the code relies on, and whether it fits together — from the kept manifests,
lockfiles and imports, with nothing sent anywhere.

Each source file answers to the nearest manifest of its ecosystem above it (`ui/src/x.ts`
to `ui/package.json`, `app/x.py` to the root `pyproject.toml`), together with any further
up. A package imported but declared nowhere works on the machine it was written on and
fails on a fresh install — unless a lockfile shows another package brings it in, which
works until that package stops.
"""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import PurePosixPath

from codelith.apps.qa.context import RunContext
from codelith.apps.qa.findings import Finding
from codelith.db.repositories.knowledge.source_repo import StoredFile
from codelith.languages import registry
from codelith.languages.base import Declared, LanguageProvider

AREAS = frozenset({"dependencies"})
TITLE = "Dependencies, lockfiles and versions"
RULES = {
    "deps.undeclared": "Imported but not declared",
    "deps.transitive-only": "Relied on only because another package brings it",
    "deps.dev-at-runtime": "Development-only packages used at runtime",
    "deps.unused": "Declared but never imported",
    "deps.unpinned": "No version asked for, and no lockfile",
    "deps.lock-drift": "Lockfile and manifest disagree",
    "deps.lock-missing": "Declared but missing from the lockfile",
    "deps.conflicting-pins": "Pinned differently in two manifests",
    "compat.syntax": "Syntax newer than the declared Python",
    "compat.image": "Container image older than the code needs",
}

#: Folders and files whose code is not shipped: their imports may lean on dev packages.
_NOT_SHIPPED = re.compile(
    r"(^|/)(tests?|testing|scripts?|tools|docs?|examples?|benchmarks?|e2e|__tests__)(/|$)"
    r"|(^|/)[\w.-]*\.config\.[cm]?[jt]s$|(^|/)(conftest|noxfile|setup)\.py$"
)
#: A manifest naming one of these builds a bundle: dev dependencies end up inside it.
_BUNDLER = re.compile(r"^(vite|webpack|rollup|parcel|esbuild|next|nuxt|@sveltejs/kit|astro|react-scripts|@angular/cli)$")


def _folder(path: str) -> str:
    parent = str(PurePosixPath(path).parent)
    return "" if parent == "." else parent


def _covers(manifest_folder: str, path: str) -> bool:
    return not manifest_folder or path == manifest_folder or path.startswith(manifest_folder + "/")


def _min_version(spec: str | None) -> tuple[int, ...] | None:
    """The lowest version a constraint like `>=3.11` or `^20.19` allows."""
    if not spec:
        return None
    m = re.search(r"(?:>=|~=|\^|==|~|>)?\s*v?(\d+)(?:\.(\d+))?", spec)
    if not m:
        return None
    return (int(m.group(1)), int(m.group(2) or 0))


def _version(text: str) -> tuple[int, ...] | None:
    m = re.match(r"v?(\d+)(?:\.(\d+))?", text)
    return (int(m.group(1)), int(m.group(2) or 0)) if m else None


def satisfies(ecosystem: str, spec: str, version: str) -> bool | None:
    """Whether `version` meets `spec`; `None` when it cannot be told."""
    spec = spec.strip()
    if not spec or spec in ("*", "latest", "x"):
        return True
    if ecosystem == "PyPI":
        try:
            from packaging.specifiers import InvalidSpecifier, SpecifierSet
            from packaging.version import InvalidVersion, Version

            return Version(version) in SpecifierSet(spec)
        except (InvalidSpecifier, InvalidVersion, ImportError):
            return None
    if ecosystem == "npm":
        if re.search(r"[|\s]|^(file|git|http|workspace|link|npm):", spec):
            return None
        m = re.match(r"^(\^|~|>=|=)?v?(\d+)(?:\.(\d+|x|\*))?(?:\.(\d+|x|\*))?", spec)
        v = re.match(r"^v?(\d+)\.(\d+)\.(\d+)", version)
        if not m or not v:
            return None
        op = m.group(1) or "="
        want = [int(x) if x and x.isdigit() else None for x in m.groups()[1:]]
        have = [int(x) for x in v.groups()]
        if op == ">=":
            return have >= [w or 0 for w in want]
        if op == "^":
            lead = next((i for i, w in enumerate(want) if w), 0)
            if have[: lead + 1] != [w or 0 for w in want[: lead + 1]]:
                return False
            return have >= [w or 0 for w in want]
        if op == "~":
            return have[:2] == [want[0], want[1] or 0] and have >= [w or 0 for w in want]
        return all(w is None or w == h for w, h in zip(want, have, strict=False))
    return None


async def run(ctx: RunContext) -> list[Finding]:
    out: list[Finding] = []
    by_name = {f.path: f for f in ctx.all_files}
    providers: dict[str, LanguageProvider] = {}
    for p in registry.providers():
        if p.ecosystem and p.ecosystem not in providers:
            providers[p.ecosystem] = p

    # What each manifest declares, and what each folder's lockfiles pin.
    manifests: dict[str, list[Declared]] = {}
    for f in ctx.all_files:
        if f.kind != "manifest":
            continue
        seen: set[tuple[str, str]] = set()
        for provider in registry.manifest_providers(f.path):
            for d in provider.declared(f.path, await ctx.text(f)):
                if (d.ecosystem, d.name) not in seen:
                    seen.add((d.ecosystem, d.name))
                    manifests.setdefault(f.path, []).append(d)
    locks: dict[tuple[str, str], dict[str, str]] = {}
    lock_paths: dict[tuple[str, str], str] = {}
    for f in ctx.all_files:
        if f.kind != "lockfile":
            continue
        name = PurePosixPath(f.path).name
        for provider in registry.providers():
            if name in getattr(provider, "lock_files", ()) and provider.ecosystem:
                pinned = provider.locked(f.path, await ctx.text(f))
                if pinned:
                    locks.setdefault((provider.ecosystem, _folder(f.path)), {}).update(pinned)
                    lock_paths[(provider.ecosystem, _folder(f.path))] = f.path

    def lock_for(ecosystem: str, folder: str) -> dict[str, str] | None:
        return locks.get((ecosystem, folder))

    # Local module roots, so `import app.x` is not taken for a package called `app`.
    local: set[str] = set()
    for f in ctx.all_files:
        provider = registry.for_path(f.path) if f.kind is None else None
        if provider is not None:
            local.add(provider.module_ref_for(f.path).name.split(".", 1)[0])
            local.add(f.path.split("/", 1)[0])
            if f.path.startswith("src/") and "/" in f.path[4:]:
                local.add(f.path[4:].split("/", 1)[0])

    # Who imports what, per ecosystem.
    imports: dict[str, dict[str, list[tuple[str, int]]]] = defaultdict(lambda: defaultdict(list))
    for f in ctx.all_files:
        provider = registry.for_path(f.path) if f.kind is None else None
        if provider is None or not provider.ecosystem:
            continue
        for root, line in provider.imported_packages(f.path, await ctx.text(f)):
            if root.split("/", 1)[0] not in local or "." in root.split("/", 1)[0]:
                imports[provider.ecosystem][root].append((f.path, line))
        await ctx.checkpoint()

    scoped = {f.path for f in ctx.files}

    def manifests_for(ecosystem: str, path: str) -> list[str]:
        found = [m for m, deps in manifests.items() if deps and deps[0].ecosystem == ecosystem and _covers(_folder(m), path)]
        return sorted(found, key=lambda m: -len(_folder(m)))

    # 1. Imported, and declared nowhere that covers the file.
    for ecosystem, roots in imports.items():
        provider = providers[ecosystem]
        for root, places in sorted(roots.items()):
            per_manifest: dict[str, list[tuple[str, int]]] = defaultdict(list)
            dev_only: dict[str, list[tuple[str, int]]] = defaultdict(list)
            for path, line in places:
                covering = manifests_for(ecosystem, path)
                if not covering:
                    continue
                declared = [d for m in covering for d in manifests[m] if provider.provides(d.name, root)]
                bundled = any(_BUNDLER.match(d.name) for d in manifests[covering[0]])
                if not declared:
                    per_manifest[covering[0]].append((path, line))
                elif (
                    all(d.dev for d in declared)
                    and not bundled
                    and not _NOT_SHIPPED.search(path)
                    and not provider.is_test_file(path)
                ):
                    dev_only[covering[0]].append((path, line))
            for manifest, where in per_manifest.items():
                where = [w for w in where if w[0] in scoped] or where
                lock = lock_for(ecosystem, _folder(manifest)) or {}
                brought = provider.normalise_package(root) in lock or root in lock
                files = sorted({p for p, _ in where})
                out.append(
                    Finding(
                        rule="deps.transitive-only" if brought else "deps.undeclared",
                        area="dependencies",
                        severity="low" if brought else "medium",
                        title=f"`{root}` is imported but not declared in `{manifest}`",
                        message=(
                            f"It is installed only because another package needs it (the lockfile has it): the day that "
                            f"package stops needing `{root}`, this code stops working."
                            if brought
                            else "It works on a machine where it happens to be installed, and fails on a fresh install with "
                            f"an import error. Imported in {len(files)} file(s)."
                        ),
                        fix=f"Declare `{root}` in `{manifest}` with the version range the code is tested against.",
                        path=where[0][0],
                        line=where[0][1],
                        confidence="likely",
                        source="check",
                        evidence={"files": files[:10], "manifest": manifest},
                    )
                )
            for manifest, where in dev_only.items():
                files = sorted({p for p, _ in where})
                out.append(
                    Finding(
                        rule="deps.dev-at-runtime",
                        area="dependencies",
                        severity="medium",
                        title=f"`{root}` is declared for development only, and shipped code imports it",
                        message=f"An install without the development extras leaves it out, and these {len(files)} file(s) "
                        "fail to import in production.",
                        fix=f"Move `{root}` to the runtime dependencies of `{manifest}`, or keep it out of shipped code.",
                        path=where[0][0],
                        line=where[0][1],
                        confidence="likely",
                        source="check",
                        evidence={"files": files[:10], "manifest": manifest},
                    )
                )

    # 2. Per manifest: unused, unpinned, lockfile drift, conflicting pins.
    pins: dict[tuple[str, str], list[tuple[str, str, int | None]]] = defaultdict(list)
    for manifest, deps in sorted(manifests.items()):
        if manifest not in scoped:
            continue
        ecosystem = deps[0].ecosystem
        provider = providers.get(ecosystem)
        if provider is None:
            continue
        folder = _folder(manifest)
        lock = lock_for(ecosystem, folder)
        covered_imports = {
            root
            for root, places in imports.get(ecosystem, {}).items()
            if any(manifests_for(ecosystem, p)[:1] == [manifest] or manifest in manifests_for(ecosystem, p) for p, _ in places)
        }
        has_code = any(_covers(folder, f.path) and f.kind is None and (pr := registry.for_path(f.path)) and pr.ecosystem == ecosystem for f in ctx.all_files)
        for d in deps:
            norm = provider.normalise_package(d.name)
            if re.match(r"^\s*==\s*[\w.]+$", d.spec) or (ecosystem == "npm" and re.match(r"^\d+\.\d+\.\d+$", d.spec)):
                pins[(ecosystem, norm)].append((manifest, d.spec, d.line))
            if (
                has_code
                and not d.dev
                and not provider.never_imported(d.name)
                and not any(provider.provides(d.name, root) for root in covered_imports)
                and ecosystem != "Go"
            ):
                out.append(
                    Finding(
                        rule="deps.unused",
                        area="dependencies",
                        severity="low",
                        title=f"`{d.name}` is declared and never imported",
                        message="Every install downloads it and every audit has to clear it, for code nothing calls. "
                        "It may be loaded by name (a plugin, a driver in a URL): if so, dismiss this with how.",
                        fix=f"Remove it from `{manifest}`, or say in a comment what loads it.",
                        path=manifest,
                        line=d.line,
                        confidence="likely",
                        source="check",
                    )
                )
            if lock is None and (not d.spec.strip() or d.spec.strip() in ("*", "latest")):
                out.append(
                    Finding(
                        rule="deps.unpinned",
                        area="dependencies",
                        severity="medium",
                        title=f"`{d.name}` asks for no version, and nothing locks one",
                        message="Every install takes whatever is newest that day: a breaking release arrives unannounced, "
                        "and two machines run different code from the same commit.",
                        fix="Give it the range the code is tested against, or commit a lockfile.",
                        path=manifest,
                        line=d.line,
                        source="check",
                    )
                )
            if lock is not None and not d.spec.startswith(("file:", "link:", "workspace:", "git", "http")):
                version = lock.get(norm) or lock.get(d.name)
                lock_path = lock_paths.get((ecosystem, folder), "the lockfile")
                if version is None and ecosystem != "Go":
                    out.append(
                        Finding(
                            rule="deps.lock-missing",
                            area="dependencies",
                            severity="medium",
                            title=f"`{d.name}` is declared but not in `{lock_path}`",
                            message="The lockfile was not updated after it was added: installs from the lockfile leave it "
                            "out, or resolve it fresh, unpinned.",
                            fix="Run the install again so the lockfile is regenerated, and commit it.",
                            path=manifest,
                            line=d.line,
                            source="check",
                        )
                    )
                elif version and satisfies(ecosystem, d.spec, version) is False:
                    out.append(
                        Finding(
                            rule="deps.lock-drift",
                            area="dependencies",
                            severity="medium",
                            title=f"`{d.name}` asks for {d.spec}, and the lockfile has {version}",
                            message="The lockfile no longer matches the manifest: what is installed is not what the "
                            "manifest says the code needs.",
                            fix="Run the install again so the lockfile is regenerated, and commit it.",
                            path=manifest,
                            line=d.line,
                            source="check",
                        )
                    )
    for (_ecosystem, name), where in pins.items():
        versions = {spec.strip("= ") for _, spec, _ in where}
        if len(versions) > 1:
            out.append(
                Finding(
                    rule="deps.conflicting-pins",
                    area="dependencies",
                    severity="medium",
                    title=f"`{name}` is pinned to {', '.join(sorted(versions))} in different manifests",
                    message="Which one is installed depends on which manifest is used: the code is tested against one "
                    "and may run against the other.",
                    fix="Pin it once, or keep the pins in step.",
                    path=where[0][0],
                    line=where[0][2],
                    source="check",
                    evidence={"manifests": [w[0] for w in where]},
                )
            )

    # 3. The runtime the code needs, against what is declared and what the image runs.
    out += await _compatibility(ctx, by_name)
    return out


async def _compatibility(ctx: RunContext, by_name: dict[str, StoredFile]) -> list[Finding]:
    out: list[Finding] = []
    needs: dict[str, tuple[str | None, str]] = {}  # runtime -> (version spec, source)
    for f in ctx.all_files:
        if f.kind != "manifest":
            continue
        for provider in registry.manifest_providers(f.path):
            siblings = frozenset(PurePosixPath(x.path).name for x in ctx.all_files if _folder(x.path) == _folder(f.path))
            info = provider.run_info(f.path, await ctx.text(f), siblings)
            if info and info.runtime and info.version and info.runtime not in needs:
                needs[info.runtime] = (info.version, f.path)

    # Syntax newer than the lowest Python the project says it supports.
    if "Python" in needs:
        spec, source = needs["Python"]
        lowest = _min_version(spec)
        reported: set[str] = set()
        for f in ctx.files:
            provider = registry.for_path(f.path) if f.kind is None else None
            if provider is None or provider.language != "python" or lowest is None:
                continue
            for feature, version, line in provider.syntax_needs(f.path, await ctx.text(f)):
                need = _version(version)
                if need and need > lowest and feature not in reported:
                    reported.add(feature)
                    out.append(
                        Finding(
                            rule="compat.syntax",
                            area="dependencies",
                            severity="medium",
                            title=f"Uses {feature}, which needs Python {version}; `{source}` allows {spec}",
                            message=f"On the oldest Python the project says it supports, this file does not even load: "
                            f"{feature} arrived in {version}.",
                            fix=f"Raise the requirement to `>={version}`, or write it the older way.",
                            path=f.path,
                            line=line,
                            source="check",
                        )
                    )

    # A container image older than the code needs.
    images = {"Python": r"^(?:docker\.io/)?(?:library/)?python:(\d+\.\d+)", "Node.js": r"^(?:docker\.io/)?(?:library/)?node:(\d+)", "Go": r"^(?:docker\.io/)?(?:library/)?golang:(\d+\.\d+)"}
    for f in ctx.files:
        if f.kind != "deploy" or "dockerfile" not in PurePosixPath(f.path).name.lower():
            continue
        for number, raw in enumerate((await ctx.text(f)).splitlines(), start=1):
            words = raw.strip().split()
            if len(words) < 2 or words[0].upper() != "FROM":
                continue
            for runtime, pattern in images.items():
                m = re.match(pattern, words[1])
                if m and runtime in needs:
                    spec, source = needs[runtime]
                    have, lowest = _version(m.group(1)), _min_version(spec)
                    # A tag naming only the major version (`node:20`) floats to its newest
                    # release, so only the major can be too old.
                    if have and lowest and "." not in m.group(1):
                        have, lowest = have[:1], lowest[:1]
                    if have and lowest and have < lowest:
                        out.append(
                            Finding(
                                rule="compat.image",
                                area="dependencies",
                                severity="high",
                                title=f"The image runs {runtime} {m.group(1)}; `{source}` needs {spec}",
                                message="The container's runtime is older than the code supports: it fails to install or "
                                "to start, or fails later on the first newer feature it reaches.",
                                fix=f"Base the image on {runtime} {'.'.join(str(x) for x in lowest)} or newer.",
                                path=f.path,
                                line=number,
                                source="check",
                            )
                        )
    return out


__all__ = ["AREAS", "RULES", "TITLE", "run", "satisfies"]
