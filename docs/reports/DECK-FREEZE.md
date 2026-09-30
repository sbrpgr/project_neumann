# DECK-FREEZE — 발표자료 수치·흐름 동결

2026-10-01 KST. 작업 브랜치의 파일만 수정. 빌더: `codex-gpt-6.1-sol`.

## 변경 내용

- 수정 전에 공유 폴더 `data/deck/build`, `assets`, `본선_발표자료_작업본.pptx·pdf`를 `data/deck/_backup_DECK-FREEZE_0620/`에 보존했다. 기존 백업·원천 자료는 수정하지 않았다.
- NUMBERS-AUDIT 후보를 검토해 `numbers_frozen.json`에 반영했다. 표시 값·분모·역사 평가와 현재 제품 측정을 분리했다.
- FINAL-LIVE-2를 06:23 확인했다. 그 전에는 지정 보고서 경로의 존재를 약 3분 간격으로 확인했다. 최신 보고서의 원 판정은 **불가 — API 전체 흐름 2/2편, 필수 4종 도구 실행 기준 미달**이다. API 완료와 최종 점검 `partial`을 모두 표시했다.
- 확정 기획 도식 3종을 6·8·15쪽에 사용했다. 자산은 git 제외 파일이므로 PNG 자체를 git show로 꺼낼 수 없었다. 대신 `c7ba7a4:scripts/deck_assets/{build_assets.py,preview_server.py,verify_assets.py}`를 git show로 읽어 공유 build 폴더에 보존하고 지정 Python으로 자산을 재생성했다. 17쪽 옛 일정 이미지는 확정 6단계 흐름과 실제 서비스 측정 표로 교체했다.
- UI-FINAL의 1440 화면에서 입력·채택·완성의 상단을 발췌했다. 각각 **화면 예시 · 시험 데이터** 캡션을 붙였다. 그림의 시험 데이터 도구·자동 수정 수치를 실제 라이브 결과로 주장하지 않는다.
- 제품 모델은 `gpt-6.1-sol`, 대표 에이전트 정의 원문은 그대로 보존했다. 발표 본문·노트에서 옛 모델명과 `【…】` 자리표시를 제거했다. 확정 URL이 없는 표지 QR의 빈 자리도 제거했다.
- 내용 변경은 공유 `build/pres5_content.py`와 `deck_freeze_content.py`에서 수행한다. `freeze_numbers.py`는 검토한 보고서 수치를 수치 파일로 재현한다. `build_deck.py`는 이미지 도형 제거도 처리하도록 보완했다.

## 바뀐 수치

쪽 번호는 최종 17장 기준이다. 기획 키트 17·18쪽은 최종 16·17쪽이다.

| 슬라이드 | 이전 | 이후 | 출처 |
|---|---|---|---|
| 5 | 공개 심사 기록 10만 편 이상 | 중복 제거 합산 미확인으로 삭제 | NUMBERS-AUDIT.md |
| 5 | 기록 823,170건 | 기록 823,170건 **추정**, 2샤드→6샤드 외삽 | NUMBERS-AUDIT.md·candidate |
| 5 | eLife 24,278편, Europe PMC 약 81,693편 | 각각 **사전 조사 인용**, 현장 원천 미확인 | NUMBERS-AUDIT.md |
| 9·11·17 | 과거 v1 분석 85·141·155초, 11쪽 카드 5장·85.0초 | 소재 **82.344초·4장**, 단백질 **104.547초·7장** | FINAL-LIVE-2.md |
| 11·17 | 수정 권고·확정·점검·초안 측정 중 | 소재 revise **31.281초**, 적용 **3/3**, finalize **48.078초·partial**; 단백질 revise **73.657초**, 적용 **18/18**, finalize **82.797초·partial** | FINAL-LIVE-2.md |
| 12 | precision@3 20%, 낸 위험 중 A 3/4 | **precision@3 3/15=20.0%**, **A-rate 3/4=75.0%**, 서로 다른 분모 명시 | NUMBERS-AUDIT.recomputed.json·candidate |
| 12 | 일반 LLM 26.7% | **precision@3 4/15=26.7%**, A-rate 4/15=26.7%; hit@3 3/5=0.6 | NUMBERS-AUDIT |
| 12 | v0 라이브 E2E 5/5 | **v0 검사 수 5/5**, 전체 흐름 성공이 아님 | NUMBERS-AUDIT |
| 12 | v1 4건 중 2건 통과 | **시연 계획서 1/3**, 무관 입력 차단 포함 총 2/4 | NUMBERS-AUDIT·949d628 실행 요약 |
| 12 | 성능 n=5 | **n=5, 통계적 결론 없음** 유지. 빈 11자리 포함, 셔플 대조 없음 | NUMBERS-AUDIT |
| 12 | 코퍼스 연결 측정 중 | 현장 코퍼스 **1,128편**, 사후 연결률은 미측정 | NUMBERS-AUDIT (서로 다른 지표를 구분) |
| 12·13·17 | 역사 원문 대조 10/10·13/13·20/20 등 | 최신 소재 **17/17**, 단백질 **26/26**, 원문 누락 0 | FINAL-LIVE-2.md |
| 12 | 테스트 936 통과 | **mock 2,979 통과·66 건너뜀**, main 9ffaceb | 사용자 지정 검증 결과; 이 작업에서 전체 pytest 재실행 안 함 |
| 14 | 분석 LLM 약 200원 이하·운영비 월 수십만 원 | 근거 없는 상한·서버비 삭제. **라이브 누계 $4.0065 추정** | LIVE $1.1901 + LIVE-B $1.0002 + LIVE-2 $1.8162 |
| 14 | 재작업 800만 원·연 20건·1.6억 원 | **800만 원×1개월×20건의 가정**, 실제 절감액 아님 | NUMBERS-AUDIT의 가정 구분 |
| 17 | 옛 목표 10~15편·2,000편 이상·T+ 일정 이미지 | 확정 흐름 + 최신 두 샘플 측정 + 제품 미달 판정 | c7ba7a4 도식·FINAL-LIVE-2 |
| 17 | 도구 실행 미측정 | 각 편 **Z3 0 / Pint 0 / NetworkX 2회**, citation 0회. NetworkX missing_sections 실패·재검사 실패 | FINAL-LIVE-2 counters.tool_runs |
| 17 | 전체 흐름 성공 미측정 | API **2/2 완료**, 제품 **partial**, 자동 수정 **각 0건** | FINAL-LIVE-2 원 판정 |

라이브 비용은 계획 가정 단가(입력 $5·출력 $20/백만 토큰)에 따른 보고서 합산 추정이다. 미반환 usage는 제외이며 실청구액·실제 가격·보장 상한을 뜻하지 않는다. FINAL-LIVE의 첫 단백질 revise 504와 LIVE-B의 재시험을 별도 실행으로 합산했다.

## 실행·검증

모든 Python 실행은 `C:/Users/User/.venvs/neumann/Scripts/python.exe`, `PYTHONPATH=src;.`를 사용했다. 프로세스에서 키·가명화 salt·라이브 허용 플래그를 제거하고 mock provider로 실행했다. 환경변수 값 출력·단언, 제품 API 호출, .env 읽기, 사용자 브라우저·데스크톱·탭 접근은 하지 않았다.

자산 생성·검사:

```text
BUILD PASS: 3 SVG + 3 PNG (1920x1080); external requests=0; mock=http://127.0.0.1:8100
NEGATIVE PASS: mutations rejected 10/10
COPY NEGATIVE PASS: missing/altered definition and positioning rejected 4/4
VERIFY PASS: 3 assets / 6 files; labels=78; external requests=0; browser errors=0
DESIGN PASS: off-token colors=0; fonts=1; type sizes=28/32/40/56
MOCK SERVER STOPPED
```

중간 PPTX 생성·검사:

```powershell
& C:/Users/User/.venvs/neumann/Scripts/python.exe build/freeze_numbers.py
& C:/Users/User/.venvs/neumann/Scripts/python.exe build/pres5_content.py _backup_E6-pres5_20261001_0300/build/content.json build/content.json C:/Users/User/Desktop/project_neumann/out/codex/deck-freeze/docs/reports/numbers_frozen.json
& C:/Users/User/.venvs/neumann/Scripts/python.exe build/build_deck.py C:/Users/User/Desktop/노이만_본선자료/발표자료/본선_발표자료.pptx build/content.json build/stage1.pptx build/img
& C:/Users/User/.venvs/neumann/Scripts/python.exe build/check_freeze.py
```

```text
saved build/stage1.pptx edits 276
slides=17; placeholders=0; obsolete_model_mentions=0; bounds_errors=[]
17 artifact checks PASS (수치·분모·원문 정의·시험 캡션·partial·도구 실행 수)
```

빌드 원명령:

```powershell
cd C:/Users/User/Desktop/project_neumann/data/deck
& C:/Users/User/.venvs/neumann/Scripts/python.exe build/pres5_build.py C:/Users/User/Desktop/project_neumann/out/codex/deck-freeze/docs/reports/numbers_frozen.json --png
```

첫 실행에서 중간본 생성은 통과했지만 PowerPoint COM의 `DispatchEx`가 `-2147023584: 지정한 로그온 세션이 없습니다`로 실패했다. git ACL·Office 실행 환경을 우회하지 않았다. 일반 사용자 세션에서 동일 명령을 실행할 수 있도록 Claude 대시보드 메시지함에 구체적인 경로·명령·진행 상태를 전달했다.

Windows 내장 `Windows.Data.Pdf`로 기존 PDF 17장을 1920px PNG로 렌더하는 사전 실행은 통과했다. 이후 Codex 런타임의 Poppler도 찾아 새 PDF 검사에 사용할 준비를 했다. `build/render_pdf.ps1`도 PDF 파일 자체를 렌더하므로 PPTX의 별도 이미지 내보내기를 PDF 검증으로 대신하지 않는다. 지정 Python 외의 Python은 실행하지 않았다.

수정한 글상자 34개의 Pretendard 실제 글꼴 폭을 이용한 보수적 줄바꿈 계산에서 넘침 경고 0개를 확인했다. 이것은 Office 실제 렌더의 육안 검사를 대체하지 않는다.

## 최종 산출물·남은 일

현재 상태: **PPTX 갱신 완료, 최종 Office 변환 및 새 PDF의 전페이지 육안 검증 차단**. 산출물 검사 17개가 통과한 `build/stage1.pptx`를 `data/deck/본선_발표자료_작업본.pptx`에 반영했다. 최종 이름의 PPTX를 다시 읽은 검사도 17항목 PASS다. 이 PPTX는 아직 Office 재저장·글꼴 내장·최종 PDF와의 시각 대조가 남아 있다. 공유 폴더의 **PDF는 03:55 구버전**이며 새 결과라고 주장하지 않는다. **발표자료 전체 동결 완료가 아니다.**

백업·전달 SHA-256 비교는 모두 통과했다: 백업 build/assets 및 원본 PPTX/PDF 존재, 최종 이름 PPTX와 stage1 바이트 일치, 재생성한 c7ba7a4 자산 6개와 백업 자산 바이트 일치. PDF가 원본 백업과 바이트 일치하는 것도 확인하여 아직 구버전임을 재확인했다.

Claude의 일반 Office 세션용 일괄 명령은 다음과 같다. 이 스크립트는 키·salt·라이브 플래그를 제거하고 원 빌드, Poppler의 PDF 전페이지 렌더, 최종 PPTX/PDF 수치 검사를 차례로 수행한다. 마지막 PNG 육안 검사까지 통과해야 동결 완료다.

```powershell
powershell -NoProfile -File C:/Users/User/Desktop/project_neumann/data/deck/build/freeze_handoff.ps1
```

비밀값 로더를 호출하지 않은 보조 검사 결과:

```text
PATTERN SECURITY: 496 files; 0 problems; secret loader not called
CONTRACT SCHEMAS: 2개
git diff --check: exit 0 (공백 오류 없음)
```

독립 모델 검증은 하위 에이전트 금지에 따라 수행하지 않았다. 자산 전용 검증과 산출물 자체 검사는 빌더 실행 결과이며 독립 검증을 대신하지 않는다. 전체 `scripts/verify.py`는 .env를 읽는 `load_real_secrets()` 때문에 실행하지 않는다. 비밀값 로더 없는 패턴 검사·git diff 공백 검사를 별도로 수행하고 전체 verify 통과로 주장하지 않는다.

git 쓰기·stash·main 병합·push는 시도하지 않았다. 사용자 지시에 따라 **Claude 커밋 대상은 `docs/reports/numbers_frozen.json`, `docs/reports/DECK-FREEZE.md` 두 파일**이다. 공유 `data/deck`의 원본·도식·산출물·중간 파일은 git 밖에 둔다. 30분 중간 커밋과 최종 커밋도 Claude가 수행한다.

권장 커밋:

```text
[DECK-FREEZE] 확정 흐름·감사 수치·최종 라이브 판정으로 발표자료 동결

검증: 17장 중간본 수치 검사 PASS, 자리표시/옛 모델명/페이지 밖 도형 0, 자산 3종 PASS; 최종 PDF 상태는 본 보고서 참조
builder: codex-gpt-6.1-sol
```
