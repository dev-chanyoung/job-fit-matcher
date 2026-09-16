"""Unit tests for schemas.py (Pydantic v2 models)."""

import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from schemas import Evaluation, Evidence, JobPosting  # noqa: E402


def _valid_job_kwargs(**overrides):
    kwargs = {
        "company": "테스트회사",
        "position": "백엔드 개발자",
        "fetched_at": "2026-09-16T00:00:00",
    }
    kwargs.update(overrides)
    return kwargs


def _valid_evidence_kwargs(**overrides):
    kwargs = {
        "jd_requirement": "Spring Boot 3년 이상",
        "profile_basis": "Spring Boot 프로젝트 3회",
        "match_level": "강함",
    }
    kwargs.update(overrides)
    return kwargs


def _valid_evaluation_kwargs(**overrides):
    kwargs = {
        "verdict": "지원 고려",
        "scores": {"필수요건_충족": 20},
        "evidence": [Evidence(**_valid_evidence_kwargs())],
        "gaps": [],
        "cover_letter_topics": [],
        "risks": [],
        "evidence_quality": "일부 부족",
    }
    kwargs.update(overrides)
    return kwargs


class TestJobPosting:
    def test_missing_required_field_raises(self):
        kwargs = _valid_job_kwargs()
        del kwargs["company"]
        with pytest.raises(ValidationError):
            JobPosting(**kwargs)

    def test_list_fields_default_to_empty_list(self):
        job = JobPosting(**_valid_job_kwargs())
        assert job.must_have == []
        assert job.nice_to_have == []
        assert job.tech_stack == []
        assert job.responsibilities == []
        assert job.missing_fields == []

    def test_list_field_defaults_are_independent_instances(self):
        job1 = JobPosting(**_valid_job_kwargs())
        job2 = JobPosting(**_valid_job_kwargs())
        job1.must_have.append("Java")
        assert job2.must_have == []


class TestEvidence:
    def test_invalid_match_level_raises(self):
        kwargs = _valid_evidence_kwargs(match_level="완벽")
        with pytest.raises(ValidationError):
            Evidence(**kwargs)


class TestEvaluation:
    def test_missing_required_field_raises(self):
        kwargs = _valid_evaluation_kwargs()
        del kwargs["verdict"]
        with pytest.raises(ValidationError):
            Evaluation(**kwargs)

    def test_list_fields_default_to_empty_list(self):
        kwargs = _valid_evaluation_kwargs()
        del kwargs["evidence"]
        del kwargs["gaps"]
        del kwargs["cover_letter_topics"]
        del kwargs["risks"]
        evaluation = Evaluation(**kwargs)
        assert evaluation.evidence == []
        assert evaluation.gaps == []
        assert evaluation.cover_letter_topics == []
        assert evaluation.risks == []

    def test_invalid_verdict_raises(self):
        kwargs = _valid_evaluation_kwargs(verdict="불합격")
        with pytest.raises(ValidationError):
            Evaluation(**kwargs)

    def test_invalid_evidence_quality_raises(self):
        kwargs = _valid_evaluation_kwargs(evidence_quality="완벽함")
        with pytest.raises(ValidationError):
            Evaluation(**kwargs)
