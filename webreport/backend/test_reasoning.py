import importlib
import sys
import unittest

sys.path.insert(0, "/")

filter_cases = importlib.import_module("test_reasoning_filter")
seam_cases = importlib.import_module("test_reasoning_seam")
partial_cases = importlib.import_module("test_reasoning_partial")
api_cases = importlib.import_module("test_reasoning_api")
span_cases = importlib.import_module("test_reasoning_span")
net_guard = importlib.import_module("test_net_guard")


def setUpModule() -> None:
    net_guard.install()


class TestExtractText(filter_cases.TestExtractText):
    pass


class TestExtractReasoning(filter_cases.TestExtractReasoning):
    pass


class TestOutboundReasoningFilter(filter_cases.TestOutboundReasoningFilter):
    pass


class TestEchoTripwire(seam_cases.TestEchoTripwire):
    pass


class TestNoReasoningNoOp(seam_cases.TestNoReasoningNoOp):
    pass


class TestReasoningPropagation(partial_cases.TestReasoningPropagation):
    pass


class TestFailurePartialReasoning(partial_cases.TestFailurePartialReasoning):
    pass


class TestHistoryEntries(api_cases.TestHistoryEntries):
    pass


class TestChatResponseShape(api_cases.TestChatResponseShape):
    pass


class TestChatEndpointReasoning(api_cases.TestChatEndpointReasoning):
    pass


class TestHistoryEndpointWiring(api_cases.TestHistoryEndpointWiring):
    pass


class TestCurrentTurnSpan(span_cases.TestCurrentTurnSpan):
    pass


class TestCheckpointSerialization(span_cases.TestCheckpointSerialization):
    pass


if __name__ == "__main__":
    unittest.main()
