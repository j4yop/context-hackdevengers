# Releasing `contextgc`

`contextgc` 0.4.1 and 0.4.2 are on PyPI and `pip install contextgc` works. This
page records how, and what the next release has to reproduce.

## What is already verified

| gate | result |
|---|---|
| `python -m build` | `contextgc-0.4.2-py3-none-any.whl` + `.tar.gz` |
| full pipeline on CI | `release.yml` dry run, **success** |
| `twine check --strict` | PASSED on both artifacts |
| wheel installs into an empty venv | yes, from `site-packages` |
| wheel ships the schemas | `['coding', 'logistics', 'travel']` |
| wheel compiles with a shipped schema | `{'current_file': 'a/b.py'}` |
| value contracts reach an installed wheel | coding, 7 travel slots, 2 logistics |
| the value gate works from an installed wheel | 1 wrong-shaped value reported |
| wheel scope | only `contextgc/` — no `benchmarks`, `server` or `web` leakage |
| sdist | carries schemas, README and LICENSE |
| `contextgc` on PyPI | 0.4.1 and 0.4.2 published, installable, no dependencies |
| `__version__` in the installed wheel | matches `pyproject.toml` — it was a stale literal, fixed in 0.4.2 |
| tag gate | tag must equal the `pyproject.toml` version, or the build fails |
| no-credential release | 0.4.2 published with `gh secret list` empty |
| runtime dependencies | none, and the gate now actually asserts it |

The `release.yml` workflow runs these again on every tag, plus a check that the
version is not already on PyPI. Dispatch it with `dry_run` to rehearse the whole
pipeline without uploading.

## PyPI account configuration, already done

PyPI Trusted Publishing, so the workflow mints a short-lived OIDC token instead
of the project holding a long-lived API token. **Configured 2026-09-28** and
verified by publishing 0.4.2 with no secret stored in the repository.

There is a step here that is easy to get wrong, and it cost three failed
uploads. An OIDC identity **cannot create a project** — it can only upload to
one. So there are two different publisher pages, and they are not
interchangeable:

| page | what it registers | when it is the right one |
|---|---|---|
| `pypi.org/manage/account/publishing/` | a **pending** publisher, bound to no project | before the project exists |
| `pypi.org/manage/project/<name>/settings/publishing/` | a **project** publisher | the one that mints a project-scoped token |

Registering only the first gets you `403 OIDC scoped token is not valid for
project '<name>'` on every upload, with no hint that a second publisher was
needed. 0.4.1 was created with a scoped API token, which *can* create a project;
that token was then deleted, and 0.4.2 published through Trusted Publishing.

1. Sign in at <https://pypi.org/manage/project/contextgc/settings/publishing/>
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

The publisher must be added on the **project's** page, not the account page.

Note that `https://pypi.org/project/create/` is not the create form — PyPI
resolves it to a package that happens to be called `create`, and shows you that
package instead of a form.

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
