# OAuth refresh diagnostics — builder report

Date: 2026-09-21  
Worker: Orca dispatched builder (`task_64b9f370bb93`)  
Scope: diagnostic forks only. Home Assistant was not restarted or
redeployed. Thermostat, entity, and config-flow code were not changed.

## Outcome

`carrier_api` `3.6.0+oauthdiag.2` now consumes the OAuth refresh JSON/body
before aiohttp `raise_for_status` can release it. Exception classification
matches v3.6.0 except `invalid_grant` still becomes `CarrierApiAuthError`.
Secret-safe diagnostics and raw-body hashing are preserved.

`ha_carrier` `2.28.2+oauthdiag.2` pins that library by immutable commit.
No thermostat, entity, or config-flow behavior changed.

## Forks and commits

| Repo | Upstream tag | Fork | Branch | Verified head |
| --- | --- | --- | --- | --- |
| `carrier_api` | v3.6.0 (`43f9ddcbcbb026ca97333db0c9908751f459bcaf`) | https://github.com/samsgro/carrier_api | `oauth-refresh-diagnostics` | `af96d9514a71a6050e6642e9e12d553bf7f41c08` |
| `ha_carrier` | v2.28.2 (`533a4f471a1e8bcf7d18d6af93651fe240124f37`) | https://github.com/samsgro/ha_carrier | `oauth-refresh-diagnostics` | recorded after this commit is pushed |

`carrier_api` code fix commit: `8b938f201c140ca80c6530b6c8c96dd0128105d9`.  
`carrier_api` docs/pin commit (branch tip): `af96d9514a71a6050e6642e9e12d553bf7f41c08`.

Previous reviewed `oauthdiag.1` heads were `84295ff…` and `5833c75…`.
This follow-up keeps those commits in history and adds the body-consume
fix.

Diagnostic versions:

- `carrier-api==3.6.0+oauthdiag.2`
- `ha_carrier==2.28.2+oauthdiag.2`

Immutable library pin used by `ha_carrier`:

```text
carrier-api @ git+https://github.com/samsgro/carrier_api.git@af96d9514a71a6050e6642e9e12d553bf7f41c08
```

No upstream pull requests were opened. No release was created.

## What changed in `carrier_api`

`refresh_auth_token` now reads raw body bytes and JSON before
`raise_for_status`. aiohttp releases an unread payload when it raises, so
the previous order lost `invalid_grant` classification and body hashes.

Classification is unchanged:

- HTTP 401/403 → `CarrierApiAuthError`
- HTTP 400 with `error == invalid_grant` → `CarrierApiAuthError`
- other HTTP 400 JSON errors → `CarrierApiTokenRefreshError`
- transport/parse/malformed-success failures → `CarrierApiTokenRefreshError`

All HTTP 400 responses are not treated as auth failures.

Logged fields only:

- HTTP status
- Content-Type
- body class
- body length and SHA-256
- allowlisted OAuth `error` / `error_description`
- allowlisted request IDs: `x-request-id`, `x-correlation-id`,
  `x-okta-request-id`, `x-okta-requestid`, `request-id`

Never logged: username, password, access/refresh tokens, cookies,
request body, `Authorization`, arbitrary headers, or raw response body.

## Tests

`carrier_api` lint, mypy, and pytest were run in a local Python 3.14
venv (`scripts/lint`, `scripts/test`).

```text
ruff check / ruff format / mypy: passed
206 passed in 0.41s
TOTAL coverage 90%
```

Regression coverage:

- releasing fake proves `json()` / `read()` fail after `raise_for_status`
- pre-raise capture still classifies `invalid_grant` as
  `CarrierApiAuthError` and logs `body_sha256`
- other JSON 400 (`temporarily_unavailable`) remains
  `CarrierApiTokenRefreshError` after the same body release

A clean Python 3.14 virtualenv installed the pinned commit:

```text
clean_pin 3.6.0+oauthdiag.2
```

`ha_carrier` was run on Python 3.14 with Home Assistant 2026.9.3:

```text
prek: passed
mypy: 3 pre-existing errors (same on main; not introduced here)
180 passed in 8.69s
TOTAL coverage 84%
```

`custom_components/` diff is version + requirement only.

## Changed files

### `carrier_api`

- `README.md`
- `src/carrier_api/api_connection_graphql.py`
- `src/carrier_api/const.py`
- `src/carrier_api/oauth_refresh_diagnostics.py`
- `tests/test_api_connection_graphql.py`
- `tests/test_oauth_refresh_diagnostics.py`

### `ha_carrier`

- `README.md`
- `DIAGNOSTIC_INSTALL.md`
- `pyproject.toml`
- `custom_components/ha_carrier/const.py`
- `custom_components/ha_carrier/manifest.json`
- `reports/oauth-refresh-diagnostics.md` (this file)

## Deployment and rollback

Not deployed. When Sam is ready, follow
`https://github.com/samsgro/ha_carrier/blob/oauth-refresh-diagnostics/DIAGNOSTIC_INSTALL.md`.

Short form:

1. Copy this branch's `custom_components/ha_carrier` into Home Assistant.
2. Restart or repair dependencies so pip installs the git SHA pin.
3. Confirm `carrier-api` version `3.6.0+oauthdiag.2`.
4. Watch for `Carrier OAuth token refresh response` log lines.

Rollback: restore upstream `ha_carrier` v2.28.2 and
`carrier-api==3.6.0` from PyPI, then restart.

## What's left

- Deploy to Home Assistant only when Sam asks.
- No upstream PRs.
- No release.
