#!/usr/bin/env python3
from pathlib import Path
import argparse, difflib, json, py_compile

MARKER='VCPulse BUILD 2.42.5 V2.8 THEME DB BETA + 2.42.2 OFFICIAL BACKFILL + 2.42.1 ALL-MARKET FIX + 2.39 OFFICIAL SAFETY GUARD'
ap=argparse.ArgumentParser()
ap.add_argument("--before",required=True)
ap.add_argument("--after",required=True)
ap.add_argument("--out-dir",required=True)
a=ap.parse_args()
b=Path(a.before).read_text(encoding="utf-8")
n=Path(a.after).read_text(encoding="utf-8")
out=Path(a.out_dir); out.mkdir(parents=True,exist_ok=True)

checks={
 "mother_marker_preserved": MARKER in b and MARKER in n,
 "theme_db_v28_preserved": 'THEME_DB = ROOT / "data" / "vcpulse_themes_v2_8_candidate.json"' in b and 'THEME_DB = ROOT / "data" / "vcpulse_themes_v2_8_candidate.json"' in n,
 "alpha138_guard_once": n.count('dedup_max_families={"重電/強韌電網","AI PCB","AI電力基建","國防航太","低軌衛星"}')==1,
 "capital_hotspots_preserved": "def build_capital_hotspots" in b and "def build_capital_hotspots" in n,
 "official_guard_preserved": "TW OFFICIAL GUARD" in b and "TW OFFICIAL GUARD" in n,
 "theme_backfill_preserved": "TW THEME BACKFILL" in b and "TW THEME BACKFILL" in n,
 "us_universe_preserved": "def fetch_us_universe" in b and "def fetch_us_universe" in n,
}
py_compile.compile(a.after,doraise=True)
diff=list(difflib.unified_diff(b.splitlines(),n.splitlines(),fromfile="scanner_before.py",tofile="scanner_after.py",lineterm=""))
# Exact patch guarantee: rebuilding expected text must equal after.
expected=b.replace('        best=max(metas,key=lambda m:(m.get("confidence",0),m.get("purity",0)))\n        if best.get("confidence",0)<60:\n            return 0.0,[]\n        w=(\n            grade_w.get(best.get("grade"),0) *\n            (.40+.60*best.get("purity",0)/100) *\n            (.50+.50*best.get("confidence",0)/100)\n        )\n        return w,best.get("segments") or []','        def meta_weight(m):\n            if m.get("confidence",0)<60:\n                return 0.0\n            return (\n                grade_w.get(m.get("grade"),0) *\n                (.40+.60*m.get("purity",0)/100) *\n                (.50+.50*m.get("confidence",0)/100)\n            )\n        # Alpha138 freeze: exact DEDUP_MAX for the five audited canonical families.\n        # All other themes preserve the V2.42.5 selector.\n        dedup_max_families={"重電/強韌電網","AI PCB","AI電力基建","國防航太","低軌衛星"}\n        if theme in dedup_max_families:\n            best=max(metas,key=meta_weight)\n        else:\n            best=max(metas,key=lambda m:(m.get("confidence",0),m.get("purity",0)))\n        w=meta_weight(best)\n        if w<=0:\n            return 0.0,[]\n        return w,best.get("segments") or []',1)
checks["exact_expected_patch_only"]=(expected==n and b.count('        best=max(metas,key=lambda m:(m.get("confidence",0),m.get("purity",0)))\n        if best.get("confidence",0)<60:\n            return 0.0,[]\n        w=(\n            grade_w.get(best.get("grade"),0) *\n            (.40+.60*best.get("purity",0)/100) *\n            (.50+.50*best.get("confidence",0)/100)\n        )\n        return w,best.get("segments") or []')==1)
status="PASS" if all(checks.values()) else "FAIL"
report={"status":status,"checks":checks,"changed_diff_lines":sum(1 for x in diff if x.startswith(("+","-")) and not x.startswith(("+++","---")))}
(out/"alpha138_production_parity.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
(out/"scanner_alpha138.patch").write_text("\n".join(diff)+"\n",encoding="utf-8")
(out/"alpha138_production_parity.md").write_text("# Alpha138 Production Parity\n\nStatus: **"+status+"**\n\n"+"\n".join(f"- {k}: {'PASS' if v else 'FAIL'}" for k,v in checks.items())+"\n",encoding="utf-8")
print(json.dumps(report,ensure_ascii=False))
if status!="PASS": raise SystemExit(1)
