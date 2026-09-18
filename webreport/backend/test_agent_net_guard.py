"""Egress-guard derivation cases for host-less and hosted database URLs.

The acceptance lane runs under a SQLite URL, which carries no remote host at all. The
guard used to raise at import for that shape, which would have taken down every module
that installs it before a single assertion ran.

Aggregated into test_agent, which is the public path the plan's acceptance commands use.
"""

import importlib
import socket
import unittest
from unittest.mock import patch


class NetGuardDerivationTests(unittest.TestCase):
    """Reload the guard under a patched URL and read back what it permits."""

    def setUp(self):
        self.config = importlib.import_module("bd_shared.config")
        self.guard = importlib.import_module("test_net_guard")
        # Captured at the guard's own import, before any install(), so these are the real
        # socket methods even when this suite runs with the guard already armed.
        self._real_connect = self.guard._original_connect
        self._real_connect_ex = self.guard._original_connect_ex
        self.addCleanup(self._restore_guard)

    def _unarm(self):
        socket.socket.connect = self._real_connect
        socket.socket.connect_ex = self._real_connect_ex

    def _restore_guard(self):
        """Leave the process exactly as armed as it was, over the real config."""
        self._unarm()
        importlib.reload(self.guard)
        self.guard.install()

    def _reload_under(self, url):
        # Unarm first, so the reload captures the real socket methods rather than wrapping
        # the guard around itself.
        self._unarm()
        with patch.object(self.config, "DATABASE_URL", url):
            return importlib.reload(self.guard)

    def test_a_host_less_url_imports_and_allows_only_loopback(self):
        """Given a SQLite URL, When the guard loads, Then it imports with no host to allow."""
        guard = self._reload_under("sqlite:///x.db")

        self.assertIsNone(guard.DATABASE_HOST)
        self.assertTrue(guard._is_allowed(socket.AF_INET, ("127.0.0.1", 8000)))
        self.assertTrue(guard._is_allowed(socket.AF_INET6, ("::1", 8000)))
        self.assertFalse(guard._is_allowed(socket.AF_INET, ("10.1.2.3", 5432)))
        self.assertFalse(guard._is_allowed(socket.AF_INET, ("mysql", 3306)))

    def test_a_host_less_url_refusal_explains_why_nothing_remote_is_allowed(self):
        """Given a SQLite URL, When a remote connection is refused, Then the message says why."""
        guard = self._reload_under("sqlite:///x.db")
        blocked = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.addCleanup(blocked.close)

        with self.assertRaises(guard.BlockedEgressError) as caught:
            guard._require_allowed(blocked, ("10.1.2.3", 5432))

        self.assertIn("carries no host", str(caught.exception))

    def test_a_server_url_still_allows_its_own_host(self):
        """Given a server URL, When the guard loads, Then that host is the one allowed."""
        guard = self._reload_under(
            "postgresql+psycopg://fixture:fixture@postgres_test:5432/fixture"
        )

        self.assertEqual(guard.DATABASE_HOST, "postgres_test")
        self.assertTrue(guard._is_allowed(socket.AF_INET, ("postgres_test", 5432)))
        self.assertTrue(guard._is_allowed(socket.AF_INET, ("127.0.0.1", 8000)))
        self.assertFalse(guard._is_allowed(socket.AF_INET, ("api.openai.com", 443)))

    def test_the_mysql_url_keeps_the_compose_service_host(self):
        """Given the shipped MySQL URL, When the guard loads, Then the Compose host is allowed."""
        guard = self._reload_under("mysql+pymysql://durak:devpass@mysql:3306/bez_durakov")

        self.assertEqual(guard.DATABASE_HOST, "mysql")
        self.assertTrue(guard._is_allowed(socket.AF_INET, ("mysql", 3306)))


if __name__ == "__main__":
    unittest.main()
