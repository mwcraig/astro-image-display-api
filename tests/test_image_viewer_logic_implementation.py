# Tests of ImageViewerLogic implementation behavior that is not part of
# the API contract, so it lives here rather than in the ImageAPITest
# compliance suite:
#
# - The template-method rendering hooks: the public API methods own all
#   state handling and label resolution, then call private no-op hooks
#   (with already-resolved labels) that display backends override to
#   update their display. Implementations of the API do not have to
#   adopt this mechanism.
# - The per-label retention of display settings: reloading data under an
#   existing label keeps that label's cuts/stretch/colormap, a new label
#   starts from the defaults.
# - The restoration of the display tracking state when a load fails.

from contextlib import contextmanager

import numpy as np
import pytest
from astropy.table import Table
from astropy.visualization import (
    AsymmetricPercentileInterval,
    LinearStretch,
    LogStretch,
)

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
            x=rng.uniform(0, IMAGE_SHAPE[1], size=10),
            y=rng.uniform(0, IMAGE_SHAPE[0], size=10),
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
    # _remove_catalog_marks hook once per removed catalog, inside a
    # single _batch_update block; the hook must never see the "*"
    # itself.
    viewer, calls = make_recording_viewer()
    viewer.load_catalog(catalog, catalog_label="cat1")
    viewer.load_catalog(catalog, catalog_label="cat2")
    calls.clear()

    viewer.remove_catalog(catalog_label="*")

    assert calls[0] == ("batch_enter", None)
    assert calls[-1] == ("batch_exit", None)
    removed = [label for name, label in calls if name == "remove_catalog_marks"]
    assert sorted(removed) == ["cat1", "cat2"]
    assert viewer.catalog_labels == ()


def test_load_image_new_label_gets_default_settings(data):
    # An image loaded under a new label must start from the default
    # cuts/stretch/colormap, not inherit the displayed image's settings.
    viewer = ImageViewerLogic()
    viewer.load_image(data, image_label="first")
    viewer.set_cuts((10, 100), image_label="first")
    viewer.set_stretch(LogStretch(), image_label="first")
    viewer.set_colormap("viridis", image_label="first")

    viewer.load_image(data * 2, image_label="second")

    assert isinstance(
        viewer.get_cuts(image_label="second"), AsymmetricPercentileInterval
    )
    assert isinstance(viewer.get_stretch(image_label="second"), LinearStretch)
    assert viewer.get_colormap(image_label="second") is None


def test_load_image_existing_label_keeps_its_settings(data):
    # Loading new data under an existing label must keep the settings
    # the user attached to that label, even when a different image with
    # different settings is currently displayed. The viewport is reset
    # to fit the new data.
    viewer = ImageViewerLogic()
    viewer.load_image(data, image_label="first")
    viewer.set_cuts((10, 100), image_label="first")
    viewer.set_stretch(LogStretch(), image_label="first")
    viewer.set_colormap("viridis", image_label="first")
    viewer.load_image(data, image_label="second")
    viewer.set_colormap("plasma", image_label="second")

    viewer.load_image(data * 2, image_label="first")

    assert viewer.get_cuts(image_label="first").get_limits(data) == (10, 100)
    assert isinstance(viewer.get_stretch(image_label="first"), LogStretch)
    assert viewer.get_colormap(image_label="first") == "viridis"
    assert np.array_equal(viewer.get_image(image_label="first"), data * 2)


def test_failed_load_image_restores_display_tracking(data):
    # A load_image that raises must leave the viewer tracking the image
    # it is still displaying, so the _apply_* hooks keep firing for it,
    # and must not leave a half-created entry under the new label.
    viewer, calls = make_recording_viewer()
    viewer.load_image(data, image_label="first")
    calls.clear()

    with pytest.raises(NotImplementedError):
        viewer.load_image("nope.asdf", image_label="second")

    assert viewer.image_labels == ("first",)
    viewer.set_cuts((10, 100), image_label="first")
    assert ("apply_cuts", "first") in calls


def test_failed_load_image_keeps_existing_entry(data):
    # A failed reload of an existing label must leave that label's data
    # and settings untouched.
    viewer = ImageViewerLogic()
    viewer.load_image(data, image_label="first")
    viewer.set_colormap("viridis", image_label="first")

    with pytest.raises(NotImplementedError):
        viewer.load_image("nope.asdf", image_label="first")

    assert np.array_equal(viewer.get_image(image_label="first"), data)
    assert viewer.get_colormap(image_label="first") == "viridis"
