# 호통 백엔드 API

FastAPI 기반의 백엔드 API 서버입니다.

## 아키텍처

- **Nginx**: 리버스 프록시 및 SSL 터미네이션
- **FastAPI**: Python 웹 프레임워크
- **Redis**: 캐싱 및 세션 저장소
- **Docker**: 컨테이너화된 배포

## 학교 이메일 OTP 인증

택시팟 사용자 인증은 기존 관리자 비밀번호 인증과 분리된 Supabase Auth를
사용합니다. Flutter는 Supabase access token을 `Authorization: Bearer`로
전달하고, FastAPI의 `GET /api/app-auth/me`는 서명과 필수 claim을 검증한 뒤
`auth.users.id`와 같은 UUID만 반환합니다.

필수 서버 환경 변수:

```dotenv
SUPABASE_PROJECT_URL=https://YOUR_PROJECT_REF.supabase.co
```

`SUPABASE_URL`은 기존 PostgreSQL 접속 문자열이므로 이름을 변경하거나 Auth
URL로 덮어쓰면 안 됩니다. JWT 검증에 `service_role` 키는 사용하지 않습니다.

DB 마이그레이션 후 Supabase Dashboard에서 다음 설정을 별도로 적용합니다.

1. Email provider와 신규 가입을 활성화합니다.
2. 이메일 템플릿에 `{{ .Token }}`을 넣고 OTP 유효기간을 10분으로 설정합니다.
3. Before User Created Hook에
   `pg-functions://postgres/public/hook_restrict_school_signup`을 연결합니다.
4. Custom Access Token Hook에
   `pg-functions://postgres/public/hook_restrict_school_token`을 연결합니다.
5. 운영 전에 Custom SMTP를 설정하고 실제 `@vision.hoseo.edu` 주소로 발송을
   검증합니다.

Flutter는 Supabase Data API를 사용하지 않습니다. 프로젝트의 다른 사용처가
없다면 Dashboard에서 Data API를 비활성화합니다. 롤백할 때는 앱의 택시 인증
진입을 먼저 닫고 두 Auth Hook 연결을 해제한 다음 마이그레이션을 내립니다.

## 택시팟 MVP

택시팟은 인증된 학교 사용자만 접근할 수 있으며 API 응답과 채팅에는 이메일이나
사용자 UUID 대신 방별 `방장`, `참여자 N` 표시만 노출합니다. 관리자는
`/admin-v2/taxi-locations`에서 캠퍼스·역·터미널 등의 거점을 관리하고,
사용자는 활성 거점 사이에서 택시팟을 만들고 즉시 참여합니다.
초기 거점으로 아산캠퍼스, 천안캠퍼스, 천안아산역, 두정역, 천안터미널,
천안역을 추가하며 관리자가 대시보드에서 이름·순서·활성 상태를 바꿀 수 있습니다.

- 앱 REST API: `/api/taxi/*`
- 앱 실시간 연결: `/ws/taxi` (`Authorization: Bearer` 필수)
- 관리자 거점 API: `/api/admin-v2/taxi-locations`
- 관리자 방 조회·강제 취소: `/api/admin-v2/taxi-parties`
- 출발 시각: 현재로부터 10분 이후, 최대 7일 이내
- 정원: 방장 포함 2~4명
- 중복 참여 방지: 출발 전 활성 모집은 사용자당 하나
- 모집 종료: 출발 시각에 자동 종료되며 즉시 새 팟 생성·참여 가능
- 채팅: 출발 후 3시간까지 쓰기 가능, 이후 읽기 전용, 출발 48시간 후 열람 종료
- 취소된 팟: 즉시 읽기 전용, 취소 48시간 후 열람 종료

마이그레이션 적용:

```bash
alembic upgrade head
```

메시지는 출발 후 48시간(취소된 팟은 취소 후 48시간)이 되면 API에서 즉시
열람할 수 없으며, 다음 일괄 작업에서 실제 삭제됩니다. 택시팟의 4자리 코드는
30일간 유지됩니다. 마이그레이션이 생성하는
`public.cleanup_expired_taxi_messages()` 프로시저가 1,000건 단위로 메시지를
삭제하고 코드를 회수합니다. `cleanup-expired-taxi-data` Cron 작업은 매일
19:00 UTC(한국 시간 04:00)에 실행되며 중복 실행 잠금을 사용합니다. 실행 권한은
`PUBLIC`, `anon`, `authenticated`에서 회수되어 있습니다.
수동으로 정리를 실행하려면 다음 SQL을 사용합니다.

```sql
call public.cleanup_expired_taxi_messages();
```

Redis가 잠시 중단되어도 이미 성공한 REST/DB 작업은 실패로 되돌리지 않습니다.
실시간 이벤트를 놓친 앱은 화면 복귀·새로고침 때 REST API를 기준으로 상태를
다시 동기화합니다.
