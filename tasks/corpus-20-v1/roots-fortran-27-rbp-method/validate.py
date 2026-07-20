from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

PROGRAM = r"""program check_rbp
  use root_module, only: root_module_rk, root_method_rbp, set_of_root_methods, &
                         root_scalar
  implicit none

  integer, parameter :: wp = root_module_rk
  real(wp) :: xzero, fzero
  integer :: iflag

  ! Use the RBP method by name to find root of f(x) = x^3 - x - 2
  ! on interval [1, 2]. Root is approximately 1.52138...
  call root_scalar('rbp', cubic, 1.0_wp, 2.0_wp, xzero, fzero, iflag)

  if (iflag /= 0) then
    print *, 'FAIL: root_scalar with rbp returned iflag =', iflag
    error stop 1
  end if

  if (abs(xzero - 1.5213797068045676_wp) > 1.0e-8_wp) then
    print *, 'FAIL: rbp root is too far from expected value', xzero
    error stop 1
  end if

  if (abs(fzero) > 1.0e-10_wp) then
    print *, 'FAIL: f(xzero) is not close enough to zero', fzero
    error stop 1
  end if

  ! Also verify we can use the type-based API
  call root_scalar(root_method_rbp, cubic, 1.0_wp, 2.0_wp, xzero, fzero, iflag)
  if (iflag /= 0) then
    print *, 'FAIL: root_scalar type-based with rbp returned iflag =', iflag
    error stop 1
  end if

  ! Verify rbp is in set_of_root_methods (size should be 19 with rbp)
  if (size(set_of_root_methods) < 19) then
    print *, 'FAIL: set_of_root_methods too small, expected at least 19'
    error stop 1
  end if

  print *, 'PASS: RBP method works correctly'

contains

  function cubic(x) result(f)
    real(wp), intent(in) :: x
    real(wp) :: f
    f = x**3 - x - 2.0_wp
  end function cubic

end program check_rbp
"""


def main() -> int:
    workspace = Path(sys.argv[1]).resolve()
    libs = sorted(workspace.glob("build/**/libroots-fortran.a"))
    mods = sorted(workspace.glob("build/**/root_module.mod"))
    if not libs:
        print("FAIL: libroots-fortran.a not found under build/")
        return 1
    if not mods:
        print("FAIL: root_module.mod not found under build/")
        return 1

    lib = libs[0]
    mod_dir = mods[0].parent
    fc = "gfortran"

    with tempfile.TemporaryDirectory(prefix="fortbench-rf27-") as tmpdir:
        tmp = Path(tmpdir)
        source = tmp / "check_rbp.F90"
        exe = tmp / "check_rbp"
        source.write_text(PROGRAM)

        compile_proc = subprocess.run(
            [fc, "-I", str(mod_dir), str(source), str(lib), "-o", str(exe)],
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
            print("FAIL: RBP method checks failed")
            print(run_proc.stdout)
            print(run_proc.stderr)
            return 1

    print("PASS: roots-fortran RBP method works correctly")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
