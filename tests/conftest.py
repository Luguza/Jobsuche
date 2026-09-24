import pytest

from jobmap.config import load_config


@pytest.fixture
def cfg():
    return load_config()
