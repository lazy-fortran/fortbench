from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def main() -> int:
    workspace = Path(sys.argv[1]).resolve()
    meson = shutil.which("meson")
    if not meson:
        print("FAIL: meson not found in PATH")
        return 1

    with tempfile.TemporaryDirectory(prefix="fortbench-minpack42-") as tmpdir:
        build_dir = Path(tmpdir) / "build"
        proc = subprocess.run(
            [meson, "setup", str(build_dir)],
            cwd=str(workspace),
            text=True,
            capture_output=True,
            timeout=120,
        )
        if proc.returncode != 0:
            print("FAIL: meson setup did not succeed")
            print(proc.stdout)
            print(proc.stderr)
            return 1
        if not (build_dir / "build.ninja").exists():
            print("FAIL: meson setup succeeded but build.ninja is missing")
            return 1

    print("PASS: Meson build files configure successfully")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
