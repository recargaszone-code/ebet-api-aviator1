import os
import time
import threading
import re
import requests
from flask import Flask, jsonify

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from webdriver_manager.chrome import ChromeDriverManager

app = Flask(__name__)

# ================= CONFIG =================

TELEGRAM_TOKEN = "8742776802:AAHSzD1qTwCqMEOdoW9_pT2l5GfmMBWUZQY"
TELEGRAM_CHAT_ID = "7427648935"

PHONE = "857789345"
PASSWORD = "max123ZICO"

URL = "https://ebet.co.mz/games/go/spribe?id=aviator"

historico = []

# ================= TELEGRAM =================


def enviar_telegram(msg):

    try:

        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            data={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": msg,
                "parse_mode": "Markdown"
            },
            timeout=15
        )

    except:
        pass


# ================= AVIATOR =================


def clicar_aviator(driver, wait):

    imgs = wait.until(
        EC.presence_of_all_elements_located(
            (By.CSS_SELECTOR, "img.landing-page__item-image")
        )
    )

    for img in imgs:

        src = img.get_attribute("src")

        if src and "aviator" in src.lower():

            driver.execute_script(
                "arguments[0].click();", img
            )

            return True

    return False


# ================= SCRAPER =================


def iniciar_scraper():

    global historico

    while True:

        driver = None

        try:

            enviar_telegram("🟢 Iniciando TXUNA BET Aviator...")

            chrome_options = Options()

            chrome_options.add_argument("--headless=new")
            chrome_options.add_argument("--no-sandbox")
            chrome_options.add_argument("--disable-dev-shm-usage")
            chrome_options.add_argument("--disable-gpu")

            chrome_options.add_argument("--window-size=1366,768")

            service = Service(
                ChromeDriverManager().install()
            )

            driver = webdriver.Chrome(
                service=service,
                options=chrome_options
            )

            wait = WebDriverWait(driver, 60)

            # ================= SITE =================

            driver.get(URL)

            time.sleep(6)

            # ================= AVIATOR =================

            clicar_aviator(driver, wait)

            time.sleep(4)

            # ================= LOGIN =================

            phone = wait.until(
                EC.presence_of_element_located(
                    (By.ID, "phone-input")
                )
            )

            phone.clear()
            phone.send_keys(PHONE)

            password = driver.find_element(
                By.ID, "password-input"
            )

            password.clear()
            password.send_keys(PASSWORD)

            login_btn = driver.find_element(
                By.CSS_SELECTOR,
                "input.btn-session"
            )

            driver.execute_script(
                "arguments[0].click();", login_btn
            )

            time.sleep(8)

            # ================= ABRIR JOGO =================

            clicar_aviator(driver, wait)

            time.sleep(8)

            # ================= NOVA ABA =================

            abas = driver.window_handles

            if len(abas) > 1:

                driver.switch_to.window(abas[-1])

            # ================= IFRAME EXTERNO =================

            iframe1 = wait.until(
                EC.presence_of_element_located(
                    (By.CSS_SELECTOR, "iframe[src*='spribe']")
                )
            )

            driver.switch_to.frame(iframe1)

            time.sleep(4)

            # ================= IFRAME SPRIBE =================

            iframe2 = wait.until(
                EC.presence_of_element_located(
                    (By.CSS_SELECTOR, "iframe[src*='spribegaming']")
                )
            )

            driver.switch_to.frame(iframe2)

            time.sleep(10)

            # ================= ESPERAR HISTÓRICO =================

            wait.until(
                EC.presence_of_element_located(
                    (By.CSS_SELECTOR, "div.payout")
                )
            )

            enviar_telegram("🚀 Aviator conectado!")

            # ================= LOOP =================

            while True:

                elements = driver.find_elements(
                    By.CSS_SELECTOR,
                    "div.payout"
                )

                novos = []

                for el in elements:

                    txt = el.text.strip()

                    match = re.search(
                        r"(\d+\.?\d*)",
                        txt
                    )

                    if match:

                        novos.append(
                            float(match.group(1))
                        )

                if novos and novos != historico:

                    historico = novos

                    lista = ", ".join(
                        f"{v:.2f}x"
                        for v in historico[:20]
                    )

                    enviar_telegram(
                        f"""📊 *TXUNA BET AVIATOR*

[{lista}]

Último: *{historico[0]:.2f}x*"""
                    )

                time.sleep(6)

        except Exception as e:

            enviar_telegram(
                f"🔥 ERRO: {type(e).__name__}"
            )

            time.sleep(15)

        finally:

            try:

                if driver:
                    driver.quit()

            except:
                pass


# ================= API =================


@app.route("/api/history")
def api_history():

    return jsonify(historico)


@app.route("/api/last")
def api_last():

    if historico:

        return jsonify(historico[0])

    return jsonify(None)


@app.route("/")
def home():

    return "TXUNA BET AVIATOR BOT ONLINE"


# ================= START =================


if __name__ == "__main__":

    threading.Thread(
        target=iniciar_scraper,
        daemon=True
    ).start()

    port = int(os.environ.get("PORT", 10000))

    app.run(
        host="0.0.0.0",
        port=port
    )
