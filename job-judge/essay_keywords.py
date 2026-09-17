"""CLI for the 자기소개서 문항 keyword-suggestion workflow (2026-09-17 요청).

The user pastes essay question text directly into a job row's 자기소개서 문항
column in Notion. This script never generates keyword suggestions itself --
that needs profile.md and a Claude Code session's judgment. It only handles
the deterministic parts:

  1. `check` -- finds rows with pending questions (text present, no
     "→ 키워드 후보:" line yet) and prints them. Run manually, or wired into a
     SessionStart hook (--json-hook) so a Claude Code session notices pending
     items at the start of a session and can fill them in from profile.md.
  2. `apply <page_id> <suggestions.json>` -- writes suggestions back, appended
     after each matching question. suggestions.json is {question_text:
     suggestion_text}. This is the ONLY way this script touches Notion, and
     update_essay_questions() only ever sends the 자기소개서 문항 property --
     see notion_writer.py's write-permission rules for 우선순위/지원동기메모/
     지원상태, which this script has no code path to touch.
"""

import json
import sys
from pathlib import Path

import typer

import notion_writer

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8")

app = typer.Typer()


def _format_pending_report(rows: list[dict]) -> str:
    pending_rows = [r for r in rows if r["pending_questions"]]
    if not pending_rows:
        return ""

    lines = ["[자기소개서 문항 - 키워드 제안 대기 중]"]
    for row in pending_rows:
        lines.append(f"\n{row['company']} / {row['position']} (page_id: {row['page_id']})")
        for q in row["pending_questions"]:
            lines.append(f"- {q}")
    return "\n".join(lines)


@app.command()
def check(
    json_hook: bool = typer.Option(
        False,
        "--json-hook",
        help="SessionStart 훅용: 대기 항목이 있을 때만 hookSpecificOutput.additionalContext JSON을 출력",
    ),
):
    """List rows whose 자기소개서 문항 has questions without a keyword suggestion yet."""
    rows = notion_writer.fetch_essay_question_rows()
    report = _format_pending_report(rows)

    if json_hook:
        if report:
            typer.echo(
                json.dumps(
                    {
                        "hookSpecificOutput": {
                            "hookEventName": "SessionStart",
                            "additionalContext": report,
                        }
                    },
                    ensure_ascii=False,
                )
            )
        raise typer.Exit(code=0)

    typer.echo(report if report else "대기 중인 자기소개서 문항 없음.")


@app.command()
def apply(
    page_id: str = typer.Argument(..., help="업데이트할 Notion 페이지 ID"),
    suggestions_json: Path = typer.Argument(
        ..., help='{"질문 원문": "키워드 후보 텍스트"} 형태의 JSON 파일 경로'
    ),
):
    """Append keyword suggestions to matching pending questions and save."""
    suggestions = json.loads(suggestions_json.read_text(encoding="utf-8"))

    rows = notion_writer.fetch_essay_question_rows()
    row = next((r for r in rows if r["page_id"] == page_id), None)
    if row is None:
        typer.echo(f"page_id {page_id}에 해당하는 자기소개서 문항 행을 찾지 못함.")
        raise typer.Exit(code=1)

    new_text = notion_writer.apply_keyword_suggestions(row["text"], suggestions)
    notion_writer.update_essay_questions(page_id, new_text)
    typer.echo(f"{row['company']} / {row['position']} 자기소개서 문항에 키워드 제안 저장 완료.")


if __name__ == "__main__":
    app()
