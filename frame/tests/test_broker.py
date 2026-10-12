"""Check the bundled broker's static build and privilege-drop caller identity.

This never opens cameras, requests root or attaches to XRService.
"""
import json
import os
from pathlib import Path
import pwd
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
source = ROOT / "third_party/frametop/camd"
with tempfile.TemporaryDirectory(prefix="framephone-broker-") as directory:
    temp = Path(directory)
    wrapper = temp / "identity.c"
    wrapper.write_text('#define main broker_main\n#include ' + json.dumps(str(source / "camd.c")) + '''
#undef main
int main(void) {
    uid_t uid;
    gid_t gid;
    target_user(&uid, &gid);
    printf("%u:%u\\n", (unsigned)uid, (unsigned)gid);
    return 0;
}
''')
    binary = temp / "identity"
    subprocess.run(["cc", "-O2", "-std=gnu11", "-static", "-Wall", "-Wextra", "-o", str(binary),
                    str(wrapper), str(source / "tp.c"), str(source / "xrcams.c"), "-lm"], check=True)
    assert 'INTERP' not in subprocess.check_output(["readelf", "-l", str(binary)], text=True)
    account = next(p for p in pwd.getpwall() if p.pw_uid > 0 and p.pw_gid > 0)
    env = {k: v for k, v in os.environ.items() if k not in ("PKEXEC_UID", "SUDO_UID", "SUDO_GID")}
    for key in ("PKEXEC_UID", "SUDO_UID"):
        result = subprocess.run([str(binary)], env=env | {key: str(account.pw_uid)}, capture_output=True, text=True)
        assert result.returncode == 0 and result.stdout.strip() == f"{account.pw_uid}:{account.pw_gid}", result
    for invalid in (None, "", "0", "-1", "12garbage", "4294967296", "4294967295", "9999999999999999999999"):
        result = subprocess.run([str(binary)], env=env | ({} if invalid is None else {"PKEXEC_UID": invalid}), capture_output=True, text=True)
        assert result.returncode != 0, (invalid, result.stdout)
print("Static broker and authenticated caller identity checks passed (no privileges/cameras used).")
