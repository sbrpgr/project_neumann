# E6-L3a 보고서 — 프로토타입 주소용 정적 배포 빌드

- 브랜치: `task/E6-L3a` · 빌더: claude-opus-5.5 · 2026-09-30
- 소유 경로만 고침: `scripts/build_static_site.py`, `scripts/build_static_site_shots.py`, `tests/e6/test_static_site.py`, 이 보고서와 스크린샷 3장
- 외부 공개(Pages 켜기·push)는 하지 않았다. 배포할 수 있는 폴더(`data/site/`, 커밋 안 함)를 만드는 데까지다

## 무엇을 했나

1. `scripts/build_static_site.py` — 서버 없이 도는 정적 사이트를 공유 폴더 `data/site/`에 만든다
   - 화면 원본 `src/neumann/webui/index.html`은 읽기만 한다(빌드 중 바이트가 바뀌면 실패). 산출물 `index.html`에만 세 곳을 주입한다
     - `</head>` 앞: `window.NEUMANN_STATIC = {...}`(데모 목록·상태) + `fetch` 가로채기. `health` → 정적 상태 JSON, `POST premortem/view` → 본문이 데모 계획서와 같으면 `demo/<id>.json`을 **상대 경로로 fetch**, 아니면 404 + "정적 판: 데모 3건만 — 라이브 분석 아님"
     - `</header>` 뒤: 모든 화면에 보이는 띠 "정적 판 · 미리 계산해 둔 결과만 보여 줍니다 — 라이브 분석 아님"
     - `</body>` 앞: 입력 화면의 "파일 업로드/직접 입력" 탭을 **데모 3건 선택**으로 바꾸고 본문을 읽기 전용으로. 원본 화면이 다시 그릴 때마다(MutationObserver) 다시 붙인다
     - 주입 지점이 정확히 1번씩 없으면 빌드 실패(원본 구조가 바뀌면 조용히 깨지지 않게)
   - 헤더 상태 알약·리포트 상단 상자에 데모별 **"사전 계산본(생성 시각 · 모델) — 라이브 분석 아님"**. 사전 계산본이 스스로 fixture 대체라고 밝히면(E6-L2a 매니페스트 `source: fixture`) "사전 계산본(fixture 대체 · 가짜 데이터 · 생성 … · 모델 …) — 라이브 분석 아님"으로 낮춰 적는다
   - 데모 3건(`tests/fixtures/plans/` plan.md·plan_elife_neuro.md·plan_medimaging.md)마다 `data/precomputed/`에서 결과를 찾는다. 받는 조건: plan_id가 데모 본문 sha256과 같음, 매니페스트 sha256과 파일 바이트가 같음(다르면 "변조 의심"으로 버림), `PremortemResult` 계약 통과. 못 쓰면 공용 fixture 결과로 채우고 사유를 화면·JSON에 적는다
   - 화면 데이터는 E4 조립기 `neumann.api.view.build_ui_view`로 만들고 `validate_ui_view`로 계약(`ui_view.schema.json`) 검사
   - 산출물: `index.html`, `fonts/**`(원본 그대로, 라이선스 포함), `demo/<id>.json` 3건, `demo/index.json`(목록·sha256), `build.json`(빌드 시각·커밋·원본 sha256), `.nojekyll`
   - 임시 폴더에 만든 뒤 바꿔 끼운다. 이 빌드가 만들지 않은 비어 있지 않은 폴더는 덮어쓰지 않는다(`--force` 필요)
   - **빌드 뒤 자동 검사 `check_site`**(`--check DIR`로 따로도): 필수 파일·폰트·데모 JSON(sha256 대조), 비밀값 패턴(verify.py와 같은 목록)·실제 비밀값, 환경변수 이름(설정·`.env.example`의 키 이름), 로컬 절대 경로(드라이브·UNC·사용자 홈·`file:`·이 기계 경로), 외부 도메인·루트 절대(`/…`) 리소스 참조와 스크립트 요청. 걸리면 exit 1, 찾은 값은 출력하지 않는다
2. `tests/e6/test_static_site.py` 26건 — 합성 화면으로 빌드 절차를 재고(E4가 없어도 돈다), 실제 화면 원본으로도 한 번 빌드한다
3. `scripts/build_static_site_shots.py` — `data/site/`를 임시 폴더의 `project_neumann/`에 복사해 `python -m http.server`로 띄우고 `http://127.0.0.1:<빈 포트>/project_neumann/`을 Playwright 1440×900으로 연다(GitHub Pages 하위 경로 재현). 입력 → 데모 1 리포트 → 위험카드·근거 패널을 찍고, 데모 3건 모두 리포트까지 돌린다. 서버는 끝나면 종료하고 포트가 비었는지 확인. 8000·8010은 쓰지 않는다

## 완료 기준별 측정

### 1. 빌드 (`data/site/`)

```
$ python scripts/build_static_site.py --data-dir C:/Users/User/Desktop/project_neumann/data
빌드: site/ · 정적 판 · 사전 계산본(fixture 대체) — 라이브 분석 아님
  - plan: precomputed(fixture) · 생성 2026-09-30T09:00:00Z · mock provider · 카드 2 · 유사 연구 3
  - plan_elife_neuro: precomputed(fixture) · 생성 2026-09-30T09:55:05.256036Z · 미기록 · 카드 0 · 유사 연구 0
  - plan_medimaging: precomputed(fixture) · 생성 2026-09-30T09:55:05.257826Z · 미기록 · 카드 0 · 유사 연구 0
검사: 파일 26개(6.0MB) · 텍스트 12개 · 리소스 참조 22개 · 데모 3건
검사 통과: 필수 파일·데모 JSON, 비밀값 0, 환경변수 이름 0, 로컬 경로 0, 외부·루트 절대 참조 0
```

- 지금 `data/precomputed/`는 E6-L2a가 만든 것(세 건 모두 `source: fixture`, 파이프라인 미연결)이다. 그래서 세 데모 모두 "사전 계산본(fixture 대체 · 가짜 데이터)"로 표시된다. plan.md는 공용 fixture 카드 2장, 나머지 둘은 카드 0장(E6-L2a가 "이 계획서의 fixture 결과가 없어 카드 없이 저장"이라고 밝힘)
- 검사를 따로 돌려도 같다: `python scripts/build_static_site.py --check C:/Users/User/Desktop/project_neumann/data/site` → 검사 통과, exit 0
- grep 교차 확인: `grep -rIl -E "[A-Za-z]:[\\/]{1,2}Users|AppData|\.venvs|OPENAI_API_KEY|NEUMANN_(DATA|RAW|LLM|EMBED|PSEUDONYM|API)" data/site` → 0건. `index.html`의 `NEUMANN_` 문자열은 `NEUMANN_STATIC` 3곳뿐, `src/href` 속성은 `data:,`·`#…`·원문 링크(`esc(u)`, a 태그)뿐

### 2. 테스트

```
$ python -m pytest tests/e6 -q
..........................                                               [100%]
26 passed in 6.35s
```

잰 것
- 필수 파일(index.html·demo/index.json·build.json·.nojekyll·폰트·데모 JSON 3건) 존재, 원본 index.html 바이트 불변, 원본 화면 스크립트가 산출물에 한 글자도 안 바뀌고 들어감
- 주입: 가로채기가 화면 스크립트보다 먼저, 데모 JSON 경로가 상대 경로(`demo/<id>.json`), 목록의 sha256 = 파일 sha256, `</script>`·`<!--`를 품은 문자열도 스크립트를 닫지 못함
- 사전 계산본: 실제 결과면 "사전 계산본(생성 2026-09-30 19:12 KST · 모델 gpt-6-astra (openai)) — 라이브 분석 아님", fixture 대체면 "사전 계산본(fixture 대체 · …)", 본문 없는 저장본은 공개 데모 본문을 plan_id가 같을 때만 다시 붙임, 매니페스트 sha256이 다르면 폴백 + "변조", plan_id가 다르면 파일 이름이 같아도 안 씀
- 폴백: 사전 계산본이 없으면 공용 fixture, plan.md가 아닌 데모에는 "예시 계획서(plan.md) 기준의 공용 fixture"라고 밝힘
- 검사기가 실제로 잡는지: 심어 둔 문제 13종(비밀값 패턴, Windows 경로, JSON 속 경로, 사용자 홈, 이 기계 절대 경로, 외부 스크립트, 외부 CSS url, 외부 fetch, 루트 절대 경로, 환경변수 이름, 데모 JSON 빠짐·변조, 폰트 빠짐) 모두 잡음. 실제 비밀값(가짜 값을 환경변수에 넣고 심음)도 잡고 값은 출력하지 않음. 근거 원문 링크(a[href])는 요청이 아니라 통과
- 실제 화면 원본 빌드: 데모 3건 뷰가 `ui_view.schema.json` 통과, `check_site` 통과

### 3. Playwright 1440×900 (로컬 정적 서버, 하위 경로 `/project_neumann/`)

```
$ python scripts/build_static_site_shots.py --site C:/Users/User/Desktop/project_neumann/data/site
...
shots: 통과          (exit 0)
```

출력 발췌:

```
"input": {"header_state": "정적 판 · 사전 계산본(fixture 대체) — 라이브 분석 아님", "selected": ["0"],
          "textarea_readonly": true, "textarea_chars": 645, "file_upload_visible": false, "start_enabled": true,
          "title": "Neumann — Research Pre-mortem (정적 데모 · 사전 계산본)"}
"reports": [{"demo": 0, "title": "연구계획서 (예시) — 전해액 이온전도도 예측 대리모델", "cards": 2, "works_rows": 3, "quotes": 8, "live_note_shown": true},
            {"demo": 1, "title": "연구계획서 (예시) — fMRI 기반 인지과제 분류", "cards": 0, "works_rows": 0, "quotes": 0, "live_note_shown": true},
            {"demo": 2, "title": "연구계획서 (예시) — 의료영상 분류 심층신경망", "cards": 0, "works_rows": 0, "quotes": 0, "live_note_shown": true}]
"fonts_report": [true, true, true, true, true]
"panel_quote": "The paper reports a random 80/10/10 split of the molecules."
"non_demo": {"status": 404, "label": "정적 판: 데모 3건만 — 라이브 분석 아님"}
"console_errors": [], "page_errors": [], "failed_requests": [], "bad_status": [], "external_requests": [],
"requests": 15,
"request_paths": ["/project_neumann/", "/project_neumann/demo/plan.json", "/project_neumann/demo/plan_elife_neuro.json",
                  "/project_neumann/demo/plan_medimaging.json", "/project_neumann/fonts/…"(폰트 11개)],
"server": "python -m http.server (127.0.0.1, 하위 경로 /project_neumann/)", "server_stopped": true, "port_free_after": true
```

- 콘솔 오류 0, 페이지 오류 0, 실패·4xx/5xx 응답 0, **외부 도메인 요청 0**(요청 15건 전부 127.0.0.1, 모두 `/project_neumann/` 아래)
- 렌더 조건: 입력 = `body[data-view=input][data-ready="1"]` + `#demoPicker` + 헤더 상태 갱신 + `document.fonts.ready`. 리포트 = `body[data-view=report][data-ready="1"]` + `#statusNotice` + (`#s-cards .rc` 또는 `#noCards`) + fonts.ready + networkidle
- 스크린샷: `docs/reports/E6-L3a_input.png`(데모 선택·읽기 전용 본문·정적 판 띠), `docs/reports/E6-L3a_report.png`(데모 1 리포트, 상단 상자에 "사전 계산본(fixture 대체 · 가짜 데이터 · 생성 2026-09-30 18:00 KST · 모델 mock provider) — 라이브 분석 아님"), `docs/reports/E6-L3a_cards.png`(위험카드 + 근거 패널)
- 정적 서버는 스크립트가 띄우고 종료했다(`server_stopped: true`, `port_free_after: true`). 남은 서버 없음

### 4. `python scripts/verify.py`

```
$ python scripts/verify.py
315 passed, 14 skipped in 10.31s
보안: 파일 149개
계약: 2개
테스트: 통과
verify 통과
```

(main `82146f9`까지 병합한 뒤. `data/site/`는 저장소 밖 공유 폴더라 커밋 대상이 아니다)

## 검증 뒤 보완 (PM 지시: main의 E4-L1b 템플릿 선택기 호환)

검증(PASS-조건부) 1번: main 화면이 입력 화면에서 `GET templates`·`GET templates/{id}`를 불러 정적 판에서 404 ×3, 콘솔 오류가 났다. `git merge main`(`00d7cb1`) 뒤 고쳤다.

- 빌드: `neumann.api.templates.list_templates()`·`get_template(id)` 응답을 그대로 `templates.json`, `templates/<id>.json`(템플릿 5 + 예시 3)으로 넣는다. 카탈로그 검사 실패면 빌드 중단, id는 API의 id 규칙(`^[a-z0-9]+(-[a-z0-9]+)*$`)일 때만 파일 이름으로 쓴다. 화면이 `templates`를 부르는데 카탈로그를 못 읽으면 빌드 실패
- 가로채기: `templates` → `templates.json`, `templates/<id>` → 목록에 있는 id만 `templates/<id>.json`, 없으면 404 JSON(네트워크로 안 나감)
- 입력 덧붙이기: 템플릿·예시로 불러온 본문은 덮어쓰지 않는다. 본문이 데모 3건 중 하나와 같으면 그 데모 칸을 켜고 실행을 연다. 템플릿 골격처럼 데모가 아니면 실행 단추를 막고 "정적 판: 템플릿 골격은 보기만 … 분석 결과는 데모 3건에만"을 붉게 적는다
- 검사: 화면이 `templates`를 부르면 `templates.json` 필수, 목록의 id마다 `templates/<id>.json`(id·text) 필수
- 대표 실명 배지는 대표 결정대로 그대로 둔다

측정(main `00d7cb1` 화면 기준):

```
$ python -m pytest tests/e6/test_static_site.py -q
29 passed
$ python scripts/build_static_site.py --data-dir C:/Users/User/Desktop/project_neumann/data
검사: 파일 35개(6.1MB) · 텍스트 21개 · 리소스 참조 22개 · 데모 3건 · 템플릿·예시 8건
검사 통과: 필수 파일·데모 JSON, 비밀값 0, 환경변수 이름 0, 로컬 경로 0, 외부·루트 절대 참조 0
$ python scripts/build_static_site_shots.py --site C:/Users/User/Desktop/project_neumann/data/site
"input": {..., "template_selector": true, "templates": 5, "examples": 3, "template_error": ""}
"template_pick": {"id": "materials-gnn", "start_enabled": false, "demo": "-1", "note_warn": true}
"example_pick": {"id": "example-battery", "start_enabled": true, "demo": "0", "note_warn": false}
"reports": 데모 3건 모두 리포트, live_note_shown true
"console_errors": [], "page_errors": [], "failed_requests": [], "bad_status": [], "external_requests": [],
"requests": 18 (templates.json, templates/materials-gnn.json, templates/example-battery.json 포함, 전부 /project_neumann/ 아래)
"server_stopped": true, "port_free_after": true, "templates_ok": true
shots: 통과  (exit 0)
```

새 테스트 3건: 템플릿 정적 JSON·가로채기·검사(빠진 템플릿 JSON을 잡음), 카탈로그 없이 templates를 부르는 화면·잘못된 id는 빌드 실패, 실제 카탈로그 = API 응답. 스크린샷 3장은 새 화면(범위 안내·템플릿 선택기 포함)으로 다시 찍었다.

## 빌드 명령

```bash
# 공유 데이터 폴더 기준(worktree에서 돌릴 때는 --data-dir을 준다. 기본값은 설정 NEUMANN_DATA_DIR)
python scripts/build_static_site.py --data-dir C:/Users/User/Desktop/project_neumann/data   # → data/site/
python scripts/build_static_site.py --check C:/Users/User/Desktop/project_neumann/data/site  # 검사만
python scripts/build_static_site_shots.py --site C:/Users/User/Desktop/project_neumann/data/site  # 하위 경로 확인·스크린샷
```

스크립트가 스스로 `src`와 저장소 루트를 `sys.path`에 넣으므로 `PYTHONPATH`가 없어도 돈다. 사전 계산본을 다시 만든 뒤(E3 파이프라인 연결 후 E6-L2a 재실행) 위 명령을 다시 돌리면 표시가 자동으로 "사전 계산본(생성 · 모델 gpt-6-astra)"로 바뀐다(매니페스트 `source`가 fixture가 아니면).

## GitHub Pages 배포 방법 제안 (실행 안 함 — 승인 필요)

**권장: `gh-pages` 브랜치에 빌드 산출물만 올리기.** 사전 계산본(`data/precomputed/`)이 저장소 밖에 있고 실제 결과를 만들려면 API 키가 필요하므로, CI에서 빌드하지 않고 로컬에서 만든 폴더를 올리는 쪽이 단순하고 키가 CI로 가지 않는다.

1. 빌드·검사·확인: 위 세 명령(모두 exit 0이어야 한다)
2. 산출물 확인: `data/site/`를 사람이 한 번 열어 본다(헤더 실명 배지·가짜 데이터 표시가 공개돼도 되는지)
3. 별도 worktree에 고아 브랜치 `gh-pages`를 만들고 `data/site/`의 내용(`.nojekyll` 포함)을 루트에 복사해 파일을 지정해 add·커밋 → `git push origin gh-pages`
   - 주의: 이 브랜치에는 `scripts/verify.py`가 없어 공용 훅(core.hooksPath)이 실패할 수 있다. 훅을 우회하지 말고, PM이 훅이 gh-pages에서 무엇을 검사할지 먼저 정한다(최소한 `build_static_site.py --check`를 통과한 폴더만 올린다)
4. 저장소 Settings → Pages → Source: Deploy from a branch, `gh-pages` / `(root)`. 또는 `gh api -X POST repos/sbrpgr/project_neumann/pages -f "source[branch]=gh-pages" -f "source[path]=/"`
5. 주소: `https://sbrpgr.github.io/project_neumann/` (하위 경로 동작은 3번 측정으로 확인)

대안: GitHub Actions(`actions/upload-pages-artifact` + `actions/deploy-pages`). 이 경우 워크플로 파일 추가(루트·`.github/`는 PM 소유)와 산출물 입력 경로가 필요하고, CI에서 빌드하면 사전 계산본이 없어 fixture 폴백만 나온다. 지금은 권장하지 않는다.

**대표·PM 승인이 필요한 것**
- 공개 게시 자체(`gh-pages` push, Pages 켜기 = 저장소 설정 변경). AGENTS 규칙상 push는 PM, 공개는 대표 승인 뒤
- 공개되는 내용: 헤더의 대표 실명 배지(E4가 대표 결정으로 유지), 공용 fixture 가짜 데이터(모두 "가짜 데이터 · 라이브 분석 아님"으로 표시), 데모 계획서 3건 본문, 가짜 원문 링크(`example.org`)
- `gh-pages` 브랜치에서 훅을 어떻게 돌릴지

## 바꾼 파일

- `scripts/build_static_site.py`(새 파일)
- `scripts/build_static_site_shots.py`(새 파일)
- `tests/e6/test_static_site.py`(새 파일, 26건)
- `docs/reports/E6-L3a.md`, `docs/reports/E6-L3a_input.png`, `docs/reports/E6-L3a_report.png`, `docs/reports/E6-L3a_cards.png`

## 결정 (스펙이 모호해서 고른 것)

- **API 대신 정적 JSON 읽기**: 두 방법을 섞었다. 데모 목록(본문·생성 시각·모델·sha256)은 `window.NEUMANN_STATIC`으로 주입하고, 화면 데이터는 `fetch` 가로채기가 `demo/<id>.json`을 상대 경로로 읽는다. 원본 화면 코드는 그대로 `fetch('health')`·`fetch('premortem/view')`를 부른다
- **입력칸**: 비활성화 대신 "데모 3건 선택"으로 바꿨다(탭 자리에 선택 칸, 본문 읽기 전용, 파일 업로드 숨김). 분석 → 리포트 흐름은 원본 그대로 돈다. 데모 밖 본문이 들어오면 404 + "정적 판: 데모 3건만"
- **"생성 시각"**: 결과의 `generated_at`(분석 시각)을 KST로 보인다. 사전 계산 작업 시각(매니페스트 `generated_at`)이 아니다. 둘 다 JSON(`_status.static`, `build.json`)에 남는다
- **대체 결과 판정**: 저장본·매니페스트가 밝힌 것만 믿는다(`source`/`origin`/`mode` 등에 fixture·sample·mock·fallback, 또는 결과 notices의 fixture·fake). 판정되면 뷰는 `_status.source = "sample"`로 만들어 원본 화면의 "공용 fixture(가짜 데이터)" 문구와 추적의 "샘플 데이터 · 분석 결과 아님"이 뜬다
- **사전 계산본 받는 조건**: plan_id 일치 + 매니페스트 sha256 일치(있을 때) + `PremortemResult` 계약. 최상위 확장 키는 계약 검사에서 빼고 출처 판정에만 쓴다(모델이 extra=forbid라서). 매니페스트에 sha256이 없으면 쓰되 "변조 여부를 확인하지 못했다"고 적는다
- **매니페스트 모양**: 작업을 시작할 때 E6-L2a 형식이 없어서 흔한 모양(entries/items 목록, id 키 dict)을 모두 받게 했고, 실제 E6-L2a 모양(`entries[].plan_id·demo·file·sha256·source·models`)을 테스트로 고정했다
- **`.nojekyll`**: GitHub Pages가 Jekyll로 가공하지 않게 넣었다
- **하위 경로 확인**: 스펙은 `python -m http.server`로 `data/site/`를 띄우라고 했다. Pages와 같은 하위 경로를 재려고 임시 폴더에 `project_neumann/`으로 복사해 그 루트를 띄웠다(루트에서 되면 하위 경로에서 깨질 수 있지만 반대는 아니다)
- **`docs/decisions.md`**: 스펙이 허용한 폴백(사전 계산본 없으면 fixture)만 썼고 스펙에서 물러난 것이 없어 적지 않았다(docs/는 PM 소유)
- **주입을 원본 DOM에 기대는 부분**: `#app`, `#ta`, `.seg`, `[data-mode]`, `#btnStart`, `body[data-view]`, `#hdrState`. 원본이 바뀌면 빌드(주입 지점)나 `build_static_site_shots.py`(DOM 조건)가 실패로 드러낸다

## 제안 (E4 화면 주인에게)

1. 정적 판을 화면 원본이 직접 알게: `window.NEUMANN_STATIC`이 있으면 입력 화면을 데모 선택으로 그리는 분기를 `renderInput`에 두면 빌드의 DOM 덧붙이기(MutationObserver)를 뺄 수 있다
2. `_status.source`에 `"precomputed"`를 인정: 지금은 리포트 머리의 소요 시간이 source가 pipeline일 때만 파이프라인 시간이고 아니면 요청 왕복 시간(정적 판에서는 0.0s)이다. 사전 계산본이면 결과의 단계 시간 합을 보이는 게 맞다

## 못 한 것

- **공개 배포**: 지시대로 하지 않았다(위 제안 참조)
- **실제 분석 결과로 된 사전 계산본**: `neumann.pipeline`(E3)이 아직 main에 없어 E6-L2a 사전 계산본이 모두 fixture 대체다. 데모 2·3은 카드 0장이다. 파이프라인 연결 → E6-L2a 재실행 → 이 빌드 재실행이 필요하다
- **`file://`로 열기**: 브라우저가 `file://`에서 JSON fetch를 막아 리포트까지 가지 않는다. HTTP(Pages·http.server)로만 확인했다
- 모바일 폭 스크린샷은 찍지 않았다(1180px 이하 레이아웃은 원본 CSS 그대로, 선택 칸은 860px 이하에서 한 줄 1개)

## 다음

- E3 파이프라인 병합 후: E6-L2a `precompute_demo.py` 재실행 → `build_static_site.py` → `build_static_site_shots.py` 다시 찍기(표시가 "사전 계산본(생성 · 모델 gpt-6-astra)"로 바뀌는지 확인)
- 대표 승인 뒤 PM: gh-pages 게시, 발표자료에 `https://sbrpgr.github.io/project_neumann/` 기재
- E6-L3b(시연 녹화): 이 정적 판을 같은 방식(하위 경로 http.server)으로 띄워 녹화할 수 있다
