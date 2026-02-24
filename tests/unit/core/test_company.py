"""Tests for company domain models."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from job_hunter_core.models.company import ATSType, CareerPage, Company


@pytest.mark.unit
class TestATSType:
    """Test ATSType enum."""

    def test_enum_values(self) -> None:
        """All expected ATS types exist."""
        assert ATSType.GREENHOUSE.value == "greenhouse"
        assert ATSType.LEVER.value == "lever"
        assert ATSType.UNKNOWN.value == "unknown"

    def test_string_coercion(self) -> None:
        """ATSType behaves as a string."""
        assert str(ATSType.GREENHOUSE) == "greenhouse"


@pytest.mark.unit
class TestCareerPage:
    """Test CareerPage model."""

    def test_valid_career_page(self) -> None:
        """Career page with valid URL creates successfully."""
        cp = CareerPage(url="https://stripe.com/careers")
        assert cp.ats_type == ATSType.UNKNOWN
        assert cp.scrape_strategy == "crawl4ai"

    def test_invalid_url_raises(self) -> None:
        """Invalid URL raises validation error."""
        with pytest.raises(ValidationError):
            CareerPage(url="not-a-url")


@pytest.mark.unit
class TestCompany:
    """Test Company model."""

    def test_valid_company(self) -> None:
        """Company with required fields creates successfully."""
        c = Company(
            name="Stripe",
            domain="stripe.com",
            career_page=CareerPage(url="https://stripe.com/careers"),
        )
        assert c.name == "Stripe"
        assert c.source_confidence == 1.0
        assert c.id is not None

    def test_confidence_bounds(self) -> None:
        """Source confidence must be between 0 and 1."""
        with pytest.raises(ValidationError):
            Company(
                name="Test",
                domain="test.com",
                career_page=CareerPage(url="https://test.com/careers"),
                source_confidence=1.5,
            )

    def test_confidence_zero(self) -> None:
        """Source confidence of 0.0 is valid."""
        c = Company(
            name="Test",
            domain="test.com",
            career_page=CareerPage(url="https://test.com/careers"),
            source_confidence=0.0,
        )
        assert c.source_confidence == 0.0
