import pytest

from backend.app.ai.video_source import VideoSource, VideoSourceError
from backend.app.core.enums import SourceType


def test_missing_file(tmp_path):
    with pytest.raises(VideoSourceError) as exc:
        VideoSource(SourceType.FILE, str(tmp_path / "missing.mp4")).open()
    assert exc.value.code == "SOURCE_NOT_FOUND"


def test_invalid_video_format(tmp_path):
    bogus = tmp_path / "not_a_video.mp4"
    bogus.write_text("this is not a video")
    with pytest.raises(VideoSourceError) as exc:
        VideoSource(SourceType.FILE, str(bogus)).open()
    assert exc.value.code == "INVALID_VIDEO"


def test_unavailable_webcam():
    with pytest.raises(VideoSourceError) as exc:
        VideoSource(SourceType.WEBCAM, "15").open()
    assert exc.value.code == "CAMERA_UNAVAILABLE"


def test_unreachable_stream():
    with pytest.raises(VideoSourceError) as exc:
        VideoSource(SourceType.RTSP, "rtsp://user:secret@127.0.0.1:9/stream", open_timeout_ms=1500).open()
    assert exc.value.code == "CAMERA_UNAVAILABLE"
    assert "secret" not in exc.value.message  # credentials never leak into errors


def test_frames_stride_and_timestamps(sample_video):
    with VideoSource(SourceType.FILE, str(sample_video)) as src:
        assert src.fps == pytest.approx(25.0)
        assert src.frame_count == 250
        assert (src.width, src.height) == (640, 360)
        frames = list(src.frames(stride=10))
    assert [i for i, _, _ in frames[:3]] == [0, 10, 20]
    assert len(frames) == 25
    assert frames[1][1] == pytest.approx(0.4)
    assert frames[0][2].shape == (360, 640, 3)


def test_max_frames_limit(sample_video):
    with VideoSource(SourceType.FILE, str(sample_video)) as src:
        assert len(list(src.frames(stride=1, max_frames=7))) == 7


def test_resources_released(sample_video):
    src = VideoSource(SourceType.FILE, str(sample_video))
    with src:
        assert src._cap is not None
    assert src._cap is None
    src.release()  # idempotent


def test_frames_requires_open(sample_video):
    with pytest.raises(RuntimeError):
        next(VideoSource(SourceType.FILE, str(sample_video)).frames())


def test_display_name_masks_credentials():
    assert VideoSource(SourceType.RTSP, "rtsp://admin:pw@10.0.0.5/live").display_name == "rtsp://***@10.0.0.5/live"
