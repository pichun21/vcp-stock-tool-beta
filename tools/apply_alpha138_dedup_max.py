#!/usr/bin/env python3
from __future__ import annotations
import argparse
from pathlib import Path

EXPECTED_MARKER = "VCPulse BUILD 2.42 THEME BETA + 2.41 CAPITAL HOTSPOTS + 2.39 OFFICIAL SAFETY GUARD"

OLD = '''        if not metas: return 0.0,[]
        best=max(metas,key=lambda m:(m.get("confidence",0),m.get("purity",0)))
        if best.get("confidence",0)<60:return 0.0,[]
        w=grade_w.get(best.get("grade"),0)*(.40+.60*best.get("purity",0)/100)*(.50+.50*best.get("confidence",0)/100)
        return w,best.get("segments") or []'''

NEW = '''        if not metas: return 0.0,[]
        def meta_weight(m):
            if m.get("confidence",0)<60:return 0.0
            return grade_w.get(m.get("grade"),0)*(.40+.60*m.get("purity",0)/100)*(.50+.50*m.get("confidence",0)/100)
        # Alpha138 freeze: exact DEDUP_MAX is promoted only for the five audited
        # canonical families. Other themes keep the existing selector unchanged.
        dedup_max_families={"重電/強韌電網","AI PCB","AI電力基建","國防航太","低軌衛星"}
        if theme in dedup_max_families:
            best=max(metas,key=meta_weight)
        else:
            best=max(metas,key=lambda m:(m.get("confidence",0),m.get("purity",0)))
        w=meta_weight(best)
        if w<=0:return 0.0,[]
        return w,best.get("segments") or []'''

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--input",default="scanner.py")
    ap.add_argument("--output",required=True)
    a=ap.parse_args()
    src=Path(a.input).read_text(encoding="utf-8")
    if EXPECTED_MARKER not in src:
        raise SystemExit("STOP: scanner.py is not the expected V2.42 mother build.")
    n=src.count(OLD)
    if n != 1:
        raise SystemExit(f"STOP: expected membership block occurrence=1, actual={n}. Mother file may have changed.")
    out=src.replace(OLD,NEW,1)
    Path(a.output).parent.mkdir(parents=True,exist_ok=True)
    Path(a.output).write_text(out,encoding="utf-8")
    print("PATCH PASS: exactly one membership block changed.")
    print("Scope: audited canonical-family selector only; no score formula/UI/schedule/source changes.")

if __name__=="__main__":
    main()
