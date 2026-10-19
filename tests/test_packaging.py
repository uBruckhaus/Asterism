"""The packages carry what the app reads next to its modules at run time: a folder left out (as
adapters/ was once) makes the packaged app fail although every source test passes."""
import ast
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILD = (ROOT / "packaging/appimage/build.sh").read_text()
PKGBUILD = (ROOT / "packaging/aur/PKGBUILD").read_text()


class PackagesCarryTheAppTest(unittest.TestCase):
    def test_runtime_folders_in_both_packages(self):
        for needed in ("translations", "icons", "adapters/*.toml", "adapters/*.py", "user-manual*.pdf",
                       "unpack-adapters.py"):
            with self.subTest(needed=needed):
                self.assertIn(needed, BUILD)
                self.assertIn(needed, PKGBUILD)

    def test_every_manual_language_is_built(self):
        pdfs = sorted(p.name for p in (ROOT / "data").glob("user-manual*.pdf"))
        self.assertEqual(len(pdfs), 8, pdfs)        # English and the seven translations

    def test_adapters_version_matches_the_app(self):
        import addons
        found = re.search(r"^_adapters=(\S+)", PKGBUILD, re.M)
        self.assertEqual(found.group(1), addons.ASTERISM_VERSION)
        self.assertEqual(re.search(r"^pkgver=(\S+)", PKGBUILD, re.M).group(1), addons.ASTERISM_VERSION)

    def test_unpacker_takes_every_file_an_add_on_may_have(self):
        source = (ROOT / "packaging/unpack-adapters.py").read_text()
        allowed = re.search(r'allowed = (\{[^}]*\})', (ROOT / "addons.py").read_text()).group(1)
        for name in ast.literal_eval(allowed):         # addons.verify's set of file names
            with self.subTest(name=name):
                self.assertIn(re.escape(name), source)


if __name__ == "__main__":
    unittest.main()
