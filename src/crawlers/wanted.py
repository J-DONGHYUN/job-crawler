"""원티드 수집.

공식 공개 API가 아니라 웹사이트가 내부적으로 쓰는 JSON 엔드포인트다.
프론트 개편 시 깨질 수 있으므로, 실패하면 조용히 빈 결과 대신 예외를 던진다.
(2026-09 기준 동작 확인)
"""
from __future__ import annotations

import logging
import time

import requests

from ..models import JobPosting

log = logging.getLogger(__name__)

BASE = "https://www.wanted.co.kr"
LIST_URL = f"{BASE}/api/chaos/navigation/v1/results"
DETAIL_URL = f"{BASE}/api/chaos/jobs/v4/{{job_id}}/details"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/127.0 Safari/537.36"
    ),
    "Referer": f"{BASE}/",
    "Accept": "application/json",
}

PAGE = 100
DELAY = 0.4  # 서버 부담을 주지 않기 위한 간격


def _list_page(session, group_id, job_id, location, offset):
    params = {
        "job_group_id": group_id,
        "job_ids": job_id,
        "locations": location,
        "years": -1,
        "job_sort": "job.latest_order",
        "limit": PAGE,
        "offset": offset,
    }
    r = session.get(LIST_URL, params=params, headers=HEADERS, timeout=20)
    r.raise_for_status()
    return r.json().get("data", [])


def _detail(session, job_id: int) -> dict:
    try:
        r = session.get(DETAIL_URL.format(job_id=job_id), headers=HEADERS, timeout=20)
        r.raise_for_status()
        return r.json().get("data", {}).get("job", {})
    except Exception as e:  # 상세는 실패해도 목록 정보만으로 진행한다
        log.warning("원티드 상세 조회 실패 (id=%s): %s", job_id, e)
        return {}


def fetch(cfg: dict) -> list[JobPosting]:
    w = cfg["원티드"]
    limit = w["최대_수집건수"]
    want_detail = w.get("상세조회", True)

    seen: dict[int, dict] = {}
    session = requests.Session()

    for job_id in w["직무_카테고리"]:
        for location in w["지역코드"]:
            offset = 0
            while len(seen) < limit:
                items = _list_page(session, w["직군_그룹"], job_id, location, offset)
                if not items:
                    break
                for it in items:
                    seen.setdefault(it["id"], it)
                offset += PAGE
                time.sleep(DELAY)
                if len(items) < PAGE:
                    break

    log.info("원티드 목록 %d건 수집", len(seen))

    jobs: list[JobPosting] = []
    for raw in list(seen.values())[:limit]:
        addr = raw.get("address") or {}
        job = JobPosting(
            source="원티드",
            source_id=str(raw["id"]),
            title=raw.get("position", ""),
            company=(raw.get("company") or {}).get("name", ""),
            url=f"{BASE}/wd/{raw['id']}",
            career_min=raw.get("annual_from"),
            career_max=raw.get("annual_to"),
            is_newbie=bool(raw.get("is_newbie")),
            location=addr.get("location", ""),
            district=addr.get("district", ""),
            employment_type="정규직" if raw.get("employment_type") == "regular" else (raw.get("employment_type") or ""),
        )

        if want_detail:
            d = _detail(session, raw["id"])
            if d:
                detail = d.get("detail") or {}
                # skill_tags는 이름이 아니라 정수 ID로만 오므로 쓰지 않는다.
                # 대신 본문에서 스택을 찾는다 (filters.py가 처리).
                body = [
                    detail.get("main_tasks"),
                    detail.get("requirements"),
                    detail.get("preferred_points"),
                ]
                job.match_text = " ".join(filter(None, body))
                job.summary = job.match_text[:400]
                job.deadline = (d.get("due_time") or "")[:10] or None
            time.sleep(DELAY)

        jobs.append(job)

    return jobs
