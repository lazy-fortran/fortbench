from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

PROGRAM = r"""program check_trailing_comma
  use json_module, only: json_core, json_value, json_CK, json_LK
  implicit none

  type(json_core) :: json_allow, json_deny
  type(json_value), pointer :: p
  logical(json_LK) :: found
  integer :: count_children

  ! --- allow_trailing_comma = true (default) ---------------------------------
  call json_allow%initialize(allow_trailing_comma=.true.)

  ! Object with trailing comma
  call json_allow%deserialize(p, '{"a":1,"b":2,}')
  if (json_allow%failed()) then
    print *, 'FAIL: allow=true object with trailing comma raised error'
    error stop 1
  end if
  call json_allow%info(p, n_children=count_children)
  if (count_children /= 2) then
    print *, 'FAIL: expected 2 children in object, got', count_children
    error stop 1
  end if
  call json_allow%destroy(p)

  ! Array with trailing comma
  call json_allow%deserialize(p, '[1,2,3,]')
  if (json_allow%failed()) then
    print *, 'FAIL: allow=true array with trailing comma raised error'
    error stop 1
  end if
  call json_allow%info(p, n_children=count_children)
  if (count_children /= 3) then
    print *, 'FAIL: expected 3 children in array, got', count_children
    error stop 1
  end if
  call json_allow%destroy(p)

  ! --- allow_trailing_comma = false ------------------------------------------
  call json_deny%initialize(allow_trailing_comma=.false.)

  ! Object with trailing comma should fail
  call json_deny%deserialize(p, '{"a":1,}')
  if (.not. json_deny%failed()) then
    print *, 'FAIL: allow=false object with trailing comma did not raise error'
    error stop 1
  end if
  call json_deny%clear_exceptions()
  call json_deny%destroy(p)

  ! Array with trailing comma should fail
  call json_deny%deserialize(p, '[1,2,]')
  if (.not. json_deny%failed()) then
    print *, 'FAIL: allow=false array with trailing comma did not raise error'
    error stop 1
  end if
  call json_deny%clear_exceptions()
  call json_deny%destroy(p)

  print *, 'PASS: trailing comma handling works correctly'

end program check_trailing_comma
"""


def main() -> int:
    workspace = Path(sys.argv[1]).resolve()
    libs = sorted(workspace.glob("build/**/libjson-fortran.a"))
    mods = sorted(workspace.glob("build/**/json_module.mod"))
    if not libs:
        print("FAIL: libjson-fortran.a not found under build/")
        return 1
    if not mods:
        print("FAIL: json_module.mod not found under build/")
        return 1

    lib = libs[0]
    mod_dir = mods[0].parent
    fc = "gfortran"

    with tempfile.TemporaryDirectory(prefix="fortbench-jf570-") as tmpdir:
        tmp = Path(tmpdir)
        source = tmp / "check_trailing_comma.F90"
        exe = tmp / "check_trailing_comma"
        source.write_text(PROGRAM)

        compile_proc = subprocess.run(
            [fc, "-J", str(mod_dir), "-I", str(mod_dir), str(source), str(lib), "-o", str(exe)],
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
            print("FAIL: trailing comma checks failed")
            print(run_proc.stdout)
            print(run_proc.stderr)
            return 1

    print("PASS: json-fortran trailing comma feature works correctly")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
