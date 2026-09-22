"""CLI for the "세션 시작 시 자동 1차 분류" workflow (2026-09-22 요청).

job-watcher already notifies Discord the moment a new posting appears, but
that list is flat and unfiltered. This workflow lets a Claude Code session,
at its own start, pull whatever job-watcher has found that hasn't gone
through a quick fit check yet, do a LIGHT judgment pass (normalize just
enough to run hard_filter.py, then -- for postings that pass -- a coarse
profile.md-keyword comparison, NOT the full evidence-by-evidence evaluation
judge_manual.py does), and post the result back to Discord grouped by source
and tier (적합/애매/부적합) so it reads like "자소설 1-1적합/1-2애매/1-3부적합,
사람인 2-1...".

This script only ever handles the deterministic parts -- listing candidates,
recording tiers, and formatting/sending the Discord message. The judgment
itself (what tier a posting belongs in, and why) is the Claude Code session's
job, same division of labor as essay_keywords.py's check/apply split.

  1. `candidates` -- lists postings job-watcher has seen that this workflow
     hasn't classified yet (via mongo_reader.fetch_candidates). Run manually,
     or wired into a SessionStart hook (--json-hook) so a session notices
     them at start.
  2. `record <results.json>` -- after the session has judged each candidate,
     writes {url, company, title, source, tier, reason} results into MongoDB
     (mongo_reader.mark_classified, so the same posting is never reprocessed)
     and posts the grouped summary to Discord (discord_poster). Both steps
     always run together -- there is deliberately no way to mark a posting
     classified without also (attempting to) post it, so a result can never
     go missing silently the way an un-appended essay suggestion would.

results.json shape: a JSON array of objects, each with keys url/company/
title/source/tier/reason. tier must be one of mongo_reader.VALID_TIERS.
"""

import json
import os
import sys
from pathlib import Path

import typer

import discord_poster
import mongo_reader

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8")

app = typer.Typer()


def _format_candidates_report(items: list[dict]) -> str:
    lines = [f"[job-watcher 신규 공고 1차 분류 대기 {len(items)}건]"]
    for it in items:
        lines.append(f"- [{it['source']}] {it['company']} / {it['title']} ({it['url']})")
    lines.append("")
    lines.append(
        "CLAUDE.md의 '세션 시작 시 자동 1차 분류' 절차대로 각 공고를 정규화+하드필터+"
        "profile.md 대조 후, batch_classify.py record <results.json>으로 저장하세요."
    )
    return "\n".join(lines)


@app.command()
def candidates(
    json_hook: bool = typer.Option(
        False,
        "--json-hook",
        help="SessionStart 훅용: 후보가 있을 때만 hookSpecificOutput.additionalContext JSON 출력",
    ),
):
    """List postings job-watcher has seen that haven't been 1차 분류 yet."""
    try:
        items = mongo_reader.fetch_candidates()
    except Exception:
        # MONGODB_URI 미설정, pymongo 미설치, DB 연결 실패 등 -- 이 기능은
        # 선택 사항이라 훅에서는 세션 시작을 막지 않도록 조용히 넘어가고,
        # 직접 실행했을 때만 에러를 보여준다.
        if json_hook:
            raise typer.Exit(code=0)
        raise

    if json_hook:
        if items:
            typer.echo(
                json.dumps(
                    {
                        "hookSpecificOutput": {
                            "hookEventName": "SessionStart",
                            "additionalContext": _format_candidates_report(items),
                        }
                    },
                    ensure_ascii=False,
                )
            )
        raise typer.Exit(code=0)

    if not items:
        typer.echo("신규 후보 없음.")
        return
    for it in items:
        typer.echo(f"[{it['source']}] {it['company']} / {it['title']} - {it['url']}")


@app.command()
def record(results_json: Path = typer.Argument(..., help="{url,company,title,source,tier,reason} 목록 JSON 파일 경로")):
    """Mark each result classified in MongoDB, then post the grouped summary to Discord."""
    results = json.loads(results_json.read_text(encoding="utf-8"))

    invalid = [r["tier"] for r in results if r.get("tier") not in mongo_reader.VALID_TIERS]
    if invalid:
        typer.echo(f"tier는 {mongo_reader.VALID_TIERS} 중 하나여야 합니다 -- 잘못된 값: {invalid}")
        raise typer.Exit(code=1)

    for r in results:
        mongo_reader.mark_classified(
            url=r["url"],
            company=r["company"],
            title=r["title"],
            source=r["source"],
            tier=r["tier"],
            reason=r["reason"],
        )
    typer.echo(f"MongoDB에 {len(results)}건 기록 완료.")

    from dotenv import load_dotenv

    load_dotenv()
    if not os.environ.get("DISCORD_WEBHOOK_URL"):
        typer.echo("DISCORD_WEBHOOK_URL 미설정 -- Discord 전송은 건너뜀.")
        raise typer.Exit(code=0)

    statuses = discord_poster.post_classified_results(results)
    typer.echo(f"Discord 전송 결과: {statuses}")


if __name__ == "__main__":
    app()
