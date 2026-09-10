.. _reference_implementation:

Building on the reference implementation
=========================================

The class :py:class:`~astro_image_display_api.image_viewer_logic.ImageViewerLogic`
is provided as an *example* of how to implement the non-display logic of the
Astronomical Image Display API (AIDA). You do not need to use this class, but
it is provided as a convenience to help you get started with your own
implementation: subclass it, override the methods that need to touch an
actual display, and let the base class handle validation, label bookkeeping,
and state storage for you.

This page walks through that override pattern in detail: what the base class
does and does not do, how it stores state, the order in which its methods are
called while an image is loading, and the couple of gotchas that trip people
up (constructing a dataclass subclass, and docstrings on overridden methods).
It ends with a small, fully tested worked example.

What ``ImageViewerLogic`` does -- and does not do
--------------------------------------------------

``ImageViewerLogic`` implements everything in
:py:class:`~astro_image_display_api.interface_definition.ImageViewerInterface`
*except* actually drawing anything. Concretely, it does:

- Validate its arguments and raise the exact exceptions and messages that
  :py:class:`~astro_image_display_api.api_test.ImageAPITest` checks for (see
  `Error messages are part of the contract`_ below).
- Keep track of per-image and per-catalog state (viewport, cuts, stretch,
  colormap, catalog style and data), keyed by label.
- Resolve labels for you when a method is called without one, including
  raising an error when the label is ambiguous.
- Set sensible default cuts (``AsymmetricPercentileInterval(1, 95)``) and
  stretch (``LinearStretch``) whenever an image is loaded.
- Load FITS files, 2D arrays, and ``astropy.nddata.NDData`` objects.

It does **not**:

- Draw or render anything. There is no plotting library, canvas, or widget
  anywhere in this class.
- Actually save an image. Its
  :py:meth:`~astro_image_display_api.image_viewer_logic.ImageViewerLogic.save`
  method just writes a placeholder text file; see `Saving the view`_.
- Support ``.asdf`` files -- loading one raises ``NotImplementedError``.
- Validate colormap names. ``set_colormap`` stores whatever string it is
  given.

The state model
----------------

Two private dictionaries hold all of the state:

- ``self._images`` maps an image label to a ``ViewportInfo`` object, which
  holds ``center``, ``fov``, ``wcs``, ``largest_dimension``, ``stretch``,
  ``cuts``, ``colormap``, and ``data``.
- ``self._catalogs`` maps a catalog label to a ``CatalogInfo`` object, which
  holds ``style`` and ``data``.

Both dictionaries always have a ``None`` key. That is the "unlabeled" slot
used when a caller loads an image or catalog without giving it a label, and
it is deliberately excluded from the public
:py:attr:`~astro_image_display_api.image_viewer_logic.ImageViewerLogic.image_labels`
and
:py:attr:`~astro_image_display_api.image_viewer_logic.ImageViewerLogic.catalog_labels`
properties, which only list labels the caller chose explicitly.

Label resolution follows the same rule everywhere an ``image_label`` or
``catalog_label`` argument is accepted:

- If a label is given explicitly, it is used as-is.
- If no label is given and exactly one user-defined label has been loaded,
  that label is used.
- If no label is given and more than one user-defined label exists, a
  ``ValueError`` is raised asking the caller to disambiguate.

Treat ``_images`` and ``_catalogs`` as private. Read state back through the
public getters (``get_viewport``, ``get_cuts``, ``get_stretch``,
``get_colormap``, ``get_catalog``, ``get_catalog_style``, ``get_image``)
rather than reaching into these dictionaries directly -- the getters apply
the same label resolution and error handling that the rest of the API relies
on.

Override the mutators, and call ``super()`` first
----------------------------------------------------

All of the argument validation lives in ``ImageViewerLogic``, and it runs
*before* anything else happens. When you override a method, call
``super().<method>(...)`` first, using the same signature and keyword names
as the base method, and forward any ``**kwargs`` you receive. Doing so gets
you two things for free: the validation and error messages described below,
and compliance with
``test_all_methods_accept_additional_kwargs``, which calls every method with
extra, unrecognized keyword arguments to make sure they are silently
accepted.

The docstrings in
:py:class:`~astro_image_display_api.interface_definition.ImageViewerInterface`
tell you which methods you are expected to override. Accessors say, in their
*Notes* section, "This has no effect on the displayed image" -- inherit
those unchanged. Mutators say something like "Setting the viewport should
update the display of the image to reflect the new viewport." -- those are
the ones to override.

.. list-table:: Which mutators need a display-specific override
   :header-rows: 1
   :widths: 25 75

   * - Method
     - What a subclass override typically adds
   * - :py:meth:`~astro_image_display_api.image_viewer_logic.ImageViewerLogic.load_image`
     - Draw the newly loaded array/FITS data in the display.
   * - :py:meth:`~astro_image_display_api.image_viewer_logic.ImageViewerLogic.set_viewport`
     - Pan/zoom the display to the new center and field of view.
   * - :py:meth:`~astro_image_display_api.image_viewer_logic.ImageViewerLogic.set_cuts`
     - Redraw the image using the new pixel value cut levels.
   * - :py:meth:`~astro_image_display_api.image_viewer_logic.ImageViewerLogic.set_stretch`
     - Redraw the image using the new stretch function.
   * - :py:meth:`~astro_image_display_api.image_viewer_logic.ImageViewerLogic.set_colormap`
     - Apply the new colormap to the rendered image.
   * - :py:meth:`~astro_image_display_api.image_viewer_logic.ImageViewerLogic.load_catalog`
     - Draw markers at the catalog positions.
   * - :py:meth:`~astro_image_display_api.image_viewer_logic.ImageViewerLogic.set_catalog_style`
     - Redraw the markers with the new shape/color/size.
   * - :py:meth:`~astro_image_display_api.image_viewer_logic.ImageViewerLogic.remove_catalog`
     - Remove markers from the display. (The interface docstring for this
       method does not spell this out explicitly, but removing a catalog's
       data without removing its markers would leave the display
       inconsistent with ``get_catalog``.)
   * - :py:meth:`~astro_image_display_api.image_viewer_logic.ImageViewerLogic.save`
     - See `Saving the view`_ -- this one is the exception to "call
       ``super()`` first".

Every accessor -- ``get_image``, ``get_viewport``, ``get_cuts``,
``get_stretch``, ``get_colormap``, ``get_catalog``, ``get_catalog_style``,
and the ``image_labels``/``catalog_labels`` properties -- is inherited
unchanged. Override one only if you need to change what state it returns,
never in order to draw something.

What happens during ``load_image``
------------------------------------

It is easy to assume that a subclass's own
:py:meth:`~astro_image_display_api.image_viewer_logic.ImageViewerLogic.load_image`
override is where all of the image-specific display setup happens, and that
it happens in one uninterrupted block. It is not quite that simple, because
the base implementation calls back into *your* overrides of
``set_viewport``, ``set_cuts``, and ``set_stretch`` while it is still running
its own body. In order, calling
``super().load_image(file, image_label=...)`` does the following:

#. The image label is resolved, and any existing state for that label is
   deleted (so reloading a label discards the old viewport, cuts, stretch,
   colormap, and data for it).
#. A format-specific loader (for FITS, arrays, or ``NDData``) stores the new
   data and WCS.
#. That loader calls ``self.set_viewport(...)``, ``self.set_cuts(...)``, and
   ``self.set_stretch(...)`` to establish the default viewport, cuts, and
   stretch for the new image. Because these are called through ``self``,
   they run *your* overrides, not the base class's methods directly.
#. ``super().load_image(...)`` returns.
#. Only then does the rest of your ``load_image`` override run.

The consequence is that your ``set_viewport``, ``set_cuts``, and
``set_stretch`` overrides can be invoked in the middle of loading a new
image, before the rest of your own ``load_image`` override has had a chance
to do its image-specific setup (for example, creating a canvas or plot
artist for the new image). Two strategies handle this:

- Write each setter override so that it only touches the display if the
  display object it needs already exists, and returns quietly otherwise.
  This works well when your viewer owns a persistent widget or canvas that
  outlives any individual image.
- Push all of your display work in ``load_image`` to *after* the call to
  ``super().load_image(...)`` returns, and read the resolved state back
  through the public getters at that point rather than trying to capture it
  from the arguments you were passed. This sidesteps the ordering problem
  entirely, at the cost of one extra round trip through the getters.

The worked example below uses the second strategy: its ``set_viewport``,
``set_cuts``, and ``set_stretch`` overrides simply record whatever they are
called with (since there is no real display object to guard), and its
``load_image`` override waits until after ``super().load_image(...)``
returns before reading back the final state and recording it.

.. literalinclude:: ../tests/example_viewer.py
  :language: python
  :pyobject: RecordingViewer.load_image

.. literalinclude:: ../tests/example_viewer.py
  :language: python
  :pyobject: RecordingViewer.set_viewport

Constructing your subclass
-----------------------------

``ImageViewerLogic`` is a ``dataclass``. Its generated ``__init__`` calls
``__post_init__``, which is where the ``_images`` and ``_catalogs``
dictionaries described above get created. Your subclass's constructor needs
to run that setup too, and it must work with **no arguments**, because
``ImageAPITest`` instantiates your class with ``image_widget_class()``. You
have a few options:

- Override ``__post_init__``, call ``super().__post_init__()`` first, and do
  your own setup (such as creating an empty call log or widget) afterward.
  This is the recommended approach, since it keeps the generated
  dataclass ``__init__`` and does not require you to repeat any of its
  argument handling.

  .. literalinclude:: ../tests/example_viewer.py
    :language: python
    :pyobject: RecordingViewer.__post_init__

- Write an explicit ``__init__`` that calls ``super().__init__()`` first,
  then does your own setup. You would only need this if you want
  constructor arguments beyond what the dataclass fields provide.
- If your viewer also needs to inherit from a widget base class (for
  example a Qt or Jupyter widget class), mixing that base class's ``__init__``
  with a dataclass-generated one usually does not work cleanly. In that case
  write an explicit ``__init__`` that calls both base class constructors
  yourself, rather than relying on ``super()`` chaining.

Docstrings on overridden methods
------------------------------------

``ImageViewerLogic``'s methods get their docstrings copied over from
``ImageViewerInterface`` by an internal ``docs_from_interface`` decorator.
That decorator only rewrites the docstrings of names that are already
present in ``ImageViewerLogic.__dict__`` at class-definition time -- it does
not run again for subclasses. If you override a method and do not give it
its own docstring, the override ends up with no docstring at all, which
makes ``test_every_method_attribute_has_docstring`` fail.

Three ways to fix this:

- Write a docstring on the override directly. This is the simplest option,
  and it is what the worked example below does.
- Apply ``docs_from_interface`` to your own subclass. It is importable from
  ``astro_image_display_api.image_viewer_logic``, but it is not in that
  module's ``__all__`` and carries no API stability promise, so treat it as
  an implementation detail you are borrowing rather than a supported public
  helper.
- Assign ``__doc__`` on your override explicitly from the base method, e.g.
  ``MyViewer.load_image.__doc__ = ImageViewerLogic.load_image.__doc__``.

Saving the view
-------------------

Unlike the other mutators, an override of
:py:meth:`~astro_image_display_api.image_viewer_logic.ImageViewerLogic.save`
should generally **not** call ``super().save(...)``. The base
implementation just writes a placeholder text file -- it has nothing useful
for a real viewer to reuse. Instead, your override should do the whole job
itself: render the current view to ``filename`` (with the output format
determined by the file's suffix), and raise ``FileExistsError`` unless
``overwrite=True`` is given.

The test suite only checks that a file appears after
:py:meth:`~astro_image_display_api.image_viewer_logic.ImageViewerLogic.save`
is called, and that the overwrite behavior above holds; it does not inspect
the file's contents or format.

.. literalinclude:: ../tests/example_viewer.py
  :language: python
  :pyobject: RecordingViewer.save

Error messages are part of the contract
-------------------------------------------

:py:class:`~astro_image_display_api.api_test.ImageAPITest` checks not just
that the right *type* of exception is raised, but that its message matches a
specific pattern, using ``pytest.raises(..., match=...)``. If you call
``super().<method>(...)`` first, as recommended above, you get all of these
for free. If you replace the base class's validation entirely, your errors
need to match the same patterns.

.. list-table:: Errors ``ImageAPITest`` checks for
   :header-rows: 1
   :widths: 35 15 50

   * - Message pattern (regex)
     - Exception
     - Raised when
   * - ``[Ii]mage label.*not found``
     - ``ValueError``
     - An ``image_label`` is given that does not correspond to a loaded
       image (accessors, ``set_viewport``, ``set_cuts``, ``set_stretch``,
       ``set_colormap``).
   * - ``Multiple image labels defined``
     - ``ValueError``
     - No ``image_label`` is given and more than one image is loaded.
   * - ``Multiple catalog styles``
     - ``ValueError``
     - No ``catalog_label`` is given and more than one catalog is loaded.
   * - ``[Ii]nvalid value for fov``
     - ``TypeError``
     - ``fov`` is not a float or an angular ``Quantity``.
   * - ``[Ii]ncorrect unit for fov``
     - ``astropy.units.UnitTypeError``
     - ``fov`` is a ``Quantity`` without an angular unit.
   * - ``[Ii]nvalid value for center``
     - ``TypeError``
     - ``center`` is not a ``SkyCoord`` or a tuple.
   * - ``Center must be a tuple``
     - ``TypeError``
     - A ``SkyCoord`` center is given for an image that has no WCS and
       whose current center is a tuple.
   * - ``FOV must be a float``
     - ``TypeError``
     - A ``Quantity`` fov is given for an image that has no WCS and whose
       current fov is a plain number.
   * - ``WCS is not set``
     - ``ValueError``
     - ``get_viewport`` is asked to convert between sky and pixel
       coordinates for an image with no WCS.
   * - ``[Ss]ky_or_pixel must be``
     - ``ValueError``
     - ``get_viewport``'s ``sky_or_pixel`` argument is not ``'sky'``,
       ``'pixel'``, or ``None``.
   * - ``Must load a catalog before setting a catalog style``
     - ``ValueError``
     - ``set_catalog_style`` is called for a label with no catalog data.
   * - ``Cannot use pixel coordinates without pixel columns``
     - ``ValueError``
     - ``load_catalog`` is given a table with no x/y columns, no sky
       coordinate column, and ``use_skycoord=False``.
   * - ``Cannot use sky coordinates without``
     - ``ValueError``
     - ``load_catalog`` is called with ``use_skycoord=True`` but the table
       has no sky coordinate column and no WCS is loaded.
   * - ``Cannot remove multiple catalogs from a list``
     - ``TypeError``
     - ``remove_catalog`` is given a list instead of a single label or
       ``'*'``.
   * - ``Stretch.*not valid.*``
     - ``TypeError``
     - ``set_stretch`` is given something that is not a
       ``BaseStretch``.
   * - ``[mM]ust be`` (cuts)
     - ``TypeError``
     - ``set_cuts`` is given something that is not a 2-tuple or a
       ``BaseInterval``.
   * - N/A (checked via file existence, not a message)
     - ``FileExistsError``
     - ``save`` is called for a file that already exists and
       ``overwrite=False``.

Worked example
------------------

The full example used throughout this page is reproduced below. It
subclasses ``ImageViewerLogic`` and, instead of drawing anything, records
each display operation it is asked to perform -- which is enough to write
tests and documentation examples that assert on *what* would have been
drawn and in what order, without an actual display backend.

.. dropdown:: tests/example_viewer.py

  .. literalinclude:: ../tests/example_viewer.py
    :language: python

Wiring up the tests
-----------------------

Testing a subclass of ``ImageViewerLogic`` works exactly the same way as
testing any other implementation of
:py:class:`~astro_image_display_api.interface_definition.ImageViewerInterface`;
see :ref:`testing_AIDA_implementation` for the general pattern of
subclassing :py:class:`~astro_image_display_api.api_test.ImageAPITest` and
setting ``image_widget_class``. Below is that pattern applied to the worked
example above, plus one extra test that pins down the call order described
in `What happens during load_image`_.

.. literalinclude:: ../tests/test_example_viewer.py
  :language: python

When not to use ``ImageViewerLogic``
----------------------------------------

Subclassing ``ImageViewerLogic`` is a convenience, not a requirement, and it
is not always the right fit:

- If your viewer already keeps track of per-image or per-catalog state
  itself (for example, because it wraps a plotting library that has its own
  notion of loaded images and layers), subclassing ``ImageViewerLogic`` on
  top of that gives you two, potentially inconsistent, copies of the same
  bookkeeping.
- If your viewer needs to subclass a widget framework's base class, that
  base class's metaclass or constructor requirements may conflict with
  ``ImageViewerLogic`` being a ``dataclass``; see `Constructing your subclass`_
  above.

In either case, two alternatives are available:

- Implement :py:class:`~astro_image_display_api.interface_definition.ImageViewerInterface`
  directly, without subclassing ``ImageViewerLogic`` at all. Because the
  interface is a ``typing.Protocol`` decorated with ``runtime_checkable``,
  ``isinstance(your_instance, ImageViewerInterface)`` still works as long as
  your class defines the required methods and attributes -- there is no
  need to inherit from anything for that check to pass.
- Use composition instead of inheritance: hold an
  ``ImageViewerLogic`` instance as, e.g., ``self._state``, and delegate to it
  for argument validation and state bookkeeping, while your own class
  handles the actual display and whatever state it needs for that.
