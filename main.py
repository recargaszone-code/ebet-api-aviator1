#!/usr/bin/env python3
# main.py - EBET Aviator (baseado no código que funcionou) + Railway + Histórico 50

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
from selenium.common.exceptions import StaleElementReferenceException

# ================= CONFIG =================
TELEGRAM_TOKEN = "8742776802:AAHSzD1qTwCqMEOdoW9_pT2l5GfmMBWUZQY"
TELEGRAM_CHAT_ID = "7427648935"
PHONE = "857789345"
PASSWORD = "max123ZICO"
URL = "https://ebet.co.mz/games/go/spribe?id=aviator"

app = Flask(__name__)

historico = []           # snapshot atual
global_history = []      # acumula até 50
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
        path = f"/tmp/{int(time.time())}_{label.replace(' ', '_')[:30]}.png"
        driver.save_screenshot(path)
        send_telegram_text(f"📸 {label}")
        print(f"   📸 Screenshot enviado: {label}")
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

def clicar_aviator(driver, wait):
    print_step("Clicando na imagem do Aviator")
    try:
        imgs = wait.until(EC.presence_of_all_elements_located((By.CSS_SELECTOR, "img.landing-page__item-image")))
        for img in imgs:
            src = (img.get_attribute("src") or "").lower()
            if "aviator" in src:
                driver.execute_script("arguments[0].click();", img)
                print("   ✅ Clique Aviator executado!")
                screenshot_and_send(driver, "Clique Aviator OK")
                return True
        print("   ⚠️ Imagem Aviator não encontrada")
        screenshot_and_send(driver, "Falha - Imagem Aviator não encontrada")
        return False
    except Exception as e:
        print(f"   Erro ao clicar Aviator: {e}")
        screenshot_and_send(driver, "Falha - Clicar Aviator")
        return False

def coletar_historico_dom(driver):
    vals = []
    for el in safe_find_elements(driver, "div.payout"):
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
            wait = WebDriverWait(driver, 60)

            print_step("1 - Abrindo URL")
            driver.get(URL)
            time.sleep(8)
            screenshot_and_send(driver, "1 - Página aberta")

            clicar_aviator(driver, wait)
            time.sleep(5)

            print_step("3 - Fazendo Login")
            phone = wait.until(EC.presence_of_element_located((By.ID, "phone-input")))
            phone.clear()
            phone.send_keys(PHONE)
            password = driver.find_element(By.ID, "password-input")
            password.clear()
            password.send_keys(PASSWORD)
            btn = driver.find_element(By.CSS_SELECTOR, "input.btn-session")
            driver.execute_script("arguments[0].click();", btn)
            screenshot_and_send(driver, "3 - Login enviado")
            print("✅ Login enviado")
            time.sleep(7)

            clicar_aviator(driver, wait)
            time.sleep(8)

            print_step("5 - Trocando aba se necessário")
            if len(driver.window_handles) > 1:
                driver.switch_to.window(driver.window_handles[-1])
                print("✅ Mudou para aba do jogo")
                screenshot_and_send(driver, "5 - Aba trocada")

            print_step("6 - Entrando no iframe externo (spribe)")
            iframe1 = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "iframe[src*='spribe']")))
            driver.switch_to.frame(iframe1)
            screenshot_and_send(driver, "6 - Iframe externo OK")
            print("✅ Iframe externo OK")
            time.sleep(5)

            print_step("7 - Entrando no iframe interno (spribegaming)")
            iframe2 = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "iframe[src*='spribegaming']")))
            driver.switch_to.frame(iframe2)
            screenshot_and_send(driver, "7 - Iframe interno OK")
            print("✅ Entrou no iframe do Aviator!")
            time.sleep(8)

            print_step("8 - Aguardando histórico")
            wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "div.payout")))
            screenshot_and_send(driver, "8 - Histórico apareceu")

            historico = coletar_historico_dom(driver)
            with _history_lock:
                global_history = historico[:]
            print(f"✅ Histórico inicial: {len(historico)} itens")
            screenshot_and_send(driver, "8 - Histórico inicial OK")

            # LOOP MONITORAMENTO
            while True:
                print_step("LOOP - Verificando novo histórico")
                if page_shows_rate_limit(driver):
                    print("⚠️ RATE LIMIT detectado")
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

                print("⏳ Aguardando 15-25s...")
                time.sleep(15 + random.uniform(5, 10))

        except Exception as e:
            print(f"❌ ERRO: {type(e).__name__} - {e}")
            traceback.print_exc()
            send_telegram_text(f"🔥 ERRO: {type(e).__name__}")
            screenshot_and_send(driver, "ERRO GERAL")
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
    return "EBET AVIATOR - Código que funcionou adaptado para Railway"

if __name__ == "__main__":
    threading.Thread(target=supervisor_thread, daemon=True).start()
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
