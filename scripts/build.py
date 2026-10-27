#!/usr/bin/env python3
"""drafts/*.jsonl 초안을 합쳐 questions.jsonl, split.json 을 만든다.

초안 한 줄: {"question","type","facility","answers":[{"law","article","level","quote"}],"note", "style"(선택)}
- qid 는 BUNDLES 순서대로 1부터 부여
- source_url, as_of 는 raw/index.json 에서 채움 (validate.py 와 같은 규칙)
- style(구어/정형) 은 통계용이라 drafts/style.json 으로만 남기고 questions.jsonl 에는 넣지 않음
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import validate as V  # noqa: E402

BUNDLES = ["fire_facility", "fire_prevention", "construction_multiuse", "building",
           "nfpc_nftc_a", "nfpc_nftc_b", "nfpc_nftc_c"]
FIELDS = ["qid", "question", "type", "facility", "answers", "as_of", "note"]


def main():
    out, style, bundle_of = [], {}, {}
    for b in BUNDLES:
        p = ROOT / "drafts" / f"{b}.jsonl"
        if not p.exists():
            continue
        for d in V.load_jsonl(p):
            qid = len(out) + 1
            answers = [{"law": a["law"], "article": a["article"], "level": a["level"], "quote": a["quote"],
                        "source_url": V.expected_url(a["law"], a["article"])} for a in d["answers"]]
            q = {"qid": qid, "question": d["question"], "type": d["type"], "facility": d.get("facility", ""),
                 "answers": answers, "as_of": V.expected_as_of(answers), "note": d["note"]}
            out.append({k: q[k] for k in FIELDS})
            style[qid] = d.get("style", "")
            bundle_of[qid] = b
    (ROOT / "questions.jsonl").write_text(
        "".join(json.dumps(q, ensure_ascii=False) + "\n" for q in out), encoding="utf-8")
    (ROOT / "split.json").write_text(json.dumps(V.split_of(out), ensure_ascii=False) + "\n", encoding="utf-8")
    (ROOT / "drafts" / "meta.json").write_text(
        json.dumps({"style": style, "bundle": bundle_of}, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"{len(out)} questions")


if __name__ == "__main__":
    main()
