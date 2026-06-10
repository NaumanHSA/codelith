"""
End-to-end workflow test — from a file/directory/git URL to generated documentation.
No UI, no Celery required. Creates the org, project, source, and job automatically.

Usage:
    # Local directory
    conda run -n LLMs python scripts/test_workflow.py --path /home/nomi/workspace/my-repo

    # Local file
    conda run -n LLMs python scripts/test_workflow.py --path /home/nomi/docs/spec.md

    # Git URL (cloned by the workflow)
    conda run -n LLMs python scripts/test_workflow.py --path https://github.com/owner/repo

    # Custom options
    conda run -n LLMs python scripts/test_workflow.py \\
        --path /home/nomi/workspace/my-repo \\
        --project-name "My API" \\
        --doc-types architecture,api,getting_started \\
        --output-formats markdown

    # Re-run an existing job (skip project/job creation)
    conda run -n LLMs python scripts/test_workflow.py --path . --job-id 7
"""

import argparse
import asyncio
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


# ── Helpers ───────────────────────────────────────────────────────────────────

def _detect_source_type(path: str) -> tuple[str, str]:
    """Return (source_type, resolved_url_or_path)."""
    lower = path.lower()
    if lower.startswith(("https://github.com", "git@github.com")):
        return "github", path
    if lower.startswith(("https://gitlab.com", "git@gitlab.com")):
        return "gitlab", path
    if lower.startswith(("https://", "http://", "git@")):
        return "github", path  # generic git URL
    # Local path
    resolved = Path(path).resolve()
    if not resolved.exists():
        print(f"[ERROR] Path does not exist: {resolved}")
        sys.exit(1)
    return "local", str(resolved)


def _slugify(name: str) -> str:
    import re
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug[:80] or "project"


def _project_name_from_path(path: str) -> str:
    lower = path.lower()
    if lower.startswith(("https://", "http://", "git@")):
        # e.g. https://github.com/owner/my-repo → my-repo
        parsed = urlparse(path if "://" in path else "https://" + path.split("@")[-1].replace(":", "/"))
        return Path(parsed.path).stem or "imported-repo"
    return Path(path).resolve().name or "my-project"


# ── DB bootstrap ──────────────────────────────────────────────────────────────

async def ensure_org_and_user(db):
    """Return (org, user). Creates a dev org/user if the DB is empty."""
    from sqlalchemy import select
    from app.models.organization import Organization
    from app.models.user import User

    org = (await db.execute(select(Organization).order_by(Organization.id).limit(1))).scalar_one_or_none()
    user = (await db.execute(select(User).order_by(User.id).limit(1))).scalar_one_or_none()

    if not org:
        from app.core.security import get_password_hash
        org = Organization(name="Dev Org", slug="dev-org", plan_tier="free")
        db.add(org)
        await db.flush()
        await db.refresh(org)
        print(f"  [bootstrap] Created org '{org.name}' (id={org.id})")

    if not user:
        from app.core.security import get_password_hash
        user = User(
            org_id=org.id,
            email="dev@localhost",
            password_hash=get_password_hash("devpassword"),
            full_name="Dev User",
            role="admin",
            is_active=True,
        )
        db.add(user)
        await db.flush()
        await db.refresh(user)
        print(f"  [bootstrap] Created user '{user.email}' (id={user.id})")

    return org, user


async def create_project_with_source(
    db,
    org,
    user,
    project_name: str,
    source_type: str,
    url_or_path: str,
    branch: str | None,
) -> tuple:
    """Create project + source, return (project, source)."""
    from app.models.project import Project, ProjectSource
    from sqlalchemy.orm import selectinload
    from sqlalchemy import select

    slug = _slugify(project_name)
    # Make slug unique if it already exists
    existing = (await db.execute(select(Project).where(Project.slug == slug))).scalar_one_or_none()
    if existing:
        import time
        slug = f"{slug}-{int(time.time()) % 10000}"

    project = Project(
        org_id=org.id,
        created_by=user.id,
        name=project_name,
        slug=slug,
        status="active",
    )
    db.add(project)
    await db.flush()
    await db.refresh(project)

    source = ProjectSource(
        project_id=project.id,
        source_type=source_type,
        url_or_path=url_or_path,
        branch=branch,
        config_json={},
    )
    db.add(source)
    await db.flush()
    await db.refresh(source)

    await db.commit()

    # Re-fetch with sources eagerly loaded
    project = (
        await db.execute(
            select(Project).options(selectinload(Project.sources)).where(Project.id == project.id)
        )
    ).scalar_one()

    return project, source


async def create_job(db, project_id: int, user_id: int, doc_types: list[str], output_formats: list[str]):
    from app.models.job import Job
    job = Job(
        project_id=project_id,
        created_by=user_id,
        status="pending",
        config_json={
            "doc_types": doc_types,
            "output_formats": output_formats,
            "human_review": False,
        },
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)
    return job


# ── Main ──────────────────────────────────────────────────────────────────────

async def main(
    path: str,
    project_name: str | None,
    doc_types: list[str],
    output_formats: list[str],
    branch: str | None,
    job_id: int | None,
):
    from app.core.logging import setup_logging
    setup_logging()

    from app.db.session import AsyncSessionLocal

    source_type, resolved_path = _detect_source_type(path)
    name = project_name or _project_name_from_path(path)

    print(f"\n{'='*62}")
    print("  document-anything — end-to-end workflow test")
    print(f"{'='*62}")

    if job_id is None:
        async with AsyncSessionLocal() as db:
            org, user = await ensure_org_and_user(db)

            print(f"\n  Source path   : {resolved_path}")
            print(f"  Source type   : {source_type}")
            print(f"  Project name  : {name}")
            print(f"  Doc types     : {', '.join(doc_types)}")
            print(f"  Output formats: {', '.join(output_formats)}")
            if branch:
                print(f"  Branch        : {branch}")

            project, source = await create_project_with_source(
                db, org, user, name, source_type, resolved_path, branch
            )
            print(f"\n  Project created: id={project.id}  slug={project.slug}")
            print(f"  Source created : id={source.id}  type={source.source_type}")

            job = await create_job(db, project.id, user.id, doc_types, output_formats)
            job_id = job.id
            print(f"  Job created    : id={job_id}")
    else:
        print(f"\n  Re-using existing job id={job_id}")

    print(f"\n{'='*62}")
    print("  Running workflow (no Celery)...")
    print(f"{'='*62}\n")

    from app.workers.tasks.generation_tasks import _run_workflow

    try:
        result = await _run_workflow(job_id)
    except Exception as exc:
        print(f"\n[FAILED] {exc}")
        import traceback; traceback.print_exc()
        sys.exit(1)

    # ── Final summary ─────────────────────────────────────────────────────────
    from app.core.sandbox import JobSandbox
    sandbox = JobSandbox(job_id)

    print(f"\n{'='*62}")
    print("  DONE")
    print(f"{'='*62}")
    print(f"  Job id        : {job_id}")
    print(f"  Status        : {'awaiting_review' if result.get('requires_review') else 'completed'}")
    print(f"  Saved doc ids : {result.get('saved_doc_ids', [])}")
    print(f"  Runs folder   : {sandbox.root}/")
    print()

    trace_md   = sandbox.trace / "trace.md"
    trace_json = sandbox.trace / "trace.json"
    outputs    = sorted(sandbox.outputs.glob("*.md"))

    if trace_md.exists():
        print(f"  Trace (md)    : {trace_md}")
    if trace_json.exists():
        print(f"  Trace (json)  : {trace_json}")

    if outputs:
        print(f"\n  Generated docs:")
        for f in outputs:
            size_kb = f.stat().st_size / 1024
            print(f"    {f.name:<40} {size_kb:>6.1f} KB")
    else:
        print("  No output files written yet (check formatter/publisher agents).")

    print(f"\n{'='*62}\n")

    if result.get("error"):
        print(f"[WARNING] Workflow reported an error: {result['error']}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Run the full documentation workflow from a path — no UI, no Celery.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--path",
        default="/home/nomi/workspace/MOI/doc-face-extractor",
        help="Local directory, local file, or git URL to document",
    )
    parser.add_argument(
        "--project-name",
        default="Test Project from Script",
        help="Project name (default: derived from path)",
    )
    parser.add_argument(
        "--doc-types",
        default="architecture,api",
        help="Comma-separated doc types (default: architecture,api)",
    )
    parser.add_argument(
        "--output-formats",
        default="markdown",
        help="Comma-separated output formats (default: markdown)",
    )
    parser.add_argument(
        "--branch",
        default=None,
        help="Branch to checkout for git sources",
    )
    parser.add_argument(
        "--job-id",
        type=int,
        default=None,
        help="Skip setup and re-run an existing job by ID",
    )

    args = parser.parse_args()
    doc_types      = [t.strip() for t in args.doc_types.split(",")      if t.strip()]
    output_formats = [f.strip() for f in args.output_formats.split(",") if f.strip()]

    asyncio.run(main(
        path=args.path,
        project_name=args.project_name,
        doc_types=doc_types,
        output_formats=output_formats,
        branch=args.branch,
        job_id=args.job_id,
    ))
