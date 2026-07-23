from importlib.metadata import version


def test_online_flash_dependencies_are_importable():
    import intelhex
    import pyocd
    import cmsis_pack_manager

    assert intelhex is not None
    assert pyocd.__version__ == version("pyocd")
    assert cmsis_pack_manager.Cache is not None
