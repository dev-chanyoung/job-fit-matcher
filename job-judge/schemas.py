"""Pydantic v2 data models for job-judge (see docs blueprint section 3)."""

from typing import Literal, Optional

from pydantic import BaseModel, Field


class JobPosting(BaseModel):
    company: str
    position: str
    source_url: Optional[str] = None
    fetched_at: str  # ISO timestamp
    employment_type: Optional[str] = None  # 신입/경력/인턴 등
    required_years: Optional[str] = None
    education_requirement: Optional[str] = None
    location: Optional[str] = None
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
    scores: dict[str, int]  # 필수요건_충족(0-30), 기술스택_일치(0-25),
    # 업무내용_일치(0-20), 우대사항(0-15), 도메인_연관성(0-10)
    evidence: list[Evidence] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    cover_letter_topics: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    evidence_quality: Literal["근거 충분", "일부 부족", "자료 부족"]
