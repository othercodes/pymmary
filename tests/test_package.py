import pytest

import pymmary


def test_package_should_expose_a_version() -> None:
    assert isinstance(pymmary.__version__, str)
    assert pymmary.__version__


@pytest.mark.parametrize("name", pymmary.__all__)
def test_package_should_export_every_name_it_advertises(name: str) -> None:
    assert hasattr(pymmary, name)


def test_package_should_keep_its_exports_sorted() -> None:
    assert pymmary.__all__ == sorted(pymmary.__all__)
