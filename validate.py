#!/usr/bin/env python3
"""questions.jsonl / split.json 을 raw/ 원문과 대조해 검사한다. 하나라도 어긋나면 종료코드 1.

검사 항목
  1. 스키마: qid, question, type, facility, answers, as_of, note
  2. answers[].law 가 raw/index.json 의 공식 법령명과 정확히 일치
  3. quote 길이 20~80자, raw/<법령>/text.txt 에 글자 그대로(띄어쓰기·괄호 포함) 존재
  4. quote 가 article 로 적은 조문 범위 안에 존재
     - 법령·NFPC: 제N조(의M) -> 제N항 -> 제N호 -> 가목 순으로 좁혀 확인
     - 별표: 해당 별표 전체
     - NFTC: 해당 번호(예 2.1.1.3)와 그 하위 번호 문단
  5. essential 1~3개, source_url·as_of 가 raw 메타데이터와 일치
  6. split.json: 모든 qid 가 train/test 중 정확히 한 곳, 두 쪽 크기 차 1 이하

사용법: python3 validate.py              (questions.jsonl + split.json)
        python3 validate.py --drafts drafts/*.jsonl   (초안 파일의 인용만 검사)
"""
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RAW = ROOT / "raw"
TYPES = {"설치기준", "설치대상", "점검관리", "면제특례", "복합"}
CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"
MOK = "가나다라마바사아자차카타파하"

INDEX = json.loads((RAW / "index.json").read_text(encoding="utf-8"))
_text_cache = {}
TABLE_PREFIX = "\u2063"  # 판독문 줄 표지(보이지 않는 문자). quote 비교 전에 떼어 낸다


def load_tables(d):
    """raw/<폴더>/tables.txt -> {이미지 id: [판독문 줄]} (raw/TABLES.md 참고)"""
    p = d / "tables.txt"
    blocks, cur = {}, None
    if p.exists():
        for ln in p.read_text(encoding="utf-8").split("\n"):
            if ln.startswith("@@이미지 "):
                cur = blocks.setdefault(ln.split()[1], [])
            elif cur is not None and ln.strip():
                cur.append(ln.rstrip())
    return blocks


def law_lines(law):
    """본문 줄 목록. [이미지 N] 줄 다음에 표 판독문 줄(표지 붙임)을 끼워 넣는다."""
    if law not in _text_cache:
        d = RAW / INDEX[law]["dir"]
        tables = load_tables(d)
        out = []
        for ln in (d / "text.txt").read_text(encoding="utf-8").split("\n"):
            out.append(ln)
            m = re.fullmatch(r"\[이미지 (\d+)\]", ln.strip())
            if m and m.group(1) in tables:
                out += [TABLE_PREFIX + t for t in tables[m.group(1)]]
        _text_cache[law] = out
    return _text_cache[law]


def plain(lines):
    return "\n".join(ln.lstrip(TABLE_PREFIX) for ln in lines)


def body_only(lines):
    return "\n".join(ln for ln in lines if not ln.startswith(TABLE_PREFIX))


TABLE_QUOTES = []  # (위치, 법령, quote) : 표 판독문에서만 찾은 인용


def is_nftc(law):
    return "(NFTC" in law


def is_nfpc(law):
    return "(NFPC" in law


# ---------- 조문 범위 찾기 ----------

ART_RE = re.compile(r"^제(\d+)조(?:의(\d+))?(?:제(\d+)항)?(?:제(\d+)호(?:의(\d+))?)?(?:([가-하])목)?$")
BYL_RE = re.compile(r"^별표 (\d+)(?:의(\d+))?(?:\s.*)?$")
NFTC_RE = re.compile(r"^\d+(?:\.\d+)+$")


def slice_until(lines, start, stop_pred):
    out = [lines[start]]
    for ln in lines[start + 1:]:
        if stop_pred(ln):
            break
        out.append(ln)
    return out


HEAD_RE = re.compile(r"^제\d+조(?:의\d+)?\([^)]*\)\s*")


def narrow_hang_ho(sec, hang, ho, ho_br, mok, where):
    """조 범위(sec) 안에서 항 -> 호 -> 목 순으로 좁힌다. 표지가 아예 없으면 넓은 범위를 그대로 쓴다."""
    # NFPC 는 "제4조(경계구역) ① ..." 처럼 제목 줄에 제1항이 붙어 있으므로 제목을 떼고 본다
    sec = [HEAD_RE.sub("", sec[0])] + sec[1:]
    if hang:
        mark = CIRCLED[int(hang) - 1]
        idx = [i for i, ln in enumerate(sec) if ln.lstrip().startswith(mark)]
        has_any = any(ln.lstrip()[:1] in CIRCLED for ln in sec)
        if idx:
            sec = slice_until(sec, idx[0], lambda ln: ln.lstrip()[:1] in CIRCLED)
        elif has_any or int(hang) > 1:
            return None, f"{where}: 제{hang}항을 찾을 수 없음"
    if ho:
        lab = f"{ho}의{ho_br}." if ho_br else f"{ho}."
        # "1.철망모르타르" 처럼 번호 뒤에 공백이 없는 원문도 있다
        idx = [i for i, ln in enumerate(sec) if re.match(rf"^\s*{re.escape(lab)}(?!\d)", ln)]
        if not idx:
            return None, f"{where}: 제{ho}호를 찾을 수 없음"
        sec = slice_until(sec, idx[0], lambda ln: re.match(r"^\s*\d+(?:의\d+)?\.(?!\d)", ln) is not None
                          or ln.lstrip()[:1] in CIRCLED)
    if mok:
        idx = [i for i, ln in enumerate(sec) if ln.lstrip().startswith(mok + ". ")]
        if not idx:
            return None, f"{where}: {mok}목을 찾을 수 없음"
        sec = slice_until(sec, idx[0], lambda ln: re.match(rf"^\s*[{MOK}]\.\s", ln) is not None)
    return sec, None


def section_for(law, article):
    """(범위 줄 목록, 오류문자열)"""
    lines = law_lines(law)
    article = article.strip()
    if is_nftc(law):
        if not NFTC_RE.match(article):
            return None, f"NFTC 조문 표기는 '2.1.1.3' 형식이어야 함: {article}"
        num_re = re.compile(r"^(\d+(?:\.\d+)*)\.?\s")
        idx = [i for i, ln in enumerate(lines) if (m := num_re.match(ln)) and m.group(1) == article]
        if not idx:
            return None, f"NFTC 번호 {article} 없음"

        def stop(ln):  # 같은 번호의 하위 번호(2.1.1.3.1 등)가 아닌 다음 번호 문단에서 끝
            m = num_re.match(ln)
            return bool(m) and m.group(1) != article and not m.group(1).startswith(article + ".")
        return slice_until(lines, idx[0], stop), None

    m = BYL_RE.match(article)
    if m and not is_nfpc(law):
        key = f"@@별표 {m.group(1)}" + (f"의{m.group(2)}" if m.group(2) else "")
        if key not in lines:
            return None, f"{key[2:]} 없음"
        i = lines.index(key)
        return slice_until(lines, i + 1, lambda ln: ln.startswith("@@")), None

    m = ART_RE.match(article)
    if not m:
        return None, f"조문 표기 형식 오류: {article}"
    jo, jo_br, hang, ho, ho_br, mok = m.groups()
    if is_nfpc(law):
        head = f"제{jo}조" + (f"의{jo_br}" if jo_br else "")
        idx = [i for i, ln in enumerate(lines) if ln.startswith(head + "(")]
        if not idx:
            return None, f"{head} 없음"
        sec = slice_until(lines, idx[0], lambda ln: re.match(r"^제\d+조(?:의\d+)?\(", ln) is not None)
    else:
        key = f"@@조 {jo}" + (f"의{jo_br}" if jo_br else "")
        if key not in lines:
            return None, f"제{jo}조{'의' + jo_br if jo_br else ''} 없음"
        i = lines.index(key)
        sec = slice_until(lines, i + 1, lambda ln: ln.startswith("@@"))
    return narrow_hang_ho(sec, hang, ho, ho_br, mok, article)


# ---------- 기대값 ----------

def expected_url(law, article):
    base = INDEX[law]["source_url"]
    m = ART_RE.match(article.strip())
    if m and not is_nfpc(law) and not is_nftc(law):
        return f"{base}/제{m.group(1)}조" + (f"의{m.group(2)}" if m.group(2) else "")
    return base


def expected_as_of(answers):
    return max(INDEX[a["law"]]["as_of"] for a in answers)


def split_of(questions):
    order = sorted(questions, key=lambda q: hashlib.sha256(q["question"].encode("utf-8")).hexdigest())
    half = len(order) // 2
    return {"train": sorted(q["qid"] for q in order[:half]),
            "test": sorted(q["qid"] for q in order[half:])}


# ---------- 검사 ----------

def check_answer(a, where, errors, full):
    law = a.get("law", "")
    if law not in INDEX:
        errors.append(f"{where}: 알 수 없는 법령명 '{law}'")
        return
    if a.get("level") not in ("essential", "useful"):
        errors.append(f"{where}: level 오류 {a.get('level')}")
    quote = a.get("quote", "")
    if not (20 <= len(quote) <= 80):
        errors.append(f"{where}: quote 길이 {len(quote)}자 (20~80자): {quote}")
    if "\n" in quote:
        errors.append(f"{where}: quote 에 줄바꿈 포함")
    whole = plain(law_lines(law))
    if quote not in whole:
        errors.append(f"{where}: 원문에 없는 quote [{law}] {quote}")
        return
    sec, err = section_for(law, a.get("article", ""))
    if err:
        errors.append(f"{where}: [{law}] {err}")
        return
    if quote not in plain(sec):
        errors.append(f"{where}: quote 가 [{law}] {a['article']} 범위 밖에 있음: {quote}")
    elif quote not in body_only(law_lines(law)):
        TABLE_QUOTES.append((where, law, quote))
    if full:
        exp = expected_url(law, a["article"])
        if a.get("source_url") != exp:
            errors.append(f"{where}: source_url 불일치 {a.get('source_url')} != {exp}")


def check_question(q, where, errors, warnings, full):
    for k in ("question", "type", "facility", "answers", "note") + (("qid", "as_of") if full else ()):
        if k not in q:
            errors.append(f"{where}: 필드 누락 {k}")
            return
    if q["type"] not in TYPES:
        errors.append(f"{where}: type 오류 {q['type']}")
    ans = q["answers"]
    ess = [a for a in ans if a.get("level") == "essential"]
    if not (1 <= len(ess) <= 3):
        errors.append(f"{where}: essential {len(ess)}개 (1~3개여야 함)")
    if not q["note"].strip():
        errors.append(f"{where}: note 비어 있음")
    seen = set()
    for j, a in enumerate(ans):
        check_answer(a, f"{where} answers[{j}]", errors, full)
        key = (a.get("law"), a.get("quote"))
        if key in seen:
            errors.append(f"{where}: 같은 quote 중복")
        seen.add(key)
    if full and all(a.get("law") in INDEX for a in ans) and ans:
        if q["as_of"] != expected_as_of(ans):
            errors.append(f"{where}: as_of {q['as_of']} != {expected_as_of(ans)}")
    # NFPC/NFTC 짝 확인(경고)
    codes = {}
    for a in ans:
        m = re.search(r"\((NFPC|NFTC)\s*(\d+)\)", a.get("law", ""))
        if m:
            codes.setdefault(m.group(2), set()).add(m.group(1))
    for c, kinds in codes.items():
        if len(kinds) == 1:
            warnings.append(f"{where}: {c} 기준이 {next(iter(kinds))} 쪽만 인용됨")


def load_jsonl(path):
    out = []
    for n, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if line.strip():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError as e:
                sys.exit(f"{path}:{n}: JSON 오류 {e}")
    return out


def main(argv):
    errors, warnings = [], []
    if argv[:1] == ["--drafts"]:
        n = 0
        for p in argv[1:]:
            for i, q in enumerate(load_jsonl(p), 1):
                check_question(q, f"{Path(p).name}#{i}", errors, warnings, full=False)
                n += 1
        report(errors, warnings, n)
        return
    qs = load_jsonl(ROOT / "questions.jsonl")
    qids = [q.get("qid") for q in qs]
    if qids != list(range(1, len(qs) + 1)):
        errors.append("qid 는 1부터 빈틈없이 증가해야 함")
    texts = [q.get("question") for q in qs]
    if len(set(texts)) != len(texts):
        errors.append("중복 질문 존재")
    for q in qs:
        check_question(q, f"qid {q.get('qid')}", errors, warnings, full=True)
    split = json.loads((ROOT / "split.json").read_text(encoding="utf-8"))
    tr, te = set(split.get("train", [])), set(split.get("test", []))
    if tr & te or (tr | te) != set(qids) or abs(len(tr) - len(te)) > 1:
        errors.append("split.json 이 train/test 반씩 빠짐없이 나뉘어 있지 않음")
    if split_of(qs) != {"train": sorted(tr), "test": sorted(te)}:
        errors.append("split.json 이 질문 해시 기준 분할과 다름")
    report(errors, warnings, len(qs))


def report(errors, warnings, n):
    for w in warnings:
        print("WARN ", w)
    for where, law, quote in TABLE_QUOTES:
        print("TABLE", f"{where}: 표 판독문 인용 [{law}] {quote}")
    for e in errors:
        print("FAIL ", e)
    print(f"\n문항 {n}개, 오류 {len(errors)}건, 경고 {len(warnings)}건, 표 판독 인용 {len(TABLE_QUOTES)}건")
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main(sys.argv[1:])
