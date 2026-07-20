from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from pathlib import Path

PROGRAM = r"""program check_iomsg
  use stdlib_io_npy, only: save_npy
  use iso_fortran_env, only: sp => real32
  implicit none

  integer :: stat
  character(len=:), allocatable :: msg
  real(sp), allocatable :: input(:, :)
  character(len=*), parameter :: filename = "/tmp/fortbench-iomsg-test.npy"

  msg = "This message should be deallocated."
  allocate(input(12, 5))
  call random_number(input)
  call save_npy(filename, input, stat, msg)

  if (stat /= 0) error stop 'save_npy returned nonzero stat'
  if (allocated(msg)) then
    print *, 'FAIL: iomsg wrongly allocated on success'
    error stop 1
  end if

  print *, 'PASS'
end program check_iomsg
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
    mod_dir = build_dir / "src" / "mod_files"
    archive = build_dir / "src" / "libfortran_stdlib.a"
    cache = build_dir / "CMakeCache.txt"
    if not mod_dir.exists() or not archive.exists() or not cache.exists():
        print("FAIL: expected CMake build artifacts are missing")
        return 1

    compiler = find_fortran_compiler(cache)
    with tempfile.TemporaryDirectory(prefix="fortbench-stdlib600-") as tmpdir:
        tmp = Path(tmpdir)
        source = tmp / "check_iomsg.f90"
        exe = tmp / "check_iomsg"
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
            print("FAIL: iomsg allocation regression still reproduces")
            print(run_proc.stdout)
            print(run_proc.stderr)
            return 1

    print("PASS: stdlib save_npy iomsg behaves correctly on success")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
