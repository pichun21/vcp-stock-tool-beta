#!/usr/bin/env python3
from pathlib import Path
import argparse

MARKER='VCPulse BUILD 2.42.5 V2.8 THEME DB BETA + 2.42.2 OFFICIAL BACKFILL + 2.42.1 ALL-MARKET FIX + 2.39 OFFICIAL SAFETY GUARD'
OLD='        best=max(metas,key=lambda m:(m.get("confidence",0),m.get("purity",0)))\n        if best.get("confidence",0)<60:\n            return 0.0,[]\n        w=(\n            grade_w.get(best.get("grade"),0) *\n            (.40+.60*best.get("purity",0)/100) *\n            (.50+.50*best.get("confidence",0)/100)\n        )\n        return w,best.get("segments") or []'
NEW='        def meta_weight(m):\n            if m.get("confidence",0)<60:\n                return 0.0\n            return (\n                grade_w.get(m.get("grade"),0) *\n                (.40+.60*m.get("purity",0)/100) *\n                (.50+.50*m.get("confidence",0)/100)\n            )\n        # Alpha138 freeze: exact DEDUP_MAX for the five audited canonical families.\n        # All other themes preserve the V2.42.5 selector.\n        dedup_max_families={"重電/強韌電網","AI PCB","AI電力基建","國防航太","低軌衛星"}\n        if theme in dedup_max_families:\n            best=max(metas,key=meta_weight)\n        else:\n            best=max(metas,key=lambda m:(m.get("confidence",0),m.get("purity",0)))\n        w=meta_weight(best)\n        if w<=0:\n            return 0.0,[]\n        return w,best.get("segments") or []'

ap=argparse.ArgumentParser()
ap.add_argument("--input",default="scanner.py")
ap.add_argument("--output",required=True)
a=ap.parse_args()
s=Path(a.input).read_text(encoding="utf-8")
if MARKER not in s:
    raise SystemExit("STOP: expected V2.42.5 mother build marker not found")
if 'vcpulse_themes_v2_8_candidate.json' not in s:
    raise SystemExit("STOP: expected V2.8 theme DB binding not found")
if s.count(OLD)!=1:
    raise SystemExit(f"STOP: expected patch block once, found {s.count(OLD)}")
Path(a.output).parent.mkdir(parents=True,exist_ok=True)
Path(a.output).write_text(s.replace(OLD,NEW,1),encoding="utf-8")
print("PATCH PASS — V2.42.5 mother / V2.8 DB / one guarded block")
