"""UI-FINAL shared design rules; static checks also run under verify."""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / 'src/neumann/webui'


def test_css_colors_are_only_tokens():
    html = (WEB / 'index.html').read_text(encoding='utf-8')
    styles = '\n'.join(re.findall(r'<style[^>]*>(.*?)</style>', html, re.S))
    styles += (WEB / 'wait.css').read_text(encoding='utf-8')
    outside = re.sub(r':root\s*\{.*?\}', '', styles, flags=re.S)
    assert not re.findall(r'#[0-9a-fA-F]{3,8}\b|rgba?\([^)]*\)|hsla?\([^)]*\)', outside)
    assert '--accent: #2F54EB' in styles and '--mark: #FFF3BF' in styles


def test_font_sizes_and_faces():
    html = (WEB / 'index.html').read_text(encoding='utf-8')
    css = html + (WEB / 'wait.css').read_text(encoding='utf-8')
    sizes = set(re.findall(r'font-size:\s*([\d.]+)px', css))
    assert sizes == {'14', '16', '20', '28'}
    assert set(re.findall(r'@font-face\s*\{\s*font-family:\s*"([^"]+)"', html)) == {'Pretendard'}
    assert '--sans: Pretendard, sans-serif;' in html


def test_mock_has_only_announced_tools():
    from tests.e4.fin_mock_data import build_fin_mock
    data = build_fin_mock()
    tools = {x['tool'] for x in data['trace'] if x['stage'] != 'correct'}
    assert tools == {'z3', 'pint', 'networkx', 'records'}
    assert not re.search('[①-⑳]', str(data))
