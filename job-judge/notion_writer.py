"""Existing tracker lookup/dedup + save to Notion (see docs blueprint section 8).

Write-permission rules (blueprint section 8 table) are enforced here:
- 자동 채움 (auto-fill): 회사명/직무명/공고링크/마감일/기술스택/연차요건 are always
  written from JobPosting. 기업규모/도메인 are also auto-filled, but only when
  JobPosting.company_size/domain exactly matches one of Notion's fixed select
  options -- otherwise the column is left blank and the guess is mentioned as
  "추정: OO" text in 결과분석 instead (see format_result_analysis).
- 제안 (suggested): 결과분석 is written for human review.
- 지원상태 (scoped exception): defaults to "관심있음" ONLY when creating a brand
  new page, so new postings sort correctly by default -- EXCEPT when the
  posting's deadline has already passed as of today, in which case the
  create-time default is "지원안함" instead (2026-09-17 사용자 요청). An
  existing row's 지원상태 is never touched by an update, regardless of
  deadline.
- 자동화 금지 (never touched by code): 우선순위/지원동기메모 must never appear as
  keys in any properties payload sent to Notion, for create or update -- and
  지원상태 must never appear in the payload used for an *update* of an
  existing row, only in the one-time create payload.
"""

import os
from datetime import datetime

from hard_filter import is_past
from schemas import Evaluation, JobPosting

DB_NAME = "백엔드_공고_트래커"

# 기술스택 fixed multi_select options (blueprint section 8). Automation must
# never introduce a new option -- only exact (case-sensitive) matches from
# this list may be written to the 기술스택 column.
FIXED_TECH_STACK_OPTIONS = [
    "Java",
    "Spring Boot",
    "MySQL",
    "AWS",
    "Kotlin",
    "Spring",
    "Kafka",
    "Docker",
    "Python",
    "TypeScript",
    "React",
    "Azure",
    "Kubernetes",
    "Go",
    "C#",
    "C++",
    "MFC",
]

# 기업규모/도메인 fixed select options, exactly as configured in the Notion
# database. Same rule as 기술스택: only an exact (case-sensitive) match may be
# written to the column -- automation must never introduce a new option.
FIXED_COMPANY_SIZE_OPTIONS = ["스타트업", "중견기업", "대기업"]
FIXED_DOMAIN_OPTIONS = ["커머스", "핀테크", "금융", "제조/자동차", "IT서비스", "통신"]

SCORE_LABELS = [
    ("필수요건_충족", "필수요건"),
    ("기술스택_일치", "기술스택"),
    ("업무내용_일치", "업무내용"),
    ("우대사항", "우대사항"),
    ("도메인_연관성", "도메인"),
]


def match_tech_stack(tech_stack: list[str]) -> list[str]:
    """Return only the items in tech_stack that exactly match a fixed option.

    Matching is case-sensitive exact string match against
    FIXED_TECH_STACK_OPTIONS -- e.g. "spring boot" (lowercase) will NOT match
    "Spring Boot". This is intentional: it avoids accidentally normalizing
    unrelated tech names into a fixed option. Non-matching names are dropped
    here; callers should mention them in the 결과분석 text instead.
    """
    fixed_set = set(FIXED_TECH_STACK_OPTIONS)
    return [tech for tech in tech_stack if tech in fixed_set]


def match_company_size(company_size: str | None) -> str | None:
    """Return company_size if it exactly matches a fixed 기업규모 option, else None."""
    if company_size in FIXED_COMPANY_SIZE_OPTIONS:
        return company_size
    return None


def match_domain(domain: str | None) -> str | None:
    """Return domain if it exactly matches a fixed 도메인 option, else None."""
    if domain in FIXED_DOMAIN_OPTIONS:
        return domain
    return None


def classify_years_requirement(job: JobPosting) -> str:
    """Force-classify required_years into "신입~3년" or "경력무관".

    Defaults to "신입~3년" (conservative) whenever required_years is None or
    does not clearly indicate "no experience required". Only returns
    "경력무관" when the text explicitly contains "경력무관" or "무관".
    """
    required_years = job.required_years
    if required_years and ("경력무관" in required_years or "무관" in required_years):
        return "경력무관"
    return "신입~3년"


def format_result_analysis(
    evaluation: Evaluation,
    version: str = "v1",
    uncertain_company_size: str | None = None,
    uncertain_domain: str | None = None,
) -> str:
    """Produce the 결과분석 text block.

    Leads with qualitative fit/mismatch reasoning (which parts match, which
    don't) built from the evidence/gaps fields, since that's what a human
    scans first when deciding whether to apply. The numeric score breakdown
    is kept as a secondary reference line, not the headline.

    uncertain_company_size/uncertain_domain are only for the case where the
    guess doesn't match a fixed Notion select option -- they get mentioned
    here as text instead of being written to the 기업규모/도메인 columns.
    """
    date_str = datetime.now().date().isoformat()
    scores = evaluation.scores
    score_parts = " ".join(
        f"{label}{scores.get(key, 0)}" for key, label in SCORE_LABELS
    )
    total = sum(scores.get(key, 0) for key, _ in SCORE_LABELS)

    fit_evidence = [e for e in evaluation.evidence if e.match_level in ("강함", "일부")]
    weak_evidence = [e for e in evaluation.evidence if e.match_level in ("미확인", "없음")]

    lines = [
        f"[{version} 평가결과 / {date_str}]",
        f"판정: {evaluation.verdict}",
        "",
        "적합한 부분:",
    ]
    if fit_evidence:
        lines += [
            f"- {e.jd_requirement} → {e.profile_basis} ({e.match_level})"
            for e in fit_evidence
        ]
    else:
        lines.append("- (뚜렷한 강점 근거 없음)")

    lines += ["", "부족하거나 안 맞는 부분:"]
    weak_lines = [
        f"- {e.jd_requirement} → {e.profile_basis} ({e.match_level})"
        for e in weak_evidence
    ] + [f"- {gap}" for gap in evaluation.gaps]
    lines += weak_lines if weak_lines else ["- (특별히 없음)"]

    if evaluation.cover_letter_topics:
        lines += ["", f"자소서 소재: {', '.join(evaluation.cover_letter_topics)}"]

    lines += ["", f"(참고) 배점: {score_parts} (총{total})"]
    if uncertain_company_size:
        lines.append(f"추정 기업규모: {uncertain_company_size} (고정 옵션에 없어 컬럼 미기입)")
    if uncertain_domain:
        lines.append(f"추정 도메인: {uncertain_domain} (고정 옵션에 없어 컬럼 미기입)")

    return "\n".join(lines)


def _title(content: str) -> dict:
    return {"title": [{"text": {"content": content}}]}


def _rich_text(content: str) -> dict:
    return {"rich_text": [{"text": {"content": content}}]}


def _url(content: str | None) -> dict:
    return {"url": content}


def _date(content: str | None) -> dict:
    if not content:
        return {"date": None}
    return {"date": {"start": content}}


def _select(name: str) -> dict:
    return {"select": {"name": name}}


def _multi_select(names: list[str]) -> dict:
    return {"multi_select": [{"name": n} for n in names]}


def _build_properties(
    job: JobPosting,
    result_analysis_text: str,
    version: str | None,
) -> dict:
    """Build a Notion properties dict containing ONLY the fields automation
    is permitted to write: 자동 채움 fields + 기술스택 + 연차요건 + 결과분석
    (+ 평가기준버전 when a version is given).

    자동화 금지 fields (우선순위/지원동기메모) are never constructed here -- they
    simply have no code path that adds them to this dict. 지원상태 is also
    never added here -- the create-only default is layered on separately in
    save(), never as part of this shared create/update payload.
    """
    properties: dict = {
        "회사명": _title(job.company),
        "직무명": _rich_text(job.position),
        "마감일": _date(job.deadline),
        "기술스택": _multi_select(match_tech_stack(job.tech_stack)),
        "연차요건": _select(classify_years_requirement(job)),
        "결과분석": _rich_text(result_analysis_text),
    }
    if job.source_url:
        properties["공고링크"] = _url(job.source_url)
    if version is not None:
        properties["평가기준버전"] = _rich_text(version)

    matched_size = match_company_size(job.company_size)
    if matched_size:
        properties["기업규모"] = _select(matched_size)

    matched_domain = match_domain(job.domain)
    if matched_domain:
        properties["도메인"] = _select(matched_domain)

    return properties


def _resolve_data_source_id(client, db_id: str) -> str:
    """Resolve a database ID to its (first) data source ID.

    Notion's API (2025-09+) scopes properties/queries to a "data source"
    under a database rather than the database object itself -- a database
    retrieved by ID exposes a `data_sources` list instead of `properties`
    directly. This tracker DB has exactly one data source in practice, so
    we use the first one.
    """
    db = client.databases.retrieve(database_id=db_id)
    data_sources = db.get("data_sources") or []
    if not data_sources:
        raise RuntimeError(f"Notion database {db_id} has no data sources")
    return data_sources[0]["id"]


def save(
    job: JobPosting,
    evaluation: Evaluation | None,
    filtered_reason: list[str] | None = None,
    client=None,
    db_id: str | None = None,
    version: str = "v1",
) -> None:
    """Create or update a row in the 백엔드_공고_트래커 Notion DB for job.

    Looks up an existing row by 공고링크 == job.source_url. If found, updates
    it; otherwise creates a new page. In both cases the properties payload
    contains only 자동 채움 + 기술스택 + 연차요건 + 기업규모/도메인(고정 옵션
    매칭 시) + 결과분석 (+ 평가기준버전) fields -- 우선순위/지원동기메모 are
    never included, and 지원상태 is added ONLY for a brand-new page (never on
    an update to an existing row).

    If evaluation is None (hard-filtered case), 결과분석 is instead built from
    filtered_reason as "필터 탈락: {reasons}".
    """
    if client is None:
        from dotenv import load_dotenv

        load_dotenv()
        from notion_client import Client

        client = Client(auth=os.environ.get("NOTION_API_KEY"))

    if db_id is None:
        db_id = os.environ.get("NOTION_DB_ID")

    data_source_id = _resolve_data_source_id(client, db_id)

    uncertain_company_size = (
        job.company_size if job.company_size and not match_company_size(job.company_size) else None
    )
    uncertain_domain = job.domain if job.domain and not match_domain(job.domain) else None

    if evaluation is not None:
        result_analysis_text = format_result_analysis(
            evaluation,
            version=version,
            uncertain_company_size=uncertain_company_size,
            uncertain_domain=uncertain_domain,
        )
    else:
        reasons = ", ".join(filtered_reason or [])
        result_analysis_text = f"필터 탈락: {reasons}"

    properties = _build_properties(job, result_analysis_text, version)

    existing_page_id = None
    if job.source_url:
        query_result = client.data_sources.query(
            data_source_id=data_source_id,
            filter={
                "property": "공고링크",
                "url": {"equals": job.source_url},
            },
        )
        results = query_result.get("results", [])
        if results:
            existing_page_id = results[0]["id"]

    if existing_page_id:
        client.pages.update(page_id=existing_page_id, properties=properties)
    else:
        # 지원상태 default is layered on ONLY here, for a brand-new row, so it
        # sorts correctly from the start -- an update to an existing row above
        # never sees this key and therefore never overwrites a value a human
        # (or a prior run) already set. If the deadline has already passed as
        # of today, default to 지원안함 instead of 관심있음 (2026-09-17 요청).
        default_status = "지원안함" if job.deadline and is_past(job.deadline) else "관심있음"
        create_properties = {**properties, "지원상태": _select(default_status)}
        client.pages.create(
            parent={"type": "data_source_id", "data_source_id": data_source_id},
            properties=create_properties,
        )
