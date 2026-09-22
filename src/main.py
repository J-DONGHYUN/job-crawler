"""채용공고 수집 → 필터링 → 노션 적재.

    python -m src.main                 # 수집 후 노션에 적재
    python -m src.main --dry-run       # 노션 없이 결과만 확인 (키 없어도 동작)
    python -m src.main --init-db PAGE_ID   # 노션 DB를 새로 생성
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from . import filters, notion_sync
from .config import load_config, load_env, require
from .crawlers import enrich_wanted, fetch_saramin, fetch_wanted
from .models import JobPosting

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s  %(levelname)-7s %(message)s", datefmt="%H:%M:%S"
)
log = logging.getLogger("job-crawler")


CACHE = Path(__file__).resolve().parent.parent / "state" / "raw_cache.json"


def collect(cfg: dict) -> list:
    jobs = []
    for name, fn in (("원티드", fetch_wanted), ("사람인", fetch_saramin)):
        try:
            got = fn(cfg)
            log.info("%s: %d건", name, len(got))
            jobs.extend(got)
        except Exception as e:
            # 한 사이트가 막혀도 나머지는 계속 간다.
            log.error("%s 수집 실패 — %s", name, e)

    # 상세 조회는 비싸다. 목록만으로 거를 수 있는 건 먼저 거르고,
    # 살아남은 공고만 본문을 가져온다.
    jobs, pre_dropped = filters.prefilter(jobs, cfg)
    log.info("사전 필터 통과 %d건 (탈락: %s)", len(jobs),
             ", ".join(f"{k} {v}" for k, v in pre_dropped.items() if v) or "없음")
    try:
        enrich_wanted(jobs, cfg)
    except Exception as e:
        log.error("원티드 상세 조회 실패 — %s", e)

    # 필터를 손볼 때 재크롤링하지 않도록 원본을 남겨둔다.
    CACHE.parent.mkdir(exist_ok=True)
    CACHE.write_text(
        json.dumps([j.to_dict() for j in jobs], ensure_ascii=False), encoding="utf-8"
    )
    return jobs


def from_cache() -> list:
    if not CACHE.exists():
        raise SystemExit("캐시가 없습니다. --from-cache 없이 한 번 실행하세요.")
    data = json.loads(CACHE.read_text(encoding="utf-8"))
    for d in data:
        d.pop("key", None)
        d.pop("track_label", None)
    return [JobPosting(**d) for d in data]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="노션에 쓰지 않고 결과만 출력")
    ap.add_argument("--init-db", metavar="PAGE_ID", help="상위 페이지 아래에 노션 DB 생성")
    ap.add_argument("--json", metavar="PATH", help="결과를 JSON 파일로도 저장")
    ap.add_argument("--from-cache", action="store_true",
                    help="직전 수집 원본을 재사용 (필터/점수 튜닝용, 네트워크 안 씀)")
    args = ap.parse_args()

    load_env()
    cfg = load_config()

    if args.init_db:
        db_id = notion_sync.create_database(args.init_db)
        print(f"\n생성 완료. .env 의 NOTION_DATABASE_ID 에 넣으세요:\n\n  {db_id}\n")
        return 0

    raw = from_cache() if args.from_cache else collect(cfg)
    if not raw:
        log.warning("수집된 공고가 없습니다.")
        return 1

    jobs, dropped = filters.apply(raw, cfg)
    by_track: dict[str, int] = {}
    for j in jobs:
        for t in j.tracks:
            by_track[t] = by_track.get(t, 0) + 1
    log.info("원본 %d건 → 통과 %d건  (탈락: %s)", len(raw), len(jobs),
             ", ".join(f"{k} {v}" for k, v in dropped.items() if v))
    log.info("트랙별: %s", ", ".join(f"{k} {v}건" for k, v in by_track.items()) or "없음")

    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump([j.to_dict() for j in jobs], f, ensure_ascii=False, indent=2)
        log.info("JSON 저장: %s", args.json)

    if args.dry_run:
        print(f"\n{'점수':>4}  {'구분':<14} {'출처':<5} {'회사':<20} 공고")
        print("─" * 100)
        for j in jobs[:40]:
            print(f"{j.score:>4}  {j.track_label:<14} {j.source:<5} "
                  f"{j.company[:18]:<20} {j.title[:40]}")
        if len(jobs) > 40:
            print(f"… 외 {len(jobs) - 40}건")
        return 0

    db_id = require("NOTION_DATABASE_ID")
    added, skipped = notion_sync.push(db_id, jobs)
    expired = notion_sync.mark_expired(db_id)
    log.info("노션 적재 완료 — 신규 %d건, 기존 %d건, 마감 처리 %d건", added, skipped, expired)
    return 0


if __name__ == "__main__":
    sys.exit(main())
