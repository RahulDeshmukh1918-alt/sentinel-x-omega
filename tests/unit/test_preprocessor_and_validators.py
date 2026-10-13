import numpy as np
import pytest

from backend.app.ai.preprocessor import InvalidFrameError, preprocess
from backend.app.core.enums import SourceType
from backend.app.core.validators import (
    SourceValidationError, mask_credentials, safe_path_within, sanitise_filename, validate_source,
)

EXT = [".mp4", ".avi"]


# ---------------------------------------------------------------- preprocessing
def test_wide_frames_are_downscaled():
    p = preprocess(np.zeros((1080, 1920, 3), np.uint8), max_width=960)
    assert p.image.shape == (540, 960, 3)
    assert p.scale == pytest.approx(0.5)
    assert p.original_size == (1920, 1080)


def test_small_frames_untouched_and_gray_converted():
    p = preprocess(np.zeros((100, 200), np.uint8), max_width=960)
    assert p.image.shape == (100, 200, 3) and p.scale == 1.0


@pytest.mark.parametrize("bad", [None, np.zeros((0, 0, 3), np.uint8), np.zeros((10, 10, 2), np.uint8), "frame"])
def test_invalid_frames_rejected(bad):
    with pytest.raises(InvalidFrameError):
        preprocess(bad)


# ---------------------------------------------------------------- validators
@pytest.mark.parametrize("uri,expected", [
    ("rtsp://admin:pw@10.0.0.5:554/s1", "rtsp://***@10.0.0.5:554/s1"),
    ("http://cam.local/video?token=abc", "http://cam.local/video?***"),
    ("rtsp://10.0.0.5/s1", "rtsp://10.0.0.5/s1"),
    ("0", "0"),
])
def test_mask_credentials(uri, expected):
    assert mask_credentials(uri) == expected


def test_safe_path_within_blocks_traversal(tmp_path):
    assert safe_path_within(tmp_path, "clip.mp4") == (tmp_path / "clip.mp4").resolve()
    assert safe_path_within(tmp_path, "sub/clip.mp4").parent.name == "sub"
    for bad in ["../secret.mp4", "sub/../../x.mp4", "/etc/passwd", "", "a\x00b"]:
        with pytest.raises(SourceValidationError):
            safe_path_within(tmp_path, bad)


def test_validate_webcam(tmp_path):
    assert validate_source(SourceType.WEBCAM, " 0 ", sample_dir=tmp_path, allowed_ext=EXT) == "0"
    for bad in ["-1", "abc", "99"]:
        with pytest.raises(SourceValidationError):
            validate_source(SourceType.WEBCAM, bad, sample_dir=tmp_path, allowed_ext=EXT)


def test_validate_rtsp(tmp_path):
    ok = "rtsp://user:pw@192.168.1.10:554/stream1"
    assert validate_source(SourceType.RTSP, ok, sample_dir=tmp_path, allowed_ext=EXT) == ok
    for bad in ["ftp://host/x", "rtsp://", "file:///etc/passwd", "not a url"]:
        with pytest.raises(SourceValidationError):
            validate_source(SourceType.RTSP, bad, sample_dir=tmp_path, allowed_ext=EXT)


def test_validate_file(tmp_path):
    assert validate_source(SourceType.FILE, "clip.MP4", sample_dir=tmp_path, allowed_ext=EXT) == "clip.MP4"
    with pytest.raises(SourceValidationError):
        validate_source(SourceType.FILE, "clip.exe", sample_dir=tmp_path, allowed_ext=EXT)
    with pytest.raises(SourceValidationError):
        validate_source(SourceType.FILE, "../../clip.mp4", sample_dir=tmp_path, allowed_ext=EXT)


@pytest.mark.parametrize("name,expected", [
    ("../../etc/passwd", "passwd"), ("my video (1).mp4", "my_video_1_.mp4"), ("", "upload"), ("...", "upload"),
])
def test_sanitise_filename(name, expected):
    assert sanitise_filename(name) == expected
