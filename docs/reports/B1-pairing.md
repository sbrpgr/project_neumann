# B1-pairing 보고서 — 내보내기 결합 검증(각각 서명된 result·revision·assembled를 섞어 보내는 A3~A6)

- 빌더: `claude-fable-5.1`(Claude Code). 독립 검증(다른 모델)은 아직 받지 않았다.
- 작업 트리 `C:/Users/User/Desktop/project_neumann/.claude/worktrees/s3-B1`, 브랜치 `task/B1-pairing`, 기준 `codex/core-final-20261001`(`f54ef1d`).
- 모든 명령 `NEUMANN_LLM_PROVIDER=mock`, `HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1`, `NEUMANN_LIVE_LLM_OK` 없음 → 실제 OpenAI 호출 0. `.env` 열지 않음, `git stash` 없음, 병합·push 없음. 포트 서버 없음(FastAPI TestClient·httpx ASGI만).
- 읽은 것: `AGENTS.md`, `docs/HANDOFF.md`, `out/codex/final_dispatcher_manifest.md`, `out/codex/review_checkpoint_0225.md`, `out/codex/results/ASTRA-provenance-coupling-audit-evidence.md`(A3~A6 반례·권고), `docs/reports/E3-L2r.verify.md`, `E3-L2r.codex.verify.md`, `core-hmac-pairing-stop.md`, `E4-L2f-authority-fix.md`.
- 보안 긴급(03:1x, 다른 에이전트의 pytest 실패 문구에 키 값이 찍힌 사고): 그 뒤 모든 명령은 `env -u OPENAI_API_KEY -u NEUMANN_PSEUDONYM_SALT`로 키를 환경에서 뺀 채 실행했다. 새 테스트·보고서는 환경변수를 읽거나 출력·단언하지 않는다. 이미 돌던 전체 verify 로그는 키 모양 문자열을 **개수로만** 검사해 0건이었다(값은 어디에도 적지 않음).

## 1. 문제

E4-L2f 서명은 객체 **하나**의 무결성(결과·수정 권고·통합본을 각각 HMAC, 도메인 분리)만 보장하고 **객체 사이의 관계**는 보장하지 않았다. `export_revision.extra_files`는 세 서명을 따로 확인하고 `plan_id`만 맞추므로, 같은 계획서의 다른 분석에서 나온 정상 서명 객체를 섞으면(Codex 감사 A3~A6) 누락 카드·다른 수정안·기각인데 채택된 통합본·같은 발췌 id에 다른 인용이 `server_signed`로 ZIP에 남았다. 기준 커밋에서 감사 반례를 방어 기대값으로 다시 돌리면 **12/12 모두 `assert 200 == 422`로 실패**했다(아래 §4).

## 2. 설계 — export 측 교차 검증을 골랐다(서명 페이로드에 상위 해시를 넣는 방식과 비교)

두 방식 모두 검토했다. 선택은 **내보내기(export) 쪽 결합 검증기 + 조립 API의 "어긋난 결합에 서명하지 않기"**다.

| 기준 | 서명 페이로드에 상위 객체 해시 추가(발급자 측) | export 측 교차 검증(선택) |
|---|---|---|
| 이미 발급된 객체 | 옛 revision·assembly에는 상위 해시가 없어 어차피 교차 검증이 필요하다(검증기가 둘 다 필요) | 옛 객체도 같은 규칙으로 검사한다 |
| 키 재기동 뒤(서명 전부 무효) | 상위 해시도 서명 안에 있으므로 함께 무효 → 어긋난 패키지를 못 막는다 | 어긋남은 서명과 무관한 사실이라 서명 없이도 422 |
| 계약·범위 | 계약 추가는 "추가만"으로 가능하나 서명 발급자(E3-L2r `api/revise.py` 두 경로)·화면(E4-L4r)·계약 문서를 함께 바꿔야 하고 PM 승인·decisions 기록이 필요 | export 소유 파일(`export_revision.py`·`export.py`)에 한정. Codex 권고와 같다 |
| 표현 차이에 대한 견고성 | 브라우저 JSON 왕복(1.0→1 등)에 맞춘 정규화 해시를 발급·검증 양쪽이 똑같이 써야 하며 어긋나면 정상 결합이 강등된다 | id·문자열 비교라 표현 차이에 안전하다 |
| 증명력 | 정확한 부모 객체를 증명(더 강함) | 모순을 잡지 실제 생성 실행의 부모를 증명하지는 못한다(감사 보고서의 한계 그대로) |

즉 상위 해시 방식은 교차 검증을 대체하지 못하고 그 위에 얹는 별도 후속이며(PM 결정 사항), 마감 전 안전한 쪽은 교차 검증이다. 다만 어긋난 결합을 서버가 **새로 인증**하는 구멍(조립 API가 다른 서명 결과 + 옛 서명 권고에 `revised_plan_sig`를 발급)은 막아야 하므로, `api/revise.py`의 `assembly_verified`에 같은 결합 검사를 더해 서명을 붙이지 않게 했다(422가 아니라 강등 — 조립 API의 기존 계약이 미확인 입력을 거절하지 않고 `client_submitted_unverified`로 표기하는 것이고, `test_assembly_signing_requires_result_and_revision_authenticity[result]`가 그 계약을 고정한다).

### 판정 규칙

| 검사 | 묶는 것 | 어긋나면 |
|---|---|---|
| `session` | revision.session_id == result.session_id | 422 |
| `cards` | revision이 다룬 카드 ⊆ result.risk_cards, 위험 유형 같음 | 422 |
| `evidence` | 카드 근거 풀(`evidence_pool`) − 권고 records = 결과 카드의 `evidence`; 인용 id ⊆ result.evidence ∪ records; records id ∩ result.evidence = ∅ | 422 |
| `edits` | 통합본 `changes[]`의 edit_id가 권고에 있고 카드·종류·줄·`current_text`·근거 id·이유·채택 문안(다듬기 미적용 때) 같음; `stats.edits_total` = 권고 수정안 수; 기각·미결정·충돌 목록 id ⊆ 권고 | 422 |
| `decisions` | 내보내기 결정(마지막 결정 기준)이 통합본 기록과 같음: 적용된 안은 결정·수정 문안 일치, 기각 목록은 기각, 미결정 목록에 결정이 오면 모순, 충돌·건너뜀은 기각 아님. **결정 생략은 기각이 아니다** | 422("통합본을 다시 만든 뒤 내보낸다" 안내) |
| `quotes` | 세 서명이 모두 확인된 사슬에서, 서명 범위 안의 `markdown.footnoted`(각주 판)와 지금 결과로 다시 그린 각주가 발췌마다 같음(라벨 줄만 제외). 인용한 발췌가 없으면 공허하게 성립 | 422; 스냅숏이 없는 옛 통합본은 **`client_submitted_unverified` + 사유**(422 아님) |

구체적 모순은 `PairingConflict(ValueError)` → `/premortem/package` 422(입력 값은 되돌려 보내지 않고 서버가 만든 id만 40자까지). 확인할 자료가 없으면 `PairingUnverifiable` → 해당 파일을 trusted로 적지 않고 README·manifest에 사유. 구조 검사 5개는 서명 여부와 무관하게 하고(어긋난 패키지는 서명이 없어도 만들지 않는다), `quotes`는 인증된 스냅숏이 있을 때만 비교한다(서명이 깨진 사슬은 이미 unverified이고, A1·A2 경계는 그대로 강등이다).

## 3. 구현

| 파일 | 내용 |
|---|---|
| `src/neumann/api/export_revision.py` | `compose()`가 계약·plan_id·edit_id 검사 → 서명 확인 → `PAIRING_CHECKS`(session·cards·evidence·edits·decisions·quotes) 실행 → `Composition`(파일별 출처, 검사 상태, 미확인 사유, trusted 통합본의 라벨). `render_files()`·`summary_of()`가 같은 판정을 쓴다(README·파일·manifest가 다른 말을 못 한다). 기존 `extra_files()`·`summary_lines()`·`_origin()`·`_assembly_trusted()` 서명은 유지. `revision_result_problem()`을 조립 API가 쓴다. trusted 통합본의 표기는 서명된 다듬기 메타데이터 우선(`run_assembly`의 라벨 규칙과 같아 서명된 각주 판과 내보낸 각주 판이 글자 그대로 같다) |
| `src/neumann/api/export.py` | `build_package_files`가 `compose()`를 한 번 부르고, manifest에 `composition`(계약 밖 패키지 메타데이터: `revision_origin`·`assembly_origin`·`checks`·`qualifiers`, 덧붙인 파일이 없으면 null)과 덧붙인 파일 항목의 `origin`을 적는다. `build_package(..., meta=dict)`로 판정을 되돌려 받아 응답 헤더 `X-Neumann-Revision-Origin`·`X-Neumann-Assembly-Origin`(해당 파일이 있을 때만)을 싣는다. 결과 서명 판정·`X-Neumann-Result-Origin`·계획서 연결 상태는 그대로 |
| `src/neumann/api/revise.py` | `assembly_verified()`가 결과·권고 서명에 더해 `revision_result_problem()`이 없을 때만 참. `run_assembly()`는 서명은 유효하나 결합이 어긋나면 서명하지 않고 사유 알림을 남긴다 |
| `tests/e4/test_export_pairing.py` | 30개: P0·A1·A2 보존 3, A3 5변형, A4 3변형, A5 3모순+3양성, A6 1, 옛 통합본 미확인 1, 비서명 어긋남 422 1, 부분집합 권고 양성 1, 다듬기 양성 1, 권고만·통합본만 1, 조립 API 서명 안 함 1, 변이 6+1 |
| 이 보고서 | — |

계약(`contracts/`, `models.py`)·config·index.html·다른 소유 폴더는 바꾸지 않았다.

## 4. 반례 전후(감사 A3~A6, 같은 fixture·mock·가짜 기록 저장소·프로세스 무작위 HMAC 키)

| 사례 | 기준 `f54ef1d` | 이번 브랜치 |
|---|---|---|
| P0 정상 결합 | 200 · 11파일 · 모두 server_signed | 200 · 11파일 · revision/assembly `server_signed` · manifest `composition.checks` 6개 모두 `ok` · 헤더 2개 · 내보낸 각주 판 == 서명된 각주 판 |
| A1 통합본 서명을 권고 서명 자리에 | 강등 | 강등(같음), `quotes`는 `skipped` |
| A2 카드 제목 변조 + 옛 결과 서명 | 강등 | 강등(같음) |
| A3 다른 세션·원천 카드 없는 서명 결과 + 옛 권고·통합본 | **200, 권고·통합본 server_signed, risk_cards.json에 카드 없음** | **422** `수정 권고의 session_id가 결과의 session_id와 다르다(다른 분석의 수정 권고)` |
| A3 변형: 세션만 / 카드 누락 / 근거 목록 다름 / 기록 id 충돌 | 200 · trusted | 422 각각 `session_id…` / `카드 card-fx-seed가 결과의 위험카드에 없다` / `카드 card-fx-seed의 근거 풀이 결과 카드의 근거 목록과 다르다` / `새 기록 발췌 1건이 결과 evidence와 같은 id를 쓴다` |
| A4 같은 결과의 다른 서명 권고(다른 카드 부분집합) + 첫 서명 통합본 | **200, 적용 수정안이 revision.json에 없는데 통합본 server_signed** | **422** `통합본에 적용된 수정안 card-fx-leak/e1이 수정 권고에 없다(다른 수정 권고의 통합본)` |
| A4 변형: 같은 edit_id·다른 제안 문안 재발급 / 수정안 하나 더 | 200 · trusted | 422 `…문안이 수정 권고의 제안 문안과 다르다` / `…stats.edits_total…다르다` |
| A5 채택된 서명 통합본 + 내보내기 결정 기각 | **200, revision.json은 기각·revised_plan.md는 채택·통합본 server_signed** | **422** `수정안 card-fx-leak/e1의 결정(기각)이 통합본에 적용된 결정(채택)과 다르다 — 결정을 바꿨으면 통합본을 다시 만든 뒤 내보낸다` |
| A5 변형: 수정(다른 문안) / 미결정 안에 채택 | 200 · trusted | 422 / 422 `…통합본에서 미결정인데 결정(채택)이 왔다…` |
| A5 양성: 결정 생략 / 같은 결정 / 통합본이 기각으로 기록한 안에 기각 / 수정 결정 문안 일치 | 200 | 200 · trusted(결정 생략은 기각이 아니다) |
| A6 같은 출처 id·오프셋·발췌 id·세션, 원문 바이트만 바뀐 서명 결과 + 옛 서명 통합본 | **200, ZIP revised_plan.md에 대체 인용, 옛 통합본 HMAC 유효, README server_signed** | **422** `발췌 ex_c5986bb2facc61b2의 인용문이 서명된 통합본의 각주와 다르다(같은 발췌 id에 다른 인용)`; 결과만 따로 내보내면 200(결과 서명은 정상) |
| 각주 판 스냅숏 없는 서명 통합본(옛 형식, 인용 있음) | 200 · server_signed | 200 · 통합본 `client_submitted_unverified` · manifest `checks.quotes=unverified` · README "결합 미확인 사유: …인용 계보…" |
| 서명 없는 어긋난 결합(카드 누락) | 200 · unverified | 422(어긋남은 서명과 무관) |
| 조립 API: 서명된 다른 결과 + 서명된 옛 권고 | 200 · **`revised_plan_sig` 발급** | 200 · `origin=client_submitted_unverified` · `revised_plan_sig=null` · 알림 "입력 결과와 수정 권고가 같은 분석의 것이 아니다(…)" |

## 5. 명령과 출력

Python `C:/Users/User/.venvs/neumann/Scripts/python.exe`, `PYTHONPATH="src;."`, `-p no:cacheprovider`.

| 기준 | 명령 | 출력 |
|---|---|---|
| Red(기준 커밋에서 새 테스트) | `pytest tests/e4/test_export_pairing.py -k "a3_ or a4_ or a5_decision_conflicting or a6_"` | `12 failed, 18 deselected in 1.23s` — 12건 모두 `assert 200 == 422` |
| Green(대상) | `pytest tests/e4/test_export_pairing.py` | `30 passed in 17.28s`(첫 실행은 A4 감사 사례의 문구 순서 1건 실패 → 적용 수정안 검사를 총수 검사보다 먼저 하도록 순서를 바꿔 통과) |
| 이웃 회귀 | `pytest tests/e4/test_export_pairing.py tests/e4/test_export_revision.py tests/e4/test_export_plan_authority.py tests/e4/test_export_revision_dates.py tests/e4/test_payload_signing.py tests/e4/test_export.py tests/e4/test_export_ui_sign.py tests/e4/test_export_raw_audit.py tests/e4/test_revise_api.py tests/e3/test_assemble.py tests/e3/test_revise.py tests/e4/test_mcp_server.py tests/e4/test_e4_api.py` | 처음 `1 failed, 304 passed in 115.02s`: `test_assembly_summary_has_independent_signature_binding[signed]`(결정 0건·인용 0건·`markdown` 없는 서명 통합본을 server_signed로 기대). 인용한 발췌가 없으면 되묶일 인용도 없으므로 `quotes`를 공허 성립으로 고친 뒤 재실행 `57 passed in 31.32s`(pairing·dates·export_revision 3파일) |
| 변이(검사별, 저장소 테스트) | `test_mutation_disabling_one_check_lets_its_counterexample_through[6]` | 6/6 통과: 검사가 켜지면 422, 그 검사 하나만 끄면 같은 반례가 200·server_signed, 되돌리면 다시 422 |
| 변이(전체 무력화, 디스크 수정 없이 `PAIRING_CHECKS` 6개 모두 no-op) | 같은 파일 `-k "a3_ or a4_ or a5_decision_conflicting or a6_ or unsigned_mismatched or mint or legacy or mutation"` | `21 failed, 9 deselected in 1.98s` — 반례·미확인·조립 검사 21건 전부 실패(항상 통과하는 검사 아님) |
| `git diff --check` | | rc 0 |
| 전체 verify | `python scripts/verify.py`(보안 + 계약 + 전체 pytest) | 아래 §5.1 |

### 5.1 전체 verify

`NEUMANN_LLM_PROVIDER=mock PYTHONPATH="src;." … python scripts/verify.py`(03:07~03:23 KST, 다른 에이전트 167개 프로세스·CPU 60% 부하 중):

- 보안 검사: 파일 538개 **통과**. 계약 검사 통과.
- 전체 pytest: **5 failed, 2208 passed, 48 skipped in 939.47s** → verify rc 1(`[테스트] pytest 실패`).
- 실패 5건은 모두 **벽시계 시간 단언**이고 이번 변경 모듈(export·export_revision·revise)을 import하지 않는다(TEST-1 범위, HANDOFF·DOC-1 기록과 같은 종류): `tests/e0/test_sec6_heading_linear.py::test_adversarial_1m_plan_axis_queries_fast[hash_a_ideographic_b]`, `::test_many_headings_1m_linear[empty_headings]`, `tests/e0/test_sec6_templates_heading.py::test_adversarial_1m_under_200ms[many]`, `tests/e3/test_short_input.py::test_new_regexes_are_fast_on_adversarial_input[adv1]`·`[adv4]`.
- 부하 대조: ① 그 5건을 곧바로 단독 재실행 → `3 failed, 2 passed in 14.86s`(예: 0.59초 vs 상한 0.2초). ② 손대지 않은 기준 worktree(`pn_corefinal`, f54ef1d)에서 같은 5건 → `5 passed in 4.39s`. ③ 같은 부하에서 **번갈아** 4회(브랜치→기준→브랜치→기준, 03:25) → `5 passed` 1.71s / 1.85s / 2.23s / **7.00s(기준)** — 같은 코드도 부하에 따라 4배 흔들린다. ④ 세 시험 모듈 전체를 브랜치에서 → **`174 passed in 13.78s`**.
- 판정: 5건은 기계 부하 변동이며 이 브랜치의 결함이 아니다. 부하가 낮을 때 PM 큐에서 전체 verify를 다시 돌려 rc 0을 확인하는 것이 병합 조건이다(전체 verify는 동시에 하나만이라 이 세션에서 재실행하지 않았다).
- 키 유출 검사: verify 로그 전체에서 키 모양 문자열 0건(개수만 검사).

## 6. 영향 받는 API·화면

- `POST /premortem/revise`: 변경 없음(권고는 입력 결과에서 만들어져 결합이 자명하다).
- `POST /premortem/revise/assemble`: 결과·권고 서명이 유효해도 결합(세션·카드·근거)이 어긋나면 `revised_plan_sig`를 발급하지 않고 `notices`에 사유. 상태 코드·계약 모양 변화 없음. 정상 결합·미확인 입력·변조 6종 기존 테스트 그대로 통과.
- `POST /premortem/package`: 결합 모순은 422(detail에 사유), 미확인은 강등. 새 응답 헤더 `X-Neumann-Revision-Origin`·`X-Neumann-Assembly-Origin`(덧붙인 파일이 있을 때만). manifest `composition`·덧붙인 파일 항목 `origin`, README "결합 검증:" 줄과 "결합 미확인 사유:" 줄. 기본 9파일·`X-Neumann-Result-Origin`·`X-Neumann-Plan-Association`·날짜·raw-cap·audit 거절은 그대로(관련 테스트 통과).
- 화면: 이 기준 브랜치의 `webui/index.html`은 `/premortem/package`에 `result·result_sig·decisions`만 보내므로(§E4-L2f 주석) 결합 검증에 걸릴 수 없고 표시도 그대로다(정적으로 확인, 브라우저 실행 없음). Codex UI 후보(`codex/final-ui-20261001`, `codex/ui-ux-followup`)는 `window.NeumannRevise.exportPayload()`로 revision·revised_plan·결정을 함께 보내고 성공 문구에 `X-Neumann-Result-Origin`만 보인다. 422의 detail은 기존 `expServerMsg`가 그대로 화면에 띄우므로 사용자는 "통합본을 다시 만든 뒤 내보낸다" 안내를 본다. **후속(UI 소유자):** 성공 문구에 두 새 헤더(권고·통합본 출처)를 결과 출처 옆에 표시하고, `client_submitted_unverified`면 결과와 같은 경고 색으로.

## 7. 한계(정직 표기)

- 교차 검증은 **모순을 잡는 것**이지 실제 생성 실행의 부모를 증명하지 않는다(감사 보고서 한계 그대로). 같은 세션·같은 카드·같은 근거·같은 수정안·같은 인용인 두 실행은 구분하지 못하며, 그 경우 내용도 같으므로 패키지에 모순은 없다.
- `quotes`는 세 서명이 모두 확인된 사슬에서만 비교한다. 서명이 깨진 사슬(A1·A2)은 이미 강등이라 다른 인용이 섞여도 422가 아니라 unverified다(경계 유지). 스냅숏 비교는 `render_markdown`의 줄 구조(본문 n줄 + 구분선 + 라벨 + 각주)에 기대며, 구조가 다르면 모순이 아니라 미확인으로 처리한다.
- 다듬기(polish)가 적용된 통합본은 채택 문안·수정 문안의 문자열 일치 검사를 건너뛴다(다듬어진 줄이라 원문과 다르다). 나머지 결합(카드·줄·근거 id·이유·인용)은 그대로 검사한다.
- `evidence_pool`이 없는 권고(현재 서버는 항상 넣는다)는 풀 검사를 건너뛰고 인용 id 검사만 한다.
- 검사 문구에는 서버가 만든 id(카드·수정안·발췌)만 40자까지 실린다. 감사 반례의 `synthetic-…` 같은 입력 값은 되돌려 보내지 않는다(테스트가 단언).
- 발급자 측 상위 해시(정확한 부모 증명)는 별도 승인 후속이다(§2).

## 8. 못 한 것·다음(PM 5줄)

1. 독립 검증(다른 모델)이 감사 7사례·이 30건·이웃 회귀를 다시 잰다. 감사의 보고서 내장 탐침은 취약 동작을 단언하므로 이제 A3~A6에서 실패하는 것이 정상이다.
2. UI 소유자가 Codex UI 후보의 내보내기 성공 문구에 `X-Neumann-Revision-Origin`·`X-Neumann-Assembly-Origin`을 표시한다(이 브랜치는 index.html 미수정).
3. PM이 발급자 측 상위 해시(계약 추가·E3-L2r·UI 동시 변경) 후속 여부를 결정한다. 지금 검증기는 모순 탐지까지다.
4. main 병합·push·HANDOFF/QUEUE/decisions 갱신은 PM. 이 브랜치는 `codex/core-final-20261001` 위에만 있으며 main과의 `export.py` 충돌(`display_text`·`JSON_GENERATOR_NOTE`, E3-L2r.codex.verify.md)은 그 병합 때 푼다.
5. 실서비스(8010·8020)·실제 OpenAI·브라우저 실행은 하지 않았다.
