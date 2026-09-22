"""Unit tests for mongo_reader.py.

Uses a small in-memory fake Mongo client/collection instead of pymongo or
mocks -- real enough to exercise find()/update_one() semantics without a
real MongoDB connection, and MONGODB_URI is never required.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mongo_reader import (  # noqa: E402
    CLASSIFIED_COLLECTION,
    SEEN_COLLECTION,
    fetch_candidates,
    mark_classified,
    source_from_url,
)


class _FakeCollection:
    def __init__(self, docs: dict[str, dict] | None = None):
        self.docs: dict[str, dict] = docs or {}

    def find(self, filter=None, projection=None):
        filter = filter or {}
        results = []
        for _id, doc in self.docs.items():
            if projection == {"_id": 1}:
                results.append({"_id": _id})
            else:
                results.append({"_id": _id, **doc})
        return results

    def update_one(self, filter, update, upsert=False):
        _id = filter["_id"]
        existing = self.docs.get(_id, {})
        existing.update(update["$set"])
        self.docs[_id] = existing


class _FakeDb:
    def __init__(self):
        self._collections: dict[str, _FakeCollection] = {
            SEEN_COLLECTION: _FakeCollection(),
            CLASSIFIED_COLLECTION: _FakeCollection(),
        }

    def __getitem__(self, name):
        return self._collections[name]


class _FakeClient:
    def __init__(self, db: _FakeDb):
        self._db = db

    def __getitem__(self, name):
        return self._db


def _client_with_seen(seen_docs: dict[str, dict]) -> _FakeClient:
    db = _FakeDb()
    db[SEEN_COLLECTION].docs = dict(seen_docs)
    return _FakeClient(db)


class TestSourceFromUrl:
    def test_jasoseol(self):
        assert source_from_url("https://jasoseol.com/recruit/123") == "jasoseol"

    def test_saramin(self):
        assert source_from_url("https://www.saramin.co.kr/zf_user/jobs/456") == "saramin"

    def test_unknown_host(self):
        assert source_from_url("https://example.com/job/1") == "기타"


class TestFetchCandidates:
    def test_returns_unclassified_seen_postings(self):
        client = _client_with_seen(
            {
                "https://jasoseol.com/a": {"first_seen": "2026-09-20", "company": "A사", "title": "백엔드"},
                "https://www.saramin.co.kr/b": {"first_seen": "2026-09-21", "company": "B사", "title": "서버"},
            }
        )

        candidates = fetch_candidates(client=client)

        urls = {c["url"] for c in candidates}
        assert urls == {"https://jasoseol.com/a", "https://www.saramin.co.kr/b"}
        by_url = {c["url"]: c for c in candidates}
        assert by_url["https://jasoseol.com/a"]["source"] == "jasoseol"
        assert by_url["https://jasoseol.com/a"]["company"] == "A사"

    def test_already_classified_postings_are_excluded(self):
        client = _client_with_seen(
            {
                "https://jasoseol.com/a": {"first_seen": "2026-09-20", "company": "A사", "title": "백엔드"},
                "https://jasoseol.com/b": {"first_seen": "2026-09-20", "company": "B사", "title": "서버"},
            }
        )
        mark_classified(
            url="https://jasoseol.com/a",
            company="A사",
            title="백엔드",
            source="jasoseol",
            tier="적합",
            reason="기술스택 직접 일치",
            client=client,
        )

        candidates = fetch_candidates(client=client)

        assert [c["url"] for c in candidates] == ["https://jasoseol.com/b"]


class TestMarkClassified:
    def test_rejects_invalid_tier(self):
        client = _client_with_seen({})
        with pytest.raises(ValueError):
            mark_classified(
                url="https://jasoseol.com/a",
                company="A사",
                title="백엔드",
                source="jasoseol",
                tier="모름",
                reason="",
                client=client,
            )

    def test_upsert_overwrites_prior_result_for_same_url(self):
        client = _client_with_seen({})
        mark_classified(
            url="https://jasoseol.com/a",
            company="A사",
            title="백엔드",
            source="jasoseol",
            tier="애매",
            reason="첫 판단",
            client=client,
        )
        mark_classified(
            url="https://jasoseol.com/a",
            company="A사",
            title="백엔드",
            source="jasoseol",
            tier="적합",
            reason="재판단",
            client=client,
        )

        stored = client["job_watcher"][CLASSIFIED_COLLECTION].docs["https://jasoseol.com/a"]
        assert stored["tier"] == "적합"
        assert stored["reason"] == "재판단"
