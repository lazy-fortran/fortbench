from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

PROGRAM = r"""module solout_mod
  use dop853_module, only: dop853_class, wp
  implicit none
  real(wp) :: first_h = 0.0_wp
  real(wp) :: last_h = 0.0_wp
  integer :: call_count = 0
contains
  subroutine my_solout(me, nr, xold, x, y, irtrn, xout)
    class(dop853_class), intent(inout) :: me
    integer, intent(in) :: nr
    real(wp), intent(in) :: xold, x
    real(wp), dimension(:), intent(in) :: y
    integer, intent(inout) :: irtrn
    real(wp), intent(out) :: xout
    real(wp) :: hcur
    call me%info(h=hcur)
    call_count = call_count + 1
    if (call_count == 1) first_h = hcur
    last_h = hcur
    xout = x
  end subroutine my_solout
end module solout_mod

program check_dense_h
  use dop853_module, only: dop853_class, wp
  use solout_mod
  implicit none

  type(dop853_class) :: s
  integer :: idid
  real(wp) :: x, y(1)
  real(wp) :: rtol(1), atol(1)
  logical :: status_ok

  call s%initialize(n=1, fcn=rhs, solout=my_solout, &
                    hinitial=0.01_wp, hmax=10.0_wp, &
                    status_ok=status_ok)
  if (.not. status_ok) then
    print *, 'FAIL: initialization failed'
    error stop 1
  end if

  x = 0.0_wp
  y = [1.0_wp]
  rtol = [1.0e-8_wp]
  atol = [1.0e-8_wp]
  call s%integrate(x, y, 10.0_wp, rtol, atol, 2, idid)

  if (idid < 0) then
    print *, 'FAIL: integration failed with idid =', idid
    error stop 2
  end if

  if (call_count < 2) then
    print *, 'FAIL: solout was called fewer than 2 times'
    error stop 3
  end if

  ! The step size should change from the initial value as the integrator
  ! adapts. With the bug, me%h stays at hinitial (0.01) throughout.
  ! With the fix, me%h gets updated as the integrator adapts step size.
  if (abs(last_h - first_h) < 1.0e-14_wp) then
    print *, 'FAIL: step size h never changed during integration'
    print *, '  first_h =', first_h, ' last_h =', last_h
    error stop 4
  end if

  print *, 'PASS'

contains
  subroutine rhs(me, x, y, f)
    class(dop853_class), intent(inout) :: me
    real(wp), intent(in) :: x
    real(wp), dimension(:), intent(in) :: y
    real(wp), dimension(:), intent(out) :: f
    f(1) = -y(1)
  end subroutine rhs
end program check_dense_h
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
        archive, mod_dir = find_fpm_artifacts(build_dir, "dop853")
    except FileNotFoundError as e:
        print(f"FAIL: {e}")
        return 1

    with tempfile.TemporaryDirectory(prefix="fortbench-dop853-10-") as tmpdir:
        tmp = Path(tmpdir)
        source = tmp / "check_dense_h.f90"
        exe = tmp / "check_dense_h"
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
            print("FAIL: dense output step size bug still reproduces")
            print(run_proc.stdout)
            print(run_proc.stderr)
            return 1

    print("PASS: dop853 step size is accessible during dense output callback")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
