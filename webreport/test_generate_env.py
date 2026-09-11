import os
import runpy
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class GenerateEnvTests(unittest.TestCase):
    def test_routes_all_opencode_free_models(self) -> None:
        # Given: the current free OpenCode Zen model catalog.
        model_ids = (
            "big-pickle",
            "deepseek-v4-flash-free",
            "mimo-v2.5-free",
            "laguna-s-2.1-free",
            "ling-3.0-flash-free",
            "north-mini-code-free",
            "nemotron-3-ultra-free",
        )
        configuration_path = Path(__file__).with_name("litellm_config.yaml")

        # When: each free model route is inspected.
        configuration = configuration_path.read_text(encoding="utf-8")

        # Then: every model uses OpenCode's endpoint, credential, and probe-bounded health check.
        for model_id in model_ids:
            with self.subTest(model_id=model_id):
                self.assertIn(
                    f"""  - model_name: opencode/{model_id}
    litellm_params:
      model: openai/{model_id}
      api_base: https://opencode.ai/zen/v1
      api_key: os.environ/OPENCODE_API_KEY
      temperature: 0
    model_info:
      health_check_timeout: 8
""",
                    configuration,
                )

    def test_routes_deepseek_v4_flash_latest_to_openrouter(self) -> None:
        # Given: the proxy configuration shipped with WebReport.
        configuration_path = Path(__file__).with_name("litellm_config.yaml")

        # When: the configured DeepSeek Flash Latest route is inspected.
        configuration = configuration_path.read_text(encoding="utf-8")

        # Then: it uses OpenRouter's moving Latest alias rather than a pinned Flash model.
        self.assertIn(
            """  - model_name: deepseek-v4-flash-latest
    litellm_params:
      model: openrouter/~deepseek/deepseek-v4-flash-latest
      api_key: os.environ/OPENROUTER_API_KEY
      temperature: 0
    model_info:
      health_check_timeout: 8
""",
            configuration,
        )

    def test_generates_env_files_when_fchmod_is_unavailable(self) -> None:
        # Given: a copy of the generator on a platform without os.fchmod.
        source_script = Path(__file__).with_name("generate_env.py")
        with tempfile.TemporaryDirectory() as temp_directory:
            script = Path(temp_directory) / source_script.name
            _ = shutil.copyfile(source_script, script)
            sys.path.insert(0, str(Path(__file__).parent.parent))
            fchmod = getattr(os, "fchmod", None)
            if fchmod is not None:
                delattr(os, "fchmod")

            try:
                # When: environment generation runs through the script entry point.
                _ = runpy.run_path(str(script), run_name="__main__")
            finally:
                _ = sys.path.pop(0)
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
                    ".env.litellm",
                    ".env.mysql",
                },
            )

    def _generate_with_database_url(self, url: str) -> tuple[Path, dict[str, str]]:
        """Run the generator against a config whose database URL is `url`.

        The generator runs in a subprocess over a copied config tree, so the URL under test
        cannot leak into the repository's own configuration.
        """
        source_script = Path(__file__).with_name("generate_env.py")
        source_config = Path(__file__).parent.parent / "bd_shared" / "config.toml"
        source_config_module = source_config.with_name("config.py")
        temp_directory = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, temp_directory, True)

        script = Path(temp_directory) / source_script.name
        config_directory = Path(temp_directory) / "bd_shared"
        config_directory.mkdir()
        _ = shutil.copyfile(source_script, script)
        _ = shutil.copyfile(source_config_module, config_directory / "config.py")

        original = source_config.read_text(encoding="utf-8")
        rewritten = []
        for line in original.splitlines(keepends=True):
            if line.startswith("url = ") or line.startswith("docker_url = "):
                key = line.split(" = ", 1)[0]
                rewritten.append(f'{key} = "{url}"\n')
            else:
                rewritten.append(line)
        _ = (config_directory / "config.toml").write_text("".join(rewritten), encoding="utf-8")

        environment = os.environ.copy()
        _ = environment.pop("BD_CONFIG_FILE", None)
        environment["PYTHONPATH"] = temp_directory

        completed = subprocess.run(
            [sys.executable, str(script)],
            cwd=temp_directory,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)

        generated = {path.name: path.read_text(encoding="utf-8") for path in Path(temp_directory).glob(".env*")}
        return Path(temp_directory), generated

    EXPECTED_ENV_FILES = {
        ".env",
        ".env.backend",
        ".env.data_collector",
        ".env.frontend",
        ".env.litellm",
        ".env.mysql",
    }

    def test_a_sqlite_url_generates_every_env_file_with_placeholder_mysql_values(self) -> None:
        # Given: a credential-less, host-less SQLite URL.
        # When: the generator runs.
        _, generated = self._generate_with_database_url("sqlite:////data/library.db")

        # Then: nothing raised, every file exists, and the bundled MySQL gets placeholders.
        self.assertEqual(set(generated), self.EXPECTED_ENV_FILES)
        self.assertIn("MYSQL_DATABASE='unused'", generated[".env.mysql"])
        self.assertIn("MYSQL_USER='unused'", generated[".env.mysql"])
        self.assertIn("MYSQL_PASSWORD='unused'", generated[".env.mysql"])
        self.assertIn("MYSQL_ROOT_PASSWORD='unused'", generated[".env.mysql"])

    def test_a_postgresql_url_takes_the_same_non_mysql_branch(self) -> None:
        # Given: a PostgreSQL URL that does carry credentials.
        # When: the generator runs.
        _, generated = self._generate_with_database_url(
            "postgresql+psycopg://warehouse_user:warehouse_secret@pg:5432/warehouse_db"
        )

        # Then: the bundled MySQL still gets placeholders, not the PostgreSQL credentials.
        self.assertEqual(set(generated), self.EXPECTED_ENV_FILES)
        self.assertIn("MYSQL_DATABASE='unused'", generated[".env.mysql"])
        self.assertIn("MYSQL_PASSWORD='unused'", generated[".env.mysql"])
        for secret in ("warehouse_user", "warehouse_secret", "warehouse_db"):
            with self.subTest(secret=secret):
                self.assertNotIn(secret, generated[".env.mysql"])

    def test_a_mysql_url_still_reaches_the_bundled_service(self) -> None:
        # Given: the shipped MySQL URL.
        # When: the generator runs.
        _, generated = self._generate_with_database_url(
            "mysql+pymysql://durak:devpass@mysql:3306/bez_durakov"
        )

        # Then: the URL's own values reach .env.mysql unchanged.
        self.assertEqual(set(generated), self.EXPECTED_ENV_FILES)
        self.assertIn("MYSQL_DATABASE='bez_durakov'", generated[".env.mysql"])
        self.assertIn("MYSQL_USER='durak'", generated[".env.mysql"])
        self.assertIn("MYSQL_PASSWORD='devpass'", generated[".env.mysql"])

    def test_generates_litellm_key_from_local_toml_without_shell_export(self) -> None:
        # Given: a base config and a local key override with no shell key.
        source_script = Path(__file__).with_name("generate_env.py")
        source_config = Path(__file__).parent.parent / "bd_shared" / "config.toml"
        source_config_module = source_config.with_name("config.py")
        with tempfile.TemporaryDirectory() as temp_directory:
            script = Path(temp_directory) / source_script.name
            config_directory = Path(temp_directory) / "bd_shared"
            config_path = config_directory / "config.toml"
            local_config_path = config_directory / "config.local.toml"
            _ = shutil.copyfile(source_script, script)
            config_directory.mkdir()
            _ = shutil.copyfile(source_config_module, config_directory / "config.py")
            _ = config_path.write_text(
                source_config.read_text(encoding="utf-8").replace(
                    "backend_port = 28000",
                    "backend_port = 29292",
                ),
                encoding="utf-8",
            )
            _ = local_config_path.write_text(
                "[webreport]\n"
                + "openai_api_key = \"config-openai-key\"\n"
                + "openrouter_api_key = \"config-openrouter-key\"\n"
                + "opencode_api_key = \"config-opencode-key\"\n",
                encoding="utf-8",
            )
            environment = os.environ.copy()
            _ = environment.pop("BD_CONFIG_FILE", None)
            _ = environment.pop("OPENAI_API_KEY", None)
            _ = environment.pop("OPENROUTER_API_KEY", None)
            _ = environment.pop("OPENCODE_API_KEY", None)
            environment["PYTHONPATH"] = temp_directory

            # When: the generator runs without an exported OPENAI_API_KEY.
            completed = subprocess.run(
                [sys.executable, str(script)],
                cwd=temp_directory,
                env=environment,
                capture_output=True,
                text=True,
            )

            # Then: LiteLLM receives the key supplied by the TOML config.
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(
                (Path(temp_directory) / ".env.litellm").read_text(encoding="utf-8"),
                "# Generated by generate_env.py; do not edit.\n"
                + "OPENAI_API_KEY='config-openai-key'\n"
                + "OPENROUTER_API_KEY='config-openrouter-key'\n"
                + "OPENCODE_API_KEY='config-opencode-key'\n",
            )
            self.assertIn(
                "WEBREPORT_BACKEND_PORT=29292\n",
                (Path(temp_directory) / ".env").read_text(encoding="utf-8"),
            )


if __name__ == "__main__":
    _ = unittest.main()
