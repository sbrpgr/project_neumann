# E5-L3b 보고서: 확정 지표로 리포트 카드 재생성 + 한 장 요약

- 브랜치 `task/E5-L3b`(분기점 main `88f1b51` = 지시문의 `9a77719` 위 QUEUE 커밋 1개. 지금 main 최신이 아니다) · 빌더 claude-opus-5.5 · 검증 예정 Claude Sonnet 5.5
- 실제 OpenAI 호출 0회. 파일만 읽었다(`NEUMANN_LLM_PROVIDER=mock`, 서버·8010 접근 없음). `git stash` 쓰지 않음
- 진행 중 받은 지시 세 가지(모두 반영):
  1. "즉시 마무리" → 짧은 보고서(`28a1472`)로 마감
  2. 철회 → 원래 과제를 끝까지
  3. PM 결정 → P2는 측정 전, 카드 한계 문구 백테스트 n=5, `e2e_cards` 이름표, 정식 보고서
  4. PM 결정 → P6 시연도 P2와 같은 규칙. 약속 칸은 측정 전, 3/3은 "generator 미기록 실행" 참고 행(`5d59a82`)
  5. 검증 PASS-조건부(`849cdaa`) → 필수 문서 정정 2건과 선택 권고 반영. 맨 아래 "검증 반영" 절, 검증 요약은 `E5-L3b.verify.md`
- `eval/report_card.py`는 처음 지시에서 수정 금지였다. 3번 PM 지시로 두 곳(한계 문구·이름표)만 고쳤다(`e9bcdbd`).

## 무엇을 했나

1. **변환 스크립트** `scripts/metrics_from_e2e.py`. 라이브 E2E 요약(`docs/reports/E5-L0e2e_live_summary.json`)을 `eval.report_card`가 읽는 `neumann.metrics/1`로 바꾼다.
   - 지표:
     - 근거 연결률 `linkage_rate`, 카드 통과율 `card_pass_rate`, 폐기율 `drop_rate`(연결 요약 문자열의 `폐기율 a/b`)
     - 화면 카드 수 `e2e_cards`
     - 실패 0으로 통과한 데모 수 `demo_e2e`(약속 P6). 통과 조건에 근거 연결 검사가 들어 있다. 그래서 연결 시스템이 미기록(참고)이면 이것도 참고 행으로 간다. detail은 "3/3; generator 미기록 실행"이다
   - 모델: `--model`은 필수다(요약에 모델 이름이 없다). 이번에는 `gpt-6-astra`로 적었다. `--product-model gpt-6.1-sol`을 주면 이 모델로 재지 않은 헤드라인 지표 4개를 값 null(= 측정 전) 행으로 적는다.
   - **연결 지표 3개의 시스템**은 연결 검사 실행의 카드 generator(`plans[*].linkage.card_generators`)로 정한다. `eval.report_card`의 연결 보고서 규칙과 같다.

     | generator 기록 | 시스템 | 약속 P2 |
     |---|---|---|
     | 한 계획서라도 없음 | `Neumann 참고(검사 실행 generator 미기록, 약속 판정 제외)` | 측정 전(PM 결정). 시연 P6도 측정 전 |
     | astra만 | `neumann` | 채움 |
     | astra + rule | `neumann`(규칙 카드 수 병기) | 채움 |
     | rule만 | `neumann_rule` | 측정 전 |
     | 그 밖 | `mixed` | 측정 전 |
     | mock 섞임 | 거부 | — |

   - 거부하는 경우(종료 코드 2):
     - 샘플 모드 요약, 파이프라인 미연결, `source != pipeline`
     - 비율과 개수가 다르거나, `links`·`cards` 필드와 요약 문자열의 개수가 다름
     - 폐기율을 읽을 수 없음, ok > total, generator 형식 오류
   - 비율: 소수 4자리로 적는다. 다만 1.0이 아닌 값을 1.0으로, 0이 아닌 값을 0으로 반올림하지 않는다. 정확한 개수와 계획서별 개수는 `detail`에 둔다.
   - 출력 줄바꿈은 LF로 고정했다(`.gitattributes eol=lf`). 그래야 카드에 적힌 sha256이 체크아웃한 파일과 같다.
2. **`eval/report_card.py`(PM 지시)**:
   - 한계 4번 "백테스트 n=30이면…"을 바꿨다. 새 문구: "백테스트는 n=5(대표 결정, 비용 사유; real 대 기준선, 셔플 없음, sol)다. 표본이 작아 95% 구간이 매우 넓다. … 셔플이 없어 특이성(진짜 − 셔플)은 재지 않는다."
   - `METRIC_LABELS`에 `e2e_cards` = "라이브 E2E 화면 위험카드 수 (데모 계획서 합)"(count)를 더했다. 카드에서 "(기타)"가 없어졌다.
3. **테스트** `tests/e5/test_metrics_from_e2e.py` 26개. 커밋된 라이브·샘플 요약 파일을 그대로 쓴다.
   - 실제 파일 변환: 연결 지표는 참고 행으로 가고 neumann 행이 없다. 값은 43/43, 12/12, 7/2033 = 0.0034, 13장, 3/3이고 sol 행은 null이다.
   - 거부: 샘플 모드, 불일치 8종, mock·형식 오류 3종.
   - 기록된 generator 5가지 경로가 각각 P2 칸을 어떻게 만드는지. 한 계획서만 미기록이어도 전체가 참고 행이 되는지.
   - 연결 실패를 1.0으로 올리지 않는지. 다른 검사가 실패한 계획서를 시연 수에서 빼는지. 반올림 보호, 폐기율 없음, 연결 검사를 안 한 계획서.
   - 카드 통합: P2 측정 전, 참고 행, P6, sol 행, 새 이름표, "(기타)" 없음, 한계 문구 n=5.
   - CLI 종료 코드, 출력 LF, 커밋된 변환 결과가 지금 변환기 출력과 바이트 단위로 같은지.
4. **변환 결과** `docs/reports/E5-L3b_metrics_e2e.json`(지표 9개, 5.5KB). 커밋된 요약에서 결정적으로 나오므로 저장소에 두었다. 카드 입력 4개 중 이 파일만 저장소 안에 있다.
5. **리포트 카드 재생성** `docs/reports/report_card.md`. 입력은 빈도 기준선·astra·규칙 score JSON 3개와 변환 지표다.
6. **한 장 요약** `docs/reports/metrics_summary.md`. 들어 있는 것:
   - 참조선
   - 약속 대비(미달 먼저, P2 측정 전)
   - 참고값(43/43·폐기율·카드 통과)과 같이 적을 숫자
   - 발표 문구 조건 7개
   - README 블록
   - 재현 명령
   - 숫자마다 출처 파일을 적었다.

## 결과 (카드 2절 그대로)

| # | 약속 | 목표 | 측정값 | 95% 구간 | n | 판정 | 입력 |
|---|---|---|---|---|---|---|---|
| P1 | 지적 추출 Macro-F1 | ≥ 0.70 | 0.4864 (gpt-6-astra) | [0.4276, 0.5394] | 148 | **미달** | score_astra.json |
| P2 | 근거 연결률 (폐기율 병기) | 100% | 측정 전 | — | — | **측정 전** | — |
| P3 | 백테스트 Top-3 적중(hit@3) | ≥ 0.50 | 측정 전 | — | — | **측정 전** | — |
| P4 | 표본 연결 | ≥ 300편 | 측정 전 | — | — | **측정 전** | — |
| P5 | 원문 링크 | 100% | 측정 전 | — | — | **측정 전** | — |
| P6 | 대표 계획 end-to-end 시연 | 3건 | 측정 전 | — | — | **측정 전** | — |

- 참조선:
  - 사람 간 상한 0.725 [0.669, 0.772]
  - 빈도 기준선 Macro 0.3308 [0.298, 0.3623], Micro 0.5379 [0.4871, 0.5861]
- 참고 행(상세 표, 약속 판정 제외). 시스템 이름은 `Neumann 참고(검사 실행 generator 미기록, 약속 판정 제외)`이다.
  - 근거 연결률 1.0 (43/43; 10/10 · 13/13 · 20/20)
  - 카드 통과 1.0 (12/12)
  - 폐기율 0.0034 (7/2033; 1/643 · 2/701 · 4/689)
  - 대표 계획 시연 3 (3/3; generator 미기록 실행)
- 같은 지표의 `Neumann (astra)` 행은 "측정 전 · 입력 없음"이다.
- 평가 모델과 제품 모델:
  - `Neumann (astra)`의 astra는 평가 모델 gpt-6-astra다.
  - `Neumann 제품 기본 모델(gpt-6.1-sol)` 행 4개(Macro-F1·근거 연결률·폐기율·시연)는 "측정 전"이다.
  - 조건 칸에 "이 카드의 Neumann 수치는 평가 모델 gpt-6-astra로 잰 것", 한계 칸에 "재측정 안 한 사유: 비용(decisions 19:38·19:42)"을 적었다.
- 기타: 비상 규칙 Macro 0.3234 [0.2434, 0.3871], 화면 위험카드 13장(5·3·5).

## 완료 기준별 명령과 출력

공통 환경: `export PYTHONIOENCODING=utf-8 PYTHONPATH="src;." NEUMANN_LLM_PROVIDER=mock`, `D=C:/Users/User/Desktop/project_neumann/data/eval`

### ① 변환 스크립트

```
$ python scripts/metrics_from_e2e.py --summary docs/reports/E5-L0e2e_live_summary.json --model gpt-6-astra --product-model gpt-6.1-sol --out docs/reports/E5-L3b_metrics_e2e.json
linkage_rate    Neumann 참고(검사 실행 generator 미기록, 약속 판정 제외) 1.0      43/43; plan.md 10/10 · plan_elife_neuro.md 13/13 · plan_medimaging.md 20/20; 검사 실행 카드 generator 미기록
card_pass_rate  Neumann 참고(검사 실행 generator 미기록, 약속 판정 제외) 1.0      12/12; plan.md 3/3 · plan_elife_neuro.md 4/4 · plan_medimaging.md 5/5
drop_rate       Neumann 참고(검사 실행 generator 미기록, 약속 판정 제외) 0.0034   7/2033; plan.md 1/643 · plan_elife_neuro.md 2/701 · plan_medimaging.md 4/689
e2e_cards       neumann                                  13       plan.md 5 · plan_elife_neuro.md 3 · plan_medimaging.md 5
demo_e2e        Neumann 참고(검사 실행 generator 미기록, 약속 판정 제외) 3        3/3; generator 미기록 실행
macro_f1        Neumann 제품 기본 모델(gpt-6.1-sol)            None
linkage_rate    Neumann 제품 기본 모델(gpt-6.1-sol)            None
drop_rate       Neumann 제품 기본 모델(gpt-6.1-sol)            None
demo_e2e        Neumann 제품 기본 모델(gpt-6.1-sol)            None
지표 9개 → docs\reports\E5-L3b_metrics_e2e.json

$ python scripts/metrics_from_e2e.py --summary docs/reports/E5-L0e2e_sample_summary.json --model gpt-6-astra --out <scratchpad>/s.json
오류: mode='sample': 라이브 요약만 받는다(샘플 모드 결과는 성능이 아니다)
exit 2

$ python -m pytest tests/e5/test_metrics_from_e2e.py tests/e5/test_report_card.py -q
57 passed in 0.96s          (이 과제 26 + E5-L3a 카드 테스트 31)
```

- 입력 대조: 계획서별 `linkage.summary`는 아래와 같고, 변환 결과와 같다.
  - `근거 연결률 10/10 · 카드 통과 3/3 · 폐기율 1/643`
  - `13/13 · 4/4 · 2/701`
  - `20/20 · 5/5 · 4/689`
  - `n_cards`는 5·3·5, `failures`는 네 건 모두 `[]`
- `linkage`에 `card_generators` 키가 없다. 그래서 연결 지표는 참고 행으로 갔다. 입력 요약의 sha256은 `6b418df5…`이고 출력 `source`에 전체 값이 있다.

**변이 검사.** 변환기를 한 곳씩 망가뜨린 뒤 테스트를 돌리고, 매번 원복했다(`git checkout -- <파일>` 또는 scratchpad 사본 복사, `cmp`로 원복 확인).

| 변이 | 결과 |
|---|---|
| 1.0 반올림 보호 제거 | 1 failed |
| 샘플 모드 허용 | 1 failed |
| 요약 문자열 대조 끔 | 1 failed |
| 폐기율 분모 +1 | 3 failed |
| `failures == []` 조건 제거 | 처음엔 **살아남음** → 테스트 추가(`6b74c63`) 뒤 1 failed |
| `result_status == ok` 조건 제거 | 1 failed |
| generator 미기록도 neumann으로 | 5 failed |
| mock 허용 | 1 failed |
| rule만인데 neumann으로 | 1 failed |
| 일부만 미기록이면 무시 | 1 failed |
| (P6) 미기록인데 시연을 `all`로 | 5 failed |
| (P6) 기록됐는데 시연을 참고로 | 7 failed |
| (P6) "generator 미기록 실행" 표기 빠짐 | 3 failed |

### ② 리포트 카드 재생성

```
$ python -m eval.report_card --inputs $D/score_baseline_freq.json $D/score_astra.json $D/score_rule.json docs/reports/E5-L3b_metrics_e2e.json --out docs/reports/report_card.md --eval-model gpt-6-astra
- 목표 미달 1건: P1 지적 추출 Macro-F1
- 측정 전 5건: P2 근거 연결률 (폐기율 병기), P3 백테스트 Top-3 적중(hit@3), P4 표본 연결, P5 원문 링크, P6 대표 계획 end-to-end 시연
리포트 카드: docs\reports\report_card.md
```

- 카드 머리: 코드 커밋 `cfd947e`(카드 코드 최종판). 머리에 "Neumann 행의 평가 모델: `gpt-6-astra` (명령행 `--eval-model` 값…)"이 있다. 카드에 "달성" 판정은 0건이다.
- 카드 7절에 적힌 입력 sha256:

  | 파일 | sha256 |
  |---|---|
  | `score_baseline_freq.json` | `e9b7e44c…` |
  | `score_astra.json` | `c409bed9…` |
  | `score_rule.json` | `b6d90596…` |
  | `E5-L3b_metrics_e2e.json` | `5e94e8c9…` |

  `sha256sum`으로 잰 값과 같다.
- 한계 4번은 n=5 문구다. 상세 표에 "(기타)"가 없다. `라이브 E2E 화면 위험카드 수 (데모 계획서 합) | Neumann (astra) | 13 (…)`이다.
- score JSON 값 대조:

  | 파일 | Macro-F1 [구간] | Micro-F1 [구간] | n |
  |---|---|---|---|
  | astra | 0.4864 [0.4276, 0.5394] | 0.5644 [0.5125, 0.612] | 148 |
  | 규칙 | 0.3234 [0.2434, 0.3871] | 0.3344 [0.263, 0.4025] | 148 |
  | 빈도 | 0.3308 [0.298, 0.3623] | 0.5379 [0.4871, 0.5861] | 148 |

  카드와 같다.
- 재현: PM 결정 전 판으로 같은 명령을 scratchpad에 다시 돌렸다. 달라지는 줄은 생성 시각·코드 커밋 줄과 출력 경로가 든 재현 명령 줄뿐이었다.

### ③ 한 장 요약

- `docs/reports/metrics_summary.md`에 있는 소수는 모두 score JSON 3개, 라이브 요약, 참조선 0.725 [0.669, 0.772], 목표값에서 온다. 스크립트로 대조했고, 남은 것은 절 번호 `§1.2`·`§2.2`뿐이다.
- PM 결정 반영: P2·P6은 "측정 전" 행에 있다. 43/43·12/12·7/2033과 시연 3/3(generator 미기록 실행)은 3절 "참고"에 있다. README 블록도 둘 다 "측정 전(참고: …)"이다. 백테스트는 "계획 n=5"로 적었다.

### verify

```
$ python scripts/verify.py        # _COMMON.md 환경변수 + NEUMANN_LLM_PROVIDER=mock
1202 passed, 27 skipped in 109.23s (0:01:49)      (P6 반영 뒤 재실행)
보안: 파일 406개
계약: 2개
테스트: 통과
verify 통과
```

## 바꾼 파일

- `scripts/metrics_from_e2e.py`(새 파일)
- `tests/e5/test_metrics_from_e2e.py`(새 파일)
- `eval/report_card.py`(PM 지시: 한계 문구·이름표 / 검증 권고: `--eval-model` 선택 옵션)
- `docs/reports/E5-L3b_metrics_e2e.json`(변환 결과)
- `docs/reports/report_card.md`(재생성)
- `docs/reports/metrics_summary.md`(새 파일)
- `docs/reports/E5-L3b.md`(이 보고서)

`tests/e2e/`·`contracts/`·`data/` 원본과 `tests/e5/test_report_card.py`(E5-L3a 소유)는 건드리지 않았다. 카드 코드 변경에 대한 테스트는 이 과제의 테스트 파일에 넣었다.

## 결정 (스펙이 모호해서 고른 것)

1. **P2 근거 연결률 = 측정 전(PM 결정).**
   - 연결 검사는 화면 실행과 별도로 같은 계획서를 `/premortem`으로 다시 돌린 결과에서 쟀다(E5-L0e2e 결정 1). 요약에 그 실행의 카드 generator가 없다.
   - 처음에는 Neumann 칸에 넣고 "generator 미기록"을 병기했다(`ef60c99`). PM 결정에 따라 참고 행으로 옮겼다(`24b122a`).
   - 규칙은 연결 보고서 경로의 `unknown_generator`와 같은 원칙이다. 한 계획서라도 기록이 없으면 합계 전체를 참고로 둔다. 일부만 약속 칸에 넣지 않는다.
   - `plans[*].linkage.card_generators`가 기록된 요약이면 같은 변환기로 P2·P6이 채워진다(테스트로 고정). **지금 task/E5-L1e2e 요약은 이 키를 기록하지 않는다**(결정 5).
2. **P6 시연도 측정 전(PM 결정, 두 번째).**
   - 처음에는 E2E 테스트 통과 수로 달성에 두고 PM 판단을 요청했다(`22f3b2c`까지).
   - PM이 P2와 같은 규칙으로 정해 `5d59a82`에서 바꿨다.
   - 연결 시스템이 참고(미기록)면 `demo_e2e`도 참고 행으로 간다. detail은 "3/3; generator 미기록 실행"이고, 한계 칸 머리에 "generator 미기록 실행: … 약속 P6 판정에 쓰지 않는 참고값"을 적는다.
   - generator가 기록된 결과는 `all`로 P6을 채운다. rule만 있거나 mixed여도 시연 수는 채운다. 시연은 끝까지 도는지를 재는 지표이고, generator 구성은 P2 쪽에서 드러나기 때문이다.
3. **근거 연결률은 합계 한 행 + 계획서별 detail.** 카드는 (지표, 시스템)당 한 행이다. 발표에는 계획서별 값을 "참고"로 쓰라고 적었다(E6-pres2 검증 권고와 같다).
4. **제품 모델 행.** 카드 코드에 모델 칸이 없다. 그래서 `system` 문자열 "Neumann 제품 기본 모델(gpt-6.1-sol)"로 null 행을 두어 구분했다. 숫자는 만들지 않았다. 참고 행도 같은 방식이다(system 문자열).
5. **`card_generators` 위치 (검증 반영으로 정정).**
   - 변환기가 약속 판정에 읽는 곳은 `plans[*].linkage.card_generators` 하나다. 이름은 `eval.linkage.LinkageReport`의 필드와 같다. 키는 generator만(`"astra"`) 또는 generator:model(`"astra:gpt-6.1-sol"`) 둘 다 받는다.
   - task/E5-L1e2e(`949d628`)에는 이미 요약 형식이 있다.
     - `plans[*].models`: `llm_model`·`card_models`·`card_generators`·`stage_impl` 등
     - 계획서 단위 `card_generators`
     - `linkage`: summary·verdict·linkage_rate·links·cards·reason_counts·contract_valid·drop
   - 하지만 **`linkage.card_generators`는 기록하지 않는다.**
   - 그 브랜치에 커밋된 `docs/reports/E5-L1e2e_live_summary.json`을 파일로만 읽어 변환해 봤다.
     - `--model gpt-6-astra`는 종료 코드 2로 멈춘다(`models.llm_model` = gpt-6.1-sol과 불일치).
     - `--model gpt-6.1-sol`은 통과하지만 연결 지표와 시연은 참고 행으로 남는다.
     - 즉 **그대로 v1 라이브를 돌리면 P2·P6은 "측정 전(참고)"이다.** 그쪽 수치는 그 과제 몫이라 여기 옮기지 않는다.
   - **E5-L1e2e 쪽에 한 줄 추가가 필요하다.** `tests/e2e/test_live.py`가 `check_linkage` 결과로 만드는 `linkage` 딕셔너리에 `card_generators`를 넣으면 된다. 같은 파일의 `C.card_generators(result)` 값을 그대로 넣어도 된다. 코디네이터가 그쪽 빌더에게 요청했다.
   - 계획서 단위 `card_generators`와 `models.card_generators`도 연결 검사와 같은 `/premortem` 결과에서 센 값이다(그 브랜치 `res_dict = result`). 그래도 변환기는 읽지 않는다. 약속 판정 입력을 `linkage` 한 곳으로 정해 두려는 것이다.
   - 이 동작은 테스트 두 개가 고정한다.
     - `test_e5_l1e2e_summary_shape_stays_reference`: 그 모양이면 참고 행으로 남는다.
     - `test_generator_model_keys_accepted_and_model_checked`: 한 줄이 들어오면 채워지고, 카드 모델이 다르면 멈춘다.
6. **변환 결과를 저장소에 커밋.** 카드 재현 표가 저장소 안 파일을 가리킨다. score JSON 3개는 공유 데이터 폴더에 있고 sha256으로 고정했다.
7. **비율 반올림.** 소수 4자리로 적는다. 목표 판정이 바뀌는 방향(1.0으로 올림, 0으로 내림)의 반올림은 막았다.

## 못 한 것

- 카드 7절 "재현"에는 변환 명령이 없다. 이 절은 macro_f1 입력의 명령만 적는다. 변환 명령은 `metrics_summary.md` 6절과 이 보고서에 적었다. `eval/` 수정은 PM 지시(한계 문구·이름표)와 검증 권고(`--eval-model`)만 했다.
- P3·P4·P5와 백테스트·판정 일치율은 입력 지표 파일이 없어 측정 전이다. P4 "표본 연결"은 정의가 저장소 보고서에 확정돼 있지 않다. 그래서 코퍼스 1,128편으로 대신 채우지 않았다.
- 12쪽의 커밋 수·태그·테스트 수는 요약에 넣지 않았다. 07:00 동결 때 다시 센다.
- 검증자 재측정은 아직 하지 않았다(검증 과제 몫).

## 다음 과제에 넘길 것

- **E5-L1e2e(v1 라이브, sol):**
  - **필요: `tests/e2e/test_live.py`의 `linkage` 딕셔너리에 `card_generators` 한 줄**(결정 5). 이것 없이 돌리면 P2·P6은 참고 행으로 남는다. 값은 `C.card_generators(result)`(generator:model 키)여도 된다.
  - 그다음 아래 명령을 돌리면 P2·P6이 채워진다. `--model`은 요약의 `models.llm_model`과 대조한다.
    - `python scripts/metrics_from_e2e.py --summary <v1 요약> --model gpt-6.1-sol --out <json>`
    - `python -m eval.report_card … --eval-model gpt-6.1-sol`
  - 이때 `--product-model`은 주지 않는다. 평가 모델이 곧 제품 모델이기 때문이다.
- **E5 백테스트:** n=5 결과를 `neumann.metrics/1`(`bt_*`)로 내면 카드에 바로 들어간다. 셔플이 없으므로 `bt_specificity`는 null로 둔다.
- **E5 `eval/report_card.py`(선택):** generic 입력에 `model`·`promise_note`를 받는 길을 두고, 재현 절에 generic 입력의 생성 명령(`source`)을 싣는 것.
- **E6 발표 12쪽:** 근거 연결·시연 칸은 "측정 전"으로 둔다. 쓰려면 "참고 10/10 · 13/13 · 20/20, 폐기율 0.34%", "참고 시연 3/3(generator 미기록 실행)"으로 적는다. 모델 표기는 요약 4절 5번을 따른다.

## 커밋

| 해시 | 내용 |
|---|---|
| `7cff2b0` | 변환기 + 테스트 16개 |
| `ef60c99` | P2 칸에 generator 미기록 표시(뒤에 PM 결정으로 대체) |
| `cc40829` | 카드 재생성 + 변환 결과 |
| `5cb77ce` | 출력 LF 고정 + 커밋본 일치 테스트 |
| `c4bd9a1` | 카드 재생성(sha 갱신) |
| `c73104c` | 한 장 요약 |
| `28a1472` | 짧은 보고서(마무리 지시 대응, 이 판으로 대체) |
| `6b74c63` | 테스트 보강(변이 검사에서 살아남은 경우) |
| `e9bcdbd` | 카드 코드: 한계 문구 n=5, `e2e_cards` 이름표(PM 지시) |
| `24b122a` | P2: generator 미기록이면 참고 행(PM 결정) + 테스트 26개 + 변환 결과 재생성 |
| `5436be9` | 카드 재생성(P2 측정 전) |
| `49f64fc` | 한 장 요약 갱신 |
| `22f3b2c` | 정식 보고서(P2 결정 반영판) |
| `5d59a82` | P6도 같은 규칙: generator 미기록이면 참고 행(PM 결정) + 테스트·변환 결과 |
| `9fbff73` | 카드 재생성(P6 측정 전, 달성 0) |
| `849cdaa` | 한 장 요약·보고서 갱신(P6) — 검증 대상 |
| `9fbf231` | 변환기: `--model`을 `models.llm_model`과 대조 |
| `cfd947e` | 카드 코드: `--eval-model`(선택) |
| `f9ded04` | 카드 재생성(`--eval-model gpt-6-astra`) |
| `f936a09` | 변환기: `linkage.card_generators`의 generator:model 키와 카드 모델 대조 |
| (이 커밋) | 검증 반영 문서(요약 분기점·결정 5·다음 과제)·검증 요약 `E5-L3b.verify.md` |

## 검증 반영 (PASS-조건부, 대상 `849cdaa`)

검증 요약은 `docs/reports/E5-L3b.verify.md`에 있다. 코디네이터 전달문을 빌더가 옮겨 적었다.

| # | 검증 지적 | 구분 | 반영 |
|---|---|---|---|
| 1 | 결정 5·다음 과제: E5-L1e2e 요약에 `linkage.card_generators`가 없어 v1을 그대로 돌리면 P2·P6이 측정 전(참고)으로 남는다 | 필수 | 결정 5와 "다음 과제"를 정정했다. 그쪽 커밋 요약으로 변환해 확인했다. 그쪽이 기존 함수로 한 줄을 채워도 되도록 generator:model 키도 받게 했다(`f936a09`) |
| 2 | 요약의 "main `88f1b51`"은 분기점이라고 명시 | 필수 | 요약 머리와 보고서 머리에 "분기점, 지금 main 최신 아님"을 적었다 |
| 3a | 변환기: 요약 `models.llm_model`과 `--model` 대조 | 선택 | 다르면 종료 코드 2, 없으면 조건 칸에 "모델은 명령행 값(요약에 기록 없음)"(`9fbf231`) |
| 3b | 카드 P1 행에 "(gpt-6-astra)" | 선택 | score JSON에 모델 기록이 없다. 그래서 카드에 `--eval-model` 선택 옵션을 두었다. 약속 표 Neumann 행 측정값 옆과 머리에 적는다(`cfd947e`, `f9ded04`). 옵션을 안 주면 출력이 전과 같다 |
| 3c | P6을 "화면 흐름 통과"와 "연결 검사"로 분리 | 제안만 | 아래 "제안" |

추가 변이 검사(매번 원복, `cmp` 확인):

| 변이 | 결과 |
|---|---|
| 모델 불일치 허용 | 1 failed |
| "명령행 값" 표기 빠짐 | 2 failed |
| 평가 모델을 모든 약속 행에 붙임 | 1 failed |
| 평가 모델 표기 안 함 | 1 failed |
| generator:model 키 분리 안 함 | 2 failed |
| 카드 모델 대조 끔 | 1 failed |

```
$ python -m pytest tests/e5/test_metrics_from_e2e.py tests/e5/test_report_card.py -q
61 passed          (이 과제 30 + E5-L3a 카드 테스트 31)
$ python scripts/metrics_from_e2e.py --summary <task/E5-L1e2e:docs/reports/E5-L1e2e_live_summary.json 사본> --model gpt-6-astra --out <scratchpad>
오류: --model 'gpt-6-astra'이 요약의 models.llm_model과 다르다: {'plan.md': 'gpt-6.1-sol', ...}
exit 2
$ python scripts/metrics_from_e2e.py --summary <같은 사본> --model gpt-6.1-sol --out <scratchpad>
linkage_rate · card_pass_rate · drop_rate · demo_e2e → "Neumann 참고(검사 실행 generator 미기록, 약속 판정 제외)"   (값은 그 과제 몫이라 생략)
```

### 제안: P6 분리 (검증 3c, 구현 안 함)

지금 P6(`demo_e2e`)은 한 숫자에 두 가지를 섞는다. 화면 흐름 통과(붙여넣기 → 리포트 화면, 카드·인용·링크·생성 방식·브라우저 오류 0)와 근거 연결 1.0 검사다. 그래서 연결 검사 실행의 generator가 미기록이면 화면 흐름까지 같이 참고로 빠진다.

나누는 안은 이렇다.
- `demo_e2e_ui`/all: 화면 흐름만. generator 기록과 상관없이 약속 P6 후보.
- `demo_e2e`/all: 화면 흐름 + 연결 검사. 지금 규칙 그대로.

이렇게 하면 "시연은 됐다"와 "시연 결과의 근거 연결이 약속 기준으로 확인됐다"를 따로 말할 수 있다. 어느 쪽을 P6으로 볼지는 PM이 정할 일이다. 그래서 이번에는 구현하지 않았다. 구현은 변환기에서 지표 한 줄을 더하고, 카드 `PROMISES`의 P6 `metric_id`를 바꾸는 것이다.

## 마지막 verify

```
$ python scripts/verify.py        # _COMMON.md 환경변수 + NEUMANN_LLM_PROVIDER=mock, 검증 반영 뒤
1206 passed, 27 skipped in 156.01s (0:02:36)
보안: 파일 407개
계약: 2개
테스트: 통과
verify 통과
```
