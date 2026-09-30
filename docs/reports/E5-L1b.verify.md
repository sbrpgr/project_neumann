**PASS**

# E5-L1b 검증 보고서 (검증자: Claude Sonnet 5.5, 빌더 claude-opus-5.5)

- 대상: 브랜치 `task/E5-L1b` (worktree `.claude/worktrees/s2-E5-L1b`, 마지막 커밋 `767637f`, 작업 트리 깨끗)
- 검증 시각: 2026-09-30. 실제 OpenAI 호출 0회(재계산은 전부 캐시·저장 파일로만), 코드·git 쓰기 없음. 임시 산출은 `C:/Users/User/AppData/Local/Temp/v_e5l1b`(검증 뒤 삭제)
- 판정 요약: 발표 숫자 astra 0.4864 [0.4276, 0.5394] / 규칙 0.3234 [0.2434, 0.3871]는 저장된 예측 파일에서 그대로 재현된다. 사전 고정 순서는 커밋 시각과 파일·캐시 시각으로 성립하고, 골드가 튜닝에 흘러들 경로가 없다. 병합 전 반드시 고칠 것은 없다(아래 "고칠 것"은 표기 정밀도 수준)

## 완료 기준·확인 항목 결과

| # | 항목 | 실행한 것 | 실제 결과 | 판정 |
|---|---|---|---|---|
| 1a | 채점 재현(astra) | `python -m eval.macro_f1 --pred pred_astra_gold.jsonl --gold disapere_gold.jsonl --out <Temp>` | Macro 0.4864 [0.4276, 0.5394], Micro 0.5644 [0.5125, 0.6120], n=148. 새 결과 JSON과 저장된 `score_astra.json`을 비교하면 `created_at`만 다르다(구간 포함 전 필드 동일, 시드 20260930) | 통과 |
| 1b | 채점 재현(규칙) | 같은 방법 | Macro 0.3234 [0.2434, 0.3871], Micro 0.3344 [0.2630, 0.4025]. `created_at` 외 전 필드 동일 | 통과 |
| 1c | 채점기와 무관한 독립 재계산 | 내 코드로 pred+gold에서 P/R/F1·Macro·Micro를 다시 계산 | astra 0.4864 / 0.5644 (TP160 FP204 FN43), 규칙 0.3234 / 0.3344 (TP52 FP56 FN151), 빈도 기준선 0.3308 / 0.5379. 채점 클래스 R1·R2·R5·R6·R7, 제외 R3·R4·R8·R9 | 통과 |
| 1d | 예측 파일 sha256 | `sha256sum` | `pred_astra_gold.jsonl` `711425e4e6ff5e18…385eb`, `pred_rule_gold.jsonl` `13bb237817a97fd5…1de48`, 골드 `ad25cb4ad5759350…f6b74c`. 세 값 모두 score JSON의 `pred_sha256`·`gold_sha256`와 같다(E5-L1a 골드와도 같음) | 통과 |
| 1e | 예측 재생성 | `predict --split gold --generator {astra,rule} --out <Temp>`(커밋된 FROZEN만 사용) | 두 파일의 sha256이 저장본과 같다. 독립 집계(FROZEN 규칙을 내 코드로 raw에 적용)도 148건 모두 일치 | 통과 |
| 2a | 사전 고정 커밋 순서 | `git log --format='%h %ci %s' main..task/E5-L1b`, reflog | 1f452cd 19:14:48 (격자 24개·선택 규칙·`FROZEN=None`) → 6c84984 19:15:54 → e801a82 19:19:29 (E3-L0 재병합) → **c4e9329 19:20:26 (FROZEN 채움, 이 커밋은 `FROZEN` 값 5줄만 바꿈, 격자·선택 규칙 불변)** → 767637f 19:25:23 (골드 결과·보고서). author·committer 시각 동일, reflog가 같은 순서 | 통과 |
| 2b | 파일·캐시 시각 | `stats.json`, 캐시 mtime, 산출물 mtime | dev astra 추출 19:14:52~19:19:09, dev 규칙 19:14:54, dev 튜닝 결과 규칙 19:14:57·astra 19:19:16 → 모두 격자 커밋(19:14:48) 뒤. 골드 astra 추출 19:20:35~19:22:22(FROZEN 커밋 9초 뒤), 골드 규칙 19:22:22, 골드 예측 19:22:27/28, 채점 19:22:28/29. 캐시 518개 = dev 369 + 골드 149로 정확히 떨어지고, 19:20:00 이전 369개·이후 149개 | 통과 |
| 2c | 골드 재채점·재추출 흔적 | `data/`·Temp 전체에서 `pred_*_gold` 참조 파일 검색, 캐시 개수, `cached_batches` | 골드 점수 파일은 `score_astra.json`·`score_rule.json` 각 1개(created_at 단일), 골드 stats `cached_batches=0`·호출 149. 캐시 수가 369+149와 정확히 같아 골드를 두 번 부른 흔적 없음 | 통과 |
| 2d | 골드가 튜닝에 들어가는 경로 | 코드 읽기 + 실행 | `load_docs`는 문장·본문만 읽고 라벨 필드를 담지 않음. `tune`은 `load_dev_labels(disapere_dev.jsonl)`만 사용하고, 골드 파일을 주면 `ValueError: dev가 아닌 행(role='gold')`(실제 골드 파일로 실행해 확인). `predict --split gold --config`는 거부. dev∩gold = 0, dev 358건 role=dev·주석자 1명 | 통과 |
| 2e | 튜닝 결과 재현 | 내 코드로 격자 24개 dev 재계산 | astra 선택 = negative·하한 0·1문장 (dev Macro 0.5553, Micro 0.6122), 규칙 선택 = negative+neutral·하한 0·1문장 (0.2755 / 0.3026). 커밋된 `FROZEN`과 같다. 보고서의 격자 값(astra 0.7→0.5546, 0.8→0.5527, 0.9→0.5320, 2문장 0.42~0.515, 규칙 하한 0.7 이상 0.08 이하)도 `tune_*_dev.json`과 일치 | 통과 |
| 3a | 예측이 실제 astra 결과인가(캐시 재계산) | 재병합된 HEAD 코드로 `extract_astra`를 돌리되 LLM 자리에 호출 시 예외를 내는 대체 객체를 넣음 | 골드 148건·dev 358건 모두 raw 파일과 **행 단위 동일**, 호출 시도 0회(캐시 149/369묶음 전부 적중). 추출기 지문 `7f1d7b247748d15d`가 캐시 폴더 이름과 일치 | 통과 |
| 3b | generator·강등·mock | raw·pred 집계 | astra 골드 예측 generator astra 148/148, model `gpt-6-astra`, status ok 148, 강등 사유 0, 지적 1,370건 전부 gen=astra. 규칙 예측 generator rule 148/148(지적 180건 전부 rule, `neumann.index.taxonomy:tag_excerpts`). 예측·raw 파일에 "mock" 0건, 캐시 518개 전부 model `gpt-6-astra`·판 `extract_issues.v1`(E3 캐시는 openai일 때만 쓰므로 mock은 캐시에 못 들어감) | 통과 |
| 3c | 호출 통계 | `raw_astra_gold.stats.json` | 요청 149, 실패 0, 재시도 0, 검증 폐기 2건(out_of_range), 평균 지연 9.74s, 토큰 입력 218,074/출력 66,773. 골드 캐시 파일이 106초 창(19:20:36~19:22:22)에 퍼져 있어 병렬 16 × 평균 9.7초와 맞는다. (호출이 실제 OpenAI로 나갔다는 직접 증거는 없고 이런 간접 증거뿐이다 — 캐시 재호출 금지 조건상 한계) | 통과(간접) |
| 4a | 제외 클래스 규칙 = E5-L1a | `eval/macro_f1.py`·`disapere_gold.py`·`baseline_freq.py` 변경 여부, 채점 출력 | 세 파일 모두 main과 동일(브랜치가 안 건드림). 제외 R3·R4·R8·R9(골드 support 0), 제외 클래스 FP는 Micro에만 반영(astra R3 2·R4 2, 규칙 R3 2·R4 9 — 보고서와 일치). R0은 채점 제외 0건 | 통과 |
| 4b | 한계 서술 ↔ 숫자 | dev/골드 파일로 재계산 | 모두 일치. Micro 구간 겹침: astra [0.5125, 0.6120] ∩ 기준선 [0.4871, 0.5861] 겹침. Macro는 astra 하한 0.4276 > 기준선 상한 0.3623, 사람 상한과 차 0.2386(≈0.24). 규칙 Macro 구간은 기준선과 겹침. 골드 no_risk 35건 중 astra 빈 예측 5건(코드 낸 것 30건), 규칙 19건. 리뷰당 정답 코드 dev 1.84·골드 1.37, astra 예측 골드 2.46·dev 2.70, Micro P 0.4396·R 0.7882. R7 dev 지적 322건 중 substance·negative 29%·none 18%·soundness 17%, R5 231건 중 replicability 27%·clarity 24%, R2 909건 중 meaningful-comparison·negative 8.3%(75건) | 통과 |
| 4c | dev>골드 원인(검증자 진단) | 골드 파일의 주석자별 라벨로 astra 예측을 다시 채점(진단 전용, 튜닝·보고 숫자 아님) | 각 주석자 라벨 기준(409쌍) Macro 0.5486, 주석자 1명 라벨 기준(148건) 0.5760. dev(1인 라벨) 0.5553과 같은 수준이라 하락 원인이 dev 과적합이 아니라 "1인 라벨 vs 과반 합의" 라벨 밀도 차이라는 보고서 설명(한계 2)을 지지한다. R1 정밀도가 dev 0.62 → 골드 0.39로 가장 크게 하락(R1 유병률 dev 51% → 골드 28%). 선택된 집계 규칙이 격자 평탄 구간의 첫 점이라 튜닝 자체는 거의 무효과 | 지지 |
| 5a | `pytest tests/e5 -q -k disapere_extract` | 실행(`NEUMANN_LIVE_TESTS` 미설정) | 16 passed, 1 skipped(실제 API 테스트는 조건부 skip), 74 deselected. `-p no:cacheprovider`로 돌려 worktree에 파일 안 남김 | 통과 |
| 5b | `python scripts/verify.py` | 실행 | 547 passed, 10 skipped, 보안 파일 217개, 계약 2개, verify 통과. (보고서의 534/23은 `NEUMANN_RAW_DIR` 없이 돌린 값으로 보인다 — 원본이 있으면 skip이 줄어든다. 환경 차이일 뿐) | 통과 |
| 5c | 소유 밖 변경 | `git diff f636fad task/E5-L1b --stat`(진짜 병합 기준점), 브랜치 전용 커밋 4개의 파일 목록 | 브랜치 전용 커밋 변경 파일: `eval/disapere_extract.py`, `tests/e5/test_disapere_extract.py`, `docs/reports/E5-L1b.md`뿐. 나머지는 E3-L0 병합분(`src/neumann/analyze/*`, `llm.py`, `pipeline.py`, `tests/e3/*`, `docs/reports/E3-L0.md`)으로 main과 내용 동일(main 대비 diff 비어 있음). `contracts/`·`src/neumann/models.py`·`eval/macro_f1.py` 변경 없음, 데이터·비밀값·`.env` 추가 없음. (`git diff main...task/E5-L1b`는 병합 기준점이 여러 개라 main이 앞서간 E3-L1a·E5 백테스트 파일까지 "변경"으로 보이는 착시가 있음 — 무시) | 통과 |
| 5d | 예측 형식·정직성 | 코드 읽기, 테스트 목록 | 인용 = 원문 오프셋 슬라이스(`Excerpt.from_source`, 반복 문장·본문 해시 불일치 테스트 있음). 실패 묶음은 규칙으로 강등하고 그 리뷰를 `generator=rule`·`status=degraded`로 표기(mock 테스트 있음, 이번 실행 0건). 규칙 예측은 항상 rule로 표기 | 통과 |

## 발표에 쓸 숫자(재현 확인분)

| 시스템 | Macro-F1 [95%] | Micro-F1 [95%] | n |
|---|---|---|---|
| 사람 간 상한(합의 골드, 외부 실측) | 0.725 [0.669, 0.772] | — | 29리뷰 LOO |
| astra(EX-4, gpt-6-astra) | **0.4864 [0.4276, 0.5394]** | 0.5644 [0.5125, 0.6120] | 148 |
| 비상 규칙 태거 | 0.3234 [0.2434, 0.3871] | 0.3344 [0.2630, 0.4025] | 148 |
| 빈도 기준선(안 읽음) | 0.3308 [0.2980, 0.3623] | 0.5379 [0.4871, 0.5861] | 148 |

## 고칠 것 (병합 차단 아님, 표기 정밀도)

1. 보고서 §2 표의 1번 행 "dev 추출 전"은 정확하지 않다. 격자·선택 규칙 커밋(19:14:48)보다 dev 앞 3건 astra 스모크(캐시 19:14:31~38)가 10~17초 먼저 돌았다. 점수는 안 냈고 dev 3건이라 규칙 고정의 순서 주장에는 영향이 없지만, "dev 점수를 보기 전"으로 고치는 편이 정확하다.
2. 발표 각주에 넣을 문구: 지시문은 E3 제품 v1 그대로(스펙의 "지시문 조정"은 하지 않음, 결정 1), dev 튜닝은 집계 규칙뿐이고 선택된 값이 평탄 구간 첫 점이라 사실상 무튜닝이다. 골드 정확히 1회 채점, LLM 호출 1회 실행(반복 분산 미측정).
3. 발표 시 "astra > 기준선"은 Macro에서만 주장하고 Micro는 "기준선과 구별 안 됨"으로 적을 것(보고서가 이미 그렇게 적음). astra − 기준선의 대응표본 차이 검정은 하지 않았으므로 "구간이 안 겹친다" 수준까지만 말한다.
4. (선택) 4c 진단(주석자별 라벨로 0.55~0.58)을 한계 2의 근거로 각주에 넣으려면 "골드를 분석에만 사용, 튜닝 없음, 사후 분석"이라고 명시하고 이번 채점과 별도 표기한다.
5. (경미) `extract --split gold`는 FROZEN이 없어도 막히지 않는다(가드는 `predict`에만 있음). 이번 순서는 커밋·캐시 시각으로 입증되지만, 이후 재사용 시 추출 단계에도 같은 가드를 두면 더 견고하다. 첫 커밋 534줄은 `_COMMON.md`의 "수백 줄 이내"에 걸치는 크기.

## 검증자가 한 골드 재채점 공개

이 검증에서 골드 148건을 `eval.macro_f1`로 2회(astra·규칙), 독립 코드로 추가 재계산했고 4c 진단도 골드 라벨을 읽었다. 전부 읽기 전용 재현·진단이며 결과 파일은 Temp에만 썼고(검증 후 삭제) 빌더의 채점 기록·튜닝과 무관하다.
