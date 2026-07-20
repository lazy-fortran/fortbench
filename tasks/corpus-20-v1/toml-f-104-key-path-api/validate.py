from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

PROGRAM = r"""program check_key_path
 use tomlf, only: toml_table, toml_error, toml_loads, &
                     get_value, set_value, toml_path, toml_path_t
  implicit none

  type(toml_table), allocatable :: table
  type(toml_error), allocatable :: error
  character(len=:), allocatable :: host_str, readback
  integer :: port_val, stat
  type(toml_path_t) :: path
  character(len=*), parameter :: doc = &
    '[server]' // new_line('a') // &
    'host = "localhost"' // new_line('a') // &
    'port = 8080' // new_line('a')

  ! Parse the TOML document
  call toml_loads(table, doc, error=error)
  if (allocated(error)) then
    print *, 'FAIL: could not parse TOML document'
    error stop 1
  end if

  ! Test get_value with toml_path for string
  call get_value(table, toml_path("server", "host"), host_str, stat=stat)
  if (stat /= 0) then
    print *, 'FAIL: get_value path for server.host failed with stat', stat
    error stop 1
  end if
  if (host_str /= "localhost") then
    print *, 'FAIL: expected localhost, got ', host_str
    error stop 1
  end if

  ! Test get_value with toml_path for integer
  call get_value(table, toml_path("server", "port"), port_val, stat=stat)
  if (stat /= 0) then
    print *, 'FAIL: get_value path for server.port failed with stat', stat
    error stop 1
  end if
  if (port_val /= 8080) then
    print *, 'FAIL: expected 8080, got', port_val
    error stop 1
  end if

  ! Test set_value with toml_path (creates intermediate table)
  call set_value(table, toml_path("database", "name"), "mydb", stat=stat)
  if (stat /= 0) then
    print *, 'FAIL: set_value path for database.name failed with stat', stat
    error stop 1
  end if

  ! Verify the set value can be read back
  call get_value(table, toml_path("database", "name"), readback, stat=stat)
  if (stat /= 0) then
    print *, 'FAIL: readback of database.name failed with stat', stat
    error stop 1
  end if
  if (readback /= "mydb") then
    print *, 'FAIL: readback expected mydb, got ', readback
    error stop 1
  end if

  print *, 'PASS: toml_path key path API works correctly'

end program check_key_path
"""


def main() -> int:
    workspace = Path(sys.argv[1]).resolve()
    libs = sorted(workspace.glob("build/**/libtoml-f.a"))
    mods = sorted(workspace.glob("build/**/tomlf.mod"))
    if not libs:
        print("FAIL: libtoml-f.a not found under build/")
        return 1
    if not mods:
        print("FAIL: tomlf.mod not found under build/")
        return 1

    lib = libs[0]
    mod_dir = mods[0].parent
    fc = "gfortran"

    with tempfile.TemporaryDirectory(prefix="fortbench-tf104-") as tmpdir:
        tmp = Path(tmpdir)
        source = tmp / "check_key_path.f90"
        exe = tmp / "check_key_path"
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
            print("FAIL: key path checks failed")
            print(run_proc.stdout)
            print(run_proc.stderr)
            return 1

    print("PASS: toml-f key path API works correctly")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
