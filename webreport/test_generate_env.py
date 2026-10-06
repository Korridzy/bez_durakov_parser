import os
import runpy
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import nullcontext
from copy import deepcopy
from pathlib import Path
from typing import ClassVar
from unittest.mock import patch


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
                    ".env.litellm",
                    ".env.mysql",
                },
            )

    def test_removes_a_stale_frontend_environment(self) -> None:
        # Given: an environment file left by the former Python frontend.
        source_script = Path(__file__).with_name("generate_env.py")
        with tempfile.TemporaryDirectory() as temp_directory:
            script = Path(temp_directory) / source_script.name
            _ = shutil.copyfile(source_script, script)
            frontend_env = Path(temp_directory) / ".env.frontend"
            _ = frontend_env.write_text(
                "API_BASE_URL='http://obsolete:8000'\n",
                encoding="utf-8",
            )

            # When: the operator regenerates the service environments.
            _ = runpy.run_path(str(script), run_name="__main__")

            # Then: obsolete frontend settings cannot survive the migration.
            self.assertFalse(frontend_env.exists())

    def test_generates_environments_without_obsolete_frontend_settings(self) -> None:
        # Given: a config without the removed client's legacy settings.
        from bd_shared.config import get_config

        config = deepcopy(get_config())
        del config["webreport"]["chat_request_timeout_seconds"]
        del config["webreport"]["frontend_debug_port"]
        source_script = Path(__file__).with_name("generate_env.py")
        with tempfile.TemporaryDirectory() as temp_directory:
            script = Path(temp_directory) / source_script.name
            _ = shutil.copyfile(source_script, script)

            # When: environment generation reads the reduced config.
            with patch("bd_shared.config.get_config", return_value=config):
                _ = runpy.run_path(str(script), run_name="__main__")

            # Then: all remaining services get their environments.
            self.assertEqual(
                {path.name for path in Path(temp_directory).glob(".env*")},
                self.EXPECTED_ENV_FILES,
            )

    @staticmethod
    def _parse_env_file(content: str) -> dict[str, str]:
        return {
            key: value
            for line in content.splitlines()
            if "=" in line
            for key, value in [line.split("=", 1)]
        }

    def _generate_with_patched_git(
        self,
        *,
        result: subprocess.CompletedProcess[str] | None = None,
        error: BaseException | None = None,
        application_overrides: dict[str, str | int] | None = None,
    ) -> dict[str, dict[str, str]]:
        source_script = Path(__file__).with_name("generate_env.py")
        with tempfile.TemporaryDirectory() as temp_directory:
            script = Path(temp_directory) / source_script.name
            _ = shutil.copyfile(source_script, script)
            sys.path.insert(0, str(Path(__file__).parent.parent))
            config_patch = nullcontext()
            if application_overrides is not None:
                from bd_shared.config import get_config

                config = deepcopy(get_config())
                config["application"] = {
                    **config["application"],
                    **application_overrides,
                }
                config_patch = patch(
                    "bd_shared.config.get_config",
                    return_value=config,
                )
            try:
                with config_patch:
                    if error is not None:
                        with patch("subprocess.run", side_effect=error):
                            _ = runpy.run_path(str(script), run_name="__main__")
                    else:
                        assert result is not None
                        with patch("subprocess.run", return_value=result):
                            _ = runpy.run_path(str(script), run_name="__main__")
            finally:
                _ = sys.path.pop(0)

            return {
                path.name: self._parse_env_file(path.read_text(encoding="utf-8"))
                for path in Path(temp_directory).glob(".env*")
            }

    def _generate_with_git_responses(
        self,
        responses: list[subprocess.CompletedProcess[str] | FileNotFoundError],
    ) -> tuple[dict[str, dict[str, str]], list[list[str]]]:
        source_script = Path(__file__).with_name("generate_env.py")
        with tempfile.TemporaryDirectory() as temp_directory:
            script = Path(temp_directory) / source_script.name
            _ = shutil.copyfile(source_script, script)
            sys.path.insert(0, str(Path(__file__).parent.parent))
            try:
                with patch("subprocess.run", side_effect=responses) as git_run:
                    _ = runpy.run_path(str(script), run_name="__main__")
                    commands = [call.args[0] for call in git_run.call_args_list]
            finally:
                _ = sys.path.pop(0)

            generated = {
                path.name: self._parse_env_file(path.read_text(encoding="utf-8"))
                for path in Path(temp_directory).glob(".env*")
            }
            return generated, commands

    def test_uses_exact_release_tag_for_app_version(self) -> None:
        # Given: git reports an exact release tag for HEAD.
        describe_command = ["git", "describe", "--tags", "--exact-match"]
        tag_result = subprocess.CompletedProcess(
            describe_command,
            0,
            stdout="v9.9.9\n",
            stderr="",
        )

        # When: environment generation resolves the application version.
        generated, commands = self._generate_with_git_responses([tag_result])

        # Then: the tag is used after querying git's exact-tag description.
        self.assertEqual(generated[".env.backend"]["BD_APP_VERSION"], "v9.9.9")
        self.assertEqual(commands, [describe_command])

    def test_uses_short_sha_when_head_has_no_exact_release_tag(self) -> None:
        # Given: HEAD has no exact tag and git supplies its short commit identifier.
        describe_command = ["git", "describe", "--tags", "--exact-match"]
        short_sha_command = ["git", "rev-parse", "--short", "HEAD"]
        no_tag_result = subprocess.CompletedProcess(
            describe_command,
            128,
            stdout="",
            stderr="fatal: no tag exactly matches 'deadbeef'\n",
        )
        short_sha_result = subprocess.CompletedProcess(
            short_sha_command,
            0,
            stdout="abc1234\n",
            stderr="",
        )

        # When: environment generation resolves the application version.
        generated, commands = self._generate_with_git_responses(
            [no_tag_result, short_sha_result]
        )

        # Then: the short SHA is used after the exact-tag lookup finds no tag.
        self.assertEqual(generated[".env.backend"]["BD_APP_VERSION"], "abc1234")
        self.assertEqual(commands, [describe_command, short_sha_command])

    def test_generates_application_logging_environment(self) -> None:
        # Given: git returns a short commit identifier.
        completed = subprocess.CompletedProcess(
            ["git", "rev-parse", "--short", "HEAD"],
            0,
            stdout="abc1234\n",
            stderr="",
        )

        # When: environment generation runs in a copied script directory.
        generated = self._generate_with_patched_git(result=completed)

        # Then: application settings reach only the application service environment files.
        expected = {
            "BD_LOG_LEVEL": "INFO",
            "BD_LOG_FORMAT": "console",
            "BD_ENVIRONMENT": "development",
            "BD_APP_VERSION": "abc1234",
        }
        for file_name in (".env.backend", ".env.data_collector"):
            with self.subTest(file_name=file_name):
                for key, value in expected.items():
                    self.assertEqual(generated[file_name][key], value)
        for file_name in (".env", ".env.mysql", ".env.litellm"):
            with self.subTest(file_name=file_name):
                for key in expected:
                    self.assertNotIn(key, generated[file_name])

    def test_generates_docker_log_rotation_environment(self) -> None:
        # Given: non-default Docker log rotation settings in application config.
        completed = subprocess.CompletedProcess(
            ["git", "rev-parse", "--short", "HEAD"],
            0,
            stdout="abc1234\n",
            stderr="",
        )

        # When: environment generation runs.
        generated = self._generate_with_patched_git(
            result=completed,
            application_overrides={
                "log_rotation_max_size": "42m",
                "log_rotation_max_files": 7,
            },
        )

        # Then: Compose receives both settings through its root environment file.
        self.assertEqual(generated[".env"]["BD_LOG_ROTATION_MAX_SIZE"], "42m")
        self.assertEqual(generated[".env"]["BD_LOG_ROTATION_MAX_FILES"], "7")

    def test_uses_unknown_app_version_when_git_is_missing(self) -> None:
        # Given: git cannot be started for the exact-tag lookup.
        describe_command = ["git", "describe", "--tags", "--exact-match"]
        generated, commands = self._generate_with_git_responses(
            [FileNotFoundError("git")]
        )

        # Then: application environments use the fallback after attempting tag lookup.
        self.assertEqual(generated[".env.backend"]["BD_APP_VERSION"], "unknown")
        self.assertEqual(commands, [describe_command])

    def test_uses_unknown_app_version_when_git_returns_nonzero(self) -> None:
        # Given: the directory is not a git repository.
        completed = subprocess.CompletedProcess(
            ["git", "rev-parse", "--short", "HEAD"],
            128,
            stdout="",
            stderr="fatal: not a git repository\n",
        )

        # When: environment generation runs.
        generated = self._generate_with_patched_git(result=completed)

        # Then: application environments use the documented fallback version.
        self.assertEqual(generated[".env.backend"]["BD_APP_VERSION"], "unknown")

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
        rewritten: list[str] = []
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

    EXPECTED_ENV_FILES: ClassVar[set[str]] = {
        ".env",
        ".env.backend",
        ".env.data_collector",
        ".env.litellm",
        ".env.mysql",
    }
    LITELLM_SETTINGS_WITHOUT_CALLBACK: ClassVar[str] = (
        "# Generated by generate_env.py; do not edit.\n"
        "litellm_settings:\n"
        "  num_retries: 2\n"
    )

    def _generate_with_langfuse_values(
        self,
        *,
        host: str,
        public_key: str,
        secret_key: str,
    ) -> tuple[Path, dict[str, str]]:
        source_script = Path(__file__).with_name("generate_env.py")
        source_config = Path(__file__).parent.parent / "bd_shared" / "config.toml"
        temp_directory = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, temp_directory, True)

        script = Path(temp_directory) / source_script.name
        config_path = Path(temp_directory) / "config.toml"
        _ = shutil.copyfile(source_script, script)

        langfuse_values = {
            "langfuse_host": host,
            "langfuse_public_key": public_key,
            "langfuse_secret_key": secret_key,
        }
        config_lines: list[str] = []
        inserted = False
        for line in source_config.read_text(encoding="utf-8").splitlines(keepends=True):
            if any(line.startswith(f"{key} = ") for key in langfuse_values):
                continue
            config_lines.append(line)
            if line.startswith("opencode_api_key = "):
                config_lines.extend(
                    f'{key} = "{value}"\n' for key, value in langfuse_values.items()
                )
                inserted = True
        self.assertTrue(inserted, "scratch config did not find the WebReport API key block")
        _ = config_path.write_text("".join(config_lines), encoding="utf-8")

        environment = os.environ.copy()
        environment["BD_CONFIG_FILE"] = str(config_path)
        _ = environment.pop("BD_CONFIG_LOCAL_FILE", None)
        environment["PYTHONPATH"] = str(Path(__file__).parent.parent)
        completed = subprocess.run(
            [sys.executable, str(script)],
            cwd=temp_directory,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)

        generated = {
            path.name: path.read_text(encoding="utf-8")
            for path in Path(temp_directory).iterdir()
            if path.name.startswith(".env")
            or path.name == "litellm_settings.generated.yaml"
        }
        return Path(temp_directory), generated

    def test_empty_langfuse_credentials_disable_callback(self) -> None:
        # Given: all three Langfuse settings are empty.
        # When: the proxy environment and generated settings are rendered.
        _, generated = self._generate_with_langfuse_values(
            host="",
            public_key="",
            secret_key="",
        )

        # Then: empty credentials reach LiteLLM and do not enable its callback.
        self.assertIn("LANGFUSE_PUBLIC_KEY=''\n", generated[".env.litellm"])
        self.assertIn("LANGFUSE_SECRET_KEY=''\n", generated[".env.litellm"])
        self.assertIn("LANGFUSE_HOST=''\n", generated[".env.litellm"])
        self.assertEqual(
            generated["litellm_settings.generated.yaml"],
            self.LITELLM_SETTINGS_WITHOUT_CALLBACK,
        )

    def test_incomplete_langfuse_credentials_disable_callback(self) -> None:
        # Given: only two of the three required Langfuse settings are populated.
        # When: the generated LiteLLM settings are rendered.
        _, generated = self._generate_with_langfuse_values(
            host="https://langfuse.example.test",
            public_key="pk-lf-test",
            secret_key="",
        )

        # Then: the callback remains disabled rather than starting with partial credentials.
        settings = generated["litellm_settings.generated.yaml"]
        self.assertEqual(settings, self.LITELLM_SETTINGS_WITHOUT_CALLBACK)
        self.assertNotIn("callbacks", settings)

    def test_generated_litellm_settings_mode_is_private(self) -> None:
        # Given: an otherwise default proxy configuration.
        directory, _ = self._generate_with_langfuse_values(
            host="",
            public_key="",
            secret_key="",
        )

        # Then: generated proxy settings are readable only by their owner.
        mode = (directory / "litellm_settings.generated.yaml").stat().st_mode & 0o777
        self.assertEqual(mode, 0o600)

    def test_static_litellm_config_includes_generated_settings(self) -> None:
        configuration = Path(__file__).with_name("litellm_config.yaml").read_text(
            encoding="utf-8"
        )

        self.assertIn("include:\n  - litellm_settings.generated.yaml\n", configuration)
        self.assertNotIn("\nlitellm_settings:\n", configuration)

    def test_litellm_service_mounts_generated_settings_and_resolves_host(self) -> None:
        configuration = Path(__file__).with_name("docker-compose.yml").read_text(
            encoding="utf-8"
        )
        litellm_service = configuration.split("  litellm:\n", 1)[1].split(
            "  backend:\n", 1
        )[0]

        self.assertIn(
            "      - ./litellm_settings.generated.yaml:"
            + "/app/litellm_settings.generated.yaml:ro\n",
            litellm_service,
        )
        self.assertIn(
            '    extra_hosts:\n      - "host.docker.internal:host-gateway"\n',
            litellm_service,
        )

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

    def test_generates_litellm_keys_from_local_toml_without_shell_export(self) -> None:
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
                + "opencode_api_key = \"config-opencode-key\"\n"
                + "langfuse_public_key = \"config-langfuse-public-key\"\n"
                + "langfuse_secret_key = \"config-langfuse-secret-key\"\n"
                + "langfuse_host = \"https://langfuse.example.test\"\n",
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
                + "OPENCODE_API_KEY='config-opencode-key'\n"
                + "LANGFUSE_PUBLIC_KEY='config-langfuse-public-key'\n"
                + "LANGFUSE_SECRET_KEY='config-langfuse-secret-key'\n"
                + "LANGFUSE_HOST='https://langfuse.example.test'\n",
            )
            self.assertEqual(
                (Path(temp_directory) / "litellm_settings.generated.yaml").read_text(
                    encoding="utf-8"
                ),
                self.LITELLM_SETTINGS_WITHOUT_CALLBACK
                + '  callbacks: ["langfuse_otel"]\n',
            )
            self.assertIn(
                "WEBREPORT_BACKEND_PORT=29292\n",
                (Path(temp_directory) / ".env").read_text(encoding="utf-8"),
            )


if __name__ == "__main__":
    _ = unittest.main()
