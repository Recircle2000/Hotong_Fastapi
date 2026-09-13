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

