from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from pathlib import Path

PROGRAM = r"""program check_real32
  use csv_module, only: csv_file
  use iso_fortran_env, only: real32
  implicit none

  type(csv_file) :: f
  logical :: status_ok
  real(real32), allocatable :: col_data(:)

  call f%open('/tmp/fortbench_csv21.csv', n_cols=2, status_ok=status_ok)
  if (.not. status_ok) error stop 'open failed'
  call f%add('x')
  call f%add('y')
  call f%next_row()
  call f%add(1.5_real32)
  call f%add(2.5_real32)
  call f%next_row()
  call f%add(3.5_real32)
  call f%add(4.5_real32)
  call f%next_row()
  call f%close(status_ok)
  if (.not. status_ok) error stop 'close failed'

  call f%read('/tmp/fortbench_csv21.csv', header_row=1, status_ok=status_ok)
  if (.not. status_ok) error stop 'read failed'

  call f%get(1, col_data, status_ok)
  if (.not. status_ok) then
    print *, 'FAIL: get real32 column failed'
    error stop 1
  end if

  if (size(col_data) /= 2) then
    print *, 'FAIL: expected 2 rows, got', size(col_data)
    error stop 2
  end if

  if (abs(col_data(1) - 1.5_real32) > 0.01_real32) then
    print *, 'FAIL: wrong value', col_data(1)
    error stop 3
  end if

  print *, 'PASS'
end program check_real32
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
    mod_dir = build_dir / "fcsv_include"
    archive = build_dir / "libfcsv.a"
    cache = build_dir / "CMakeCache.txt"
    if not mod_dir.exists() or not archive.exists() or not cache.exists():
        print("FAIL: expected CMake build artifacts are missing")
        return 1

    compiler = find_fortran_compiler(cache)
    with tempfile.TemporaryDirectory(prefix="fortbench-csv21-") as tmpdir:
        tmp = Path(tmpdir)
        source = tmp / "check_real32.f90"
        exe = tmp / "check_real32"
        source.write_text(PROGRAM)
        compile_proc = subprocess.run(
            [compiler, "-I", str(mod_dir), str(source), str(archive), "-o", str(exe)],
            text=True,
            capture_output=True,
        )
        if compile_proc.returncode != 0:
            print("FAIL: could not compile validator program")
            print(compile_proc.stdout)
            print(compile_proc.stderr)
            return 1

        run_proc = subprocess.run([str(exe)], text=True, capture_output=True, timeout=30)
        if run_proc.returncode != 0:
            print("FAIL: real32 support regression still reproduces")
            print(run_proc.stdout)
            print(run_proc.stderr)
            return 1

    print("PASS: csv-fortran supports real32 reading and writing")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
