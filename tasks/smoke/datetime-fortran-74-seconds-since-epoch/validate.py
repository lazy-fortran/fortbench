from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from pathlib import Path


PROGRAM = """program check_epoch
  use, intrinsic :: iso_fortran_env, only : int64
  use datetime_module, only : datetime
  implicit none
  type(datetime) :: a

  a = datetime(1970, 1, 1, 0, 0, 0)
  if (a % secondsSinceEpoch() /= 0_int64) error stop 1

  a = datetime(2070, 1, 1)
  if (a % secondsSinceEpoch() /= 3155760000_int64) error stop 2

  print *, 'PASS'
end program check_epoch
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
    mod_dir = build_dir / "include"
    archive = build_dir / "lib" / "libdatetime.a"
    cache = build_dir / "CMakeCache.txt"
    if not mod_dir.exists() or not archive.exists() or not cache.exists():
        print("FAIL: expected CMake build artifacts are missing")
        return 1

    compiler = find_fortran_compiler(cache)
    with tempfile.TemporaryDirectory(prefix="fortbench-datetime74-") as tmpdir:
        tmp = Path(tmpdir)
        source = tmp / "check_epoch.f90"
        exe = tmp / "check_epoch"
        source.write_text(PROGRAM)
        compile_proc = subprocess.run(
            [compiler, "-I", str(mod_dir), str(source), str(archive), "-lstdc++", "-o", str(exe)],
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
            print("FAIL: secondsSinceEpoch regression still reproduces")
            print(run_proc.stdout)
            print(run_proc.stderr)
            return 1

    print("PASS: datetime-fortran secondsSinceEpoch range behaves as expected")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
