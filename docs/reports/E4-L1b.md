# E4-L1b 보고서 — AI for Science 템플릿 선택기·범위 안내

- 빌더: Claude Opus 5.5 · 브랜치 `task/E4-L1b` · 기준 커밋 `e0008d0`
- 결과: 완료 기준 3개 모두 직접 실행해 통과(아래 명령·출력)

## 무엇을 했나

1. **템플릿 카탈로그**(`src/neumann/api/templates/`)
   - `catalog.json`: 범위 안내(`scope.label` = "AI 활용 과학 연구 계획서 전용", 분야 5개), 필수 칸 5개(연구 목표·방법·데이터·평가·일정), 템플릿 5종, 예시 3건
   - 템플릿 5종 골격(한국어 마크다운): `materials_gnn.md`(재료·배터리 GNN 대리모델), `protein_molecule.md`(단백질·분자), `physics_pde_climate.md`(물리·PDE·기후), `neuro_fmri.md`(신경과학 fMRI), `medical_imaging.md`(의료영상). 칸마다 채울 항목을 분야에 맞게 적었다(데이터 분할·누출 점검, 기준선, 반복 수·오차 막대, OOD 일반화 등 심사에서 자주 지적되는 항목)
   - 예시 3건: `tests/fixtures/plans/plan.md`, `plan_elife_neuro.md`, `plan_medimaging.md`를 경로로 연결(복사하지 않음). 범위 밖 예시(`negative_recipe.md`)는 넣지 않았다
   - `catalog.schema.json`: JSON Schema Draft-07(추가 필드 금지, id 패턴, 예시 경로는 `tests/fixtures/plans/*.md`만)
2. **`src/neumann/api/templates.py`**: `router`(APIRouter)
   - `GET /templates` → `{version, scope, required_sections, templates[{id, kind, name, domain, summary, sections}], examples[{id, kind, name, domain, template_id, filename, title}]}` (목록에는 본문 없음)
   - `GET /templates/{id}` → 템플릿이면 골격, 예시면 데모 계획서 원문. `{id, kind, name, domain, text, filename, source, sections, chars, sha256, ...}`
   - 카탈로그는 처음 읽을 때 스키마 + 참조(골격 파일 존재, 필수 칸, 예시 파일 존재, template_id, id 중복, 분야가 scope 안인지)를 검사한다. 실패하면 빈 목록으로 숨기지 않고 500과 사유를 준다
   - id는 카탈로그 사전에서만 찾는다(요청 문자열로 경로를 만들지 않음). 패턴 밖이면 422, 없으면 404
3. **입력 화면**(`src/neumann/webui/index.html`의 입력 부분만)
   - 상단 범위 안내 `#scope`: "AI 활용 과학 연구 계획서 전용" + 분야 5개. HTML에 고정 문구로 있어 API가 죽어도 보인다
   - 템플릿 선택기 `#tplList`(5칸, 로마숫자 + 이름, 선택 = 붉은 밑줄): 누르면 `GET /templates/{id}`로 골격을 받아 입력칸을 채우고 직접 입력 모드로 바꾼다
   - 예시 불러오기 `#exList`(밑줄 텍스트 링크 3개): 누르면 데모 계획서 원문을 채우고 연결 템플릿을 선택 표시, 요청의 `filename`에 원래 파일 이름을 넣는다
   - 사용자가 쓴 글을 템플릿이 덮으면 "이전 입력 되돌리기"가 나온다
   - 적합성 판정 자리 `#fitBox`(평소 숨김): `window.NeumannInput.showFitness(result)`로 판정 결과를 보인다. 부적합이면 "적합성 판정 · 부적합 — 분석하지 않음" + 사유 + 분야·언어·판정 방식(astra 판정 / 규칙 비상 판정 / mock provider)
   - `/templates`가 404·500이면 "템플릿 목록을 불러오지 못함 · GET /templates 404"를 붉게 보인다(범위 안내는 그대로)
   - 디자인 규칙: 색 토큰만 사용, 알약·채움 칩·왼쪽 색 바 없음(밑줄·괘선·색 텍스트), 한글에 자간·uppercase·모노 없음, CDN 없음
4. **테스트**
   - `tests/e4/test_templates.py`(기본 pytest, 25건): 스키마 자체 유효성, 카탈로그 스키마 통과, 망가진 카탈로그 9종 거부, 골격 필수 칸 누락 검출, 분야·템플릿 5종, 골격 칸 순서, 예시 3건 = 데모 계획서, 목록·골격·예시 라우트(원문과 글자 단위로 같음), 404/422, 카탈로그 고장 시 500, 화면 정적 검사
   - `tests/e4/test_templates_ui.py`(Playwright, `NEUMANN_UI_TESTS=1`일 때만 pytest가 돌림 · 스크립트로도 실행): 하위 프로세스에서 `main.app`에 라우터를 붙여 8121에 띄우고, 끝나면 종료

## 완료 기준별 측정

환경변수는 `_COMMON.md`대로(`PYTHONIOENCODING=utf-8 PYTHONPATH="src;." HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 NEUMANN_RAW_DIR=… NEUMANN_DATA_DIR=… NEUMANN_EMBED_MODEL=…`), Python은 `C:/Users/User/.venvs/neumann/Scripts/python.exe`.

### 1. `pytest tests/e4 -q -k templates` + 템플릿 JSON 스키마 테스트 — 통과

```
$ python -m pytest tests/e4 -q -k templates
.........................s                                               [100%]
25 passed, 1 skipped, 30 deselected in 0.88s
```

건너뛴 1건은 Playwright 검사(`NEUMANN_UI_TESTS=1` 전용, 2번에서 따로 실행). 스키마 테스트는 `test_templates_schema_is_valid_draft7`, `test_templates_catalog_matches_schema`, `test_templates_catalog_checker_rejects_broken[9종]`.

### 2. Playwright(1440×900) 스크린샷·콘솔 오류 0·외부 요청 0 — 통과

```
$ python tests/e4/test_templates_ui.py --port 8121      # exit 0
 "scope_text": "AI 활용 과학 연구 계획서 전용\n소재·화학·분자\n단백질·생물·신약\n물리·PDE·기후\n신경과학\n의료영상",
 "templates_shown": ["i 재료·배터리 GNN 대리모델", "ii 단백질·분자", "iii 물리·PDE·기후", "iv 신경과학 fMRI", "v 의료영상"],
 "examples_shown": ["전해액 이온전도도 GNN소재·화학·분자", "fMRI 인지과제 분류신경과학", "흉부 X선 폐렴 검출의료영상"],
 "fitbox_hidden_initially": true,
 "template_fills_textarea": true,
 "template_selected": "true",
 "undo_restores_user_text": true,
 "all_templates_fill": {"materials-gnn": true, "protein-molecule": true, "physics-pde-climate": true, "neuro-fmri": true, "medical-imaging": true},
 "examples_fill_and_select_template": {"example-battery": true, "example-fmri": true, "example-medimaging": true},
 "example_meta": "예시 fMRI 인지과제 분류\nplan_elife_neuro.md\n템플릿 신경과학 fMRI\n이전 입력 되돌리기",
 "fitbox_text": "적합성 판정 · 부적합 — 분석하지 않음\n[mock] 연구 질문·방법·데이터·평가 요소가 없다\n[mock] 조리법 문서로 보인다\n분야 해당 없음 · 언어 ko · mock provider",
 "fitbox_hidden_after_clear": true,
 "no_router_error_text": "템플릿 목록을 불러오지 못함 · GET /templates 404",
 "console_errors": [],
 "console_errors_in_404_scenario": ["Failed to load resource: the server responded with a status of 404 (Not Found)"],
 "page_errors": [],
 "failed_requests": [],
 "requests_total": 30,
 "request_paths": ["/", "/fonts/…(7개)", "/health", "/templates", "/templates/example-battery", "/templates/example-fmri",
                   "/templates/example-medimaging", "/templates/materials-gnn", "/templates/medical-imaging",
                   "/templates/neuro-fmri", "/templates/physics-pde-climate", "/templates/protein-molecule"],
 "external_requests": [],
 "problems": []

$ python -c "…connect_ex(('127.0.0.1',8121))…"
8121 free: True          # 서버 종료 확인
```

- 콘솔 오류 0, 페이지 오류 0, 실패 요청 0, 외부 요청 0(본 흐름). 404 콘솔 오류 1건은 "라우터 없음" 장면을 일부러 만든 것(`page.route`로 404 주입)이라 따로 셌다
- 스크린샷(렌더 완료 조건 = `data-ready="1"` + 템플릿 버튼 5개 + 입력칸 값 일치 + `document.fonts.ready` 뒤 촬영):
  - `E4-L1b_input.png` 첫 화면: 범위 안내 · 템플릿 선택기 · 예시 불러오기
  - `E4-L1b_template.png` 템플릿 i 선택 → 골격이 입력칸에, 선택 표시·칸 목록·되돌리기
  - `E4-L1b_example.png` 예시 "fMRI 인지과제 분류" → 원문이 입력칸에, 연결 템플릿 iv 선택 표시
  - `E4-L1b_fitness.png` 적합성 판정 자리. **판정은 mock 주입**(연결 전 자리 확인용, 화면에 "mock provider"·"[mock]"으로 표기)
  - `E4-L1b_no_router.png` `/templates` 404일 때: 사유 표시, 범위 안내 유지

### 3. `python scripts/verify.py` — 통과

```
$ python scripts/verify.py
183 passed, 1 skipped in 2.86s
보안: 파일 129개
계약: 2개
테스트: 통과
verify 통과
```

## 바꾼 파일

- 새로: `src/neumann/api/templates.py`, `src/neumann/api/templates/{catalog.json, catalog.schema.json, materials_gnn.md, protein_molecule.md, physics_pde_climate.md, neuro_fmri.md, medical_imaging.md}`, `tests/e4/test_templates.py`, `tests/e4/test_templates_ui.py`, `docs/reports/E4-L1b.md`, `docs/reports/E4-L1b_*.png`(5장)
- 수정: `src/neumann/webui/index.html` — 입력 화면 부분만(`renderInput`의 반환 HTML, 새 함수 묶음 "1 입력 · 템플릿 선택기…", `render()`의 입력 분기에 클릭 위임 1개, 부팅 줄에 `loadTemplates()`, CSS 블록 "E4-L1b 입력" 추가). 실행·리포트 화면과 `S` 상태 객체는 건드리지 않았다
- 안 고침: `main.py`, `contracts/`, `models.py`, `tests/fixtures/`

## PM이 main.py에 붙이는 법

```python
from neumann.api.templates import router as templates_router
app.include_router(templates_router)
```

prefix 없이 붙인다(화면은 상대 경로 `fetch('templates')`를 쓴다). 붙이기 전까지 화면은 "템플릿 목록을 불러오지 못함 · GET /templates 404"를 보인다.

## 결정(스펙이 모호해서 고른 것)

- `GET /templates`는 배열이 아니라 객체(`scope`·`templates`·`examples`)를 돌려준다. 범위 안내와 예시를 같은 요청에 싣기 위해서다. 예시도 같은 `GET /templates/{id}`로 받는다(`kind`: template | example)
- 예시 계획서는 복사하지 않고 `tests/fixtures/plans/`를 경로로 읽는다(`main.py`가 이미 `tests/fixtures/premortem_result.json`을 읽는 것과 같은 방식). 경로는 스키마로 `tests/fixtures/plans/*.md`만 허용
- 데모 계획서 "3건"은 `plan.md`·`plan_elife_neuro.md`·`plan_medimaging.md`. `negative_recipe.md`(범위 밖)는 예시에서 뺐다
- 범위 안내는 히어로 위, 화면 맨 위 한 줄로 두었다(스펙 "상단"). 문구는 HTML에 고정해 API 실패와 무관하게 보인다
- 적합성 판정 자리는 `assess_fitness`(E3-L1c, 아직 main에 없음)의 반환 필드가 확정되지 않아 느슨하게 읽는다: 적합 여부 `fit`/`is_fit`/`suitable`/`is_research_plan`/`is_plan`(bool) 또는 `verdict`(fit·unfit·적합·부적합), 사유 `reasons`(목록)/`reason`/`why`, 분야 `field`/`domain`, 언어 `language`/`lang`, 판정 방식 `generator`/`method`/`judged_by`/`impl`(astra·rule·mock). 판정 방식이 없으면 "판정 방식 미표기"로 보인다(규칙 판정을 astra로 보이지 않게)
- `main.py`를 못 고치므로 Playwright 검사는 하위 프로세스에서 `main.app`에 라우터를 붙여(이미 있으면 그대로) 띄운다. 포트 8010이면 거부한다
- 템플릿이 사용자 글을 덮을 때 확인 창(confirm) 대신 "이전 입력 되돌리기"를 둔다(브라우저 대화상자는 Playwright·발표 중 흐름을 끊는다)

## 못 한 것

- 적합성 판정의 실제 연결(스펙상 PM 몫): `/premortem/view` 응답이나 별도 호출에서 판정 dict를 받아 `window.NeumannInput.showFitness(result)`를 부르면 된다. 부적합이면 분석 단계로 넘어가지 않게 하는 흐름은 `startAnalysis`(실행 화면, 이 과제 소유 밖)에서 PM이 정한다
- 파일 업로드 모드에서 템플릿을 고르면 직접 입력 모드로 바뀐다(업로드 파일과 템플릿을 합치지 않음)

## 다음

- PM: 위 두 줄로 라우터 연결 → `NEUMANN_UI_TESTS=1 python -m pytest tests/e4/test_templates_ui.py -q -s`로 재확인(8121 사용, 스스로 종료)
- E3-L1c 병합 뒤: 판정 dict 필드 이름을 `normFit`(index.html)에 맞추고, 부적합일 때 입력 화면으로 돌아와 `#fitBox`를 보이게 연결
- E5-L0e2e: 범위 밖 입력(`negative_recipe.md`)에서 `#fitBox` 문구를 확인 대상으로 쓸 수 있다
