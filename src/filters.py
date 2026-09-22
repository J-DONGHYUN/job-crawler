"""수집한 공고를 거르고, 경력 트랙을 붙이고, 적합도 점수를 매긴다."""
from __future__ import annotations

import re

from .models import JobPosting

REMOTE_PAT = re.compile(r"재택|원격|리모트|remote|하이브리드", re.I)

# 영문 별칭은 단어 단위로 매칭한다.
# 이게 없으면 "java" 가 "javascript" 에, "spring" 이 아무 데나 걸린다.
_ASCII = re.compile(r"^[\x00-\x7f]+$")
_cache: dict[str, re.Pattern] = {}


def _pattern(alias: str) -> re.Pattern:
    if alias not in _cache:
        esc = re.escape(alias.lower())
        if _ASCII.match(alias):
            esc = rf"(?<![a-z0-9+#]){esc}(?![a-z0-9+#])"
        _cache[alias] = re.compile(esc, re.I)
    return _cache[alias]


def _haystack(job: JobPosting) -> str:
    return " ".join(
        [job.title, " ".join(job.skills), job.summary, job.match_text, job.employment_type]
    ).lower()


def career_tracks(job: JobPosting, cfg: dict) -> list[str]:
    """공고가 어느 트랙(신입 / 1~3년차)에 해당하는지. 빈 리스트면 대상 아님."""
    c = cfg["경력"]
    lo = job.career_min if job.career_min is not None else 0
    hi = job.career_max if job.career_max is not None else 99
    # 원티드는 상한을 100으로 넣는 경우가 많다 — 무제한으로 본다.
    hi = min(hi, 99)

    tracks: list[str] = []
    for name, t in c["트랙"].items():
        if not t.get("사용", True):
            continue
        name = str(name)
        # 연차 구간이 겹치면 해당 트랙
        if lo <= t["최대_연차"] and hi >= t["최소_연차"]:
            tracks.append(name)
        # 공고에 '신입 가능' 표시가 있으면 연차와 무관하게 신입 트랙
        elif t["최소_연차"] == 0 and job.is_newbie and c.get("신입_공고_항상포함"):
            tracks.append(name)
    return tracks


def location_fits(job: JobPosting, cfg: dict) -> bool:
    allowed = cfg["지역"]["허용"]
    if not allowed:
        return True
    blob = f"{job.location} {job.district}"
    if any(a in blob for a in allowed):
        return True
    # 지역이 비어 있으면 버리지 않고 통과시킨다 (사이트가 값을 안 준 경우)
    return not blob.strip()


def is_excluded(job: JobPosting, cfg: dict) -> str | None:
    """제외 키워드에 걸리면 그 단어를, 아니면 None을 돌려준다."""
    hay = _haystack(job)
    for word in cfg["키워드"].get("제외") or []:
        if str(word).lower() in hay:
            return str(word)
    return None


def _weight_and_aliases(spec) -> tuple[int, list[str]]:
    """우대_스택 항목은 {점수, 별칭} 또는 그냥 정수 둘 다 받는다."""
    if isinstance(spec, dict):
        return int(spec.get("점수", 1)), [str(a) for a in (spec.get("별칭") or [])]
    return int(spec), []


def score(job: JobPosting, cfg: dict) -> tuple[int, list[str]]:
    hay = _haystack(job)
    total = 0
    matched: list[str] = []

    for stack, spec in (cfg["키워드"].get("우대_스택") or {}).items():
        weight, aliases = _weight_and_aliases(spec)
        for alias in [str(stack), *aliases]:
            if _pattern(alias).search(hay):
                total += weight
                matched.append(str(stack))
                break  # 같은 스택은 한 번만 센다

    if job.is_newbie:
        total += 2
        matched.append("신입가능")

    if cfg["지역"].get("재택_우대") and REMOTE_PAT.search(hay):
        total += 1
        matched.append("재택/원격")

    return total, matched


def prefilter(jobs: list[JobPosting], cfg: dict) -> tuple[list[JobPosting], dict[str, int]]:
    """상세 조회 **전에** 돌리는 값싼 필터.

    목록 응답만으로 판단할 수 있는 경력·지역·제목 제외어를 먼저 걸러
    상세 조회 횟수를 줄인다. 본문이 필요한 판단은 apply()가 맡는다.
    """
    kept: list[JobPosting] = []
    dropped = {"경력불일치": 0, "지역불일치": 0, "제외키워드": 0}

    for job in jobs:
        tracks = career_tracks(job, cfg)
        if not tracks:
            dropped["경력불일치"] += 1
            continue
        if not location_fits(job, cfg):
            dropped["지역불일치"] += 1
            continue
        if is_excluded(job, cfg):
            dropped["제외키워드"] += 1
            continue
        job.tracks = tracks
        kept.append(job)

    return kept, dropped


def apply(jobs: list[JobPosting], cfg: dict) -> tuple[list[JobPosting], dict[str, int]]:
    """필터링 + 트랙 분류 + 점수 부여. 통과한 공고와 탈락 사유 집계를 돌려준다."""
    kept: list[JobPosting] = []
    dropped = {"경력불일치": 0, "지역불일치": 0, "제외키워드": 0, "점수미달": 0}
    floor = cfg["출력"]["최소_적합도점수"]

    for job in jobs:
        tracks = career_tracks(job, cfg)
        if not tracks:
            dropped["경력불일치"] += 1
            continue
        if not location_fits(job, cfg):
            dropped["지역불일치"] += 1
            continue
        if is_excluded(job, cfg):
            dropped["제외키워드"] += 1
            continue

        job.score, job.matched = score(job, cfg)
        if job.score < floor:
            dropped["점수미달"] += 1
            continue

        job.tracks = tracks
        if not job.skills:
            job.skills = [m for m in job.matched if m not in ("신입가능", "재택/원격")]
        kept.append(job)

    # 점수 높은 순, 같으면 신입 트랙 먼저
    kept.sort(key=lambda j: (j.score, "신입" in j.tracks), reverse=True)
    return kept, dropped
