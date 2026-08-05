import pymmary


def test_package_should_expose_a_version() -> None:
    assert isinstance(pymmary.__version__, str)
    assert pymmary.__version__
