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

    if job.education_requirement:
        # 졸업예정자(soon-to-graduate)는 "졸업자만" 요건으로 취급하지 않는다.
        # "졸업자"가 포함되어 있어도 "졸업예정"이 포함되어 있으면 플래그하지 않음.
        if "졸업자" in job.education_requirement and "졸업예정" not in job.education_requirement:
            reasons.append("학사 졸업자 요건 (졸업예정자 아님)")

    return (len(reasons) == 0, reasons)
