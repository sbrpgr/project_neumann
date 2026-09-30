# Neumann

연구계획서를 넣으면, 비슷한 연구가 실제로 받은 **심사평·저자 답변·결정·정정/철회 기록**에서 위험을 찾아 근거가 연결된 위험카드로 돌려주는 서비스다.

- 분석 대상은 논문 본문이 아니라 평가 과정 기록이다.
- 개입 시점은 투고 직전이 아니라 연구 착수 전이다.
- 카드마다 실제 심사평 문장을 인용하고 원문 링크를 단다. 근거 없는 문장은 내보내지 않는다.

2026 NAIS AI 해커톤 본선(2026-09-30 17:00 ~ 10-01 12:00)에서 처음부터 만들고 있다. 커밋 이력이 곧 현장 개발 기록이다.

## 상태

| 단계 | 내용 | 태그 |
|---|---|---|
| L0 | 계획서 입력 → 유사 연구 + 위험카드(실제 심사평 인용) | `v0` |
| L1 | 위험점수, 예상 심사평, 근거 열람 패널 | `v1` |
| L2 | 체크리스트·결정 로그, 백테스트, 내보내기 | `v2` |
| L3 | 디자인, 규모 확대, 리포트 카드 | `v3` |

## 시작하기

Python 3.12. 의존성은 `pyproject.toml`.

```bash
cp .env.example .env                      # 값을 채운다. .env는 커밋되지 않는다
git config core.hooksPath .githooks       # 비밀값 검사 훅을 켠다(클론마다 한 번)
python scripts/verify.py                  # 보안 + 계약 + 테스트
```

## 보안

공개 저장소다. 비밀값은 `.env`에만 두고 코드는 환경변수로만 읽는다.

- `.gitignore`가 `.env`, 데이터, 모델 가중치, 캐시, 로그를 막는다.
- `scripts/verify.py`가 키 형태 문자열, `.env`에 든 실제 키 값, 금지 파일, 5MB 넘는 파일을 찾는다. 찾은 값은 출력하지 않는다.
- git 훅: `pre-commit`(스테이징 내용), `commit-msg`(메시지), `pre-push`(추적 파일 전체와 커밋 메시지).
- GitHub 시크릿 스캐닝과 푸시 보호가 켜져 있다.

## 구조

| 경로 | 내용 |
|---|---|
| `AGENTS.md` | 에이전트 규칙 원본(Claude·Codex 공통). `CLAUDE.md`가 가져온다 |
| `contracts/` | 데이터 계약 JSON Schema(API 응답, 화면 데이터) |
| `docs/decisions.md` | 결정 기록 |
| `docs/HANDOFF.md` | 작업 인계 문서 |
| `scripts/verify.py` | 검증 러너 |
| `src/neumann/` | 제품 코드(작성 예정) |

## 데이터 출처

공개 데이터 원본을 쓴다. 데이터 파일은 저장소에 넣지 않는다.

- OpenReview 공개 심사 기록(공개 미러 ResearchArcade 경유)
- DISAPERE(사람이 붙인 심사평 라벨)
- Crossref–Retraction Watch(정정·철회)
- 임베딩 모델 BAAI/bge-m3
