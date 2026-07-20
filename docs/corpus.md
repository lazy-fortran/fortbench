# Corpus

The active corpus contains 20 tasks drawn from 12 Fortran repositories
(`tasks/corpus-20-v1/`). Tasks include pre-copilot PRs (merged before
2022-06-21) and recent issues from actively maintained projects:

| Task | Repository | Source | Difficulty |
|---|---|---|---|
| `bspline-41-extrapolation-fix` | jacobwilliams/bspline-fortran | PR #41 | medium |
| `csv-fortran-21-real32-support` | jacobwilliams/csv-fortran | PR #21 | medium |
| `datetime-fortran-74-seconds-since-epoch` | wavebitscientific/datetime-fortran | PR #74 | small |
| `dop853-10-dense-output-step-size` | jacobwilliams/dop853 | PR #10 | medium |
| `json-fortran-454-get-path-array` | jacobwilliams/json-fortran | PR #454 | medium |
| `json-fortran-479-remove-pointer-fix` | jacobwilliams/json-fortran | PR #479 | medium |
| `json-fortran-504-exported-target` | jacobwilliams/json-fortran | PR #504 | medium |
| `json-fortran-570-trailing-comma` | jacobwilliams/json-fortran | PR #570 | small |
| `minpack-29-c-api-export` | fortran-lang/minpack | PR #29 | medium |
| `minpack-42-meson-build` | fortran-lang/minpack | PR #42 | small |
| `quadpack-22-dqnc79-intent-fix` | jacobwilliams/quadpack | PR #22 | small |
| `rklib-19-rkssp43-rkls54` | jacobwilliams/rklib | PR #19 | hard |
| `roots-fortran-26-itp-method-fix` | jacobwilliams/roots-fortran | PR #26 | medium |
| `roots-fortran-27-rbp-method` | jacobwilliams/roots-fortran | PR #27 | hard |
| `stdlib-543-string-concat` | fortran-lang/stdlib | PR #543 | small |
| `stdlib-600-iomsg-save-npy` | fortran-lang/stdlib | PR #600 | medium |
| `test-drive-18-fetch-no-ctest-leak` | fortran-lang/test-drive | PR #18 | small |
| `test-drive-42-junit-xml` | fortran-lang/test-drive | PR #42 | medium |
| `toml-f-104-key-path-api` | toml-f/toml-f | PR #104 | hard |
| `toml-f-55-escape-set-value` | toml-f/toml-f | PR #55 | medium |

All tasks require macOS-runnable builds and have deterministic validators.
Base commits are frozen; PR sources predate Copilot exposure on the
respective repositories so the corpus is not contaminated by training
data leakage from the answer set.

The legacy 10-task pilot remains frozen under `tasks/pilot/` for
historical reference.
