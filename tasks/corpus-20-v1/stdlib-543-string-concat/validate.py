from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from pathlib import Path


PROGRAM = """program check_concat
  use stdlib_error, only : check
  use stdlib_string_type, only : string_type, assignment(=), operator(==), operator(//)
  implicit none
  type(string_type) :: a, b
  a = 'a'
  b = 'b'
  call check('a' // b == 'ab')
  call check(a // 'b' == 'ab')
  call check(a // b == 'ab')
  call check(a // '' == 'a')
  call check('' // b == 'b')
end program check_concat
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
    with tempfile.TemporaryDirectory(prefix="fortbench-stdlib543-") as tmpdir:
        tmp = Path(tmpdir)
        source = tmp / "check_concat.f90"
        exe = tmp / "check_concat"
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

        run_proc = subprocess.run([str(exe)], text=True, capture_output=True)
        if run_proc.returncode != 0:
            print("FAIL: concatenation checks failed")
            print(run_proc.stdout)
            print(run_proc.stderr)
            return 1

    print("PASS: stdlib string concatenation behaves as expected")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
