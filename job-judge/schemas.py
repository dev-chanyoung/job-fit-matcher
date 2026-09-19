"""Pydantic v2 data models for job-judge (see docs blueprint section 3)."""

from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

# Evaluation.scores 항목별 배점 상한 (CLAUDE.md "4. 평가" 절과 동일한 배점).
# Evaluation은 정확히 이 5개 키만 허용하고, 각 값은 0~상한 범위여야 한다 -- 누락된
# 키, 오타 키, 범위를 벗어난 값(음수/상한 초과)은 모두 검증 실패로 거절한다.
SCORE_CAPS: dict[str, int] = {
    "필수요건_충족": 30,
    "기술스택_일치": 25,
    "업무내용_일치": 20,
    "우대사항": 15,
    "도메인_연관성": 10,
}


class JobPosting(BaseModel):
    company: str
    position: str
    source_url: Optional[str] = None
    fetched_at: str  # ISO timestamp
    employment_type: Optional[str] = None  # 신입/경력/인턴 등
    required_years: Optional[str] = None
    education_requirement: Optional[str] = None
    location: Optional[str] = None
    company_size: Optional[str] = None  # 스타트업/중견기업/대기업 (Notion 고정 옵션과 매칭 시에만 컬럼에 반영)
    domain: Optional[str] = None  # 커머스/핀테크/금융/제조/자동차/IT서비스/통신 (Notion 고정 옵션과 매칭 시에만 컬럼에 반영)
    must_have: list[str] = Field(default_factory=list)
    nice_to_have: list[str] = Field(default_factory=list)
    tech_stack: list[str] = Field(default_factory=list)
    responsibilities: list[str] = Field(default_factory=list)
    deadline: Optional[str] = None
    missing_fields: list[str] = Field(default_factory=list)  # 본문에서 못 찾은 항목


class Evidence(BaseModel):
    jd_requirement: str
    profile_basis: str
    match_level: Literal["강함", "일부", "미확인", "없음"]


class Evaluation(BaseModel):
    verdict: Literal["적극 지원", "지원 고려", "보류"]
    scores: dict[str, int]  # SCORE_CAPS의 5개 키, 각 0~해당 상한 범위 (아래 validator가 강제)
    evidence: list[Evidence] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    cover_letter_topics: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    evidence_quality: Literal["근거 충분", "일부 부족", "자료 부족"]
    # 카테고리별 점수 계산 근거를 한 줄로 남기는 선택 필드 (2026-09-19). 예:
    # "Java 100%x2, Spring 75%x2, Redis 25%x1 -> 75% -> 18.75/25 -> 19점".
    # SCORE_CAPS 키가 아닌 카테고리는 거절하지만, 항목 전체를 채울 필요는 없다
    # (요구사항이 하나뿐이라 계산이랄 게 없는 카테고리는 생략 가능).
    score_breakdown: dict[str, str] = Field(default_factory=dict)

    @field_validator("scores")
    @classmethod
    def _validate_scores(cls, v: dict[str, int]) -> dict[str, int]:
        expected = set(SCORE_CAPS)
        actual = set(v)
        if actual != expected:
            problems = []
            missing = expected - actual
            extra = actual - expected
            if missing:
                problems.append(f"누락된 키: {sorted(missing)}")
            if extra:
                problems.append(f"알 수 없는 키: {sorted(extra)}")
            raise ValueError("scores는 정확히 5개 항목이어야 합니다 -- " + ", ".join(problems))
        for key, cap in SCORE_CAPS.items():
            value = v[key]
            if not (0 <= value <= cap):
                raise ValueError(f"{key}는 0~{cap} 범위여야 합니다 (받은 값: {value})")
        return v

    @field_validator("score_breakdown")
    @classmethod
    def _validate_score_breakdown_keys(cls, v: dict[str, str]) -> dict[str, str]:
        unknown = set(v) - set(SCORE_CAPS)
        if unknown:
            raise ValueError(f"score_breakdown에 알 수 없는 키가 있습니다: {sorted(unknown)}")
        return v
