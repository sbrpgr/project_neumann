# E4-L1a — 계획서 업로드 파서(txt·md·pdf·docx)

- 빌더: Claude Opus 5.5 · 검증: Claude Sonnet 5.5 · 목표 40분
- 소유: `src/neumann/api/upload.py`, `tests/e4/test_upload*.py` (`api/main.py` 등 다른 파일은 건드리지 않는다)

## 읽을 것
- 계획서 §4 E4 L1(`POST /upload/plan`: txt·md·pdf·docx, 10MB, 디스크 미저장, HWP 거부)

## 만들 것
1. `api/upload.py`: `parse_plan_upload(filename: str, data: bytes) -> str` — 확장자·매직바이트로 판별, pdf(pypdf)·docx(python-docx)·txt/md(인코딩 추정: utf-8 → cp949) 텍스트 추출, 10MB 초과 거부, HWP/HWPX는 415와 "HWP는 PDF나 DOCX로 저장해 올려 주세요" 안내, 디스크에 저장하지 않음. FastAPI `router`에 `POST /upload/plan`(텍스트와 줄 수, 추출 경고 반환). `main.py` 연결은 PM이 한다
2. 테스트용 작은 pdf·docx는 테스트 안에서 생성(파일 커밋 최소화)
## 완료 기준
1. 형식별 추출 테스트, 한국어 텍스트 보존, 크기·HWP 거부
2. `python scripts/verify.py` 통과
