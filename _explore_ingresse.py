import sys, time
sys.path.insert(0, "src")
from base import SeleniumBase
from logger import LoggerService

logger = LoggerService(log_dir="output/logs")
sb = SeleniumBase(logger)
sb.initialize_driver(headless=True)
try:
    url = "https://www.ingresse.com/search/?location=BRA-RJ&language=pt_br&page=1"
    sb.navigate_to(url)
    time.sleep(8)
    sb.scroll_to_bottom()
    time.sleep(3)
    html = sb.driver.execute_script("return document.documentElement.outerHTML;")
    with open("_dump_ingresse.html", "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Saved: {len(html)} bytes")

    # Find event links
    from selenium.webdriver.common.by import By
    candidates = []
    for sel in ["//a[contains(@href, '/event/')]", "//a[contains(@href, '/eventos/')]",
                "//a[contains(@href, '/e/')]", "//a[contains(@href, '/v/')]",
                "//a[contains(@href, 'ingresse.com')]"]:
        els = sb.driver.find_elements(By.XPATH, sel)
        print(f"{sel}: {len(els)}")
        for e in els[:5]:
            try:
                print("  ", e.get_attribute("href"))
            except: pass

    # Look for headers
    h1 = sb.driver.find_elements(By.TAG_NAME, "h1")
    h2 = sb.driver.find_elements(By.TAG_NAME, "h2")
    print(f"h1 count: {len(h1)}, h2 count: {len(h2)}")
    for h in h1[:3]: print("  H1:", h.text)
    for h in h2[:5]: print("  H2:", h.text)
finally:
    sb.quit_driver()
