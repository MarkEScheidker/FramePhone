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
    /* An open-order binding to a 15-buffer run must not hide another
     * compatible run. Only positively identified foreign buffers are excluded. */
    xr.ncameras = 2;
    xr_camera_t *left = &xr.cameras[0], *right = &xr.cameras[1];
    memset(left, 0, sizeof(*left));
    memset(right, 0, sizeof(*right));
    strcpy(left->sensor, "og01a1b 4-0060");
    strcpy(right->sensor, "og01a1b 4-0036");
    for (int g = 0; g < 2; g++) {
        memset(&xr.groups[g], 0, sizeof(xr.groups[g]));
        xr.groups[g].planesize[0] = 4096;
        xr.groups[g].buf[0].xfd = 200+g;
    }
    xr.groups[0].cam = right; /* heuristic guess */
    xr.groups[1].cam = left;
    assert(candidate_buffer(right, 0, 0, 4096));
    assert(candidate_buffer(right, 1, 0, 4096));
    left->nqbuf = 1;
    left->qbuf_xfd[0] = 200;
    assert(!candidate_buffer(right, 0, 0, 4096));
    right->nqbuf = 1;
    right->qbuf_xfd[0] = 201;
    assert(candidate_buffer(right, 1, 0, 4096));
    right->qbuf_xfd[0] = 200; /* conflicting identities are not evidence */
    assert(!candidate_buffer(right, 0, 0, 4096));
    assert(!candidate_buffer(right, 1, 0, 8192));

    /* 15 candidates across fragments, 8 observed indices, shuffled queue.
     * The original shared-run gate loops forever despite unique evidence. */
    memset(&c, 0, sizeof(c));
    c.nslots = 7; /* primary open-order guess sees only unrelated buffers */
    c.ncandidates = 15;
    c.need = 4096;
    c.lay.width = c.lay.height = c.lay.pitch = 64;
    memset(&ring_camera, 0, sizeof(ring_camera));
    ring_camera.nslots = 4;
    ring_camera.stride = 64;
    ring_camera.slot_bytes = 64+4096;
    c.rc = &ring_camera;
    c.ring_slots = output;
    static uint64_t fragmented[15][NSAMP];
    int chosen[] = {12, 9, 14, 7, 11, 8, 13, 10};
    for (int s = 0; s < c.ncandidates; s++) {
        c.slot_group[s] = s < 7 ? 0 : 1;
        c.slot_pos[s] = 2*s+1; /* no contiguous allocation-order hypothesis */
        c.fd[s] = s;
        memset(fragmented[s], 80+s, sizeof(fragmented[s]));
        c.map[s] = (uint8_t *)fragmented[s];
        sample_words(c.map[s], c.need, c.samp[s]);
    }
    for (int cycle = 0; cycle < 28; cycle++) {
        for (int i = 0; i < 8; i++) {
            for (int k = 0; k < NSAMP; k++) fragmented[chosen[i]][k]++;
            on_frame(&c, i, cycle*8+i, cycle*8+i+1000, mono_ns());
        }
        if (cycle == 19) assert(!c.mapped && c.nslots == 7 && !ring_camera.published);
    }
    assert(c.mapped && c.shared && c.events == 224 && c.nslots == 15);
    assert(ring_camera.published >= 8 && ring_camera.latest >= 8);
    for (int i = 0; i < 8; i++) assert(c.slot_of[i] == chosen[i]);
    c.mapped = false;
    c.votes[0][1] = c.nobs[0]; /* indistinguishable second camera/buffer */
    resolve_map(&c);
    assert(!c.mapped);

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
    puts("Exact/fragmented queue mapping, ambiguity rejection and DMA learning passed.");
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
    state.ncameras = 2;
    for (int i = 0; i < 2; i++) {
        state.cameras[i].nplanes = 2;
        state.cameras[i].planesize[0] = 4096;
        state.cameras[i].planesize[1] = 128;
    }
    state.cameras[0].nqbuf = 1;
    state.cameras[0].qbuf_xfd[0] = 300;
    state.cameras[1].nqbuf = 15;
    nfdents = 32;
    for (int i = 0; i < 16; i++) {
        fdents[2*i].kind = fdents[2*i+1].kind = FD_DMABUF;
        fdents[2*i].size = 4096;
        fdents[2*i+1].size = 128;
        fdents[2*i].xfd = 300+2*i;
        fdents[2*i+1].xfd = 301+2*i;
        if (i) state.cameras[1].qbuf_xfd[i-1] = 300+2*i;
    }
    build_groups(&state);
    assert(state.ngroups == 2);
    assert(state.groups[0].nbufs == 1 && state.groups[1].nbufs == 15);
    assert(state.groups[0].cam == &state.cameras[0] && state.groups[0].exact);
    assert(state.groups[1].cam == &state.cameras[1] && state.groups[1].exact);
    state.ngroups = 0;
    state.cameras[0].nqbuf = state.cameras[1].nqbuf = 0;
    nfdents = 2;
    build_groups(&state);
    assert(state.ngroups == 0); /* unrelated one-buffer noise remains excluded */
    puts("QUERYBUF-owned short buffer fragments preserved.");
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
