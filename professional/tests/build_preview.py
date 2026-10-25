#!/usr/bin/env python3
"""Render the real PHP view with explicit illustrative fixtures into a standalone preview."""
import os
import re
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
html = html.replace('Consulta atualizada', 'Prévia com dados ilustrativos')
html = re.sub(r'Central profissional [0-9.]+ · HestiaCP', 'Prévia · Nenhum servidor conectado', html)
(ROOT / 'professional/preview.html').write_text(html)
mfa = subprocess.check_output([php, '-n', str(ROOT / 'professional/tests/render_twofactor_preview.php')], text=True)
mfa = mfa.replace('<link rel="stylesheet" href="/professional/dashboard.css">', '<style>' + (ROOT / 'web/professional/dashboard.css').read_text() + '</style>')
mfa = mfa.replace('<main class="pro-main">', '<main class="pro-main"><p class="pro-banner">Prévia ilustrativa · Nenhum servidor conectado · A2F não ativada</p>')
(ROOT / 'professional/twofactor-preview.html').write_text(mfa)
print('Standalone preview generated from the PHP template; illustrative data only')
business = subprocess.check_output([php, '-n', str(ROOT / 'professional/tests/render_business_preview.php')], text=True)
business = business.replace('<link rel="stylesheet" href="/professional/dashboard.css">', '<style>' + (ROOT / 'web/professional/dashboard.css').read_text() + '</style>')
business = business.replace('<script src="/professional/business.js" defer></script>', '')
business = business.replace('</body>', '<script>' + (ROOT / 'web/professional/business.js').read_text() + '</script></body>')
business = business.replace('<h1>Operações do servidor</h1>', '<h1>Operações do servidor</h1><p class="pro-banner">Prévia ilustrativa · Nenhum servidor conectado · Nenhuma alteração aplicada</p>')
(ROOT / 'professional/business-preview.html').write_text(business)
