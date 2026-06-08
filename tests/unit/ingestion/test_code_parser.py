import tempfile
from pathlib import Path
import pytest
from app.ingestion.parsers.code_parser import CodeParser


def test_parse_python_file():
    parser = CodeParser()
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        (root / "main.py").write_text(
            "class MyClass:\n    pass\n\ndef my_function(x):\n    return x\n"
        )
        result = parser.parse_directory(root)

    assert result.total_files == 1
    assert result.languages.get("python") == 1
    file = result.files[0]
    assert file.path == "main.py"
    assert any(s["name"] == "MyClass" for s in file.symbols)
    assert any(s["name"] == "my_function" for s in file.symbols)


def test_ignores_venv():
    parser = CodeParser()
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        (root / ".venv").mkdir()
        (root / ".venv" / "lib.py").write_text("def hidden(): pass\n")
        (root / "app.py").write_text("def visible(): pass\n")
        result = parser.parse_directory(root)

    assert result.total_files == 1
    assert result.files[0].path == "app.py"


def test_primary_language():
    parser = CodeParser()
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        for i in range(3):
            (root / f"file{i}.py").write_text("def f(): pass\n")
        (root / "one.js").write_text("function g() {}\n")
        result = parser.parse_directory(root)

    assert result.primary_language == "python"
