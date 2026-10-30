# -*- coding: utf-8 -*-
"""
문서 처리 도구 — 파일 읽기 + 청크(조각)로 나누기

main.py가 사용하는 '도우미' 파일입니다. 수업에서는 이 파일을 자세히 읽지 않아도 됩니다.
  read_file(파일명, 바이트)  → 텍스트
  make_chunks(텍스트)        → ["[제목] 내용...", "[제목] 내용...", ...]

청크를 잘 나누는 것이 검색 품질을 크게 좌우합니다.
  1) <br>, &nbsp;, **, ` 같은 꾸밈 기호를 지웁니다.
  2) 표는 행마다 "[행 이름] 내용" 문장으로 바꿉니다. (행이 잘려도 무슨 내용인지 알 수 있게)
  3) 마크다운 제목(#)을 기준으로 절을 나누고, 줄 단위로 최대 size 글자까지 채웁니다.
  4) 각 청크 맨 앞에 [제목 경로]를 붙입니다.
"""
import html
import io
import re

import pypdf


# ------------------------------------------
# 1. 파일 읽기
# ------------------------------------------
def read_file(filename, content):
    """파일 내용(바이트)을 텍스트로 바꿉니다. (.pdf / .txt / .md)"""
    if filename.lower().endswith(".pdf"):
        reader = pypdf.PdfReader(io.BytesIO(content))
        # 이미지만 있는 페이지는 None이 나오므로 빈 문자열로 처리
        return "\n".join(page.extract_text() or "" for page in reader.pages)

    # 한글 txt는 UTF-8 또는 CP949(공공데이터포털 파일에 흔함) 두 가지가 많습니다.
    for encoding in ("utf-8-sig", "cp949"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            pass
    return content.decode("utf-8", errors="ignore")


# ------------------------------------------
# 2. 기호 정리 + 표를 문장으로 바꾸기
# ------------------------------------------
def _clean(text):
    text = html.unescape(text).replace("\xa0", " ").replace("**", "").replace("`", "")
    return re.sub(r"[ \t]+", " ", text).strip()


def _split_br(cell):
    """표 칸 안의 <br> 줄바꿈을 기준으로 나눕니다."""
    return [v for v in (_clean(x) for x in re.split(r"<br\s*/?>", cell, flags=re.I)) if v]


def _is_separator(line):
    """| :--- | :---: | 같은 표 구분선, 또는 --- 구분선"""
    return bool(re.fullmatch(r"\s*\|?[\s:\-|]+\|?\s*", line)) and "-" in line


def _cells(line):
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _table_row(header, cells):
    """표 한 행 → "[행 이름] 내용" 줄들
    예) | 공가 | • 국가 소집<br>• 본인 결혼 | 출석 인정 |
     →  [공가] 주요 내용: • 국가 소집 / [공가] • 본인 결혼 / [공가] 비고: 출석 인정
    """
    key = next((i for i, h in enumerate(header) if h.replace(" ", "") == "구분"), 0)
    label = " ".join(_split_br(cells[key])) if key < len(cells) else ""
    tag = f"[{label}] " if label else ""

    short, lines = [], []
    for i, cell in enumerate(cells):
        values = _split_br(cell)
        if i == key or not values or values == ["-"]:
            continue
        name = f"{header[i]}: " if i < len(header) and header[i] else ""
        if len(values) == 1:
            short.append(name + values[0])
        else:
            lines.append(tag + name + values[0])
            lines += [tag + v for v in values[1:]]
    if short:
        lines.insert(0, tag + " / ".join(short))
    return lines


def _clean_document(text):
    raw = text.splitlines()
    lines, i = [], 0
    while i < len(raw):
        if raw[i].strip().startswith("|") and i + 1 < len(raw) and _is_separator(raw[i + 1]):
            header = [" ".join(_split_br(c)) for c in _cells(raw[i])]
            i += 2
            while i < len(raw) and raw[i].strip().startswith("|"):
                lines += _table_row(header, _cells(raw[i]))
                i += 1
            continue
        if not _is_separator(raw[i]):
            lines += _split_br(raw[i])
        i += 1
    return lines


# ------------------------------------------
# 3. 제목별로 나누고 청크 만들기
# ------------------------------------------
def _split_long(line, size, overlap):
    """size보다 긴 줄(긴 문단)은 overlap만큼 겹치게 잘라 여러 줄로 만듭니다."""
    pieces = []
    while len(line) > size:
        pieces.append(line[:size])
        line = line[size - overlap:]
    return pieces + [line]


def make_chunks(text, size=250, overlap=50):
    """텍스트를 검색하기 좋은 크기의 청크 목록으로 나눕니다."""
    chunks, heads, current = [], [], []

    def save():
        if current:
            title = f"[{' > '.join(heads)}]\n" if heads else ""
            chunks.append(title + "\n".join(current))

    for line in _clean_document(text):
        heading = re.match(r"^(#{1,6})\s+(.*)", line)
        if heading:                                   # 새 제목이 나오면 지금까지 모은 청크 저장
            save()
            current = []
            level = len(heading.group(1))
            heads[:] = heads[:level - 1] + [heading.group(2)]
            continue

        for piece in _split_long(line, size, overlap):
            if current and len("\n".join(current + [piece])) > size:
                save()
                # 앞 청크의 마지막 줄이 짧으면 다음 청크에도 넣어 문맥을 이어줍니다.
                current = [current[-1]] if len(current[-1]) <= overlap else []
            current.append(piece)
    save()
    return chunks
