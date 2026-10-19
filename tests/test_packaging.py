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

    def test_versions_match_the_app(self):
        """pkgver is the app's version; the adapter add-ons have releases of their own, of the same
        minor version (a patch release of the app keeps them)."""
        import addons
        self.assertEqual(re.search(r"^pkgver=(\S+)", PKGBUILD, re.M).group(1), addons.ASTERISM_VERSION)
        adapters = re.search(r"^_adapters=(\S+)", PKGBUILD, re.M).group(1)
        self.assertEqual(adapters.split(".")[:2], addons.ASTERISM_VERSION.split(".")[:2])
        self.assertLessEqual(addons.version_tuple(adapters), addons.version_tuple(addons.ASTERISM_VERSION))

    def test_manuals_name_this_version(self):
        """Each built manual's footer names this Asterism version (docs/manual/build.py --all)."""
        import shutil
        import subprocess
        import addons
        if shutil.which("pdftotext") is None:
            self.skipTest("pdftotext not installed")
        for pdf in sorted((ROOT / "data").glob("user-manual*.pdf")):
            with self.subTest(pdf=pdf.name):
                text = subprocess.run(["pdftotext", "-f", "5", "-l", "5", str(pdf), "-"], capture_output=True,
                                      text=True, timeout=30).stdout
                self.assertIn(f"Asterism {addons.ASTERISM_VERSION}", text)

    def test_unpacker_takes_every_file_an_add_on_may_have(self):
        source = (ROOT / "packaging/unpack-adapters.py").read_text()
        allowed = re.search(r'allowed = (\{[^}]*\})', (ROOT / "addons.py").read_text()).group(1)
        for name in ast.literal_eval(allowed):         # addons.verify's set of file names
            with self.subTest(name=name):
                self.assertIn(re.escape(name), source)


if __name__ == "__main__":
    unittest.main()
