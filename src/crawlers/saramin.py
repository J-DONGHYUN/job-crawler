"""사람인 수집 — 공식 오픈 API 사용.

키 발급: https://oapi.saramin.co.kr  (무료)
문서의 지역/직무 코드가 config.yaml 값과 다르면 config만 고치면 된다.
"""
from __future__ import annotations

import logging
import os
import time

import requests

from ..models import JobPosting

log = logging.getLogger(__name__)

API = "https://oapi.saramin.co.kr/job-search"
DELAY = 0.3


def _text(node, *path, default="") -> str:
    """중첩 dict에서 안전하게 문자열을 꺼낸다."""
    cur = node
    for p in path:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(p)
    if isinstance(cur, dict):
        cur = cur.get("name")
    return str(cur) if cur not in (None, "") else default


def _to_int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def fetch(cfg: dict) -> list[JobPosting]:
    key = os.environ.get("SARAMIN_ACCESS_KEY", "").strip()
    if not key:
        log.warning("SARAMIN_ACCESS_KEY 가 없어 사람인 수집을 건너뜁니다.")
        return []

    s = cfg["사람인"]
    keywords = " ".join(cfg["키워드"]["검색어"])

    jobs: list[JobPosting] = []
    seen: set[str] = set()
    session = requests.Session()

    for page in range(s["최대_페이지"]):
        params = {
            "access-key": key,
            "keywords": keywords,
            "loc_cd": ",".join(str(c) for c in s["지역코드"]),
            "job_mid_cd": ",".join(str(c) for c in s["직무코드"]),
            "exp_max": cfg["경력"]["최대_연차"],
            "count": s["페이지당"],
            "start": page,
            "sort": "pd",  # 최신 등록순
        }
        r = session.get(API, params=params, timeout=20)
        r.raise_for_status()
        payload = r.json().get("jobs") or {}
        items = payload.get("job") or []
        if not items:
            break

        for raw in items:
            jid = str(raw.get("id", ""))
            if not jid or jid in seen:
                continue
            seen.add(jid)

            pos = raw.get("position") or {}
            exp = pos.get("experience-level") or {}
            exp_name = _text(exp, "name")

            jobs.append(
                JobPosting(
                    source="사람인",
                    source_id=jid,
                    title=_text(pos, "title"),
                    company=_text(raw, "company", "detail", "name"),
                    url=raw.get("url", ""),
                    career_min=_to_int(exp.get("min")),
                    career_max=_to_int(exp.get("max")),
                    is_newbie="신입" in exp_name or exp.get("code") in (1, "1"),
                    location=_text(pos, "location"),
                    employment_type=_text(pos, "job-type"),
                    skills=[k for k in (raw.get("keyword") or "").split(",") if k],
                    salary=_text(raw, "salary"),
                    deadline=(raw.get("expiration-date") or "")[:10] or None,
                    posted_at=(raw.get("posting-date") or "")[:10] or None,
                    summary=f"{_text(pos, 'job-code')} · 경력 {exp_name}".strip(" ·"),
                )
            )

        total = _to_int(payload.get("total")) or 0
        if (page + 1) * s["페이지당"] >= total:
            break
        time.sleep(DELAY)

    log.info("사람인 %d건 수집", len(jobs))
    return jobs
