"""Smoke tests: the module must import cleanly and be a real pipeline
plugin (via OVOSAbstractApplication, which also gives it speak_dialog/
settings/file_system - see module docstring)."""
from conftest import CommonReadingPipeline, ContentFetchError


def test_imports_cleanly():
    assert CommonReadingPipeline is not None
    assert issubclass(ContentFetchError, Exception)


def test_is_a_pipeline_plugin():
    from ovos_plugin_manager.templates.pipeline import PipelinePlugin
    assert issubclass(CommonReadingPipeline, PipelinePlugin)


def test_is_an_ovos_abstract_application():
    from ovos_workshop.app import OVOSAbstractApplication
    assert issubclass(CommonReadingPipeline, OVOSAbstractApplication)
