"""Unit tests for judge.py CLI (see docs blueprint section 7).

All dependency modules (extractor/normalizer/hard_filter/evaluator/notion_writer)
are monkeypatched at the module-attribute level, so no real network/LLM/Notion
calls happen here.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from typer.testing import CliRunner  # noqa: E402

import judge  # noqa: E402
from schemas import Evaluation, Evidence, JobPosting  # noqa: E402

runner = CliRunner()


def _fake_job(**overrides) -> JobPosting:
    kwargs = {
        "company": "테스트회사",
        "position": "백엔드 개발자",
        "fetched_at": "2026-09-16T00:00:00",
    }
    kwargs.update(overrides)
    return JobPosting(**kwargs)


def _fake_evaluation(**overrides) -> Evaluation:
    kwargs = {
        "verdict": "지원 고려",
        "scores": {
            "필수요건_충족": 20,
            "기술스택_일치": 15,
            "업무내용_일치": 10,
            "우대사항": 5,
            "도메인_연관성": 5,
        },
        "evidence": [
            Evidence(
                jd_requirement="Spring Boot 경험",
                profile_basis="프로젝트 A",
                match_level="강함",
            )
        ],
        "gaps": ["Kafka 운영 경험 없음"],
        "cover_letter_topics": ["실시간 처리 프로젝트"],
        "risks": [],
        "evidence_quality": "근거 충분",
    }
    kwargs.update(overrides)
    return Evaluation(**kwargs)


def test_extraction_failure_url(monkeypatch):
    """(a) 본문 추출 실패: URL input, extractor.fetch returns None."""
    calls = {"fetch": 0, "normalize": 0}

    def fake_fetch(url):
        calls["fetch"] += 1
        return None

    def fake_normalize(*args, **kwargs):
        calls["normalize"] += 1
        raise AssertionError("normalizer.normalize should not be called")

    monkeypatch.setattr(judge.extractor, "fetch", fake_fetch)
    monkeypatch.setattr(judge.normalizer, "normalize", fake_normalize)

    result = runner.invoke(judge.app, ["http://example.com/job/123"])

    assert result.exit_code == 1
    assert calls["fetch"] == 1
    assert calls["normalize"] == 0
    assert "본문 추출 실패" in result.output


def test_hard_filter_rejection(monkeypatch):
    """(b) 하드필터 탈락: plain JD text input."""
    fake_job = _fake_job()
    evaluate_calls = []
    save_calls = []

    monkeypatch.setattr(judge.normalizer, "normalize", lambda *a, **k: fake_job)
    monkeypatch.setattr(
        judge.hard_filter, "hard_filter", lambda job: (False, ["마감 지남"])
    )
    monkeypatch.setattr(
        judge.evaluator,
        "evaluate",
        lambda *a, **k: evaluate_calls.append((a, k)),
    )
    monkeypatch.setattr(
        judge.notion_writer,
        "save",
        lambda *a, **k: save_calls.append((a, k)),
    )

    result = runner.invoke(judge.app, ["백엔드 개발자 채용 공고 텍스트입니다"])

    assert result.exit_code == 0
    assert len(evaluate_calls) == 0
    assert len(save_calls) == 1
    args, kwargs = save_calls[0]
    all_args = list(args) + list(kwargs.values())
    assert fake_job in all_args
    assert kwargs.get("evaluation") is None or (
        len(args) >= 2 and args[1] is None
    )
    assert kwargs.get("filtered_reason") == ["마감 지남"] or (
        len(args) >= 3 and args[2] == ["마감 지남"]
    )
    assert "필터 탈락" in result.output


def test_normal_pass(monkeypatch):
    """(c) 정상 통과: hard filter passes, evaluation runs, save called with evaluation."""
    fake_job = _fake_job()
    fake_evaluation = _fake_evaluation()
    evaluate_calls = []
    save_calls = []

    monkeypatch.setattr(judge.normalizer, "normalize", lambda *a, **k: fake_job)
    monkeypatch.setattr(judge.hard_filter, "hard_filter", lambda job: (True, []))

    def fake_evaluate(*args, **kwargs):
        evaluate_calls.append((args, kwargs))
        return fake_evaluation

    def fake_save(*args, **kwargs):
        save_calls.append((args, kwargs))

    monkeypatch.setattr(judge.evaluator, "evaluate", fake_evaluate)
    monkeypatch.setattr(judge.notion_writer, "save", fake_save)

    # Avoid depending on real profile.md content.
    monkeypatch.setattr(judge, "PROFILE_PATH", _FakePath("fake profile content"))

    result = runner.invoke(judge.app, ["백엔드 개발자 채용 공고 텍스트입니다"])

    assert result.exit_code == 0
    assert len(evaluate_calls) == 1
    assert len(save_calls) == 1
    args, kwargs = save_calls[0]
    all_args = list(args) + list(kwargs.values())
    assert fake_evaluation in all_args
    assert fake_evaluation.verdict in result.output


class _FakePath:
    """Minimal stand-in for Path with a read_text() method, for monkeypatching
    judge.PROFILE_PATH without touching the real profile.md file."""

    def __init__(self, content: str):
        self._content = content

    def read_text(self, encoding: str | None = None) -> str:
        return self._content
