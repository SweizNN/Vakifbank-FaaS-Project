import pytest
from pipeline import sse_event

def test_sse_event_formatting():
    event = sse_event("step", "Starting deploy")
    assert event == "event: step\ndata: Starting deploy\n\n"

def test_sse_event_newline_replacement():
    event = sse_event("log", "Line 1\nLine 2")
    assert event == "event: log\ndata: Line 1↵Line 2\n\n"
