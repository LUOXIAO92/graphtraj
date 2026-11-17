# Graftling

Independent native Agent control and optional native Session archives.

The package, its README, public interface, changelog and per-host install guides are in
[`src/graftling`](src/graftling/README.md):

- [README](src/graftling/README.md)
- [Public interface and version rules](src/graftling/PUBLIC_API.md)
- [Changelog](src/graftling/CHANGELOG.md)
- Install guides: [`src/graftling/install`](src/graftling/install)

Build a wheel from a checkout with `python -m pip wheel --no-deps -w dist ./src/graftling`.
Run the tests with an editable install: `python -m pip install -e ./src/graftling pytest`, then `python -m pytest`.

Licensed under the [Apache License, Version 2.0](LICENSE).
