# 인계 문서

PM이 병합할 때마다 갱신한다. Claude 한도가 다 되면 이 문서를 Codex에 주고 PM 역할을 넘긴다.

## 지금 상태 (2026-09-30 18:00)

- 단계: E0(골격) 진행 중. 제품 코드 없음.
- 태그: 없음. 다음 태그 `v0`(목표 T+3h, 20:00).
- main: 규칙(`AGENTS.md`), 보안 설정(`.gitignore`, 훅, `scripts/verify.py`), 계약 스키마, 문서.

## 다음 할 일

1. E0 나머지: `src/neumann/models.py`·`config.py`, 공용 fixture, 데모 계획서 3건, `docs/tasks/`
2. W1 과제 발행: E1-L0 수집 · E2-L0 색인 · E3-L0 카드 · E4-L0 화면

## 인계 받는 쪽이 지킬 것

- 규칙은 `AGENTS.md`. 병합 전 `python scripts/verify.py` 통과가 유일한 게이트다.
- 기준 문서: `C:\Users\User\Desktop\노이만_본선자료\기획서\00_구현_계획서.md`
- `.env`는 열지 않는다. 키가 있는지만 참·거짓으로 확인한다.
