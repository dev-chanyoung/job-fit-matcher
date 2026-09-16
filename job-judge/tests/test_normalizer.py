"""Tests for normalizer.normalize() — no real network/API calls (Anthropic client is mocked)."""

import json
from unittest.mock import MagicMock

import normalizer


def _fake_client(response_text: str) -> MagicMock:
    client = MagicMock()
    fake_content_block = MagicMock()
    fake_content_block.text = response_text
    fake_response = MagicMock()
    fake_response.content = [fake_content_block]
    client.messages.create.return_value = fake_response
    return client


def test_normalize_builds_job_posting_from_valid_json():
    payload = {
        "company": "테스트회사",
        "position": "백엔드 엔지니어",
        "employment_type": "경력",
        "required_years": "3년 이상",
        "education_requirement": "학사 이상",
        "location": "서울",
        "must_have": ["Python", "SQL"],
        "nice_to_have": ["Kubernetes"],
        "tech_stack": ["Python", "FastAPI", "PostgreSQL"],
        "responsibilities": ["백엔드 API 개발"],
        "deadline": "2026-10-01",
        "missing_fields": [],
    }
    mock_client = _fake_client(json.dumps(payload, ensure_ascii=False))

    result = normalizer.normalize(
        "some jd text", source_url="https://x.com/job/1", client=mock_client
    )

    assert result.company == "테스트회사"
    assert result.position == "백엔드 엔지니어"
    assert result.employment_type == "경력"
    assert result.required_years == "3년 이상"
    assert result.tech_stack == ["Python", "FastAPI", "PostgreSQL"]
    assert result.must_have == ["Python", "SQL"]
    assert result.source_url == "https://x.com/job/1"
    assert isinstance(result.fetched_at, str) and len(result.fetched_at) > 0

    mock_client.messages.create.assert_called_once()


def test_normalize_defaults_missing_optional_fields():
    payload = {
        "company": "회사B",
        "position": "프론트엔드 엔지니어",
        "missing_fields": ["tech_stack", "must_have"],
    }
    mock_client = _fake_client(json.dumps(payload, ensure_ascii=False))

    result = normalizer.normalize("some jd text", client=mock_client)

    assert result.missing_fields == ["tech_stack", "must_have"]
    assert result.tech_stack == []
    assert result.must_have == []
    assert result.nice_to_have == []

    mock_client.messages.create.assert_called_once()


def test_normalize_strips_markdown_code_fence():
    payload = {
        "company": "회사C",
        "position": "데이터 엔지니어",
    }
    fenced_text = "```json\n" + json.dumps(payload, ensure_ascii=False) + "\n```"
    mock_client = _fake_client(fenced_text)

    result = normalizer.normalize("some jd text", client=mock_client)

    assert result.company == "회사C"
    assert result.position == "데이터 엔지니어"

    mock_client.messages.create.assert_called_once()
