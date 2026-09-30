# FIN-TOOLS — 최종 점검용 검증 도구와 규칙 기반 점검 추출기

빌더: claude-opus-5.5. 기준: `codex/finalization-20261001` + `codex/core-final-20261001` 병합(2dd0785, 문서 충돌 2건 양쪽 보존) + FIN-ENGINE 도구 인터페이스 a3b973b(b93561a). 모든 명령 mock, OpenAI 0, `.env` 미사용, 키 변수 제거(`env -u OPENAI_API_KEY -u NEUMANN_PSEUDONYM_SALT`).

범위 조정(PM): 새 계산기·단위 대수·제한 실행기(units·sandbox)는 만들지 않았다. Codex FINAL-TOOLS의 Z3·Pint·NetworkX와 숫자 규칙을 재사용해, 가장 큰 공백이던 **규칙 기반 점검 추출기**(mock에서 checks 0개 문제)와 FIN-ENGINE 레지스트리용 도구 구현을 만들었다.

## 한 일

- **VER-FIN C-1 수정(f1d9bc7)**: `analyze/final_tools._constraint`가 Z3 전역 컨텍스트를 써서 2스레드 동시 호출에 프로세스가 죽었다(수정 전 이 PC에서 0xC0000005 재현). 모든 Z3 경로를 공용 `final_tools.Z3_LOCK` + 호출마다 새 `z3.Context()`로 바꾸고 참조·컨텍스트를 잠금 안에서 놓는다. 기존 상한(16 checks·32 terms·256자 인용·200 ms) 유지. 회귀: 별도 프로세스 4스레드×20회×16 checks, 2번, 종료 0.
- `src/neumann/finalize/tools/` (FIN-ENGINE `ToolCall→ToolResult` 계약에 `ToolSpec`으로 등록, `fin_tools.register_all()`)
  - `quantities.py`: 수치·단위 인식. Codex `_NUMBER` 경계(한글 조사 허용, 영문 식별자·지수 조각 거부) + 천 단위 쉼표·과학 표기·한국어 배수(1억 5천만)·ML 배수(7B parameters)·비율(초당 N, N/s). 한정·부정 줄은 Codex `_QUALIFIED_NUMERIC`로 제외.
  - `extract.py`: 계획서 → 점검 목록(`ExtractedCheck`: 점검 유형·줄·원문 글자 그대로의 근거 위치·`ToolCall`). 도구 선택은 `TOOL_FOR_CHECK` 표가 한다.
  - `sums.py`(arithmetic_sum): 정확한 유리수 + Z3 교차 확인(같은 잠금). `dimension.py`(unit_dimension): Pint 차원·변환·규모(derive·compare), 정보량은 [information] 차원(Pint 기본 byte 무차원·Gb=gilbert 회피). `structure.py`(structure): NetworkX 절 계층·표/그림·참조 그래프. `citation.py`(citation_lookup): MCP 서버 백엔드로 DOI 철회 조회·제목 코퍼스 확인, 환경변수를 읽지 않음(엔진이 `configure(data_dir)`로 지정).

## 점검 유형 → 도구 표 (코드: `fin_tools.CHECK_TOOL_TABLE`, 선택은 `TOOL_FOR_CHECK`)

| 추출 라벨 | 원문 예 | 점검 유형 | 도구(구현) |
|---|---|---|---|
| split_sum | 80/10/10 train/val/test, 학습 70%·검증 15%·테스트 15% | sum | arithmetic_sum (Fraction+Z3) |
| schedule_sum / schedule_span | 1단계 3개월…총 연구 기간 12개월 / M1–M14 vs 12개월 | sum | arithmetic_sum |
| budget_sum / table_sum | 인건비 3억 원…총 6억 원 / 표의 합계 행·열 | sum | arithmetic_sum |
| expr_sum | 3 + 4 = 8 | sum | arithmetic_sum |
| arith_expr | 32 × 100 = 3200 (단위 없음) | arithmetic | calculator (FIN-ENGINE; 없으면 unchecked) |
| unit_derive | 1억 개를 초당 1,000개로 처리하면 10시간 / GPU 8장 × 72시간 = 576 GPU시간 | unit | unit_dimension derive (Pint 규모) |
| unit_add / unit_compare | 10 mS + 1 S/cm / 120 GB ≤ 80 GB | unit | unit_dimension add·compare (Pint) |
| sections | 필수 9절 존재·순서·번호 빈칸·중복 | structure | structure (NetworkX) |
| references | §12 참조, 표 2 참조 | reference | structure (NetworkX) |
| citation | doi:10.…, “제목” (연도·et al.) | citation | citation_lookup (코퍼스·Retraction Watch) |

## 완료 기준별 측정

- 오류 심은 fixture(`tests/finalize/fin_tools_plans.SEEDED`): 심은 9종 모두 해당 줄에서 검사가 생기고 fail(분할 110≠100, 일정 10≠12, 예산 표 5억≠6억, 10 mS+1 S/cm 차원 불일치, 27.8 h≠10 h, 576≠500, 누락 위험·기대효과·가설 순서·5절 빈 번호, §12·표 2 깨진 참조, 철회 DOI). 대조군 CLEAN은 추출된 검사 전부 pass. 데모 계획서 3편은 80/10/10 pass, 필수 절 누락만 fail.
- 변이 검사 31종(합계 6·Pint 6·구조 6·추출 6·수치 4·인용 3): 전부 잡힘(`test_fin_tools_mutation.py`, 소스 한 곳을 바꾼 모듈을 새로 실행해 각 도구 사례 표로 판정).
- 적대 입력: 코드 문자열·bool·inf·nan·1e999·거대 지수 단위(`m^999`, `__import__`), 20만 자 잡음·5,000줄 표·§ 1만 개 → 예외 없이 unchecked 또는 상한 안(추출 ≤32건, 참조 ≤500개). 도구 오류 문구는 evidence에 남지 않음.
- 명령: `env -u OPENAI_API_KEY -u NEUMANN_PSEUDONYM_SALT NEUMANN_LLM_PROVIDER=mock PYTHONPATH="src;." PYTHONUTF8=1 python -m pytest tests/finalize/ tests/e3/test_final_tools.py tests/e3/test_final_tools_threads.py tests/e3/test_finalize.py -q` (결과는 커밋 메시지). PM 지시로 전체 verify는 다시 돌리지 않았다(커밋 훅 `verify --staged` 보안 검사만 통과).

## 한계

- 추출은 규칙이다. 뜻이 둘로 읽히는 경우(금액 둘인 항목 줄, 병행 일정, 단위 섞인 합, 단위 없는 피연산자가 섞인 단위 산식)는 뽑지 않는다(오탐보다 누락). 뽑히지 않은 주장은 "검사 안 함"이지 통과가 아니다.
- calculator·restricted_exec 구현은 FIN-TOOLS 범위 밖이다(arith_expr은 호출만 만든다). 인용은 코퍼스 밖 논문이면 unchecked이며, 철회 "기록 없음"은 보증이 아니다.
- Pint는 이 PC에서 import 수 초 + 레지스트리 약 2초가 걸린다(과정당 1회 캐시, `fin_tools.warmup()`). 백엔드 검색 시 E2 색인 모듈이 자체 설정을 읽을 수 있다(도구 코드는 환경변수를 읽지 않는다).

## 남은 일

1. FIN-ENGINE `checks`/엔진이 `extract_checks` → `run_checks` 결과를 문제·수정 이력에 붙이도록 연결하고, 서버 기동 때 `fin_tools.warmup()`·`citation.configure(data_dir)`를 부른다.
2. calculator 구현(FIN-ENGINE builtin)이 들어오면 arith_expr의 `tolerance`(적힌 자릿수 반 칸, 절대값) 의미를 맞춘다.
3. 실제 계획서(공개 샘플 8~10편)로 추출 재현율·오탐을 재고, 뽑지 않은 유형(단위 섞인 합, 연차별 예산 표)을 규칙으로 보탠다.
4. `analyze/final_tools._units`가 호출마다 Pint 레지스트리를 새로 만든다(느림) — `dimension.registry()` 공유로 바꿀지 E3 소유자와 정한다.
5. Codex V-C1의 f1d9bc7 독립 검증 결과를 받아 반영하고, PM이 FIN-ENGINE과 같은 기준으로 병합 순서를 정한다.
