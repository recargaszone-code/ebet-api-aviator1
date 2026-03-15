# main.py - EBET Aviator com proteção contra rate-limit + HISTÓRICO ACUMULADO ATÉ 50
import os
import time
import threading
import re
import random
import traceback
import requests
from flask import Flask, jsonify
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.common.exceptions import (
    TimeoutException,
    StaleElementReferenceException,
    NoSuchElementException,
    WebDriverException,
)
from selenium.webdriver.support.ui import WebDriverWait

app = Flask(__name__)

# ================= CONFIG (hardcoded) =================
TELEGRAM_TOKEN = "8742776802:AAHSzD1qTwCqMEOdoW9_pT2l5GfmMBWUZQY"
TELEGRAM_CHAT_ID = "7427648935"
PHONE = "857789345"
PASSWORD = "max123ZICO"
URL = "https://ebet.co.mz/games/go/spribe?id=aviator"
# ====================================================

historico = []           # snapshot atual (para detectar mudança)
global_history = []      # acumula os últimos 50 (novo no topo, remove o mais antigo)
_last_telegram = 0


def send_telegram_text(msg, throttle_seconds=6):
    global _last_telegram
    now = time.time()
    if now - _last_telegram < throttle_seconds:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            data={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "Markdown"},
            timeout=15,
        )
        _last_telegram = now
    except Exception:
        pass


def send_telegram_photo(path, caption="", throttle_seconds=30):
    global _last_telegram
    now = time.time()
    if now - _last_telegram < throttle_seconds:
        return
    try:
        with open(path, "rb") as f:
            requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto",
                files={"photo": f},
                data={"chat_id": TELEGRAM_CHAT_ID, "caption": caption},
                timeout=30,
            )
        _last_telegram = now
    except Exception:
        pass


def screenshot_and_send(driver, label, path="/tmp/print.png"):
    try:
        driver.save_screenshot(path)
        send_telegram_photo(path, caption=label)
    except Exception:
        pass


def safe_find_elements(driver, selector, max_retries=4, sleep_between=0.3):
    for attempt in range(max_retries):
        try:
            elems = driver.find_elements(By.CSS_SELECTOR, selector)
            return elems
        except StaleElementReferenceException:
            time.sleep(sleep_between)
            continue
        except Exception:
            time.sleep(sleep_between)
    return []


def click_aviator_if_found(driver):
    imgs = safe_find_elements(driver, "img.landing-page__item-image")
    for img in imgs:
        try:
            src = (img.get_attribute("src") or "").lower()
            alt = (img.get_attribute("alt") or "").lower()
            if "aviator" in src or "aviator" in alt:
                driver.execute_script("arguments[0].click();", img)
                return True
        except:
            continue
    return False


def coletar_historico_dom(driver):
    items = safe_find_elements(driver, "div.payouts-block div.payout")
    vals = []
    for el in items:
        try:
            txt = el.text.strip()
            m = re.search(r"(\d+(\.\d+)?)", txt)
            if m:
                vals.append(float(m.group(1)))
        except:
            continue
    return vals


def page_shows_rate_limit(driver):
    try:
        body = driver.page_source.lower()
        checks = ["rate limit", "too many requests", "429", "rate-limited", "try again later"]
        return any(token in body for token in checks)
    except:
        return False


def iniciar_scraper():
    global historico, global_history
    base_backoff = 8
    max_backoff = 600
    backoff = base_backoff

    while True:
        driver = None
        falhas_consecutivas = 0
        MAX_FALHAS = 6

        try:
            send_telegram_text("🟢 Iniciando EBET Aviator (histórico 50 + anti-rate-limit reforçado)...")

            chrome_options = Options()
            chrome_options.add_argument("--headless=new")
            chrome_options.add_argument("--no-sandbox")
            chrome_options.add_argument("--disable-dev-shm-usage")
            chrome_options.add_argument("--disable-gpu")
            chrome_options.add_argument("--window-size=1366,768")
            chrome_options.add_argument(
                "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36"
            )

            if os.path.exists("/usr/bin/chromium"):
                chrome_options.binary_location = "/usr/bin/chromium"
            service = Service("/usr/bin/chromedriver") if os.path.exists("/usr/bin/chromedriver") else Service()

            driver = webdriver.Chrome(service=service, options=chrome_options)
            wait = WebDriverWait(driver, 30)

            driver.get(URL)
            time.sleep(8)
            screenshot_and_send(driver, "Página inicial aberta")

            click_aviator_if_found(driver)
            time.sleep(3)

            # Login
            try:
                phone = driver.find_element(By.ID, "phone-input")
                phone.clear()
                phone.send_keys(PHONE)
                password = driver.find_element(By.ID, "password-input")
                password.clear()
                password.send_keys(PASSWORD)
                btn = driver.find_element(By.CSS_SELECTOR, "input.btn-session")
                driver.execute_script("arguments[0].click();", btn)
                screenshot_and_send(driver, "Login enviado")
            except NoSuchElementException:
                pass
            except StaleElementReferenceException:
                time.sleep(3)

            time.sleep(8)
            click_aviator_if_found(driver)
            time.sleep(5)

            # Trocar aba se necessário
            handles = driver.window_handles
            if len(handles) > 1:
                driver.switch_to.window(handles[-1])

            # Iframes
            iframe1 = None
            for f in driver.find_elements(By.TAG_NAME, "iframe"):
                src = (f.get_attribute("src") or "").lower()
                if "spribe" in src and "launch" not in src:
                    iframe1 = f
                    break
            if iframe1:
                driver.switch_to.frame(iframe1)
                time.sleep(3)

            iframe2 = None
            for f in driver.find_elements(By.TAG_NAME, "iframe"):
                src = (f.get_attribute("src") or "").lower()
                if "spribegaming" in src or "launch.spribegaming" in src:
                    iframe2 = f
                    break
            if iframe2:
                driver.switch_to.frame(iframe2)
                time.sleep(4)

            # Aguarda payouts
            total_wait_start = time.time()
            while True:
                if page_shows_rate_limit(driver):
                    falhas_consecutivas += 1
                    sleep_time = min(max_backoff, backoff) + random.uniform(5, 15)
                    send_telegram_text(f"⚠️ Rate limit detectado ({falhas_consecutivas}/{MAX_FALHAS}) — dormindo {int(sleep_time)}s")
                    time.sleep(sleep_time)
                    backoff = min(max_backoff, backoff * 1.6)

                    if falhas_consecutivas >= MAX_FALHAS:
                        raise RuntimeError("Rate limit persistente após várias tentativas")

                    try:
                        driver.switch_to.default_content()
                    except:
                        pass
                    continue

                payouts = safe_find_elements(driver, "div.payouts-block div.payout")
                if payouts and len(payouts) > 0:
                    break

                if time.time() - total_wait_start > 120:
                    send_telegram_text("⚠️ Ainda sem payouts após 120s...")
                    time.sleep(min(max_backoff, backoff))
                    backoff = min(max_backoff, backoff * 2)
                    total_wait_start = time.time()

                time.sleep(3)

            backoff = base_backoff
            falhas_consecutivas = 0
            send_telegram_text("🚀 EBET Aviator conectado (payouts detectados).")
            screenshot_and_send(driver, "Dentro do jogo (payouts detectados)")

            # Inicializa históricos
            historico = coletar_historico_dom(driver)
            global_history = historico[:]

            # LOOP DE MONITORAMENTO - mais lento e robusto
            while True:
                try:
                    if page_shows_rate_limit(driver):
                        falhas_consecutivas += 1
                        sleep_time = min(max_backoff, backoff) + random.uniform(5, 15)
                        send_telegram_text(f"Rate limit detectado no loop ({falhas_consecutivas}/{MAX_FALHAS}) — dormindo {int(sleep_time)}s")
                        time.sleep(sleep_time)
                        backoff = min(max_backoff, backoff * 1.6)

                        if falhas_consecutivas >= MAX_FALHAS:
                            send_telegram_text("🔄 Excesso de rate limit → reiniciando navegador")
                            raise RuntimeError("Rate limit persistente")

                        continue

                    falhas_consecutivas = 0
                    backoff = base_backoff

                    novos = coletar_historico_dom(driver)

                    if novos and (not historico or novos[0] != historico[0]):
                        added = False
                        for v in novos:
                            if v not in global_history:
                                global_history.insert(0, v)
                                added = True
                        if len(global_history) > 50:
                            global_history = global_history[:50]

                        if added:
                            lista = ", ".join(f"{v:.2f}x" for v in global_history[:20])
                            send_telegram_text(
                                f"📊 **EBET AVIATOR - ÚLTIMOS 50**\n\n[{lista}]\n\nÚltimo: *{global_history[0]:.2f}x*",
                                throttle_seconds=10
                            )
                            if random.random() < 0.5:
                                screenshot_and_send(driver, "Histórico atualizado")

                        historico = novos[:]

                    time.sleep(15 + random.uniform(5, 10))  # polling mais humano

                except (StaleElementReferenceException, WebDriverException) as e:
                    falhas_consecutivas += 1
                    send_telegram_text(f"⚠️ Erro Selenium ({falhas_consecutivas}/{MAX_FALHAS}): {type(e).__name__}")
                    if falhas_consecutivas >= MAX_FALHAS:
                        raise
                    time.sleep(10 + random.uniform(0, 8))
                    continue

        except Exception as e:
            sleep_time = min(max_backoff, backoff) + random.uniform(5, 15)
            send_telegram_text(f"🔥 ERRO: {type(e).__name__} → reiniciando em {int(sleep_time)}s")
            time.sleep(sleep_time)
            backoff = min(max_backoff, backoff * 2)

        finally:
            try:
                if driver:
                    driver.quit()
            except:
                pass
            time.sleep(5)


@app.route("/api/history")
def api_history():
    return jsonify(global_history)


@app.route("/api/last")
def api_last():
    return jsonify(global_history[0] if global_history else None)


@app.route("/")
def home():
    return "EBET AVIATOR BOT (protected mode + histórico acumulado até 50)"


if __name__ == "__main__":
    t = threading.Thread(target=iniciar_scraper, daemon=True)
    t.start()
    port = int(os.environ.get("PORT", "8080"))
    app.run(host="0.0.0.0", port=port)
