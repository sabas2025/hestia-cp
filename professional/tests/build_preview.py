#!/usr/bin/env python3
"""Render the real PHP view with explicit illustrative fixtures into a standalone preview."""
import os
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[2]
php = os.environ.get('PHP_BINARY') or shutil.which('php')
if not php: raise SystemExit('PHP required')
html = subprocess.check_output([php, '-n', str(ROOT / 'professional/tests/render_preview.php')], text=True)
html = html.replace('<link rel="stylesheet" href="/professional/dashboard.css">', '<style>' + (ROOT / 'web/professional/dashboard.css').read_text() + '</style>')
html = html.replace('<script src="/professional/dashboard.js" defer></script>', '')
html = html.replace('</body>', '<script>' + (ROOT / 'web/professional/dashboard.js').read_text() + '</script></body>')
html = html.replace('Consulta atualizada', 'Prévia com dados ilustrativos').replace('Central profissional 1.1 · HestiaCP', 'Prévia 1.1 · Nenhum servidor conectado')
(ROOT / 'professional/preview.html').write_text(html)
print('Standalone preview generated from the PHP template; illustrative data only')
