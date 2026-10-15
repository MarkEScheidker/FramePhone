"""Phone-only decoding, native coordinates, visible outlines and model integrity."""
from pathlib import Path
import sys
import tempfile
import unittest

import cv2 as cv
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "desktop"))
from phone_detection import PhoneDetector, decode, outline


class DetectionTests(unittest.TestCase):
    def test_native_coordinates_nms_and_competing_class(self):
        output = np.zeros((1, 8400, 85), dtype=np.float32)
        # First grid cell: x=100,y=120,w=40,h=80 in a 640px input.
        for i in (0, 1):
            output[0, i, :5] = [12.5 - i, 15, np.log(5), np.log(10), .9]
            output[0, i, 5 + 67] = .8
        output[0, 2] = output[0, 0]
        output[0, 2, 5] = .99  # Stronger person class: cannot become a phone.
        found = decode(output, 1280, 960)
        self.assertEqual(len(found), 1)
        np.testing.assert_allclose(found[0]["box_xywh"], [160, 160, 80, 160], atol=.001)
        self.assertAlmostEqual(found[0]["confidence"], .72, places=5)

    def test_padding_and_invalid_graph_do_not_become_detections(self):
        output = np.zeros((1, 8400, 85), dtype=np.float32)
        output[0, 0, :5] = [20, 60, np.log(5), np.log(10), .9]
        output[0, 0, 72] = .9
        self.assertEqual(decode(output, 640, 320), [])  # Entirely in bottom padding.
        with self.assertRaises(ValueError):
            decode(np.zeros((1, 100, 85)), 640, 480)

    def test_visible_quad_axis_and_missing_edges(self):
        gray = np.zeros((300, 300), dtype=np.uint8)
        quad = np.int32(cv.boxPoints(((150, 150), (65, 130), 25)))
        cv.fillConvexPoly(gray, quad, 220)
        box = list(cv.boundingRect(quad))
        result = outline(gray, box)
        self.assertIsNotNone(result)
        self.assertLess(abs(result["axis_deg_mod180"] + 65), 3)
        self.assertIsNone(outline(np.zeros_like(gray), box))
        self.assertEqual(len(result["corners_px"]), 4)

    def test_model_integrity_fails_before_loading(self):
        with tempfile.TemporaryDirectory() as folder:
            bad = Path(folder) / "model.onnx"
            bad.write_bytes(b"not the pinned model")
            with self.assertRaisesRegex(ValueError, "checksum"):
                PhoneDetector(bad)


if __name__ == "__main__":
    unittest.main()
