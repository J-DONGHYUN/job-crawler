"""수집된 공고를 사이트와 무관한 하나의 형태로 통일한다."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass
class JobPosting:
    source: str                  # "사람인" | "원티드"
    source_id: str               # 사이트 내부 공고 ID
    title: str
    company: str
    url: str

    career_min: Optional[int] = None   # 요구 최소 연차
    career_max: Optional[int] = None   # 요구 최대 연차
    is_newbie: bool = False            # 신입 지원 가능 여부

    location: str = ""                 # 시/도
    district: str = ""                 # 시/군/구
    employment_type: str = ""          # 정규직 / 계약직 ...
    skills: list[str] = field(default_factory=list)
    salary: str = ""

    deadline: Optional[str] = None     # YYYY-MM-DD, 상시채용이면 None
    posted_at: Optional[str] = None    # YYYY-MM-DD
    summary: str = ""                  # 본문 발췌 — 노션에 표시되는 값 (최대 400자)
    match_text: str = ""               # 키워드 매칭 전용 원문. 노션에는 올리지 않는다.

    score: int = 0                     # 적합도 점수 (filters.py가 채움)
    tracks: list[str] = field(default_factory=list)   # 해당 경력 트랙 (신입 / 1~3년차)
    matched: list[str] = field(default_factory=list)  # 점수 근거가 된 스택

    @property
    def key(self) -> str:
        """중복 판별 키. 노션에서 이 값이 곧 행의 고유 식별자다."""
        return f"{self.source}:{self.source_id}"

    @property
    def track_label(self) -> str:
        """노션 '구분' 칼럼에 들어갈 값."""
        return " · ".join(self.tracks) if self.tracks else "미분류"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["key"] = self.key
        d["track_label"] = self.track_label
        return d
