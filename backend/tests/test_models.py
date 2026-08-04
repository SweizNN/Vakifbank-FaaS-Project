import pytest
from pydantic import ValidationError

from models import DeployRequest

def test_deploy_request_valid():
    req = DeployRequest(
        name="my-func",
        language="python",
        code="def main(): return 'hello'",
        is_update=False
    )
    assert req.name == "my-func"
    assert req.language == "python"

def test_deploy_request_invalid_name():
    with pytest.raises(ValidationError) as exc:
        DeployRequest(
            name="Invalid_Name!",
            language="python",
            code="def main(): return 'hello'"
        )
    assert "Function name must start with a lowercase letter" in str(exc.value)

def test_deploy_request_invalid_language():
    with pytest.raises(ValidationError) as exc:
        DeployRequest(
            name="my-func",
            language="ruby", # assuming ruby is not in SUPPORTED_LANGUAGES based on config.py typically
            code="def main(): return 'hello'"
        )
    assert "Unsupported language" in str(exc.value)
