# Third-Party Notices

FortBench is MIT licensed. This file records the upstream repositories used as
benchmark task sources and the licenses identified for them at the time this
notice was written.

## Scope

FortBench does not vendor complete upstream source repositories as benchmark
fixtures. Instead, task manifests point to public repositories, issue/PR URLs,
and frozen commits; the harness clones those repositories during execution.

FortBench may contain:

- task metadata derived from issue/PR descriptions
- small benchmark validators and consumer fixtures
- generated benchmark reports that quote short issue/problem statements

If a future task copies a substantial upstream source excerpt into this
repository, the task directory should include a task-specific attribution note.

## Upstream task-source repositories

| Repository | URL | License status |
|---|---|---|
| `fortran-lang/fpm` | <https://github.com/fortran-lang/fpm> | MIT |
| `fortran-lang/minpack` | <https://github.com/fortran-lang/minpack> | MIT in upstream modern wrapper, plus preserved historical Minpack notice in upstream `LICENSE.txt` |
| `fortran-lang/test-drive` | <https://github.com/fortran-lang/test-drive> | Apache-2.0 |
| `fortran-lang/stdlib` | <https://github.com/fortran-lang/stdlib> | MIT |
| `jacobwilliams/json-fortran` | <https://github.com/jacobwilliams/json-fortran> | BSD-3-Clause-style upstream license, plus original FSON MIT notice preserved upstream |
| `toml-f/toml-f` | <https://github.com/toml-f/toml-f> | Apache-2.0 |
| `wavebitscientific/datetime-fortran` | <https://github.com/wavebitscientific/datetime-fortran> | MIT |
| `lazy-fortran/fortrun` | <https://github.com/lazy-fortran/fortrun> | MIT |
| `lazy-fortran/fortui` | <https://github.com/lazy-fortran/fortui> | No top-level license file detected in GitHub repository metadata during this pass |

## Notes

### `fortran-lang/minpack`

The upstream `LICENSE.txt` contains both an MIT grant for the modern wrapper
and an older retained Minpack/Argonne notice. Substantial direct copying from
upstream Minpack should preserve that upstream notice.

### `jacobwilliams/json-fortran`

The upstream `LICENSE` is BSD-3-Clause-style and also preserves the original
FSON MIT notice. Substantial direct copying from upstream JSON-Fortran should
preserve both notices where applicable.

### `lazy-fortran/fortui`

FortBench currently uses `fortui` issue/task metadata and benchmark scenarios.
Because no top-level license file was detected in repository metadata during
this review, direct source-code copying from `fortui` into FortBench should be
avoided unless upstream licensing is clarified.
