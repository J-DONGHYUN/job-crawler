"""Notion 공식 API로 공고를 적재한다.

원칙 두 가지:
  1) 이미 있는 공고(공고키 기준)는 새로 만들지 않는다.
  2) '지원상태'는 사람이 관리하는 칸이다. 크롤러는 생성할 때 말고는 절대 건드리지 않는다.
"""
from __future__ import annotations

import datetime as dt
import logging
import os
import re

import requests

from .models import JobPosting

log = logging.getLogger(__name__)

API = "https://api.notion.com/v1"
VERSION = "2022-06-28"

TODAY = dt.date.today().isoformat()

SCHEMA = {
    "공고제목": {"title": {}},
    "회사명": {"rich_text": {}},
    "출처": {"select": {"options": [{"name": "사람인"}, {"name": "원티드"}]}},
    "구분": {
        "select": {
            "options": [
                {"name": "신입"}, {"name": "1~3년차"}, {"name": "신입 · 1~3년차"},
            ]
        }
    },
    "적합도": {"number": {"format": "number"}},
    "경력": {"rich_text": {}},
    "지역": {"rich_text": {}},
    "기술스택": {"multi_select": {}},
    "고용형태": {"select": {}},
    "연봉": {"rich_text": {}},
    "마감일": {"date": {}},
    "등록일": {"date": {}},
    "수집일": {"date": {}},
    "링크": {"url": {}},
    "공고상태": {"select": {"options": [{"name": "모집중"}, {"name": "마감"}]}},
    "지원상태": {
        "select": {
            "options": [
                {"name": "미확인"}, {"name": "관심"}, {"name": "지원함"},
                {"name": "서류탈락"}, {"name": "면접"}, {"name": "최종합격"},
            ]
        }
    },
    "요약": {"rich_text": {}},
    "공고키": {"rich_text": {}},
}


def _headers() -> dict:
    token = os.environ.get("NOTION_TOKEN", "").strip()
    if not token:
        raise SystemExit("NOTION_TOKEN 이 비어 있습니다.")
    return {
        "Authorization": f"Bearer {token}",
        "Notion-Version": VERSION,
        "Content-Type": "application/json",
    }


def _post(path: str, body: dict) -> dict:
    r = requests.post(f"{API}{path}", headers=_headers(), json=body, timeout=30)
    if r.status_code >= 400:
        raise RuntimeError(f"Notion API {r.status_code}: {r.text[:500]}")
    return r.json()


def _patch(path: str, body: dict) -> dict:
    r = requests.patch(f"{API}{path}", headers=_headers(), json=body, timeout=30)
    if r.status_code >= 400:
        raise RuntimeError(f"Notion API {r.status_code}: {r.text[:500]}")
    return r.json()


def create_database(parent_page_id: str, title: str = "채용공고 트래커") -> str:
    """상위 페이지 아래에 DB를 새로 만들고 database_id를 돌려준다."""
    res = _post(
        "/databases",
        {
            "parent": {"type": "page_id", "page_id": parent_page_id},
            "title": [{"type": "text", "text": {"content": title}}],
            "properties": SCHEMA,
        },
    )
    return res["id"]


def existing_keys(database_id: str) -> set[str]:
    """DB에 이미 들어있는 공고키를 전부 모은다."""
    keys: set[str] = set()
    cursor = None
    while True:
        body = {"page_size": 100}
        if cursor:
            body["start_cursor"] = cursor
        res = _post(f"/databases/{database_id}/query", body)
        for page in res.get("results", []):
            prop = (page.get("properties") or {}).get("공고키") or {}
            for t in prop.get("rich_text") or []:
                keys.add(t.get("plain_text", ""))
        if not res.get("has_more"):
            break
        cursor = res.get("next_cursor")
    return keys - {""}


def _rt(text: str) -> list:
    return [{"type": "text", "text": {"content": (text or "")[:2000]}}]


def _multi(values: list[str]) -> list:
    """Notion multi_select는 쉼표를 허용하지 않는다."""
    out, seen = [], set()
    for v in values:
        name = re.sub(r"[,\n]", " ", (v or "")).strip()[:100]
        if name and name not in seen:
            seen.add(name)
            out.append({"name": name})
    return out[:20]


def _career_label(job: JobPosting) -> str:
    if job.is_newbie and not job.career_min:
        return "신입"
    lo = job.career_min if job.career_min is not None else 0
    hi = job.career_max
    if hi is None or hi >= 99:
        return f"{lo}년 이상"
    return f"{lo}~{hi}년"


def _properties(job: JobPosting) -> dict:
    props = {
        "공고제목": {"title": [{"type": "text", "text": {"content": job.title[:200] or "(제목 없음)"}}]},
        "회사명": {"rich_text": _rt(job.company)},
        "출처": {"select": {"name": job.source}},
        "구분": {"select": {"name": job.track_label}},
        "적합도": {"number": job.score},
        "경력": {"rich_text": _rt(_career_label(job))},
        "지역": {"rich_text": _rt(" ".join(filter(None, [job.location, job.district])))},
        "기술스택": {"multi_select": _multi(job.matched or job.skills)},
        "연봉": {"rich_text": _rt(job.salary)},
        "수집일": {"date": {"start": TODAY}},
        "링크": {"url": job.url or None},
        "공고상태": {"select": {"name": "모집중"}},
        "지원상태": {"select": {"name": "미확인"}},
        "요약": {"rich_text": _rt(job.summary)},
        "공고키": {"rich_text": _rt(job.key)},
    }
    if job.employment_type:
        props["고용형태"] = {"select": {"name": job.employment_type[:100]}}
    if job.deadline:
        props["마감일"] = {"date": {"start": job.deadline}}
    if job.posted_at:
        props["등록일"] = {"date": {"start": job.posted_at}}
    return props


def push(database_id: str, jobs: list[JobPosting]) -> tuple[int, int]:
    """신규 공고만 추가한다. (추가된 수, 건너뛴 수)"""
    known = existing_keys(database_id)
    added = skipped = 0

    for job in jobs:
        if job.key in known:
            skipped += 1
            continue
        try:
            _post(
                "/pages",
                {"parent": {"database_id": database_id}, "properties": _properties(job)},
            )
            added += 1
        except Exception as e:
            log.error("적재 실패 [%s] %s — %s", job.source, job.title[:40], e)

    return added, skipped


def mark_expired(database_id: str) -> int:
    """마감일이 지난 행의 '공고상태'만 '마감'으로 바꾼다. 지원상태는 손대지 않는다."""
    res = _post(
        f"/databases/{database_id}/query",
        {
            "filter": {
                "and": [
                    {"property": "마감일", "date": {"before": TODAY}},
                    {"property": "공고상태", "select": {"equals": "모집중"}},
                ]
            },
            "page_size": 100,
        },
    )
    n = 0
    for page in res.get("results", []):
        _patch(f"/pages/{page['id']}", {"properties": {"공고상태": {"select": {"name": "마감"}}}})
        n += 1
    return n
