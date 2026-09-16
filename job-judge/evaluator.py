"""Normalized JD + profile.md -> Evaluation JSON via LLM call (see docs blueprint section 2)."""

import json
import os
from pathlib import Path

from dotenv import load_dotenv

from llm_utils import strip_code_fence
from schemas import Evaluation, JobPosting

PROMPT_PATH = Path(__file__).parent / "prompts" / "evaluate_prompt.txt"


def evaluate(job: JobPosting, profile_text: str, client=None) -> Evaluation:
    if client is None:
        load_dotenv()
        import anthropic

        client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

    prompt_template = PROMPT_PATH.read_text(encoding="utf-8")
    prompt = prompt_template.format(
        normalized_jd_json=job.model_dump_json(),
        profile_md_content=profile_text,
    )

    response = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )

    raw_text = response.content[0].text
    cleaned_text = strip_code_fence(raw_text)
    data = json.loads(cleaned_text)

    return Evaluation.model_validate(data)
