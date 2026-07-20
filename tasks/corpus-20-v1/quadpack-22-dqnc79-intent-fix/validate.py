from __future__ import annotations

import glob
import subprocess
import sys
import tempfile
from pathlib import Path

PROGRAM = r"""program check_dqnc79
  use quadpack, only: dqnc79
  implicit none

  integer, parameter :: dp = selected_real_kind(15)
  real(dp) :: ans, err_out
  integer :: ierr, k
  real(dp), parameter :: tol = 1.0e-10_dp
  real(dp), parameter :: exact = 2.0_dp
  real(dp), parameter :: check_tol = 1.0e-6_dp

  call dqnc79(fsin, 0.0_dp, acos(-1.0_dp), tol, ans, ierr, k)

  if (abs(ans - exact) > check_tol) then
    print *, 'FAIL: integral of sin(x) from 0 to pi =', ans, ' expected', exact
    error stop 1
  end if
  if (ierr /= 1) then
    print *, 'FAIL: ierr =', ierr, ' expected 1 (normal return)'
    error stop 2
  end if

  print *, 'PASS'

contains

  function fsin(x) result(f)
    real(dp), intent(in) :: x
    real(dp) :: f
    f = sin(x)
  end function fsin

end program check_dqnc79
"""


def find_fpm_artifacts(build_dir: Path, lib_name: str) -> tuple[Path, Path]:
    """Find the fpm library archive and module directory."""
    archives = list(build_dir.glob(f"*/{lib_name}/lib{lib_name}.a"))
    if not archives:
        raise FileNotFoundError(f"lib{lib_name}.a not found under {build_dir}")
    archive = archives[0]
    mod_dirs = list(build_dir.glob("*/*.mod"))
    if not mod_dirs:
        raise FileNotFoundError(f"No .mod files found under {build_dir}")
    mod_dir = mod_dirs[0].parent
    return archive, mod_dir


def main() -> int:
    workspace = Path(sys.argv[1]).resolve()
    build_dir = workspace / "build"

    try:
        archive, mod_dir = find_fpm_artifacts(build_dir, "quadpack")
    except FileNotFoundError as e:
        print(f"FAIL: {e}")
        return 1

    with tempfile.TemporaryDirectory(prefix="fortbench-quadpack22-") as tmpdir:
        tmp = Path(tmpdir)
        source = tmp / "check_dqnc79.f90"
        exe = tmp / "check_dqnc79"
        source.write_text(PROGRAM)
        compile_proc = subprocess.run(
            ["gfortran", "-I", str(mod_dir), str(source), str(archive),
             "-o", str(exe)],
            text=True,
            capture_output=True,
        )
        if compile_proc.returncode != 0:
            print("FAIL: could not compile validator program")
            print(compile_proc.stdout)
            print(compile_proc.stderr)
            return 1

        run_proc = subprocess.run(
            [str(exe)], text=True, capture_output=True, timeout=30
        )
        if run_proc.returncode != 0:
            print("FAIL: dqnc79 intent bug still reproduces")
            print(run_proc.stdout)
            print(run_proc.stderr)
            return 1

    print("PASS: quadpack dqnc79 uses caller-supplied tolerance correctly")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
