# VCPulse v1.1c Parameter Calibration

Research-only calibration. Production scanner/UI are untouched.

## Grid
- ATR20/ATR60: 0.80 / 0.85 / 0.90 / 0.95 / 1.00 / disabled
- Price contraction: strict / tolerant / regression / first-vs-last
- Total: 24 variants

All variants keep: liquidity, trend, >=2 contractions, volume dry-up, and clear Pivot trigger.
Consecutive qualifying dates for the same stock are deduplicated into one event.

This run is exploratory on the same historical period. A promising parameter set must pass a separate holdout/OOS validation before production adoption.
