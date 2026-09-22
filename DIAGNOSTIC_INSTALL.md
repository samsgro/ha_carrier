# Production-fix install and rollback

This branch is `2.28.2+oauthfix.1`. It is a production-fix fork of
`ha_carrier` v2.28.2. Thermostat entity logic and config-flow identity
are unchanged. The library pin is `carrier-api 3.6.0+oauthfix.1` at an
immutable git SHA.

Always-on in this fork: token lock, single-flight refresh, atomic
`TokenPair` install, and `invalid_grant` recovery. Early-refresh canary,
pre-expiry scheduling, and OAuth experiment options are removed. Stale
stored option keys (`early_refresh_canary`, `invalid_grant_recovery`)
may remain in a config entry until the options form is next saved;
runtime code ignores them.

## Pins

| Item | Value |
| --- | --- |
| `ha_carrier` version | `2.28.2+oauthfix.1` |
| `carrier-api` version | `3.6.0+oauthfix.1` |
| Immutable `carrier-api` commit | `bf759dcd7a5fe839202377559e2d16ede1c934bb` |
| `carrier-api` fork | https://github.com/samsgro/carrier_api/tree/oauth-refresh-diagnostics |
| `ha_carrier` fork | https://github.com/samsgro/ha_carrier/tree/oauth-refresh-diagnostics |

Manifest requirement:

```text
carrier-api @ git+https://github.com/samsgro/carrier_api.git@bf759dcd7a5fe839202377559e2d16ede1c934bb
```

That requirement is a PEP 508 direct URL pin. Home Assistant will install it
on the next integration setup or dependency repair. It is not the published
PyPI `carrier-api==3.6.0` wheel.

## Production behavior

At access-token expiry the library attempts the refresh grant once. On
HTTP 400 `invalid_grant` or token-endpoint HTTP 401/403 it suppresses
that refresh token and runs up to three `assistedLogin` attempts with 1s
then 3s backoff. Transient transport, timeout, GraphQL transport/server,
and malformed successful-token payload failures retry. Explicit
`assistedLogin success=false` is credential rejection and starts Home
Assistant reauthentication. `invalid_client` and `unauthorized_client`
never fall back to login. Three transient login failures keep the atomic
token pair, keep the dead refresh fingerprint suppressed, and raise a
retryable connection/token-refresh error.

Secret-safe OAuth refresh diagnostics are unchanged: HTTP status,
Content-Type, body class, length/SHA-256, allowlisted OAuth `error` /
`error_description`, and allowlisted request IDs. Logs never include
username, password, tokens, cookies, request bodies, `Authorization`,
arbitrary headers, or the raw response body.

## Manual install into Home Assistant

Do this only when Sam is ready to deploy. This document does not restart
or reconfigure Home Assistant.

1. Take a fresh Home Assistant backup.
2. Copy `custom_components/ha_carrier` from this branch over the installed
   integration, typically `/config/custom_components/ha_carrier`.
3. Confirm `manifest.json` `version` is `2.28.2+oauthfix.1` and
   `requirements` contains the git SHA from this branch.
4. Restart Home Assistant (or repair the integration dependencies) so pip
   installs the pinned `carrier-api` commit.
5. Confirm the loaded package version is `3.6.0+oauthfix.1`.
6. Observe at least two expiry cycles for one refresh rejection followed
   by first-attempt assisted-login success, no outage, no storm, and no
   reauth.

To install just the library in a clean Python 3.14 environment, use the
SHA from `manifest.json`:

```bash
python3.14 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install \
  "carrier-api @ git+https://github.com/samsgro/carrier_api.git@bf759dcd7a5fe839202377559e2d16ede1c934bb"
.venv/bin/python -c "from carrier_api.const import VERSION; print(VERSION)"
```

Expected print: `3.6.0+oauthfix.1`.

## Rollback

There is no option toggle for recovery. Use a hard pin rollback.

Hard rollback to `oauthdiag.3`:

1. Replace `custom_components/ha_carrier` with `2.28.2+oauthdiag.3`.
2. Confirm `manifest.json` has `"version": "2.28.2+oauthdiag.3"` and
   `carrier-api` pin `f7c22aa8ac505984653cbde3ff21ae03cd254b47`.
3. Restart Home Assistant.

Hard rollback to published upstream:

1. Replace `custom_components/ha_carrier` with upstream `ha_carrier` v2.28.2
   (HACS download or
   https://github.com/dahlb/ha_carrier/releases/tag/v2.28.2).
2. Confirm `manifest.json` has `"version": "2.28.2"` and
   `"carrier-api==3.6.0"`.
3. Restart Home Assistant so it reinstalls `carrier-api==3.6.0` from PyPI.

Library-only rollback to `oauthdiag.3`:

```bash
.venv/bin/python -m pip install --force-reinstall \
  "carrier-api @ git+https://github.com/samsgro/carrier_api.git@f7c22aa8ac505984653cbde3ff21ae03cd254b47"
```

Library-only rollback to published upstream:

```bash
.venv/bin/python -m pip install --force-reinstall "carrier-api==3.6.0"
```

No upstream pull request is opened by this production-fix work.
