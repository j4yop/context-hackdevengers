# Releasing `contextgc`

The project has never been published. `pyproject.toml` says `0.4.0` and there
are no git tags, so `pip install contextgc` — which the README tells people to
run — does not work yet.

Everything except one step is done and verified. That step is PyPI account
configuration, and it has to be done in a browser.

## What is already verified

| gate | result |
|---|---|
| `python -m build` | `contextgc-0.4.0-py3-none-any.whl` + `.tar.gz` |
| full pipeline on CI | `release.yml` dry run, **success** |
| `twine check --strict` | PASSED on both artifacts |
| wheel installs into an empty venv | yes, from `site-packages` |
| wheel ships the schemas | `['coding', 'logistics', 'travel']` |
| wheel compiles with a shipped schema | `{'current_file': 'a/b.py'}` |
| value contracts reach an installed wheel | `['current_file', 'failing_test']` |
| the value gate works from an installed wheel | 1 wrong-shaped value reported |
| wheel scope | only `contextgc/` — no `benchmarks`, `server` or `web` leakage |
| sdist | carries schemas, README and LICENSE |
| `contextgc` on PyPI | HTTP 404 — the name is free |
| tag gate | `v0.4.0` matches `pyproject.toml`; `v0.4.1` would correctly fail |
| runtime dependencies | none, and the gate now actually asserts it |

The `release.yml` workflow runs these again on every tag, plus a check that the
version is not already on PyPI. Dispatch it with `dry_run` to rehearse the whole
pipeline without uploading.

## The one step that needs you

PyPI Trusted Publishing, so the workflow can mint a short-lived OIDC token
instead of the project holding a long-lived API token. **Verified 2026-09-28**
against the committed `release.yml`: the publish job requests exactly this
identity, and only a tag can reach it.

1. Sign in at <https://pypi.org/manage/account/publishing/>
2. **Add a new publisher** → **GitHub**
3. Fill in, copying these exactly — they are what the workflow's OIDC token
   will claim, and a mismatch fails with an error that reads like a permissions
   problem rather than a typo:

   | field | value |
   |---|---|
   | Owner | `j4yop` |
   | Repository name | `context-hackdevengers` |
   | Workflow name | `release.yml` |
   | Environment name | `pypi` |

4. Save.

The environment name must be `pypi`. The workflow's publish job declares
`environment: pypi`, and Trusted Publishing matches on the pair, so a mismatch
fails with an OIDC error that reads like a permissions problem.

Leave the pending-invitation field empty — the repository already exists, so
this registers a publisher for it rather than creating a project.

## Then release

```bash
# rehearse: builds, verifies, uploads nothing
gh workflow run release.yml -f dry_run=true

# publish
git tag v0.4.0
git push origin v0.4.0
```

The tag triggers `release.yml`, which builds, verifies, checks PyPI for a
collision, and publishes. Watch it with `gh run watch`.

## If you would rather use an API token

Set the repository secret `PYPI_API_TOKEN` instead. The workflow prefers it when
present, so no other change is needed. A token is a long-lived credential in
secret storage; Trusted Publishing is the better default and is what the
workflow is built around.

## After the first release

The version in `pyproject.toml` and the git tag must agree, or the tag gate
fails. Bump the version in the same commit that needs it — there is no separate
changelog step, and the release commit message is the changelog.

A release cannot be reused: the publish job checks PyPI first and refuses if that
version already exists, rather than silently overwriting.
