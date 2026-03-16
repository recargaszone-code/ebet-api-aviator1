#!/usr/bin/env python3
# main.py - EBET Aviator + IFRAME CORRIGIDO (bitville + spribe) + LOGS COMPLETOS

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
from selenium.common.exceptions import StaleElementReferenceException
from selenium.webdriver.support.ui import WebDriverWait

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

SCREEN_DIR = Path("/tmp/ebet_aviator_steps")
SCREEN_DIR.mkdir(parents=True, exist_ok=True)

def send_telegram_text(msg, throttle=6):
    global _last_telegram
    if time.time() - _last_telegram < throttle:
        return
    try:
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                      data={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "Markdown"}, timeout=10)
        _last_telegram = time.time()
    except:
        pass

def screenshot_and_send(driver, label):
    try:
        path = f"/tmp/{int(time.time())}_{label.replace(' ', '_')}.png"
        driver.save_screenshot(path)
        send_telegram_text(f"📸 {label}")
    except:
        pass

def print_step(step):
    print(f"\n{'='*80}")
    print(f"🚀 PASSO: {step}")
    print(f"{'='*80}")
    send_telegram_text(f"📍 {step}")

def safe_find_elements(driver, selector):
    for _ in range(5):
        try:
            return driver.find_elements(By.CSS_SELECTOR, selector)
        except:
            time.sleep(0.4)
    return []

def click_aviator_if_found(driver):
    print("   Procurando imagem do Aviator...")
    for img in safe_find_elements(driver, "img.landing-page__item-image"):
        try:
            src = (img.get_attribute("src") or "").lower()
            alt = (img.get_attribute("alt") or "").lower()
            if "aviator" in src or "aviator" in alt:
                driver.execute_script("arguments[0].click();", img)
                print("   ✅ Clique no Aviator executado!")
                return True
        except:
            continue
    print("   ⚠️ Imagem Aviator não encontrada")
    return False

def coletar_historico_dom(driver):
    vals = []
    for el in safe_find_elements(driver, "div.payouts-block div.payout, div.payout"):
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
    print_step("Iniciando Chrome Driver")
    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--window-size=1366,768")
    opts.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")

    if os.path.exists("/usr/bin/chromium"):
        opts.binary_location = "/usr/bin/chromium"
    service = Service("/usr/bin/chromedriver") if os.path.exists("/usr/bin/chromedriver") else Service()
    return webdriver.Chrome(service=service, options=opts)

def iniciar_scraper():
    global historico, global_history
    backoff = 10

    while True:
        driver = None
        try:
            print_step("INICIANDO NOVO CICLO")
            driver = start_driver()

            print_step("1 - Abrindo URL")
            driver.get(URL)
            time.sleep(8)
            screenshot_and_send(driver, "Página inicial")

            print_step("2 - Clicando Aviator")
            click_aviator_if_found(driver)
            time.sleep(4)

            print_step("3 - Tentando Login")
            try:
                phone = driver.find_element(By.ID, "phone-input")
                phone.send_keys(PHONE)
                password = driver.find_element(By.ID, "password-input")
                password.send_keys(PASSWORD)
                btn = driver.find_element(By.CSS_SELECTOR, "input.btn-session")
                driver.execute_script("arguments[0].click();", btn)
                screenshot_and_send(driver, "Login enviado")
                print("✅ Login enviado com sucesso")
            except:
                print("⚠️ Login já feito ou campos não encontrados")

            time.sleep(8)

            print_step("4 - Procurando e entrando no iframe (bitville + spribe)")
            if len(driver.window_handles) > 1:
                driver.switch_to.window(driver.window_handles[-1])
                print("✅ Trocou para nova aba")

            iframe_el = None
            print("   Buscando iframe Spribe / Bitville...")
            for f in driver.find_elements(By.TAG_NAME, "iframe"):
                try:
                    src = (f.get_attribute("src") or "").lower()
                    class_name = (f.get_attribute("class") or "").lower()
                    id_name = (f.get_attribute("id") or "").lower()
                    print(f"   Candidato: id={id_name} | class={class_name} | src={src[:90]}...")

                    if ("launch.spribegaming.com" in src or 
                        "aviator-next.spribegaming.com" in src or 
                        "games-interface.bitville-api.com" in src or 
                        "spribe" in src or 
                        "spribe-iframe" in class_name or 
                        "game-iframe" in class_name or 
                        "provider-game-iframe" in id_name):
                        iframe_el = f
                        print("   ✅ IFRAME ENCONTRADO!")
                        break
                except:
                    continue

            if iframe_el:
                driver.switch_to.frame(iframe_el)
                print("✅ Entrou no iframe com sucesso!")
            else:
                print("❌ Nenhum iframe encontrado após 1 tentativa")
                raise RuntimeError("Iframe não localizado")

            print_step("5 - Aguardando payouts (com logs a cada tentativa)")
            start_time = time.time()
            attempt = 0
            while time.time() - start_time < 120:
                attempt += 1
                payouts = safe_find_elements(driver, "div.payouts-block div.payout, div.payout")
                print(f"   Tentativa {attempt} → {len(payouts)} payouts encontrados")

                if len(payouts) > 0:
                    print("✅ PAYOUTS ENCONTRADOS!")
                    break
                if page_shows_rate_limit(driver):
                    print("⚠️ Rate limit detectado")
                    time.sleep(10)
                time.sleep(4)

            print_step("6 - Coletando histórico inicial")
            historico = coletar_historico_dom(driver)
            with _history_lock:
                global_history = historico[:]
            print(f"✅ Histórico inicial carregado: {len(historico)} itens")

            # LOOP PRINCIPAL
            while True:
                print_step("LOOP - Verificando novo histórico")
                if page_shows_rate_limit(driver):
                    print("⚠️ RATE LIMIT no loop")
                    time.sleep(backoff + random.uniform(5, 15))
                    continue

                novos = coletar_historico_dom(driver)
                if novos and (not historico or novos[0] != historico[0]):
                    print(f"🔄 NOVO HISTÓRICO! Último: {novos[0]:.2f}x")
                    with _history_lock:
                        for v in novos:
                            if v not in global_history:
                                global_history.insert(0, v)
                        if len(global_history) > 50:
                            global_history = global_history[:50]
                    lista = ", ".join(f"{v:.2f}x" for v in global_history[:20])
                    print(f"   Histórico atualizado: {lista}")
                    send_telegram_text(f"📊 **EBET AVIATOR - ÚLTIMOS 50**\n[{lista}]\nÚltimo: *{global_history[0]:.2f}x*")
                    screenshot_and_send(driver, "Histórico atualizado")
                    historico = novos[:]

                print("⏳ Aguardando próxima checagem (15-25s)...")
                time.sleep(15 + random.uniform(5, 10))

        except Exception as e:
            print(f"❌ ERRO: {type(e).__name__} - {e}")
            traceback.print_exc()
            send_telegram_text(f"🔥 ERRO: {type(e).__name__}")
            time.sleep(15)

        finally:
            if driver:
                try:
                    driver.quit()
                    print("🔌 Driver fechado")
                except:
                    pass
            time.sleep(5)


def supervisor_thread():
    while True:
        worker = threading.Thread(target=iniciar_scraper, daemon=True)
        worker.start()
        print("✅ Supervisor: Worker iniciado")
        worker.join()
        print("⚠️ Worker morreu - reiniciando em 10s...")
        time.sleep(10)


@app.route("/api/history")
def api_history():
    with _history_lock:
        return jsonify(global_history)

@app.route("/")
def home():
    return "EBET AVIATOR - IFRAME CORRIGIDO (bitville + spribe)"

if __name__ == "__main__":
    threading.Thread(target=supervisor_thread, daemon=True).start()
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
