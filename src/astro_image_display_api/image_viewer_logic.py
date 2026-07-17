import numbers
import os
from copy import copy, deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from astropy import units as u
from astropy.coordinates import SkyCoord
from astropy.nddata import CCDData, NDData
from astropy.table import Table
from astropy.units import Quantity
from astropy.visualization import (
    AsymmetricPercentileInterval,
    BaseInterval,
    BaseStretch,
    LinearStretch,
    ManualInterval,
)
from astropy.wcs import WCS
from astropy.wcs.utils import proj_plane_pixel_scales
from numpy.typing import ArrayLike

from .interface_definition import ImageViewerInterface

__all__ = ["ImageViewerLogic"]


@dataclass
class CatalogInfo:
    """
    Class to hold information about a catalog.
    """

    style: dict[str, Any] = field(default_factory=dict)
    data: Table | None = None


@dataclass
class ViewportInfo:
    """
    Class to hold image and viewport information.
    """

    center: SkyCoord | tuple[numbers.Real, numbers.Real] | None = None
    fov: float | Quantity | None = None
    wcs: WCS | None = None
    largest_dimension: int | None = None
    stretch: BaseStretch | None = None
    cuts: BaseInterval | tuple[numbers.Real, numbers.Real] | None = None
    colormap: str | None = None
    data: ArrayLike | NDData | CCDData | None = None


def docs_from_interface(cls):
    """
    Decorator to copy the docstrings from the interface methods to the
    methods in the class.
    """
    for name, method in cls.__dict__.items():
        if not name.startswith("_"):
            interface_method = getattr(ImageViewerInterface, name, None)
            if interface_method:
                method.__doc__ = interface_method.__doc__
    return cls


@dataclass
@docs_from_interface
class ImageViewerLogic:
    """
    This viewer does not do anything except making changes to its internal
    state to simulate the behavior of a real viewer.
    """

    # some internal variable for keeping track of viewer state
    _wcs: WCS | None = None
    _center: tuple[numbers.Real, numbers.Real] = (0.0, 0.0)

    def __post_init__(self):
        self._set_up_catalog_image_dicts()

    def _set_up_catalog_image_dicts(self):
        # Keys are the user-visible labels of the loaded catalogs and images.
        # Entries are created only by the load_* methods, so reading state
        # can never create an entry.
        self._catalogs: dict[str, CatalogInfo] = {}
        self._images: dict[str, ViewportInfo] = {}

    @staticmethod
    def _generate_label(registry: dict, kind: str) -> str:
        """
        Generate a unique label for a new image or catalog.

        Parameters
        ----------
        registry : dict
            The dictionary of already-loaded images or catalogs.
        kind : str
            Either ``"image"`` or ``"catalog"``; used as the prefix of the
            generated label.

        Returns
        -------
        str
            A label of the form ``"<kind>-<number>"`` that is not already
            a key of ``registry``.
        """
        index = len(registry) + 1
        while (label := f"{kind}-{index}") in registry:
            index += 1
        return label

    def _resolve_label(
        self,
        label: str | None,
        kind: str,
        allow_new: bool = False,
    ) -> str:
        """
        Resolve a user-provided image or catalog label.

        This is needed so that the user gets what they expect in the simple
        case where there is only one image or catalog loaded. In that case
        the user may or may not have actually specified a label.

        Parameters
        ----------
        label : str or None
            The label the user provided, or None if they did not provide one.
        kind : str
            Either ``"image"`` or ``"catalog"``; selects which registry the
            label is resolved against and is used in error messages.
        allow_new : bool, optional
            If True the label is being resolved for a load operation, so an
            explicit label need not already exist and a missing label leads
            to a unique generated label instead of an error.

        Returns
        -------
        str
            The resolved label.

        Raises
        ------
        ValueError
            If an explicit label does not correspond to loaded data, or, when
            no label is given, if nothing is loaded or if several labels
            exist so the choice is ambiguous. Never raised when ``allow_new``
            is True.
        """
        registry, article = (
            (self._images, "an image")
            if kind == "image"
            else (self._catalogs, "a catalog")
        )

        if label is not None:
            if not allow_new and label not in registry:
                raise ValueError(
                    f"{kind.capitalize()} label '{label}' not found. "
                    f"Please load {article} first."
                )
            return label

        if allow_new:
            return self._generate_label(registry, kind)

        match len(registry):
            case 0:
                raise ValueError(f"No {kind} is loaded. Please load {article} first.")
            case 1:
                return next(iter(registry))
            case _:
                raise ValueError(
                    f"Multiple {kind} labels defined. Please specify a "
                    f"{kind}_label to select one."
                )

    def _resolve_catalog_label(
        self, catalog_label: str | None, allow_new: bool = False
    ) -> str:
        """
        Resolve a user-provided catalog label; see `_resolve_label`.
        """
        return self._resolve_label(catalog_label, "catalog", allow_new=allow_new)

    @property
    def _default_catalog_style(self) -> dict[str, Any]:
        """
        The default style for the catalog markers.
        """
        return {
            "shape": "circle",
            "color": "red",
            "size": 5,
        }

    def get_stretch(
        self,
        image_label: str | None = None,
        **kwargs,  # noqa: ARG002
    ) -> BaseStretch:
        image_label = self._resolve_image_label(image_label)
        return self._images[image_label].stretch

    def set_stretch(
        self,
        value: BaseStretch,
        image_label: str | None = None,
        **kwargs,  # noqa: ARG002
    ) -> None:
        if not isinstance(value, BaseStretch):
            raise TypeError(
                f"Stretch option {value} is not valid. Must be an "
                "`astropy.visualization` Stretch object."
            )
        image_label = self._resolve_image_label(image_label)
        self._images[image_label].stretch = value

    def get_cuts(
        self,
        image_label: str | None = None,
        **kwargs,  # noqa: ARG002
    ) -> tuple:
        image_label = self._resolve_image_label(image_label)
        return self._images[image_label].cuts

    def set_cuts(
        self,
        value: tuple[numbers.Real, numbers.Real] | BaseInterval,
        image_label: str | None = None,
        **kwargs,  # noqa: ARG002
    ) -> None:
        if isinstance(value, tuple) and len(value) == 2:
            cuts = ManualInterval(value[0], value[1])
        elif isinstance(value, BaseInterval):
            cuts = value
        else:
            raise TypeError(
                "Cuts must be an Astropy.visualization Interval object or a tuple "
                "of two values."
            )
        image_label = self._resolve_image_label(image_label)
        self._images[image_label].cuts = cuts

    def set_colormap(
        self,
        map_name: str,
        image_label: str | None = None,
        **kwargs,  # noqa: ARG002
    ) -> None:
        image_label = self._resolve_image_label(image_label)
        self._images[image_label].colormap = map_name

    def get_colormap(
        self,
        image_label: str | None = None,
        **kwargs,  # noqa: ARG002
    ) -> str:
        image_label = self._resolve_image_label(image_label)
        return self._images[image_label].colormap

    # The methods, grouped loosely by purpose

    def get_catalog_style(
        self,
        catalog_label=None,
        **kwargs,  # noqa: ARG002
    ) -> dict[str, Any]:
        if catalog_label is None and not self._catalogs:
            # Nothing is loaded, so report the default style that a new
            # catalog would get.
            style = self._default_catalog_style
            style["catalog_label"] = None
            return style

        catalog_label = self._resolve_catalog_label(catalog_label)

        style = self._catalogs[catalog_label].style.copy()
        style["catalog_label"] = catalog_label
        return style

    def set_catalog_style(
        self,
        catalog_label: str | None = None,
        shape: str = "circle",
        color: str = "red",
        size: float = 5,
        **kwargs,
    ) -> None:
        if not self._catalogs:
            raise ValueError("Must load a catalog before setting a catalog style.")

        catalog_label = self._resolve_catalog_label(catalog_label)

        self._catalogs[catalog_label].style = dict(
            shape=shape, color=color, size=size, **kwargs
        )

    # Methods for loading data
    def _resolve_image_label(
        self, image_label: str | None, allow_new: bool = False
    ) -> str:
        """
        Resolve a user-provided image label; see `_resolve_label`.
        """
        return self._resolve_label(image_label, "image", allow_new=allow_new)

    def load_image(
        self,
        file: str | os.PathLike | ArrayLike | NDData,
        image_label: str | None = None,
        **kwargs,  # noqa: ARG002
    ) -> None:
        image_label = self._resolve_image_label(image_label, allow_new=True)

        # Start from a fresh entry so that no state from a previous image
        # with this label carries over.
        self._images[image_label] = ViewportInfo()

        if isinstance(file, str | os.PathLike):
            if isinstance(file, str):
                is_asdf = file.endswith(".asdf")
            else:
                is_asdf = file.suffix == ".asdf"
            if is_asdf:
                self._load_asdf(file, image_label)
            else:
                self._load_fits(file, image_label)
        elif isinstance(file, NDData):
            self._load_nddata(file, image_label)
        else:
            # Assume it is a 2D array
            self._load_array(file, image_label)

        # This may eventually get pulled, but for now is needed to keep markers
        # working with the new image.
        self._wcs = self._images[image_label].wcs

    def get_image(
        self,
        image_label: str | None = None,
        **kwargs,  # noqa: ARG002
    ) -> ArrayLike | NDData | CCDData:
        image_label = self._resolve_image_label(image_label)
        return self._images[image_label].data

    @property
    def image_labels(self) -> tuple[str, ...]:
        return tuple(self._images)

    def _determine_largest_dimension(self, shape: tuple[int, int]) -> int:
        """
        Determine which index is the largest dimension.

        Parameters
        ----------
        shape : tuple of int
            The shape of the image.

        Returns
        -------
        int
            The index of the largest dimension of the image, or 0 if square.
        """
        return int(shape[1] > shape[0])

    def _initialize_image_viewport_stretch_cuts(
        self,
        image_data: ArrayLike | NDData | CCDData,
        image_label: str | None,
    ) -> None:
        """
        Initialize the viewport, stretch and cuts for an image.

        Parameters
        ----------
        image_data : ArrayLike
            The image data to initialize the viewport for.
        image_label : str or None
            The label for the image. If None, the default label will be used.

        Note
        ----
        This method is called internally to set up the initial viewport,
        stretch, and cuts for the image. It should be called AFTER setting
        the WCS.
        """

        # Deal with the viewport first
        height, width = image_data.shape
        # Center the image in the viewport and show the whole image.
        # With 0-indexed pixel-center coordinates the center of the
        # image is at ((width - 1) / 2, (height - 1) / 2).
        center = ((width - 1) / 2, (height - 1) / 2)
        fov = max(image_data.shape)
        self._images[image_label].largest_dimension = self._determine_largest_dimension(
            image_data.shape
        )

        wcs = self._images[image_label].wcs
        # Is there a WCS set? If yes, make center a SkyCoord and fov a Quantity,
        # otherwise leave them as pixels.
        if wcs is not None:
            center = wcs.pixel_to_world(center[0], center[1])
            # largest_dimension indexes the numpy shape tuple (0 = y, 1 = x),
            # but proj_plane_pixel_scales is ordered by WCS pixel axis
            # (0 = x, 1 = y), so flip the index.
            fov = (
                fov
                * u.degree
                * proj_plane_pixel_scales(wcs)[
                    1 - self._images[image_label].largest_dimension
                ]
            )

        self.set_viewport(center=center, fov=fov, image_label=image_label)

        # Now set the stretch and cuts
        self.set_cuts(AsymmetricPercentileInterval(1, 95), image_label=image_label)
        self.set_stretch(LinearStretch(), image_label=image_label)

    def _load_fits(self, file: str | os.PathLike, image_label: str | None) -> None:
        ccd = CCDData.read(file)
        self._images[image_label].wcs = ccd.wcs
        self._images[image_label].data = ccd
        self._initialize_image_viewport_stretch_cuts(ccd.data, image_label)

    def _load_array(self, array: ArrayLike, image_label: str | None) -> None:
        """
        Load a 2D array into the viewer.

        Parameters
        ----------
        array : array-like
            The array to load.
        """
        self._images[image_label].wcs = None  # No WCS for raw arrays
        self._images[image_label].largest_dimension = self._determine_largest_dimension(
            array.shape
        )
        self._images[image_label].data = array
        self._initialize_image_viewport_stretch_cuts(array, image_label)

    def _load_nddata(self, data: NDData, image_label: str | None) -> None:
        """
        Load an `astropy.nddata.NDData` object into the viewer.

        Parameters
        ----------
        data : `astropy.nddata.NDData`
            The NDData object to load.
        """
        self._images[image_label].wcs = data.wcs
        self._images[image_label].data = data
        self._images[image_label].largest_dimension = self._determine_largest_dimension(
            data.data.shape
        )
        # Not all NDDData objects have a shape, apparently
        self._initialize_image_viewport_stretch_cuts(data.data, image_label)

    def _load_asdf(self, asdf_file: str | os.PathLike, image_label: str | None) -> None:
        """
        Not implementing some load types is fine.
        """
        raise NotImplementedError(
            "ASDF loading is not implemented in this dummy viewer."
        )

    # Saving contents of the view and accessing the view
    def save(
        self,
        filename: str | os.PathLike,
        overwrite: bool = False,
        **kwargs,  # noqa: ARG002
    ) -> None:
        p = Path(filename)
        if p.exists() and not overwrite:
            raise FileExistsError(
                f"File {filename} already exists. Use overwrite=True to overwrite it."
            )

        p.write_text("This is a dummy file. The viewer does not save anything.")

    # Marker-related methods
    def load_catalog(
        self,
        table: Table,
        x_colname: str = "x",
        y_colname: str = "y",
        skycoord_colname: str = "coord",
        use_skycoord: bool = False,
        catalog_label: str | None = None,
        catalog_style: dict | None = None,
        **kwargs,  # noqa: ARG002
    ) -> None:
        try:
            coords = table[skycoord_colname]
        except KeyError:
            coords = None

        try:
            xy = (table[x_colname], table[y_colname])
        except KeyError:
            xy = None

        to_add = deepcopy(table)
        if xy is None:
            if self._wcs is not None and coords is not None:
                x, y = self._wcs.world_to_pixel(coords)
                to_add[x_colname] = x
                to_add[y_colname] = y
                xy = (x, y)
            else:
                to_add[x_colname] = to_add[y_colname] = None

        if not use_skycoord and xy is None:
            raise ValueError(
                "Cannot use pixel coordinates without pixel columns or both "
                "coordinates and a WCS."
            )

        if coords is None:
            if use_skycoord and self._wcs is None:
                raise ValueError(
                    "Cannot use sky coordinates without a SkyCoord column or WCS."
                )
            elif xy is not None and self._wcs is not None:
                # If we have xy coordinates, convert them to sky coordinates
                coords = self._wcs.pixel_to_world(xy[0], xy[1])
                to_add[skycoord_colname] = coords
            else:
                to_add[skycoord_colname] = None

        catalog_label = self._resolve_catalog_label(catalog_label, allow_new=True)

        if catalog_label not in self._catalogs:
            self._catalogs[catalog_label] = CatalogInfo()

        # Set the new data
        self._catalogs[catalog_label].data = to_add

        # Ensure a catalog always has a style
        if catalog_style is None:
            if not self._catalogs[catalog_label].style:
                # No style has been set, so use the default style
                catalog_style = self._default_catalog_style.copy()
            else:
                # Use the existing style
                catalog_style = self._catalogs[catalog_label].style.copy()

        self._catalogs[catalog_label].style = catalog_style

    def remove_catalog(
        self,
        catalog_label: str | None = None,
        **kwargs,  # noqa: ARG002
    ) -> None:
        """
        Remove markers from the image.

        Parameters
        ----------
        marker_name : str, optional
            The name of the marker set to remove. If the value is ``"*"``,
            then all markers will be removed.
        """
        if isinstance(catalog_label, list):
            raise TypeError(
                "Cannot remove multiple catalogs from a list. Please specify "
                "a single catalog label or use '*' to remove all catalogs."
            )
        elif catalog_label == "*":
            # If the user wants to remove all catalogs, we reset the
            # catalogs dictionary to an empty one, which is exactly the
            # state a fresh viewer starts in.
            self._catalogs = {}
            return

        # Special cases are done, so we can resolve the catalog label.
        # Resolution raises a ValueError if the label is not found.
        catalog_label = self._resolve_catalog_label(catalog_label)

        del self._catalogs[catalog_label]

    def get_catalog(
        self,
        x_colname: str = "x",
        y_colname: str = "y",
        skycoord_colname: str = "coord",
        catalog_label: str | None = None,
        **kwargs,  # noqa: ARG002
    ) -> Table:
        # Docstring is copied from the interface definition, so it is not
        # duplicated here.
        if catalog_label is None and not self._catalogs:
            # Nothing is loaded; return an empty table with the expected
            # columns rather than raising, so that "is there anything
            # here?" queries are easy to write.
            result = Table(names=["x", "y", "coord"])
        else:
            catalog_label = self._resolve_catalog_label(catalog_label)
            result = self._catalogs[catalog_label].data

        result.rename_columns(
            ["x", "y", "coord"], [x_colname, y_colname, skycoord_colname]
        )

        return result

    @property
    def catalog_labels(self) -> tuple[str, ...]:
        return tuple(self._catalogs)

    # Methods that modify the view
    def set_viewport(
        self,
        center: SkyCoord | tuple[numbers.Real, numbers.Real] | None = None,
        fov: Quantity | numbers.Real | None = None,
        image_label: str | None = None,
        **kwargs,  # noqa: ARG002
    ) -> None:
        image_label = self._resolve_image_label(image_label)

        # Get current center/fov, if any, so that the user may input only one of them
        # after the initial setup if they wish.
        current_viewport = copy(self._images[image_label])
        if center is None:
            center = current_viewport.center
        if fov is None:
            fov = current_viewport.fov

        # If either center or fov is None these checks will raise an appropriate error
        if not isinstance(center, SkyCoord | tuple):
            raise TypeError(
                "Invalid value for center. Center must be a SkyCoord or tuple "
                "of (X, Y)."
            )
        if not isinstance(fov, Quantity | numbers.Real):
            raise TypeError(
                "Invalid value for fov. fov must be an angular Quantity or float."
            )

        if isinstance(fov, Quantity) and not fov.unit.is_equivalent(u.deg):
            raise u.UnitTypeError(
                "Incorrect unit for fov. fov must be an angular Quantity or float."
            )

        # Check that the center and fov are compatible with the current image
        if self._images[image_label].wcs is None:
            if current_viewport.center is not None:
                # If there is a WCS either input is fine. If there is no WCS then we
                # only check wther the new center is the same type as the
                # current center.
                if isinstance(center, SkyCoord) and not isinstance(
                    current_viewport.center, SkyCoord
                ):
                    raise TypeError(
                        "Center must be a tuple for this image when WCS is not set."
                    )
                elif isinstance(center, tuple) and not isinstance(
                    current_viewport.center, tuple
                ):
                    raise TypeError(
                        "Center must be a SkyCoord for this image when WCS is not set."
                    )
            if current_viewport.fov is not None:
                if isinstance(fov, Quantity) and not isinstance(
                    current_viewport.fov, Quantity
                ):
                    raise TypeError(
                        "FOV must be a float for this image when WCS is not set."
                    )
                elif isinstance(fov, numbers.Real) and not isinstance(
                    current_viewport.fov, numbers.Real
                ):
                    raise TypeError(
                        "FOV must be a float for this image when WCS is not set."
                    )

        # 😅 if we made it this far we should be able to handle the actual setting
        self._images[image_label].center = center
        self._images[image_label].fov = fov

    def get_viewport(
        self,
        sky_or_pixel: str | None = None,
        image_label: str | None = None,
        **kwargs,  # noqa: ARG002
    ) -> dict[str, Any]:
        if sky_or_pixel not in (None, "sky", "pixel"):
            raise ValueError("sky_or_pixel must be 'sky', 'pixel', or None.")
        image_label = self._resolve_image_label(image_label)

        viewport = self._images[image_label]

        # Figure out what to return if the user did not specify sky_or_pixel.
        # The interface definition for get_viewport says that if the image has a WCS,
        # then the return should be in world coordinates, otherwise it should
        # be in pixel coordinates.
        if sky_or_pixel is None:
            if self._wcs is not None:
                # Somebody set this to sky coordinates, so return sky coordinates
                sky_or_pixel = "sky"
            else:
                # Somebody set this to pixel coordinates, so return pixel coordinates
                sky_or_pixel = "pixel"

        center = None
        fov = None
        if sky_or_pixel == "sky":
            if isinstance(viewport.center, SkyCoord):
                center = viewport.center

            if isinstance(viewport.fov, Quantity):
                fov = viewport.fov

            if center is None or fov is None:
                # At least one of center or fov is not set, which means at least one
                # was not already sky, so we need to convert them or fail
                if viewport.wcs is None:
                    raise ValueError(
                        "WCS is not set. Cannot convert pixel coordinates to "
                        "sky coordinates."
                    )
                else:
                    if center is None:
                        center = viewport.wcs.pixel_to_world(
                            viewport.center[0], viewport.center[1]
                        )
                    if fov is None:
                        # largest_dimension indexes the numpy shape tuple
                        # (0 = y, 1 = x), but proj_plane_pixel_scales is
                        # ordered by WCS pixel axis (0 = x, 1 = y), so flip
                        # the index.
                        pixel_scale = proj_plane_pixel_scales(viewport.wcs)[
                            1 - viewport.largest_dimension
                        ]
                        fov = pixel_scale * viewport.fov * u.degree
        else:
            # Pixel coordinates
            if isinstance(viewport.center, SkyCoord):
                if viewport.wcs is None:
                    raise ValueError(
                        "WCS is not set. Cannot convert sky coordinates to "
                        "pixel coordinates."
                    )
                center = viewport.wcs.world_to_pixel(viewport.center)
            else:
                center = viewport.center
            if isinstance(viewport.fov, Quantity):
                if viewport.wcs is None:
                    raise ValueError(
                        "WCS is not set. Cannot convert FOV to pixel coordinates."
                    )
                # See comment above about flipping the index into
                # proj_plane_pixel_scales.
                pixel_scale = proj_plane_pixel_scales(viewport.wcs)[
                    1 - viewport.largest_dimension
                ]
                # proj_plane_pixel_scales returns degrees for a celestial WCS
                # (wcslib normalizes CUNIT to degrees), so convert the fov to
                # degrees rather than assuming it already is in degrees.
                fov = viewport.fov.to_value(u.degree) / pixel_scale
            else:
                fov = viewport.fov

        return dict(center=center, fov=fov, image_label=image_label)
