# E5-L3a 검증 보고서 (리포트 카드 생성기)

**최종 판정: PASS-조건부** — 완료 기준 3개는 모두 직접 재현했고 계약 위반도 없다. 다만 mock·비상 규칙 링크 카드가 약속 칸(P2)을 채울 수 있는 구멍이 실제로 재현된다. 병합 전에 아래 "병합 전 고칠 것" 2건을 고친다.

- 검증자: Claude Sonnet 5.5 · 빌더: claude-opus-5.5 · 브랜치 `task/E5-L3a` 커밋 `f41a7e5` · 검증일 2026-09-30
- 환경: `_COMMON.md`의 환경변수 그대로. 생성 출력은 임시 폴더(scratchpad)로 `--out` 지정. worktree는 검증 전후 `git status` 깨끗(무시된 `.pytest_cache/`는 빌더가 18:58에 만든 것)

## 병합 전 고칠 것

1. **mock 카드가 섞인 링크 보고서가 P2 "Neumann" 칸을 채운다.** `card_generators={"astra":5,"mock":5}`인 링크 보고서 하나만 넣어도 P2가 `1.0 (10/10) | **달성(폐기율 병기)**`로 찍힌다. `_read_linkage`가 mock을 "전부 mock일 때만" 배제한다(`set(real) == {"mock"}`). 링크 보고서를 여러 개 넣으면 합산 과정에서 astra 보고서 + mock 보고서가 이렇게 섞인다. mock 카드가 하나라도 있으면 약속 칸을 채우지 않게 고친다(예: mock 보고서는 합산에서 빼고 "mock" 행으로만, 섞인 보고서는 오류 또는 시스템 `mixed`). 이 경우를 테스트에 넣는다(현재 테스트는 전부 mock인 경우만 본다).
2. **비상 규칙(rule) 카드로 만든 링크 보고서도 P2 "Neumann" 칸을 그대로 채우고, 약속 표 행에는 표시가 없다.** `card_generators={"rule":10}`이면 P2가 `**달성(폐기율 병기)**`이고, "비상 규칙 카드 N장 포함"은 3절 상세 표의 '조건' 칸에만 있다. AGENTS.md는 비상 경로 결과를 결과와 화면에 표시하라고 한다. Macro-F1은 rule이 "Neumann 비상 규칙" 행으로 분리되는데(테스트 있음) 링크는 분리되지 않는다. 빌더 보고서의 "rule generator는 'Neumann 비상 규칙' 행으로 따로 둔다"는 Macro-F1에만 맞는 말이다. 약속 행 판정에 규칙 카드 수를 병기하거나 시스템을 나눈다. 테스트를 더한다.

(고친 뒤 `docs/reports/report_card.md`는 코드 커밋이 바뀌므로 같은 명령으로 다시 생성해 커밋한다. 값은 바뀌지 않는다.)

## 권고(병합을 막지 않음)

- 일반 지표 JSON에서 `system`을 생략하면 조용히 `neumann`이 된다(`m.get("system", "neumann")`). `{"id":"bt_hit_at_3","value":0.9,"n":30}`만 넣어도 P3가 Neumann 달성으로 찍힌다. `system`을 필수로 하면 안전하다.
- 링크 보고서 한 개일 때 `linkage_rate`를 입력 그대로 쓴다. `linkage_rate=1.0`인데 `links_ok/links_total=37/40`인 조작 입력은 `1.0 (37/40) 달성`으로 나온다. `eval.linkage`는 항상 `ok/total`을 내므로 실제 위험은 낮다. `ok/total`과 다르면 오류로 멈추게 하면 된다.
- 빈도 기준선 한계 문구 "Micro-F1이 높게 나온다"는 비교 대상 없이 적혀 있다(명세 §2.1·§6의 비교 대상은 옛 union 예측기라 인용할 수 없다). 값(0.5379)은 이번에 새로 잰 것이 맞다(아래). 문구를 "재현율이 높은 흔한 코드만 맞힌다(R1·R2·R6 재현율 1.0, R5·R7 0)"처럼 이번 실측으로만 쓰면 더 정직하다.

## 완료 기준 (직접 실행)

| # | 항목 | 실행한 명령 | 실제 출력(핵심) | 결과 |
|---|---|---|---|---|
| 1a | 가짜 지표 입력 테스트 | `python -m pytest tests/e5/test_report_card.py -p no:cacheprovider -q` | `22 passed in 0.42s`. 값 그대로 옮김(0.612345 등 반올림하면 달라지는 값을 칸 단위로 비교), 없는 지표 `측정 전`(P5·P6·상세 표), 입력 0개면 6개 모두 측정 전, null 값도 측정 전 | 통과 |
| 1b | 테스트가 실제로 실패하는가(조작 코드) | 코드 사본을 scratchpad에 복사해 19가지 변이를 넣고 같은 테스트를 실행(worktree 불변) | 적용된 18개 전부 실패(KILLED): 값 2자리 반올림 · 판정 항상 달성 · 없는 지표를 0으로 채움 · 정렬 뒤집기 · mock→neumann · rule→neumann · 섹션 순서 바꿈 · 구간 low/high 뒤바꿈 · n 칸 삭제 · 제외 클래스 절 삭제 · 연결률 1.0 하드코딩 · 전부-mock 링크를 neumann으로 · 구간 하한 검사 삭제 · 미달 목록 삭제 · 중복 허용 · 각주 1·2 삭제 · 폐기율 없음 표시 삭제. 1개(0.725 값 변경)는 그 값이 `eval/macro_f1.py`에 있어 사본 패턴이 안 맞았다. 테스트가 `"\| 0.725 \| [0.669, 0.772] \|"` 글자를 직접 검사한다. 항상 통과하는 테스트는 없다 | 통과 |
| 2 | 실제 지표로 1회 생성 | `python -m eval.report_card --inputs C:/Users/User/Desktop/project_neumann/data/eval/score_baseline_freq.json --out <scratchpad>/v/card_real.md` | exit 0. `목표 미달 0건: 없음` / `측정 전 6건: P1~P6`. 생성물은 커밋된 `docs/reports/report_card.md`와 생성 줄·재현 명령의 `--out` 경로만 다르고 나머지 동일(diff 확인). 입력 JSON 대조: macro_f1 0.3308 [0.298, 0.3623], micro_f1 0.5379 [0.4871, 0.5861], n=148, 제외 R3·R4·R8·R9, 골드 sha256 `ad25cb4a…` 모두 카드 글자와 같음. 골드·예측 파일 sha256이 입력 JSON 기록과 일치, 카드가 적은 입력 sha256(`e9b7e44c…`)도 실제 파일과 일치 | 통과 |
| 3 | `python scripts/verify.py` | 환경변수 세팅 후 `python scripts/verify.py` | `207 passed in 7.40s` · 보안: 파일 126개 · 계약: 2개 · 테스트: 통과 · `verify 통과`(exit 0). 빌더의 205 passed, 2 skipped는 `NEUMANN_RAW_DIR` 없이 돌린 것이라 skip 2가 다르다 | 통과 |

## 계약 위반 (`git diff main...task/E5-L3a --stat`)

| 항목 | 확인 | 결과 |
|---|---|---|
| 변경 파일 4개 | `docs/reports/E5-L3a.md`, `docs/reports/report_card.md`, `eval/report_card.py`, `tests/e5/test_report_card.py`(전부 추가, +1198). 소유 경로(과제 파일 + 보고서 예외) 밖 변경 없음 | 통과 |
| `contracts/`·`src/neumann/models.py` | 변경 0 | 통과 |
| 데이터·비밀값 | `.env`·`data/`·parquet·키 파일 추가 없음. 키 패턴(`sk-…`, `api_key=`) grep 0건. 입력은 공유 데이터 폴더의 절대 경로로만 참조 | 통과 |
| 다른 `eval/` 파일 | 안 건드림. `eval.macro_f1.REFERENCE_LINES`는 import만 | 통과 |
| main과 충돌 | 병합 기준 이후 main 쪽에서 `eval/`·`tests/e5`·`docs/reports/report_card*`·`E5-L3a*` 변경 없음 | 통과 |

## 정직성

| 항목 | 확인 | 결과 |
|---|---|---|
| 옛 제품 숫자 | 카드·코드에 κ 0.238·0.2379, Macro-F1 0.469·0.4689, Top-3 0.322·0.3222 없음. 빌더 보고서 문장과 테스트의 금지 목록에만 나옴. 카드의 Micro-F1 0.5379는 옛 실측과 같은 숫자지만 이번에 `score_baseline_freq.json`(2026-09-30 18:27, 골드·예측 sha 일치)에서 새로 잰 값이다(같은 골드·같은 결정적 기준선이라 같게 나옴) | 통과 |
| 없는 지표를 지어냄 | 실제 카드에서 Neumann 지표·백테스트·근거 연결·판정 일치율 전부 `측정 전`(값·구간·n을 비움, "입력 없음"). 빈도 기준선 백테스트 precision@3도 `측정 전`. 조작 입력으로 null·NaN·문자열·bool·음수 n·low>high 모두 거부 또는 `측정 전` | 통과 |
| 미달을 먼저 | 약속 표 위에 미달·측정 전 목록, 표는 미달 → 측정 전 → 달성 순(테스트 + 변이 4·14가 실패시킴). 경계값: 0.70은 `달성(구간 하한은 목표 아래)`, 0.6999는 `미달` | 통과 |
| 참조선 값 = 04_평가_명세 | 사람 상한 0.725 [0.669, 0.772]: 명세 §1.2와 일치. n `29리뷰(LOO)`: 명세 §3.1 "4인 라벨 29건"과 일치. 0.629·0.430·0.840(옛 프로토콜 값)은 일부러 뺌(스펙이 0.725와 빈도 기준선만 지목). 참조선이 약속 표보다 먼저 나옴 | 통과 |
| R7 각주 | R7 = `asp_motivation-impact` 근사는 §3.1 표와 같고 "영향·함의 불명확"은 택소노미 R7.6 `impact_unclear`와 같음 | 통과 |
| 골드 대체 각주 | "수동 라벨 100건(2인 교차)" → DISAPERE 합의 골드, 대표 승인 2026-09-29, 계획서 §1.5, §5 결정 5: 명세와 일치 | 통과 |
| 골드 없는 클래스 목록 | R3·R4·R8·R9를 4절에 시스템별로 적고 골드 sha256 병기. 규칙 ①(§2.1) 인용 맞음 | 통과 |
| 값 그대로 옮김 | 입력 숫자를 `str()`로 옮김(재반올림 없음). 합산한 값만 `계산` 표시(테스트 있음) | 통과 |
| mock 결과가 약속 칸을 채우는가 | Macro-F1 mock은 P1을 안 채움(테스트 + 변이 5). 링크가 전부 mock이면 P2를 안 채움. **astra+mock 혼합 링크는 P2를 채움 → 고칠 것 1** | 조건부 |
| 규칙 결과를 LLM 결과로 표시하는가 | Macro-F1 rule은 `Neumann 비상 규칙` 행으로 분리, astra+rule 혼합은 `혼합 generator`로 P1을 안 채움(재현 확인). **링크 rule 카드는 P2 약속 행에 표시 없이 Neumann으로 채움 → 고칠 것 2** | 조건부 |
| 폐기율 없는 100% | 폐기율 없으면 `측정 전 (폐기율 없음)`, P2는 `달성(폐기율 병기)`로만 적음 | 통과 |
| 빌더 보고서 주장 | 22개 테스트·4개 파일·실제 카드 값·재현 명령 모두 사실. 예외: "rule generator는 'Neumann 비상 규칙' 행으로 따로 둔다"는 링크에는 해당 안 됨(고칠 것 2) | 조건부 |

## 재현 절차 (고칠 것)

```python
# 고칠 것 1·2: tests/e5/test_report_card.py의 _linkage_json 사용
build([write("l.json", _linkage_json(10, 10, gens={"astra": 5, "mock": 5}))])   # P2 행: 1.0 (10/10) | **달성(폐기율 병기)**
build([write("l.json", _linkage_json(10, 10, gens={"rule": 10}))])             # P2 행: 1.0 (10/10) | **달성(폐기율 병기)**  (규칙 표시 없음)
```

## 재검증 (5097159)

**최종 판정: PASS** — 1차 "병합 전 고칠 것" 2건이 조작 입력으로 직접 고쳐진 것을 확인했고, 새 테스트는 고치기 전 코드에서 9개 모두 실패한다. `python scripts/verify.py` 통과, 소유 경로 밖 변경 없음. 병합을 막지 않는 남은 점 3건과 PM 확인 1건은 맨 아래에 적는다.

- 검증자: Claude Sonnet 5.5 · 브랜치 `task/E5-L3a` 커밋 `5097159` · 검증일 2026-09-30 · `_COMMON.md` 환경변수 그대로
- 조작 입력·변이 실험은 전부 scratchpad 사본에서 했다(worktree는 검증 전후 `git status` 깨끗, 무시된 `.pytest_cache/`는 18:58 그대로). 실제 OpenAI 호출 없음
- 코드는 `1032ae3` 이후 안 바뀜(`git diff 1032ae3 5097159 -- eval tests` 비어 있음). `d14f3c6`(카드 재생성)·`5097159`(보고서)는 문서만 바뀜

### 고칠 것 1·2: 조작 입력으로 직접 생성 (P2 약속 행과 상세 표를 확인)

`eval.report_card.build`로 근거 연결 보고서를 만들어 넣었다(링크 10/10, 폐기율 5/60). P2 약속 행 결과:

| # | `card_generators` | P2 약속 행 | 상세 표 시스템 칸 | 결과 |
|---|---|---|---|---|
| A | astra 5 + **mock 1** | `측정 전` | `mock 섞임(성능 아님)`, 한계 "mock 카드 1/6장이 들어 있다. 성능 수치가 아니고 약속 판정에 쓰지 않는다" | 통과 |
| B | astra 5 + mock 5 (1차에서 재현된 그 입력) | `측정 전` | `mock 섞임(성능 아님)` | 통과 |
| C | 전부 mock 10 | `측정 전` | `mock(테스트용, 성능 아님)` | 통과 |
| H | mock 1 + rule 4 | `측정 전` | `mock 섞임` (규칙 카드 4/5장도 조건 칸에 적힘) | 통과 |
| N | astra 5 + mock 5, 링크 37/40 | `측정 전`(미달로도 안 잡힘) | `mock 섞임` 0.925 | 통과 |
| P | astra 9 + mock "1"(문자열), mock 0.5·True·-1, 키 `Mock`/`MOCK` | 전부 `측정 전` | (안전한 쪽으로 빠짐) | 통과 |
| F | 파일 2개: astra 10 보고서 + (astra 5 + mock 5) 보고서 | `1.0 (10/10)`, 근거 파일 `f1.json`만 | Neumann 행은 astra 보고서만, mock 섞임 행은 따로. 합산 안 됨(20/20으로 안 나옴) | 통과 |
| D | 전부 rule 10 | `측정 전` | `Neumann 비상 규칙` 행 1.0 (10/10), 조건 칸 "비상 규칙 카드 10/10장 포함". Neumann(astra) 행은 `측정 전` | 통과 |
| G | 파일 2개: astra 10 + 전부 rule 10 | `1.0 (10/10)`(astra 것만) | 규칙 보고서는 `Neumann 비상 규칙` 행으로 분리 | 통과 |
| E | astra 5 + rule 5 | `1.0 (10/10)` · `**달성(폐기율 병기)** · 비상 규칙 카드 5/10장 포함` | Neumann 행 한계 칸 "astra 카드만의 값이 아니다" | 통과(표시 있음, PM 확인 아래) |
| O | 파일 2개: astra 10 + (astra 5 + rule 5) | `1.0 (20/20) 계산` · `비상 규칙 카드 5/20장 포함` | 같은 표시 | 통과 |
| I·J | astra 5 + baseline 5 / `{}` 빈 generator | `측정 전` | `혼합 generator` / `generator 미상` | 통과 |
| L·K | astra 10 (대조군) / astra 10 + mock 0 | `1.0 (10/10)` `**달성(폐기율 병기)**`, 표시 없음 | Neumann 행 | 통과(정상 경로 안 막힘) |

1차에서 재현된 두 입력(B, D)은 더 이상 P2를 채우지 않는다. 표시 없이 채워지는 경로는 찾지 못했다(E·O는 판정 칸에 규칙 카드 수가 붙는다).

### 새 테스트가 고치기 전 동작을 잡는가

| 항목 | 실행 | 결과 |
|---|---|---|
| 고치기 전 코드(`f41a7e5`의 `eval/report_card.py`)에 새 테스트 | `git archive`로 scratchpad에 사본을 만들고 그 파일만 `f41a7e5` 것으로 바꿔 `pytest tests/e5/test_report_card.py` | **9 failed, 22 passed**. 실패한 것: 위 테스트 `test_linkage_with_any_mock_card_never_fills_promise`, `test_mock_report_not_summed_into_neumann`, `test_rule_only_linkage_goes_to_emergency_row`, `test_astra_plus_rule_linkage_marks_rule_cards_in_promise_row`, `test_generic_metric_without_system_rejected`, `test_linkage_rate_must_match_counts` 3개, `test_freq_baseline_note_uses_only_this_measurement`. 빌더 보고서의 "9개 모두 실패"와 같다 |
| 고친 코드에 조작 변이 16개(사본) | 한 번에 하나씩 넣고 같은 테스트 실행 | 12개 KILLED: 원래 버그 되살림(전부 mock일 때만 배제), rule→neumann, 판정 칸 병기 삭제, `system` 기본값 복원, 비율 검사 삭제, ok>total 검사 삭제, mock 보고서를 Neumann에 합산, 규칙 카드 수 오기, mock 한계 문구 삭제, 상단 mock 경고 삭제, astra+rule을 혼합으로 오분류(과잉 차단), 빈도 문구 하드코딩, 비율 허용오차 0.5. 항상 통과하는 새 테스트는 없다 |
| 살아남은 변이 4개 | | mock이 절반 미만이면 무시(`mock/전체 ≥ 1/2`)·mock이 2장 미만이면 무시, astra+baseline을 Neumann으로 취급, generator 비었을 때 Neumann으로 취급, `mock: 0`을 mixed_mock으로 취급(과잉 차단). 테스트는 mock 5/10만 쓰고 혼합·미상 generator는 테스트가 없다. 현재 코드는 위 A·I·J·K에서 직접 확인했듯 맞게 동작한다. 아래 권고 |

### 전체 검증·계약

| # | 항목 | 실행한 명령 | 실제 출력(핵심) | 결과 |
|---|---|---|---|---|
| 1 | 리포트 카드 테스트 | `python -m pytest tests/e5/test_report_card.py -p no:cacheprovider -q` | `31 passed` | 통과 |
| 2 | 실제 지표 1회 생성 | `python -m eval.report_card --inputs …/data/eval/score_baseline_freq.json --out <scratchpad>/card_real.md` | exit 0. 커밋된 `docs/reports/report_card.md`와 비교하면 다른 줄은 생성 시각·코드 커밋·`--out` 경로 3곳뿐. 목표 미달 0건, 측정 전 6건(P1~P6). 카드 안 빈도 기준선 문구는 "늘 내는 코드(R1·R2·R6)는 재현율 1.0, 안 내는 코드(R5·R7)는 재현율 0이라 Micro-F1(0.5379)이 Macro-F1(0.3308)보다 높다"로 바뀜(입력 JSON의 클래스별 재현율과 일치) | 통과 |
| 3 | `python scripts/verify.py` | 환경변수 세팅 후 실행 | `216 passed in 3.68s` · 보안: 파일 126개 · 계약: 2개 · 테스트: 통과 · `verify 통과`(exit 0). 216 = 기존 + 새 9개(1차 207 → 216) | 통과 |
| 4 | 소유 경로 | `git diff main...task/E5-L3a --stat` | 4개 파일(`docs/reports/E5-L3a.md`, `docs/reports/report_card.md`, `eval/report_card.py`, `tests/e5/test_report_card.py`), 전부 추가 +1410. 소유 경로 밖 변경 없음 | 통과 |
| 5 | 계약·데이터·비밀값 | 변경 파일 이름을 `contracts/`·`src/neumann/models.py`·`data/`·`.env`로 grep, diff에서 `sk-…`·`api_key=` grep | 각각 0건 | 통과 |
| 6 | main과 충돌 | 병합 기준(`481e11c`) 이후 main 쪽에서 `eval/`·`tests/e5`·`docs/reports/report_card.md`·`E5-L3a.md` 변경 | 없음 | 통과 |
| 7 | 권고 반영 확인 | 조작 입력 | `system` 없는 일반 지표는 `InputError("system이 없다…")`(테스트 + 변이 4가 실패시킴). `linkage_rate=1.0`인데 37/40이면 오류(변이 5·15가 실패시킴) | 통과 |

### PM 결정과의 대조 (요청 4)

- **main `docs/decisions.md`의 19:15·19:20 줄은 이 내용이 아니다.** 19:15는 위험점수를 곱으로(E4-L1b), 19:20은 내보내기는 결과 JSON만 받음(SEC-1 S-02)과 터널 공개는 SEC-1 수정 뒤다. 파일 전체와 `docs/`를 `mock`·`약속`·`해당 없음`·`비상`으로 찾아도 "mock·rule 카드는 약속 칸을 채우지 않는다"는 기록이 없다. 그래서 요청에 적힌 문구("mock·rule 카드는 약속 칸을 채우지 않고 측정 전/해당 없음")를 기준으로 대조했다. 원문 위치가 다르면 알려 달라.
- mock: 한 장이라도 섞이면 P2·P1 모두 `측정 전`. 문구와 같다(A·B·C·H·N).
- rule: 전부 규칙이면 P2 `측정 전`, `Neumann 비상 규칙` 행으로만 나옴. 문구와 같다(D·G). 이 카드 생성기에는 "해당 없음" 표기가 없고 모두 `측정 전`이다.
- **문구와 글자 그대로는 어긋나는 한 곳**: astra와 규칙 카드가 섞인 링크 보고서(E·O)는 P2를 채운다. 값 옆에 `· 비상 규칙 카드 k/N장 포함`이 붙는다. 1차 보고서가 "약속 행 판정에 규칙 카드 수를 병기하거나 시스템을 나눈다"고 허용한 쪽이고, "표시 없이 채우지 않는다"는 요청 2의 기준은 만족한다. 다만 Macro-F1은 astra+rule이 섞이면 `혼합 generator`로 P1을 안 채우므로(`_macro_system`), 같은 상황에서 P1은 비우고 P2는 병기로 채우는 불일치가 남는다. 링크 보고서는 카드별 generator에 따른 연결 결과를 나눠 주지 않아 빌더가 병기를 골랐고(빌더 보고서 결정 절), 이유는 타당하다. **PM이 어느 쪽인지 정한다(결정이 "규칙 카드가 하나라도 있으면 약속 칸을 비운다"면 `_linkage_system`의 astra+rule 분기를 `mixed`로 바꾸고 테스트 1개를 뒤집으면 된다).** 병합을 막는 결함은 아니다.

### 병합을 막지 않는 남은 점

1. 새 테스트는 mock 5/10만 쓴다. mock 1장/전체 N장(A·P처럼 소수 혼입), astra+baseline 혼합, generator 비어 있음이 테스트에 없다. 코드는 맞게 동작하지만(직접 확인) 임계값을 넣는 식의 되돌림은 테스트가 못 잡는다(변이 살아남음). 소수 mock 1건 테스트를 더하는 것을 권한다.
2. `card_generators` 개수 합이 `cards_total`과 달라도(예: `{"astra": 5}`, cards_total 10) 그대로 astra 행으로 채운다(M). `eval.linkage`는 카드마다 세므로(`eval/linkage.py` `generators[...] += 1`) 실제 출력에서는 합이 같다. 손으로 만든 입력에서만 가능하다.
3. `card_generators` 값이 정수로 못 읽히는 문자열(`"abc"`)이면 `InputError`가 아니라 `ValueError`(추적 메시지)로 멈춘다. 멈추는 방향이라 안전하고, 실제 도구 출력은 항상 정수다.
