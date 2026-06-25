"""Builda o .exe final usando PyInstaller.

Roda assim:
    .\\venv\\Scripts\\python.exe build_exe.py

Saida: dist/Scraping Eventos.exe (1 arquivo, ~120 MB)
"""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# --- pastas que precisam ir junto -------------------------------------------
ADD_DATA = [
    # .env com chave do Gemini
    f"{ROOT / '.env'}{os.pathsep}.",
]

# --- modulos que o PyInstaller nao detecta sozinho --------------------------
HIDDEN_IMPORTS = [
    # scrapers
    "scraping",
    "scraping.mapadosfestivais_navigator",
    "scraping.ticketsports_navigator",
    "scraping.clubinho_scraper",
    "scraping.ingresse_navigator",
    "scraping.visite_navigator",
    "scraping.shotgun_navigator",
    "taxonomia",
    # dependencias indiretas
    "cloudscraper",
    "google.genai",
    "google.auth",
    "markdownify",
    "dotenv",
    "dateutil.relativedelta",
    "selenium.webdriver.chrome.options",
    "selenium.webdriver.edge.options",
    "undetected_chromedriver",
]

# Modulos do undetected-chromedriver precisam de tratamento especial:
# ele tem arquivos .py em paths estranhos. PyInstaller geralmente trata via collect-all.

# --- monta o comando --------------------------------------------------------
def build():
    args = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--windowed",
        "--name", "Scraping Eventos",
        "--paths", str(ROOT / "src"),
    ]
    for h in HIDDEN_IMPORTS:
        args.extend(["--hidden-import", h])
    args.extend(["--collect-all", "undetected_chromedriver"])
    args.extend(["--collect-submodules", "google"])
    for ad in ADD_DATA:
        args.extend(["--add-data", ad])
    args.append(str(ROOT / "src" / "app.py"))

    print("RUN:", " ".join(f'"{a}"' if " " in a else a for a in args))
    subprocess.check_call(args, cwd=str(ROOT))


if __name__ == "__main__":
    build()
    out = ROOT / "dist" / "Scraping Eventos.exe"
    print(f"\n[OK] Gerado: {out}")
    print(f"[OK] Tamanho: {out.stat().st_size / 1024 / 1024:.1f} MB" if out.exists() else "[!!] EXE nao gerado")
