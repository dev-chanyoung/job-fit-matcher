"""CLI entry point for job-judge (see docs blueprint section 7)."""

import sys
from pathlib import Path

import typer

import evaluator
import extractor
import hard_filter
import normalizer
import notion_writer

# Windows consoles often default to a non-UTF-8 codepage (e.g. cp949), which
# raises UnicodeEncodeError on characters like the em dash used in our
# Korean status messages. Force UTF-8 stdout/stderr so `python judge.py`
# works from any console, not just inside test harnesses that capture output
# differently.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8")

app = typer.Typer()

PROFILE_PATH = Path(__file__).parent / "profile.md"


def _print_result(job, evaluation) -> None:
    typer.echo(f"회사: {job.company}")
    typer.echo(f"직무: {job.position}")
    typer.echo(f"판정: {evaluation.verdict}")
    typer.echo(f"점수: {evaluation.scores}")
    typer.echo(f"근거자료 충분도: {evaluation.evidence_quality}")


@app.command()
def run(input: str):
    # 1. 입력 판별: URL이면 extractor로 본문 추출 시도
    if input.startswith("http"):
        text = extractor.fetch(input)
        if text is None:
            typer.echo("본문 추출 실패 — JD 텍스트를 직접 붙여넣어 주세요.")
            raise typer.Exit(code=1)
        source_url = input
    else:
        text = input
        source_url = None

    # 2. 정규화
    job = normalizer.normalize(text, source_url)

    # 3. 하드 필터
    passed, reasons = hard_filter.hard_filter(job)
    if not passed:
        typer.echo(f"필터 탈락: {reasons}")
        notion_writer.save(job, evaluation=None, filtered_reason=reasons)
        raise typer.Exit(code=0)

    # 4. 평가
    profile_text = PROFILE_PATH.read_text(encoding="utf-8")
    evaluation = evaluator.evaluate(job, profile_text)

    # 5. 출력 + 저장
    _print_result(job, evaluation)
    notion_writer.save(job, evaluation)


if __name__ == "__main__":
    app()
