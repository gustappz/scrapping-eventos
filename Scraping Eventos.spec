# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_submodules
from PyInstaller.utils.hooks import collect_all

datas = [('C:\\Users\\gzite\\Desktop\\scrapping nathy\\.env', '.')]
binaries = []
hiddenimports = ['scraping', 'scraping.mapadosfestivais_navigator', 'scraping.ticketsports_navigator', 'scraping.clubinho_scraper', 'scraping.ingresse_navigator', 'scraping.visite_navigator', 'scraping.shotgun_navigator', 'taxonomia', 'cloudscraper', 'google.genai', 'google.auth', 'markdownify', 'dotenv', 'dateutil.relativedelta', 'selenium.webdriver.chrome.options', 'selenium.webdriver.edge.options', 'undetected_chromedriver']
hiddenimports += collect_submodules('google')
tmp_ret = collect_all('undetected_chromedriver')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['C:\\Users\\gzite\\Desktop\\scrapping nathy\\src\\app.py'],
    pathex=['C:\\Users\\gzite\\Desktop\\scrapping nathy\\src'],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='Scraping Eventos',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
