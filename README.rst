django-changerequest
====================

django-changerequest is yet another model auditing/versioning package. As usual in cases like
these, it was created because I wasn't *quite* happy with any of the
`existing solutions <https://djangopackages.org/grids/g/versioning/>`_
(that are still being actively maintained).

This django package started as an app inside one of my projects. When I wanted to use it in
another project I put it into its own repository, but it still contained too many references
to the original project. This repository starts fresh and attempts to (re)write the code to
be now properly reusable, to the point where it is ready to put on PyPI
(which it isn't yet at the moment).

Purpose
-------

The purpose of django-changerequest is to record all user editing activity on the affected
models, but also allow staged edits (where changes first have to be approved by a moderator
before they're committed to the actual database).

