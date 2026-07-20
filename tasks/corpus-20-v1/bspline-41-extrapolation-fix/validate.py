from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from pathlib import Path

PROGRAM = r"""program check_extrap
  use bspline_module
  use bspline_kinds_module, only: wp
  implicit none

  integer, parameter :: nx = 6, ny = 6, kx = 4, ky = 4, iknot = 0
  real(wp) :: x(nx), y(ny), fcn(nx, ny)
  real(wp) :: tx(nx + kx), ty(ny + ky)
  real(wp) :: val, tru, err
  integer :: i, j, iflag, inbvx, inbvy, iloy, idx, idy
  real(wp), parameter :: tol = 1.0e-2_wp

  idx = 0; idy = 0
  do i = 1, nx
    x(i) = dble(i - 1) / dble(nx - 1)
  end do
  do j = 1, ny
    y(j) = dble(j - 1) / dble(ny - 1)
  end do
  do i = 1, nx
    do j = 1, ny
      fcn(i, j) = 0.5_wp * (y(j) * exp(-x(i)) + sin(1.1_wp * atan(1.0_wp) * y(j)))
    end do
  end do

  iflag = 0
  call db2ink(x, nx, y, ny, fcn, kx, ky, iknot, tx, ty, fcn, iflag)
  if (iflag /= 0) then
    print *, 'FAIL: db2ink error: ', get_status_message(iflag)
    error stop 1
  end if

  inbvx = 1; inbvy = 1; iloy = 1

  call db2val(1.2_wp, 0.5_wp, idx, idy, tx, ty, nx, ny, kx, ky, &
              fcn, val, iflag, inbvx, inbvy, iloy, extrap=.true.)
  if (iflag /= 0) then
    print *, 'FAIL: x-extrapolation error: ', get_status_message(iflag)
    error stop 2
  end if

  call db2val(0.5_wp, 1.2_wp, idx, idy, tx, ty, nx, ny, kx, ky, &
              fcn, val, iflag, inbvx, inbvy, iloy, extrap=.true.)
  if (iflag /= 0) then
    print *, 'FAIL: y-extrapolation error: ', get_status_message(iflag)
    error stop 3
  end if

  print *, 'PASS'
end program check_extrap
"""


def find_fortran_compiler(cache_path: Path) -> str:
    pattern = re.compile(r"^CMAKE_Fortran_COMPILER:FILEPATH=(.+)$")
    for line in cache_path.read_text().splitlines():
        match = pattern.match(line.strip())
        if match:
            return match.group(1)
    raise RuntimeError("CMAKE_Fortran_COMPILER not found in CMakeCache.txt")


def main() -> int:
    workspace = Path(sys.argv[1]).resolve()
    build_dir = workspace / "build"
    archive = build_dir / "libbspline-fortran.a"
    cache = build_dir / "CMakeCache.txt"
    if not archive.exists() or not cache.exists():
        print("FAIL: expected CMake build artifacts are missing")
        return 1

    compiler = find_fortran_compiler(cache)
    with tempfile.TemporaryDirectory(prefix="fortbench-bspline41-") as tmpdir:
        tmp = Path(tmpdir)
        source = tmp / "check_extrap.f90"
        exe = tmp / "check_extrap"
        source.write_text(PROGRAM)
        compile_proc = subprocess.run(
            [compiler, "-I", str(build_dir), str(source), str(archive), "-o", str(exe)],
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
            print("FAIL: extrapolation regression still reproduces")
            print(run_proc.stdout)
            print(run_proc.stderr)
            return 1

    print("PASS: bspline-fortran extrapolation works for 2D splines")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
