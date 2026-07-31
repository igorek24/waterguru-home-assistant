# Changelog

## 0.1.0 — 2026-07-31

Initial release. Verified against a live account with two SENSE pods.

- Cognito SRP authentication + SigV4 Lambda invocation, fully async
- Token caching and refresh (no re-login on every poll)
- Sensors: free chlorine, pH, skimmer flow, water temperature, status,
  last measurement; per pod: cassette, battery, Wi-Fi signal, last connection
- Binary sensors: water problem, cassette low, battery low
- Alerts and WaterGuru's chemical dosing advice exposed as attributes
- Multiple water bodies and multiple pods per account
- Config flow with re-auth, options (polling interval, temperature unit),
  `waterguru.refresh` service, diagnostics
