"""verify-db-isolation contract tests: Docker, ss and /proc never reach the real host."""

import contextlib
import io
import ipaddress
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import deploy.deploy as d  # noqa: E402

MYSQL_IMAGE = "mysql@sha256:" + "4" * 64
SERVICES = {"mysql": (33121, 3306), "backend": (28000, 8000), "frontend": (28501, 8501)}
LOOPBACK_SS = "LISTEN 0 4096 127.0.0.1:33121 0.0.0.0:*\nLISTEN 0 128 0.0.0.0:22 0.0.0.0:*\n"
# Repository privacy rule: tracked files carry no address literals except 127.0.0.1, 0.0.0.0 and
# 127.0.0.11, so every other address these tests need is built from integers at runtime.
def _v4(number):
    return str(ipaddress.IPv4Address(number))


def _v6(number):
    return str(ipaddress.IPv6Address(number))


PRIVATE_V4_ONE = _v4(0x0A010203)
PRIVATE_V4_TWO = _v4(0x0A090807)
PRIVATE_V4_THREE = _v4(0x0A000001)
DOCUMENTATION_V4 = _v4(0xC0000209)
PUBLIC_V4 = _v4(0x01010101)
LOOPBACK_V4_OTHER = _v4(0x7F090909)
LOOPBACK_V4_SECOND = _v4(0x7F000036)
DOCUMENTATION_V6 = _v6((0x20010DB8 << 96) | 1)
DOCUMENTATION_V6_PREFIX = f"{0x2001:x}:{0xDB8:x}"
LINK_LOCAL_V6 = _v6((0xFE80 << 112) | 1) + "%eth0"
PROC_HEADER = "  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode\n"


def bound(host_ip, published, target, *, with_ip=True):
    entry = {"mode": "ingress", "target": target, "published": str(published), "protocol": "tcp"}
    if with_ip:
        entry["host_ip"] = host_ip
    return entry


def rendered(**hosts):
    services = {}
    for name, (published, target) in SERVICES.items():
        host = hosts.get(name, "127.0.0.1")
        services[name] = {"image": MYSQL_IMAGE if name == "mysql" else name,
                          "ports": [bound(host, published, target, with_ip=host is not None)]}
    return json.dumps({"services": services})


def bindings(host_ip, published, target, *, with_ip=True):
    entry = {"HostPort": str(published)}
    if with_ip:
        entry["HostIp"] = host_ip
    return json.dumps({f"{target}/tcp": [entry]})


def proc_line(slot, address, state):
    return f"   {slot}: {address} 00000000:0000 {state} 00000000:00000000 00:00000000 00000000     0        0 1 1\n"


class IsolationRunner:
    """Answers each command class; an Exception value is raised instead of returned."""

    def __init__(self):
        self.calls = []
        self.config: Any = rendered()
        self.ids = {name: "id-" + name for name in SERVICES}
        self.bindings: dict[str, Any] = {"id-" + name: bindings("127.0.0.1", p, t) for name, (p, t) in SERVICES.items()}
        self.ss: Any = LOOPBACK_SS
        self.ss_code = 0
        self.probe: Any = (0, "probe-exit=1\nbash: connect: Connection refused\n")
        self.config_code = 0
        self.ps_code = 0

    def reply(self, argv, code, out: Any = "", err=""):
        value = code if isinstance(code, BaseException) else subprocess.CompletedProcess(argv, code, out, err)
        if isinstance(value, BaseException):
            raise value
        return value

    def run(self, argv, *, cwd, env, input=None, timeout=120):
        self.calls.append((list(argv), timeout))
        if argv[:2] == ["docker", "compose"] and "config" in argv:
            if isinstance(self.config, BaseException):
                raise self.config
            return self.reply(argv, self.config_code, self.config, "boom-secret")
        if argv[:2] == ["docker", "compose"] and "ps" in argv:
            return self.reply(argv, self.ps_code, self.ids.get(argv[-1], "") + "\n" if self.ids.get(argv[-1]) else "")
        if argv[:3] == ["docker", "container", "inspect"]:
            value = self.bindings[argv[3]]
            return self.reply(argv, value if isinstance(value, BaseException) else 0, value)
        if argv[0] == "ss":
            if isinstance(self.ss, BaseException):
                raise self.ss
            return self.reply(argv, self.ss_code, self.ss)
        if argv[:2] == ["docker", "run"]:
            code, out = self.probe if not isinstance(self.probe, BaseException) else (self.probe, "")
            return self.reply(argv, code, out)
        raise AssertionError(f"Unexpected command: {argv}")


class VerifyIsolationTest(unittest.TestCase):
    def __init__(self, methodName="runTest"):
        super().__init__(methodName)
        self.temp = tempfile.TemporaryDirectory(prefix="bdvrd-t16-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "webreport").mkdir()
        self.env = {"BD_DEPLOY_STATE_DIR": str(self.root / "state"), "COMPOSE_PROJECT_NAME": "bdvrd-t16-test"}
        self.runner = IsolationRunner()
        self.proc = mock.MagicMock(side_effect=OSError("no proc"))

    def setUp(self):
        patch = mock.patch.object(d, "read_proc_tcp", self.proc)
        patch.start()
        self.addCleanup(patch.stop)

    def invoke(self, *flags):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = d.main(["verify-db-isolation", *flags], root=self.root, env=self.env, runner=self.runner)
        return code, out.getvalue(), err.getvalue()

    def release_mode(self):
        state = d.State(self.root, self.env)
        state.initialize()
        pin = state.path / "releases" / "v1.2.3" / "compose.release.yml"
        pin.parent.mkdir(parents=True)
        pin.write_text("{}\n")
        state.write_current({"last_successful": {"tag": "v1.2.3"}})
        return pin

    @staticmethod
    def rows(out, check):
        found = []
        for line in out.splitlines():
            parts = line.split(None, 2)
            if len(parts) == 3 and parts[1] == check and parts[0] in ("PASS", "FAIL", "INFO", "SKIP"):
                found.append((parts[0], parts[2]))
        return found

    def assertFails(self, result, check, containing=""):
        code, out, err = result
        self.assertEqual(code, 1, (out, err))
        self.assertIn("RESULT: FAIL", out)
        failed = [detail for status, detail in self.rows(out, check) if status == "FAIL"]
        self.assertTrue(any(containing in detail for detail in failed), (check, containing, out))

    def assertPasses(self, result):
        code, out, err = result
        self.assertEqual(code, 0, (out, err))
        self.assertIn("RESULT: PASS", out)
        self.assertNotIn("FAIL", [status for line in out.splitlines() for status in line.split()[:1]])

    def test_all_loopback_passes_with_one_row_per_check(self):
        result = self.invoke()
        self.assertPasses(result)
        out = result[1]
        for check in ("compose-config", "container-bindings", "listening-sockets"):
            self.assertIn("PASS", [status for status, _ in self.rows(out, check)], check)
        self.assertEqual(self.rows(out, "container-probe"), [])
        self.assertIn("mysql", out)

    def test_dev_mode_reports_other_services_as_informational_only(self):
        self.runner.config = rendered(backend=None, frontend="0.0.0.0")
        self.runner.bindings["id-backend"] = bindings("", 28000, 8000)
        self.runner.bindings["id-frontend"] = bindings("::", 28501, 8501)
        self.runner.ss = LOOPBACK_SS + "LISTEN 0 4096 0.0.0.0:28000 0.0.0.0:*\n"
        result = self.invoke()
        self.assertPasses(result)
        info = [detail for status, detail in self.rows(result[1], "compose-config") if status == "INFO"]
        self.assertEqual(len(info), 2, result[1])
        self.assertTrue(any("backend" in detail for detail in info))

    def test_config_with_wildcard_binding_fails(self):
        for host in ("0.0.0.0", "::", "[::]", "", None, PRIVATE_V4_ONE, "localhost", "::1"):
            with self.subTest(host=host):
                self.runner.config = rendered(mysql=host)
                result = self.invoke()
                self.assertFails(result, "compose-config", "mysql")
                self.assertNotIn(PRIVATE_V4_ONE, result[1] + result[2])

    def test_unrenderable_or_malformed_config_fails(self):
        cases = {
            "nonzero": lambda r: setattr(r, "config_code", 1),
            "timeout": lambda r: setattr(r, "config", subprocess.TimeoutExpired("docker", 120)),
            "oserror": lambda r: setattr(r, "config", OSError("no docker")),
            "garbage": lambda r: setattr(r, "config", "not json"),
            "list": lambda r: setattr(r, "config", "[]"),
            "no-mysql": lambda r: setattr(r, "config", json.dumps({"services": {}})),
            "ports-not-list": lambda r: setattr(r, "config", json.dumps({"services": {"mysql": {"ports": "3306"}}})),
            "port-not-object": lambda r: setattr(r, "config", json.dumps({"services": {"mysql": {"ports": [None]}}})),
        }
        for name, mutate in cases.items():
            with self.subTest(name=name):
                self.runner = IsolationRunner()
                mutate(self.runner)
                result = self.invoke()
                self.assertEqual(result[0], 1, result)
                self.assertTrue(any(status == "FAIL" for status, _ in self.rows(result[1], "compose-config")), result[1])
                self.assertNotIn("boom-secret", result[1] + result[2])

    def test_container_binding_wildcards_fail(self):
        for host in ("::", "[::]", "0.0.0.0", "", None, DOCUMENTATION_V4):
            with self.subTest(host=host):
                self.runner.bindings["id-mysql"] = bindings(host, 33121, 3306, with_ip=host is not None)
                result = self.invoke()
                self.assertFails(result, "container-bindings", "mysql")
                self.assertNotIn(DOCUMENTATION_V4, result[1] + result[2])

    def test_container_binding_without_publication_is_not_a_failure(self):
        for value in ("null", "{}", '{"3306/tcp": null}', '{"3306/tcp": []}'):
            with self.subTest(value=value):
                self.runner.bindings["id-mysql"] = value
                self.assertPasses(self.invoke())

    def test_malformed_container_bindings_fail(self):
        for value in ("not json", "[]", '"x"', '{"3306/tcp": "x"}', '{"3306/tcp": [null]}', '{"3306/tcp": [{"HostIp": 7}]}',
                      subprocess.TimeoutExpired("docker", 30)):
            with self.subTest(value=value):
                self.runner.bindings["id-mysql"] = value
                self.assertFails(self.invoke(), "container-bindings", "mysql")

    def test_listing_or_inspect_failure_fails_not_skips(self):
        self.runner.ps_code = 1
        self.assertFails(self.invoke(), "container-bindings", "mysql")

    def test_stopped_service_is_skipped_visibly(self):
        self.runner.ids["mysql"] = ""
        result = self.invoke()
        self.assertPasses(result)
        self.assertIn("SKIP", [status for status, _ in self.rows(result[1], "container-bindings")])

    def test_wildcard_socket_on_required_port_fails(self):
        for local in ("0.0.0.0:33121", "*:33121", "[::]:33121", "[::ffff:0.0.0.0]:33121", "0.0.0.0%lo:33121",
                      f"{PRIVATE_V4_TWO}:33121", f"[{DOCUMENTATION_V6}]:33121"):
            with self.subTest(local=local):
                self.runner.ss = f"LISTEN 0 4096 {local} 0.0.0.0:*\n"
                result = self.invoke()
                self.assertFails(result, "listening-sockets", "33121")
                self.assertNotIn(PRIVATE_V4_TWO, result[1] + result[2])
                self.assertNotIn(DOCUMENTATION_V6_PREFIX, result[1] + result[2])

    def test_loopback_forms_and_other_ports_pass(self):
        self.runner.ss = ("LISTEN 0 1 127.0.0.1:33121 0.0.0.0:*\nLISTEN 0 1 [::1]:33121 [::]:*\n"
                          f"LISTEN 0 1 {LOOPBACK_V4_SECOND}:33121 0.0.0.0:*\nLISTEN 0 1 *:8080 *:*\nLISTEN 0 1 [::]:8081 [::]:*\n")
        self.assertPasses(self.invoke())

    def test_empty_or_unparsable_ss_never_reads_as_pass(self):
        for text in ("", "\n", "garbage\n", "LISTEN 0 1 nonsense 0.0.0.0:*\n", "LISTEN 0 1 127.0.0.1:notaport 0.0.0.0:*\n"):
            with self.subTest(text=text):
                self.runner.ss = text
                self.assertFails(self.invoke(), "listening-sockets")

    def test_ss_failure_falls_back_to_proc_and_fails_when_both_fail(self):
        self.runner.ss_code = 1
        self.runner.ss = ""
        self.assertFails(self.invoke(), "listening-sockets", "cannot")
        self.runner.ss = OSError("no ss")
        self.assertFails(self.invoke(), "listening-sockets", "cannot")
        self.runner.ss = subprocess.TimeoutExpired("ss", 30)
        self.assertFails(self.invoke(), "listening-sockets", "cannot")

    def test_proc_fallback_detects_wildcards_and_passes_loopback(self):
        self.runner.ss_code = 1
        files = {
            "tcp": PROC_HEADER + proc_line(0, "0100007F:8161", "0A") + proc_line(1, "00000000:0016", "0A"),
            "tcp6": PROC_HEADER + proc_line(0, "00000000000000000000000001000000:8161", "0A"),
        }
        self.proc.side_effect = lambda name: files[name]
        self.assertPasses(self.invoke())
        files["tcp"] += proc_line(2, "00000000:8161", "0A")
        self.assertFails(self.invoke(), "listening-sockets", "33121")
        files["tcp"] = PROC_HEADER + proc_line(0, "0100007F:8161", "0A") + proc_line(2, "00000000:8161", "01")
        self.assertPasses(self.invoke())
        files["tcp6"] += proc_line(1, "00000000000000000000000000000000:8161", "0A")
        self.assertFails(self.invoke(), "listening-sockets", "33121")

    def test_proc_fallback_with_nothing_listening_fails(self):
        self.runner.ss_code = 1
        self.proc.side_effect = lambda name: PROC_HEADER
        self.assertFails(self.invoke(), "listening-sockets", "cannot")

    def test_release_mode_uses_the_pin_file_and_requires_every_service(self):
        pin = self.release_mode()
        self.assertPasses(self.invoke())
        config_calls = [argv for argv, _ in self.runner.calls if "config" in argv]
        self.assertEqual(len(config_calls), 1)
        argv = config_calls[0]
        files = [argv[i + 1] for i, item in enumerate(argv) if item == "-f"]
        self.assertEqual(files, [str(self.root / "webreport" / "docker-compose.yml"),
                                 str(self.root / "webreport" / "docker-compose.prod.yml"), str(pin)])
        self.runner.config = rendered(frontend="0.0.0.0")
        self.assertFails(self.invoke(), "compose-config", "frontend")
        self.runner.config = rendered()
        self.runner.bindings["id-backend"] = bindings("0.0.0.0", 28000, 8000)
        self.assertFails(self.invoke(), "container-bindings", "backend")
        self.runner.bindings["id-backend"] = bindings("127.0.0.1", 28000, 8000)
        self.runner.ss = LOOPBACK_SS + "LISTEN 0 1 *:28501 *:*\n"
        self.assertFails(self.invoke(), "listening-sockets", "28501")

    def test_dev_mode_does_not_include_prod_files(self):
        self.invoke()
        argv = next(argv for argv, _ in self.runner.calls if "config" in argv)
        self.assertEqual([argv[i + 1] for i, item in enumerate(argv) if item == "-f"],
                         [str(self.root / "webreport" / "docker-compose.yml")])

    def test_release_mode_without_a_recorded_release_fails(self):
        state = d.State(self.root, self.env)
        state.initialize()
        state.write_current({"attempt": {"tag": "v1.2.3"}})
        self.assertFails(self.invoke(), "compose-config", "release")

    def config_calls(self):
        return [argv for argv, _ in self.runner.calls if "config" in argv]

    def write_state(self, data):
        state = d.State(self.root, self.env)
        state.initialize()
        (state.path / "current.json").write_bytes(data)
        return state

    def test_absent_current_json_selects_dev_mode(self):
        self.assertFalse((d.State(self.root, self.env).path / "current.json").exists())
        self.assertPasses(self.invoke())
        files = [argv[i + 1] for argv in self.config_calls() for i, item in enumerate(argv) if item == "-f"]
        self.assertEqual(files, [str(self.root / "webreport" / "docker-compose.yml")])

    def test_existing_but_empty_or_invalid_state_fails_instead_of_selecting_dev_mode(self):
        for name, data in {"empty-object": b"{}\n", "empty-file": b"", "invalid-json": b"{not json",
                           "list": b"[]", "attempt-only": b'{"attempt": {"tag": "v1.2.3"}}',
                           "last-successful-null": b'{"last_successful": null}',
                           "no-tag": b'{"last_successful": {}}',
                           "tag-not-a-version": b'{"last_successful": {"tag": "../x"}}',
                           "tag-not-a-string": b'{"last_successful": {"tag": 7}}'}.items():
            with self.subTest(name=name):
                self.runner = IsolationRunner()
                self.write_state(data)
                result = self.invoke()
                self.assertFails(result, "compose-config", "cannot")
                self.assertEqual(self.config_calls(), [])
                self.assertNotIn("not required in dev mode", result[1])

    def test_state_that_is_not_a_readable_file_fails(self):
        state = d.State(self.root, self.env)
        state.initialize()
        (state.path / "current.json").mkdir()
        self.assertFails(self.invoke(), "compose-config", "cannot")

    def test_valid_state_with_missing_pin_file_fails(self):
        self.write_state(b'{"last_successful": {"tag": "v1.2.3"}}')
        result = self.invoke()
        self.assertFails(result, "compose-config", "pin file")
        self.assertEqual(self.config_calls(), [])

    def test_valid_state_with_pin_file_selects_release_mode(self):
        pin = self.release_mode()
        self.assertPasses(self.invoke())
        argv = self.config_calls()[0]
        files = [argv[i + 1] for i, item in enumerate(argv) if item == "-f"]
        self.assertEqual(files[1:], [str(self.root / "webreport" / "docker-compose.prod.yml"), str(pin)])

    def test_dirty_marker_does_not_block_a_read_only_check(self):
        state = d.State(self.root, self.env)
        self.release_mode()
        state.write_current({"stage": "migration_started", "last_successful": {"tag": "v1.2.3"}})
        self.assertPasses(self.invoke())

    def probe_calls(self):
        return [argv for argv, _ in self.runner.calls if argv[:2] == ["docker", "run"]]

    def test_probe_refused_passes_and_uses_the_pinned_mysql_image(self):
        result = self.invoke("--container-probe")
        self.assertPasses(result)
        self.assertIn("PASS", [status for status, _ in self.rows(result[1], "container-probe")])
        calls = self.probe_calls()
        self.assertEqual(len(calls), 1)
        argv = calls[0]
        for needle in ("--rm", "--network", "bridge", "host.docker.internal:host-gateway", MYSQL_IMAGE):
            self.assertIn(needle, argv)
        self.assertIn("never", argv)
        self.assertIn("/dev/tcp/host.docker.internal/33121", argv[-1])

    def test_probe_runs_for_every_required_published_port_in_release_mode(self):
        self.release_mode()
        self.assertPasses(self.invoke("--container-probe"))
        found = [re.search(r"/dev/tcp/host\.docker\.internal/(\d+)", argv[-1]) for argv in self.probe_calls()]
        ports = sorted(match.group(1) for match in found if match)
        self.assertEqual(ports, ["28000", "28501", "33121"])

    def test_probe_that_connects_fails(self):
        self.runner.probe = (0, "probe-exit=0\n")
        self.assertFails(self.invoke("--container-probe"), "container-probe", "connected")

    def test_probe_timeout_is_inconclusive_and_fails(self):
        self.runner.probe = (0, "probe-exit=124\n")
        self.assertFails(self.invoke("--container-probe"), "container-probe", "inconclusive")

    def test_probe_that_could_not_run_or_hung_fails(self):
        cases = [(125, ""), (0, ""), (0, "probe-exit=1\nbash: host.docker.internal: Name or service not known\n"),
                 (0, "probe-exit=127\n"), subprocess.TimeoutExpired("docker", 60), OSError("no docker")]
        for probe in cases:
            with self.subTest(probe=probe):
                self.runner.probe = probe
                self.assertFails(self.invoke("--container-probe"), "container-probe", "mysql")

    def test_probe_without_a_pinned_image_fails_before_running_docker(self):
        for image in (None, "mysql:8", ""):
            with self.subTest(image=image):
                self.runner = IsolationRunner()
                services = json.loads(self.runner.config)
                services["services"]["mysql"]["image"] = image
                self.runner.config = json.dumps(services)
                self.assertFails(self.invoke("--container-probe"), "container-probe", "image")
                self.assertEqual(self.probe_calls(), [])

    def test_probe_is_off_unless_requested(self):
        self.invoke()
        self.assertEqual(self.probe_calls(), [])

    def test_off_host_recipe_is_printed_without_any_address(self):
        code, out, _ = self.invoke()
        self.assertIn("nc -4 -z -w 3 <public-ipv4> 33121", out)
        self.assertIn("nc -6 -z -w 3 <public-ipv6> 33121", out)
        self.assertIn("443", out)
        for word in ("connect", "refused", "timeout"):
            self.assertIn(word, out.lower())
        allowed = {"127.0.0.1", "0.0.0.0"}
        self.assertEqual({m for m in re.findall(r"\d{1,3}(?:\.\d{1,3}){3}", out)} - allowed, set())

    def test_read_only_commands_only(self):
        self.invoke("--container-probe")
        for argv, timeout in self.runner.calls:
            self.assertGreater(timeout, 0)
            self.assertLessEqual(timeout, 120)
            self.assertNotIn(argv[2:3], (["up"], ["down"], ["rm"], ["restart"], ["stop"]))
            self.assertIn(argv[0], ("docker", "ss"))
            self.assertNotIn("iptables", argv)
            self.assertNotIn("ufw", argv)
            self.assertNotIn("--privileged", argv)

    def test_failures_still_print_the_recipe_and_a_summary(self):
        self.runner.config = rendered(mysql="0.0.0.0")
        code, out, _ = self.invoke()
        self.assertEqual(code, 1)
        self.assertIn("nc -4 -z -w 3", out)
        self.assertIn("RESULT: FAIL", out)


class ParserTest(unittest.TestCase):
    def test_classify_host(self):
        cases = {"127.0.0.1": "loopback", LOOPBACK_V4_OTHER: "loopback", "::1": "loopback", "[::1]": "loopback",
                 "::ffff:127.0.0.1": "loopback", "0.0.0.0": "wildcard", "::": "wildcard", "[::]": "wildcard",
                 "*": "wildcard", "": "wildcard", None: "wildcard", "::ffff:0.0.0.0": "wildcard",
                 PRIVATE_V4_THREE: "other", DOCUMENTATION_V6: "other", LINK_LOCAL_V6: "other",
                 "0.0.0.0%lo": "wildcard", LOOPBACK_V4_SECOND + "%lo": "loopback", "localhost": "invalid", "1.2.3": "invalid", 7: "invalid"}
        for host, expected in cases.items():
            with self.subTest(host=host):
                self.assertEqual(d.classify_host(host), expected)

    def test_parse_ss(self):
        text = ("LISTEN 0 4096 127.0.0.1:3306 0.0.0.0:*\nLISTEN 0 4096 *:80 *:* users:((\"x\",pid=1,fd=3))\n"
                "LISTEN 0 4096 [::]:3306 [::]:*\n\n")
        self.assertEqual(d.parse_ss(text), [("127.0.0.1", 3306), ("*", 80), ("::", 3306)])
        for bad in ("LISTEN 0 1\n", "LISTEN 0 1 nocolon 0.0.0.0:*\n", f"LISTEN 0 1 {PUBLIC_V4}:99999 0.0.0.0:*\n"):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    d.parse_ss(bad)

    def test_parse_proc_tcp(self):
        v4 = PROC_HEADER + proc_line(0, "0100007F:0CEA", "0A") + proc_line(1, "00000000:0016", "01")
        self.assertEqual(d.parse_proc_tcp(v4, v6=False), [("127.0.0.1", 3306)])
        v6 = PROC_HEADER + proc_line(0, "00000000000000000000000001000000:0CEA", "0A")
        self.assertEqual(d.parse_proc_tcp(v6, v6=True), [("::1", 3306)])
        with self.assertRaises(ValueError):
            d.parse_proc_tcp(PROC_HEADER + "garbage line 0A\n", v6=False)

    def test_parse_port_bindings(self):
        self.assertEqual(d.parse_port_bindings("null"), [])
        self.assertEqual(d.parse_port_bindings('{"3306/tcp":[{"HostIp":"::","HostPort":"1"}]}'), [("3306/tcp", "::")])
        self.assertEqual(d.parse_port_bindings('{"3306/tcp":[{"HostPort":"1"}]}'), [("3306/tcp", None)])


if __name__ == "__main__":
    unittest.main()
