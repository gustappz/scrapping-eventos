"""SeleniumBase wrapper. Used for sites that need a real browser (JS-rendered)."""
import os
import random
import time
import uuid
from pathlib import Path
from typing import Optional

import os
import shutil

import requests
from selenium import webdriver
from selenium.common.exceptions import NoSuchElementException, TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from logger import LoggerService


def _detect_browser():
    """Devolve ('chrome', path) ou ('edge', path). Prefere Chrome se existir, senao Edge."""
    chrome_candidates = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expanduser(r"~\AppData\Local\Google\Chrome\Application\chrome.exe"),
    ]
    for c in chrome_candidates:
        if os.path.exists(c):
            return ("chrome", c)
    edge_candidates = [
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    ]
    for c in edge_candidates:
        if os.path.exists(c):
            return ("edge", c)
    # last resort: Chrome on PATH
    chrome_on_path = shutil.which("chrome")
    if chrome_on_path:
        return ("chrome", chrome_on_path)
    return (None, None)

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
]


class SeleniumBase:
    def __init__(self, logger_instance: LoggerService):
        self.driver: Optional[webdriver.Chrome] = None
        self.logger_service = logger_instance
        self.downloads_folder = os.path.join(os.getcwd(), "downloads_selenium")
        Path(self.downloads_folder).mkdir(parents=True, exist_ok=True)
        self.logger_service.debug("SeleniumBase initialized.")

    def initialize_driver(self, headless: bool = False, stealth: bool = False):
        """`stealth=True` usa undetected-chromedriver (precisa de Chrome) — necessario
        pra passar Cloudflare em sites como visitrio.com.br."""
        if stealth:
            import undetected_chromedriver as uc
            opts = uc.ChromeOptions()
            if headless:
                opts.add_argument("--headless=new")
            opts.add_argument("--window-size=1920,1080")
            opts.add_argument("--disable-blink-features=AutomationControlled")
            opts.add_argument(f"--user-agent={random.choice(USER_AGENTS)}")
            self.driver = uc.Chrome(options=opts, use_subprocess=True)
            self.logger_service.debug("WebDriver (chrome stealth) initialized.")
            return

        kind, binary = _detect_browser()
        if kind is None:
            raise RuntimeError(
                "Nenhum navegador (Chrome ou Edge) encontrado. "
                "Instale Google Chrome ou use Microsoft Edge."
            )

        # Selenium 4 tem Selenium Manager built-in: ele baixa o driver certo automaticamente.
        if kind == "chrome":
            from selenium.webdriver.chrome.options import Options as ChromeOptions

            options = ChromeOptions()
            DriverCls = webdriver.Chrome
        else:
            from selenium.webdriver.edge.options import Options as EdgeOptions

            options = EdgeOptions()
            DriverCls = webdriver.Edge
        service = None

        if headless:
            options.add_argument("--headless=new")
        options.add_argument("--disable-gpu")
        options.add_argument("--window-size=1920,1080")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--start-maximized")
        options.add_experimental_option("excludeSwitches", ["enable-logging", "enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)
        options.add_argument(f"user-agent={random.choice(USER_AGENTS)}")

        if service is not None:
            self.driver = DriverCls(service=service, options=options)
        else:
            self.driver = DriverCls(options=options)
        try:
            self.driver.execute_cdp_cmd(
                "Page.addScriptToEvaluateOnNewDocument",
                {"source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"},
            )
        except Exception:
            pass
        self.logger_service.debug(f"WebDriver ({kind}) initialized with success.")

    def quit_driver(self):
        try:
            if self.driver:
                self.driver.quit()
                self.driver = None
            self.logger_service.debug("WebDriver closed.")
        except Exception as e:
            self.logger_service.error(f"Error quitting driver: {e}")

    def navigate_to(self, url: str):
        if not self.driver:
            self.logger_service.error("Driver not initialized. Call 'initialize_driver' first.")
            return
        self.driver.get(url)
        self.logger_service.debug(f"Navigate to {url}")

    def wait_for_element(self, by_type, locator, timeout: int = 15):
        wait = WebDriverWait(self.driver, timeout)
        element = wait.until(EC.presence_of_element_located((by_type, locator)))
        self.logger_service.debug(f"Element '{locator}' found after waiting.")
        return element

    def find_element(self, by_type, locator):
        try:
            el = self.driver.find_element(by_type, locator)
            self.logger_service.debug(f"Element '{locator}' found.")
            return el
        except NoSuchElementException:
            return None

    def find_elements(self, by_type, locator):
        els = self.driver.find_elements(by_type, locator)
        self.logger_service.debug(f"{len(els)} elements '{locator}' found.")
        return els

    def click_element(self, by_type, locator, timeout: int = 10):
        el = self.wait_for_element(by_type, locator, timeout)
        try:
            el.click()
        except Exception:
            self.driver.execute_script("arguments[0].click();", el)
        self.logger_service.debug(f"Clicked on element: {locator}")

    def wait_random_period_of_time(self, min_seconds: float = 1.0, max_seconds: float = 3.0):
        time.sleep(random.uniform(min_seconds, max_seconds))

    def scroll_to_bottom(self):
        self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        self.wait_random_period_of_time(0.5, 1.5)

    def scroll_to_top(self):
        self.driver.execute_script("window.scrollTo(0, 0);")
        self.wait_random_period_of_time(0.5, 1.0)

    def human_like_behavior(self, scroll_times: int = 3):
        for _ in range(scroll_times):
            h = self.driver.execute_script("return document.body.scrollHeight")
            target = random.randint(int(h * 0.3), int(h * 0.9))
            self.driver.execute_script(f"window.scrollTo(0, {target});")
            time.sleep(random.uniform(0.4, 1.2))

    def scroll_to_element(self, element, factor: float = 0.8):
        try:
            y = element.location["y"]
            self.driver.execute_script(f"window.scrollTo(0, {int(y * factor)});")
            self.logger_service.debug("Scroll the page to element position.")
        except Exception:
            pass

    def download_file_from_url(self, url: str) -> str:
        self.logger_service.debug(f"Download file of: {url}")
        from utils import download_file
        path = download_file(self.downloads_folder, url)
        self.logger_service.debug(f"File saved on: {os.path.basename(path) if path else 'FAILED'}")
        return path
