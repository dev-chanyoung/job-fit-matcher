"""Reads job-watcher's MongoDB state to find postings that haven't been
through the 1차 분류(적합/애매/부적합) workflow yet (see CLAUDE.md "세션 시작 시
자동 1차 분류" 절).

job-watcher (../job-watcher/lib/mongo.ts) owns the `job_watcher.seen_postings`
collection -- this module only ever READS it, keyed by posting URL (_id),
with {first_seen, company, title}. job-judge owns a separate
`job_judge_classified` collection in the SAME database for this feature's own
state (which postings this workflow has already classified) -- writing there
never touches job-watcher's collection, so the two projects can't step on
each other's data.
"""

import os
from datetime import datetime, timezone
from urllib.parse import urlparse

DB_NAME = "job_watcher"
SEEN_COLLECTION = "seen_postings"
CLASSIFIED_COLLECTION = "job_judge_classified"

VALID_TIERS = ("적합", "애매", "부적합")

# job-watcher's Posting.url is the real site URL for whichever source scraped
# it, so the source can be recovered from the host -- seen_postings itself
# doesn't store which site a posting came from.
_SOURCE_HOSTS = {
    "jasoseol.com": "jasoseol",
    "saramin.co.kr": "saramin",
}


def source_from_url(url: str) -> str:
    host = urlparse(url).netloc.lower()
    for suffix, source in _SOURCE_HOSTS.items():
        if host.endswith(suffix):
            return source
    return "기타"


def _get_db(client=None):
    if client is None:
        from pymongo import MongoClient

        uri = os.environ.get("MONGODB_URI")
        if not uri:
            raise RuntimeError("MONGODB_URI is not set")
        client = MongoClient(uri)
    return client[DB_NAME]


def fetch_candidates(client=None) -> list[dict]:
    """Return seen_postings entries with no job_judge_classified record yet.

    Each item: {url, company, title, source, first_seen}.
    """
    db = _get_db(client)
    classified_urls = {doc["_id"] for doc in db[CLASSIFIED_COLLECTION].find({}, {"_id": 1})}

    candidates = []
    for doc in db[SEEN_COLLECTION].find({}):
        url = doc["_id"]
        if url in classified_urls:
            continue
        candidates.append(
            {
                "url": url,
                "company": doc.get("company", ""),
                "title": doc.get("title", ""),
                "source": source_from_url(url),
                "first_seen": doc.get("first_seen"),
            }
        )
    return candidates


def mark_classified(
    url: str,
    company: str,
    title: str,
    source: str,
    tier: str,
    reason: str,
    client=None,
) -> None:
    """Record a posting's 1차 분류 result so fetch_candidates() never returns
    it again. Upserts by URL -- re-classifying the same URL just overwrites
    its prior result rather than erroring."""
    if tier not in VALID_TIERS:
        raise ValueError(f"tier는 {VALID_TIERS} 중 하나여야 합니다 (받은 값: {tier!r})")

    db = _get_db(client)
    db[CLASSIFIED_COLLECTION].update_one(
        {"_id": url},
        {
            "$set": {
                "company": company,
                "title": title,
                "source": source,
                "tier": tier,
                "reason": reason,
                "classified_at": datetime.now(timezone.utc).isoformat(),
            }
        },
        upsert=True,
    )
