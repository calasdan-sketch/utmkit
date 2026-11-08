# Publishing utmkit (for Calas Automations Inc.)

**Version to release: 0.2.0.** A search of PyPI on 2026-11-08 found no package called `utmkit` (the lookup returned "not found"), so 0.2.0 has never been published and no version bump is needed. After a first upload that version number can never be reused, so any later fix is 0.2.1.

Nothing here has been run for you. The upload step is yours (you are signed in to PyPI).

## Before you upload (about 10 minutes)

1. Open a terminal in the `utmkit` folder.
2. Run the tests: `python -m pip install -e ".[dev]"` then `python -m pytest -q`. Expect every test to pass (199 at the time of writing).
3. Build the files: `python -m build`. Two files appear in `dist/`: a `.whl` and a `.tar.gz`.
4. Check them: `python -m twine check dist/*`. Expect `PASSED` twice.
5. Check the author that will be shown on PyPI: `unzip -p dist/*.whl "*/METADATA" | grep -i "^Author"`. It must say `Author: Calas Automations Inc.`
6. Try the built file in a clean place (not your working copy):
   `python -m venv /tmp/try && /tmp/try/bin/pip install dist/*.whl && /tmp/try/bin/utmkit --version`
   Expect `utmkit 0.2.0 (Calas Automations Inc.)`.
7. Read `CHANGELOG.md` and `README.md` once. Both describe exactly what ships.

## Decide first

- **The repository is private.** The package page will therefore show no source link, and the README does not claim one. If you later make the repository public, add a `[project.urls]` section to `pyproject.toml` and release 0.2.1.
- **Contact address.** No email is in the package metadata (none was given for this project). People will see only the company name.
- **PyPI name.** `utmkit` looked free, but names can be taken at any moment. If the upload says the name exists, pick another name before anything else.

## Upload (your step)

Optional dress rehearsal on the test site (free): `python -m twine upload --repository testpypi dist/*`

The real upload: `python -m twine upload dist/*`

After it succeeds: `pip install utmkit` in a fresh environment and run `utmkit --version`.

Do not upload twice with the same version number; PyPI refuses it.
