"""Actual Tk + native capture/solve/tracker against an independent camera ring.

Run under Xvfb with the CMake build directory. No headset/phone/root required.
"""
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import threading
import time
import tkinter as tk
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "desktop"))
from app import Runtime, Window
from front_cameras import FRONT_CAMERAS

binary = Path(sys.argv[1]).resolve()
with tempfile.TemporaryDirectory(prefix="framephone-body-gui-") as folder:
    temporary = Path(folder)
    fixture = temporary / "fixture"
    subprocess.run([str(binary / "framephone-fiducial-tests"), "--write-trial", str(fixture)], check=True)
    images = [(fixture / "motion" / f"pair-1-{v}.pgm").read_bytes().split(b"\n", 3)[3] for v in range(2)]
    width, height = 640, 480
    strides = (width, width+32)
    slot_bytes = [64+stride*height for stride in strides]
    starts = (1344,1344+4*slot_bytes[0])
    data = bytearray(1344+4*sum(slot_bytes))
    struct.pack_into("<8sIIIIQqQ", data, 0, b"FHRING01", 1, 1344, 2, 0, len(data), os.getpid(), time.monotonic_ns())
    for v, name in enumerate(pair[1].encode() for pair in FRONT_CAMERAS):
        offset = 64 + v * 160
        data[offset:offset + 7] = b"og01a1b"
        data[offset + 32:offset + 32 + len(name)] = name
        struct.pack_into("<IIIIIIQQ", data, offset + 64, v, 0, width, height, strides[v], 4,
                         starts[v], slot_bytes[v])
    images[1] = b"".join(images[1][y*width:(y+1)*width]+bytes([222])*32 for y in range(height))
    ring = temporary / "ring"
    ring.write_bytes(data)
    stop, blank, pause = threading.Event(), threading.Event(), threading.Event()
    right_missing, right_blank, skewed = threading.Event(), threading.Event(), threading.Event()
    right_missing.set()
    def publish():
        number = 0
        with ring.open("r+b", buffering=0) as file:
            while not stop.is_set():
                if pause.is_set():
                    stop.wait(.02)
                    continue
                now = time.monotonic_ns()
                number += 1
                os.pwrite(file.fileno(), struct.pack("<Q", now), 40)
                for v in range(2):
                    if v == 1 and right_missing.is_set():
                        continue
                    start = starts[v]+(number%4)*slot_bytes[v]
                    capture = now+(20_000_000 if v and skewed.is_set() else v*100000)
                    os.pwrite(file.fileno(), struct.pack("<QQQQQIf", 2 * number + 1, number,
                              capture, now, now, number, 100.), start)
                    hidden = blank.is_set() or (v == 1 and right_blank.is_set())
                    os.pwrite(file.fileno(), bytes([24]) * len(images[v]) if hidden else images[v], start + 64)
                    os.pwrite(file.fileno(), struct.pack("<Q", 2 * number + 2), start)
                    os.pwrite(file.fileno(), struct.pack("<QQ", number, number), 64 + v * 160 + 104)
                stop.wait(.04)
    class TestRuntime(Runtime):
        overlay_command = None
        def __init__(self):
            self.ring = ring
            self.factory_root = fixture / "factory"
        def command(self, tool, *args):
            if tool == "overlay" and self.overlay_command:
                return [*self.overlay_command, *map(str, args)]
            return [str(binary / f"framephone-{tool}"), *map(str, args)]
        def calibration_id(self):
            return "synthetic-factory-v1"
        def camera_command(self):
            return [sys.executable, "-c", "import time;print('running without privileges',flush=True);time.sleep(90)"]
    target = {"family": "tag36h11", "id": 0, "black_edge_m": .06,
              "origin": "black_square_center", "axes": "right_up_front", "size_source": "manual_black_edge",
              "screen_width_px": 1080, "screen_height_px": 2400, "black_edge_px": 864}
    class Phone:
        displayed = True
        session_id = "synthetic-phone"
        arcore = False
        automatic = False
        required = True
        ar_state = "tracking"
        acquisition = "scan-1"
        commands = []
        def pose_packet(self):
            return self.snapshot()["arcore"]
        def alignment_command(self, kind, generation, acquisition):
            self.commands.append(kind)
            if kind == "alignment_accepted":
                self.displayed = False
                self.required = False
            else:
                self.required = True
            return True
        def snapshot(self):
            now = time.monotonic_ns()
            packet = {"schema": "framephone-arcore-v1", "session": self.session_id, "clock_valid": True,
                      "received_host_monotonic_ns": now, "poses": [{"generation": "anchor-1",
                      "acquisition": self.acquisition, "state": self.ar_state, "marker_required": self.required,
                      "host_t_ns": now, "translation_m": [0, 0, 0], "quaternion_xyzw": [0, 0, 0, 1]}]}
            return {"session": self.session_id, "dimensions": (.07, .15, .009), "fiducial": target,
                    "marker_displayed": self.displayed, "marker_state_fresh": True, "arcore": packet if self.arcore else None, "automatic_marker": self.automatic}
        def stop(self):
            pass
    os.environ["XDG_CONFIG_HOME"] = str(temporary / "config")
    os.environ["XDG_STATE_HOME"] = str(temporary / "state")
    settings = temporary / "config/framephone"
    settings.mkdir(parents=True)
    (settings/"settings.json").write_text(json.dumps({"left": "wrong", "left_stream": "side-camera"}))
    root = tk.Tk()
    errors = []
    root.report_callback_exception = lambda *error: errors.append(error)
    runtime = TestRuntime()
    window = Window(root, runtime)
    root.geometry("720x600")
    # Keep the real telemetry UI idle; only the snapshot boundary is substituted.
    window.phone_panel.parent.after_cancel(window.phone_panel.timer)
    phone = Phone()
    window.phone_panel.link = phone
    # The synthetic connection replaces the real connected event and readouts.
    window.phone_panel.settings.pack_forget()
    for row in window.phone_panel.rows.values():
        row.set("X +0.000 Y +0.000 Z +0.000\n120.0 Hz · age ≈ 12.3 ms")
    phone_startups = []
    window.phone_panel.startup = lambda: phone_startups.append(True)
    assert window.camera_selection == tuple(item[0] for item in FRONT_CAMERAS)+tuple(item[1] for item in FRONT_CAMERAS)
    writer = threading.Thread(target=publish)
    writer.start()
    panel = window.tracking_panel
    # Observe the actual process/atomic-pose handoff without requiring a GPU or
    # SteamVR. Native geometry/loader failures are checked separately by CTest.
    helper = temporary / "observe_overlay.py"
    observed = temporary / "overlay-states"
    helper.write_text("import json,sys,time\nfrom pathlib import Path\n"
                      "session=Path(sys.argv[-1])\n"
                      f"log=Path({str(observed)!r}).open('a',buffering=1)\n"
                      "print('VR screen ready: synthetic process observer',flush=True)\n"
                      "previous=None\nwhile True:\n"
                      "    state=json.loads((session/'vr-pose.json').read_text())['status']\n"
                      "    if state!=previous: log.write(state+'\\n'); previous=state\n"
                      "    time.sleep(.01)\n")
    runtime.overlay_command = [sys.executable, "-B", str(helper)]
    panel.vr_enabled.set(True)
    def until(predicate, timeout=10):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            root.update()
            assert not errors, errors
            if predicate(): return
            time.sleep(.01)
        raise AssertionError((panel.status.get(), panel.pose.get()))
    try:
        until(lambda: window.status.get().startswith("Front cameras ready"))
        assert "camera" in window.processes, "startup did not enable cameras"
        assert phone_startups == [True], "startup did not initiate phone discovery"
        def widgets(parent):
            return [child for direct in parent.winfo_children() for child in [direct, *widgets(direct)]]
        assert not any(w.winfo_class() == "TCombobox" for w in widgets(panel.parent)), "camera selection remains editable"
        assert not any(w.winfo_class() == "TNotebook" for w in widgets(root)), "dashboard still uses tabs"
        until(lambda: bool(panel.preview_detections[0]) and "Waiting for camera frames" in panel.camera_status[1].get())
        assert not panel.busy and panel.result is None
        assert panel.preview_detections[0] and panel.preview_detections[0][0]["id"] == 0
        assert panel.preview_images[0] != b"P5\n640 480\n255\n"+images[0], "preview has no drawn tag annotations"
        assert panel.preview_images[1] is None and panel.images is None
        panel.start()
        assert not panel.busy and "Front right" in panel.status.get()
        right_missing.clear()
        until(lambda: all(panel.preview_detections))
        original_command = runtime.command
        def failed_right(tool, *args):
            if args and args[0] == "--preview-ring" and args[-1] == FRONT_CAMERAS[1][1]:
                return [sys.executable, "-c", "import sys;sys.stderr.write('Camera preview failed');sys.exit(4)"]
            return original_command(tool, *args)
        runtime.command = failed_right
        window.preview_reader.stop(1)
        until(lambda: "Camera preview failed" in panel.camera_status[1].get())
        assert panel.preview_images[0] and panel.preview_images[1] is None
        runtime.command = original_command
        until(lambda: all(panel.preview_detections))
        assert all(getattr(canvas,"image",None) for canvas in panel.canvases)
        for canvas in panel.canvases:
            assert canvas.winfo_ismapped() and canvas.winfo_height() > 40
            image_item = canvas.find_all()[0]
            x, y = canvas.coords(image_item)
            assert abs(x-(canvas.winfo_width()-canvas.image.width())/2) <= 1
            assert abs(y-(canvas.winfo_height()-canvas.image.height())/2) <= 1
            assert min(canvas.winfo_width()-canvas.image.width(),
                       canvas.winfo_height()-canvas.image.height()) <= 1
            assert canvas.winfo_rootx()+canvas.winfo_width() <= root.winfo_rootx()+root.winfo_width()
        assert panel.pose_label.winfo_rooty()+panel.pose_label.winfo_height() <= root.winfo_rooty()+root.winfo_height()
        window.self_test()
        until(lambda: window.self_test_result is not None)
        assert window.self_test_result
        window.show_views.set(False)
        window.toggle_views()
        until(lambda: not window.preview_reader.workers)
        assert not any(canvas.winfo_ismapped() for canvas in panel.canvases)
        window.show_views.set(True)
        window.toggle_views()
        until(lambda: all(panel.preview_detections))
        window.toggle_log()
        root.update()
        assert window.log_panel.winfo_ismapped()
        window.toggle_log()
        root.update()
        assert not window.log_panel.winfo_ismapped()
        until(lambda: all(panel.preview_detections))
        panel.start()
        until(lambda: panel.result is not None and panel.result["status"] == "measured")
        assert "Marker center XYZ" in panel.pose.get()
        assert "left 1" in panel.status.get() and "right 1" in panel.status.get()
        assert all(c.find_withtag("pose-axis") for c in panel.canvases)
        window.show_views.set(False)
        window.toggle_views()
        until(lambda: not window.preview_reader.workers)
        assert panel.busy and panel.result["status"] == "measured"
        window.show_views.set(True)
        window.toggle_views()
        until(lambda: all(panel.preview_detections))
        with patch("fiducial_panel.preview_pair", return_value=None):
            until(lambda: panel.result is not None and panel.result["status"] == "measured" and panel.images is None)
            assert "Marker center XYZ" in panel.pose.get()
            assert not any(c.find_withtag("pose-axis") for c in panel.canvases), "old pose drawn on unpaired raw frames"
        until(lambda: panel.result is not None and panel.images is not None)
        right_blank.set()
        until(lambda: panel.result is not None and panel.result["status"] == "lost" and
              len(panel.result["detections"][0]) == 1 and not panel.result["detections"][1])
        assert panel.canvases[0].find_withtag("tag-detection")
        assert not any(c.find_withtag("pose-axis") for c in panel.canvases)
        right_blank.clear()
        until(lambda: panel.result is not None and panel.result["status"] == "measured")
        until(lambda: observed.exists() and "measured" in observed.read_text())
        assert "processed_host_monotonic_ns" in json.loads((panel.session/"vr-pose.json").read_text())
        pause.set()
        until(lambda: panel.result is None and "Stale" in panel.pose.get())
        assert json.loads((panel.session/"vr-pose.json").read_text())["status"] == "lost"
        pause.clear()
        until(lambda: panel.result is not None and panel.result["status"] == "measured")
        blank.set()
        until(lambda: panel.result is not None and panel.result["status"] == "lost")
        assert "no current" in panel.pose.get()
        assert not panel.result["candidates"]
        until(lambda: "lost" in observed.read_text())
        blank.clear()
        until(lambda: panel.result is not None and panel.result["status"] == "measured")
        assert not list(panel.session.glob("*telemetry*")), "recording must be opt-in"
        assert not (panel.session/"corners.json").exists()
        phone.displayed = False
        until(lambda: not panel.busy and "overlay" not in window.processes)
        assert json.loads((panel.session/"vr-pose.json").read_text())["status"] == "lost"
        assert "marker hidden" in panel.status.get()
        phone.displayed = True
        skewed.set()
        time.sleep(.1)
        panel.start()
        until(lambda: not panel.busy,timeout=10)
        assert "no synchronized pair" in panel.status.get()
        assert "latest skew" in panel.status.get() and "limit 3 ms" in panel.status.get()
        # Preview workers restart after the tracker relinquishes the cameras.
        until(lambda: all(panel.preview_images) and len(window.preview_reader.workers) == 2)
        assert all(c.winfo_height() > 40 for c in panel.canvases), "status text pushed camera data out of view"
        assert not any(c.find_withtag("pose-axis") for c in panel.canvases)
        skewed.clear()
        time.sleep(.1)
        panel.start()
        until(lambda: panel.result is not None and panel.result["status"] == "measured")
        window.phone_panel.link = None
        until(lambda: not panel.busy and "overlay" not in window.processes)
        assert panel.result is None and "no current pose" in panel.pose.get()
        assert "disconnected" in panel.status.get().lower(), panel.status.get()
        assert (panel.session/"tracker.log").exists()
        print("Tk single-tag pose, VR process/publication, stale/blank loss, marker hiding, reacquisition and disconnect clearing passed")
        # Native engine geometry is covered independently. This process fixture
        # exercises the actual dashboard/command/gate lifecycle without SteamVR.
        helper.write_text("""import json,sys,time
from pathlib import Path
s=Path(sys.argv[-1]); key=None; accepted=False; changed=0
while True:
    try:
        p=json.loads((s/'phone-pose.json').read_text())['poses'][-1]
        k=(p['generation'],p['acquisition'])
        if k!=key: key=k; accepted=False; changed=time.monotonic_ns()
        o=json.loads((s/'vr-pose.json').read_text())
        if p['state']!='tracking': accepted=False
        elif o.get('status')=='measured' and o.get('processed_host_monotonic_ns',0)>=changed: accepted=True
        state={'generation':key[0],'acquisition':key[1],'state':'tracking' if accepted else 'acquiring',
               'visible':accepted and (s/'allow-visible').exists(),'reason':'synthetic handoff process','updated_host_monotonic_ns':time.monotonic_ns()}
        t=s/'arcore-state.json.tmp'; t.write_text(json.dumps(state)); t.replace(s/'arcore-state.json')
    except (OSError,ValueError,KeyError,IndexError): pass
    time.sleep(.03)
""")
        window.phone_panel.link = phone
        phone.arcore = True
        phone.automatic = True
        phone.session_id = "automatic-session"
        phone.displayed = True
        until(lambda: panel.busy and (panel.session/'arcore-state.json').exists() and
              json.loads((panel.session/'arcore-state.json').read_text()).get('state')=='tracking')
        assert phone.displayed and not panel.handoff_active, 'marker hidden before VR visibility confirmation'
        (panel.session/'allow-visible').touch()
        until(lambda: panel.handoff_active and not phone.displayed)
        assert panel.busy and panel.config['arcore_handoff'] and 'overlay' in window.processes
        assert not panel.arcore_toggle.winfo_ismapped()
        assert 'alignment_accepted' in phone.commands
        until(lambda: not window.preview_reader.workers)
        assert (panel.session/'optical-paused').exists()
        deadline=time.monotonic()+.3
        until(lambda: time.monotonic()>=deadline)
        before=(panel.session/'run/poses.jsonl').read_bytes()
        deadline=time.monotonic()+.4
        until(lambda: time.monotonic()>=deadline)
        assert (panel.session/'run/poses.jsonl').read_bytes()==before, 'detector still running after handoff'
        phone.ar_state='paused'
        phone.acquisition='scan-2'
        phone.required=True
        until(lambda: not panel.handoff_active and 'automatic marker' in panel.status.get())
        assert panel.busy and (panel.session/'optical-paused').exists()
        phone.displayed=True
        until(lambda: panel.result is not None and panel.result['status']=='measured' and
              not (panel.session/'optical-paused').exists())
        assert not panel.handoff_active and phone.displayed, 'ARCore resume must not gate optical detection or accept early'
        window.terminate('overlay')
        until(lambda: 'overlay' not in window.processes)
        until(lambda: panel.result is not None and panel.result['status']=='measured' and
              not (panel.session/'optical-paused').exists())
        assert phone.displayed and not panel.handoff_active, 'renderer shutdown incorrectly suppressed detection'
        phone.acquisition='scan-2-ready'
        phone.ar_state='tracking'
        until(lambda: panel.handoff_active and not phone.displayed)
        # A screen-off/resume may report a new display layout. Rebuild the
        # optical session automatically rather than blocking this paired link.
        previous_session=panel.session
        target['screen_height_px'] += 10
        phone.acquisition='scan-3'
        phone.required=True
        phone.displayed=True
        until(lambda: panel.session!=previous_session and panel.busy)
        assert panel.config['fiducial']['screen_height_px']==target['screen_height_px']
        (panel.session/'allow-visible').touch()
        until(lambda: panel.handoff_active and not phone.displayed)
        panel.stop(manual=True)
        until(lambda: not panel.busy and 'overlay' not in window.processes)
        phone.acquisition='scan-4'
        phone.required=True
        phone.displayed=True
        deadline=time.monotonic()+.4
        until(lambda: time.monotonic()>=deadline)
        assert not panel.busy, 'deliberate Stop restarted automatically'
        window.phone_panel.link=None
        assert not panel.handoff_active
        print('Tk ARCore acknowledgment, detector suspension, reacquisition, layout recovery and manual Stop passed')
    finally:
        stop.set()
        writer.join(timeout=2)
        panel.close()
        window.preview_reader.close()
        window.phone_panel.close()
        for name in list(window.processes):
            window.terminate(name)
        root.destroy()
