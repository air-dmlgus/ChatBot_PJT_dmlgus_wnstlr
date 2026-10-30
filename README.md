# 한끼로그 — AI 식단 코치

식단·영양 질문에 답하고 업로드한 PDF·Markdown·텍스트 문서를 찾아 근거로 답변하는 RAG 챗봇입니다.

## 프로젝트 구조

```text
├── docs/                 요구서와 고찰 보고서
├── front/                HTML, CSS, JavaScript 화면
├── servers/              FastAPI, 문서 처리, 벡터 검색
│   └── data/              기본 가이드 및 문서
├── tests/                API 점검 테스트
├── .gitignore
├── README.md
└── start.ps1              Windows 실행 스크립트
```

## 실행 방법

1. `servers/.env.example`을 복사해 `servers/.env`로 저장한 뒤 `GMS_KEY`를 입력합니다.
2. PowerShell에서 프로젝트 루트로 이동해 `./start.ps1`을 실행합니다. 첫 실행 때 가상환경과 라이브러리를 설치합니다.
3. VS Code Live Server로 `front/index.html`을 엽니다. API 문서는 http://localhost:8000/docs 입니다.

수동 실행은 `servers` 폴더에서 `python -m venv .venv`, 가상환경 활성화, `pip install -r requirements.txt`, `python main.py` 순서로 진행합니다.

## 기능

- 일반 AI 대화 `POST /chat`
- 벡터 유사도 문서 검색 `POST /search`
- 문서 근거 RAG 대화 `POST /integrated-chat`
- PDF·MD·TXT 업로드 `POST /upload`
- 학습 문서 목록 `GET /documents`
- 추천 질문, 출처 표시, 오류·업로드 상태 표시

`.env`, 가상환경, ChromaDB 데이터와 Python 캐시는 Git에 올리지 마세요. API 키를 저장소에 커밋하지 마세요.
