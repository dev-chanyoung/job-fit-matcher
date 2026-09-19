"""Unit tests for notion_writer.py.

All Notion client interaction is mocked via unittest.mock.MagicMock -- no
real Notion API calls are made and NOTION_API_KEY is not required.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from notion_writer import (  # noqa: E402
    ESSAY_QUESTIONS_PROPERTY,
    apply_keyword_suggestions,
    classify_years_requirement,
    fetch_essay_question_rows,
    find_pending_questions,
    format_result_analysis,
    match_company_size,
    match_domain,
    match_tech_stack,
    save,
    update_essay_questions,
)
from schemas import Evaluation, JobPosting  # noqa: E402

# 우선순위/지원동기메모: never touched by code, on create or update.
NEVER_TOUCHED_KEYS = {"우선순위", "지원동기메모"}
# 지원상태: allowed ONLY as a one-time default on a brand-new page's create
# payload -- an update to an existing row must never include it.
UPDATE_PROTECTED_KEYS = NEVER_TOUCHED_KEYS | {"지원상태"}


def _valid_job(**overrides):
    kwargs = {
        "company": "테스트회사",
        "position": "백엔드 개발자",
        "source_url": "https://example.com/job/123",
        "fetched_at": "2026-09-16T00:00:00",
        "tech_stack": ["Java", "Spring Boot"],
        "deadline": "2026-12-31",
    }
    kwargs.update(overrides)
    return JobPosting(**kwargs)


def _valid_evaluation(**overrides):
    data = {
        "verdict": "지원 고려",
        "scores": {
            "필수요건_충족": 28,
            "기술스택_일치": 18,
            "업무내용_일치": 15,
            "우대사항": 10,
            "도메인_연관성": 5,
        },
        "evidence": [
            {
                "jd_requirement": "Spring Boot 백엔드 개발 경험",
                "profile_basis": "Spring Boot 3년 경력",
                "match_level": "강함",
            }
        ],
        "gaps": ["메시지 브로커 운영 경험 없음"],
        "cover_letter_topics": ["실시간 처리 프로젝트 경험"],
        "risks": [],
        "evidence_quality": "근거 충분",
    }
    data.update(overrides)
    return Evaluation.model_validate(data)


class TestMatchTechStack:
    def test_returns_only_exact_matches(self):
        result = match_tech_stack(["Java", "Spring Boot", "FooBarLang", "COBOL"])
        assert result == ["Java", "Spring Boot"]


class TestMatchCompanySizeAndDomain:
    def test_company_size_exact_match_passes_through(self):
        assert match_company_size("대기업") == "대기업"

    def test_company_size_non_option_is_dropped(self):
        assert match_company_size("공기업") is None

    def test_domain_exact_match_passes_through(self):
        assert match_domain("IT서비스") == "IT서비스"

    def test_domain_non_option_is_dropped(self):
        assert match_domain("항공운송업") is None

    def test_none_is_dropped_for_both(self):
        assert match_company_size(None) is None
        assert match_domain(None) is None


class TestClassifyYearsRequirement:
    def test_explicit_no_experience_required(self):
        job = _valid_job(required_years="경력무관")
        assert classify_years_requirement(job) == "경력무관"

    def test_none_defaults_to_entry_level(self):
        job = _valid_job(required_years=None)
        assert classify_years_requirement(job) == "신입~3년"

    def test_ambiguous_range_defaults_to_entry_level(self):
        job = _valid_job(required_years="1~3년")
        assert classify_years_requirement(job) == "신입~3년"


class TestFormatResultAnalysis:
    def test_contains_verdict_version_and_score_labels(self):
        evaluation = _valid_evaluation()
        text = format_result_analysis(evaluation, version="v1")

        assert "지원 고려" in text
        assert "v1" in text
        assert "필수요건" in text
        assert "기술스택" in text
        assert "업무내용" in text
        assert "우대사항" in text
        assert "도메인" in text

    def test_leads_with_qualitative_fit_and_gap_sections(self):
        """Score is a secondary reference line; fit/mismatch reasoning is the
        headline the user scans first."""
        evaluation = _valid_evaluation()
        text = format_result_analysis(evaluation, version="v1")

        assert "적합한 부분:" in text
        assert "부족하거나 안 맞는 부분:" in text
        assert "(참고) 배점:" in text
        # The strong-match evidence item lands in the fit section.
        assert "Spring Boot 백엔드 개발 경험 → Spring Boot 3년 경력 (강함)" in text
        # The headline sections appear before the reference score line.
        assert text.index("적합한 부분:") < text.index("(참고) 배점:")

    def test_exposes_evidence_quality_under_verdict(self):
        evaluation = _valid_evaluation(evidence_quality="일부 부족")
        text = format_result_analysis(evaluation, version="v1")

        assert "정보 충분도: 일부 부족" in text
        assert text.index("판정:") < text.index("정보 충분도:") < text.index("적합한 부분:")

    def test_exposes_risks_when_present(self):
        evaluation = _valid_evaluation(risks=["자격증 취득 여부 미확인"])
        text = format_result_analysis(evaluation, version="v1")

        assert "위험 요인:" in text
        assert "- 자격증 취득 여부 미확인" in text

    def test_omits_risks_section_when_empty(self):
        evaluation = _valid_evaluation(risks=[])
        text = format_result_analysis(evaluation, version="v1")

        assert "위험 요인:" not in text

    def test_warns_when_mandatory_score_too_low_for_strong_verdict(self):
        evaluation = _valid_evaluation(
            verdict="적극 지원",
            scores={
                "필수요건_충족": 0,
                "기술스택_일치": 25,
                "업무내용_일치": 20,
                "우대사항": 15,
                "도메인_연관성": 10,
            },
        )
        text = format_result_analysis(evaluation, version="v1")

        assert "⚠ 점수-판정 불일치" in text
        assert "적극 지원" in text  # verdict itself is not overwritten

    def test_no_warning_when_mandatory_score_is_sufficient(self):
        evaluation = _valid_evaluation(
            verdict="적극 지원",
            scores={
                "필수요건_충족": 28,
                "기술스택_일치": 18,
                "업무내용_일치": 15,
                "우대사항": 10,
                "도메인_연관성": 5,
            },
        )
        text = format_result_analysis(evaluation, version="v1")

        assert "⚠ 점수-판정 불일치" not in text

    def test_shows_score_breakdown_line_under_reference_score(self):
        evaluation = _valid_evaluation(
            score_breakdown={
                "기술스택_일치": "Java 100%x2, Spring 75%x2, Redis 25%x1 -> 75% -> 18.75/25 -> 19점"
            }
        )
        text = format_result_analysis(evaluation, version="v1")

        assert "기술스택: Java 100%x2, Spring 75%x2, Redis 25%x1 -> 75% -> 18.75/25 -> 19점" in text
        assert text.index("(참고) 배점:") < text.index("기술스택: Java 100%x2")

    def test_omits_breakdown_lines_when_empty(self):
        evaluation = _valid_evaluation(score_breakdown={})
        text = format_result_analysis(evaluation, version="v1")

        assert "->" not in text

    def test_no_warning_when_verdict_is_not_strong_apply(self):
        evaluation = _valid_evaluation(
            verdict="보류",
            scores={
                "필수요건_충족": 0,
                "기술스택_일치": 0,
                "업무내용_일치": 0,
                "우대사항": 0,
                "도메인_연관성": 0,
            },
        )
        text = format_result_analysis(evaluation, version="v1")

        assert "⚠ 점수-판정 불일치" not in text

    def test_weak_and_unconfirmed_evidence_lands_in_gap_section(self):
        evaluation = _valid_evaluation(
            evidence=[
                {
                    "jd_requirement": "Kafka 운영 경험",
                    "profile_basis": "학습만 해봄, 실무 경험 없음",
                    "match_level": "미확인",
                }
            ],
            gaps=["메시지 브로커 운영 경험 없음"],
        )
        text = format_result_analysis(evaluation, version="v1")

        gap_section = text.split("부족하거나 안 맞는 부분:")[1]
        assert "Kafka 운영 경험 → 학습만 해봄, 실무 경험 없음 (미확인)" in gap_section
        assert "메시지 브로커 운영 경험 없음" in gap_section


def _mock_client_with_data_source(query_results):
    """Build a MagicMock Notion client wired for the current (2025-09+) API,
    where properties/queries are scoped to a data source resolved from the
    database ID via client.databases.retrieve(...)['data_sources']."""
    mock_client = MagicMock()
    mock_client.databases.retrieve.return_value = {
        "data_sources": [{"id": "fake-data-source-id"}]
    }
    mock_client.data_sources.query.return_value = {"results": query_results}
    return mock_client


class TestSaveNewRow:
    def test_creates_page_without_never_touched_fields(self):
        mock_client = _mock_client_with_data_source([])

        job = _valid_job()
        evaluation = _valid_evaluation()

        save(job, evaluation, client=mock_client, db_id="fake-db-id")

        mock_client.data_sources.query.assert_called_once()
        assert (
            mock_client.data_sources.query.call_args.kwargs["data_source_id"]
            == "fake-data-source-id"
        )
        mock_client.pages.create.assert_called_once()
        mock_client.pages.update.assert_not_called()

        _, kwargs = mock_client.pages.create.call_args
        assert kwargs["parent"] == {
            "type": "data_source_id",
            "data_source_id": "fake-data-source-id",
        }
        properties = kwargs["properties"]
        assert NEVER_TOUCHED_KEYS.isdisjoint(properties.keys())

    def test_writes_company_size_and_domain_when_they_match_fixed_options(self):
        mock_client = _mock_client_with_data_source([])

        job = _valid_job(company_size="대기업", domain="IT서비스")
        save(job, _valid_evaluation(), client=mock_client, db_id="fake-db-id")

        _, kwargs = mock_client.pages.create.call_args
        properties = kwargs["properties"]
        assert properties["기업규모"] == {"select": {"name": "대기업"}}
        assert properties["도메인"] == {"select": {"name": "IT서비스"}}

    def test_falls_back_to_result_analysis_text_when_no_fixed_option_matches(self):
        mock_client = _mock_client_with_data_source([])

        job = _valid_job(company_size="공기업", domain="항공운송업")
        save(job, _valid_evaluation(), client=mock_client, db_id="fake-db-id")

        _, kwargs = mock_client.pages.create.call_args
        properties = kwargs["properties"]
        assert "기업규모" not in properties
        assert "도메인" not in properties
        analysis_text = properties["결과분석"]["rich_text"][0]["text"]["content"]
        assert "추정 기업규모: 공기업" in analysis_text
        assert "추정 도메인: 항공운송업" in analysis_text

    def test_writes_score_as_sum_of_evaluation_components(self):
        mock_client = _mock_client_with_data_source([])

        save(_valid_job(), _valid_evaluation(), client=mock_client, db_id="fake-db-id")

        _, kwargs = mock_client.pages.create.call_args
        properties = kwargs["properties"]
        assert properties["점수"] == {"number": 76}

    def test_new_page_defaults_status_to_interested(self):
        """A brand-new row gets 지원상태 defaulted to 관심있음 so it sorts
        correctly alongside postings a human has already triaged."""
        mock_client = _mock_client_with_data_source([])

        save(_valid_job(), _valid_evaluation(), client=mock_client, db_id="fake-db-id")

        _, kwargs = mock_client.pages.create.call_args
        assert kwargs["properties"]["지원상태"] == {"select": {"name": "관심있음"}}

    def test_new_page_defaults_status_to_not_applying_when_deadline_already_passed(self):
        """When the deadline has already passed as of today, a brand-new row
        should default to 지원안함 instead of 관심있음 (2026-09-17 사용자 요청)."""
        mock_client = _mock_client_with_data_source([])

        job = _valid_job(deadline="2020-01-01")
        save(job, _valid_evaluation(), client=mock_client, db_id="fake-db-id")

        _, kwargs = mock_client.pages.create.call_args
        assert kwargs["properties"]["지원상태"] == {"select": {"name": "지원안함"}}


class TestSaveExistingRow:
    def test_updates_existing_page_without_protected_fields(self):
        """An update must never touch 지원상태 either -- the default in
        TestSaveNewRow is strictly a create-time, one-time thing."""
        mock_client = _mock_client_with_data_source([{"id": "existing-page-id"}])

        job = _valid_job()
        evaluation = _valid_evaluation()

        save(job, evaluation, client=mock_client, db_id="fake-db-id")

        mock_client.pages.update.assert_called_once()
        mock_client.pages.create.assert_not_called()

        _, kwargs = mock_client.pages.update.call_args
        assert kwargs["page_id"] == "existing-page-id"
        properties = kwargs["properties"]
        assert UPDATE_PROTECTED_KEYS.isdisjoint(properties.keys())

    def test_dedup_filter_matches_url_and_position_not_url_alone(self):
        """A group-recruiting notice (e.g. a Korean 대기업 공동채용 posting)
        commonly lists many distinct roles under one shared 공고링크. Matching
        an existing row by URL alone would make every role saved from that
        page collide into a single row, silently overwriting one role's data
        with another's (real bug: this happened with a O그룹 posting
        where multiple subsidiaries/roles shared one jobnoticeSn URL)."""
        mock_client = _mock_client_with_data_source([])

        job = _valid_job(position="백엔드 개발자 B")
        save(job, _valid_evaluation(), client=mock_client, db_id="fake-db-id")

        _, kwargs = mock_client.data_sources.query.call_args
        condition = kwargs["filter"]["and"]
        assert {"property": "공고링크", "url": {"equals": job.source_url}} in condition
        assert {"property": "직무명", "rich_text": {"equals": "백엔드 개발자 B"}} in condition
        # No existing row matches this URL+position pair, so it must create,
        # not update -- even though another role at the same URL might exist.
        mock_client.pages.create.assert_called_once()
        mock_client.pages.update.assert_not_called()


class TestSaveHardFiltered:
    def test_hard_filtered_posting_score_is_explicit_null(self):
        """No Evaluation exists for a hard-filtered posting, so 점수 must be
        sent as an EXPLICIT null rather than written as 0 (0 would
        misleadingly read as 'scored and got zero' instead of 'never
        evaluated') and rather than omitted (omitting it on an update would
        leave a stale score from a prior evaluation untouched -- see the
        update test below)."""
        mock_client = _mock_client_with_data_source([])

        save(
            _valid_job(),
            evaluation=None,
            filtered_reason=["마감 지남"],
            client=mock_client,
            db_id="fake-db-id",
        )

        _, kwargs = mock_client.pages.create.call_args
        assert kwargs["properties"]["점수"] == {"number": None}

    def test_hard_filtered_update_clears_stale_score_from_prior_evaluation(self):
        """A posting that was previously evaluated (and scored) later gets
        re-run and hard-filtered -- e.g. its deadline passed -- so the
        update must explicitly null out 점수 instead of leaving the old
        score in place (real bug: omitting the key on update sends no
        instruction to Notion, so a prior score silently lingers)."""
        mock_client = _mock_client_with_data_source([{"id": "existing-page-id"}])

        save(
            _valid_job(),
            evaluation=None,
            filtered_reason=["마감 지남"],
            client=mock_client,
            db_id="fake-db-id",
        )

        mock_client.pages.update.assert_called_once()
        mock_client.pages.create.assert_not_called()
        _, kwargs = mock_client.pages.update.call_args
        assert kwargs["properties"]["점수"] == {"number": None}

    def test_new_row_with_filtered_reason_and_no_evaluation(self):
        mock_client = _mock_client_with_data_source([])

        job = _valid_job()

        save(
            job,
            evaluation=None,
            filtered_reason=["마감 지남"],
            client=mock_client,
            db_id="x",
        )

        mock_client.pages.create.assert_called_once()
        mock_client.pages.update.assert_not_called()

        _, kwargs = mock_client.pages.create.call_args
        properties = kwargs["properties"]
        assert NEVER_TOUCHED_KEYS.isdisjoint(properties.keys())
        assert properties["지원상태"] == {"select": {"name": "관심있음"}}
        assert "마감 지남" in properties["결과분석"]["rich_text"][0]["text"]["content"]


class TestResolveDataSourceId:
    def test_raises_when_no_data_sources(self):
        import pytest

        from notion_writer import _resolve_data_source_id

        mock_client = MagicMock()
        mock_client.databases.retrieve.return_value = {"data_sources": []}

        with pytest.raises(RuntimeError):
            _resolve_data_source_id(mock_client, "some-db-id")


class TestFindPendingQuestions:
    def test_question_without_suggestion_is_pending(self):
        text = "1. 협업 경험을 서술하시오."
        assert find_pending_questions(text) == ["1. 협업 경험을 서술하시오."]

    def test_question_with_suggestion_is_not_pending(self):
        text = "1. 협업 경험을 서술하시오.\n→ 키워드 후보: Clean Eye(협업)"
        assert find_pending_questions(text) == []

    def test_mixed_blocks_only_pending_ones_returned(self):
        text = (
            "1. 협업 경험을 서술하시오.\n→ 키워드 후보: Clean Eye(협업)"
            "\n\n"
            "2. 실패를 극복한 경험은?"
        )
        assert find_pending_questions(text) == ["2. 실패를 극복한 경험은?"]

    def test_blank_text_has_no_pending_questions(self):
        assert find_pending_questions("") == []


class TestApplyKeywordSuggestions:
    def test_appends_suggestion_after_matching_pending_question(self):
        text = "1. 협업 경험을 서술하시오."
        result = apply_keyword_suggestions(
            text, {"1. 협업 경험을 서술하시오.": "Clean Eye(협업/팀프로젝트)"}
        )
        assert result == "1. 협업 경험을 서술하시오.\n→ 키워드 후보: Clean Eye(협업/팀프로젝트)"

    def test_does_not_touch_block_that_already_has_a_suggestion(self):
        text = "1. 협업 경험을 서술하시오.\n→ 키워드 후보: 기존 제안"
        result = apply_keyword_suggestions(text, {"1. 협업 경험을 서술하시오.": "새 제안"})
        assert result == text

    def test_only_updates_questions_present_in_suggestions_dict(self):
        text = "1. 질문 A\n\n2. 질문 B"
        result = apply_keyword_suggestions(text, {"1. 질문 A": "A 제안"})
        assert "1. 질문 A\n→ 키워드 후보: A 제안" in result
        assert "2. 질문 B" in result
        assert "2. 질문 B\n→" not in result


def _mock_client_for_essay_rows(pages):
    mock_client = MagicMock()
    mock_client.databases.retrieve.return_value = {
        "data_sources": [{"id": "fake-data-source-id"}]
    }
    mock_client.data_sources.query.return_value = {"results": pages, "has_more": False}
    return mock_client


def _essay_page(page_id, company, position, essay_text):
    return {
        "id": page_id,
        "properties": {
            "회사명": {"title": [{"plain_text": company}]},
            "직무명": {"rich_text": [{"plain_text": position}]},
            ESSAY_QUESTIONS_PROPERTY: {"rich_text": [{"plain_text": essay_text}]},
        },
    }


class TestFetchEssayQuestionRows:
    def test_skips_pages_with_empty_essay_text(self):
        pages = [_essay_page("p1", "회사A", "백엔드", "")]
        mock_client = _mock_client_for_essay_rows(pages)

        rows = fetch_essay_question_rows(client=mock_client, db_id="fake-db-id")

        assert rows == []

    def test_returns_row_with_pending_questions_computed(self):
        pages = [_essay_page("p1", "회사A", "백엔드", "1. 협업 경험을 서술하시오.")]
        mock_client = _mock_client_for_essay_rows(pages)

        rows = fetch_essay_question_rows(client=mock_client, db_id="fake-db-id")

        assert len(rows) == 1
        assert rows[0]["page_id"] == "p1"
        assert rows[0]["company"] == "회사A"
        assert rows[0]["position"] == "백엔드"
        assert rows[0]["pending_questions"] == ["1. 협업 경험을 서술하시오."]

    def test_row_with_no_pending_questions_has_empty_list(self):
        essay_text = "1. 협업 경험을 서술하시오.\n→ 키워드 후보: Clean Eye"
        pages = [_essay_page("p1", "회사A", "백엔드", essay_text)]
        mock_client = _mock_client_for_essay_rows(pages)

        rows = fetch_essay_question_rows(client=mock_client, db_id="fake-db-id")

        assert rows[0]["pending_questions"] == []


class TestUpdateEssayQuestions:
    def test_updates_only_the_essay_questions_property(self):
        mock_client = MagicMock()

        update_essay_questions("some-page-id", "새 텍스트", client=mock_client)

        mock_client.pages.update.assert_called_once()
        _, kwargs = mock_client.pages.update.call_args
        assert kwargs["page_id"] == "some-page-id"
        assert list(kwargs["properties"].keys()) == [ESSAY_QUESTIONS_PROPERTY]
        assert kwargs["properties"][ESSAY_QUESTIONS_PROPERTY] == {
            "rich_text": [{"text": {"content": "새 텍스트"}}]
        }
