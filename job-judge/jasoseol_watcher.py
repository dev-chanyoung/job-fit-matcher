"""Daily discovery watcher for a fixed jasoseol.com job-search filter.

Detects postings that are NEW since the last run and sends a Discord
notification listing them. Deliberately does NOT run hard_filter.py or any
evaluation -- this is a lightweight discovery layer only; the user reviews
the Discord message and manually pastes whichever links they want judged
into a Claude Code session later, exactly like the judge_manual.py workflow
described in CLAUDE.md.

jasoseol.com's search page is server-rendered by Next.js and ships the full
result list as JSON inside a <script id="__NEXT_DATA__"> tag -- no browser/
JS execution needed (confirmed live 2026-09-22: perPage=100 returns every
posting matching the filter in one request). Because the whole thing is a
deterministic HTTP fetch + JSON parse, this module contains NO LLM call --
mirrors hard_filter.py's principle of keeping deterministic logic out of
LLM judgment, and keeps the recurring cron cost close to zero.
"""

import json
import os
import re
import sys
from datetime import date, datetime
from pathlib import Path

import httpx
import typer

# Windows consoles often default to a non-UTF-8 codepage (e.g. cp949), which
# raises UnicodeEncodeError on Korean text / em dashes. Same fix as
# judge_manual.py -- force UTF-8 stdout/stderr so this works from any console.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8")

app = typer.Typer()

# 사용자가 실제 보고 있는 필터를 그대로 사용 (대기업/중견기업, IT 관련 duty group,
# 마감 제외). 필터를 바꾸고 싶으면 이 상수만 교체하면 된다.
SEARCH_URL = (
    "https://jasoseol.com/search?division=1%2C3%2C4"
    "&businessTypes=big_business%2Cmiddle_market"
    "&dutyGroupIds=160%2C164%2C165%2C166%2C170%2C171%2C176%2C177%2C178"
    "&excludeClosed=true"
)
PER_PAGE = 100
TIMEOUT_SECONDS = 10
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
# 현재 필터는 54건이라 1페이지(perPage=100)로 충분하지만, 나중에 늘어날 경우를
# 대비한 페이지네이션 안전장치 -- 응답 구조가 깨져도 무한루프에 빠지지 않게 상한을 둔다.
MAX_PAGES = 20

STATE_PATH = Path(__file__).parent / "watch_state" / "jasoseol_seen.json"
DISCORD_CONTENT_LIMIT = 2000

_NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
    re.DOTALL,
)


def _fetch_html(url: str) -> str:
    """Fetch url's raw HTML. Unlike extractor.fetch(), this raises on any
    failure instead of returning None -- a watcher run must not mistake
    "site unreachable" for "no new postings today" (that would silently
    hide the failure in cron logs)."""
    response = httpx.get(url, timeout=TIMEOUT_SECONDS, headers={"User-Agent": USER_AGENT})
    response.raise_for_status()
    return response.text


def _parse_next_data(html: str) -> dict:
    """Extract and parse the Next.js __NEXT_DATA__ JSON payload embedded in
    the server-rendered HTML. extractor.fetch() can't be reused here --
    trafilatura.extract() strips <script> tags entirely, which would destroy
    this payload."""
    match = _NEXT_DATA_RE.search(html)
    if not match:
        raise ValueError(
            "__NEXT_DATA__ script tag not found -- jasoseol.com markup may have changed"
        )
    return json.loads(match.group(1))


def _extract_postings(next_data: dict) -> dict:
    """Drill into the react-query dehydrated cache to the search result
    payload: {"data": [...postings...], "page", "perPage", "totalCount"}."""
    try:
        queries = next_data["props"]["pageProps"]["dehydratedState"]["queries"]
        return queries[0]["state"]["data"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError(
            f"Unexpected __NEXT_DATA__ shape -- jasoseol.com response structure may have changed: {exc}"
        ) from exc


def fetch_all_postings(url: str = SEARCH_URL) -> list[dict]:
    """Fetch every posting matching url's filters, paginating if totalCount
    exceeds one page's worth."""
    collected: list[dict] = []
    page = 1
    total_count = None
    while True:
        sep = "&" if "?" in url else "?"
        page_url = f"{url}{sep}perPage={PER_PAGE}&page={page}"
        payload = _extract_postings(_parse_next_data(_fetch_html(page_url)))
        items = payload.get("data", [])
        if total_count is None:
            total_count = payload.get("totalCount", len(items))
        if not items:
            break
        collected.extend(items)
        if len(collected) >= total_count or page >= MAX_PAGES:
            break
        page += 1
    return collected


def posting_url(posting: dict) -> str:
    """Canonical dedup key for a posting -- also its public URL."""
    return f"https://jasoseol.com/recruit/{posting['id']}"


def posting_fields(posting: dict) -> list[str]:
    """Deduplicated list of employments[*].field (e.g. ["품질", "DT"]),
    preserving first-seen order."""
    fields: list[str] = []
    for employment in posting.get("employments", []):
        field = employment.get("field")
        if field and field not in fields:
            fields.append(field)
    return fields


def load_seen_state(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def save_seen_state(state: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def diff_new_postings(postings: list[dict], seen: dict) -> list[dict]:
    return [p for p in postings if posting_url(p) not in seen]


def merge_seen_state(seen: dict, new_postings: list[dict], today: date) -> dict:
    """Return a new dict = seen plus one entry per new_postings. Never
    mutates or overwrites an existing entry -- this single rule is what
    makes an edited posting (same id, changed title) NOT re-trigger as new,
    and a posting whose deadline passed and later reappears under the same
    id also NOT re-trigger (only a genuinely new id counts as new)."""
    merged = dict(seen)
    for posting in new_postings:
        merged[posting_url(posting)] = {
            "first_seen": today.isoformat(),
            "company": posting.get("name", ""),
            "title": posting.get("title", ""),
        }
    return merged


def _format_deadline(posting: dict) -> str:
    end_time = posting.get("end_time")
    if not end_time:
        return "미상"
    try:
        return datetime.fromisoformat(end_time).strftime("%Y-%m-%d")
    except (TypeError, ValueError):
        return "미상"


def format_discord_chunks(new_postings: list[dict]) -> list[str]:
    """Format new_postings into Discord message bodies, splitting into
    multiple chunks so none exceeds Discord's 2000-char content limit."""
    header = f"[자소설닷컴 신규 공고 {len(new_postings)}건]"
    lines = [header]
    for posting in new_postings:
        fields = ", ".join(posting_fields(posting)) or "직무 미상"
        lines.append(
            f"{posting.get('name', '?')} — {posting.get('title', '?')} / {fields} "
            f"/ 마감 {_format_deadline(posting)} / {posting_url(posting)}"
        )

    chunks: list[str] = []
    current = ""
    for line in lines:
        candidate = f"{current}\n{line}" if current else line
        if len(candidate) > DISCORD_CONTENT_LIMIT:
            if current:
                chunks.append(current)
            current = line
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


def _echo_chunks(chunks: list[str]) -> None:
    for chunk in chunks:
        typer.echo(chunk)


def send_discord_notification(chunks: list[str], webhook_url: str) -> None:
    for chunk in chunks:
        response = httpx.post(webhook_url, json={"content": chunk}, timeout=TIMEOUT_SECONDS)
        response.raise_for_status()


def _normalize_company_name(name: str) -> str:
    return re.sub(r"\s+", "", name or "").lower()


def seed_from_notion(client=None, db_id: str | None = None) -> set[str]:
    """Return the set of normalized company names already tracked in the
    Notion job tracker (회사명 property on every existing page). Used ONLY
    on this watcher's very first run, so postings the user already knows
    about (already registered via the manual judge_manual.py workflow)
    don't get re-surfaced as "new" just because the watcher's own state file
    happens to be empty (2026-09-22 user request)."""
    import notion_writer

    if client is None:
        from dotenv import load_dotenv

        load_dotenv()
        from notion_client import Client

        client = Client(auth=os.environ.get("NOTION_API_KEY"))
    if db_id is None:
        db_id = os.environ.get("NOTION_DB_ID")

    data_source_id = notion_writer._resolve_data_source_id(client, db_id)

    names: set[str] = set()
    start_cursor = None
    while True:
        kwargs = {"data_source_id": data_source_id, "page_size": 100}
        if start_cursor:
            kwargs["start_cursor"] = start_cursor
        result = client.data_sources.query(**kwargs)
        for page in result.get("results", []):
            company_prop = page.get("properties", {}).get("회사명", {})
            company = "".join(run.get("plain_text", "") for run in company_prop.get("title", []))
            if company.strip():
                names.add(_normalize_company_name(company))
        if not result.get("has_more"):
            break
        start_cursor = result.get("next_cursor")
    return names


def _company_already_tracked(posting: dict, tracked_names: set[str]) -> bool:
    """Loose match: true if posting's company name contains, or is
    contained by, any already-tracked Notion company name (whitespace-
    stripped, case-insensitive substring check). Intentionally conservative
    -- prefers a missed match (posting resurfaces once, harmless) over a
    false match that would silently hide a genuinely new posting."""
    normalized = _normalize_company_name(posting.get("name", ""))
    if not normalized:
        return False
    return any(normalized in tracked or tracked in normalized for tracked in tracked_names)


@app.command()
def run(
    dry_run: bool = typer.Option(
        False, "--dry-run", help="상태 파일을 저장/알림 발송하지 않고 결과만 미리 확인"
    ),
):
    from dotenv import load_dotenv

    load_dotenv()

    is_first_run = not STATE_PATH.exists()
    postings = fetch_all_postings(SEARCH_URL)

    if is_first_run:
        tracked_names = seed_from_notion()
        seen: dict = {}
        new_postings = []
        today_str = date.today().isoformat()
        for posting in postings:
            if _company_already_tracked(posting, tracked_names):
                seen[posting_url(posting)] = {
                    "first_seen": today_str,
                    "company": posting.get("name", ""),
                    "title": posting.get("title", ""),
                }
            else:
                new_postings.append(posting)
        typer.echo(
            f"최초 실행 -- 공고 {len(postings)}건 중 Notion에 이미 있는 {len(seen)}건은 시드, "
            f"신규 {len(new_postings)}건 처리"
        )
    else:
        seen = load_seen_state(STATE_PATH)
        new_postings = diff_new_postings(postings, seen)
        typer.echo(f"신규 공고 {len(new_postings)}건 발견" if new_postings else "신규 공고 없음")

    if new_postings and not dry_run:
        chunks = format_discord_chunks(new_postings)
        webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
        if webhook_url:
            try:
                send_discord_notification(chunks, webhook_url)
            except httpx.HTTPError as exc:
                # 전송 실패해도 상태 저장은 계속 진행한다 -- 그렇지 않으면 다음 실행에서
                # 같은 공고를 또 "신규"로 판정해 같은 실패를 매일 반복하게 된다 (예:
                # 웹훅 URL이 잘못됐거나 일시적 네트워크 오류인 경우). 이번 회차의 알림은
                # 유실되지만, 콘솔에 남겨서 사람이 나중에라도 확인할 수 있게 한다.
                typer.echo(f"Discord 전송 실패 -- {exc}. 콘솔에 출력만 합니다.")
                _echo_chunks(chunks)
        else:
            typer.echo("DISCORD_WEBHOOK_URL 미설정 -- 콘솔에 출력만 합니다.")
            _echo_chunks(chunks)
    elif new_postings and dry_run:
        typer.echo("(--dry-run: Discord 전송 생략, 아래는 전송될 내용 미리보기)")
        _echo_chunks(format_discord_chunks(new_postings))

    if dry_run:
        typer.echo("(--dry-run: 상태 파일은 저장하지 않았습니다)")
    else:
        merged = merge_seen_state(seen, new_postings, date.today())
        save_seen_state(merged, STATE_PATH)


if __name__ == "__main__":
    app()
