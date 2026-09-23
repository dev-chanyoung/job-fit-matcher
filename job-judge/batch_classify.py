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
import re
import sys
from pathlib import Path

import typer

import discord_poster
import mongo_reader
import notion_writer

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8")

app = typer.Typer()

# 소스 간 중복 회사 제거 시 남길 소스의 우선순위 (2026-09-22 사용자 요청: 자소설닷컴 우선).
# 숫자가 작을수록 우선.
_SOURCE_PRIORITY = {"jasoseol": 0, "saramin": 1}
_PAREN_RE = re.compile(r"\([^)]*\)")
_CORP_DESIGNATOR_RE = re.compile(r"㈜|주식회사|그룹|\s+")

# 제목에 이 괄호 내용만 있으면 "특정 직무를 콕 집지 않은 일반 문구"로 취급한다
# (2026-09-23 사용자 요청 -- 아래 _is_generic_bundle_title 참고).
_GENERIC_TITLE_PAREN_TOKENS = {
    "신입", "경력", "신입/경력", "신입 또는 경력", "인턴", "정규직", "계약직",
    "채용연계형 인턴", "체험형 인턴", "체험형",
}
_TITLE_PAREN_RE = re.compile(r"\(([^()]*(?:\([^()]*\))?[^()]*)\)")


def _normalize_company(name: str) -> str:
    """Loosely normalize a company name for cross-source/Notion duplicate
    matching -- strips any parenthetical qualifier (legal-entity markers
    like "(주)"/"㈜", but also sub-division tags like "(제조계열사)" or
    "(C부문)"), then common Korean corporate designators ("주식회사", the
    "그룹" (group) suffix some group-wide 공채 postings use in place of the
    legal entity name, e.g. "G유통그룹" vs "(주)G유통") and whitespace.
    Deliberately collapses different divisions of the same parent company
    (e.g. "A사(C부문)" and "A사(커머스부문)") to one key -- once ANY
    row for a company exists in Notion, or a higher-priority source already
    has it, that's the intended "already tracked, don't notify again"
    behavior (2026-09-22 사용자 요청), not a bug. This is a heuristic, not an
    exact registry match: it can miss real duplicates with unusual naming,
    or in principle over-merge two genuinely different companies that
    happen to normalize the same way -- acceptable here since a human
    always reviews the Discord output before acting on it."""
    without_parens = _PAREN_RE.sub("", name)
    return _CORP_DESIGNATOR_RE.sub("", without_parens)


def _is_generic_bundle_title(title: str) -> bool:
    """True when `title` reads as a company-wide "we're hiring" announcement
    with no specific role named -- e.g. "2026 신입사원 공개채용" or "26년
    하반기 신입사원 채용" -- as opposed to a specific-role posting like
    "J그룹 2026년 하반기 신입사원 공개채용(웹개발자(AI응용))" or "26년
    하반기 신입사원 채용 (데이터 사이언티스트/데이터)" (2026-09-23 사용자
    요청). jasoseol postings are almost always the former (one page bundling
    every division/role of a group-wide 공채); saramin postings for the same
    company are often the latter (one specific role) -- so a company-name
    match alone isn't enough to call two listings "the same posting". Only a
    title with NO parenthetical content, or whose only parenthetical content
    is a generic employment-type qualifier (_GENERIC_TITLE_PAREN_TOKENS,
    e.g. "(신입)", "(인턴)"), counts as generic; any other parenthetical
    (a role, 부문, 트랙 name) makes it role-specific. Heuristic, not a JD
    diff -- a role named outside parentheses (rare in observed titles) would
    still be missed, and a human reviews the Discord output regardless."""
    generic_tokens = {t.replace(" ", "") for t in _GENERIC_TITLE_PAREN_TOKENS}
    parens = _TITLE_PAREN_RE.findall(title)
    return all(p.replace(" ", "") in generic_tokens for p in parens)


def _dedupe_cross_source(results: list[dict]) -> list[dict]:
    """Drop an item only when it's both (a) outranked by a higher-priority
    source (jasoseol over saramin) that has an item for the same normalized
    company, AND (b) itself reads as a generic company-wide bundle title
    (_is_generic_bundle_title) -- i.e. the two listings plausibly describe
    the SAME posting. A role-specific title (e.g. a saramin listing naming
    an actual position) is kept even when the company already has a generic
    jasoseol bundle, since that jasoseol page won't have that role's actual
    담당업무/자격요건 detail (2026-09-23 사용자 요청 -- 같은 공고면 자소설만,
    내용이 다르면 둘 다 보낸다). Items are never dropped for duplicating
    another item from their OWN source -- a single source can legitimately
    list multiple distinct postings for one company."""
    companies_by_source: dict[str, set[str]] = {}
    for item in results:
        key = _normalize_company(item.get("company") or "")
        if key:
            companies_by_source.setdefault(item["source"], set()).add(key)

    kept = []
    for item in results:
        key = _normalize_company(item.get("company") or "")
        source = item["source"]
        outranked = key and any(
            key in companies
            for other_source, companies in companies_by_source.items()
            if other_source != source
            and _SOURCE_PRIORITY.get(other_source, 99) < _SOURCE_PRIORITY.get(source, 99)
        )
        if not outranked or not _is_generic_bundle_title(item.get("title") or ""):
            kept.append(item)
    return kept


def _dedupe_against_notion(results: list[dict]) -> list[dict]:
    """Drop any item whose normalized company already has at least one row
    in the Notion tracker DB (2026-09-22 사용자 요청: H그룹/I항공처럼 이미
    Notion에 올라가 있는 회사가 job-watcher에서 새 URL로 다시 발견되면서 또
    Discord로 추천되는 문제) -- a company already being tracked doesn't need a
    fresh notification just because the posting resurfaced under a different
    URL/position (URL+position 기준인 notion_writer.save()의 dedup은 이 경우를
    못 잡는다). Best-effort: if the Notion lookup itself fails (missing
    credentials, network), results are returned unchanged with a warning --
    this layer must never block record() from doing its core job of marking
    MongoDB and sending Discord."""
    try:
        existing_companies = {_normalize_company(c) for c in notion_writer.fetch_existing_companies()}
    except Exception as err:  # noqa: BLE001 -- best-effort layer, must not block record()
        typer.echo(f"Notion 기존 회사 목록 조회 실패 -- 이 중복 제거 단계는 건너뜀: {err}")
        return results

    return [r for r in results if _normalize_company(r.get("company") or "") not in existing_companies]


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

    after_source_dedup = _dedupe_cross_source(results)
    source_dropped = len(results) - len(after_source_dedup)
    if source_dropped:
        typer.echo(f"소스 간 중복 {source_dropped}건은 자소설닷컴 우선으로 Discord 전송에서 제외 (MongoDB 기록은 그대로 유지).")

    deduped = _dedupe_against_notion(after_source_dedup)
    notion_dropped = len(after_source_dedup) - len(deduped)
    if notion_dropped:
        typer.echo(f"이미 Notion에 있는 회사 {notion_dropped}건은 Discord 전송에서 제외 (MongoDB 기록은 그대로 유지).")

    statuses = discord_poster.post_classified_results(deduped)
    typer.echo(f"Discord 전송 결과: {statuses}")


if __name__ == "__main__":
    app()
