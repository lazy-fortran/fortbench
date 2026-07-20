from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from pathlib import Path

PROGRAM = r"""program check_remove
  use json_module
  implicit none

  type(json_core) :: json
  type(json_value), pointer :: root, p, p2
  integer(json_IK) :: ival
  logical(json_LK) :: found
  character(kind=json_CK, len=:), allocatable :: str_out

  character(kind=json_CK, len=*), parameter :: input_json = &
    '{"object1": {"a": 1, "b": 2, "move1": 3, "move2": 4, "e": 5}, '// &
    '"object2": {"f": 10, "g": 11}}'

  call json%deserialize(root, input_json)

  call json%get(root, 'object1.move1', p, found)
  if (.not. found) error stop 'cannot find object1.move1'
  call json%clone(p, p2)
  call json%remove(p, .true.)
  call json%add_by_path(root, 'object2.move1', p2)

  call json%get(root, 'object1.move2', p, found)
  if (.not. found) error stop 'cannot find object1.move2'
  call json%remove(p, .false.)
  call json%add_by_path(root, 'object2.move2', p)

  call json%get(root, 'object2.move1', ival, found)
  if (.not. found .or. ival /= 3) then
    print *, 'FAIL: object2.move1 not found or wrong value'
    error stop 1
  end if

  call json%get(root, 'object2.move2', ival, found)
  if (.not. found .or. ival /= 4) then
    print *, 'FAIL: object2.move2 not found or wrong value'
    error stop 2
  end if

  call json%get(root, 'object1.a', ival, found)
  if (.not. found) then
    print *, 'FAIL: object1.a not found'
    error stop 3
  end if

  call json%get(root, 'object1.e', ival, found)
  if (.not. found) then
    print *, 'FAIL: object1.e not found after move'
    error stop 4
  end if

  call json%serialize(root, str_out)
  if (json%failed()) then
    print *, 'FAIL: serialization failed'
    error stop 5
  end if

  call json%destroy(root)
  print *, 'PASS'
end program check_remove
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
    with tempfile.TemporaryDirectory(prefix="fortbench-json479-") as tmpdir:
        tmp = Path(tmpdir)
        source = tmp / "check_remove.f90"
        exe = tmp / "check_remove"
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
            print("FAIL: json_value_remove pointer regression still reproduces")
            print(run_proc.stdout)
            print(run_proc.stderr)
            return 1

    print("PASS: json-fortran json_value_remove correctly nullifies pointers")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
