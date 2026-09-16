"""Unit tests for evaluator.py."""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from evaluator import evaluate  # noqa: E402
from schemas import JobPosting  # noqa: E402


def _valid_job():
    return JobPosting(
        company="테스트회사",
        position="백엔드 개발자",
        fetched_at="2026-09-16T00:00:00",
    )


def _valid_evaluation_dict(**overrides):
    data = {
        "verdict": "지원 고려",
        "scores": {
            "필수요건_충족": 25,
            "기술스택_일치": 20,
            "업무내용_일치": 15,
            "우대사항": 10,
            "도메인_연관성": 5,
        },
        "evidence": [
            {
                "jd_requirement": "Python 3년 이상",
                "profile_basis": "Python 백엔드 개발 4년 경력",
                "match_level": "강함",
            }
        ],
        "gaps": ["클라우드 경험 부족"],
        "cover_letter_topics": ["대규모 트래픽 처리 경험"],
        "risks": ["최근 이직 빈도"],
        "evidence_quality": "근거 충분",
    }
    data.update(overrides)
    return data


def _mock_client_with_text(text: str) -> MagicMock:
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_content_block = MagicMock()
    mock_content_block.text = text
    mock_response.content = [mock_content_block]
    mock_client.messages.create.return_value = mock_response
    return mock_client


class TestEvaluateSuccess:
    def test_valid_json_response_builds_evaluation(self):
        payload = _valid_evaluation_dict()
        mock_client = _mock_client_with_text(json.dumps(payload, ensure_ascii=False))

        result = evaluate(_valid_job(), "dummy profile text", client=mock_client)

        assert result.verdict == payload["verdict"]
        assert result.scores == payload["scores"]
        for value in result.scores.values():
            assert isinstance(value, int)
        assert result.evidence[0].match_level == payload["evidence"][0]["match_level"]
        mock_client.messages.create.assert_called_once()


class TestEvaluateMarkdownFence:
    def test_markdown_code_fence_is_stripped(self):
        payload = _valid_evaluation_dict()
        fenced_text = "```json\n" + json.dumps(payload, ensure_ascii=False) + "\n```"
        mock_client = _mock_client_with_text(fenced_text)

        result = evaluate(_valid_job(), "dummy profile text", client=mock_client)

        assert result.verdict == payload["verdict"]
        assert result.scores == payload["scores"]
        assert result.evidence[0].match_level == payload["evidence"][0]["match_level"]
        mock_client.messages.create.assert_called_once()


class TestEvaluateInvalidVerdict:
    def test_invalid_verdict_raises_validation_error(self):
        payload = _valid_evaluation_dict(verdict="강력 추천")
        mock_client = _mock_client_with_text(json.dumps(payload, ensure_ascii=False))

        with pytest.raises(ValidationError):
            evaluate(_valid_job(), "dummy profile text", client=mock_client)

        mock_client.messages.create.assert_called_once()
