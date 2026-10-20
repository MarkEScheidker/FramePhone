"""Actual Tk/native photo workflow against a separately published synthetic ring."""
import hashlib
import io
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
from PIL import Image

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"desktop"))
from app import Runtime,Window

binary=Path(sys.argv[1]).resolve()
with tempfile.TemporaryDirectory(prefix="framephone-photo-gui-") as folder:
    root_path=Path(folder); fixture=root_path/"fixture"
    subprocess.run([str(binary/"framephone-photo-tests"),"--write-trial",str(fixture)],check=True)
    encoded=io.BytesIO()
    with Image.open(fixture/"reference/photo.pgm") as image:
        image.convert("RGB").save(encoded,format="PNG")
        size=image.size
    png=encoded.getvalue(); identity=hashlib.sha256(png).hexdigest()
    metadata={"id":identity,"width":size[0],"height":size[1],"size":len(png)}
    images=[(fixture/"motion"/f"pair-1-{v}.pgm").read_bytes().split(b"\n",3)[3] for v in range(2)]
    width,height=640,480; slot_bytes=64+width*height
    data=bytearray(1344+8*slot_bytes)
    struct.pack_into("<8sIIIIQqQ",data,0,b"FHRING01",1,1344,2,0,len(data),os.getpid(),time.monotonic_ns())
    for v,name in enumerate((b"slam_left",b"slam_right")):
        offset=64+v*160
        data[offset:offset+7]=b"og01a1b"
        data[offset+32:offset+32+len(name)]=name
        struct.pack_into("<IIIIIIQQ",data,offset+64,v,0,width,height,width,4,1344+v*4*slot_bytes,slot_bytes)
    ring=root_path/"ring"; ring.write_bytes(data)
    stop,blank,right_blank=threading.Event(),threading.Event(),threading.Event()
    def publish():
        number=0
        with ring.open("r+b",buffering=0) as file:
            while not stop.is_set():
                now=time.monotonic_ns(); number+=1
                os.pwrite(file.fileno(),struct.pack("<Q",now),40)
                for v in range(2):
                    start=1344+(v*4+number%4)*slot_bytes
                    os.pwrite(file.fileno(),struct.pack("<QQQQQIf",2*number+1,number,now+v*100000,now,now,number,100.),start)
                    hidden=blank.is_set() or (v == 1 and right_blank.is_set())
                    os.pwrite(file.fileno(),bytes([100])*len(images[v]) if hidden else images[v],start+64)
                    os.pwrite(file.fileno(),struct.pack("<Q",2*number+2),start)
                    os.pwrite(file.fileno(),struct.pack("<Q",number),64+v*160+104)
                stop.wait(.04)
    class TestRuntime(Runtime):
        def __init__(self): self.ring=ring; self.factory_root=fixture/"factory"
        def command(self,tool,*args): return [str(binary/f"framephone-{tool}"),*map(str,args)]
        def calibration_id(self): return "synthetic-factory-v1"
    class Phone:
        displayed=True
        def snapshot(self):
            return {"session":"synthetic-phone","photo":{"metadata":metadata,"state":{"id":identity,"displayed":self.displayed},"error":""}}
        def photo_reference(self): return png,metadata
        def stop(self): pass
    os.environ["XDG_CONFIG_HOME"]=str(root_path/"config")
    os.environ["XDG_STATE_HOME"]=str(root_path/"state")
    root=tk.Tk(); errors=[]
    root.report_callback_exception=lambda *error:errors.append(error)
    window=Window(root,TestRuntime())
    window.phone_panel.parent.after_cancel(window.phone_panel.timer)
    phone=Phone(); window.phone_panel.link=phone
    for name in ("left","left_stream"): getattr(window,name).set("slam_left")
    for name in ("right","right_stream"): getattr(window,name).set("slam_right")
    panel=window.photo_panel
    if "--learned" not in sys.argv[2:]:
        panel.backend.set("RootSIFT baseline")
    def until(predicate,timeout=20):
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            root.update()
            assert not errors,errors
            if predicate(): return
            time.sleep(.01)
        raise AssertionError((panel.status.get(),panel.pose.get()))
    writer=threading.Thread(target=publish); writer.start()
    try:
        panel.start()
        until(lambda:panel.result is not None and panel.result["status"]=="measured")
        assert "Photo XYZ" in panel.pose.get()
        assert panel.result["pose"]["rms_px"]<1.8
        assert panel.canvases[0].find_withtag("matching-area")
        assert panel.canvases[0].find_withtag("pose-match")
        right_blank.set()
        until(lambda:panel.result is not None and panel.result["status"]=="lost"
              and panel.result["view_inliers"][0]>=12 and panel.result["scene_features"][1]==0)
        assert "no current pose" in panel.pose.get()
        assert panel.canvases[0].find_withtag("image-match")
        assert not panel.canvases[0].find_withtag("pose-match")
        assert "reference matches" in panel.status.get() and "Stereo matched" in panel.status.get()
        right_blank.clear()
        until(lambda:panel.result is not None and panel.result["status"]=="measured")
        blank.set()
        until(lambda:panel.result is not None and panel.result["status"]=="lost")
        assert "no current pose" in panel.pose.get()
        blank.clear()
        until(lambda:panel.result is not None and panel.result["status"]=="measured")
        phone.displayed=False
        until(lambda:panel.cancelled.is_set() and not panel.busy)
        assert panel.result is None
        assert "state changed" in panel.status.get()
        phone.displayed=True
        panel.start()
        until(lambda:panel.result is not None and panel.result["status"]=="measured")
        window.phone_panel.link=None
        until(lambda:panel.cancelled.is_set() and not panel.busy)
        assert panel.result is None
    finally:
        stop.set(); writer.join(3); window.close()
        deadline=time.monotonic()+4
        while time.monotonic()<deadline:
            try:
                if not root.winfo_exists(): break
                root.update()
            except tk.TclError: break
            time.sleep(.01)
print("Photo Tk/native workflow passed: acquisition, one-camera evidence, loss, reacquisition, hidden photo and disconnect.")
