import numpy as np

from astro_image_display_api import ImageViewerInterface
from astro_image_display_api.api_test import ImageAPITest

from .example_viewer import RecordingViewer


def test_instance():
    assert isinstance(RecordingViewer(), ImageViewerInterface)


def test_load_image_calls_setters_before_returning():
    viewer = RecordingViewer()
    viewer.load_image(np.zeros((4, 6)), image_label="a")
    assert [op for op, _ in viewer.display_calls] == [
        "set_viewport",
        "set_cuts",
        "set_stretch",
        "load_image",
    ]


class TestRecordingViewer(ImageAPITest):
    image_widget_class = RecordingViewer
