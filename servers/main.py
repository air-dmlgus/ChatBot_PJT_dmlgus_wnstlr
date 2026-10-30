# -*- coding: utf-8 -*-
"""
SSAFY ChatBot 관통 PJT - RAG 챗봇 서버 (FastAPI)

[API]
  POST /chat             일반 채팅 (GPT에게 그대로 질문)
  POST /search           문서 검색만 (GPT 없이 비슷한 문서 조각 찾기)
  POST /integrated-chat  RAG 채팅 (문서 검색 + GPT 답변)
  POST /upload           문서 업로드 (.txt / .md / .pdf)
  GET  /documents        학습된 문서 목록

[실행]  cd servers → python main.py → http://localhost:8000/docs
"""
import os
import traceback
from collections import Counter
from contextlib import asynccontextmanager
from pathlib import Path

import chromadb
import numpy as np
from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from openai import APIConnectionError, APIStatusError, AuthenticationError, OpenAI, RateLimitError
from pydantic import BaseModel, Field

from document_utils import make_chunks, read_file

# ==========================================
# 1. 설정 — 실험할 때 이 숫자들을 바꿔 보세요
# ==========================================
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")             # API 키는 코드가 아니라 .env 파일에서 읽습니다

GMS_KEY = os.getenv("GMS_KEY", "").strip()
if not GMS_KEY.isascii():                  # .env.example의 한글 안내 문구를 그대로 둔 경우 → 키 없음으로 처리
    GMS_KEY = ""
GMS_BASE_URL = os.getenv("GMS_BASE_URL") or "https://gms.ssafy.io/gmsapi/api.openai.com/v1"
GPT_MODEL = os.getenv("GPT_MODEL") or "gpt-5-nano"                         # 답변을 만드는 모델
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL") or "text-embedding-3-small"   # 문장을 숫자(벡터)로 바꾸는 모델

DATA_DIR = BASE_DIR / "data"               # 챗봇이 공부할 문서 폴더
CHUNK_SIZE = 250                           # 청크(문서 조각) 최대 글자 수
SIMILARITY_THRESHOLD = 0.22                # 이 점수 이상인 청크만 "관련 문서"로 인정 (1에 가까울수록 비슷)
ALLOWED_EXTENSIONS = {".txt", ".md", ".pdf"}
MAX_UPLOAD_MB = 10

CHAT_PROMPT = """당신은 SSAFY 교육생을 돕는 친절한 AI 챗봇입니다.
한국어로 간결하게 답하세요. 답변은 말풍선에 글자 그대로 표시되므로 마크다운 기호(#, **, 표)는 쓰지 마세요."""

RAG_PROMPT = """당신은 SSAFY 교육 과정을 돕는 AI 어시스턴트입니다.
아래 [참고 문서]를 근거로 질문에 답하세요.
1. [참고 문서]에 있는 내용은 그 내용을 근거로 정확하게 답합니다.
2. [참고 문서]에 없는 내용은 지어내지 말고, 일반 지식으로 답할 때는 "문서에 없는 내용이라 일반 지식으로 답변드립니다."라고 먼저 밝히세요.
3. 한국어로 간결하게, 마크다운 기호(#, **, 표) 없이 답하세요.

[참고 문서]
{context}"""

# ==========================================
# 2. GMS(OpenAI) 호출 — 임베딩 / GPT
#    GMS는 주소(base_url)만 다를 뿐 OpenAI API와 사용법이 같습니다.
# ==========================================
client = OpenAI(api_key=GMS_KEY or "not-set", base_url=GMS_BASE_URL, timeout=60, max_retries=1)


def call_gms(request):
    """GMS 요청을 실행하고, 실패하면 이유를 알기 쉬운 오류 메시지로 바꿉니다."""
    if not GMS_KEY:
        raise HTTPException(500, "GMS_KEY가 없습니다. servers/.env 파일의 GMS_KEY= 뒤에 키를 붙여넣고 서버를 다시 켜세요.")
    try:
        return request()
    except AuthenticationError:
        raise HTTPException(401, "GMS 인증 실패: GMS_KEY가 올바른지 확인하세요.")
    except RateLimitError:
        raise HTTPException(429, "GMS 사용량 한도를 초과했습니다. 잠시 후 다시 시도하세요.")
    except APIConnectionError:
        raise HTTPException(502, "GMS 서버에 연결할 수 없습니다. 네트워크를 확인하세요.")
    except APIStatusError as e:
        reason = e.body.get("message") if isinstance(e.body, dict) else e.message
        hint = " (.env의 모델명을 확인하세요)" if e.status_code == 404 else ""
        raise HTTPException(502, f"GMS 호출 실패 ({e.status_code}): {reason}{hint}")


def embed(texts):
    """문장 목록 → 벡터(숫자 목록) 목록.  뜻이 비슷한 문장은 비슷한 벡터가 됩니다."""
    vectors = []
    for i in range(0, len(texts), 100):                  # 한 번에 100개씩 나눠서 요청
        res = call_gms(lambda: client.embeddings.create(model=EMBEDDING_MODEL, input=texts[i:i + 100]))
        vectors += [item.embedding for item in res.data]
    return vectors


def ask_gpt(question, system_prompt):
    """GPT에게 질문하고 답변 글자만 돌려줍니다. (OpenAI Responses API)"""
    res = call_gms(lambda: client.responses.create(model=GPT_MODEL, instructions=system_prompt, input=question))
    return res.output_text


# ==========================================
# 3. 벡터 DB(ChromaDB) — 청크와 벡터를 저장하고, 비슷한 청크를 찾아줍니다
# ==========================================
collection = None   # 서버가 켜질 때(lifespan) 만들어집니다


def add_document(filename, text):
    """문서를 청크로 나누고 → 벡터로 바꿔서 → DB에 저장합니다. (같은 이름이 있으면 교체)"""
    chunks = make_chunks(text, size=CHUNK_SIZE)
    if not chunks:
        return 0
    vectors = embed(chunks)                              # GMS 호출이 실패하면 여기서 멈추므로 기존 문서는 안전
    collection.delete(where={"source": filename})        # 같은 이름의 예전 내용 지우기
    collection.add(
        ids=[f"{filename}#{i}" for i in range(len(chunks))],
        documents=chunks,
        embeddings=vectors,
        metadatas=[{"source": filename}] * len(chunks),
    )
    return len(chunks)


def search_chunks(question, top_k):
    """질문과 가장 비슷한 청크 top_k개를 [{text, source, score}] 형태로 돌려줍니다."""
    if collection.count() == 0:
        return []
    res = collection.query(query_embeddings=embed([question]), n_results=min(top_k, collection.count()))
    return [
        # Chroma는 '거리'(작을수록 비슷)를 주므로 1에서 빼서 '유사도'(클수록 비슷)로 바꿉니다
        {"text": doc, "source": meta["source"], "score": round(1 - dist, 4)}
        for doc, meta, dist in zip(res["documents"][0], res["metadatas"][0], res["distances"][0])
    ]


def numpy_search(question, top_k):
    """search_chunks()와 같은 일을 NumPy로 '직접 계산'해서 보여주는 버전 (/search에서 사용)

    코사인 유사도 = (A · B) / (|A| × |B|)   → 두 벡터의 방향이 같을수록 1에 가까움
    벡터 DB(ChromaDB)는 내부에서 바로 이 계산을 빠르게 해 줍니다.
    """
    data = collection.get(include=["embeddings", "documents", "metadatas"])
    if len(data["ids"]) == 0:
        return []
    doc_vecs = np.array(data["embeddings"])               # (청크 수, 벡터 차원)
    q_vec = np.array(embed([question])[0])                # (벡터 차원,)

    scores = doc_vecs @ q_vec / (np.linalg.norm(doc_vecs, axis=1) * np.linalg.norm(q_vec))
    best = np.argsort(scores)[::-1][:top_k]               # 점수 높은 순서로 top_k개
    return [
        {"text": data["documents"][i], "source": data["metadatas"][i]["source"], "score": round(float(scores[i]), 4)}
        for i in best
    ]


@asynccontextmanager
async def lifespan(app):
    """서버가 켜질 때 한 번: DB를 새로 만들고 data 폴더의 문서를 모두 학습합니다."""
    global collection
    chroma = chromadb.PersistentClient(path=str(BASE_DIR / "chroma_data"))
    try:
        chroma.delete_collection("docs")                 # 지난번 내용은 지우고 data 폴더 기준으로 새로 만듭니다
    except Exception:
        pass                                             # 처음 실행이라 지울 것이 없음
    # hnsw:space=cosine → 거리를 '코사인 거리'로 계산 (1 - 거리 = 코사인 유사도)
    collection = chroma.create_collection("docs", metadata={"hnsw:space": "cosine"})

    print(f"LLM: {GPT_MODEL} / 임베딩: {EMBEDDING_MODEL}")
    if not GMS_KEY:
        print("[경고] GMS_KEY가 없어 문서를 학습하지 않았습니다. servers/.env 를 확인하세요.")
    else:
        for f in sorted(DATA_DIR.glob("*")):
            if f.suffix.lower() in ALLOWED_EXTENSIONS:
                try:
                    print(f"  [성공] {f.name} ({add_document(f.name, read_file(f.name, f.read_bytes()))}개 청크)")
                except HTTPException as e:
                    print(f"  [로드 실패] {f.name}: {e.detail}")
    print(f"준비 완료! (총 {collection.count()}개 청크) http://localhost:8000/docs")
    yield


# ==========================================
# 4. API
# ==========================================
app = FastAPI(title="SSAFY RAG Chatbot API", lifespan=lifespan)


@app.middleware("http")
async def catch_errors(request: Request, call_next):
    """예상 못한 오류도 {"detail": ...} JSON으로 응답 (그냥 두면 브라우저에는 'CORS 오류'로만 보입니다)"""
    try:
        return await call_next(request)
    except Exception as e:
        traceback.print_exc()                            # 서버 터미널에는 자세한 오류 출력
        return JSONResponse({"detail": f"서버 내부 오류: {e}"}, status_code=500)


# Live Server(127.0.0.1:5500)에서 이 서버(localhost:8000)로 요청할 수 있게 허용
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


class ChatReq(BaseModel):
    message: str = Field(min_length=1, max_length=2000, examples=["SSAFY 지각 기준 알려줘"])
    model_config = {"str_strip_whitespace": True}        # 공백만 보낸 질문은 거절


# [API 1] 일반 채팅
@app.post("/chat")
def chat(req: ChatReq):
    return {"answer": ask_gpt(req.message, CHAT_PROMPT)}


# [API 2] 문서 검색만 (GPT 없음) — 유사도를 NumPy로 직접 계산
@app.post("/search")
def search(req: ChatReq, top_k: int = Query(3, ge=1, le=10)):
    results = numpy_search(req.message, top_k)            # NumPy로 직접 계산 (RAG는 ChromaDB 사용)
    if not results:
        return {"answer": "DB가 비어있습니다. 문서를 업로드하세요.", "score": None, "source": None,
                "threshold": SIMILARITY_THRESHOLD, "results": []}

    best = results[0]
    found = best["score"] >= SIMILARITY_THRESHOLD
    return {
        "answer": best["text"] if found else "관련된 내용을 찾을 수 없습니다.",
        "score": best["score"],
        "source": best["source"] if found else None,
        "threshold": SIMILARITY_THRESHOLD,
        "results": results,
    }


# [API 3] RAG 채팅: ① 검색 → ② 기준 넘는 청크만 고르기 → ③ GPT에게 근거로 주고 답변 받기
@app.post("/integrated-chat")
def integrated_chat(req: ChatReq, n_results: int = Query(5, ge=1, le=8), debug: bool = False):
    candidates = search_chunks(req.message, n_results)                             # ①
    picked = [c for c in candidates if c["score"] >= SIMILARITY_THRESHOLD]          # ②

    if picked:
        context = "\n\n".join(f"[출처: {c['source']}]\n{c['text']}" for c in picked)
        source = ", ".join(dict.fromkeys(c["source"] for c in picked))           # 중복 제거
    else:
        context = "(관련 문서 없음)"
        source = "ChatGPT 일반 지식 (문서 미참고)"

    answer = ask_gpt(req.message, RAG_PROMPT.format(context=context))               # ③

    result = {
        "answer": answer,
        "source": source,
        "rag_used": bool(picked),                                                   # 문서를 참고했는지 (화면 배지)
        "references": [{"source": c["source"], "similarity": c["score"]} for c in picked],
    }
    if debug:                                                                       # ?debug=true → 검색 후보 전부 보기
        result["candidates"] = candidates
    return result


# [API 4] 문서 업로드
#   - HTML <form>으로 보내면(Step 2): 처리 후 원래 페이지로 되돌아감
#   - JavaScript fetch로 보내면(Step 3~): JSON으로 결과 응답
@app.post("/upload")
async def upload(request: Request, file: UploadFile = File(...)):
    filename = Path(file.filename or "").name          # '../' 같은 경로는 빼고 파일 이름만 사용
    if Path(filename).suffix.lower() not in ALLOWED_EXTENSIONS:
        raise HTTPException(400, "지원하지 않는 파일 형식입니다. (.txt, .md, .pdf 만 가능)")

    content = await file.read()
    if len(content) > MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(413, f"파일이 너무 큽니다. ({MAX_UPLOAD_MB}MB 이하만 가능)")

    try:
        text = read_file(filename, content)
    except Exception as e:
        raise HTTPException(400, f"파일을 읽을 수 없습니다: {e}")
    if not text.strip():
        raise HTTPException(400, "파일에서 글자를 찾을 수 없습니다. (스캔 이미지 PDF는 지원하지 않습니다)")

    count = add_document(filename, text)
    (DATA_DIR / filename).write_bytes(content)          # data 폴더에도 저장 → 서버를 다시 켜도 유지
    message = f"'{filename}' 학습 완료! ({count}개 청크)"
    print("[업로드]", message)

    referer = request.headers.get("referer")
    if "text/html" in request.headers.get("accept", "") and referer:   # <form> 제출이면 원래 페이지로
        return RedirectResponse(referer, status_code=303)
    return {"success": True, "message": message, "filename": filename, "chunks_added": count}


# [API 5] 학습된 문서 목록
@app.get("/documents")
def documents():
    counts = Counter(meta["source"] for meta in collection.get(include=["metadatas"])["metadatas"])
    return {
        "documents": [{"source": name, "chunks": n} for name, n in counts.items()],
        "total_chunks": sum(counts.values()),
    }


if __name__ == "__main__":
    import uvicorn

    # reload=True: main.py를 저장하면 서버가 자동으로 다시 켜집니다
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True, app_dir=str(BASE_DIR),
                reload_dirs=[str(BASE_DIR)],
                reload_excludes=[str(BASE_DIR / d) for d in ("venv", ".venv", "chroma_data") if (BASE_DIR / d).is_dir()])
