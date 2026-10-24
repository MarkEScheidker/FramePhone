"""Aspect-preserving camera display; source pixels and calibration stay unchanged."""
from io import BytesIO


def fit_image(data, width, height):
    import tkinter as tk
    from PIL import Image
    with Image.open(BytesIO(data)) as source:
        scale = min(max(1, width)/source.width, max(1, height)/source.height)
        size = (max(1, round(source.width*scale)), max(1, round(source.height*scale)))
        image = source.resize(size, Image.Resampling.BILINEAR)
        output = BytesIO()
        image.save(output, format="PPM")
        photo = tk.PhotoImage(data=output.getvalue(), format="PPM")
        return photo, (size[0]/source.width, size[1]/source.height), ((width-size[0])/2, (height-size[1])/2)
