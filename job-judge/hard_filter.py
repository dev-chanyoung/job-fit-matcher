"""Code-based eligibility filter (see docs blueprint section 5).

Rules are hardcoded conditionals only — no LLM calls.
"""

import re
from datetime import date, datetime

from schemas import JobPosting

_YEARS_AT_LEAST_RE = re.compile(r"(\d+)\s*년\s*이상")
_YEARS_RANGE_RE = re.compile(r"(\d+)\s*~\s*(\d+)\s*년")
# "신입" 앞뒤(쉼표/슬래시/줄바꿈으로 안 끊긴 10자 이내)에 부정어가 있으면 신입 대체경로가
# 아니라 "신입 지원 불가"·"지원 불가 신입" 같은 배제 문구다 (2026-09-19 재발견 버그:
# "신입"이라는 글자만 보고 무조건 대체경로로 오판했었음. 앞쪽 부정어는 2026-09-30 추가).
_NEG = r"(?:불가|제외|안\s?됨|어려움)"
_NEW_GRAD_NEGATION_RE = re.compile(rf"신입[^,·/\n]{{0,10}}{_NEG}|{_NEG}[^,·/\n]{{0,10}}신입")
_CLAUSE_SPLIT_RE = re.compile(r"[,\n·/]")


def _has_new_grad_alternative(required_years: str) -> bool:
    """True when the text offers a 신입 path alongside an experience
    condition (e.g. "신입 또는 경력 3년 이상") -- a 신입 applicant satisfies
    the posting through that alternative, so the years mention isn't a hard
    blocker for them. Excludes phrasing that negates 신입 nearby (e.g.
    "경력 3년 이상 (신입 지원 불가)") -- the bare substring "신입" alone
    isn't enough to tell the two apart."""
    if "신입" not in required_years:
        return False
    return _NEW_GRAD_NEGATION_RE.search(required_years) is None


def _clause_containing(text: str, position: int) -> str:
    """Return the comma/slash/middle-dot/newline-delimited clause that
    `position` falls in, so a preference marker ("우대") describing a
    DIFFERENT clause doesn't leak into an unrelated years mention in the
    same required_years string (e.g. "경력 3년 이상, 금융권 경험 우대" --
    that "우대" describes 금융권 경험, not the 3년 이상 requirement)."""
    last = 0
    for sep in _CLAUSE_SPLIT_RE.finditer(text):
        if last <= position < sep.start():
            return text[last:sep.start()]
        last = sep.end()
    return text[last:]


def _is_preference_mention(clause: str) -> bool:
    """True when THIS clause (not the whole required_years string) reads as
    a preference ("우대") rather than a mandatory condition -- heuristic:
    the clause mentions 우대 and not 필수."""
    return "우대" in clause and "필수" not in clause


def extract_mandatory_min_years(required_years: str | None) -> int | None:
    """Return the minimum years of experience this posting mandatorily
    requires with no 신입 alternative, or None if there's no such hard
    requirement (no years mentioned, a 신입 alternative exists, the years
    mention's own clause reads as a preference, or the required minimum is
    0 -- which a 신입 applicant trivially satisfies regardless of wording).

    This is a text heuristic over freeform Korean, not a full parser or
    OR/AND grouping engine -- phrasing that doesn't match a recognized
    pattern intentionally falls through to None (not rejected), per project
    policy: hard_filter must never auto-reject on a reading it isn't
    confident about (that gets surfaced during the qualitative evaluation
    step instead).
    """
    if not required_years:
        return None
    if _has_new_grad_alternative(required_years):
        return None

    mandatory_years: list[int] = []
    for pattern in (_YEARS_AT_LEAST_RE, _YEARS_RANGE_RE):
        for m in pattern.finditer(required_years):
            if _is_preference_mention(_clause_containing(required_years, m.start())):
                continue
            years = int(m.group(1))
            if years > 0:
                mandatory_years.append(years)

    if not mandatory_years:
        return None
    return min(mandatory_years)


def is_past(deadline_str: str) -> bool:
    """Return True if deadline_str parses to a date strictly before today.

    Accepts at least "YYYY-MM-DD" and full ISO datetime strings. If the
    string cannot be parsed, treat it as not-past (return False) rather
    than raising, since a malformed deadline shouldn't crash the filter.
    """
    try:
        parsed = datetime.fromisoformat(deadline_str)
        deadline_date = parsed.date()
    except (TypeError, ValueError):
        try:
            deadline_date = date.fromisoformat(deadline_str)
        except (TypeError, ValueError):
            return False
    return deadline_date < date.today()


def hard_filter(job: JobPosting) -> tuple[bool, list[str]]:
    """Apply hardcoded eligibility rules to a JobPosting.

    Returns (passed, reasons) where passed is True iff no rule flagged
    the posting, and reasons lists the human-readable reasons for any
    disqualification.
    """
    reasons: list[str] = []

    min_years = extract_mandatory_min_years(job.required_years)
    if min_years is not None:
        reasons.append(f"경력 {min_years}년 이상 요구 (신입 지원 경로 없음)")

    if job.deadline and is_past(job.deadline):
        reasons.append("마감 지남")

    # 지원자는 2026년 8월에 이미 졸업했다 (2026-09-17 프로필 갱신, 2026-09-19 사용자 확인).
    # "졸업자만 지원 가능"(졸업예정자 불가) 같은 요건은 이미 학위를 보유한 지원자에게는
    # 애초에 걸릴 일이 없는 조건이므로, education_requirement 기반 탈락 규칙은 여기서
    # 다루지 않는다 (예전에는 "아직 졸업 전" 프로필을 가정해 이 텍스트를 탈락 사유로
    # 취급했었음 -- 그 가정이 더 이상 맞지 않아 제거함).

    return (len(reasons) == 0, reasons)
