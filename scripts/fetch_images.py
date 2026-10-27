#!/usr/bin/env python3
"""NFPC·NFTC 본문에 그림으로만 들어 있는 표를 law.go.kr 에서 받아 raw/<폴더>/images/<id>.gif 로 저장한다.

본문 XML 의 <img id="N"> 는 law.go.kr flDownload.do?flSeq=N 파일이다. 요청 간격 1.5초.
받은 그림은 사람이 읽어 raw/<폴더>/tables.txt 에 옮겨 적는다(raw/TABLES.md 참고).
"""
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "raw"
URL = "https://www.law.go.kr/LSW/flDownload.do?flSeq={}"


def main():
    last = 0.0
    for d in sorted(RAW.glob("nf*_*")):
        ids = re.findall(r"<img id=\"(\d+)\"", (d / "source.xml").read_text(encoding="utf-8"))
        for i in ids:
            out = d / "images" / f"{i}.gif"
            if out.exists():
                continue
            out.parent.mkdir(exist_ok=True)
            for attempt in range(5):
                time.sleep(max(0.0, 1.5 - (time.time() - last)))
                last = time.time()
                p = subprocess.run(["curl", "-sS", "-L", "--max-time", "90", "-o", str(out), URL.format(i)],
                                   capture_output=True)
                if p.returncode == 0 and out.stat().st_size > 0:
                    break
                time.sleep(3 * (attempt + 1))
            else:
                sys.exit(f"law.go.kr 접속 실패, 중단: {URL.format(i)}")
            print(d.name, i, out.stat().st_size)


if __name__ == "__main__":
    main()
