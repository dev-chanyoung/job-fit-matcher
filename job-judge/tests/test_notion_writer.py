"""Unit tests for notion_writer.py.

All Notion client interaction is mocked via unittest.mock.MagicMock -- no
real Notion API calls are made and NOTION_API_KEY is not required.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from notion_writer import (  # noqa: E402
    classify_years_requirement,
    format_result_analysis,
    match_tech_stack,
    save,
)
from schemas import Evaluation, JobPosting  # noqa: E402

PROTECTED_KEYS = {"지원상태", "우선순위", "지원동기메모"}


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
    def test_creates_page_without_protected_fields(self):
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
        assert PROTECTED_KEYS.isdisjoint(properties.keys())


class TestSaveExistingRow:
    def test_updates_existing_page_without_protected_fields(self):
        mock_client = _mock_client_with_data_source([{"id": "existing-page-id"}])

        job = _valid_job()
        evaluation = _valid_evaluation()

        save(job, evaluation, client=mock_client, db_id="fake-db-id")

        mock_client.pages.update.assert_called_once()
        mock_client.pages.create.assert_not_called()

        _, kwargs = mock_client.pages.update.call_args
        assert kwargs["page_id"] == "existing-page-id"
        properties = kwargs["properties"]
        assert PROTECTED_KEYS.isdisjoint(properties.keys())


class TestSaveHardFiltered:
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
        assert PROTECTED_KEYS.isdisjoint(properties.keys())
        assert "마감 지남" in properties["결과분석"]["rich_text"][0]["text"]["content"]


class TestResolveDataSourceId:
    def test_raises_when_no_data_sources(self):
        import pytest

        from notion_writer import _resolve_data_source_id

        mock_client = MagicMock()
        mock_client.databases.retrieve.return_value = {"data_sources": []}

        with pytest.raises(RuntimeError):
            _resolve_data_source_id(mock_client, "some-db-id")
