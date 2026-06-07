# Third-Party Notices

This repository depends on third-party software and includes some materials with
their own license markers. Those materials remain under their own licenses. The
top-level [LICENSE.md](./LICENSE.md) applies only to repository content owned by
Rasmus Thornberg.

## Dependency Declarations

Dependency sources currently include:

- [pyproject.toml](./pyproject.toml)
- [requirements.txt](./requirements.txt)
- [app/requirements.txt](./app/requirements.txt)
- [requirements-smoke.txt](./requirements-smoke.txt)

Most declared Python dependencies are permissively licensed, such as MIT, BSD,
Apache-2.0, ISC, PSF, or public-domain style licenses. For example, `orjson`
is declared upstream as `Apache-2.0 OR MIT`.

The current dependency set also includes notice-relevant weak copyleft examples:

- `psycopg` is declared as `psycopg[binary]` and is LGPL-licensed upstream.
- `certifi` and `tqdm` include MPL-2.0 licensing in their upstream metadata.

Using these packages as external dependencies does not make this repository's
own code LGPL or MPL. If this project is redistributed, packaged, or shipped as
a binary or service bundle, the distribution process should include the required
third-party license texts and notices for the bundled dependencies.

## Fixtures and Other Separately Licensed Content

Some golden fixture files currently carry explicit `CC-BY-4.0` metadata:

- [golden/dataset.md](./golden/dataset.md)
- [golden/note_evergreen.md](./golden/note_evergreen.md)
- [golden/creative_scene.md](./golden/creative_scene.md)

Those fixture license markers apply to those materials. They do not change the
license for the repository's owner-controlled code or documentation.

Some committed test assets may also identify themselves as repo-original, CC0,
generated, or otherwise separately licensed in nearby documentation. Preserve
those notices when copying or redistributing those assets.

## Practical Rule

Do not assume that the top-level repository license grants rights to third-party
packages, externally sourced content, fixture data, generated assets with their
own notices, trademarks, or service-provider materials.
