import subprocess


def _run(cmd: list[str], cwd: str) -> str:
    try:
        result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=10)
        return result.stdout.strip()
    except Exception as exc:
        return f"git error: {exc}"


def git_log(repo_path: str, limit: int = 20) -> str:
    return _run(["git", "log", f"--max-count={limit}", "--oneline"], cwd=repo_path)


def git_diff(repo_path: str, ref_a: str = "HEAD~1", ref_b: str = "HEAD") -> str:
    return _run(["git", "diff", "--stat", ref_a, ref_b], cwd=repo_path)


def git_blame(repo_path: str, file_path: str) -> str:
    return _run(["git", "blame", "--porcelain", file_path], cwd=repo_path)


def git_show_file(repo_path: str, file_path: str, ref: str = "HEAD") -> str:
    return _run(["git", "show", f"{ref}:{file_path}"], cwd=repo_path)
