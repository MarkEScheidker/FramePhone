"""Check single-file build handoff/errors with a simulated build engine.

Real native/ARM64 builds, extraction, detector and GUI smoke are separate CI jobs.
"""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("source_export", ROOT / "scripts/package-source.py")
export = importlib.util.module_from_spec(spec)
spec.loader.exec_module(export)
ENGINE = '''#!/usr/bin/env python3
import json, os, pathlib, sys
args = sys.argv[1:]
with open(os.environ['FAKE_LOG'], 'a') as log:
    log.write(json.dumps([pathlib.Path(sys.argv[0]).name, *args]) + '\\n')
if pathlib.Path(sys.argv[0]).name == 'podman':
    expected = ['--cgroup-manager=cgroupfs', '--events-backend=file']
    if args[:2] != expected:
        raise SystemExit('Podman build/export needs session-independent options: ' + repr(args))
    args = args[2:]
    if args[0] == 'build':
        if '--isolation=chroot' not in args:
            raise SystemExit('Error: simulated crun startup failure without chroot')
    elif any(arg.startswith('--isolation') for arg in args):
        raise SystemExit('build isolation option passed to export/cleanup')
elif any(arg.startswith('--isolation') for arg in args):
    raise SystemExit('Podman-specific build isolation passed to Docker')
if args[0] == 'build':
    print('STEP 1/2: simulated container build', flush=True)
    status = int(os.environ.get('FAKE_BUILD_STATUS', '0'))
    if status:
        print('Error: simulated RUN failure', file=sys.stderr)
    sys.exit(status)
elif args[:2] == ['image', 'inspect']:
    print(os.environ['FAKE_ARCH'])
elif args[0] == 'create':
    print('test-container')
elif args[0] == 'cp':
    if os.environ.get('FAKE_COPY_FAIL'):
        sys.exit(42)
    pathlib.Path(args[2]).write_bytes(b'simulated executable payload')
elif args[0] != 'rm':
    raise SystemExit('unexpected container command: ' + repr(args))
'''

with tempfile.TemporaryDirectory(prefix="framephone-package-") as folder:
    temp = Path(folder)
    project = temp / "source with spaces"
    for source in export.source_files():
        target = project / source.relative_to(ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    engines = temp / "engines"
    engines.mkdir()
    for name in ("podman", "docker"):
        path = engines / name
        path.write_text(ENGINE)
        path.chmod(0o755)
    # Model native ARM64 and cross builds without an actual container runtime.
    uname = engines / "uname"
    uname.write_text('''#!/usr/bin/env python3
import os, platform, sys
if sys.argv[1:] == ['-m']:
    print(os.environ.get('FAKE_MACHINE', platform.machine()))
elif sys.argv[1:] == ['-s']:
    print(platform.system())
else:
    raise SystemExit('unexpected uname arguments')
''')
    uname.chmod(0o755)
    native = {"x86_64": "amd64", "aarch64": "arm64"}[platform.machine()]
    log = temp / "commands.jsonl"
    env = dict(os.environ, PATH=str(engines) + os.pathsep + os.environ["PATH"],
               FRAMEPHONE_CONTAINER_ENGINE="docker", FAKE_LOG=str(log), FAKE_ARCH=native)

    def run(*args, ok=True, extra=None):
        result = subprocess.run(list(map(str, args)), cwd=project,
                                env=env | (extra or {}), capture_output=True, text=True)
        assert (result.returncode == 0) == ok, (args, result.stdout, result.stderr)
        return result

    def commands():
        return [json.loads(line) for line in log.read_text().splitlines()]

    build = project / "frame/build.sh"
    run("bash", build, "--arch", "native")
    call = next(c for c in commands() if c[1] == "build")
    assert call[call.index("--platform") + 1] == "linux/" + native
    assert "TARGET_ARCH=" + native in call
    executable = project / "frame/build/dist" / f"FramePhone-{native}.run"
    assert executable.read_bytes() == b"simulated executable payload"
    assert executable.stat().st_mode & 0o111
    assert hashlib.sha256(executable.read_bytes()).hexdigest() == executable.with_name(
        executable.name + ".sha256").read_text().split()[0]
    assert commands()[-1][1:] == ["rm", "test-container"]
    assert not any(c[1] in ("run", "save", "load") for c in commands())
    # Failed build, wrong architecture and failed export preserve the previous executable.
    original = executable.read_bytes()
    for extra in ({"FAKE_BUILD_STATUS": "42"}, {"FAKE_ARCH": "wrong"}, {"FAKE_COPY_FAIL": "1"}):
        run("bash", build, "--arch", "native", ok=False, extra=extra)
        assert executable.read_bytes() == original
    assert commands()[-1][1:] == ["rm", "test-container"]
    # Default must produce ARM64 even on an AMD64 build machine.
    run("bash", build, extra={"FAKE_ARCH": "arm64"})
    call = [c for c in commands() if c[1] == "build"][-1]
    assert call[call.index("--platform") + 1] == "linux/arm64"
    # Every Podman operation, including failure cleanup, uses the same manager.
    start = len(commands())
    podman = {"FRAMEPHONE_CONTAINER_ENGINE": "podman"}
    run("bash", build, "--arch", "native", extra=podman)
    calls = commands()[start:]
    assert [c[3] for c in calls] == ["build", "image", "create", "cp", "rm"], calls
    assert all(c[:3] == ["podman", "--cgroup-manager=cgroupfs", "--events-backend=file"] for c in calls)
    assert "--isolation=chroot" in calls[0] and all("--isolation=chroot" not in c for c in calls[1:])
    assert "Using Podman" in run("bash", build, "--arch", "native", extra=podman).stdout
    for failure in ({"FAKE_BUILD_STATUS": "42"}, {"FAKE_ARCH": "wrong"}, {"FAKE_COPY_FAIL": "1"}):
        result = run("bash", build, "--arch", "native", ok=False, extra=podman | failure)
        assert executable.read_bytes() == original
        if "FAKE_COPY_FAIL" in failure:
            assert commands()[-1][3:] == ["rm", "test-container"]
        if "FAKE_BUILD_STATUS" in failure:
            assert "Container build failed (exit 42)" in result.stderr
            assert "Error: simulated RUN failure" in result.stderr
    # A failure is not evidence of an architecture problem. Only cross builds
    # get the emulation hint; native ARM64 must never be told to install QEMU.
    for machine, target in (("aarch64", "arm64"), ("x86_64", "amd64"),
                            ("x86_64", "arm64"), ("aarch64", "amd64")):
        result = run("bash", build, "--arch", target, ok=False,
                     extra={"FAKE_MACHINE": machine, "FAKE_BUILD_STATUS": "42"})
        is_cross = (machine == "aarch64") != (target == "arm64")
        assert ("QEMU/binfmt" in result.stderr) == is_cross, result.stderr
        assert "Error: simulated RUN failure" in result.stderr
        log_path = Path(next(line.removeprefix("Build log: ")
                             for line in result.stdout.splitlines() if line.startswith("Build log: ")))
        assert "STEP 1/2" in log_path.read_text() and "Error: simulated RUN failure" in log_path.read_text()
        assert not list((project / "frame/build").glob("package.*"))
        assert executable.read_bytes() == original
    run("bash", build, "--arch", "invalid", ok=False)

print("Single-executable handoff/error checks passed (simulated build engine).")
