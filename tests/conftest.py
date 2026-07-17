import pytest

from easyvista_python_client.config import EasyvistaConfig


@pytest.fixture
def config():
    return EasyvistaConfig(server="https://ev.test", account="acme", token="tok")
