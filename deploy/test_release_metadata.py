"""Cover the release metadata contract that promotion and the deploy executor both rely on.

The module is a parser for a document that arrives from outside the process (a release asset
and a release body), so besides the contract rules these cases feed it hostile input and
require a `MetadataError` that names the offending field instead of any other exception.
"""

import copy
import dataclasses
import json
import os
import sys
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from deploy import release_metadata as rm  # noqa: E402

COMMIT = "0123456789abcdef0123456789abcdef01234567"
DIGEST = "a" * 64
PREFIX_ENV = "BD_RELEASE_IMAGE_PREFIX"
DEFAULT_PREFIX = "ghcr.io/korridzy/bez_durakov_parser"


def valid_dict(prefix: str = DEFAULT_PREFIX) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "repository": "Korridzy/bez_durakov_parser",
        "version": "v1.2.3",
        "source_commit": COMMIT,
        "ci_run_id": 123456789,
        "ci_run_attempt": 1,
        "built_from_candidate_tag": "sha-" + COMMIT,
        "images": {
            "backend": f"{prefix}/backend@sha256:{'1' * 64}",
            "data_collector": f"{prefix}/data-collector@sha256:{'2' * 64}",
            "frontend": f"{prefix}/frontend@sha256:{'3' * 64}",
        },
        "alembic_revision": "b1c2d3e4f5g6",
    }


class ContractTestCase(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict(os.environ)
        patcher.start()
        self.addCleanup(patcher.stop)
        os.environ.pop(PREFIX_ENV, None)

    def assertRejects(self, obj, field):
        with self.assertRaises(rm.MetadataError) as ctx:
            rm.validate(obj)
        self.assertIn(field, str(ctx.exception))


class ConstantsTest(ContractTestCase):
    def test_constants(self):
        self.assertEqual(rm.SCHEMA_VERSION, 1)
        self.assertEqual(rm.ASSET_NAME, "release-metadata.json")
        self.assertEqual(
            rm.IMAGE_REPOSITORIES,
            {
                "backend": "ghcr.io/korridzy/bez_durakov_parser/backend",
                "data_collector": "ghcr.io/korridzy/bez_durakov_parser/data-collector",
                "frontend": "ghcr.io/korridzy/bez_durakov_parser/frontend",
            },
        )


class ValidateTest(ContractTestCase):
    def test_valid_document_is_accepted(self):
        meta = rm.validate(valid_dict())
        self.assertIsInstance(meta, rm.ReleaseMetadata)
        self.assertEqual(meta.version, "v1.2.3")
        self.assertEqual(meta.alembic_revision, "b1c2d3e4f5g6")
        self.assertEqual(meta.images["backend"], valid_dict()["images"]["backend"])

    def test_repository_defaults_when_omitted(self):
        fields = {key: value for key, value in valid_dict().items() if key != "repository"}
        meta = rm.ReleaseMetadata(**fields)
        self.assertEqual(meta.repository, "Korridzy/bez_durakov_parser")
        self.assertEqual(meta, rm.validate(valid_dict()))
        self.assertEqual(rm.loads(rm.dumps(meta)), meta)

    def test_repository_can_be_set_explicitly(self):
        fields = dict(valid_dict(), repository="Other/project")
        self.assertEqual(rm.ReleaseMetadata(**fields).repository, "Other/project")

    def test_ci_numbers_have_an_upper_bound(self):
        limit = 2**63 - 1
        for key in ("ci_run_id", "ci_run_attempt"):
            for value in (limit + 1, 10**30, 10**4299, 10**4300, 10**5000):
                with self.subTest(key=key, digits=len(str(value)) if value < 10**4300 else "huge"):
                    obj = valid_dict()
                    obj[key] = value
                    self.assertRejects(obj, key)
            obj = valid_dict()
            obj[key] = limit
            self.assertEqual(getattr(rm.validate(obj), key), limit)

    def test_metadata_is_frozen(self):
        meta = rm.validate(valid_dict())
        with self.assertRaises(dataclasses.FrozenInstanceError):
            meta.version = "v9.9.9"

    def test_non_object_is_rejected(self):
        for value in (None, [], "x", 1):
            with self.subTest(value=value):
                with self.assertRaises(rm.MetadataError):
                    rm.validate(value)

    def test_wrong_schema_version_is_rejected(self):
        for value in (2, 0, "1", True, 1.0, None):
            with self.subTest(value=value):
                obj = valid_dict()
                obj["schema_version"] = value
                self.assertRejects(obj, "schema_version")

    def test_extra_key_is_rejected(self):
        obj = valid_dict()
        obj["hostname"] = "example"
        self.assertRejects(obj, "hostname")

    def test_missing_key_is_rejected(self):
        for key in valid_dict():
            with self.subTest(key=key):
                obj = valid_dict()
                del obj[key]
                self.assertRejects(obj, key)

    def test_version_must_be_plain_release(self):
        # A version with four components, not an address; built so no dotted quad is spelled in a tracked file.
        four_components = ".".join(["v1", "2", "3", "4"])
        for value in ("v1.0.0-rc1", "1.2.3", "v1.2", "v01.2.3", "v1.2.3\n", "v1.2.3+b1", four_components, "V1.2.3", 1, None):
            with self.subTest(value=value):
                obj = valid_dict()
                obj["version"] = value
                self.assertRejects(obj, "version")

    def test_version_with_zero_components_is_accepted(self):
        for value in ("v0.0.0", "v0.1.0", "v10.20.30"):
            with self.subTest(value=value):
                obj = valid_dict()
                obj["version"] = value
                self.assertEqual(rm.validate(obj).version, value)

    def test_non_ascii_digits_in_version_are_rejected(self):
        obj = valid_dict()
        obj["version"] = "v1.\u0663.0"
        self.assertRejects(obj, "version")

    def test_source_commit_must_be_40_lowercase_hex(self):
        for value in ("abc", COMMIT.upper(), COMMIT + "0", COMMIT[:-1] + "g", COMMIT + "\n", None):
            with self.subTest(value=value):
                obj = valid_dict()
                obj["source_commit"] = value
                obj["built_from_candidate_tag"] = "sha-" + str(value)
                self.assertRejects(obj, "source_commit")

    def test_candidate_tag_mismatch_is_rejected(self):
        for value in ("sha-" + "f" * 40, COMMIT, "sha-" + COMMIT + "\n", "latest", None):
            with self.subTest(value=value):
                obj = valid_dict()
                obj["built_from_candidate_tag"] = value
                self.assertRejects(obj, "built_from_candidate_tag")

    def test_image_component_set_must_match(self):
        obj = valid_dict()
        del obj["images"]["frontend"]
        self.assertRejects(obj, "images")
        obj = valid_dict()
        obj["images"]["litellm"] = obj["images"]["frontend"]
        self.assertRejects(obj, "images")
        obj = valid_dict()
        obj["images"] = ["backend"]
        self.assertRejects(obj, "images")

    def test_image_references_are_checked_per_component(self):
        good = valid_dict()["images"]
        bad_values = {
            "tag instead of digest": good["backend"].split("@")[0] + ":v1.2.3",
            "short digest": good["backend"][:-1],
            "long digest": good["backend"] + "0",
            "uppercase digest": good["backend"].split("@")[0] + "@sha256:" + "A" * 64,
            "trailing newline": good["backend"] + "\n",
            "other registry": "docker.io/library/backend@sha256:" + "1" * 64,
            "other component name": f"{DEFAULT_PREFIX}/frontend@sha256:" + "1" * 64,
            "not a string": 5,
        }
        for label, value in bad_values.items():
            with self.subTest(label=label):
                obj = valid_dict()
                obj["images"]["backend"] = value
                self.assertRejects(obj, "images.backend")

    def test_collector_image_uses_hyphenated_repository(self):
        obj = valid_dict()
        obj["images"]["data_collector"] = f"{DEFAULT_PREFIX}/data_collector@sha256:{'2' * 64}"
        self.assertRejects(obj, "images.data_collector")

    def test_alembic_revision_rules(self):
        for value in ("head", "heads", "base", "HEAD", "", "a" * 33, "abc-def", "abc def", "abc\n", "\u0431", None, 7):
            with self.subTest(value=value):
                obj = valid_dict()
                obj["alembic_revision"] = value
                self.assertRejects(obj, "alembic_revision")
        for value in ("b1c2d3e4f5g6", "a" * 32, "0", "rev_1"):
            with self.subTest(value=value):
                obj = valid_dict()
                obj["alembic_revision"] = value
                self.assertEqual(rm.validate(obj).alembic_revision, value)

    def test_ci_run_numbers_must_be_positive_ints(self):
        for key in ("ci_run_id", "ci_run_attempt"):
            for value in (0, -1, True, 1.5, "7", None):
                with self.subTest(key=key, value=value):
                    obj = valid_dict()
                    obj[key] = value
                    self.assertRejects(obj, key)

    def test_repository_must_be_owner_slash_name(self):
        for value in ("", "noslash", "a/b/c", "a b/c", None, 3):
            with self.subTest(value=value):
                obj = valid_dict()
                obj["repository"] = value
                self.assertRejects(obj, "repository")

    def test_validate_does_not_mutate_its_input(self):
        obj = valid_dict()
        snapshot = copy.deepcopy(obj)
        rm.validate(obj)
        self.assertEqual(obj, snapshot)


class ImagePrefixOverrideTest(ContractTestCase):
    def test_override_accepts_local_registry_references(self):
        os.environ[PREFIX_ENV] = "127.0.0.1:5000/bd"
        obj = valid_dict("127.0.0.1:5000/bd")
        meta = rm.validate(obj)
        self.assertEqual(meta.images["data_collector"], f"127.0.0.1:5000/bd/data-collector@sha256:{'2' * 64}")

    def test_override_rejects_default_prefix(self):
        os.environ[PREFIX_ENV] = "127.0.0.1:5000/bd"
        self.assertRejects(valid_dict(), "images.backend")

    def test_default_prefix_rejects_override_references(self):
        self.assertRejects(valid_dict("127.0.0.1:5000/bd"), "images.backend")

    def test_override_is_read_at_call_time(self):
        obj = valid_dict("127.0.0.1:5000/bd")
        with self.assertRaises(rm.MetadataError):
            rm.validate(obj)
        os.environ[PREFIX_ENV] = "127.0.0.1:5000/bd"
        rm.validate(obj)
        del os.environ[PREFIX_ENV]
        with self.assertRaises(rm.MetadataError):
            rm.validate(obj)

    def test_override_is_not_a_prefix_match(self):
        os.environ[PREFIX_ENV] = "127.0.0.1:5000/bd"
        obj = valid_dict("127.0.0.1:5000/bd")
        obj["images"]["backend"] = f"127.0.0.1:5000/bdx/backend@sha256:{'1' * 64}"
        self.assertRejects(obj, "images.backend")


class LoadsDumpsTest(ContractTestCase):
    def test_round_trip(self):
        meta = rm.validate(valid_dict())
        self.assertEqual(rm.loads(rm.dumps(meta)), meta)

    def test_dumps_is_canonical(self):
        meta = rm.validate(valid_dict())
        data = rm.dumps(meta)
        self.assertIsInstance(data, bytes)
        self.assertTrue(data.endswith(b"}\n"))
        self.assertFalse(data.endswith(b"\n\n"))
        expected = (json.dumps(valid_dict(), sort_keys=True, indent=2) + "\n").encode("utf-8")
        self.assertEqual(data, expected)
        self.assertEqual(rm.dumps(rm.loads(data)), data)

    def test_dumps_never_leaks_another_exception_type(self):
        base = rm.validate(valid_dict())
        huge = [dataclasses.replace(base, ci_run_id=10**5000), dataclasses.replace(base, ci_run_attempt=2**63)]
        for index, meta in enumerate(huge):
            with self.subTest(case=index):
                with self.assertRaises(rm.MetadataError) as ctx:
                    rm.dumps(meta)
                self.assertIn("ci_run", str(ctx.exception))
        for value in (None, {}, valid_dict(), "x"):
            with self.subTest(value=value):
                with self.assertRaises(rm.MetadataError):
                    rm.dumps(value)

    def test_largest_allowed_numbers_round_trip(self):
        meta = dataclasses.replace(rm.validate(valid_dict()), ci_run_id=2**63 - 1, ci_run_attempt=2**63 - 1)
        self.assertEqual(rm.loads(rm.dumps(meta)), meta)

    def test_dumps_rejects_an_invalid_object(self):
        meta = dataclasses.replace(rm.validate(valid_dict()), version="v1.0.0-rc1")
        with self.assertRaises(rm.MetadataError) as ctx:
            rm.dumps(meta)
        self.assertIn("version", str(ctx.exception))

    def test_duplicate_key_is_rejected(self):
        data = b'{"schema_version": 1, "schema_version": 1}'
        with self.assertRaises(rm.MetadataError) as ctx:
            rm.loads(data)
        self.assertIn("schema_version", str(ctx.exception))

    def test_duplicate_key_in_nested_object_is_rejected(self):
        text = json.dumps(valid_dict(), sort_keys=True)
        text = text.replace('"frontend": ', '"backend": "x", "frontend": ', 1)
        with self.assertRaises(rm.MetadataError) as ctx:
            rm.loads(text.encode())
        self.assertIn("backend", str(ctx.exception))

    def test_extra_key_is_rejected_through_loads(self):
        obj = valid_dict()
        obj["extra"] = 1
        with self.assertRaises(rm.MetadataError) as ctx:
            rm.loads(json.dumps(obj).encode())
        self.assertIn("extra", str(ctx.exception))

    def test_wrong_schema_version_names_the_field(self):
        with self.assertRaises(rm.MetadataError) as ctx:
            rm.loads(b'{"schema_version": 2}')
        self.assertIn("schema_version", str(ctx.exception))

    def test_size_limit(self):
        base = rm.dumps(rm.validate(valid_dict()))
        padded = base[:-2] + b" " * (65536 - len(base)) + b"}\n"
        self.assertEqual(len(padded), 65536)
        self.assertEqual(rm.loads(padded), rm.validate(valid_dict()))
        with self.assertRaises(rm.MetadataError) as ctx:
            rm.loads(padded + b" ")
        self.assertIn("65536", str(ctx.exception))

    def test_loads_requires_bytes(self):
        with self.assertRaises(rm.MetadataError):
            rm.loads(json.dumps(valid_dict()))


class HostileInputTest(ContractTestCase):
    """Whatever the bytes are, the only exception that may escape is MetadataError."""

    def assertHostile(self, data, mention=None):
        with self.assertRaises(rm.MetadataError) as ctx:
            rm.loads(data)
        if mention is not None:
            self.assertIn(mention, str(ctx.exception))

    def test_malformed_documents(self):
        valid = rm.dumps(rm.validate(valid_dict()))
        cases = {
            "empty": b"",
            "whitespace only": b"  \n",
            "null": b"null",
            "list": b"[]",
            "string": b'"x"',
            "number": b"1",
            "truncated": valid[:-5],
            "trailing garbage": valid + b"garbage",
            "second document": valid + valid,
            "non utf-8": b"\xff\xfe\x00{",
            "invalid continuation byte": b'{"version": "\xc3\x28"}',
            "utf-8 bom": b"\xef\xbb\xbf" + valid,
            "utf-16 bom": b"\xff\xfe" + valid.decode().encode("utf-16-le"),
            "nul byte": b"{\x00}",
            "single quotes": b"{'schema_version': 1}",
            "trailing comma": b'{"schema_version": 1,}',
        }
        for label, data in cases.items():
            with self.subTest(label=label):
                self.assertHostile(data)

    def test_non_finite_numbers(self):
        for constant in ("NaN", "Infinity", "-Infinity"):
            for key in ("ci_run_id", "ci_run_attempt", "schema_version"):
                with self.subTest(constant=constant, key=key):
                    text = json.dumps(valid_dict()).replace(f'"{key}": ' + str(valid_dict()[key]), f'"{key}": {constant}')
                    self.assertIn(constant, text)
                    self.assertHostile(text.encode(), mention=constant)

    def test_huge_integers(self):
        for key in ("ci_run_id", "ci_run_attempt", "schema_version"):
            for digits in (20, 100, 4400, 60000):
                with self.subTest(key=key, digits=digits):
                    text = json.dumps(valid_dict())
                    old = f'"{key}": {valid_dict()[key]}'
                    self.assertIn(old, text)
                    data = text.replace(old, f'"{key}": ' + "9" * digits).encode()
                    self.assertHostile(data, mention=key if digits < 4300 else None)

    def test_huge_integer_beyond_interpreter_limit_names_the_document(self):
        data = b'{"ci_run_id": ' + b"9" * 6000 + b"}"
        self.assertHostile(data, mention="JSON")

    def test_deep_nesting(self):
        for opener, closer in ((b"[", b"]"), (b'{"a":', b"}")):
            with self.subTest(opener=opener):
                depth = 60000 // len(opener)
                self.assertHostile(opener * depth + closer * depth)
                self.assertHostile(opener * depth)

    def test_nested_values_in_scalar_fields(self):
        for key in ("version", "source_commit", "ci_run_id", "alembic_revision", "repository", "images"):
            for value in ([], {}, [[]], {"a": {"b": 1}}, None):
                with self.subTest(key=key, value=value):
                    obj = valid_dict()
                    obj[key] = value
                    self.assertHostile(json.dumps(obj).encode(), mention=key)

    def test_lone_surrogate_escapes(self):
        for key in ("version", "alembic_revision", "built_from_candidate_tag", "repository"):
            with self.subTest(key=key):
                text = json.dumps(valid_dict()).replace(f'"{key}": "', f'"{key}": "\\ud800')
                self.assertHostile(text.encode(), mention=key)

    def test_bool_and_float_ints_are_not_ints(self):
        text = json.dumps(valid_dict()).replace('"ci_run_attempt": 1', '"ci_run_attempt": true')
        self.assertHostile(text.encode(), mention="ci_run_attempt")
        text = json.dumps(valid_dict()).replace('"ci_run_attempt": 1', '"ci_run_attempt": 1.0')
        self.assertHostile(text.encode(), mention="ci_run_attempt")


class MarkerTest(ContractTestCase):
    def test_sha256_hex(self):
        self.assertEqual(
            rm.sha256_hex(b"abc"),
            "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
        )

    def test_marker_round_trip_inside_a_body(self):
        digest = rm.sha256_hex(b"payload")
        marker = rm.format_marker(digest)
        self.assertEqual(marker, f"<!-- release-metadata.json sha256={digest} -->")
        body = f"Release notes\n\n{marker}\n\nmore text\n"
        self.assertEqual(rm.parse_marker(body), digest)
        self.assertEqual(rm.parse_marker(marker), digest)

    def test_marker_survives_crlf_line_endings(self):
        digest = rm.sha256_hex(b"payload")
        body = f"notes\r\n\r\n{rm.format_marker(digest)}\r\n\r\nmore\r\n"
        self.assertEqual(rm.parse_marker(body), digest)

    def test_format_marker_rejects_a_bad_digest(self):
        for value in ("", "abc", "A" * 64, "g" * 64, "a" * 63, "a" * 65, "a" * 64 + "\n", None):
            with self.subTest(value=value):
                with self.assertRaises(rm.MetadataError) as ctx:
                    rm.format_marker(value)
                self.assertIn("digest", str(ctx.exception))

    def test_zero_markers_raise(self):
        for body in ("", "no marker here", "<!-- release-metadata.json sha256=abc -->", "x" * 100000):
            with self.subTest(body=body[:30]):
                with self.assertRaises(rm.MetadataError) as ctx:
                    rm.parse_marker(body)
                self.assertIn("marker", str(ctx.exception))

    def test_two_markers_raise_even_when_identical(self):
        marker = rm.format_marker(rm.sha256_hex(b"one"))
        other = rm.format_marker(rm.sha256_hex(b"two"))
        for body in (f"{marker}\n{other}\n", f"{marker}\n{marker}\n"):
            with self.subTest(body=body[:20]):
                with self.assertRaises(rm.MetadataError) as ctx:
                    rm.parse_marker(body)
                self.assertIn("marker", str(ctx.exception))

    def test_marker_must_own_its_line(self):
        marker = rm.format_marker(rm.sha256_hex(b"one"))
        for body in (f"text {marker}", f"{marker} text", f"  {marker}"):
            with self.subTest(body=body):
                with self.assertRaises(rm.MetadataError):
                    rm.parse_marker(body)

    def test_parse_marker_requires_text(self):
        with self.assertRaises(rm.MetadataError):
            rm.parse_marker(None)


if __name__ == "__main__":
    unittest.main()
