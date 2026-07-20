from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from pathlib import Path

PROGRAM = r"""program check_get_path
  use json_module
  implicit none

  type(json_core) :: json
  type(json_value), pointer :: p, x
  character(kind=json_CK, len=:), allocatable :: path
  integer(json_IK) :: ival
  logical(json_LK) :: found

  call json%deserialize(p, '{ "x": [[1], [1,2,3,[4]]] }')

  call json%get(p, 'x[2][4][1]', ival, found)
  if (.not. found) then
    print *, 'FAIL: could not find x[2][4][1]'
    call json%destroy(p)
    error stop 1
  end if
  if (ival /= 4) then
    print *, 'FAIL: x[2][4][1] =', ival, ', expected 4'
    call json%destroy(p)
    error stop 2
  end if

  call json%initialize(path_mode=1_json_IK)
  call json%get(p, 'x[2][4][1]', x, found)
  if (.not. found) then
    print *, 'FAIL: cannot traverse to x[2][4][1]'
    call json%destroy(p)
    error stop 3
  end if
  call json%get_path(x, path)
  if (json%failed()) then
    print *, 'FAIL: get_path failed'
    call json%destroy(p)
    error stop 4
  end if
  if (path /= 'x[2][4][1]') then
    print *, 'FAIL: wrong path: "', path, '", expected "x[2][4][1]"'
    call json%destroy(p)
    error stop 5
  end if

  call json%destroy(p)
  print *, 'PASS'
end program check_get_path
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
    archive = build_dir / "lib" / "libjsonfortran.a"
    cache = build_dir / "CMakeCache.txt"
    if not mod_dir.exists() or not archive.exists() or not cache.exists():
        print("FAIL: expected CMake build artifacts are missing")
        return 1

    compiler = find_fortran_compiler(cache)
    with tempfile.TemporaryDirectory(prefix="fortbench-json454-") as tmpdir:
        tmp = Path(tmpdir)
        source = tmp / "check_get_path.f90"
        exe = tmp / "check_get_path"
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
            print("FAIL: json_get_path regression still reproduces")
            print(run_proc.stdout)
            print(run_proc.stderr)
            return 1

    print("PASS: json-fortran json_get_path handles nested arrays correctly")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
