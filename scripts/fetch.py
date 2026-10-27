#!/usr/bin/env python3
"""국가법령정보센터(law.go.kr) 공식 Open API(DRF)에서 현행 법령·행정규칙 원문을 받아 raw/ 에 저장한다.

- 요청 간격은 최소 1.5초.
- 법령별 폴더: raw/<slug>/source.xml (받은 그대로), text.txt (검증용 평문), meta.json (출처·시행일)
- raw/index.json : 법령명 -> 폴더, 시행일, 출처 주소
law.go.kr 접속이 실패하면 다른 출처로 대체하지 않고 즉시 중단한다.
"""
import json
import re
import subprocess
import sys
import time
import urllib.parse
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "raw"
BASE = "https://www.law.go.kr/DRF"
OC = "test"  # law.go.kr DRF 공개 시험용 OC

LAWS = [
    # (slug, 공식 법령명)
    ("fire_facility_act", "소방시설 설치 및 관리에 관한 법률"),
    ("fire_facility_decree", "소방시설 설치 및 관리에 관한 법률 시행령"),
    ("fire_facility_rule", "소방시설 설치 및 관리에 관한 법률 시행규칙"),
    ("fire_prevention_act", "화재의 예방 및 안전관리에 관한 법률"),
    ("fire_prevention_decree", "화재의 예방 및 안전관리에 관한 법률 시행령"),
    ("fire_prevention_rule", "화재의 예방 및 안전관리에 관한 법률 시행규칙"),
    ("construction_act", "소방시설공사업법"),
    ("construction_decree", "소방시설공사업법 시행령"),
    ("multiuse_act", "다중이용업소의 안전관리에 관한 특별법"),
    ("multiuse_decree", "다중이용업소의 안전관리에 관한 특별법 시행령"),
    ("multiuse_rule", "다중이용업소의 안전관리에 관한 특별법 시행규칙"),
    ("building_evac_rule", "건축물의 피난ㆍ방화구조 등의 기준에 관한 규칙"),
]

CODES = ["101", "102", "103", "201", "202", "203", "301", "303", "304",
         "501", "502", "503", "504", "505"]

_last = [0.0]


def get(url: str) -> bytes:
    """1.5초 간격, 연결 끊김 시 최대 5회 재시도. 끝내 실패하면 중단."""
    for attempt in range(5):
        wait = 1.5 - (time.time() - _last[0])
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.time()
        p = subprocess.run(["curl", "-sS", "--max-time", "90", url], capture_output=True)
        if p.returncode == 0 and p.stdout:
            return p.stdout
        sys.stderr.write(f"  retry {attempt + 1}: {p.stderr.decode(errors='replace').strip()}\n")
        time.sleep(3 * (attempt + 1))
    sys.exit(f"law.go.kr 접속 실패, 중단: {url}")


def q(s: str) -> str:
    return urllib.parse.quote(s)


def norm_name(s: str) -> str:
    return re.sub(r"[\s·ㆍ]", "", s)


def search(target: str, query: str) -> list[dict]:
    url = f"{BASE}/lawSearch.do?OC={OC}&target={target}&type=XML&display=100&query={q(query)}"
    root = ET.fromstring(get(url))
    tag = "law" if target == "law" else "admrul"
    return [{c.tag: (c.text or "").strip() for c in el} for el in root.iter(tag)]


def text_of(el, path):
    return (el.findtext(path) or "").strip("\n")


def law_to_text(root) -> str:
    """법령 XML -> 줄 단위 평문. 조문·항·호·목은 한 줄씩, 별표는 원문 줄바꿈을 유지(뒤 공백만 제거)."""
    out = []
    for jo in root.iter("조문단위"):
        body = text_of(jo, "조문내용").strip()
        if jo.findtext("조문여부") == "전문":
            out.append(body)
            continue
        out.append(f"@@조 {jo.findtext('조문번호')}" + (f"의{jo.findtext('조문가지번호')}" if jo.findtext('조문가지번호') else ""))
        out.append(body)
        for hang in jo.findall("항"):
            if (h := text_of(hang, "항내용").strip()):
                out.append(h)
            for ho in hang.findall("호"):
                out.append(text_of(ho, "호내용").strip())
                for mok in ho.findall("목"):
                    for line in text_of(mok, "목내용").splitlines():
                        if line.strip():
                            out.append(line.strip())
    for byl in root.iter("별표단위"):
        if byl.findtext("별표구분") != "별표":
            continue
        no = int(byl.findtext("별표번호"))
        br = int(byl.findtext("별표가지번호") or 0)
        out.append(f"@@별표 {no}" + (f"의{br}" if br else ""))
        out.append(f"[별표 {no}{f'의{br}' if br else ''}] {byl.findtext('별표제목').strip()}")
        content = byl.findtext("별표내용") or ""
        for line in content.splitlines():
            if line.strip():
                out.append(line.rstrip())
    return "\n".join(out) + "\n"


def admrul_to_text(root) -> str:
    out = []
    for c in root.iter("조문내용"):
        for line in (c.text or "").splitlines():
            line = re.sub(r"<img[^>]*id=\"?(\d+)\"?[^>]*>", r"[이미지 \1]", line)
            line = line.replace("</img>", "").strip()
            if line:
                out.append(line)
    return "\n".join(out) + "\n"


def save(slug, name, kind, xml_bytes, text, meta):
    d = RAW / slug
    d.mkdir(parents=True, exist_ok=True)
    (d / "source.xml").write_bytes(xml_bytes)
    (d / "text.txt").write_text(text, encoding="utf-8")
    (d / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"saved {slug}: {name} 시행 {meta['as_of']} ({len(text)} chars)")


def fetch_law(slug, name):
    hits = [h for h in search("law", name)
            if norm_name(h.get("법령명한글", "")) == norm_name(name) and h.get("현행연혁코드") == "현행"]
    if len(hits) != 1:
        sys.exit(f"현행 법령 검색 결과가 1건이 아님: {name} -> {hits}")
    h = hits[0]
    url = f"{BASE}/lawService.do?OC={OC}&target=law&MST={h['법령일련번호']}&type=XML"
    xml_bytes = get(url)
    root = ET.fromstring(xml_bytes)
    info = root.find("기본정보")
    official = info.findtext("법령명_한글").strip()
    # law.go.kr 현행 화면의 [시행 YYYY. M. D.] 와 같은 값은 검색 결과의 시행일자다
    # (본문 XML의 시행일자는 전부개정 등 기본 시행일로 남아 있는 경우가 있음).
    ef = h["시행일자"]
    meta = {
        "law": official, "kind": info.findtext("법종구분"),
        "xml_effective": info.findtext("시행일자"),
        "as_of": f"{ef[:4]}-{ef[4:6]}-{ef[6:]}",
        "promulgation": f"{info.findtext('공포일자')} 제{info.findtext('공포번호')}호 ({info.findtext('제개정구분')})",
        "mst": h["법령일련번호"], "law_id": info.findtext("법령ID"),
        "byl_effective": info.findtext("별표시행일자문자열") or "",
        "fetched_url": url,
        "source_url": "https://www.law.go.kr/법령/" + official.replace(" ", ""),
        "fetched_at": time.strftime("%Y-%m-%d"),
    }
    save(slug, official, "law", xml_bytes, law_to_text(root), meta)
    return meta


def fetch_admrul(slug, kind, code):
    word = "화재안전성능기준" if kind == "NFPC" else "화재안전기술기준"
    cands = [h for h in search_cache(word)
             if re.search(rf"\({kind}\s*{code}\)", h.get("행정규칙명", "")) and h.get("현행연혁구분") == "현행"]
    if len(cands) != 1:
        sys.exit(f"현행 행정규칙 검색 결과가 1건이 아님: {kind} {code} -> {cands}")
    h = cands[0]
    url = f"{BASE}/lawService.do?OC={OC}&target=admrul&ID={h['행정규칙일련번호']}&type=XML"
    xml_bytes = get(url)
    root = ET.fromstring(xml_bytes)
    info = root.find("행정규칙기본정보")
    official = info.findtext("행정규칙명").strip()
    ef = info.findtext("시행일자")
    meta = {
        "law": official, "kind": info.findtext("행정규칙종류"),
        "as_of": f"{ef[:4]}-{ef[4:6]}-{ef[6:]}",
        "promulgation": f"{info.findtext('발령일자')} 제{info.findtext('발령번호')}호 ({info.findtext('제개정구분명')})",
        "admrul_seq": h["행정규칙일련번호"], "admrul_id": info.findtext("행정규칙ID"),
        "fetched_url": url,
        "source_url": "https://www.law.go.kr/행정규칙/" + official.replace(" ", ""),
        "fetched_at": time.strftime("%Y-%m-%d"),
    }
    save(slug, official, "admrul", xml_bytes, admrul_to_text(root), meta)
    return meta


_cache = {}


def search_cache(word):
    if word not in _cache:
        _cache[word] = search("admrul", word)
    return _cache[word]


def regen():
    """이미 받은 source.xml 에서 text.txt 만 다시 만든다(네트워크 사용 안 함)."""
    for d in sorted(RAW.iterdir()):
        if (d / "source.xml").exists():
            root = ET.parse(d / "source.xml").getroot()
            text = law_to_text(root) if root.tag == "법령" else admrul_to_text(root)
            (d / "text.txt").write_text(text, encoding="utf-8")


def main():
    if sys.argv[1:] == ["--regen"]:
        return regen()
    only = set(sys.argv[1:])
    index_path = RAW / "index.json"
    index = json.loads(index_path.read_text(encoding="utf-8")) if index_path.exists() else {}
    jobs = [(s, lambda s=s, n=n: fetch_law(s, n)) for s, n in LAWS]
    for c in CODES:
        for kind in ("NFPC", "NFTC"):
            s = f"{kind.lower()}_{c}"
            jobs.append((s, lambda s=s, k=kind, c=c: fetch_admrul(s, k, c)))
    for slug, fn in jobs:
        if only and slug not in only:
            continue
        meta = fn()
        index[meta["law"]] = {"dir": slug, "as_of": meta["as_of"], "source_url": meta["source_url"],
                              "fetched_url": meta["fetched_url"]}
        index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
