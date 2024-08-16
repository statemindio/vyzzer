import pytest

from func_tracker import FuncTracker
from config import MAX_FUNCTIONS

from proto_loader import import_proto
proto = import_proto()

@pytest.fixture
def func_tracker():
    return FuncTracker(MAX_FUNCTIONS)


def test_func_tracker_register(func_tracker):
    name = "test0"
    mutability = proto.Func.Mutability.PURE
    visibility = proto.Func.Visibility.EXTERNAL
    input_parameters = []
    output_parameters = []
    func_tracker._register_function(name, mutability, visibility, input_parameters, output_parameters)

    expected_name = f"self.{name}"

    assert func_tracker.current_id == 0
    assert func_tracker[0].name == expected_name
    assert func_tracker[0].mutability == 0
    assert func_tracker[0].render_call(()) == f"{expected_name}()"
    assert func_tracker[0].render_signature(()) == f"def {name}()"
