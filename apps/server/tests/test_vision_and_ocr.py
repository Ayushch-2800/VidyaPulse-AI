import importlib.util
import os
import sys
from types import SimpleNamespace

import pytest


class FakeCapture:
    """A video as a list of frames; each frame is a number standing for its picture."""

    frames = []
    fps = 2.0
    opened = True

    def __init__(self, path):
        self.position = 0

    def isOpened(self):
        return FakeCapture.opened

    def get(self, prop):
        return FakeCapture.fps

    def set(self, prop, value):
        self.position = int(value)

    def read(self):
        if self.position >= len(FakeCapture.frames):
            return False, None
        frame = FakeCapture.frames[self.position]
        self.position += 1
        return True, frame

    def release(self):
        pass


def fake_ssim(a, b, full=False):
    return (1.0 if a == b else 0.2), None


@pytest.fixture
def vision(stub, monkeypatch, tmp_path):
    """vision_extractor against fake OpenCV and scikit-image, writing frames to tmp_path."""

    def imwrite(path, frame, params):
        with open(path, "w") as f:
            f.write(str(frame))
        return True

    stub(
        "cv2",
        VideoCapture=FakeCapture,
        CAP_PROP_FPS=5,
        CAP_PROP_POS_FRAMES=1,
        COLOR_BGR2GRAY=6,
        IMWRITE_JPEG_QUALITY=1,
        cvtColor=lambda frame, code: frame,
        imwrite=imwrite,
    )
    stub("skimage")
    stub("skimage.metrics", structural_similarity=fake_ssim)
    sys.modules.pop("vision_extractor", None)
    import vision_extractor

    monkeypatch.setattr(vision_extractor, "TEMP_DIR", str(tmp_path))
    monkeypatch.setattr(vision_extractor.time, "sleep", lambda s: None)
    FakeCapture.opened = True
    yield vision_extractor
    sys.modules.pop("vision_extractor", None)


def test_slide_changes_become_keyframes_with_ocr(vision, db, monkeypatch, tmp_path):
    # 2 fps, sampled once a second: slides change at 2s and 4s; frame 0 is always kept
    FakeCapture.frames = ["A", "A", "A", "A", "B", "B", "B", "B", "C", "C"]
    ocr = {"A": "Intro", "B": "", "C": "$$\\int x\\,dx$$"}

    def extract(image_path, timestamp):
        with open(image_path) as f:
            return {
                "image_path": image_path,
                "extracted_content": ocr[f.read()],
                "timestamp": timestamp,
            }

    monkeypatch.setattr(vision, "extract_visual_data", extract)
    frames = vision.process_video_keyframes(
        "talk.mp4", "lec", "user", ssim_threshold=0.7
    )

    assert [f["timestamp_seconds"] for f in frames] == [0.0, 2.0, 4.0]
    assert [f["extracted_text"] for f in frames] == ["Intro", "", "$$\\int x\\,dx$$"]
    assert all(f["storage_path"].startswith("user/lec/") for f in frames)
    assert [u["bucket"] for u in db.storage.uploads] == ["lecture-keyframes"] * 3
    assert len(db.tables["keyframes"]) == 3
    assert os.listdir(tmp_path) == []  # local frames are deleted after upload


def test_unreadable_and_empty_videos(vision):
    FakeCapture.opened = False
    with pytest.raises(ValueError, match="Could not open video"):
        vision.process_video_keyframes("bad.mp4", "lec", "user")
    FakeCapture.opened = True
    FakeCapture.frames = []
    assert vision.process_video_keyframes("empty.mp4", "lec", "user") == []


class FakeGenaiModels:
    replies = []

    def generate_content(self, model, contents, config):
        reply = FakeGenaiModels.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return SimpleNamespace(text=reply)


@pytest.fixture
def ocr(monkeypatch, no_sleep, tmp_path):
    from google import genai
    from PIL import Image

    import ocr_engine

    monkeypatch.setattr(
        genai, "Client", lambda: SimpleNamespace(models=FakeGenaiModels())
    )
    image = tmp_path / "frame.jpg"
    Image.new("RGB", (8, 8), "white").save(image)
    return ocr_engine, str(image)


def test_ocr_extracts_slide_text(ocr):
    engine, image = ocr
    FakeGenaiModels.replies = ["  $$a^2+b^2=c^2$$ "]
    result = engine.extract_visual_data(image, 12.0)
    assert result == {
        "timestamp": 12.0,
        "image_path": image,
        "extracted_content": "$$a^2+b^2=c^2$$",
        "content_type": "visual_ocr",
    }


def test_ocr_retries_busy_errors_and_gives_up_on_others(ocr, no_sleep):
    engine, image = ocr
    FakeGenaiModels.replies = [RuntimeError("503 UNAVAILABLE"), "Slide"]
    assert engine.extract_visual_data(image, 1.0)["extracted_content"] == "Slide"
    assert no_sleep == [5]

    FakeGenaiModels.replies = [RuntimeError("400 bad image")]
    assert engine.extract_visual_data(image, 1.0)["extracted_content"] == ""


def test_ocr_missing_frame(ocr):
    engine, _ = ocr
    with pytest.raises(FileNotFoundError):
        engine.extract_visual_data("/no/frame.jpg", 0.0)


@pytest.mark.skipif(
    not (importlib.util.find_spec("cv2") and importlib.util.find_spec("skimage")),
    reason="OpenCV and scikit-image are not installed",
)
def test_real_opencv_finds_slide_changes_in_a_noisy_video(db, monkeypatch, tmp_path):
    """A real encoded video: 3 slides with sensor noise, as a phone recording of a board would have."""
    import cv2
    import numpy as np

    sys.modules.pop("vision_extractor", None)
    import vision_extractor

    path = str(tmp_path / "board.avi")
    writer = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"MJPG"), 4, (160, 120))
    rng = np.random.default_rng(0)
    slides = [
        ["Limits", "x->0", "sin x/x"],
        ["Chain rule", "f(g(x))", "f'g'"],
        ["Integrals", "int x dx", "x^2/2"],
    ]
    for lines in slides:
        for _ in range(8):  # 2 seconds per slide
            frame = np.full((120, 160, 3), 255, np.uint8)
            for i, line in enumerate(lines):
                cv2.putText(
                    frame,
                    line,
                    (5, 30 + i * 35),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.9,
                    (0, 0, 0),
                    2,
                )
            noise = rng.integers(0, 12, frame.shape, dtype=np.uint8)
            writer.write(cv2.subtract(frame, noise))
    writer.release()

    monkeypatch.setattr(vision_extractor, "TEMP_DIR", str(tmp_path))
    monkeypatch.setattr(
        vision_extractor,
        "extract_visual_data",
        lambda image_path, timestamp: {
            "image_path": image_path,
            "extracted_content": f"slide at {timestamp}",
        },
    )
    monkeypatch.setattr(vision_extractor.time, "sleep", lambda s: None)
    frames = vision_extractor.process_video_keyframes(
        path, "lec", "user", ssim_threshold=0.7
    )
    sys.modules.pop("vision_extractor", None)
    assert [f["timestamp_seconds"] for f in frames] == [0.0, 2.0, 4.0]
