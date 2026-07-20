from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


PROGRAM = """#include "minpack.h"

static void dummy_func(int n, const double *x, double *fvec, int *iflag, void *udata) {
  (void)n; (void)x; (void)fvec; (void)iflag; (void)udata;
}

int main(void) {
  minpack_func f = &dummy_func;
  void *p1 = (void *) minpack_hybrd;
  void *p2 = (void *) minpack_hybrd1;
  void *p3 = (void *) minpack_lmdif;
  void *p4 = (void *) minpack_lmdif1;
  void *p5 = (void *) minpack_chkder;
  return (minpack_dpmpar(1) > 0.0 && f && p1 && p2 && p3 && p4 && p5) ? 0 : 1;
}
"""


def main() -> int:
    workspace = Path(sys.argv[1]).resolve()
    header = workspace / "include" / "minpack.h"
    capi_module = workspace / "src" / "minpack_capi.f90"
    manifest = workspace / "fpm.toml"
    libs = sorted(workspace.glob("build/**/minpack/libminpack.a"))
    if not header.exists():
        print("FAIL: expected include/minpack.h to exist")
        return 1
    if not capi_module.exists():
        print("FAIL: expected src/minpack_capi.f90 to exist")
        return 1
    if not libs:
        print("FAIL: built libminpack.a not found under build/**/minpack/")
        return 1

    header_text = header.read_text()
    required_exports = [
        "minpack_dpmpar",
        "minpack_hybrd",
        "minpack_hybrd1",
        "minpack_lmdif",
        "minpack_lmdif1",
        "minpack_chkder",
    ]
    missing_exports = [name for name in required_exports if name not in header_text]
    if missing_exports:
        print("FAIL: minpack header is missing required exported C API declarations")
        print(", ".join(missing_exports))
        return 1

    manifest_text = manifest.read_text()
    if 'name = "c-test"' not in manifest_text or 'source-dir = "test/api"' not in manifest_text:
        print("FAIL: expected fpm.toml to register the C API test suite")
        return 1

    cc = shutil.which("cc") or shutil.which("clang")
    fc = shutil.which("gfortran") or shutil.which("gfortran-15")
    if not cc or not fc:
        print("FAIL: required C and Fortran compilers not found")
        return 1

    with tempfile.TemporaryDirectory(prefix="fortbench-minpack29-") as tmpdir:
        tmp = Path(tmpdir)
        source = tmp / "probe.c"
        obj = tmp / "probe.o"
        exe = tmp / "probe"
        source.write_text(PROGRAM)
        compile_proc = subprocess.run(
            [cc, "-c", str(source), "-I", str(header.parent), "-o", str(obj)],
            text=True,
            capture_output=True,
        )
        if compile_proc.returncode != 0:
            print("FAIL: trivial C consumer did not compile against minpack headers")
            print(compile_proc.stdout)
            print(compile_proc.stderr)
            return 1

        link_proc = subprocess.run(
            [fc, str(obj), str(libs[0]), "-o", str(exe)],
            text=True,
            capture_output=True,
        )
        if link_proc.returncode != 0:
            print("FAIL: trivial C consumer did not link against minpack")
            print(link_proc.stdout)
            print(link_proc.stderr)
            return 1

        run_proc = subprocess.run([str(exe)], text=True, capture_output=True)
        if run_proc.returncode != 0:
            print("FAIL: trivial C consumer executable returned non-zero")
            print(run_proc.stdout)
            print(run_proc.stderr)
            return 1

    print("PASS: Minpack exports a usable C API header and library symbol")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
