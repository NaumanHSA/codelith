"""What a new reading may keep from the last one, decided from file fingerprints."""

from __future__ import annotations

from types import SimpleNamespace

from codelith.knowledge import incremental


def reading(hashes: dict[str, str], *, model: str | None = "embed-a", error: str | None = None):
    return SimpleNamespace(
        id=7,
        commit_sha="abc12345",
        file_hashes_json=hashes,
        stats_json={"embedding": {"model": model}} if model else {},
        error_message=error,
    )


class TestCompareFiles:
    def test_sorts_every_path_into_one_bucket(self) -> None:
        delta = incremental.compare_files(
            {"a.py": "1", "b.py": "2", "gone.py": "3"},
            {"a.py": "1", "b.py": "9", "new.py": "4"},
        )
        assert delta.unchanged == {"a.py"}
        assert delta.changed == {"b.py"}
        assert delta.added == {"new.py"}
        assert delta.removed == {"gone.py"}
        assert delta.touched == {"b.py", "new.py", "gone.py"}


class TestPlan:
    def test_force_reads_everything(self) -> None:
        plan = incremental.plan(reading({"a.py": "1"}), {"a.py": "1"}, force=True, embedding_model="embed-a")
        assert not incremental.active(plan)
        assert "forced" in plan["reason"]

    def test_a_first_reading_has_nothing_to_keep(self) -> None:
        plan = incremental.plan(None, {"a.py": "1"}, force=False, embedding_model="embed-a")
        assert not incremental.active(plan)

    def test_a_reading_without_fingerprints_cannot_be_compared(self) -> None:
        plan = incremental.plan(reading({}), {"a.py": "1"}, force=False, embedding_model="embed-a")
        assert not incremental.active(plan)

    def test_records_the_difference_and_whether_vectors_carry_over(self) -> None:
        plan = incremental.plan(
            reading({"a.py": "1", "b.py": "2"}), {"a.py": "1", "b.py": "3"}, force=False, embedding_model="embed-a"
        )
        assert incremental.active(plan)
        assert plan["from_kb"] == 7
        assert plan["changed"] == ["b.py"]
        assert plan["unchanged"] == 1
        assert plan["vectors"] is True

    def test_vectors_from_another_model_are_not_reused(self) -> None:
        plan = incremental.plan(reading({"a.py": "1"}), {"a.py": "1"}, force=False, embedding_model="embed-b")
        assert incremental.active(plan)
        assert plan["vectors"] is False

    def test_a_fallback_architecture_is_not_kept(self) -> None:
        previous = reading({"a.py": "1"}, error="architecture map came from the deterministic fallback")
        plan = incremental.plan(previous, {"a.py": "1"}, force=False, embedding_model="embed-a")
        assert plan["architecture_ok"] is False


class TestQuestions:
    def test_files_unchanged(self) -> None:
        plan = incremental.plan(
            reading({"a.py": "1", "b.py": "2"}), {"a.py": "1", "b.py": "3"}, force=False, embedding_model="embed-a"
        )
        assert incremental.files_unchanged(plan, ["a.py"])
        assert not incremental.files_unchanged(plan, ["a.py", "b.py"])
        # Nothing to compare against means nothing is known to be unchanged.
        assert not incremental.files_unchanged({"from_kb": None}, ["a.py"])

    def test_structure_is_unchanged_only_when_the_summarizer_said_so(self) -> None:
        plan = incremental.plan(reading({"a.py": "1"}), {"a.py": "1"}, force=False, embedding_model="embed-a")
        assert not incremental.structure_unchanged(plan)
        assert incremental.structure_unchanged(incremental.note(plan, structure_unchanged=True))

    def test_the_stored_summary_has_counts_not_file_lists(self) -> None:
        plan = incremental.plan(
            reading({"a.py": "1", "b.py": "2"}), {"a.py": "1", "c.py": "3"}, force=False, embedding_model="embed-a"
        )
        out = incremental.summary(incremental.note(plan, summaries_kept=4))
        assert "changed" not in out and "added" not in out
        assert out["files_added"] == 1
        assert out["files_removed"] == 1
        assert out["summaries_kept"] == 4
