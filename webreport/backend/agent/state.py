import importlib
from typing import Annotated

add_messages = importlib.import_module("langgraph.graph.message").add_messages
TypedDict = importlib.import_module("typing_extensions").TypedDict
message_list = getattr(Annotated, "__class_getitem__")((list, add_messages))

GraphState = TypedDict(
    "GraphState",
    {
        "messages": message_list,
        "report_payload": dict | None,
        "rows_consumed": int,
        "knowledge_bytes_consumed": int,
    },
)
