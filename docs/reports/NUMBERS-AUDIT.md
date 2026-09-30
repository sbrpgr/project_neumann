# NUMBERS-AUDIT — E6-pres5 발표 수치 감사

- 기준 브랜치 `codex/numbers-audit`, 기반 커밋 `87d3597`(E6-pres5). 감사 시각 2026-10-01T04:19:38+09:00.
- 핵심 성능 수치의 산술은 v3 기본 결과와 일치한다. **precision@3 3/15=20.0%와 A-rate 3/4=75.0%를 섞으면 안 된다.** 기준선은 4/15=26.7%, hit@3은 Neumann 1/5=0.2 / 기준선 3/5=0.6이다. 빈 슬롯 11개와 위험 0개인 논문 3편을 빼지 않았다.
- **발표 표시 보강:** v1 `2/4 통과`에는 범위 밖 입력 1건이 포함된다. 시연 계획서만 보면 **1/3 통과**다. v0 5/5는 데모 3건 + 차단 1건 + 별도 API 근거 검사 1건의 검사 수이며, 결과 패키지·최종 초안까지의 전체 흐름 성공을 뜻하지 않는다.
- **원천 부재·미측정:** eLife 24,278편, Europe PMC 81,693편, 전체 6샤드 823,170건, 중복을 제거한 총량 10만 편 이상, 월 서버비와 분석 200원 상한. 사전 조사 인용·추정은 현장 실측과 구분한다. 17쪽 이미지에는 구버전 일정, 백테스트 10~15편과 데이터 2,000편 이상 목표가 남았다.
- 산출물: `NUMBERS-AUDIT.md`, `numbers_frozen.candidate.json`(전체 스키마 유지, 자동 반영 금지), `NUMBERS-AUDIT.recomputed.json`(재계산값·원천해시, 원문/개인정보/실행로그 없음). 기존 JSON·코드·PPTX를 수정하지 않았다.
- 빌더: Codex(GPT-6 기반). 세부 런타임 모델 ID는 이 세션에 노출되지 않아 특정 세부 모델로 단정하지 않았다.

## 범위와 원천 표기

`numbers_frozen.json`, `data/deck/build/pres5_content.py`·`pres5_build.py`를 읽었다. 생성된 `content.json`, PPTX 17장의 본문·표·노트와 17쪽 일정 이미지까지 읽기 전용으로 검사했다. 프레젠테이션 스킬의 읽기 전용 지침을 적용했다. 표의 쪽 번호는 **최종 17장 번호**이며, 생성 코드의 옛 17쪽은 최종 16쪽, 옛 18쪽은 최종 17쪽이다. 좌표·crop·폰트 크기·EMU·쪽 번호·절 번호·모델 버전·위험 및 심각도 코드·연도는 형식 또는 식별자이므로 성능 대조 대상에서 제외했다. 1956년은 기획서의 역사 인용이며, 외부 논문을 새로 검증하지 않았다.

표의 원천 약칭은 다음의 실제 파일을 뜻한다. 원본은 읽기만 했다.

- `RAW` = `C:/Users/User/Desktop/노이만_본선자료/공개자료/data/`. ResearchArcade papers는 `researcharcade/papers/train-00000-of-00001.parquet`, reviews는 `researcharcade/reviews/train-00000-of-00006.parquet`·`train-00001-of-00006.parquet`다. 전체 학회와 ICLR 2024·2025 범위를 구분했다. 노트 title만 세면 공식 리뷰 53,532건·답변 149,857건이다. 역할 필터까지 적용해야 53,529건·149,854건이 된다. 원본 신원 값은 산출물에 저장하지 않았다.
- `PLAN` = `C:/Users/User/Desktop/노이만_본선자료/기획서/`, 기준 `00_구현_계획서.md`, 보조 `03_데이터_수집_명세.md`·`04_평가_명세.md`·`07_데이터_활용과_확장_잠재력.md`·`08_발표_질의응답.md`. 전재하지 않았다.
- `V3ANS` = `data/eval/judge_n5v3/answers/J1/·J2/·J3/env_*.json`(15개), `V3KEY` = `data/eval/judge_n5v3_key/pairing.json`. v2는 `V2ANS`=`data/eval/judge_n5/answers/…`, `V2KEY`=`data/eval/judge_n5_key/pairing.json`.
- `POSTANS` = `data/eval/judge_n5_posthoc/answers/J1/·J2/·J3/env_f1938f8c91b7.json`, `POSTKEY` = `data/eval/judge_n5_posthoc_key/pairing.json`.
- `V0` = `docs/reports/E5-L0e2e_live_summary.json`. `V1` = **커밋 949d628의** `docs/reports/E5-L1e2e_live_summary.json`(`git show`로 읽음). 공유 `data/deck/build/src_v1_949d628/`에도 같은 실행의 요약·화면이 있다. 이후 덮어쓴 결과와 섞지 않는다.
- 상대 경로 `data/`는 공유 `C:/Users/User/Desktop/project_neumann/data/`, `docs/`·`src/`는 이 worktree다.

## 대조표

**불일치·원천 부재·재계산 불가·대상을 오해하기 쉬운 표시는 행 전체를 굵게 표시했다.** 일치(인용/계획)는 현장 실측 확정이라는 뜻이 아니다. 미측정 공란은 유지한다.

| 슬라이드 | 항목 | 현재 값 | 재계산 값 | 원천 파일 | 필드·계산 | 일치 여부 |
|---|---|---|---|---|---|---|
| 3·10 | ICLR 2024·2025 심사 논문 | 13,433편 | 13,433편 | RAW papers + reviews 샤드 0·1 | venue 필터, 공식 리뷰 replyto 고유 논문 | 일치 |
| 3 | 채택 | 5,605편·42% | 5,605 / (13,433−22) = 41.79% → 42% | RAW papers + reviews | paper_decision; 데스크 리젝트 22 별도 | 일치 |
| 3 | 거절 | 7,806편·58% | 7,806 / (13,433−22) = 58.21% → 58% | RAW papers + reviews | Rejected_Submission; 데스크 리젝트 제외 | 일치 |
| 3 | 데스크 리젝트 | 22편 별도 | 22편; 5,605+7,806+22=13,433 | RAW papers | Desk_Rejected_Submission | 일치 |
| 3·10 | 공식 심사평 | 53,529건 | 53,529건 | RAW reviews 0·1 | ICLR 2024·2025, title Official Review*, writer Reviewer_* | 일치 |
| 3·10 | 저자 답변 | 149,854건 | 149,854건 | RAW reviews 0·1 | ICLR 2024·2025, writer Authors | 일치 |
| 3·5·10 | 철회·정정 기록 | 72,684건 | CSV 72,684행 | RAW retraction_watch/retraction_watch.csv | 헤더 제외 레코드 수; 우려·복원도 포함 | 일치 |
| 5 | OpenReview 공개 미러 논문 | 49,418편 | 49,418행 | RAW researcharcade/papers/*.parquet | parquet metadata.num_rows | 일치 |
| **5** | **OpenReview 공개 미러 기록** | **823,170건** | **현존 2샤드 274,390행; 6×137,195=823,170은 외삽** | **PLAN 03·07 + RAW reviews 0·1** | **6샤드 중 4개 미반입** | **원천 부재(6샤드 전수 재계산 불가)** |
| **5** | **eLife 공개 심사 논문** | **24,278편** | **현장 원천 전체 목록 없음** | **PLAN 08 Q&A 숫자표** | **24,278 인용, 전체 목록·집계 JSON 없음** | **원천 부재(사전 조사 인용)** |
| **5** | **Europe PMC 리뷰 연결** | **약 81,693편** | **원천 조회 결과 없음; 부분집합 합산으로 산출 불가** | **PLAN 03·07** | **81,693 인용; PLOS/eLife/F1000 겹침** | **원천 부재(사전 조사 인용)** |
| 5·10 | DISAPERE 문장 | 9,946문장 | 5,216+1,484+3,246=9,946 | RAW disapere/DISAPERE.zip | final_dataset train/dev/test review_sentences 길이 합 | 일치 |
| **5** | **공개 심사 기록 총량** | **10만 편 이상** | **서로 다른 코퍼스의 고유 논문 합집합 미계산** | **PLAN 07 + content.json + PPTX 5** | **중복 제거 없는 총량** | **검증 불가(합집합 원장 없음)** |
| 9·10 | bge-m3 차원 | 1,024차원 | 1,024차원 | data/index/manifest.json | dense_dim, backend.dense_dim | 일치 |
| 10·14 | 현장 코퍼스 논문 | 1,128 | 1,128 | data/processed/works.jsonl·reviews.jsonl / data/index/excerpts.jsonl | works.jsonl 행 수 | 일치 |
| 10 | 심사평 합 | 5,366 | 5,366 | data/processed/works.jsonl·reviews.jsonl / data/index/excerpts.jsonl | reviews.jsonl 행 수 | 일치 |
| 10 | 공식 리뷰 | 4,298 | 4,298 | data/processed/works.jsonl·reviews.jsonl / data/index/excerpts.jsonl | kind=official_review | 일치 |
| 10 | 메타리뷰 | 1,068 | 1,068 | data/processed/works.jsonl·reviews.jsonl / data/index/excerpts.jsonl | kind=meta_review | 일치 |
| 10 | 색인 문장 | 133,769 | 133,769 | data/processed/works.jsonl·reviews.jsonl / data/index/excerpts.jsonl | excerpts.jsonl 행 수 | 일치 |
| 10 | 색인 GPU 재빌드 | 약 77초 | 76.578초 → 77초 | data/index/manifest.json | build_seconds; 기존 실행 인용(재빌드 안 함) | 일치 |
| 10 노트 | 키워드 분야 | 3개 | materials/protein/physics 3개 | data/processed/corpus_manifest.json | keywords.fields 키 수 | 일치 |
| 10 | 예시 논문의 기록 | 공식 4·메타 1·결정 1 | 4·1·1 | RAW reviews 0·1 | replyto=j7OAzA9DQd, title 유형 집계 | 일치 |
| 10 | 예시 점수 | 평점 3·건전성 2·확신도 4 | 3·2·4 | RAW reviews 0·1 | review ZQI2Fe4Q5j, content.Rating/Soundness/Confidence | 일치 |
| 6·8·9·10 | 위험 유형 | R0~R9 / R1~R9 | 전체 10개, 비위험 R0 제외 위험 9개 | src/neumann/index/taxonomy.py + eval/macro_f1.py | 식별자이며 성능 숫자 아님(클래스 정의) | 일치 |
| 9·15 | 분석 단계 | 10단계 | plan_normalize부터 semantic_validate까지 10키 | git:949d628:E5-L1e2e_live_summary.json | plans.plan.md.timings.result_stage_s | 일치 |
| 9 | 카드 뒤 병렬 구간 | 3단계 | expected_review / checklist / semantic_validate 3개 | docs/reports/E3-L1y.md | v1 병렬 구간(의존성 때문에 모두 완전 동시 아님) | 일치 |
| 9·9 노트 | 모의 지연 순차→병렬 | 54.1초→42.0초 | 기존 측정 54.11→42.02, 반올림 일치 | docs/reports/E3-L1y.md | 전체 total_s 행; 단계합 54.02 / 중첩 고려 약42.01+오버헤드 | 일치 |
| 9·9 노트 | v1 시연 화면 시간 | 85·141·155초 | 85.017·140.757·154.686 → 85·141·155 | V1 | plans.*.timings.ui_total_s | 일치 |
| 11·11 노트 | 유사 연구 | 10편 | 화면 표 순번 1~10, 10행 | data/deck/build/src_v1_949d628/E5-L1e2e_live_plan_report.png | 유사 연구 목록 수동 계수; 요약 JSON에는 검색 편수 없음 | 일치(화면 계수) |
| 11·11 노트 | 배터리 예시 카드 | 5장 | 5장 | V1 | plans.plan.md.n_cards | 일치 |
| 11·11 노트 | 배터리 예시 시간 | 85.0초 / 85초 | 85.017 → 85.0초 / 85초 | V1 | plans.plan.md.timings.ui_total_s | 일치 |
| 11 노트 | 예상 심사평·근거 번호 | 8문장·23개 | 8·23 | V1 | plans.plan.md.v1.view.review.sentences/cites | 일치 |
| 11 노트 | 1위 위험 | R2 | 상위 카드 R2(화면 01), 위험코드 식별자 | data/deck/build/src_v1_949d628/E5-L1e2e_live_plan_report.png | 카드 01, 정량 성능 아님 | 일치(화면 확인) |
| 12 | 백테스트 표본 | n=5 | 앞 5 work_id, 5편 모두 포함 | data/eval/backtest_sample.json + V3KEY | items[:5], risksets | 일치 |
| 12 | 기준선 precision@3 | 26.7% | 4/15=26.6667% →26.7% | V3ANS + V3KEY | grade=A / (5편×3슬롯) | 일치 |
| 12 | 기준선 precision@3 구간 | [6.7,46.7] | [0.0667,0.4667]×100 →[6.7,46.7] | V3ANS + V3KEY | 논문 재표집 2,000회·seed 20260930·linear percentile | 일치 |
| 12 | 기준선 A 슬롯 | A 4/15자리 | A=4 / 15슬롯 | V3ANS + V3KEY | 복원된 5×3 등급 | 일치 |
| 12 | 기준선 A-rate | 낸 위험 중 A 4/15 | 4/15=26.7% | V3ANS + V3KEY | A / 낸 위험 15개 | 일치 |
| 12 | 기준선 hit@3 | 0.6 | A 있는 논문 3/5=0.6 | V3ANS + V3KEY | 논문별 any(A) | 일치 |
| 12 | Neumann precision@3 | 20.0% | 3/15=20.0% | V3ANS + V3KEY | A / (5편×3슬롯), 빈 슬롯도 분모에 포함 | 일치 |
| 12 | Neumann precision@3 구간 | [0.0,60.0] | [0.0000,0.6000]×100 | V3ANS + V3KEY | 논문 재표집 2,000회·seed 20260930 | 일치 |
| 12 | Neumann A 슬롯·빈 슬롯 | A 3/15자리(빈 11) | 3A+1B+11빈=15슬롯 | V3ANS + V3KEY | grades 길이 3 고정, None=11 | 일치 |
| 12 | Neumann A-rate | 낸 위험 중 A 3/4 | 3/4=75.0%; precision@3과 다름 | V3ANS + V3KEY | A / 낸 위험 4개 | 일치 |
| 12 | Neumann hit@3 / 목표표 | 0.2 / 20% [0,60] | A 있는 논문 1/5=0.2, CI [0,0.6] | V3ANS + V3KEY | 논문별 any(A); 왼쪽 표는 hit@3 | 일치 |
| 12 | 오탐률 | 기준선·Neumann 0%, C 0/15 | 둘 다 0/15=0% | V3ANS + V3KEY | C / (5×3); 빈 슬롯은 C가 아님 | 일치 |
| 12 | 근거율 | 기준선 0/15=0%, Neumann 4/4=100% | 0/15,4/4 | data/eval/riskset_*.sol.first5.jsonl | risks[].evidence_ok; 구조 검사값, A 적중과 별개 | 일치 |
| 12 | 위험 0개 | 3편 | SFCH / o1Iii / ihHeq 3편 | data/eval/riskset_neumann.sol.first5.jsonl | len(risks)=0; status ok여도 실패로 포함 | 일치 |
| 12 | 표본 구성 | 거절 3·채택 2·PDE 4 | 3·2·physics_pde_climate 4 | data/eval/backtest_sample.json | items[:5].decision/fields; 분야는 중복 가능 | 일치 |
| 12 | 300자 미만 입력 | 3편·153·281·287자 | len(plan_text)=153·281·287,3편 | data/eval/backtest_plans.jsonl | 앞5 work_id만 선택, 공백 포함 len | 일치 |
| **12** | **입력 거절 경계** | **300자** | **대표 결정 300; 감사 브랜치는 옛40, 현재 main은300** | **docs/decisions.md 23:1x / git:main:src/neumann/analyze/fitness.py** | **MIN_CHARS; 실행본 버전 확인 필요** | **표시 보강(브랜치·실서비스 버전 구분)** |
| 12 | 비용에 따른 표본 축소 | 30→15→5 | sample.n=30,reduced_n=15,v3.work_ids=5 | data/eval/backtest_sample.json + V3KEY | n / reduced_n / work_ids 길이 | 일치 |
| 12 | 판정자 | Claude Sonnet 3명 | J1/J2/J3, 각5봉투=15답변 | V3ANS | judge_model=claude-sonnet-5-5; 실제 심사위원 신원 아님 | 일치 |
| **12** | **블라인드 단서 제거** | **2건** | **조사·근거출처문장 2종 제거, 3차가 기본** | **docs/reports/E5-L2b_n5_results.md + V2/V3 envelopes** | **블라인드 절; 2건은 레코드 수가 아니라 단서 유형 수** | **표시 보강(2건→2종 권고)** |
| 12 | 3명 일치율 | 0.947 | 18/19=0.947368… →0.947(94.7%) | V3ANS + V3KEY | risk별 세 grade 동일 여부 | 일치 |
| 12 | v2 민감도 A-rate | 4/4 | 4/4=100%, v3 3/4와 구분 | data/eval/judge_n5/answers + judge_n5_key/pairing.json | v2 다수결 A | 일치 |
| 12 | v2 민감도 precision@3 / hit@3 | 0.267 / 0.4 | 4/15=0.266667 / 2/5=0.4 | V2ANS + V2KEY | 빈 슬롯 포함; 주 결과로 대체 금지 | 일치 |
| 12 | 사후 기준선 | A 1/3·같은1편 hit@3 1.0 | A1+B2, 1편 any(A)=1 | POSTANS + POSTKEY | 사후 별도 봉투 SFCHv2G33F | 일치 |
| 12 | 사후 Neumann | B 1/1·1/3편 카드1장·hit@3 0 | 3편 재실행 [1,0,0], 그1장 B, hit=0 | data/eval/riskset_neumann.sol.posthoc_fix3.jsonl + POSTANS | 위험수 [1,0,0]; 판정표는 위험 나온1편만, 재실행 모수3 | 일치 |
| 12 | 골드 심사평 | 148건(과반 합의) | 148고유 review_id | data/eval/disapere_gold.jsonl | 행 수 / resolution=majority_vote | 일치 |
| 12 | 지적 추출 Macro-F1 | 0.4864 | 0.4864 | data/eval/disapere_gold.jsonl + pred_astra_gold.jsonl | support>0 R1/R2/R5/R6/R7 F1 평균 | 일치 |
| 12 | Macro-F1 구간 | [0.4276,0.5394] | [0.4276,0.5394] | 동일 gold/pred JSONL | 리뷰 재표집2,000회, seed20260930, C* 재계산 | 일치 |
| 12 | 비상 규칙 Macro-F1 | 0.3234 | 0.3234 | data/eval/disapere_gold.jsonl + pred_rule_gold.jsonl | support>0 클래스 F1 평균 | 일치 |
| 12 | 빈도 기준선 Macro-F1 | 0.3308 | 0.3308 | data/eval/disapere_gold.jsonl + pred_baseline_freq.jsonl | support>0 클래스 F1 평균 | 일치 |
| 12 | 사람 상한 | 0.725 | 기획 문서 인용0.725; 새 인간 평가 안 함 | PLAN 04 §1.2 / score_astra.json reference_lines | 29리뷰LOO 외부 인용, 우리 성능 아님 | 일치(인용값, 독립 재현 안 함) |
| 12 | 골드 채점 횟수 | 1회 | 과거 모델 추출1회; 감사는 같은 예측의 산술 재계산 | docs/reports/E5-L1b.md + data/eval/raw_astra_gold.stats.json | 과거 실행 보고, 신규 API 호출 없음 | 일치(실행 보고 인용) |
| 12 | 목표치 | 연결100%·Macro≥0.70·hit≥50%·연결≥300편·시연3건 | 신청서 목표 그대로, 백테스트 hit20%로 미달 | PLAN 00·04 / docs/reports/metrics_summary.md | P1~P6; 목표와 실측 구분 | 일치 |
| **12·13** | **v0 API 근거 대조** | **10/10·13/13·20/20·100%** | **합43/43, 각1.0** | **V0** | **plans.*.linkage.links; 화면과 다른 API 호출** | **표시 보강(generator 미기록 참고값)** |
| 12 | v0 폐기율 | 0.2~0.6% | 1/643=0.1555%,2/701=0.2853%,4/689=0.5806% →0.2~0.6% | V0 | linkage.summary; 전체7/2033=0.3443% | 일치 |
| **12** | **v1 API 근거 대조** | **19/19·28/28·27/27·100%** | **합74/74, 각1.0** | **V1** | **linkage.links; API 카드5·7·8, 화면5·7·7** | **표시 보강(API와 화면을 동일 실행으로 오해 금지)** |
| 12 | v1 폐기율 | 0.6~1.4% | 4/636=0.6289%,9/623=1.4446%,9/753=1.1952% →0.6~1.4% | V1 | linkage.drop.dropped/total; 전체22/2012=1.0934% | 일치 |
| **12** | **v0 데모·라이브 검사** | **데모3건·5/5** | **데모3/3 + 차단1/1 + 별도 연결검사1개=5검사** | **V0 + tests/e2e/test_live.py + metrics_summary.md** | **failure[] 없음, 검사5개와 데모3편은 모수 다름** | **표시 보강(v0 참고, 전체 흐름·ZIP 완료 아님)** |
| 12 | v1 시연 카드 | 3건·5·7·7장 | 화면3편 카드5·7·7 | V1 | plan/protein/neural n_cards; API 재실행은5·7·8 | 일치 |
| **12** | **v1 통과** | **판정4건 중2건 통과** | **시연3편 중1편 + 무관입력1편 = 전체4편 중2편** | **V1** | **plans.*.failures==[]; 차단은 성공 시연이 아님** | **표시 보강(시연1/3·전체2/4를 함께 표기)** |
| 13 | 무관 입력 차단 | 1/1 | negative_recipe.md 실패목록0·카드0=1/1 | V0 | negative_recipe.md n_cards/failures; 단일실행 | 일치 |
| 12 | v0 도달 시각 | 19:19 | taggerdate 2026-09-30 19:19:04 +0900 | git refs/tags/v0 | taggerdate:iso | 일치 |
| 12 | 커밋 수 | 236건(9/30 19:45) | 1436218=236; 감사 기반87d3597=528; main관측693 | git rev-list --count | 스냅숏별 ancestry 포함, merge 포함 | 일치(역사값), 07:00 갱신 필요 |
| 12 | 태그 수 | 1개 | tag --list=[v0],1개 | git refs/tags | 작업 시작 관측1개; 07:00 재확인 | 일치 |
| 12 | 테스트 수 | 936개 통과(9/30 19:45) | 기존936 passed/25 skipped 보고; 이번 관련24 passed | docs/reports/E6-pres2.verify.md §숫자 재계산 | 1436218 기존 실행. 현재 전체검사 금지로 재실행 안 함 | 일치(검증 보고 인용), 현재 총수 미측정 |
| **13** | **업로드 상한** | **10MB** | **10×1024²=10,485,760 B=10MiB** | **src/neumann/api/upload.py** | **MAX_UPLOAD_BYTES; 십진10MB와 다름** | **표시 보강(10MiB 권고)** |
| **14** | **월 인건비·기간** | **1인·재작업1개월·약800만 원** | **800만 원은 가정; 연봉8천만~1억 /12 =666.7만~833.3만, 보험료율 미제공** | **PLAN 08 Q45** | **연봉·보험 가정, 원천 기사·요율 없음** | **검증 불가(추정 산식 입력 부족)** |
| 14 | 연 절감액 | 연20건·약1.6억 원 | 800만원×1개월×20건=16,000만원=1.6억 원 | PLAN 08 Q45 | 산술 일치, 재작업20개월 절감은 가정 | 일치(가정하 산술) |
| **14** | **서버 수·월 운영비** | **1대·월 수십만 원** | **서버1대 가정, 사양·요금표 없음** | **PLAN 08 Q46** | **설계 추정, 사용량·견적 없음** | **검증 불가(운영비 원천 없음)** |
| **14** | **분석 LLM 비용** | **1건당 약200원 이하** | **환율·토큰 단가·분석 토큰량 동일 실행 원장 없음** | **PLAN 08 Q46** | **상한200원 추정; 수정안·최종점검 미포함** | **검증 불가(200원 상한 재계산 불가)** |
| 6·9·15 | 최종 점검·자동 반복 | 점검1회·반복루프0 | 대표 결정: 확정뒤 점검1회·재검색/재검토루프0 | docs/decisions.md 2026-10-01 02:5x | 정책/흐름 상한, 실측 완주 횟수 아님 | 일치(설계 결정, 병합 후 확정 유지) |
| 9·15·17 | MCP 도구 | 3종 | @server.tool 3개 | src/neumann/api/mcp_server.py | search_similar_works / get_review_records / get_post_status | 일치 |
| 15 | STAGE1 실행 범위 | 최소 실행 검증1건 | 계획상한1건, 이번 버전 구현 아님 | PLAN 00 §0.2 + pres5_content.py | 로드맵 상한 | 일치 |
| 16 | 본선 인력·기간 | 대표1 + AI·19시간 | 사람1 가정; 9/30 17:00→10/1 12:00=19h | PLAN 00 본선 일정 | 일정 차이 계산; 투입 인건비 실측 아님 | 일치 |
| 16 | 추가 인력·기간 | 엔지니어2·1~3/3~6/6~12개월 이상 | 개발 일정·인력 추정, 독립 실측 없음 | PPTX16 + pres5_content.py T17 + PLAN 08 | 중장기 기획 가정 | 일치(기획값, 실측 아님) |
| 16 | 파일럿 | 기관1곳·신규계획10건 | 목표1곳·10건, 실제 실증 결과 없음 | pres5_content.py put_note(17) + PPTX16 | 계획 규모, 모집·성공 수치 아님 | 일치(기획값) |
| 2·16·17 | 해커톤 총 시간 | 19시간 | 2026-09-30 17:00→10-01 12:00=19시간 | PLAN 00 / PPTX17 image7.png | datetime 차이 | 일치 |
| **17** | **일정 이미지 단계 시각** | **21:00(T+4)·02:00(T+9)·07:00(T+14)·10:00(T+17)·12:00(T+19)** | **T+4/9/14/17/19 산술 일치; 현 계획L0 T+3/L1 T+7/L2 T+11로 개정** | **PPTX17 image7.png + PLAN 00 §0** | **이전 제출 계획 이미지 유지** | **불일치(현재 개정 일정과 다름)** |
| **17** | **이미지 백테스트 계획** | **10~15편** | **실제 기본결과 n=5** | **PPTX17 image7.png + V3KEY** | **이전 계획 vs 현 대표 결정** | **불일치(동결 시 역사적 계획 표시 또는 교체)** |
| **17** | **이미지 데이터 목표** | **2,000편+** | **서비스색인1,128편; 확대2,128은 전환 보류** | **PPTX17 image7.png + docs/decisions.md 22:5x** | **구현 완료치로 읽으면 틀림; 현재 목표는 전체흐름** | **불일치(현재 방향·서비스수치와 다름)** |
| **17** | **이미지 동시 인원** | **5명 이하** | **개정기획 PM1+빌더≤7+검증≤2=≤10; 현재 사용자 약30작업** | **PPTX17 image7.png + PLAN00 편성** | **이전 운영 계획, 실제 최대 동시수 원장 없음** | **불일치(이전 계획)** |
| 17 | 이미지 체크포인트 | 데모1건10분·데모3건10분·기동15분·숫자확인15분 | 1/3건과10/15분은 일정 예산, 실행 측정값 없음 | PPTX17 image7.png | 계획 가정 | 일치(계획값, 실제 달성 아님) |
| **17** | **이미지 컷라인** | **T+5·T+10·T+15·T+17** | **산술상22:00·03:00·08:00·10:00; 개정기획 v0컷T+3.5/확장T+14/코드프리즈T+17** | **PPTX17 image7.png + PLAN00** | **이전 계획** | **불일치(개정 컷라인과 다름)** |
| 11·12 | 전체 흐름 후반 측정 | 뒤4칸null·예시2~3건측정중 | 동일 실행 원천없음, 값 보류 | numbers_frozen.json live_full_flow + docs/decisions.md03:1x | revise/confirm/final_check/draft/e2e_line null | 일치(미측정 유지) |
| 12·13 | 대표 판정·연결·보안 검사 | 일치율null·연결편/마스킹건/게이트삭제문장 측정중 | 대표 판정CSV·해당 단위 원천없음, 값 보류 | numbers_frozen.json backtest.human_agreement + PPTX12·13 | 다수결일치18/19로 대표판정값 대체 금지 | 일치(미측정 유지) |

## 재계산 방법과 측정값

새 API 호출이나 모델 판정 없이 원장을 독립 산술로 계산했다. 판정자의 grade를 pairing으로 시스템·논문·rank에 복원해 다수결(모두 다르면 B)을 만들고, 위험 0개인 논문에도 3슬롯을 둔다. 논문을 work_id순으로 정렬하고 `random.Random(20260930)`의 `randrange(n)`으로 2,000회 재표집했다. 백테스트 구간은 linear percentile, Macro-F1은 기존 명세의 정렬 표본 order statistic(하위 index 50·상위 1,949)이다. Macro는 매 재표집에서 support>0 클래스만 평균하며, Micro는 R1~R9 전체 FP를 포함한다. 원래 채점 함수를 호출하지 않고 TP·FP·FN과 F1을 독립 계산했다.

| 원장 | 기준선 / Neumann 또는 값 | 대조 |
|---|---|---|
| v3 A/B/C·빈 슬롯 | 기준선4/11/0·0빈, Neumann3/1/0·11빈 | 저장 결과 JSON·발표와 일치 |
| v3 precision@3·CI | 0.2667 [0.0667,0.4667] / 0.2 [0,0.6] | 일치 |
| v3 hit@3·CI | 0.6 [0.2,1] / 0.2 [0,0.6] | 일치 |
| v3 다수결 일치 | 18/19=0.947368… | 발표0.947 반올림 일치 |
| v2(민감도) | Neumann4/15=0.2667·A-rate4/4·hit2/5=0.4 | 기본v3와 분리 |
| 사후 | 3편재실행 [1,0,0]장, 판정B1/1; 기준선은 같은1편A1/3 | 기본v3와 분리 |
| astra Macro / Micro | 0.4864 / 0.5644, TP160·FP204·FN43 | 원래 score_astra.json과 일치 |
| 빈도 Macro / Micro | 0.3308 / 0.5379, TP174·FP270·FN29 | 일치 |
| 규칙 Macro / Micro | 0.3234 / 0.3344, TP52·FP56·FN151 | 일치 |
| astra Macro95%CI | [0.4276,0.5394] | 일치 |
| 코퍼스 | 1,128편 / 5,366리뷰 / 133,769문장 | JSONL 실제 행 수와 manifest 일치 |

실제 수행 명령·출력:

```powershell
$env:PYTHONIOENCODING='utf-8'
$env:PYTHONPATH='src;.'
$env:NEUMANN_LLM_PROVIDER='mock'
Remove-Item Env:OPENAI_API_KEY,Env:NEUMANN_PSEUDONYM_SALT,Env:NEUMANN_LIVE_LLM_OK,Env:NEUMANN_LIVE_TESTS -ErrorAction SilentlyContinue
& C:/Users/User/.venvs/neumann/Scripts/python.exe out/audit/recalculate.py
# exit 0. 위 표 수치와 out/audit/recomputed.json 생성(임시 감사 도구, 제품 코드 아님).
& C:/Users/User/.venvs/neumann/Scripts/python.exe -m pytest -q tests/e5/test_macro_f1.py tests/e5/test_backtest_metrics.py
# 24 passed in 0.22s
git rev-list --count 1436218
# 236
git rev-list --count 87d3597
# 528
git for-each-ref refs/tags/v0 --format='%(taggerdate:iso)'
# 2026-09-30 19:19:04 +0900
```

임시 감사 스크립트는 무시되는 `out/audit/`에만 만들었다. 재계산 요약은 `NUMBERS-AUDIT.recomputed.json`에 보존한다. 원천 SHA-256, 논문별 3슬롯 등급, 분자·분모, F1의 TP·FP·FN으로 원장과 대조할 수 있다. 과거 provider·model 기록을 실제 실행 설정으로 사용하지 않았다. 환경변수 값을 출력하거나 단언하는 테스트는 실행하지 않았다.

추가 파일 검사: 후보의 필수 키·타입, 미측정 값 유지, precision@3와 A-rate 필드 분리, F1 3종의 원래 점수·신뢰구간, v3 원장과 집계의 일치, 기존 동결 JSON·발표 코드·PPTX·content의 SHA-256 불변을 검사해 모두 통과했다. 대조표는 98행이다.

## 07:00 후보와 숫자 파일 적용의 한계

`numbers_frozen.candidate.json`은 원본과 같은 빌드 필수 키를 가진 **전체 후보**다. v3 성능 수치는 모두 그대로 두었다. 후보 변경은 일치율 18/19 표시, 시연 1/3·전체 2/4 구분, v0 참고값 표시, 현재 저장소 총수와 비용 200원 상한의 측정 중 표시다. 후반 4칸·대표 판정·병합 bool은 보류했다. `_audit.manual_edits_not_controlled_by_frozen_json`에 수동 편집 후보를 남겼다. 코드·PPTX는 수정하지 않았다.

**숫자 파일은 모든 수치의 단일 원본이 아니다.** 9쪽 시간, 10쪽 코퍼스, 12쪽 왼쪽 목표표의 Macro/P2/P6, 13쪽 보안 참고, 14쪽 절감액, 16쪽 인력·일정, 17쪽 이미지와 11·12쪽 발표자 노트는 `pres5_content.py`·백업 content·원본 PPTX에서 유지된다. 후보 JSON만 주입해도 왼쪽 표의 3건·100%, 노트의 85초와 구이미지는 자동 수정되지 않는다. PM이 07:00에 같은 실행의 본문·노트·캡처로 맞춰야 한다. 후보 문구가 길어지는 곳은 발표자료 담당자가 레이아웃을 재검사해야 한다.

07:00에는 main 커밋을 먼저 고정하고 그 커밋·태그 목록과 승인된 mock 검사 결과를 사용한다. 전체 흐름은 입력 → 분석 → 수정안 → 확정 → 도구 점검·수정 → 최종 초안의 동일 실행 원장으로 채운다. v0·v1의 분석까지 돈 기록을 전체 흐름 성과로 승격하지 않는다. 후반 원장이 없으면 null·측정 중을 유지한다. 이번 감사는 07:00 동결 실측을 대신하지 않는다.

## 못 한 것과 다음

- eLife·Europe PMC의 전체 원천 목록, 미반입 4샤드, 서버 요금·연봉 보도·보험료율·토큰 가격·환율을 확보하지 않았다. 근거 없이 새 값을 만들지 않았다.
- 현 브랜치의 제품 코드는 300자 거절 병합 전이므로 현재 main 규칙과 구분했다. 실서비스의 커밋·동작 확인은 PM이 해야 한다.
- 제품 LLM 실제 호출, 전체 `scripts/verify.py`, 전체 pytest, 색인 재빌드, 서버 기동·브라우저 접속은 하지 않았다. v0 E2E 5/5와 936개 테스트는 기존 실행 보고를 인용했다. 하위 위임 금지에 따라 다른 모델의 검증자를 새로 띄우지 않았다.
- main 병합·push·stash·다른 worktree 수정은 없었다. 커밋 뒤 사용자가 지정한 8099 메시지함 POST만 실행한다. 이 포트를 서버 기동·시험에 사용하지 않는다.
- 다음 담당: PM·발표자료 담당이 후보를 검토한 뒤 07:00 원장으로 확정하고 수동 편집 칸을 갱신한다.

## 커밋 인계 상태

보고서·후보·재계산 요약 3개 파일은 작성 및 검사를 마쳤으나 **커밋은 못 했다.** 명시적으로 `.git` 쓰기가 허용됐다는 과제 지시에도 실제 실행 환경은 아래 `git add`를 두 번 모두 거부했다. lock 파일 충돌이 아니라 생성 권한 거부다. 권한·훅을 우회하거나 다른 worktree를 수정하지 않았다.

```text
git add -- docs/reports/NUMBERS-AUDIT.md docs/reports/numbers_frozen.candidate.json docs/reports/NUMBERS-AUDIT.recomputed.json
fatal: Unable to create 'C:/Users/User/Desktop/project_neumann/.git/worktrees/numbers-audit/index.lock': Permission denied
```

권한이 반영되면 이 브랜치에서 위 세 파일만 stage한 뒤 다음 메시지로 커밋할 수 있다. main 병합·push는 하지 않는다.

```text
[NUMBERS-AUDIT] 발표 수치 98항목 원천 대조 및 07:00 동결 후보

validation: 관련 평가 테스트 24 passed; 후보 스키마·v3/F1 재계산·원본 해시 불변 PASS
builder: codex (GPT-6 기반; 세부 런타임 모델 ID 미노출)
```

대시보드 인계: 지정된 PowerShell `Invoke-RestMethod` POST를 실행해 메시지 ID `m1790796209959`를 받았다. 감사 결과와 커밋 권한 거부 상태를 한 줄로 알렸다.
