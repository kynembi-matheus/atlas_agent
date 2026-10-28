import json
import re
from xml.etree import ElementTree as ET

from fastapi.testclient import TestClient

from api.main import create_app
from core.config import ROOT


def test_all_ui_icons_reference_the_local_lucide_library(settings):
    folder = ROOT / 'frontend/vendor/lucide'
    manifest = json.loads((folder / 'manifest.json').read_text(encoding='utf-8'))
    assert manifest['library'] == 'Lucide'
    assert manifest['version'] == '0.468.0'
    symbols = {symbol.attrib['id'] for symbol in ET.parse(folder / 'sprite.svg').getroot()}
    html = (ROOT / 'frontend/index.html').read_text(encoding='utf-8')
    assert '<path ' not in html
    assert '<symbol ' not in html
    references = re.findall(r'/static/vendor/lucide/sprite.svg\?v=[\d.]+#(icon-[\w-]+)', html)
    assert references and set(references) <= symbols
    assert 'ISC License' in (folder / 'LICENSE').read_text(encoding='utf-8')
    with TestClient(create_app(settings, mcp=object(), client=object())) as client:
        response = client.get('/static/vendor/lucide/sprite.svg?v=0.468.0')
        assert response.status_code == 200
        assert 'image/svg+xml' in response.headers['content-type']
        assert len(ET.fromstring(response.content)) == len(symbols)
        for name in ('loader-circle', 'circle-check', 'circle-alert', 'circle-x', 'clock'):
            assert client.get(f'/static/vendor/lucide/icons/{name}.svg').status_code == 200
