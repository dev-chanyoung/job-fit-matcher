# job-watcher

자소설닷컴의 특정 검색결과(직무/기업분류 필터)를 매일 확인해서, 지난 실행 이후
새로 올라온 공고만 Discord로 알려주는 서비스. Vercel Cron으로 매일 자동 실행되고
(PC가 꺼져 있어도 동작), 상태는 MongoDB에 저장한다.

`job-judge`(로컬 Claude Code CLI 도구)와는 완전히 독립적인 별도 프로젝트다 —
이 프로젝트는 **"신규 공고 발견 + 알림"까지만** 하고, 하드필터/평가는 절대
자동으로 돌리지 않는다. Discord로 알림이 오면, 평가하고 싶은 링크를 골라서
기존처럼 Claude Code 세션(`job-judge`)에 붙여넣어야 실제 평가가 시작된다.

## 동작 방식

1. 매일 정해진 시각(기본: 오전 10시 KST, `vercel.json`의 `schedule` 참고)에
   Vercel이 `/api/check-postings`를 호출한다.
2. 자소설닷컴 검색 페이지를 fetch해서 `__NEXT_DATA__` 스크립트 태그 안의
   JSON을 직접 파싱한다 (JS 렌더링/헤드리스 브라우저 불필요 — LLM 호출도 없음,
   전부 결정론적 코드).
3. MongoDB에 저장된 "이미 본 공고" 목록과 비교해서 신규 공고만 골라낸다.
   - **최초 실행**(MongoDB에 아무 데이터도 없을 때)에는 Notion(job-judge가 쓰는
     채용 트래커 DB)에 이미 등록된 회사는 회사명 기준으로 조용히 시드(=알림
     제외)하고, Notion에 없는 회사만 진짜 신규로 취급해서 알림 + 저장한다.
4. 신규 공고가 있으면 Discord 웹훅으로 포맷된 메시지를 보낸다(2000자 넘으면
   여러 메시지로 분할).
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

`lib/jasoseol.ts`의 `SEARCH_URL` 상수를 자소설닷컴에서 원하는 조건으로 검색한
뒤 그 주소로 바꾸면 된다.

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
