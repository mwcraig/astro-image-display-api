"""
A worked example of an `~astro_image_display_api.image_viewer_logic.ImageViewerLogic`
subclass, used in the documentation to show how a real viewer backend can plug into
the reference implementation.

Instead of drawing anything, :class:`RecordingViewer` simply records, in order, the
display operations that were requested of it. That makes it possible to write tests
(and documentation examples) that assert on *what* would have been drawn and in what
order, without needing an actual display backend.
"""

import numbers
import os
from pathlib import Path
from typing import Any

from astropy.coordinates import SkyCoord
from astropy.nddata import NDData
from astropy.table import Table
from astropy.units import Quantity
from astropy.visualization import BaseInterval, BaseStretch
from numpy.typing import ArrayLike

from astro_image_display_api.image_viewer_logic import ImageViewerLogic

__all__ = ["RecordingViewer"]


class RecordingViewer(ImageViewerLogic):
    """
    An `~astro_image_display_api.image_viewer_logic.ImageViewerLogic` that records
    display operations instead of drawing them.

    Every mutator method (the ones that would normally update a plot or widget)
    appends an entry to :attr:`display_calls` describing what was requested. This is
    a stand-in for a real viewer, which would instead update whatever GUI or plotting
    library it wraps.
    """

    def __post_init__(self):
        # Let the base class set up its internal ``_images``/``_catalogs``
        # dictionaries first, then start our own call log.
        super().__post_init__()
        self.display_calls = []

    def _record(self, operation: str, **details: Any) -> None:
        """Append one (operation, details) entry to the display call log."""
        self.display_calls.append((operation, details))

    # ------------------------------------------------------------------
    # Methods that modify the view
    # ------------------------------------------------------------------
    def set_viewport(
        self,
        center: SkyCoord | tuple[numbers.Real, numbers.Real] | None = None,
        fov: Quantity | numbers.Real | None = None,
        image_label: str | None = None,
        **kwargs,
    ) -> None:
        """Set the viewport, then record the request."""
        # NOTE: do not call get_viewport() here -- during load_image() the base
        # class has not yet set self._wcs, so an unqualified get_viewport() can
        # raise "WCS is not set". Record the arguments we were given instead.
        super().set_viewport(center=center, fov=fov, image_label=image_label, **kwargs)
        self._record("set_viewport", center=center, fov=fov, image_label=image_label)

    def set_cuts(
        self,
        value: tuple[numbers.Real, numbers.Real] | BaseInterval,
        image_label: str | None = None,
        **kwargs,
    ) -> None:
        """Set the cuts, then record the request."""
        super().set_cuts(value, image_label=image_label, **kwargs)
        self._record("set_cuts", value=value, image_label=image_label)

    def set_stretch(
        self,
        value: BaseStretch,
        image_label: str | None = None,
        **kwargs,
    ) -> None:
        """Set the stretch, then record the request."""
        super().set_stretch(value, image_label=image_label, **kwargs)
        self._record("set_stretch", value=value, image_label=image_label)

    def set_colormap(
        self,
        map_name: str,
        image_label: str | None = None,
        **kwargs,
    ) -> None:
        """Set the colormap, then record the request."""
        super().set_colormap(map_name, image_label=image_label, **kwargs)
        self._record("set_colormap", map_name=map_name, image_label=image_label)

    # ------------------------------------------------------------------
    # Loading images
    # ------------------------------------------------------------------
    def load_image(
        self,
        file: str | os.PathLike | ArrayLike | NDData,
        image_label: str | None = None,
        **kwargs,
    ) -> None:
        """Load the image, then record the state it ended up with in one entry."""
        # Loading fires set_viewport/set_cuts/set_stretch internally (via self.*,
        # so our overrides above record each one), but not set_colormap. Once
        # loading is done we read the *resolved* state back through the public
        # getters and push it as a single "load_image" entry, demonstrating the
        # "setters fire early, load pushes everything at the end" strategy.
        super().load_image(file, image_label=image_label, **kwargs)

        # get_viewport() resolves the image label for us (its returned dict has
        # the resolved "image_label"), so we can reuse that resolved label for
        # the remaining getters. Force sky_or_pixel="pixel" so this never raises
        # "WCS is not set" for an image that has no WCS.
        viewport = self.get_viewport(image_label=image_label, sky_or_pixel="pixel")
        resolved_label = viewport["image_label"]

        self._record(
            "load_image",
            image_label=resolved_label,
            viewport=viewport,
            cuts=self.get_cuts(image_label=resolved_label),
            stretch=self.get_stretch(image_label=resolved_label),
            colormap=self.get_colormap(image_label=resolved_label),
        )

    # ------------------------------------------------------------------
    # Catalogs
    # ------------------------------------------------------------------
    def load_catalog(
        self,
        table: Table,
        x_colname: str = "x",
        y_colname: str = "y",
        skycoord_colname: str = "coord",
        use_skycoord: bool = False,
        catalog_label: str | None = None,
        catalog_style: dict | None = None,
        **kwargs,
    ) -> None:
        """Load the catalog, then record the request."""
        super().load_catalog(
            table,
            x_colname=x_colname,
            y_colname=y_colname,
            skycoord_colname=skycoord_colname,
            use_skycoord=use_skycoord,
            catalog_label=catalog_label,
            catalog_style=catalog_style,
            **kwargs,
        )
        self._record(
            "load_catalog",
            catalog_label=catalog_label,
            use_skycoord=use_skycoord,
        )

    def set_catalog_style(
        self,
        catalog_label: str | None = None,
        shape: str = "circle",
        color: str = "red",
        size: float = 5,
        **kwargs,
    ) -> None:
        """Set the catalog style, then record the request."""
        super().set_catalog_style(
            catalog_label=catalog_label, shape=shape, color=color, size=size, **kwargs
        )
        self._record(
            "set_catalog_style",
            catalog_label=catalog_label,
            shape=shape,
            color=color,
            size=size,
        )

    def remove_catalog(
        self,
        catalog_label: str | None = None,
        **kwargs,
    ) -> None:
        """Remove the catalog (or, with ``'*'``, all catalogs), then record it."""
        super().remove_catalog(catalog_label=catalog_label, **kwargs)
        # No special-casing needed: this also records the "*" (remove all) case,
        # with the argument recorded exactly as given.
        self._record("remove_catalog", catalog_label=catalog_label)

    # ------------------------------------------------------------------
    # Saving
    # ------------------------------------------------------------------
    def save(
        self,
        filename: str | os.PathLike,
        overwrite: bool = False,
        **kwargs,  # noqa: ARG002
    ) -> None:
        """Write the recorded display calls to ``filename`` instead of drawing."""
        # Unlike the other overrides, this one does NOT call super() -- the base
        # implementation just writes a dummy placeholder, which is not useful
        # here. Instead, write out the log of everything that was "displayed".
        p = Path(filename)
        if p.exists() and not overwrite:
            raise FileExistsError(
                f"File {filename} already exists. Use overwrite=True to overwrite it."
            )

        p.write_text("\n".join(str(call) for call in self.display_calls))
