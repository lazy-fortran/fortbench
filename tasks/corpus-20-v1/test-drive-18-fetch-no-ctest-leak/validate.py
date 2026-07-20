from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


CONSUMER_CMAKELISTS = """cmake_minimum_required(VERSION 3.18)
project(fortbench_test_drive_consumer LANGUAGES NONE)

include(FetchContent)
include(CTest)
set(TEST_DRIVE_BUILD_TESTING OFF CACHE BOOL "Disable upstream test-drive tests")

FetchContent_Declare(
  test-drive
  SOURCE_DIR "{workspace}"
)
FetchContent_MakeAvailable(test-drive)

add_test(NAME local-smoke COMMAND ${{CMAKE_COMMAND}} -E true)
"""


def run(command: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=str(cwd), text=True, capture_output=True)


def main() -> int:
    args = sys.argv[1:]
    setup_only = False
    if "--setup-only" in args:
        setup_only = True
        args = [arg for arg in args if arg != "--setup-only"]
    workspace = Path(args[0]).resolve()

    with tempfile.TemporaryDirectory(prefix="fortbench-testdrive18-") as tmpdir:
        tmp = Path(tmpdir)
        consumer = tmp / "consumer"
        build = consumer / "build"
        consumer.mkdir(parents=True)
        (consumer / "CMakeLists.txt").write_text(CONSUMER_CMAKELISTS.format(workspace=workspace.as_posix()))

        cmake = shutil.which("cmake")
        if not cmake:
            print("FAIL: cmake not found")
            return 1

        configure = run([cmake, "-S", str(consumer), "-B", str(build)], consumer)
        if configure.returncode != 0:
            print("FAIL: consumer configure failed")
            print(configure.stdout)
            print(configure.stderr)
            return 1

        if setup_only:
            print("PASS: consumer configure succeeded")
            return 0

        listing = run([cmake, "--build", str(build)], consumer)
        if listing.returncode != 0:
            print("FAIL: consumer build failed")
            print(listing.stdout)
            print(listing.stderr)
            return 1

        ctest = run(["ctest", "-N"], build)
        if ctest.returncode != 0:
            print("FAIL: ctest -N failed")
            print(ctest.stdout)
            print(ctest.stderr)
            return 1

        output = ctest.stdout + "\n" + ctest.stderr
        unwanted = ("test-drive/all-tests", "test-drive/check", "test-drive/select")
        if any(name in output for name in unwanted):
            print("FAIL: test-drive tests leaked into consumer ctest list")
            print(output)
            return 1
        if "local-smoke" not in output:
            print("FAIL: consumer local-smoke test is missing")
            print(output)
            return 1

        print("PASS: FetchContent consumer only sees its own CTest entries")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
