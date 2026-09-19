"""Code-based eligibility filter (see docs blueprint section 5).

Rules are hardcoded conditionals only — no LLM calls.
"""

from datetime import date, datetime

from schemas import JobPosting


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

    if job.required_years and "3년" in job.required_years:
        reasons.append("경력 3년 이상 요구")

    if job.deadline and is_past(job.deadline):
        reasons.append("마감 지남")

    # 지원자는 2026년 8월에 이미 졸업했다 (2026-09-17 프로필 갱신, 2026-09-19 사용자 확인).
    # "졸업자만 지원 가능"(졸업예정자 불가) 같은 요건은 이미 학위를 보유한 지원자에게는
    # 애초에 걸릴 일이 없는 조건이므로, education_requirement 기반 탈락 규칙은 여기서
    # 다루지 않는다 (예전에는 "아직 졸업 전" 프로필을 가정해 이 텍스트를 탈락 사유로
    # 취급했었음 -- 그 가정이 더 이상 맞지 않아 제거함).

    return (len(reasons) == 0, reasons)
