"""JD text -> normalized JobPosting JSON via LLM call (see docs blueprint section 2)."""

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

from llm_utils import strip_code_fence
from schemas import JobPosting

PROMPT_PATH = Path(__file__).parent / "prompts" / "normalize_prompt.txt"


def normalize(text: str, source_url: str | None = None, client=None) -> JobPosting:
    if client is None:
        load_dotenv()
        import anthropic

        client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

    prompt_template = PROMPT_PATH.read_text(encoding="utf-8")
    prompt = prompt_template.format(jd_text=text)

    response = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )

    raw_text = response.content[0].text
    cleaned = strip_code_fence(raw_text)
    data = json.loads(cleaned)

    data["source_url"] = source_url
    data["fetched_at"] = datetime.now(timezone.utc).isoformat()

    return JobPosting.model_validate(data)
