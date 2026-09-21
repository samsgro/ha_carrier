# Diagnostic fork install and rollback

This branch is `2.28.2+oauthdiag.1`. It is a diagnostics-only fork of
`ha_carrier` v2.28.2. Thermostat behavior, entities, and config flow are
unchanged. The only functional addition is a pinned `carrier-api`
diagnostic build that logs secret-safe OAuth refresh metadata.

## Pins

| Item | Value |
| --- | --- |
| `ha_carrier` version | `2.28.2+oauthdiag.1` |
| `carrier-api` version | `3.6.0+oauthdiag.1` |
| Immutable `carrier-api` commit | `84295ff294f0c97d7c978ca1ec0062f0587d3418` |
| `carrier-api` fork | https://github.com/samsgro/carrier_api/tree/oauth-refresh-diagnostics |
| `ha_carrier` fork | https://github.com/samsgro/ha_carrier/tree/oauth-refresh-diagnostics |

Manifest requirement:

```text
carrier-api @ git+https://github.com/samsgro/carrier_api.git@84295ff294f0c97d7c978ca1ec0062f0587d3418
```

That requirement is a PEP 508 direct URL pin. Home Assistant will install it
on the next integration setup or dependency repair. It is not the published
PyPI `carrier-api==3.6.0` wheel.

## What the diagnostics log

On token refresh, `carrier_api` logs only:

- HTTP status
- Content-Type
- Body class (`json_object`, `html`, `empty`, `malformed`, and similar)
- Body length and SHA-256
- Allowlisted OAuth `error` / `error_description`
- Allowlisted request IDs (`x-request-id`, `x-correlation-id`, `x-okta-request-id`, `request-id`)

It never logs username, password, access/refresh tokens, cookies, the
request body, `Authorization`, arbitrary headers, or the raw response body.

Look for lines starting with `Carrier OAuth token refresh response` in
Home Assistant logs (`carrier_api` logger). Enable debug logging on the
integration if you also want successful refresh records.

## Manual install into Home Assistant

Do this only when Sam is ready to deploy. This document does not restart or
reconfigure Home Assistant.

1. Copy `custom_components/ha_carrier` from this branch over the installed
   integration, typically
   `/config/custom_components/ha_carrier`.
2. Confirm `manifest.json` `version` is `2.28.2+oauthdiag.1` and
   `requirements` contains the git SHA above.
3. Restart Home Assistant (or repair the integration dependencies) so pip
   installs the pinned `carrier-api` commit.
4. Confirm the loaded package version is `3.6.0+oauthdiag.1`.

To install just the library in a clean Python 3.14 environment:

```bash
python3.14 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install \
  "carrier-api @ git+https://github.com/samsgro/carrier_api.git@84295ff294f0c97d7c978ca1ec0062f0587d3418"
.venv/bin/python -c "from carrier_api.const import VERSION; print(VERSION)"
```

Expected print: `3.6.0+oauthdiag.1`.

## Rollback

Restore the published HACS/upstream integration and PyPI library:

1. Replace `custom_components/ha_carrier` with upstream `ha_carrier` v2.28.2
   (HACS download or
   https://github.com/dahlb/ha_carrier/releases/tag/v2.28.2).
2. Confirm `manifest.json` has `"version": "2.28.2"` and
   `"carrier-api==3.6.0"`.
3. Restart Home Assistant so it reinstalls `carrier-api==3.6.0` from PyPI.

Library-only rollback:

```bash
.venv/bin/python -m pip install --force-reinstall "carrier-api==3.6.0"
```

No upstream pull request is opened by this diagnostic work.
