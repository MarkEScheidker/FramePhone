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
    wrapper.write_text('#define ioctl framephone_test_ioctl\n#define main broker_main\n#include ' + json.dumps(str(source / "camd.c")) + '''
#undef main
#undef ioctl
static int starts, ends;
int framephone_test_ioctl(int fd, unsigned long request, ...) {
    assert(request == DMA_BUF_IOCTL_SYNC);
    va_list arguments;
    va_start(arguments, request);
    struct dma_buf_sync *sync = va_arg(arguments, struct dma_buf_sync *);
    va_end(arguments);
    (void)fd;
    if (sync->flags & DMA_BUF_SYNC_END) ends++;
    else starts++;
    return 0;
}
static void capture_mapping_test(void) {
    static xr_camera_t camera;
    static cam_t c;
    c.cam = &camera;
    c.nslots = camera.nqbuf = 4;
    int shuffled[] = {2, 0, 3, 1};
    for (int i = 0; i < 4; i++) {
        c.slot_group[i] = 0;
        c.slot_pos[i] = i;
        xr.groups[0].buf[i].xfd = 100 + shuffled[i];
        camera.qbuf_xfd[i] = 100 + i;
    }
    assert(map_query_buffers(&c));
    assert(c.mapped && c.maxindex == 3);
    for (int i = 0; i < 4; i++)
        assert(shuffled[c.slot_of[i]] == i);
    static uint8_t frames[4][4096], output[4 * (64+4096)];
    static fh_ring_cam_t ring_camera;
    c.need = sizeof(frames[0]);
    c.lay.width = c.lay.height = c.lay.pitch = 64;
    c.rc = &ring_camera;
    c.ring_slots = output;
    ring_camera.nslots = 4;
    ring_camera.stride = 64;
    ring_camera.slot_bytes = 64+4096;
    for (int i = 0; i < 4; i++) {
        memset(frames[i], 40+i, sizeof(frames[i]));
        c.map[i] = frames[i];
        c.fd[i] = i;
    }
    on_frame(&c, 3, 1, 123, mono_ns());
    assert(c.events == 1 && c.bright == 1 && ring_camera.latest == 1);
    fh_ring_slot_t *published = (fh_ring_slot_t *)(output + ring_camera.slot_bytes);
    assert(published->frame == 1 && published->capture_ns == 123);
    assert(*((uint8_t *)published+64) == 40+c.slot_of[3]);

    c.mapped = false;
    camera.qbuf_xfd[3] = 999;
    assert(!map_query_buffers(&c) && !c.mapped);
    camera.qbuf_xfd[3] = camera.qbuf_xfd[2];
    assert(!map_query_buffers(&c));
    camera.nqbuf = MAX_INDEX+1;
    assert(!map_query_buffers(&c));
    camera.nqbuf = 0;
    assert(!map_query_buffers(&c));
    camera.nqbuf = 4;
    camera.qbuf_xfd[3] = 103;
    xr.groups[0].buf[3].xfd = xr.groups[0].buf[0].xfd;
    assert(!map_query_buffers(&c));

    static uint64_t pixels[2][NSAMP];
    memset(&c, 0, sizeof(c));
    c.nslots = 2;
    c.need = sizeof(pixels[0]);
    for (int i = 0; i < 2; i++) {
        for (int j = 0; j < NSAMP; j++) pixels[i][j] = 42;
        c.fd[i] = i;
        c.map[i] = (const uint8_t *)pixels[i];
    }
    starts = ends = 0;
    learn(&c, 0);
    assert(starts == 2 && ends == 2);
    assert(c.learn_events == 1 && c.votes[0][0] == 1 && c.votes[0][1] == 1);
    /* A missing attachment must not collapse allocation positions. Unique
     * observed mappings may still recover via the per-index resolver. */
    memset(&c, 0, sizeof(c));
    c.nslots = 4;
    c.maxindex = 3;
    int positions[] = {0, 1, 3, 4};
    for (int i = 0; i < 4; i++) {
        c.slot_pos[i] = positions[i];
        c.nobs[i] = c.votes[i][i] = 10;
    }
    assert(!resolve_block(&c));
    resolve_map(&c);
    assert(c.mapped);
    puts("Exact queue mapping, allocation bounds and DMA synchronization passed.");
}
int main(int argc, char **argv) {
    if (argc == 2 && !strcmp(argv[1], "--mapping")) {
        capture_mapping_test();
        return 0;
    }
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
    subprocess.run([str(binary), "--mapping"], check=True)
    assert 'INTERP' not in subprocess.check_output(["readelf", "-l", str(binary)], text=True)
    grouping = temp / "grouping.c"
    grouping.write_text('#include <assert.h>\n#include ' + json.dumps(str(source / "xrcams.c")) + '''
int main(void) {
    static xr_state_t state;
    /* An unrelated allocation between plane 0 and plane 1 used to leave
     * 15/16 buffers in separate fragments. Reconstruct all 16 from QUERYBUF. */
    memset(&state, 0, sizeof(state));
    state.ncameras = 1;
    xr_camera_t *camera = &state.cameras[0];
    camera->nplanes = 2;
    camera->planesize[0] = 4096;
    camera->planesize[1] = 128;
    camera->nqbuf = 16;
    nfdents = 0;
    for (int i = 0; i < 16; i++) {
        camera->qbuf_xfd[i] = 300+4*((i*5)%16);
        fdents[nfdents++] = (fdent_t){ .kind=FD_DMABUF, .xfd=300+4*i, .size=4096 };
        if (i == 5)
            fdents[nfdents++] = (fdent_t){ .kind=FD_DMABUF, .xfd=301+4*i, .size=16*1024*1024 };
        fdents[nfdents++] = (fdent_t){ .kind=FD_DMABUF, .xfd=302+4*i, .size=128 };
    }
    build_groups(&state);
    assert(state.ngroups == 1 && state.groups[0].nbufs == 16 && state.groups[0].exact);
    for (int i = 0; i < 16; i++) {
        assert(state.groups[0].buf[i].xfd == 300+4*i);
        assert(state.groups[0].buf[i].size == 4096);
    }
    assert(state.groups[0].buf[5].xfd1 == -1); /* restored plane 0, not the unrelated buffer */
    camera->qbuf_xfd[16] = 321; /* wrong-sized allocation */
    camera->qbuf_xfd[17] = 999; /* nonexistent descriptor */
    camera->nqbuf = 18;
    complete_exact_groups(&state);
    assert(state.ngroups == 1 && state.groups[0].nbufs == 16); /* idempotent and bounded */
    puts("Interrupted plane pairing restored all 16 queried camera buffers.");
    return 0;
}
''')
    grouping_binary = temp / "grouping"
    subprocess.run(["cc", "-O2", "-std=gnu11", "-static", "-Wall", "-Wextra",
                    "-o", str(grouping_binary), str(grouping)], check=True)
    subprocess.run([str(grouping_binary)], check=True)
    account = next(p for p in pwd.getpwall() if p.pw_uid > 0 and p.pw_gid > 0)
    env = {k: v for k, v in os.environ.items() if k not in ("PKEXEC_UID", "SUDO_UID", "SUDO_GID")}
    for key in ("PKEXEC_UID", "SUDO_UID"):
        result = subprocess.run([str(binary)], env=env | {key: str(account.pw_uid)}, capture_output=True, text=True)
        assert result.returncode == 0 and result.stdout.strip() == f"{account.pw_uid}:{account.pw_gid}", result
    for invalid in (None, "", "0", "-1", "12garbage", "4294967296", "4294967295", "9999999999999999999999"):
        result = subprocess.run([str(binary)], env=env | ({} if invalid is None else {"PKEXEC_UID": invalid}), capture_output=True, text=True)
        assert result.returncode != 0, (invalid, result.stdout)
print("Static broker and authenticated caller identity checks passed (no privileges/cameras used).")
