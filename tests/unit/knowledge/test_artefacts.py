"""
Making absence retrievable.

Asked how neurosurfer is deployed, an answer described "a single Python runtime
container image" and its 43 dependencies. The repository ships no Dockerfile — the
CHANGELOG records one being removed — and what the model had read was
`docs/server/deployment.md`, which *recommends* an image. Documentation prose became
a description of what is.

Nothing in the evidence could have contradicted it. Detection was never the problem:
the analysis looks for Dockerfiles and correctly found none. But "none" is not a row
in a table, so retrieval returned whatever deployment-ish material sat nearby and
absence stayed silent.
"""

from __future__ import annotations

from app.knowledge.artefacts import ARTEFACTS, profile, render


class TestWhatIsThere:
    def test_a_file_is_found_wherever_it_lives(self) -> None:
        """`.github/workflows/ci.yml` and `deploy/ci.yml` are both a CI workflow, and
        a Dockerfile is one wherever somebody put it."""
        present, _ = profile([".github/workflows/ci.yml", "docker/Dockerfile"])

        assert ("CI workflow", ".github/workflows/ci.yml") in present
        assert ("Dockerfile", "docker/Dockerfile") in present

    def test_matching_ignores_case(self) -> None:
        present, _ = profile(["dockerfile", "Makefile"])

        assert {label for label, _ in present} == {"Dockerfile", "Makefile"}

    def test_the_path_comes_back_so_the_reader_can_open_it(self) -> None:
        present, _ = profile(["services/api/pyproject.toml"])

        assert present == [("Python packaging", "services/api/pyproject.toml")]


class TestWhatIsNot:
    def test_a_repository_without_docker_says_so(self) -> None:
        """The load-bearing case, and the one the whole module exists for."""
        _, absent = profile([".github/workflows/ci.yml", "pyproject.toml", ".env.example"])

        assert "Dockerfile" in absent
        assert "Compose file" in absent
        assert "Python packaging" not in absent

    def test_an_empty_repository_is_all_absences(self) -> None:
        present, absent = profile([])

        assert present == []
        assert len(absent) == len(ARTEFACTS)


class TestHowItReads:
    def test_absence_is_stated_as_a_finding(self) -> None:
        """A model told merely that nothing was found assumes it searched badly and
        keeps going. Told the search happened and came back empty, it can say so —
        the same wording `list_facts` uses for an entity kind with no rows."""
        text = render(*profile(["pyproject.toml"]))

        assert "findings, not gaps" in text
        assert "ABSENT   Dockerfile" in text

    def test_the_recommendation_trap_is_named(self) -> None:
        """The failure was not inventing a Dockerfile out of nothing — it was reading
        documentation that recommends one as a description of what exists. Saying
        only "there is no Dockerfile" leaves that route open."""
        text = render(*profile([]))

        assert "however much the repository's own prose recommends it" in text

    def test_what_is_present_carries_its_path(self) -> None:
        text = render(*profile(["deploy/Dockerfile"]))

        assert "present  Dockerfile: deploy/Dockerfile" in text


class TestTheListItself:
    def test_every_artefact_declares_names_and_a_meaning(self) -> None:
        for artefact in ARTEFACTS:
            assert artefact.label and artefact.means
            assert artefact.names
            assert all(n == n.lower() for n in artefact.names), (
                f"{artefact.label}: names are matched lowercased"
            )

    def test_no_two_artefacts_claim_the_same_filename(self) -> None:
        """A filename matching two entries would report one artefact present and the
        other absent depending on iteration order."""
        seen: dict[str, str] = {}
        for artefact in ARTEFACTS:
            for name in artefact.names:
                assert name not in seen, f"{name} claimed by {seen.get(name)} and {artefact.label}"
                seen[name] = artefact.label
