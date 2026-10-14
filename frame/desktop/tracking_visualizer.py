"""Tk diagnostics: image-space tags and an orthographic head-relative phone view."""
import math


def transform(point, rotation, translation):
    return [sum(rotation[3 * row + col] * point[col] for col in range(3)) + translation[row]
            for row in range(3)]


def project(point, width, height, span):
    """Fixed oblique view: +X right, +Y up, -Z forward; span is meters."""
    x, y, z = point
    scale = min(width, height) / span
    return (width * .5 + scale * (.85 * x + .5 * z),
            height * .72 - scale * (y - .3 * z))


def phone_outline(layout):
    """P axes are portrait-aligned, centered on the measured display."""
    cal = layout["calibration"]
    w, h = float(cal["portrait_width_m"]), float(cal["portrait_height_m"])
    if not all(math.isfinite(value) and 0 < value <= 2 for value in (w, h)):
        raise ValueError("invalid measured screen size")
    return [(-w / 2, h / 2, 0), (w / 2, h / 2, 0),
            (w / 2, -h / 2, 0), (-w / 2, -h / 2, 0)]


class TrackingVisualizer:
    def __init__(self, root, choose_layout=None, start_tracking=None):
        import tkinter as tk
        from tkinter import ttk
        self.window = tk.Toplevel(root)
        self.window.title("FramePhone — tracking visualizer")
        self.window.geometry("960x760")
        self.window.minsize(680, 560)
        self.window.columnconfigure(0, weight=1)
        self.window.rowconfigure(1, weight=1)
        self.window.rowconfigure(3, weight=2)
        ttk.Label(self.window, text="Uncalibrated • detected marker outlines in raw image coordinates",
                  padding=8).grid(row=0, column=0, sticky="w")
        images = ttk.Frame(self.window)
        images.grid(row=1, column=0, sticky="nsew", padx=8)
        images.rowconfigure(0, weight=1)
        self.images = []
        for index in range(2):
            images.columnconfigure(index, weight=1)
            canvas = tk.Canvas(images, background="#101c2c", highlightthickness=0, height=220)
            canvas.grid(row=0, column=index, sticky="nsew", padx=4)
            self.images.append(canvas)
        controls = ttk.Frame(self.window, padding=8)
        controls.grid(row=2, column=0, sticky="ew")
        ttk.Label(controls, text="Calibrated • head-relative 3D view (factory calibration)").pack(side="left")
        self.span = tk.StringVar(value="1.5")
        ttk.Combobox(controls, textvariable=self.span, values=("0.5", "1.5", "3", "6"),
                     state="readonly", width=5).pack(side="right")
        ttk.Label(controls, text="View span (m)").pack(side="right", padx=8)
        self.scene = tk.Canvas(self.window, background="#101c2c", highlightthickness=0)
        self.scene.grid(row=3, column=0, sticky="nsew", padx=12)
        self.status = tk.StringVar(value="Enable cameras for marker detection; Start tracking for a calibrated pose.")
        actions = ttk.Frame(self.window, padding=8)
        actions.grid(row=4, column=0, sticky="w")
        if choose_layout:
            ttk.Button(actions, text="Choose phone layout…", command=choose_layout).pack(side="left")
        if start_tracking:
            ttk.Button(actions, text="Start 3D tracking", command=start_tracking).pack(side="left", padx=8)
        ttk.Label(self.window, textvariable=self.status, padding=8, wraplength=900).grid(row=5, column=0, sticky="w")
        self.outline = None

    def render(self, views, progress, setup_message=None):
        for index, (canvas, view) in enumerate(zip(self.images, views)):
            canvas.delete("all")
            width, height = canvas.winfo_width(), canvas.winfo_height()
            title = ("Front left", "Front right")[index]
            canvas.create_text(12, 12, text=title, anchor="nw", fill="white")
            if not view or not view["evaluated"]:
                canvas.create_text(width / 2, height / 2, text="Waiting for live detections", fill="#bac6d6")
                continue
            scale = min((width - 24) / view["width"], (height - 48) / view["height"])
            ox, oy = (width - scale * view["width"]) / 2, 36
            canvas.create_rectangle(ox, oy, ox + scale * view["width"], oy + scale * view["height"], outline="#52667e")
            for marker, corners in zip(view["ids"], view.get("corners", [])):
                points = [(ox + x * scale, oy + y * scale) for x, y in corners]
                canvas.create_polygon(*[v for p in points for v in p], fill="", outline="#4be0b0", width=2)
                canvas.create_text(*points[0], text=str(marker), anchor="sw", fill="#ffdf80")
            canvas.create_text(width - 12, 12, text=f"{view['count']} markers", anchor="ne", fill="#4be0b0")
        canvas = self.scene
        canvas.delete("all")
        width, height, span = canvas.winfo_width(), canvas.winfo_height(), float(self.span.get())
        screen = lambda p: project(p, width, height, span)
        origin = screen((0, 0, 0))
        # The fixed head axes remain visible when tracking is lost.
        for axis, label, color in (((.2, 0, 0), "+X right", "#ff8c8c"),
                                    ((0, .2, 0), "+Y up", "#4be0b0"),
                                    ((0, 0, -.2), "−Z forward", "#80b8ff")):
            end = screen(axis)
            canvas.create_line(*origin, *end, fill=color, arrow="last", width=2)
            canvas.create_text(*end, text=label, fill=color, anchor="s")
        canvas.create_text(*origin, text="Head", fill="white", anchor="n")
        if not progress or progress["status"] != "accepted" or "rotation" not in progress:
            status = progress["status"].replace("_", " ") if progress else "no live pose"
            message = setup_message or "No calibrated phone pose — " + status
            canvas.create_text(width / 2, height * .2, text=message, width=max(200, width - 60),
                               fill="#bac6d6", font=("sans", 12))
            self.status.set(message + ". Image-space detection needs no calibration.")
            return
        t, r = progress["translation"], progress["rotation"]
        center = screen(t)
        canvas.create_line(*origin, *center, fill="#52667e", dash=(4, 4))
        if self.outline:
            points = [screen(transform(p, r, t)) for p in self.outline]
            canvas.create_polygon(*[v for p in points for v in p], fill="#1e4851", outline="#4be0b0", width=3)
        for axis, color in (((.06, 0, 0), "#ff8c8c"), ((0, .06, 0), "#4be0b0"), ((0, 0, .06), "#80b8ff")):
            canvas.create_line(*center, *screen(transform(axis, r, t)), fill=color, arrow="last", width=2)
        canvas.create_text(*center, text="Phone", fill="white", anchor="s")
        self.status.set(f"Factory pose • distance {progress['distance']:.3f} m • "
                        f"X {t[0]:+.3f}, Y {t[1]:+.3f}, Z {t[2]:+.3f} m • "
                        "screen outline and phone axes; metric accuracy still needs a measured check.")
