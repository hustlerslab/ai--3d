"""Run Blender headless as a subprocess.

    blender -b [scene.blend] --factory-startup --python-exit-code 1
            --python blender/scripts/<script>.py -- <args>

stdout/stderr are streamed to a log file. Scripts print one final line
`ALLURE_RESULT {json}` which becomes BlenderResult.result.

CLI smoke test:
    python -m app.blender.runner --smoke [out.png] [--engine BLENDER_EEVEE]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO, Optional

from ..core.config import get_settings

RESULT_PREFIX = "ALLURE_RESULT "


class BlenderError(Exception):
    def __init__(self, message: str, log_path: Optional[Path] = None, tail: str = ""):
        super().__init__(message)
        self.log_path = log_path
        self.tail = tail


class BlenderNotConfigured(BlenderError):
    pass


class BlenderTimeout(BlenderError):
    pass


@dataclass
class BlenderResult:
    returncode: int
    result: dict = field(default_factory=dict)
    log_path: Optional[Path] = None
    duration_s: float = 0.0
    stdout_tail: str = ""


class BlenderRunner:
    def __init__(
        self,
        blender_path: Optional[str] = None,
        scripts_dir: Optional[Path] = None,
        timeout: Optional[int] = None,
    ):
        settings = get_settings()
        self.blender_path = blender_path or settings.blender_path
        self.scripts_dir = Path(scripts_dir or settings.blender_scripts_dir)
        self.timeout = timeout or settings.blender_timeout_seconds

    @property
    def configured(self) -> bool:
        return bool(self.blender_path) and Path(self.blender_path).exists()

    def version(self) -> str:
        self._require()
        out = subprocess.run(
            [self.blender_path, "-b", "--version"], capture_output=True, text=True, timeout=60
        )
        return out.stdout.strip().splitlines()[0] if out.stdout else out.stderr.strip()

    def _require(self) -> None:
        if not self.configured:
            raise BlenderNotConfigured(
                "BLENDER_PATH is not set or does not exist; set it in .env to the blender executable"
            )

    # ── core ─────────────────────────────────────────────────────
    def run(
        self,
        script: str,
        args: Optional[list[str]] = None,
        *,
        blend: Optional[Path] = None,
        log_path: Optional[Path] = None,
        timeout: Optional[int] = None,
        factory_startup: bool = True,
    ) -> BlenderResult:
        self._require()
        script_path = self.scripts_dir / script if not Path(script).is_absolute() else Path(script)
        if not script_path.exists():
            raise BlenderError(f"Blender script not found: {script_path}")

        cmd = [self.blender_path, "-b"]
        if blend is not None:
            cmd.append(str(blend))
        if factory_startup:
            cmd.append("--factory-startup")
        cmd += ["--python-exit-code", "1", "--python", str(script_path), "--", *(args or [])]

        log_file: Optional[IO[str]] = None
        if log_path is not None:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_file = open(log_path, "a", encoding="utf-8")
            log_file.write(f"$ {' '.join(cmd)}\n")

        tail: list[str] = []
        result_line: list[str] = []
        t0 = time.monotonic()
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )

        def pump() -> None:
            assert proc.stdout is not None
            for line in proc.stdout:
                if log_file is not None:
                    log_file.write(line)
                stripped = line.rstrip()
                if stripped.startswith(RESULT_PREFIX):
                    result_line.append(stripped[len(RESULT_PREFIX):])
                tail.append(stripped)
                if len(tail) > 40:
                    del tail[0]

        reader = threading.Thread(target=pump, daemon=True)
        reader.start()
        try:
            proc.wait(timeout=timeout or self.timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            reader.join(5)
            if log_file is not None:
                log_file.write("\n[aether] killed: timeout\n")
                log_file.close()
            raise BlenderTimeout(
                f"Blender exceeded {timeout or self.timeout}s and was killed", log_path, "\n".join(tail)
            )
        reader.join(5)
        duration = time.monotonic() - t0
        if log_file is not None:
            log_file.write(f"[aether] exit {proc.returncode} after {duration:.1f}s\n")
            log_file.close()

        result: dict = {}
        if result_line:
            try:
                result = json.loads(result_line[-1])
            except json.JSONDecodeError:
                result = {"raw": result_line[-1]}

        if proc.returncode != 0 or result.get("ok") is False:
            raise BlenderError(
                f"Blender exited with code {proc.returncode}: {result.get('error') or (tail[-1] if tail else 'no output')}",
                log_path,
                "\n".join(tail),
            )
        return BlenderResult(proc.returncode, result, log_path, duration, "\n".join(tail))

    # ── convenience ──────────────────────────────────────────────
    def smoke(
        self,
        out: Path,
        *,
        engine: str = "CYCLES",
        samples: int = 16,
        size: tuple[int, int] = (640, 360),
        log_path: Optional[Path] = None,
    ) -> BlenderResult:
        out = Path(out).resolve()
        out.parent.mkdir(parents=True, exist_ok=True)
        return self.run(
            "smoke.py",
            [
                "--out", str(out),
                "--engine", engine,
                "--samples", str(samples),
                "--width", str(size[0]),
                "--height", str(size[1]),
            ],
            log_path=log_path,
            timeout=300,
        )


def _main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Aether Blender runner")
    parser.add_argument("--smoke", nargs="?", const="smoke.png", metavar="OUT")
    parser.add_argument("--engine", default="CYCLES")
    parser.add_argument("--samples", type=int, default=16)
    parser.add_argument("--version", action="store_true")
    ns = parser.parse_args(argv)
    runner = BlenderRunner()
    if ns.version:
        print(runner.version())
        return 0
    if ns.smoke:
        res = runner.smoke(Path(ns.smoke), engine=ns.engine, samples=ns.samples)
        print(json.dumps({"duration_s": round(res.duration_s, 2), **res.result}, indent=2))
        return 0
    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(_main())
