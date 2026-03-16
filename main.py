#!/usr/bin/env python3
# main.py - EBET Aviator + AGUARDO HISTÓRICO COM LOGS + ANTI-TRAVAMENTO

import os
import sys
import time
import threading
import re
import random
import traceback
import signal
from pathlib import Path
import requests
from flask import Flask, jsonify
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, StaleElementReferenceException

# ================= CONFIG =================
TELEGRAM_TOKEN = "8742776802:AAHSzD1qTwCqMEOdoW9_pT2l5GfmMBWUZQY"
TELEGRAM_CHAT_ID = "7427648935"
PHONE = "857789345"
PASSWORD = "max123ZICO"
URL = "https://ebet.co.mz/games/go/spribe?id=aviator"

app = Flask(__name__)

historico = []
global_history = []
_history_lock = threading.Lock()
_last_telegram = 0

def send_telegram_text(msg, throttle=30):
    global _last_telegram
    if time.time() - _last_telegram < throttle:
        return
    try:
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                      data={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "Markdown"}, timeout=15)
        _last_telegram = time.time()
    except:
        pass

def screenshot_and_send(driver, label):
    try:
        path = f"/tmp/{int(time.time())}_{label.replace(' ', '_')[:30]}.png"
        driver.save_screenshot(path)
        send_telegram_text(f"📸 {label}")
        print(f"   📸 Enviado: {label}")
    except:
        pass

def print_step(step):
    print(f"\n{'='*80}")
    print(f"🚀 {step}")
    print(f"{'='*80}")
    send_telegram_text(f"📍 {step}", throttle=60)

def safe_find_elements(driver, selector):
    for _ in range(5):
        try:
            return driver.find_elements(By.CSS_SELECTOR, selector)
        except:
            time.sleep(0.5)
    return []

def clicar_aviator(driver, wait):
    print("   Procurando Aviator...")
    try:
        imgs = wait.until(EC.presence_of_all_elements_located((By.CSS_SELECTOR, "img.landing-page__item-image")))
        for img in imgs:
            src = (img.get_attribute("src") or "").lower()
            if "aviator" in src:
                driver.execute_script("arguments[0].click();", img)
                print("   ✅ Clique OK")
                screenshot_and_send(driver, "Clique Aviator")
                return True
    except Exception as e:
        print(f"   Falha clicar Aviator: {e}")
    return False

def coletar_historico_dom(driver):
    vals = []
    for el in safe_find_elements(driver, "div.payout, div.payout.ng-star-inserted"):
        try:
            m = re.search(r"(\d+\.?\d*)", el.text.strip())
            if m:
                vals.append(float(m.group(1)))
        except:
            continue
    return vals

def page_shows_rate_limit(driver):
    try:
        return any(x in driver.page_source.lower() for x in ["rate limit", "too many requests", "429"])
    except:
        return False

def start_driver():
    print_step("Iniciando Driver")
    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--window-size=1366,768")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")

    if os.path.exists("/usr/bin/chromium"):
        opts.binary_location = "/usr/bin/chromium"
    service = Service("/usr/bin/chromedriver") if os.path.exists("/usr/bin/chromedriver") else Service()
    driver = webdriver.Chrome(service=service, options=opts)
    try:
        driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
            "source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
        })
    except:
        pass
    return driver

def iniciar_scraper():
    global historico, global_history
    backoff = 15

    while True:
        driver = None
        try:
            print_step("INICIANDO CICLO")
            driver = start_driver()
            wait = WebDriverWait(driver, 60)

            print_step("Abrindo URL")
            driver.get(URL)
            time.sleep(random.uniform(8, 12))
            screenshot_and_send(driver, "Página aberta")

            clicar_aviator(driver, wait)
            time.sleep(random.uniform(5, 10))

            print_step("Login")
            try:
                phone = wait.until(EC.presence_of_element_located((By.ID, "phone-input")))
                phone.clear()
                for ch in PHONE:
                    phone.send_keys(ch)
                    time.sleep(random.uniform(0.1, 0.3))
                password = driver.find_element(By.ID, "password-input")
                password.clear()
                for ch in PASSWORD:
                    password.send_keys(ch)
                    time.sleep(random.uniform(0.1, 0.3))
                btn = driver.find_element(By.CSS_SELECTOR, "input.btn-session")
                driver.execute_script("arguments[0].click();", btn)
                screenshot_and_send(driver, "Login enviado")
                print("✅ Login OK")
            except:
                print("⚠️ Login pulado")

            time.sleep(random.uniform(8, 15))

            clicar_aviator(driver, wait)
            time.sleep(random.uniform(8, 15))

            if len(driver.window_handles) > 1:
                driver.switch_to.window(driver.window_handles[-1])
                print("✅ Nova aba")

            print_step("Iframe externo")
            try:
                iframe1 = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "iframe[src*='spribe']")))
                driver.switch_to.frame(iframe1)
                screenshot_and_send(driver, "Iframe externo OK")
                print("✅ Iframe externo")
                time.sleep(random.uniform(4, 8))
            except:
                screenshot_and_send(driver, "Falha iframe externo")

            print_step("Iframe interno")
            try:
                iframe2 = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "iframe[src*='spribegaming']")))
                driver.switch_to.frame(iframe2)
                screenshot_and_send(driver, "Iframe interno OK")
                print("✅ Entrou no Aviator!")
            except:
                screenshot_and_send(driver, "Falha iframe interno")

            print_step("AGUARDANDO HISTÓRICO (até 3min com logs)")
            start_wait = time.time()
            attempt = 0
            while time.time() - start_wait < 180:
                attempt += 1
                if page_shows_rate_limit(driver):
                    print("⚠️ RATE LIMIT detectado no aguardo")
                    send_telegram_text("⚠️ Rate limit no aguardo histórico")
                    time.sleep(20)
                    continue

                payouts = safe_find_elements(driver, "div.payout, div.payout.ng-star-inserted")
                print(f"   Tentativa {attempt} - {len(payouts)} payouts")

                if len(payouts) > 0:
                    print("✅ HISTÓRICO CARREGADO!")
                    screenshot_and_send(driver, "Histórico apareceu")
                    break

                if attempt % 5 == 0:
                    print("   Ainda aguardando... (não travou, continua tentando)")
                    send_telegram_text("⏳ Ainda aguardando histórico...", throttle=120)

                time.sleep(random.uniform(4, 8))

            if len(payouts) == 0:
                raise RuntimeError("Histórico não carregou em 3min")

            historico = coletar_historico_dom(driver)
            with _history_lock:
                global_history = historico[:]
            screenshot_and_send(driver, "Histórico inicial OK")
            print(f"✅ Histórico inicial: {len(historico)}")

            while True:
                print_step("LOOP - Checando novo histórico")
                novos = coletar_historico_dom(driver)

                if novos and (not historico or novos[0] != historico[0]):
                    print(f"🔄 NOVO! Último: {novos[0]:.2f}x")
                    with _history_lock:
                        for v in novos:
                            if v not in global_history:
                                global_history.insert(0, v)
                        if len(global_history) > 50:
                            global_history = global_history[:50]
                    lista = ", ".join(f"{v:.2f}x" for v in global_history[:20])
                    send_telegram_text(f"📊 **EBET AVIATOR - ÚLTIMOS 50**\n[{lista}]\nÚltimo: *{global_history[0]:.2f}x*", throttle=20)
                    screenshot_and_send(driver, "Novo histórico")
                    historico = novos[:]

                time.sleep(random.uniform(20, 40))

        except Exception as e:
            print(f"❌ ERRO: {type(e).__name__} - {e}")
            traceback.print_exc()
            send_telegram_text(f"🔥 ERRO: {type(e).__name__}")
            time.sleep(30)

        finally:
            if driver:
                try:
                    driver.quit()
                except:
                    pass
            time.sleep(10)

def supervisor_thread():
    while True:
        worker = threading.Thread(target=iniciar_scraper, daemon=True)
        worker.start()
        print("✅ Supervisor iniciado")
        worker.join()
        print("⚠️ Worker morreu - reiniciando...")
        time.sleep(20)

@app.route("/api/history")
def api_history():
    with _history_lock:
        return jsonify(global_history)

@app.route("/")
def home():
    return "EBET AVIATOR - AGUARDO HISTÓRICO CORRIGIDO"

if __name__ == "__main__":
    threading.Thread(target=supervisor_thread, daemon=True).start()
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
