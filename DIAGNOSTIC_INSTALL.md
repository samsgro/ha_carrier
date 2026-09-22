# Diagnostic fork install and rollback

This branch is `2.28.2+oauthdiag.3`. It is a diagnostic/fix fork of
`ha_carrier` v2.28.2. Thermostat entity logic and config-flow identity
are unchanged. The library pin is `carrier-api 3.6.0+oauthdiag.3` at an
immutable git SHA.

Always-on in this fork: token lock, single-flight refresh, and atomic
`TokenPair` install. Two **independently default-off** options:

- `early_refresh_canary` — one diagnostic refresh 30–60 seconds after login
- `invalid_grant_recovery` — `assistedLogin` fallback after a permanent
  refresh rejection

Recovery must stay off until the live evidence table in
`home-automation/reports/Carrier OAuth early-refresh canary implementation plan.md`
selects Path R.

## Pins

| Item | Value |
| --- | --- |
| `ha_carrier` version | `2.28.2+oauthdiag.3` |
| `carrier-api` version | `3.6.0+oauthdiag.3` |
| Immutable `carrier-api` commit | `f7c22aa8ac505984653cbde3ff21ae03cd254b47` |
| `carrier-api` fork | https://github.com/samsgro/carrier_api/tree/oauth-refresh-diagnostics |
| `ha_carrier` fork | https://github.com/samsgro/ha_carrier/tree/oauth-refresh-diagnostics |

Manifest requirement:

```text
carrier-api @ git+https://github.com/samsgro/carrier_api.git@f7c22aa8ac505984653cbde3ff21ae03cd254b47
```

That requirement is a PEP 508 direct URL pin. Home Assistant will install it
on the next integration setup or dependency repair. It is not the published
PyPI `carrier-api==3.6.0` wheel.

## What this fork adds

`oauthdiag.2` secret-safe OAuth refresh diagnostics are unchanged: HTTP
status, Content-Type, body class, length/SHA-256, allowlisted OAuth
`error` / `error_description`, and allowlisted request IDs. Logs never
include username, password, tokens, cookies, request bodies,
`Authorization`, arbitrary headers, or the raw response body.

`oauthdiag.3` adds a second allowlisted line for token-session
orchestration (`Carrier OAuth token session ...`) plus the lock/atomicity
layer. A failed canary does not write tokens and does not start Home
Assistant reauth.

## Manual install into Home Assistant

Do this only when Sam is ready to deploy. This document does not restart or
reconfigure Home Assistant.

1. Copy `custom_components/ha_carrier` from this branch over the installed
   integration, typically
   `/config/custom_components/ha_carrier`.
2. Confirm `manifest.json` `version` is `2.28.2+oauthdiag.3` and
   `requirements` contains the git SHA above.
3. Restart Home Assistant (or repair the integration dependencies) so pip
   installs the pinned `carrier-api` commit.
4. Confirm the loaded package version is `3.6.0+oauthdiag.3`.
5. Leave both new options off for the first observation window.

To install just the library in a clean Python 3.14 environment:

```bash
python3.14 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install \
  "carrier-api @ git+https://github.com/samsgro/carrier_api.git@f7c22aa8ac505984653cbde3ff21ae03cd254b47"
.venv/bin/python -c "from carrier_api.const import VERSION; print(VERSION)"
```

Expected print: `3.6.0+oauthdiag.3`.

## Rollback

Turning both options off and reloading is the **soft** rollback. Use it
only when the regression is canary- or recovery-flag behavior.

**Lock-layer regressions require a hard pin rollback.** Mixed pairs, a
stuck lock, flags-off entity loss, or unexpected `invalid_grant` from a
reused refresh token that the lock should have prevented are not fixed by
option toggles. Restore `oauthdiag.2` or upstream v2.28.2.

Hard rollback to `oauthdiag.2`:

1. Replace `custom_components/ha_carrier` with `2.28.2+oauthdiag.2`.
2. Confirm `manifest.json` has `"version": "2.28.2+oauthdiag.2"` and
   `carrier-api` pin `af96d9514a71a6050e6642e9e12d553bf7f41c08`.
3. Restart Home Assistant.

Hard rollback to published upstream:

1. Replace `custom_components/ha_carrier` with upstream `ha_carrier` v2.28.2
   (HACS download or
   https://github.com/dahlb/ha_carrier/releases/tag/v2.28.2).
2. Confirm `manifest.json` has `"version": "2.28.2"` and
   `"carrier-api==3.6.0"`.
3. Restart Home Assistant so it reinstalls `carrier-api==3.6.0` from PyPI.

Library-only rollback to `oauthdiag.2`:

```bash
.venv/bin/python -m pip install --force-reinstall \
  "carrier-api @ git+https://github.com/samsgro/carrier_api.git@af96d9514a71a6050e6642e9e12d553bf7f41c08"
```

Library-only rollback to published upstream:

```bash
.venv/bin/python -m pip install --force-reinstall "carrier-api==3.6.0"
```

No upstream pull request is opened by this diagnostic work.
