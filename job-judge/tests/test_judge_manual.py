"""Unit tests for judge_manual.py (Claude-Code-session workflow, no ANTHROPIC_API_KEY).

hard_filter.py runs for real (pure code, no mocking needed). Only
notion_writer.save is monkeypatched, so no real Notion calls happen here.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from typer.testing import CliRunner  # noqa: E402

import judge_manual  # noqa: E402

runner = CliRunner()

_VALID_JOB = {
    "company": "테스트회사",
    "position": "백엔드 개발자",
    "required_years": "신입~2년",
    "deadline": "2099-12-31",
}

_REJECTED_JOB = {
    "company": "테스트회사",
    "position": "백엔드 개발자",
    "required_years": "경력 3년 이상",
}

_VALID_EVALUATION = {
    "verdict": "지원 고려",
    "scores": {
        "필수요건_충족": 20,
        "기술스택_일치": 15,
        "업무내용_일치": 10,
        "우대사항": 5,
        "도메인_연관성": 5,
    },
    "evidence": [
        {
            "jd_requirement": "Spring Boot 경험",
            "profile_basis": "프로젝트 A",
            "match_level": "강함",
        }
    ],
    "gaps": ["Kafka 운영 경험 없음"],
    "cover_letter_topics": ["실시간 처리 프로젝트"],
    "risks": [],
    "evidence_quality": "근거 충분",
}


def _write_json(tmp_path: Path, name: str, data: dict) -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


def test_hard_filter_rejection_saves_and_exits(tmp_path, monkeypatch):
    job_path = _write_json(tmp_path, "job.json", _REJECTED_JOB)
    save_calls = []
    monkeypatch.setattr(
        judge_manual.notion_writer, "save", lambda *a, **k: save_calls.append((a, k))
    )

    result = runner.invoke(judge_manual.app, [str(job_path)])

    assert result.exit_code == 0
    assert "필터 탈락" in result.output
    assert len(save_calls) == 1
    _, kwargs = save_calls[0]
    assert kwargs.get("evaluation") is None
    assert kwargs.get("filtered_reason") == ["경력 3년 이상 요구 (신입 지원 경로 없음)"]


def test_pass_without_evaluation_does_not_save(tmp_path, monkeypatch):
    job_path = _write_json(tmp_path, "job.json", _VALID_JOB)
    save_calls = []
    monkeypatch.setattr(
        judge_manual.notion_writer, "save", lambda *a, **k: save_calls.append((a, k))
    )

    result = runner.invoke(judge_manual.app, [str(job_path)])

    assert result.exit_code == 0
    assert "PASSED" in result.output
    assert len(save_calls) == 0


def test_pass_with_evaluation_saves_full_result(tmp_path, monkeypatch):
    job_path = _write_json(tmp_path, "job.json", _VALID_JOB)
    eval_path = _write_json(tmp_path, "evaluation.json", _VALID_EVALUATION)
    save_calls = []
    monkeypatch.setattr(
        judge_manual.notion_writer, "save", lambda *a, **k: save_calls.append((a, k))
    )

    result = runner.invoke(
        judge_manual.app, [str(job_path), "--evaluation", str(eval_path)]
    )

    assert result.exit_code == 0
    assert _VALID_EVALUATION["verdict"] in result.output
    assert len(save_calls) == 1
    _, kwargs = save_calls[0]
    assert kwargs.get("evaluation") is not None
    assert kwargs.get("evaluation").verdict == _VALID_EVALUATION["verdict"]
    assert kwargs.get("version") == "v1.4"


def test_rejected_job_ignores_provided_evaluation(tmp_path, monkeypatch):
    """Hard filter is always re-applied server-side; a caller mistake (passing
    --evaluation for a job that actually fails the filter) must not bypass
    the filter."""
    job_path = _write_json(tmp_path, "job.json", _REJECTED_JOB)
    eval_path = _write_json(tmp_path, "evaluation.json", _VALID_EVALUATION)
    save_calls = []
    monkeypatch.setattr(
        judge_manual.notion_writer, "save", lambda *a, **k: save_calls.append((a, k))
    )

    result = runner.invoke(
        judge_manual.app, [str(job_path), "--evaluation", str(eval_path)]
    )

    assert result.exit_code == 0
    assert "필터 탈락" in result.output
    assert len(save_calls) == 1
    _, kwargs = save_calls[0]
    assert kwargs.get("evaluation") is None
