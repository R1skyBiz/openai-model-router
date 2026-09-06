from model_router import __version__


def test_package_imports_without_api_key() -> None:
    assert __version__ == "0.1.0"
