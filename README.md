# 채용공고 자동 수집기

**Java/Spring 백엔드** 공고를 **원티드·사람인**에서 모아
**신입 / 1~3년차** 두 트랙으로 나누고, 중복을 거른 뒤
적합도 순으로 **Notion 데이터베이스**에 쌓습니다.
매일 오전 8시(KST) GitHub Actions가 자동 실행합니다.

## 지금 상태

| 항목 | 상태 |
|---|---|
| 원티드 수집 | ✅ 동작 확인 (200건 수집 → 54건 통과) |
| 필터·점수 | ✅ 동작 확인 (Java/Spring 30점, JS 프론트 0점) |
| 경력 트랙 분류 | ✅ 동작 확인 (1~3년차 54건, 신입 8건) |
| 사람인 수집 | ⏸ API 키 대기 중 — 키만 넣으면 바로 동작 |
| 노션 적재 | ⏸ 토큰·DB ID 대기 중 |
| GitHub Actions | ⏸ 저장소 푸시 + Secrets 등록 필요 |

잡코리아는 공개 API가 없고 약관상 자동수집이 금지되어 제외했습니다.

## 셋업 (3단계)

### 1. 사람인 API 키
[oapi.saramin.co.kr](https://oapi.saramin.co.kr) 가입 → 무료 키 발급 → `.env`의 `SARAMIN_ACCESS_KEY`에 입력.

발급 폼의 **"사용할 곳 URL"** 에는 이 프로젝트의 GitHub 저장소 주소를 적으면 됩니다.
개인 구직용이라 서비스 도메인이 없어도 됩니다. (`localhost`는 반려될 수 있으니 피하세요.)
서비스명은 "개인 구직용 채용공고 수집기" 정도로 적으면 충분합니다.

### 2. Notion 연결
1. [notion.so/my-integrations](https://www.notion.so/my-integrations) 에서 내부 통합 생성 → `ntn_`으로 시작하는 토큰 복사 → `.env`의 `NOTION_TOKEN`
2. 공고 DB를 넣을 노션 페이지를 열고 `···` → **연결 추가**에서 방금 만든 통합을 연결
3. 그 페이지 URL 끝의 32자리 ID를 복사해서 아래 실행:
   ```bash
   ./.venv/bin/python -m src.main --init-db <페이지ID>
   ```
   출력된 database_id를 `.env`의 `NOTION_DATABASE_ID`에 입력.

### 3. GitHub Actions
저장소에 푸시한 뒤 **Settings → Secrets and variables → Actions**에서
`SARAMIN_ACCESS_KEY`, `NOTION_TOKEN`, `NOTION_DATABASE_ID` 세 개를 등록하면 끝입니다.

## 사용법

```bash
# 최초 1회
python3 -m venv .venv && ./.venv/bin/pip install -r requirements.txt
cp .env.example .env     # 값 채우기

# 노션 없이 결과만 확인 (키 없어도 동작)
./.venv/bin/python -m src.main --dry-run

# 필터/점수만 튜닝 — 재크롤링 없이 즉시 (권장)
./.venv/bin/python -m src.main --dry-run --from-cache

# 실제 노션 적재
./.venv/bin/python -m src.main
```

수집 조건은 **`config.yaml`만** 고치면 됩니다. 코드는 건드릴 필요 없습니다.
제외 키워드를 손본 뒤 `--from-cache`로 결과를 바로 확인하는 흐름을 추천합니다.

### 경력 트랙

`config.yaml`의 `경력.트랙`에서 신입과 1~3년차를 각각 켜고 끌 수 있습니다.
한쪽만 집중해서 보고 싶을 때 `사용: false`로 바꾸세요.

```yaml
경력:
  트랙:
    신입:     { 사용: true, 최소_연차: 0, 최대_연차: 0 }
    1~3년차:  { 사용: true, 최소_연차: 1, 최대_연차: 3 }
```

### 기술스택 점수

`Java 6점 · Spring 5점 · Spring Boot 5점 · Spring Data JPA 4점 ·
Docker 3점 · AWS 3점 · Grafana 2점 · Jira 1점 · Slack 1점`

영문 별칭은 **단어 단위로** 매칭합니다 — `java`가 `javascript`에 걸리지 않습니다.
별칭 덕분에 공고가 `스프링부트`라고 쓰든 `Spring Boot`라고 쓰든 똑같이 잡힙니다.

## 노션 DB 구조

`공고제목 · 회사명 · 출처 · 구분 · 적합도 · 경력 · 지역 · 기술스택 · 고용형태 · 연봉 ·
마감일 · 등록일 · 수집일 · 링크 · 공고상태 · 지원상태 · 요약 · 공고키`

- **구분**은 `신입` / `1~3년차` / `신입 · 1~3년차` 중 하나입니다.
  노션에서 이 칼럼으로 보드 뷰를 만들면 트랙별로 나눠 볼 수 있습니다.
  두 조건을 모두 만족하는 공고는 `신입 · 1~3년차`로 표시됩니다.
- **공고키** (`출처:공고ID`)로 중복을 막습니다. 같은 공고는 몇 번을 돌려도 한 줄입니다.
- **지원상태**(미확인/관심/지원함/서류탈락/면접/최종합격)는 직접 관리하는 칸입니다.
  크롤러는 행을 처음 만들 때 '미확인'을 넣고, 그 뒤로는 **절대 덮어쓰지 않습니다.**
- 마감일이 지나면 **공고상태**만 '마감'으로 바뀝니다.

## 구조

```
config.yaml              수집 조건 (여기만 고치면 됨)
src/crawlers/wanted.py   원티드 — 내부 JSON API
src/crawlers/saramin.py  사람인 — 공식 오픈 API
src/filters.py           경력·지역·제외어 필터 + 적합도 점수
src/notion_sync.py       노션 적재 (중복 방지, 마감 처리)
src/main.py              실행 진입점
state/raw_cache.json     직전 수집 원본 (--from-cache 용, git 미추적)
```

## 알아둘 점

- **원티드는 공식 API가 아닙니다.** 사이트 개편 시 깨질 수 있습니다.
  그때는 `src/crawlers/wanted.py`의 엔드포인트만 고치면 됩니다.
  한 사이트가 실패해도 나머지는 계속 수집합니다.
- 서버 부담을 주지 않도록 요청 간 0.4초 간격을 둡니다. 이 값을 줄이지 마세요.
- 개인 구직 용도로만 쓰세요. 수집한 데이터를 재배포하면 각 사이트 약관 위반입니다.
