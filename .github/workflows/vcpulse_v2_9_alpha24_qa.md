# V2.9 Alpha24 QA

Purpose: identify observable entry-day features that may flag Alpha23 lagging/overheated Theme Top5 entries.

Candidate features:
- prior 3-day return
- prior 5-day return
- Heat
- Setup
- Heat minus Setup
- entry rank
- active constituent count

Method:
- quartile lagging-rate diagnostics
- transparent one-feature threshold search
- no black-box model
- no score tuning

Guardrails:
- Heat/Setup formula changes: 0
- Grade/Purity/Confidence changes: 0
- taxonomy changes: 0
- production changes: 0
- V2.8 frozen baseline untouched
- no UI timing label should be deployed until an out-of-sample validation confirms the candidate rule
