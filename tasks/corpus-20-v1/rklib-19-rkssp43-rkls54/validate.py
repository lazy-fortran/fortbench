from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

PROGRAM = r"""program check_rk_methods
  use rklib_module, wp => rk_module_rk
  implicit none

  integer, parameter :: n = 1
  real(wp) :: x0(n), xf(n)
  real(wp) :: t0, tf, h
  real(wp) :: exact

  t0 = 0.0_wp
  tf = 1.0_wp
  x0 = [1.0_wp]
  exact = exp(-tf)

  ! ----- Test rkls54 (fixed-step) -----
  block
    type(rkls54_class) :: solver
    call solver%initialize(n=n, f=decay_rhs)
    h = 0.001_wp
    call solver%integrate(t0, x0, h, tf, xf)
    if (solver%failed()) then
      print *, 'FAIL: rkls54 integration failed'
      error stop 1
    end if
    if (abs(xf(1) - exact) > 1.0e-6_wp) then
      print *, 'FAIL: rkls54 result too far from exact', xf(1), exact
      error stop 1
    end if
    print *, 'rkls54 OK: xf =', xf(1), 'exact =', exact
  end block

  ! ----- Test rkssp43 (variable-step) -----
  block
    type(rkssp43_class) :: solver
    integer :: p
    call solver%initialize(n=n, f=decay_rhs, rtol=[1.0e-10_wp], atol=[1.0e-12_wp])
    h = 0.1_wp
    call solver%integrate(t0, x0, h, tf, xf)
    if (solver%failed()) then
      print *, 'FAIL: rkssp43 integration failed'
      error stop 1
    end if
    if (abs(xf(1) - exact) > 1.0e-6_wp) then
      print *, 'FAIL: rkssp43 result too far from exact', xf(1), exact
      error stop 1
    end if
    p = solver%order()
    if (p /= 3) then
      print *, 'FAIL: rkssp43 order should be 3, got', p
      error stop 1
    end if
    print *, 'rkssp43 OK: xf =', xf(1), 'exact =', exact, 'order =', p
  end block

  print *, 'PASS: both rkssp43 and rkls54 methods work correctly'

contains

  subroutine decay_rhs(me, t, x, xdot)
    class(rk_class), intent(inout) :: me
    real(wp), intent(in) :: t
    real(wp), dimension(:), intent(in) :: x
    real(wp), dimension(:), intent(out) :: xdot
    xdot(1) = -x(1)
  end subroutine decay_rhs

end program check_rk_methods
"""


def main() -> int:
    workspace = Path(sys.argv[1]).resolve()
    libs = sorted(workspace.glob("build/**/librklib.a"))
    mods = sorted(workspace.glob("build/**/rklib_module.mod"))
    if not libs:
        print("FAIL: librklib.a not found under build/")
        return 1
    if not mods:
        print("FAIL: rklib_module.mod not found under build/")
        return 1

    lib = libs[0]
    mod_dir = mods[0].parent

    dep_libs = sorted(workspace.glob("build/**/libroots-fortran.a"))
    all_libs = [str(lib)] + [str(d) for d in dep_libs]

    fc = "gfortran"

    with tempfile.TemporaryDirectory(prefix="fortbench-rk19-") as tmpdir:
        tmp = Path(tmpdir)
        source = tmp / "check_rk_methods.F90"
        exe = tmp / "check_rk_methods"
        source.write_text(PROGRAM)

        compile_proc = subprocess.run(
            [fc, "-I", str(mod_dir), str(source)] + all_libs + ["-o", str(exe)],
            text=True,
            capture_output=True,
        )
        if compile_proc.returncode != 0:
            print("FAIL: could not compile validator program")
            print(compile_proc.stdout)
            print(compile_proc.stderr)
            return 1

        run_proc = subprocess.run([str(exe)], text=True, capture_output=True)
        if run_proc.returncode != 0:
            print("FAIL: RK method checks failed")
            print(run_proc.stdout)
            print(run_proc.stderr)
            return 1

    print("PASS: rklib rkssp43 and rkls54 methods work correctly")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
