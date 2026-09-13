#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, difflib
from pathlib import Path
from collections import defaultdict

FAMILIES={"重電/強韌電網","AI PCB","AI電力基建","國防航太","低軌衛星"}
GRADE={"A":1.0,"B":.75,"C":.45,"D":.20}
MARKER="VCPulse BUILD 2.42 THEME BETA + 2.41 CAPITAL HOTSPOTS + 2.39 OFFICIAL SAFETY GUARD"

def weight(m):
    if float(m.get("confidence",0) or 0)<60:return 0.0
    return GRADE.get(m.get("grade"),0)*(.40+.60*float(m.get("purity",0) or 0)/100)*(.50+.50*float(m.get("confidence",0) or 0)/100)

def selector_audit(db):
    amap=((db.get("themeTaxonomy") or {}).get("alias_to_canonical") or {})
    grouped=defaultdict(list)
    for code,s in (db.get("stocks") or {}).items():
        for raw,m in (s.get("themes") or {}).items():
            can=amap.get(raw,raw)
            if can in FAMILIES:
                grouped[(str(code),can)].append((raw,m))
    rows=[]
    for (code,can),items in sorted(grouped.items()):
        if len(items)<2:continue
        old=max(items,key=lambda x:(x[1].get("confidence",0),x[1].get("purity",0)))
        new=max(items,key=lambda x:weight(x[1]))
        rows.append({
            "code":code,"canonical":can,"raw_count":len(items),
            "old_raw":old[0],"new_raw":new[0],
            "old_weight":round(weight(old[1]),6),"new_weight":round(weight(new[1]),6),
            "selector_changed":old[0]!=new[0]
        })
    return rows

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--before",required=True); ap.add_argument("--after",required=True)
    ap.add_argument("--theme-db",required=True); ap.add_argument("--out-dir",required=True)
    a=ap.parse_args()
    before=Path(a.before).read_text(encoding="utf-8")
    after=Path(a.after).read_text(encoding="utf-8")
    db=json.loads(Path(a.theme_db).read_text(encoding="utf-8"))
    out=Path(a.out_dir); out.mkdir(parents=True,exist_ok=True)

    if MARKER not in before or MARKER not in after:
        raise SystemExit("PARITY FAIL: build marker changed/missing.")
    if before==after:
        raise SystemExit("PARITY FAIL: patch made no change.")
    guard='dedup_max_families={"重電/強韌電網","AI PCB","AI電力基建","國防航太","低軌衛星"}'
    if after.count(guard)!=1:
        raise SystemExit("PARITY FAIL: Alpha138 family guard missing.")

    diff=list(difflib.unified_diff(before.splitlines(),after.splitlines(),
                                   fromfile="scanner_before.py",tofile="scanner_after.py",lineterm=""))
    changed=[x for x in diff if (x.startswith("+") or x.startswith("-")) and not x.startswith(("+++","---"))]
    allowed_tokens=("best=max(metas","meta_weight","dedup_max_families","if theme in dedup_max_families",
                    "w=meta_weight","if w<=0","Alpha138 freeze","canonical families",
                    "Other themes keep")
    suspicious=[]
    for line in changed:
        body=line[1:].strip()
        if not body or body.startswith("#"):
            continue
        if any(tok in body for tok in allowed_tokens):
            continue
        if body in (
            'if best.get("confidence",0)<60:return 0.0,[]',
            'w=grade_w.get(best.get("grade"),0)*(.40+.60*best.get("purity",0)/100)*(.50+.50*best.get("confidence",0)/100)'
        ):
            continue
        suspicious.append(line)
    if suspicious:
        raise SystemExit("PARITY FAIL: changes outside approved membership block:\n"+"\n".join(suspicious))

    audit=selector_audit(db)
    changed_pairs=[r for r in audit if r["selector_changed"]]
    report={
        "status":"PASS",
        "build_marker":MARKER,
        "production_patch":"Alpha138 DEDUP_MAX selector alignment",
        "audited_families":sorted(FAMILIES),
        "multi_membership_pairs_in_v2_6":len(audit),
        "pairs_where_exact_weight_selector_differs_from_old_selector":len(changed_pairs),
        "changed_pairs":changed_pairs,
        "diff_changed_lines":len(changed),
        "scope_guards":{
            "theme_score_formula_changed":False,
            "ui_changed":False,
            "schedule_changed":False,
            "data_source_changed":False,
            "theme_db_changed":False
        }
    }
    (out/"alpha138_production_parity.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    (out/"scanner_alpha138.patch").write_text("\n".join(diff)+"\n",encoding="utf-8")
    md=[
      "# Alpha138 Production Integration Preview","",
      "- Status: **PASS**",
      f"- V2.6 audited multi-membership stock×canonical pairs: **{len(audit)}**",
      f"- Pairs where old selector and exact membership-weight MAX choose different raw membership: **{len(changed_pairs)}**",
      "- Production mother build marker preserved.",
      "- Theme score formula / UI / schedule / data source / theme DB: **UNCHANGED**","",
      "## Selector differences"
    ]
    if changed_pairs:
        for r in changed_pairs:
            md.append(f"- {r['code']} {r['canonical']}: {r['old_raw']} ({r['old_weight']}) → {r['new_raw']} ({r['new_weight']})")
    else:
        md.append("- None. The code is now Alpha138-exact, but current V2.6 data produces the same selected raw membership.")
    (out/"alpha138_production_parity.md").write_text("\n".join(md),encoding="utf-8")
    print(json.dumps({"status":"PASS","multi_pairs":len(audit),"selector_changed_pairs":len(changed_pairs)},ensure_ascii=False))

if __name__=="__main__":
    main()
