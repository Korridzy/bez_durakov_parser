import os
import runpy
import shutil
import tempfile
import unittest
from pathlib import Path


class GenerateEnvTests(unittest.TestCase):
    def test_generates_env_files_when_fchmod_is_unavailable(self) -> None:
        # Given: a copy of the generator on a platform without os.fchmod.
        source_script = Path(__file__).with_name("generate_env.py")
        with tempfile.TemporaryDirectory() as temp_directory:
            script = Path(temp_directory) / source_script.name
            _ = shutil.copyfile(source_script, script)
            fchmod = getattr(os, "fchmod", None)
            if fchmod is not None:
                delattr(os, "fchmod")

            try:
                # When: environment generation runs through the script entry point.
                _ = runpy.run_path(str(script), run_name="__main__")
            finally:
                if fchmod is not None:
                    setattr(os, "fchmod", fchmod)

            # Then: every expected environment file is generated.
            self.assertEqual(
                {path.name for path in Path(temp_directory).glob(".env*")},
                {
                    ".env",
                    ".env.backend",
                    ".env.data_collector",
                    ".env.frontend",
                    ".env.mysql",
                },
            )


if __name__ == "__main__":
    _ = unittest.main()
