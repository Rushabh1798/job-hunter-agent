"""Tests for candidate domain models."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from job_hunter_core.models.candidate import (
    CandidateProfile,
    Education,
    SearchPreferences,
    Skill,
)


@pytest.mark.unit
class TestSkill:
    """Test Skill model."""

    def test_minimal_skill(self) -> None:
        """Skill with just a name is valid."""
        s = Skill(name="Python")
        assert s.name == "Python"
        assert s.level is None

    def test_full_skill(self) -> None:
        """Skill with all fields is valid."""
        s = Skill(name="Python", level="expert", years=5.0)
        assert s.level == "expert"
        assert s.years == 5.0

    def test_invalid_level_raises(self) -> None:
        """Invalid skill level raises validation error."""
        with pytest.raises(ValidationError):
            Skill(name="Python", level="god-tier")  # type: ignore[arg-type]


@pytest.mark.unit
class TestEducation:
    """Test Education model."""

    def test_valid_education(self) -> None:
        """Education with valid graduation year."""
        e = Education(degree="BS", field="CS", graduation_year=2020)
        assert e.graduation_year == 2020

    def test_graduation_year_too_old(self) -> None:
        """Graduation year before 1950 raises error."""
        with pytest.raises(ValidationError, match="outside valid range"):
            Education(graduation_year=1900)

    def test_graduation_year_too_future(self) -> None:
        """Graduation year after 2030 raises error."""
        with pytest.raises(ValidationError, match="outside valid range"):
            Education(graduation_year=2050)


@pytest.mark.unit
class TestCandidateProfile:
    """Test CandidateProfile model."""

    def _make_profile(self, **overrides: object) -> CandidateProfile:
        """Create a valid profile with optional overrides."""
        defaults: dict[str, object] = {
            "name": "Jane Doe",
            "email": "jane@example.com",
            "years_of_experience": 5.0,
            "skills": [{"name": "Python"}],
            "raw_text": "Resume text here",
            "content_hash": "abc123",
        }
        defaults.update(overrides)
        return CandidateProfile(**defaults)  # type: ignore[arg-type]

    def test_valid_profile(self) -> None:
        """Valid profile creates successfully."""
        p = self._make_profile()
        assert p.name == "Jane Doe"
        assert str(p.email) == "jane@example.com"

    def test_invalid_email_raises(self) -> None:
        """Invalid email format raises error."""
        with pytest.raises(ValidationError):
            self._make_profile(email="not-an-email")

    def test_negative_yoe_raises(self) -> None:
        """Negative years of experience raises error."""
        with pytest.raises(ValidationError):
            self._make_profile(years_of_experience=-1)

    def test_optional_fields_default_none(self) -> None:
        """Optional fields default to None."""
        p = self._make_profile()
        assert p.phone is None
        assert p.location is None
        assert p.current_title is None


@pytest.mark.unit
class TestSearchPreferences:
    """Test SearchPreferences model."""

    def test_minimal_preferences(self) -> None:
        """Preferences with only raw_text is valid."""
        p = SearchPreferences(raw_text="Looking for ML roles")
        assert p.remote_preference == "any"
        assert p.currency == "USD"

    def test_salary_range_valid(self) -> None:
        """Valid salary range passes validation."""
        p = SearchPreferences(raw_text="test", min_salary=100000, max_salary=200000)
        assert p.min_salary == 100000

    def test_salary_range_invalid(self) -> None:
        """min_salary > max_salary raises error."""
        with pytest.raises(ValidationError, match="cannot exceed"):
            SearchPreferences(raw_text="test", min_salary=200000, max_salary=100000)

    def test_org_types_default(self) -> None:
        """Default org_types is ['any']."""
        p = SearchPreferences(raw_text="test")
        assert p.org_types == ["any"]
