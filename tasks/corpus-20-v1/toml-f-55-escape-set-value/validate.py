from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from pathlib import Path

PROGRAM = r"""program check_escape
  use tomlf, only: toml_table, set_value, get_value
  implicit none

  type(toml_table) :: table
  character(len=:), allocatable :: val
  integer :: stat

  table = toml_table()

  call set_value(table, 'path', 'C:\Users\test', stat=stat)
  if (stat /= 0) then
    print *, 'FAIL: set_value failed'
    error stop 1
  end if

  call get_value(table, 'path', val, stat=stat)
  if (stat /= 0) then
    print *, 'FAIL: get_value failed'
    error stop 2
  end if

  if (val /= 'C:\Users\test') then
    print *, 'FAIL: roundtrip failed, got: "', val, '"'
    error stop 3
  end if

  print *, 'PASS'
end program check_escape
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
    archive = build_dir / "libtoml-f.a"
    cache = build_dir / "CMakeCache.txt"
    if not mod_dir.exists() or not archive.exists() or not cache.exists():
        print("FAIL: expected CMake build artifacts are missing")
        return 1

    compiler = find_fortran_compiler(cache)
    with tempfile.TemporaryDirectory(prefix="fortbench-tomlf55-") as tmpdir:
        tmp = Path(tmpdir)
        source = tmp / "check_escape.f90"
        exe = tmp / "check_escape"
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
            print("FAIL: string escaping regression still reproduces")
            print(run_proc.stdout)
            print(run_proc.stderr)
            return 1

    print("PASS: toml-f set_value escapes special characters correctly")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
