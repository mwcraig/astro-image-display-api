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

There is no longer a special ``None`` key. Instead, loading an image or
catalog without an explicit label stores it under a shared sentinel string
(the module-level ``DEFAULT_LABEL`` constant), so repeated unlabeled loads
replace the same "unlabeled" entry rather than accumulating new ones. Unlike
in earlier versions, that default label is **not** hidden from the public
:py:attr:`~astro_image_display_api.image_viewer_logic.ImageViewerLogic.image_labels`
and
:py:attr:`~astro_image_display_api.image_viewer_logic.ImageViewerLogic.catalog_labels`
properties -- once something has been loaded without a label, it shows up in
those tuples just like any other label. If you need to refer to it
explicitly (most callers do not; omitting ``image_label``/``catalog_label``
already resolves to it when nothing else is ambiguous), find it by set
difference against the labels you *did* choose yourself, e.g.
``(set(viewer.image_labels) - {"a", "b"}).pop()``, rather than depending on
the exact sentinel value, which is a private implementation detail.

Label resolution -- implemented by the private ``_resolve_label`` helper
(via ``_resolve_image_label``/``_resolve_catalog_label``) -- follows the
same rule everywhere an ``image_label`` or ``catalog_label`` argument is
accepted:

- If a label is given explicitly to ``load_image``/``load_catalog``, it is
  used as-is, and need not already exist -- loading under a brand-new label
  creates it.
- If no label is given to ``load_image``/``load_catalog``, the shared
  default label above is used.
- For every other method (the getters, ``set_viewport``, ``set_cuts``,
  ``set_stretch``, ``set_colormap``, ``set_catalog_style``,
  ``remove_catalog``), an explicit label must already correspond to loaded
  data, or a ``ValueError`` is raised.
- If no label is given to one of those other methods and nothing is loaded,
  a ``ValueError`` ("No image/catalog is loaded...") is raised.
- If no label is given to one of those other methods and exactly one label
  is loaded -- whether it is the shared default label or one the caller
  chose -- that label is used.
- If no label is given to one of those other methods and more than one
  label exists, a ``ValueError`` is raised asking the caller to
  disambiguate.

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
you three things for free: the validation and error messages described
below; compliance with ``test_all_methods_accept_additional_kwargs``, which
calls every method with extra, unrecognized keyword arguments to make sure
they are silently accepted; and compliance with
``test_parameter_names_match_interface``, which inspects each method's
signature (rather than calling it) to check that your parameter names match
the interface's, in order. That check exists because every method also
accepts ``**kwargs``, so a wrongly named parameter does not raise a
``TypeError`` when called by keyword -- it just silently falls into
``**kwargs`` and is never used. Mirroring the base method's signature
exactly, as recommended above, satisfies this automatically.

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
``super().load_image(data, image_label=...)`` does the following:

#. The image label is resolved (a load accepts a brand-new label, or falls
   back to the shared default label described in `The state model`_ above).
#. Any existing entry for that label is temporarily replaced with a fresh,
   empty one, and the label is temporarily marked as not displayed, so
   nothing reacts to the setter calls in the next step.
#. A format-specific loader (for FITS, arrays, or ``NDData``) stores the new
   data and WCS, then calls ``self.set_viewport(...)``, ``self.set_cuts(...)``,
   and ``self.set_stretch(...)`` to establish the default viewport, cuts, and
   stretch for the new image. Because these are called through ``self``,
   they run *your* overrides, not the base class's methods directly.
#. If the label already existed before this load, its previous cuts,
   stretch, and colormap are restored now, overriding the fresh defaults
   just established in the previous step -- reloading data under an
   existing label keeps that label's display settings; only its viewport
   and data come from the new image. A label that did not exist before
   keeps the defaults set in the previous step.
#. If loading raised an exception at any point above, the label's previous
   entry (or its absence, if the label was new) and the previously
   displayed-image tracking are put back before the exception propagates,
   so the viewer keeps showing whatever it showed before the failed load,
   and the steps below are skipped.
#. The label is marked as the (only) displayed image, and the base class
   calls its own internal, private rendering hooks (``_render_image``,
   ``_apply_cuts``, ``_apply_stretch``, ``_apply_colormap``,
   ``_apply_viewport``) directly, once each, with the resolved label. These
   are a separate, lower-level extension point -- they are not your
   ``set_*`` overrides, and calling them does not call your overrides. They
   are no-ops unless a subclass overrides them, so they are harmless (and
   invisible) to a subclass that only overrides the public mutators, as the
   worked example below does; see ``tests/test_image_viewer_logic_implementation.py``
   in the source tree if you want to use these hooks instead.
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
  outlives any individual image. Note that this alone will not repaint
  anything at the *end* of a load, since the final "apply" step above calls
  the private hooks, not your public setter overrides -- combine this
  strategy with an override of the relevant ``_apply_*``/``_render_image``
  hook if you need that.
- Push all of your display work in ``load_image`` to *after* the call to
  ``super().load_image(...)`` returns, and read the resolved state back
  through the public getters at that point rather than trying to capture it
  from the arguments you were passed. This sidesteps the ordering problem
  entirely, at the cost of one extra round trip through the getters, and
  does not depend on the private hooks at all.

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
- Apply
  :py:func:`~astro_image_display_api.image_viewer_logic.docs_from_image_viewer_logic_if_missing`
  to your own subclass. Unlike ``docs_from_interface``, which is an internal
  implementation detail, this helper *is* in
  ``astro_image_display_api.image_viewer_logic.__all__`` and is meant to be
  used this way: it fills in the docstring of any public method or property
  on your class that lacks its own, from the same-named attribute on
  ``ImageViewerLogic``.
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
       ``set_colormap``, ``get_image``).
   * - ``(?i)catalog label.*not found``
     - ``ValueError``
     - A ``catalog_label`` is given that does not correspond to a loaded
       catalog (``get_catalog``, ``get_catalog_style``,
       ``set_catalog_style``, ``remove_catalog``).
   * - ``[Nn]o image``
     - ``ValueError``
     - No image is loaded at all, so no ``image_label`` -- given or not --
       could possibly resolve (any accessor, or ``set_viewport``,
       ``set_cuts``, ``set_stretch``, ``set_colormap``).
   * - ``[Nn]o catalog``
     - ``ValueError``
     - ``remove_catalog`` is called with no ``catalog_label`` and no
       catalog is loaded at all.
   * - ``Multiple image labels defined``
     - ``ValueError``
     - No ``image_label`` is given and more than one image is loaded. Also
       raised by ``load_catalog`` when a pixel/sky conversion is required
       and several images are loaded with none of them the displayed one.
   * - ``Multiple catalog labels defined``
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
     - ``set_catalog_style`` is called when no catalog at all has been
       loaded yet.
   * - ``Cannot use pixel coordinates without pixel columns``
     - ``ValueError``
     - ``load_catalog`` is called with ``use_skycoord=False`` (the default)
       on a table with no x/y columns, and they cannot be computed either
       (no sky coordinate column, or no WCS to convert one with).
   * - ``Cannot use sky coordinates without``
     - ``ValueError``
     - ``load_catalog`` is called with ``use_skycoord=True`` but the table
       has no sky coordinate column and no WCS is loaded to compute one
       from the pixel columns.
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
   * - ``not a valid`` (colormap)
     - ``ValueError``
     - ``set_colormap`` is given a name that is not a valid Matplotlib
       colormap name (only checked when Matplotlib is installed).
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
