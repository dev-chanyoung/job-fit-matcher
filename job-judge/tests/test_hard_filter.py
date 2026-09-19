"""Unit tests for hard_filter.py."""

import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hard_filter import hard_filter, is_past  # noqa: E402
from schemas import JobPosting  # noqa: E402

FUTURE_DATE = (date.today() + timedelta(days=30)).isoformat()
PAST_DATE = (date.today() - timedelta(days=30)).isoformat()


def _valid_job_kwargs(**overrides):
    kwargs = {
        "company": "테스트회사",
        "position": "백엔드 개발자",
        "fetched_at": "2026-09-16T00:00:00",
    }
    kwargs.update(overrides)
    return kwargs


class TestHardFilterPass:
    def test_pass_case(self):
        job = JobPosting(
            **_valid_job_kwargs(
                required_years=None,
                deadline=FUTURE_DATE,
                education_requirement=None,
            )
        )
        assert hard_filter(job) == (True, [])


class TestHardFilterFail:
    def test_fail_required_years_only(self):
        job = JobPosting(
            **_valid_job_kwargs(
                required_years="3년 이상",
                deadline=FUTURE_DATE,
                education_requirement=None,
            )
        )
        assert hard_filter(job) == (False, ["경력 3년 이상 요구"])

    def test_pass_required_years_3_or_fewer_not_flagged(self):
        # "3년 이하"는 신입도 포함하는 요건이라 "3년 이상 요구"와는 반대 의미다.
        job = JobPosting(
            **_valid_job_kwargs(
                required_years="신입 또는 유관경력 3년 이하",
                deadline=FUTURE_DATE,
                education_requirement=None,
            )
        )
        assert hard_filter(job) == (True, [])

    def test_fail_deadline_only(self):
        job = JobPosting(
            **_valid_job_kwargs(
                required_years=None,
                deadline=PAST_DATE,
                education_requirement=None,
            )
        )
        assert hard_filter(job) == (False, ["마감 지남"])

    def test_pass_education_graduates_only_not_flagged(self):
        # 지원자는 이미 졸업했으므로 "졸업자만 지원 가능" 요건은 탈락 사유가 아니다.
        job = JobPosting(
            **_valid_job_kwargs(
                required_years=None,
                deadline=FUTURE_DATE,
                education_requirement="학사 졸업자",
            )
        )
        assert hard_filter(job) == (True, [])

    def test_pass_education_soon_to_graduate_not_flagged(self):
        job = JobPosting(
            **_valid_job_kwargs(
                required_years=None,
                deadline=FUTURE_DATE,
                education_requirement="졸업예정자 가능",
            )
        )
        assert hard_filter(job) == (True, [])

    def test_combined_failures(self):
        job = JobPosting(
            **_valid_job_kwargs(
                required_years="3년 이상",
                deadline=PAST_DATE,
                education_requirement=None,
            )
        )
        passed, reasons = hard_filter(job)
        assert passed is False
        assert len(reasons) == 2


class TestIsPast:
    def test_past_date_is_true(self):
        assert is_past(PAST_DATE) is True

    def test_future_date_is_false(self):
        assert is_past(FUTURE_DATE) is False

    def test_malformed_string_is_false(self):
        assert is_past("not-a-date") is False
