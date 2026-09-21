# job-watcher

여러 채용 사이트(현재: 자소설닷컴, 사람인)의 특정 검색결과를 매일 확인해서,
지난 실행 이후 새로 올라온 공고만 Discord로 알려주는 서비스. Vercel Cron으로
매일 자동 실행되고(PC가 꺼져 있어도 동작), 상태는 MongoDB에 저장한다.

`job-judge`(로컬 Claude Code CLI 도구)와는 완전히 독립적인 별도 프로젝트다 —
이 프로젝트는 **"신규 공고 발견 + 알림"까지만** 하고, 하드필터/평가는 절대
자동으로 돌리지 않는다. Discord로 알림이 오면, 평가하고 싶은 링크를 골라서
기존처럼 Claude Code 세션(`job-judge`)에 붙여넣어야 실제 평가가 시작된다.

## 동작 방식

1. 매일 정해진 시각(기본: 오전 10시 KST, `vercel.json`의 `schedule` 참고)에
   Vercel이 `/api/check-postings`를 호출한다.
2. 등록된 각 사이트 모듈(`lib/jasoseol.ts`, `lib/saramin.ts`)이 각자의 검색
   페이지를 fetch해서 공고 목록을 파싱한다 — 둘 다 서버가 완성된 HTML/JSON을
   내려주는 구조라 JS 렌더링/헤드리스 브라우저가 필요 없고, LLM 호출도 없다
   (전부 결정론적 코드). 사이트 하나가 일시적으로 실패해도(마크업 변경 등)
   나머지 사이트로는 계속 진행한다.
3. 모든 사이트의 결과를 합쳐서, MongoDB에 저장된 "이미 본 공고" 목록과
   비교해 신규 공고만 골라낸다. 사이트별로 공고 URL이 다르므로 서로 다른
   사이트의 공고끼리 충돌하지 않지만, **같은 회사가 여러 사이트에 각각
   올린 공고는 현재 별개로 취급돼 각각 알림이 간다** (사이트 간 회사명 기준
   중복 제거는 아직 없음).
   - **최초 실행**(MongoDB에 아무 데이터도 없을 때)에는 Notion(job-judge가 쓰는
     채용 트래커 DB)에 이미 등록된 회사는 회사명 기준으로 조용히 시드(=알림
     제외)하고, Notion에 없는 회사만 진짜 신규로 취급해서 알림 + 저장한다.
4. 신규 공고가 있으면 Discord에 embed(카드형 리스트: 회사명/직무/마감일/
   클릭 가능한 🔗 링크)로 보낸다. Discord의 embed 필드(25개)·메시지당 embed
   개수(10개) 제한을 넘으면 자동으로 여러 embed/메시지로 나뉜다.
5. 이번 실행에서 본 공고들을 MongoDB에 기록해서 다음 실행 때 다시 안 뜨게 한다.

## 필요한 환경변수 (Vercel 프로젝트 설정 → Environment Variables)

| 변수 | 용도 |
|---|---|
| `MONGODB_URI` | MongoDB Atlas 연결 문자열 |
| `DISCORD_WEBHOOK_URL` | 신규 공고 알림을 보낼 Discord 웹훅. 미설정 시 알림 없이 상태만 저장 |
| `NOTION_API_KEY` | job-judge와 동일한 Notion 통합 키 (최초 실행 시드용) |
| `NOTION_DB_ID` | job-judge와 동일한 Notion DB ID |
| `CRON_SECRET` | Vercel Cron 요청 인증용 무작위 문자열. 여기 설정하면 Vercel이 요청마다 `Authorization: Bearer <값>` 헤더를 자동으로 실어 보낸다 |

로컬 테스트용으로는 `.env.example`을 복사해서 `.env`를 만들면 된다 (git에는
안 올라감). **로컬 `.env`는 로컬 테스트에만 쓰이고, 실제 배포/크론 실행에는
Vercel 프로젝트 설정에 넣은 값이 쓰인다 — 둘은 별개다.**

## 감시 대상 필터 바꾸기

각 사이트 모듈(`lib/jasoseol.ts`, `lib/saramin.ts`)의 `SEARCH_URL` 상수를
그 사이트에서 원하는 조건으로 검색한 뒤 나온 주소로 바꾸면 된다.

## 사이트 추가하기

새 사이트를 붙이려면 `lib/<site>.ts`에 `SEARCH_URL` 상수와
`fetchAllPostings(url?: string): Promise<Posting[]>`를 구현하고(각 항목을
`lib/types.ts`의 공용 `Posting` 셰이프로 정규화), `api/check-postings.ts`의
`fetchAllSources()` 안 `sources` 배열에 한 줄 추가하면 된다. 사이트마다
마크업/데이터 구조가 완전히 다르므로(자소설닷컴은 Next.js JSON, 사람인은
전통적 서버렌더링 HTML), 새 사이트를 붙이기 전에 먼저 실제 페이지를 fetch해서
구조부터 확인하는 걸 권장한다 (JS 렌더링이 필요한 SPA라면 이 방식 자체가
안 통할 수 있음 — 그 경우는 별도 논의 필요).

## 실행 주기 바꾸기

`vercel.json`의 `crons[0].schedule`을 수정하면 된다. cron 표현식은 항상
UTC 기준이고(예: 오전 10시 KST = `0 1 * * *`), Hobby(무료) 플랜은 하루 1회로
제한되며 지정한 시(hour) 안에서 임의 시각에 실행된다(예: `0 1 * * *`는
01:00~01:59 UTC 사이 아무 때나).

## 개발

```
npm install
npm run typecheck   # tsc --noEmit
npm test            # vitest (네트워크/DB/Discord 전부 mock, 실제 호출 없음)
```

## 배포

1. 이 폴더(`job-watcher/`)를 Root Directory로 지정해서 Vercel 프로젝트를 만든다
   (Framework Preset: **Other**).
2. 위 환경변수 5개를 Vercel 프로젝트 설정에 등록한다.
3. MongoDB Atlas에서 이 클러스터의 Network Access를 "Allow access from
   anywhere(0.0.0.0/0)"로 열어둔다 — Vercel 서버리스 함수는 고정 IP가 없어서
   연결 문자열의 아이디/비번으로만 인증하는 이 방식이 표준이다.
4. 배포 후 `vercel.json`에 정의된 크론이 자동으로 등록된다 (Vercel 프로젝트의
   Settings → Cron Jobs에서 확인 가능).
5. 첫 실행 전에 `/api/check-postings`를 직접 한 번 호출해서(브라우저로 배포된
   URL 접속, 또는 Vercel 대시보드의 Cron Jobs 화면에서 수동 실행) 정상 동작하는지
   확인하는 걸 추천한다 — 이때가 "최초 실행"이라 Notion 시드가 일어난다.
