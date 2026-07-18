# Tests of the template-method rendering hooks in ImageViewerLogic: the
# public API methods own all state handling and label resolution, then call
# private no-op hooks (with already-resolved labels) that display backends
# override to update their display.
#
# The hook mechanism is an implementation detail of ImageViewerLogic, not
# part of the API contract -- implementations of the API do not have to
# adopt it -- so these tests live here rather than in the ImageAPITest
# compliance suite.

from contextlib import contextmanager

import numpy as np
import pytest
from astropy.table import Table
from astropy.visualization import LogStretch

from astro_image_display_api.image_viewer_logic import ImageViewerLogic

IMAGE_SHAPE = (100, 150)


@pytest.fixture
def data():
    rng = np.random.default_rng(1234)
    return rng.random(IMAGE_SHAPE)


@pytest.fixture
def catalog():
    rng = np.random.default_rng(45328975)
    return Table(
        dict(
            x=rng.uniform(0, IMAGE_SHAPE[0], size=10),
            y=rng.uniform(0, IMAGE_SHAPE[1], size=10),
        )
    )


def make_recording_viewer():
    """
    Create a viewer whose rendering hooks record their calls.

    The hooks are no-ops in ImageViewerLogic, so the overrides do not
    need to call super().

    Returns
    -------
    viewer, calls
        An ImageViewerLogic subclass instance and the list that the hook
        calls are recorded in as ``(hook_name, label)`` tuples.
    """
    calls = []

    class RecordingViewer(ImageViewerLogic):
        def _render_image(self, image_label):
            calls.append(("render_image", image_label))

        def _apply_cuts(self, image_label):
            calls.append(("apply_cuts", image_label))

        def _apply_stretch(self, image_label):
            calls.append(("apply_stretch", image_label))

        def _apply_colormap(self, image_label):
            calls.append(("apply_colormap", image_label))

        def _apply_viewport(self, image_label):
            calls.append(("apply_viewport", image_label))

        def _draw_catalog(self, catalog_label):
            calls.append(("draw_catalog", catalog_label))

        def _remove_catalog_marks(self, catalog_label):
            calls.append(("remove_catalog_marks", catalog_label))

        @contextmanager
        def _batch_update(self):
            calls.append(("batch_enter", None))
            yield
            calls.append(("batch_exit", None))

    return RecordingViewer(), calls


def test_load_image_hook_sequence(data):
    # load_image must call the rendering hooks exactly once each, in a
    # fixed order, inside a single _batch_update block, with the
    # resolved label. The set_* calls that initialize the new image's
    # state must not fire any hooks along the way.
    viewer, calls = make_recording_viewer()
    viewer.load_image(data, image_label="test")

    assert calls == [
        ("batch_enter", None),
        ("render_image", "test"),
        ("apply_cuts", "test"),
        ("apply_stretch", "test"),
        ("apply_colormap", "test"),
        ("apply_viewport", "test"),
        ("batch_exit", None),
    ]


def test_load_image_hooks_get_default_label(data):
    # An unlabeled load must pass the resolved default label to the
    # hooks, never None.
    viewer, calls = make_recording_viewer()
    viewer.load_image(data)

    default_label = viewer.image_labels[0]
    hook_labels = {label for _, label in calls if label is not None}
    assert hook_labels == {default_label}
    assert ("render_image", default_label) in calls


def test_apply_hooks_gated_on_displayed_image(data):
    # The _apply_* hooks must fire only for the displayed image; for
    # any other image the settings are stored but no hook is called.
    viewer, calls = make_recording_viewer()
    viewer.load_image(data, image_label="first")
    viewer.load_image(data * 2, image_label="second")  # now displayed
    calls.clear()

    # Settings for the non-displayed image are stored but not applied.
    viewer.set_cuts((10, 100), image_label="first")
    viewer.set_stretch(LogStretch(), image_label="first")
    viewer.set_colormap("viridis", image_label="first")
    viewer.set_viewport(center=(10, 10), fov=50, image_label="first")
    assert calls == []
    # ...but the state was stored.
    assert viewer.get_cuts(image_label="first").get_limits(data) == (10, 100)
    assert isinstance(viewer.get_stretch(image_label="first"), LogStretch)
    assert viewer.get_colormap(image_label="first") == "viridis"

    # The same calls for the displayed image fire the hooks.
    viewer.set_cuts((10, 100), image_label="second")
    viewer.set_stretch(LogStretch(), image_label="second")
    viewer.set_colormap("viridis", image_label="second")
    viewer.set_viewport(center=(10, 10), fov=50, image_label="second")
    assert calls == [
        ("apply_cuts", "second"),
        ("apply_stretch", "second"),
        ("apply_colormap", "second"),
        ("apply_viewport", "second"),
    ]


def test_catalog_hooks_get_resolved_labels(catalog):
    # load_catalog and set_catalog_style must call _draw_catalog, and
    # remove_catalog must call _remove_catalog_marks, always with the
    # resolved catalog label.
    viewer, calls = make_recording_viewer()

    viewer.load_catalog(catalog, catalog_label="cat")
    assert ("draw_catalog", "cat") in calls

    calls.clear()
    viewer.set_catalog_style(catalog_label="cat", color="blue", shape="square", size=5)
    assert calls == [("draw_catalog", "cat")]

    calls.clear()
    viewer.remove_catalog(catalog_label="cat")
    assert calls == [("remove_catalog_marks", "cat")]

    # An unlabeled load must pass the resolved default label to the hook.
    calls.clear()
    viewer.load_catalog(catalog)
    default_label = viewer.catalog_labels[0]
    assert ("draw_catalog", default_label) in calls


def test_remove_catalog_star_expanded_before_hooks(catalog):
    # remove_catalog must expand "*" itself and call the
    # _remove_catalog_marks hook once per removed catalog; the hook
    # must never see the "*" itself.
    viewer, calls = make_recording_viewer()
    viewer.load_catalog(catalog, catalog_label="cat1")
    viewer.load_catalog(catalog, catalog_label="cat2")
    calls.clear()

    viewer.remove_catalog(catalog_label="*")

    removed = [label for name, label in calls if name == "remove_catalog_marks"]
    assert sorted(removed) == ["cat1", "cat2"]
    assert viewer.catalog_labels == ()


def test_load_image_carries_forward_display_settings(data):
    # Loading a new image replaces the displayed image and carries the
    # displayed image's cuts, stretch and colormap forward to the new
    # image instead of applying the defaults.
    viewer = ImageViewerLogic()
    viewer.load_image(data, image_label="first")
    viewer.set_cuts((10, 100), image_label="first")
    viewer.set_stretch(LogStretch(), image_label="first")
    viewer.set_colormap("viridis", image_label="first")

    viewer.load_image(data * 2, image_label="second")

    assert viewer.get_cuts(image_label="second").get_limits(data) == (10, 100)
    assert isinstance(viewer.get_stretch(image_label="second"), LogStretch)
    assert viewer.get_colormap(image_label="second") == "viridis"

    # The carried settings are per-image copies of the state: changing
    # the new image's settings must not touch the replaced image's.
    viewer.set_cuts((1, 2), image_label="second")
    assert viewer.get_cuts(image_label="first").get_limits(data) == (10, 100)


def test_load_image_carry_forward_uses_displayed_image(data):
    # The settings carried forward must come from the image being
    # displayed, not from some other loaded image.
    viewer = ImageViewerLogic()
    viewer.load_image(data, image_label="first")
    viewer.load_image(data, image_label="second")  # now displayed

    viewer.set_colormap("plasma", image_label="first")
    viewer.set_colormap("viridis", image_label="second")

    viewer.load_image(data, image_label="third")
    assert viewer.get_colormap(image_label="third") == "viridis"
