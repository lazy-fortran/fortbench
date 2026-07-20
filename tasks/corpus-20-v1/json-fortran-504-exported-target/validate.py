from __future__ import annotations

import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path


def run(command: list[str], cwd: Path, timeout: int = 300) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=str(cwd), text=True, capture_output=True, timeout=timeout)


def find_package_name(prefix: Path) -> str:
    configs = sorted(prefix.glob("**/*config.cmake"))
    if not configs:
        raise RuntimeError("no installed *config.cmake found")
    name = configs[0].name.removesuffix("-config.cmake").removesuffix("Config")
    return name


def main() -> int:
    workspace = Path(sys.argv[1]).resolve()
    with tempfile.TemporaryDirectory(prefix="fortbench-json504-") as tmpdir:
        tmp = Path(tmpdir)
        install_prefix = tmp / "inst"
        build_dir = tmp / "json-build"
        configure = run(
            [
                "cmake",
                "-S",
                str(workspace),
                "-B",
                str(build_dir),
                f"-DCMAKE_INSTALL_PREFIX={install_prefix}",
                "-DCMAKE_POLICY_VERSION_MINIMUM=3.5",
                "-DSKIP_DOC_GEN=TRUE",
            ],
            workspace,
        )
        if configure.returncode != 0:
            print("FAIL: json-fortran configure failed")
            print(configure.stdout)
            print(configure.stderr)
            return 1

        build = run(["cmake", "--build", str(build_dir), "-j4"], workspace, timeout=600)
        if build.returncode != 0:
            print("FAIL: json-fortran build failed")
            print(build.stdout)
            print(build.stderr)
            return 1

        install = run(["cmake", "--install", str(build_dir)], workspace)
        if install.returncode != 0:
            print("FAIL: json-fortran install failed")
            print(install.stdout)
            print(install.stderr)
            return 1

        try:
            package_name = find_package_name(install_prefix)
        except RuntimeError as exc:
            print(f"FAIL: {exc}")
            return 1

        consumer = tmp / "consumer"
        consumer.mkdir()
        (consumer / "CMakeLists.txt").write_text(
            textwrap.dedent(
                f"""
                cmake_minimum_required(VERSION 3.18)
                project(consumer LANGUAGES Fortran)
                find_package({package_name} CONFIG REQUIRED)
                add_executable(consumer main.f90)
                target_link_libraries(consumer PRIVATE {package_name}::jsonfortran-static)
                """
            ).strip()
            + "\n"
        )
        (consumer / "main.f90").write_text(
            "program main\n"
            "  use json_module, only : json_file\n"
            "  type(json_file) :: json\n"
            "  call json%destroy()\n"
            "  print *, 'ok'\n"
            "end program main\n"
        )

        consumer_configure = run(
            [
                "cmake",
                "-S",
                str(consumer),
                "-B",
                str(consumer / "build"),
                f"-DCMAKE_PREFIX_PATH={install_prefix}",
            ],
            consumer,
        )
        if consumer_configure.returncode != 0:
            print("FAIL: consumer configure failed")
            print(consumer_configure.stdout)
            print(consumer_configure.stderr)
            return 1

        consumer_build = run(["cmake", "--build", str(consumer / "build"), "-j4"], consumer)
        if consumer_build.returncode != 0:
            print("FAIL: consumer build failed")
            print(consumer_build.stdout)
            print(consumer_build.stderr)
            return 1

        print("PASS: installed json-fortran exports a usable imported CMake target")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
