import pytest

import app as launcher


@pytest.mark.parametrize('flags,development,reload', [
    ([], False, False),
    (['--reload'], False, True),
    (['--development'], True, False),
    (['--development', '--reload'], True, True),
])
def test_launcher_passes_explicit_development_flag(monkeypatch, flags, development, reload):
    calls = []
    monkeypatch.setattr('sys.argv', ['app.py', *flags])
    monkeypatch.setattr(launcher.uvicorn, 'run', lambda *args, **kwargs: calls.append((args, kwargs)))
    launcher.main()
    args, kwargs = calls[0]
    assert args == (('api.main:create_development_app' if development else 'api.main:app'),)
    assert kwargs.get('factory', False) is development
    assert kwargs['reload'] is reload


def test_development_factory_enables_runtime_flag(monkeypatch):
    import api.main as api_main

    calls = []
    sentinel = object()

    def create_app(**kwargs):
        calls.append(kwargs)
        return sentinel

    monkeypatch.setattr(api_main, 'create_app', create_app)
    assert api_main.create_development_app() is sentinel
    assert calls == [{'development': True}]
