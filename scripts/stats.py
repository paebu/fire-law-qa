#!/usr/bin/env python3
"""questions.jsonl 통계를 마크다운으로 출력한다(REPORT.md 작성용)."""
import collections
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import validate as V  # noqa: E402

BUNDLE_NAME = {
    "fire_facility": "소방시설법·시행령·시행규칙",
    "fire_prevention": "화재예방법·시행령·시행규칙",
    "construction_multiuse": "소방시설공사업법·다중이용업소법",
    "building": "건축물 피난·방화구조 규칙",
    "nfpc_nftc_a": "NFPC·NFTC (101·102·103·503)",
    "nfpc_nftc_b": "NFPC·NFTC (201·202·203·504·505)",
    "nfpc_nftc_c": "NFPC·NFTC (301·303·304·501·502)",
}
TYPES = ["설치기준", "설치대상", "점검관리", "면제특례", "복합"]


def lcs_len(a, b):
    """공백 제거 후 최장 공통 부분문자열 길이."""
    a, b = re.sub(r"\s", "", a), re.sub(r"\s", "", b)
    best, prev = 0, [0] * (len(b) + 1)
    for ca in a:
        cur = [0] * (len(b) + 1)
        for j, cb in enumerate(b, 1):
            if ca == cb:
                cur[j] = prev[j - 1] + 1
                best = max(best, cur[j])
        prev = cur
    return best


def table(rows, head):
    out = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


def main():
    qs = V.load_jsonl(ROOT / "questions.jsonl")
    meta = json.loads((ROOT / "drafts" / "meta.json").read_text(encoding="utf-8"))
    style = {int(k): v for k, v in meta["style"].items()}
    bundle = {int(k): v for k, v in meta["bundle"].items()}
    n = len(qs)

    print("### 묶음별 × 유형별 문항 수\n")
    rows = []
    for b, name in BUNDLE_NAME.items():
        c = collections.Counter(q["type"] for q in qs if bundle[q["qid"]] == b)
        rows.append([name] + [c[t] for t in TYPES] + [sum(c.values())])
    tot = collections.Counter(q["type"] for q in qs)
    rows.append(["**합계**"] + [f"{tot[t]} ({tot[t] * 100 // n}%)" for t in TYPES] + [n])
    print(table(rows, ["묶음", *TYPES, "계"]))

    print("\n### 정답 조문에 인용된 법령별 문항 수 (한 문항이 여러 법령을 인용하면 각각 계산)\n")
    by_law = collections.Counter()
    ess_law = collections.Counter()
    for q in qs:
        for law in {a["law"] for a in q["answers"]}:
            by_law[law] += 1
        for law in {a["law"] for a in q["answers"] if a["level"] == "essential"}:
            ess_law[law] += 1
    rows = [[law, V.INDEX[law]["as_of"], by_law[law], ess_law[law]] for law in V.INDEX if by_law[law]]
    print(table(rows, ["법령", "현행 시행일", "인용 문항", "필수로 인용"]))
    nf = sum(1 for q in qs if bundle[q["qid"]].startswith("nfpc_nftc"))
    print(f"\nNFPC·NFTC 묶음 문항: {nf}/{n} ({nf * 100 // n}%)")

    c = collections.Counter(style.values())
    print(f"\n### 질문 말투\n\n구어 {c['구어']} ({c['구어'] * 100 // n}%), 정형 {c['정형']}")
    law_word = [q["qid"] for q in qs if style[q["qid"]] == "구어"
                and re.search(r"법률|시행령|시행규칙|화재안전|NFPC|NFTC|제\d+조|별표", q["question"])]
    print(f"\n구어로 표시됐지만 법령명·조문번호가 들어간 문항: {law_word or '없음'}")

    ess = collections.Counter(sum(a["level"] == "essential" for a in q["answers"]) for q in qs)
    print(f"\n### 필수 조문 수 분포\n\n" + ", ".join(f"{k}개: {ess[k]}문항" for k in sorted(ess)))

    print("\n### 질문-인용문 어구 겹침(조문 베끼기 점검)\n")
    over = []
    for q in qs:
        m = max(lcs_len(q["question"], a["quote"]) for a in q["answers"])
        if m >= 12:
            over.append((q["qid"], m, q["question"]))
    print(f"질문과 인용문이 공백 제외 12자 이상 연속으로 겹치는 문항: {len(over)}개")
    for qid, m, t in over:
        print(f"- qid {qid} ({m}자): {t}")


if __name__ == "__main__":
    main()
