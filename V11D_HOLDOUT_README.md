# VCPulse v1.1d Holdout Validation

Research only. Production scanner/UI are untouched.

Frozen candidates selected from v1.1c calibration:
- regression + ATR20/ATR60 <= 1.00 (primary)
- regression + ATR20/ATR60 <= 0.95
- first-vs-last + ATR20/ATR60 <= 1.00

Default holdout window: 2024-09-10 through 2025-09-09.
Do not change candidate definitions after seeing holdout results.
Compare against A_current_v1_0 using event-deduplicated 5/10/20-day return, positive rate, MAE and MFE.
