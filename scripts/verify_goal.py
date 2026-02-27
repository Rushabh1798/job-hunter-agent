"""Verify pipeline output meets GOAL.md criteria.

Exit code 0 = all goals met, 1 = some goals failed.
Prints a summary table of pass/fail status for each goal.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path


def verify(csv_path: str) -> bool:
    """Verify a pipeline output CSV meets goals."""
    path = Path(csv_path)
    if not path.exists():
        print(f"FAIL: CSV not found at {csv_path}")
        return False

    with open(path) as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    total = len(rows)
    companies: set[str] = set()
    has_specific_apply_url = 0
    has_posted_date = 0
    location_relevant = 0

    for row in rows:
        company = row.get("Company", row.get("company_name", ""))
        companies.add(company)

        # Check apply URL is specific (not a generic landing page)
        apply_url = row.get("Apply URL", row.get("apply_url", ""))
        if apply_url and "/" in apply_url:
            # Landing pages typically end with just the domain or /careers/
            url_path = apply_url.split("//", 1)[-1] if "//" in apply_url else apply_url
            parts = url_path.strip("/").split("/")
            if len(parts) >= 2:  # Has at least domain + path segment
                has_specific_apply_url += 1

        # Check posted date
        posted = row.get("Posted Date", row.get("posted_date", ""))
        if posted and posted not in ("Unknown", "None", "", "N/A"):
            has_posted_date += 1

        # Check location relevance
        location = row.get("Location", row.get("location", "")).lower()
        remote = row.get("Remote", row.get("remote_type", "")).lower()
        india_keywords = [
            "india",
            "bangalore",
            "bengaluru",
            "mumbai",
            "pune",
            "hyderabad",
            "chennai",
            "noida",
            "gurgaon",
            "ahmedabad",
        ]
        if any(kw in location for kw in india_keywords):
            location_relevant += 1
        elif "remote" in location or remote == "remote":
            location_relevant += 1

    # Check all unique companies
    all_unique = total == len(companies)

    results: dict[str, bool] = {}
    results[f"At least 10 scored jobs (got {total})"] = total >= 10
    results[f"All unique companies (got {len(companies)} companies for {total} jobs)"] = all_unique
    results[f"All location-relevant (got {location_relevant}/{total})"] = (
        total > 0 and location_relevant == total
    )
    results[f"Posted dates populated (got {has_posted_date}/{total})"] = has_posted_date > 0
    results[f"Specific apply URLs (got {has_specific_apply_url}/{total})"] = (
        total > 0 and has_specific_apply_url >= total * 0.8
    )

    print(f"\n{'=' * 60}")
    print(f"GOAL VERIFICATION: {csv_path}")
    print(f"{'=' * 60}")
    print(f"Total jobs in output: {total}")
    if companies:
        print(f"Companies: {', '.join(sorted(companies))}")
    print()

    all_pass = True
    for desc, passed in results.items():
        status = "PASS" if passed else "FAIL"
        if not passed:
            all_pass = False
        print(f"  [{status}] {desc}")

    print()
    if all_pass:
        print("ALL GOALS MET")
    else:
        print("SOME GOALS NOT MET")
    print(f"{'=' * 60}\n")

    return all_pass


if __name__ == "__main__":
    if len(sys.argv) < 2:
        # Find latest results CSV
        output_dir = Path("output")
        csvs = sorted(output_dir.glob("run_*_results.csv"))
        if not csvs:
            print("No results CSV found in output/")
            sys.exit(1)
        csv_path = str(csvs[-1])
        print(f"Using latest: {csv_path}")
    else:
        csv_path = sys.argv[1]

    success = verify(csv_path)
    sys.exit(0 if success else 1)
