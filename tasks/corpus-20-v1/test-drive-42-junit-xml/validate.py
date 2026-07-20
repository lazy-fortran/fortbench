from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

PROGRAM = r"""program check_junit
  use testdrive, only: testsuite_type, unittest_type, error_type, &
                        test_interface, collect_interface, &
                        check, run_testsuite, junit_output, junit_header
  implicit none

  type(junit_output) :: junit
  integer :: stat, u
  character(len=:), allocatable :: xml

  stat = 0
  u = 6

  call junit_header(junit, "fortbench")

  ! Verify xml_start was set
  if (.not. allocated(junit%xml_start)) then
    print *, 'FAIL: junit%xml_start not allocated after junit_header'
    error stop 1
  end if
  if (index(junit%xml_start, '<?xml') == 0) then
    print *, 'FAIL: xml_start missing xml declaration'
    error stop 1
  end if

  ! Run a simple test suite (parallel=.false. to avoid OpenMP issues with junit)
  call run_testsuite(collect_suite, u, stat, parallel=.false., junit=junit)

  ! Build full XML (xml_start accumulates all suite output, xml_block is
  ! cleared after each suite by junit_pop_suite, xml_final has closing tag)
  xml = junit%xml_start // junit%xml_block // junit%xml_final

  ! Check for expected XML elements
  if (index(xml, '<testsuites') == 0) then
    print *, 'FAIL: xml missing <testsuites>'
    error stop 1
  end if
  if (index(xml, '<testsuite') == 0) then
    print *, 'FAIL: xml missing <testsuite element in output'
    error stop 1
  end if
  if (index(xml, '<testcase') == 0) then
    print *, 'FAIL: xml missing <testcase>'
    error stop 1
  end if
  if (index(xml, '</testsuites>') == 0) then
    print *, 'FAIL: xml missing </testsuites>'
    error stop 1
  end if
  ! Verify the test name appears in the output
  if (index(xml, 'trivial-pass') == 0) then
    print *, 'FAIL: xml missing test name trivial-pass'
    error stop 1
  end if
  ! Verify tests="1" appears in the testsuite attributes
  if (index(xml, 'tests="1"') == 0) then
    print *, 'FAIL: xml missing tests="1" in testsuite'
    error stop 1
  end if

  print *, 'PASS: JUnit XML output works correctly'

contains

  subroutine collect_suite(testsuite)
    type(unittest_type), allocatable, intent(out) :: testsuite(:)
    testsuite = [unittest_type("trivial-pass", trivial_test)]
  end subroutine collect_suite

  subroutine trivial_test(error)
    type(error_type), allocatable, intent(out) :: error
    call check(error, 1 + 1 == 2)
  end subroutine trivial_test

end program check_junit
"""


def main() -> int:
    workspace = Path(sys.argv[1]).resolve()
    libs = sorted(workspace.glob("build/**/libtest-drive.a"))
    mods = sorted(workspace.glob("build/**/testdrive.mod"))
    if not libs:
        print("FAIL: libtest-drive.a not found under build/")
        return 1
    if not mods:
        print("FAIL: testdrive.mod not found under build/")
        return 1

    lib = libs[0]
    mod_dir = mods[0].parent
    fc = "gfortran"

    with tempfile.TemporaryDirectory(prefix="fortbench-td42-") as tmpdir:
        tmp = Path(tmpdir)
        source = tmp / "check_junit.F90"
        exe = tmp / "check_junit"
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
            print("FAIL: JUnit checks failed")
            print(run_proc.stdout)
            print(run_proc.stderr)
            return 1

    print("PASS: test-drive JUnit XML output works correctly")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
