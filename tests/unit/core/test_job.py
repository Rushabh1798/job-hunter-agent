"""Tests for job domain models."""

from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from job_hunter_core.models.job import FitReport, NormalizedJob, RawJob, ScoredJob


@pytest.mark.unit
class TestRawJob:
    """Test RawJob model."""

    def test_valid_raw_job(self) -> None:
        """RawJob with required fields creates successfully."""
        j = RawJob(
            company_id=uuid4(),
            company_name="Stripe",
            source_url="https://stripe.com/careers/123",
            scrape_strategy="api",
            source_confidence=0.9,
        )
        assert j.company_name == "Stripe"
        assert j.id is not None

    def test_confidence_out_of_range(self) -> None:
        """Source confidence > 1.0 raises error."""
        with pytest.raises(ValidationError):
            RawJob(
                company_id=uuid4(),
                company_name="Test",
                source_url="https://test.com/jobs/1",
                scrape_strategy="crawl4ai",
                source_confidence=1.5,
            )


@pytest.mark.unit
class TestNormalizedJob:
    """Test NormalizedJob model."""

    def _make_job(self, **overrides: object) -> NormalizedJob:
        """Create a valid NormalizedJob with optional overrides."""
        defaults: dict[str, object] = {
            "raw_job_id": uuid4(),
            "company_id": uuid4(),
            "company_name": "Stripe",
            "title": "Senior Engineer",
            "jd_text": "Build payment systems",
            "apply_url": "https://stripe.com/apply/123",
            "content_hash": "hash123",
        }
        defaults.update(overrides)
        return NormalizedJob(**defaults)  # type: ignore[arg-type]

    def test_valid_normalized_job(self) -> None:
        """NormalizedJob with required fields creates successfully."""
        j = self._make_job()
        assert j.title == "Senior Engineer"
        assert j.remote_type == "unknown"

    def test_salary_range_valid(self) -> None:
        """Valid salary range passes."""
        j = self._make_job(salary_min=100000, salary_max=200000)
        assert j.salary_min == 100000

    def test_salary_range_invalid(self) -> None:
        """salary_min > salary_max raises error."""
        with pytest.raises(ValidationError, match="salary_min"):
            self._make_job(salary_min=200000, salary_max=100000)

    def test_embedding_optional(self) -> None:
        """Embedding defaults to None."""
        j = self._make_job()
        assert j.embedding is None


@pytest.mark.unit
class TestFitReport:
    """Test FitReport model."""

    def test_valid_fit_report(self) -> None:
        """FitReport with all required fields creates successfully."""
        r = FitReport(
            score=85,
            skill_overlap=["Python", "ML"],
            skill_gaps=["Rust"],
            seniority_match=True,
            location_match=True,
            org_type_match=True,
            summary="Strong match",
            recommendation="strong_match",
            confidence=0.9,
        )
        assert r.score == 85

    def test_score_out_of_range(self) -> None:
        """Score > 100 raises error."""
        with pytest.raises(ValidationError):
            FitReport(
                score=101,
                skill_overlap=[],
                skill_gaps=[],
                seniority_match=True,
                location_match=True,
                org_type_match=True,
                summary="test",
                recommendation="strong_match",
                confidence=0.9,
            )

    def test_score_negative(self) -> None:
        """Score < 0 raises error."""
        with pytest.raises(ValidationError):
            FitReport(
                score=-1,
                skill_overlap=[],
                skill_gaps=[],
                seniority_match=True,
                location_match=True,
                org_type_match=True,
                summary="test",
                recommendation="mismatch",
                confidence=0.5,
            )


@pytest.mark.unit
class TestScoredJob:
    """Test ScoredJob model."""

    def test_valid_scored_job(self) -> None:
        """ScoredJob composes NormalizedJob and FitReport."""
        job = NormalizedJob(
            raw_job_id=uuid4(),
            company_id=uuid4(),
            company_name="Stripe",
            title="SWE",
            jd_text="Build things",
            apply_url="https://stripe.com/apply",
            content_hash="hash",
        )
        report = FitReport(
            score=75,
            skill_overlap=["Python"],
            skill_gaps=["Go"],
            seniority_match=True,
            location_match=True,
            org_type_match=False,
            summary="Good fit",
            recommendation="good_match",
            confidence=0.8,
        )
        scored = ScoredJob(job=job, fit_report=report, rank=1)
        assert scored.rank == 1
        assert scored.fit_report.score == 75
