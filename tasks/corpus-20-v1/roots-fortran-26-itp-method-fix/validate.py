from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

PROGRAM = r"""program check_itp
  use root_module, only: itp_solver, root_solver, wp => root_module_rk
  implicit none

  type(itp_solver) :: s
  real(wp) :: xzero, fzero
  integer :: iflag
  real(wp), parameter :: ax = 0.0_wp
  real(wp), parameter :: bx = 157.08_wp
  real(wp), parameter :: expected_root = 7.4771853245531515e1_wp
  real(wp), parameter :: tol = 1.0e-6_wp

  call s%initialize(f=linear_func, ftol=0.0_wp, rtol=1.0e-12_wp, &
                    atol=1.0e-12_wp, maxiter=200)
  call s%solve(ax, bx, xzero, fzero, iflag)

  if (iflag /= 0) then
    print *, 'FAIL: ITP method returned iflag =', iflag
    error stop 1
  end if
  if (abs(xzero - expected_root) > tol) then
    print *, 'FAIL: root =', xzero, ' expected ~', expected_root
    error stop 2
  end if

  print *, 'PASS'

contains

  function linear_func(me, x) result(f)
    class(root_solver), intent(inout) :: me
    real(wp), intent(in) :: x
    real(wp) :: f
    real(wp), parameter :: x1 = 0.0_wp, x2 = 157.08_wp
    real(wp), parameter :: y1 = 1012.0_wp, y2 = -1114.0_wp
    f = y1 + ((x - x1) / (x2 - x1)) * (y2 - y1)
  end function linear_func

end program check_itp
"""


def find_fpm_artifacts(build_dir: Path, lib_name: str) -> tuple[Path, Path]:
    """Find the fpm library archive and module directory."""
    archives = list(build_dir.glob(f"*/{lib_name}/lib{lib_name}.a"))
    if not archives:
        # try with hyphens converted to underscores or vice versa
        alt = lib_name.replace("-", "_")
        archives = list(build_dir.glob(f"*/{alt}/lib{alt}.a"))
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
        archive, mod_dir = find_fpm_artifacts(build_dir, "roots-fortran")
    except FileNotFoundError as e:
        print(f"FAIL: {e}")
        return 1

    with tempfile.TemporaryDirectory(prefix="fortbench-roots26-") as tmpdir:
        tmp = Path(tmpdir)
        source = tmp / "check_itp.f90"
        exe = tmp / "check_itp"
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
            print("FAIL: ITP method bug still reproduces")
            print(run_proc.stdout)
            print(run_proc.stderr)
            return 1

    print("PASS: roots-fortran ITP method works for f(a) > f(b) case")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
