"""Code-based eligibility filter (see docs blueprint section 5).

Rules are hardcoded conditionals only — no LLM calls.
"""

import re
from datetime import date, datetime

from schemas import JobPosting

_YEARS_AT_LEAST_RE = re.compile(r"(\d+)\s*년\s*이상")
_YEARS_RANGE_RE = re.compile(r"(\d+)\s*~\s*(\d+)\s*년")


def _has_new_grad_alternative(required_years: str) -> bool:
    """True when the text offers a 신입 path alongside an experience
    condition (e.g. "신입 또는 경력 3년 이상") -- a 신입 applicant satisfies
    the posting through that alternative, so the years mention isn't a hard
    blocker for them."""
    return "신입" in required_years


def _is_preference_only(required_years: str) -> bool:
    """True when the text reads as a preference ("우대") rather than a
    mandatory condition -- current heuristic: it mentions 우대 and never
    mentions 필수 anywhere in the string."""
    return "우대" in required_years and "필수" not in required_years


def extract_mandatory_min_years(required_years: str | None) -> int | None:
    """Return the minimum years of experience this posting mandatorily
    requires with no 신입 alternative, or None if there's no such hard
    requirement (no years mentioned, a 신입 alternative exists, or the
    mention reads as a preference rather than a mandatory condition).

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
    if _is_preference_only(required_years):
        return None

    years = [int(m.group(1)) for m in _YEARS_AT_LEAST_RE.finditer(required_years)]
    years += [int(m.group(1)) for m in _YEARS_RANGE_RE.finditer(required_years)]
    if not years:
        return None
    return min(years)


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
