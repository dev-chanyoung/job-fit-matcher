"""Manual CLI entry point for job-judge when normalization/evaluation is
produced by a Claude Code session directly instead of the Anthropic API.

This bypasses normalizer.py/evaluator.py entirely, so no ANTHROPIC_API_KEY
is required -- only NOTION_API_KEY/NOTION_DB_ID.

Workflow:
  1. A Claude Code session reads the JD + profile.md and writes a JobPosting-
     shaped JSON file (see schemas.py for fields).
  2. Run: python judge_manual.py <job.json>
     - If the hard filter rejects the posting, this call saves the filtered
       result to Notion and exits -- no evaluation needed.
     - If it passes, this call prints "PASSED" and exits WITHOUT saving, so
       the Claude Code session can then write an Evaluation-shaped JSON file
       and re-run with --evaluation.
  3. Run: python judge_manual.py <job.json> --evaluation <evaluation.json>
     - Re-applies the hard filter (always authoritative here, never trusts
       the caller). If it still passes, saves the full evaluation to Notion.
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import typer

import hard_filter
import notion_writer
from schemas import Evaluation, JobPosting

# Windows consoles often default to a non-UTF-8 codepage (e.g. cp949), which
# raises UnicodeEncodeError on characters like the em dash used in our
# Korean status messages. Force UTF-8 stdout/stderr so `python judge_manual.py`
# works from any console, not just inside test harnesses that capture output
# differently.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8")

app = typer.Typer()


def _load_job(job_json_path: Path) -> JobPosting:
    data = json.loads(job_json_path.read_text(encoding="utf-8"))
    data.setdefault("fetched_at", datetime.now(timezone.utc).isoformat())
    return JobPosting.model_validate(data)


def _load_evaluation(evaluation_json_path: Path) -> Evaluation:
    data = json.loads(evaluation_json_path.read_text(encoding="utf-8"))
    return Evaluation.model_validate(data)


@app.command()
def run(
    job_json: Path = typer.Argument(..., help="JobPosting 필드를 담은 JSON 파일 경로"),
    evaluation_json: Path = typer.Option(
        None,
        "--evaluation",
        help="Evaluation 필드를 담은 JSON 파일 경로 (하드필터 통과 후 2차 실행 시 제공)",
    ),
    version: str = typer.Option("v1-manual", "--version", help="평가기준버전 태그"),
):
    job = _load_job(job_json)

    passed, reasons = hard_filter.hard_filter(job)
    if not passed:
        typer.echo(f"필터 탈락: {reasons}")
        notion_writer.save(job, evaluation=None, filtered_reason=reasons, version=version)
        typer.echo("Notion에 탈락 사유 저장 완료.")
        raise typer.Exit(code=0)

    if evaluation_json is None:
        typer.echo("PASSED — 하드 필터 통과. 평가(Evaluation) JSON을 만들어 --evaluation 옵션으로 다시 실행하세요.")
        raise typer.Exit(code=0)

    evaluation = _load_evaluation(evaluation_json)
    typer.echo(f"회사: {job.company}")
    typer.echo(f"직무: {job.position}")
    typer.echo(f"판정: {evaluation.verdict}")
    typer.echo(f"점수: {evaluation.scores}")
    typer.echo(f"근거자료 충분도: {evaluation.evidence_quality}")

    notion_writer.save(job, evaluation=evaluation, version=version)
    typer.echo("Notion에 평가 결과 저장 완료.")


if __name__ == "__main__":
    app()
