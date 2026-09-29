"""Unit tests for hard_filter.py."""

import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hard_filter import extract_mandatory_min_years, hard_filter, is_past  # noqa: E402
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
        assert hard_filter(job) == (False, ["경력 3년 이상 요구 (신입 지원 경로 없음)"])

    def test_fail_required_years_five_or_more_mandatory(self):
        job = JobPosting(
            **_valid_job_kwargs(required_years="경력 5년 이상 필수", deadline=FUTURE_DATE)
        )
        passed, reasons = hard_filter(job)
        assert passed is False
        assert reasons == ["경력 5년 이상 요구 (신입 지원 경로 없음)"]

    def test_fail_required_years_no_space_variant(self):
        job = JobPosting(**_valid_job_kwargs(required_years="경력 3년이상", deadline=FUTURE_DATE))
        passed, _ = hard_filter(job)
        assert passed is False

    def test_fail_required_years_range_without_isang(self):
        job = JobPosting(**_valid_job_kwargs(required_years="경력 3~5년", deadline=FUTURE_DATE))
        passed, _ = hard_filter(job)
        assert passed is False

    def test_pass_required_years_with_new_grad_alternative(self):
        job = JobPosting(
            **_valid_job_kwargs(required_years="신입 또는 경력 3년 이상", deadline=FUTURE_DATE)
        )
        assert hard_filter(job) == (True, [])

    def test_pass_required_years_preference_only(self):
        job = JobPosting(
            **_valid_job_kwargs(required_years="경력 3년 이상 우대", deadline=FUTURE_DATE)
        )
        assert hard_filter(job) == (True, [])

    def test_pass_zero_years_range(self):
        # "0~3년"의 최소 연차는 0이므로 사실상 경력무관과 같다 -- 탈락 사유가 아니다.
        job = JobPosting(**_valid_job_kwargs(required_years="경력 0~3년", deadline=FUTURE_DATE))
        assert hard_filter(job) == (True, [])

    def test_pass_zero_years_at_least(self):
        job = JobPosting(**_valid_job_kwargs(required_years="경력 0년 이상", deadline=FUTURE_DATE))
        assert hard_filter(job) == (True, [])

    def test_fail_new_grad_explicitly_disallowed(self):
        # "신입"이라는 글자만 보고 대체경로로 착각하면 안 된다 -- 여기선 신입을 명시적으로 배제한다.
        job = JobPosting(
            **_valid_job_kwargs(
                required_years="경력 3년 이상 (신입 지원 불가)", deadline=FUTURE_DATE
            )
        )
        passed, _ = hard_filter(job)
        assert passed is False

    def test_fail_preference_in_different_clause_does_not_cover_mandatory_years(self):
        # "우대"는 금융권 경험에만 붙어 있다 -- 앞의 "경력 3년 이상"까지 우대로 봐주면 안 된다.
        job = JobPosting(
            **_valid_job_kwargs(
                required_years="경력 3년 이상, 금융권 경험 우대", deadline=FUTURE_DATE
            )
        )
        passed, _ = hard_filter(job)
        assert passed is False

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


class TestExtractMandatoryMinYears:
    def test_none_input_returns_none(self):
        assert extract_mandatory_min_years(None) is None

    def test_no_years_mentioned_returns_none(self):
        assert extract_mandatory_min_years("경력무관") is None

    def test_new_grad_alternative_returns_none(self):
        assert extract_mandatory_min_years("신입 또는 경력 3년 이상") is None

    def test_preference_only_returns_none(self):
        assert extract_mandatory_min_years("경력 3년 이상 우대") is None

    def test_mandatory_with_explicit_keyword_returns_min_years(self):
        assert extract_mandatory_min_years("경력 5년 이상 필수") == 5

    def test_plain_at_least_phrasing_returns_years(self):
        assert extract_mandatory_min_years("5년 이상") == 5

    def test_no_space_variant_returns_years(self):
        assert extract_mandatory_min_years("3년이상") == 3

    def test_range_without_isang_returns_lower_bound(self):
        assert extract_mandatory_min_years("3~5년") == 3

    def test_zero_minimum_returns_none(self):
        assert extract_mandatory_min_years("경력 0~3년") is None
        assert extract_mandatory_min_years("경력 0년 이상") is None

    def test_new_grad_negation_is_not_an_alternative(self):
        assert extract_mandatory_min_years("경력 3년 이상 (신입 지원 불가)") == 3

    def test_new_grad_negation_before_keyword_is_not_an_alternative(self):
        assert extract_mandatory_min_years("경력 3년 이상 (지원 불가 신입)") == 3

    def test_negation_in_other_clause_does_not_cancel_new_grad_alternative(self):
        assert extract_mandatory_min_years("경력자 제외, 신입 또는 경력 3년 이상") is None

    def test_preference_in_unrelated_clause_does_not_cover_mandatory_years(self):
        assert extract_mandatory_min_years("경력 3년 이상, 금융권 경험 우대") == 3


class TestIsPast:
    def test_past_date_is_true(self):
        assert is_past(PAST_DATE) is True

    def test_future_date_is_false(self):
        assert is_past(FUTURE_DATE) is False

    def test_malformed_string_is_false(self):
        assert is_past("not-a-date") is False
