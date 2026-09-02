"""
The conventional files a repository has, and the ones it does not.

Asked how neurosurfer is deployed, an answer described "a single Python runtime
container image" and its 43 dependencies. The repository ships no Dockerfile — the
CHANGELOG records one being removed — and what the model had actually read was
`docs/server/deployment.md`, which *recommends* an image. Prose became a description
of what is, rather than of what is suggested.

Nothing in the evidence could have contradicted it. The analysis detects Dockerfiles
correctly and found none, but "none" is not a row in a table: retrieval can only
return what exists, so a question about deployment gets whatever deployment-ish
material happens to be nearby, and absence is silent.

**This makes absence retrievable.** A short, checkable list of conventional
artefacts — packaging, containers, CI, environment templates — each marked present
with its path or absent outright. "There is no Dockerfile in this repository" is a
fact the analysis established by looking, and it belongs in the evidence next to the
files that do exist.

Derived from entities at question time rather than stored, so it is true of whatever
the last analysis found and needs no migration to arrive.
"""

from __future__ import annotations

from dataclasses import dataclass


#: What to check for, and what each one would tell a reader. Deliberately short:
#: this is the list somebody scans to orient themselves in an unfamiliar repository,
#: not an inventory. Every entry has to be a file whose presence or absence changes
#: the answer to a real question.
@dataclass(frozen=True, slots=True)
class Artefact:
    label: str
    #: Matched case-insensitively against the basename of a detected file.
    names: tuple[str, ...]
    #: What it means when it is there — written for the reader of an answer.
    means: str


ARTEFACTS: tuple[Artefact, ...] = (
    Artefact("Dockerfile", ("dockerfile",), "the repository builds a container image"),
    Artefact(
        "Compose file",
        ("docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"),
        "it defines a multi-service local stack",
    ),
    Artefact(
        "Kubernetes / Helm",
        ("chart.yaml", "values.yaml", "kustomization.yaml"),
        "it ships Kubernetes deployment config",
    ),
    Artefact(
        "CI workflow",
        ("ci.yml", "ci.yaml", "main.yml", "test.yml", "build.yml", ".gitlab-ci.yml", "jenkinsfile"),
        "it has automated builds or tests",
    ),
    Artefact(
        "Environment template",
        (".env.example", ".env.sample", ".env.template"),
        "the variables it expects are documented in a file",
    ),
    Artefact(
        "Python packaging",
        ("pyproject.toml", "setup.py", "setup.cfg"),
        "it is installable as a Python package",
    ),
    Artefact("Node packaging", ("package.json",), "it is a Node or front-end package"),
    Artefact("Go module", ("go.mod",), "it is a Go module"),
    Artefact("Rust crate", ("cargo.toml",), "it is a Rust crate"),
    Artefact("JVM build", ("pom.xml", "build.gradle", "build.gradle.kts"), "it is a JVM project"),
    Artefact(
        "Terraform",
        ("main.tf", "variables.tf", "terraform.tf"),
        "it provisions infrastructure as code",
    ),
    Artefact("Makefile", ("makefile", "justfile", "taskfile.yml"), "it has a task runner"),
    Artefact(
        "Procfile / service manifest",
        ("procfile", "app.yaml", "fly.toml", "render.yaml", "vercel.json", "netlify.toml"),
        "it declares how a platform should run it",
    ),
)

#: Kinds whose entities name files worth checking against the list above.
FILE_ENTITY_KINDS = ("config_file", "infra_resource", "entrypoint")


def profile(paths: list[str]) -> tuple[list[tuple[str, str]], list[str]]:
    """
    `(present, absent)` — the artefacts found, with their paths, and those missing.

    Matched on the basename so that `.github/workflows/ci.yml` and `deploy/ci.yml`
    both count, and so a Dockerfile is one wherever it lives.
    """
    basenames = {p.rsplit("/", 1)[-1].lower(): p for p in paths if p}

    present: list[tuple[str, str]] = []
    absent: list[str] = []
    for artefact in ARTEFACTS:
        hit = next((basenames[n] for n in artefact.names if n in basenames), None)
        if hit:
            present.append((artefact.label, hit))
        else:
            absent.append(artefact.label)
    return present, absent


def render(present: list[tuple[str, str]], absent: list[str]) -> str:
    """
    The profile as something a model can quote and a reader can check.

    Absence is stated as a finding, in the same words `list_facts` uses for an empty
    entity kind: the analysis looked, and there are none. A model told merely that
    nothing was found assumes it searched badly and keeps going; told that the search
    happened and came back empty, it can say so.
    """
    lines = ["Conventional files in this repository, checked by the analysis:", ""]
    for label, path in present:
        lines.append(f"  present  {label}: {path}")
    for label in absent:
        lines.append(f"  ABSENT   {label}")

    lines += [
        "",
        "The absences are findings, not gaps — the analysis looked for each of these "
        "by name and the repository does not contain one. Do not describe a "
        "deployment, a build or a configuration mechanism that depends on a file "
        "listed as ABSENT, however plausible it is, and however much the "
        "repository's own prose recommends it.",
    ]
    return "\n".join(lines)


__all__ = ["ARTEFACTS", "FILE_ENTITY_KINDS", "Artefact", "profile", "render"]
