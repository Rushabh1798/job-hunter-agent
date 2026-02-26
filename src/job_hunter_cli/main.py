"""CLI entrypoint using typer."""

from __future__ import annotations

import asyncio
from pathlib import Path

import structlog
import typer
from rich.console import Console

from job_hunter_agents.observability import configure_logging, configure_tracing
from job_hunter_agents.orchestrator.pipeline import Pipeline
from job_hunter_core.config.settings import Settings
from job_hunter_core.models.run import RunConfig, RunResult

app = typer.Typer(
    name="job-hunter",
    help="Autonomous multi-agent job discovery system",
)
console = Console()
logger = structlog.get_logger()


@app.command()
def run(
    resume: Path = typer.Argument(..., help="Path to resume PDF", exists=True),
    prefs: str = typer.Option("", "--prefs", help="Freeform job preferences text"),
    prefs_file: Path | None = typer.Option(
        None, "--prefs-file", help="File containing preferences text"
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Skip email, generate files only"),
    force_rescrape: bool = typer.Option(False, "--force-rescrape", help="Ignore scrape cache"),
    company_limit: int | None = typer.Option(
        None, "--company-limit", help="Cap companies for testing"
    ),
    lite: bool = typer.Option(False, "--lite", help="SQLite + local embeddings, no Docker"),
    resume_from: str | None = typer.Option(
        None, "--resume-from", help="Resume from checkpoint run_id"
    ),
    adaptive: bool = typer.Option(
        True, "--adaptive/--no-adaptive", help="Use adaptive pipeline with discovery loop"
    ),
    min_jobs: int | None = typer.Option(None, "--min-jobs", help="Minimum recommended jobs target"),
    temporal: bool = typer.Option(
        False, "--temporal", help="Use Temporal orchestrator (requires Temporal server)"
    ),
    trace: bool = typer.Option(False, "--trace", help="Enable OTLP tracing (requires Jaeger)"),
    verbose: bool = typer.Option(False, "-v", "--verbose", help="Enable debug logging"),
) -> None:
    """Run the job hunter pipeline."""
    # Resolve preferences text
    preferences_text = prefs
    if prefs_file and prefs_file.exists():
        preferences_text = prefs_file.read_text().strip()

    if not preferences_text:
        console.print(
            "[red]Error:[/red] Provide --prefs or --prefs-file",
            style="bold",
        )
        raise typer.Exit(code=1)

    config = RunConfig(
        resume_path=resume,
        preferences_text=preferences_text,
        dry_run=dry_run,
        force_rescrape=force_rescrape,
        company_limit=company_limit,
        lite_mode=lite,
    )

    if resume_from:
        config.run_id = resume_from

    settings = Settings()  # type: ignore[call-arg]
    if lite:
        settings.db_backend = "sqlite"
        settings.embedding_provider = "local"
        settings.cache_backend = "db"

    if verbose:
        settings.log_level = "DEBUG"

    if temporal:
        settings.orchestrator = "temporal"

    if trace:
        settings.otel_exporter = "otlp"

    if min_jobs is not None:
        settings.min_recommended_jobs = min_jobs

    configure_logging(settings)
    configure_tracing(settings)

    console.print(f"[bold green]Starting run:[/bold green] {config.run_id}")
    if settings.orchestrator == "temporal":
        console.print("[dim]Orchestrator: Temporal[/dim]")
    else:
        console.print("[dim]Orchestrator: checkpoint[/dim]")

    patch_stack = None
    if dry_run:
        from job_hunter_agents.dryrun import activate_dry_run_patches

        patch_stack = activate_dry_run_patches()

    try:
        result = asyncio.run(_run_pipeline(settings, config, adaptive=adaptive))
    except Exception as exc:
        # Surface Temporal connection failures with a clear message
        from job_hunter_core.exceptions import TemporalConnectionError

        if isinstance(exc, TemporalConnectionError):
            console.print(
                f"[red]Error:[/red] Temporal server unreachable at "
                f"{settings.temporal_address}. Start it with `make dev-temporal` "
                f"or omit --temporal to use checkpoint mode.",
            )
            raise typer.Exit(code=1) from exc
        raise
    finally:
        if patch_stack is not None:
            patch_stack.close()

    console.print(f"\n[bold]Run complete:[/bold] {result.status}")
    console.print(f"  Companies: {result.companies_succeeded}/{result.companies_attempted}")
    console.print(f"  Jobs scraped: {result.jobs_scraped}")
    console.print(f"  Jobs scored: {result.jobs_scored}")
    console.print(f"  Cost: ${result.estimated_cost_usd:.2f}")
    console.print(f"  Duration: {result.duration_seconds:.1f}s")

    if result.output_files:
        console.print("\n[bold]Output files:[/bold]")
        for f in result.output_files:
            console.print(f"  {f}")

    if result.email_sent:
        console.print("\n[green]Email sent successfully[/green]")
    elif not config.dry_run:
        console.print("\n[yellow]Email not sent[/yellow]")

    if result.errors:
        console.print(f"\n[yellow]Warnings/Errors: {len(result.errors)}[/yellow]")

    if result.status != "success":
        raise typer.Exit(code=1)


@app.command()
def worker(
    queue: str = typer.Option("default", "--queue", help="Task queue: default, llm, or scraping"),
    verbose: bool = typer.Option(False, "-v", "--verbose", help="Enable debug logging"),
) -> None:
    """Start a Temporal worker for the specified task queue."""
    settings = Settings()  # type: ignore[call-arg]
    if verbose:
        settings.log_level = "DEBUG"

    configure_logging(settings)
    console.print(f"[bold green]Starting Temporal worker:[/bold green] queue={queue}")

    from job_hunter_agents.orchestrator.temporal_worker import run_worker

    asyncio.run(run_worker(settings, queue))


@app.command()
def version() -> None:
    """Show version."""
    console.print("job-hunter-agent v0.1.0")


async def _run_pipeline(
    settings: Settings,
    config: RunConfig,
    *,
    adaptive: bool = True,
) -> RunResult:
    """Select and run the appropriate orchestrator."""
    if settings.orchestrator == "temporal":
        from job_hunter_agents.orchestrator.temporal_orchestrator import TemporalOrchestrator

        orchestrator = TemporalOrchestrator(settings)
        return await orchestrator.run(config)

    if adaptive:
        from job_hunter_agents.orchestrator.adaptive_pipeline import AdaptivePipeline

        return await AdaptivePipeline(settings).run(config)

    return await Pipeline(settings).run(config)


if __name__ == "__main__":
    app()
