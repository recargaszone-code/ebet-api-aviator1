#!/usr/bin/env python3
# main.py - EBET Aviator com proteção contra rate-limit + HISTÓRICO ACUMULADO ATÉ 50
# + supervisor que reinicia o worker se houver falha
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
from selenium.common.exceptions import (
    TimeoutException,
    StaleElementReferenceException,
    NoSuchElementException,
    WebDriverException,
)
from selenium.webdriver.support.ui import WebDriverWait

# ---------------- CONFIG (hardcoded) ----------------
TELEGRAM_TOKEN = "8742776802:AAHSzD1qTwCqMEOdoW9_pT2l5GfmMBWUZQY"
TELEGRAM_CHAT_ID = "7427648935"
PHONE = "857789345"
PASSWORD = "max123ZICO"
URL = "https://ebet.co.mz/games/go/spribe?id=aviator"
# ====================================================

app = Flask(__name__)

# estado compartilhado
historico = []           # snapshot atual (para detectar mudança)
global_history = []      # acumula os últimos 50 (novo no topo)
_history_lock = threading.Lock()

_last_telegram = 0

# Supervisor params
SUPERVISOR_BACKOFF_BASE = 2      # s
SUPERVISOR_BACKOFF_MAX = 300     # s
RESTART_WINDOW_SECONDS = 300     # janela para contar reinícios
RESTART_THRESHOLD = 8            # threshold -> execv restart

# pasta para screenshots (opcional)
SCREEN_DIR = Path("/tmp/ebet_aviator_steps")
SCREEN_DIR.mkdir(parents=True, exist_ok=True)


def send_telegram_text(msg, throttle_seconds=6):
    global _last_telegram
    now = time.time()
    if now - _last_telegram < throttle_seconds:
        return False
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            data={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "Markdown"},
            timeout=15,
        )
        _last_telegram = now
        return True
    except Exception as e:
        print("send_telegram_text failed:", e)
        return False


def send_telegram_photo(path, caption="", throttle_seconds=30):
    global _last_telegram
    now = time.time()
    if now - _last_telegram < throttle_seconds:
        return False
    try:
        with open(path, "rb") as f:
            requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto",
                files={"photo": f},
                data={"chat_id": TELEGRAM_CHAT_ID, "caption": caption},
                timeout=30,
            )
        _last_telegram = now
        return True
    except Exception as e:
        print("send_telegram_photo failed:", e)
        return False


def save_screenshot(driver, label):
    try:
        fname = f"{int(time.time())}_{abs(hash(label))%10000}.png"
        path = SCREEN_DIR / fname
        driver.save_screenshot(str(path))
        return str(path)
    except Exception as e:
        print("save_screenshot failed:", e)
        return None


def screenshot_and_send(driver, label):
    p = save_screenshot(driver, label)
    if p:
        send_telegram_photo(p, caption=label)


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
        except Exception:
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
        except Exception:
            continue
    return vals


def page_shows_rate_limit(driver):
    try:
        body = driver.page_source.lower()
        checks = ["rate limit", "too many requests", "429", "rate-limited", "try again later"]
        return any(token in body for token in checks)
    except Exception:
        return False


def start_driver():
    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--window-size=1366,768")
    opts.add_argument(
        "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36"
    )
    if os.path.exists("/usr/bin/chromium"):
        opts.binary_location = "/usr/bin/chromium"
    service = Service("/usr/bin/chromedriver") if os.path.exists("/usr/bin/chromedriver") else Service()
    driver = webdriver.Chrome(service=service, options=opts)

    # tentar reduzir fingerprint
    try:
        stealth = r"""
        Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
        try{ Object.defineProperty(navigator, 'languages', {get:()=>['pt-BR','pt']}); }catch(e){}
        try{ Object.defineProperty(navigator, 'plugins', {get:()=>[1,2,3]}); }catch(e){}
        """
        driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {"source": stealth})
    except Exception:
        pass

    time.sleep(0.3)
    return driver


def iniciar_scraper():
    """
    Scraper principal - contem loop interno com tratamento de excecoes.
    Se ocorrer uma exceção não tratada e a função terminar, o supervisor irá reiniciar.
    """
    global historico, global_history
    base_backoff = 8
    max_backoff = 600
    backoff = base_backoff

    while True:
        driver = None
        try:
            send_telegram_text("🟢 Iniciando EBET Aviator (modo protegido + histórico 50)...", throttle_seconds=6)

            driver = start_driver()
            wait = WebDriverWait(driver, 30)

            # abrir URL
            driver.get(URL)
            time.sleep(6)
            screenshot_and_send(driver, "Página inicial aberta")

            # clicar aviator se houver
            click_aviator_if_found(driver)
            time.sleep(2)

            # tentar login (se o site for EBET com campos id's diferentes)
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
                # layout diferente, ignora
                pass
            except StaleElementReferenceException:
                time.sleep(2)

            time.sleep(6)
            click_aviator_if_found(driver)
            time.sleep(4)

            # trocar para nova aba caso o jogo tenha aberto uma
            handles = driver.window_handles
            if len(handles) > 1:
                driver.switch_to.window(handles[-1])

            # localizar iframes (duas camadas possíveis)
            iframe1 = None
            for f in driver.find_elements(By.TAG_NAME, "iframe"):
                try:
                    src = (f.get_attribute("src") or "").lower()
                    if "spribe" in src and "launch" not in src:
                        iframe1 = f
                        break
                except Exception:
                    continue
            if iframe1:
                driver.switch_to.frame(iframe1)
                time.sleep(2)

            iframe2 = None
            for f in driver.find_elements(By.TAG_NAME, "iframe"):
                try:
                    src = (f.get_attribute("src") or "").lower()
                    if "spribegaming" in src or "launch.spribegaming" in src:
                        iframe2 = f
                        break
                except Exception:
                    continue
            if iframe2:
                driver.switch_to.frame(iframe2)
                time.sleep(3)

            # aguardar payouts aparecerem (com proteção rate-limit)
            total_wait_start = time.time()
            while True:
                if page_shows_rate_limit(driver):
                    sleep_time = min(max_backoff, backoff) + random.uniform(0.2, 1.2)
                    send_telegram_text(f"⚠️ Rate limit detectado. Dormindo {int(sleep_time)}s", throttle_seconds=6)
                    time.sleep(sleep_time)
                    backoff = min(max_backoff, backoff * 2)
                    try:
                        driver.switch_to.default_content()
                    except Exception:
                        pass
                    continue

                payouts = safe_find_elements(driver, "div.payouts-block div.payout")
                if payouts and len(payouts) > 0:
                    break

                if time.time() - total_wait_start > 90:
                    send_telegram_text("⚠️ Ainda sem payouts depois de 90s — aguardando.", throttle_seconds=6)
                    time.sleep(min(max_backoff, backoff))
                    backoff = min(max_backoff, backoff * 2)
                    total_wait_start = time.time()

                time.sleep(2)

            backoff = base_backoff
            send_telegram_text("🚀 EBET Aviator conectado (payouts detectados).", throttle_seconds=6)
            screenshot_and_send(driver, "Dentro do jogo (payouts detectados)")

            # coleta inicial do histórico
            historico = coletar_historico_dom(driver)
            with _history_lock:
                global_history = historico[:]   # inicia o acumulador

            # monitoring loop
            while True:
                if page_shows_rate_limit(driver):
                    sleep_time = min(max_backoff, backoff) + random.uniform(0.2, 1.2)
                    send_telegram_text(f"Rate limit detectado no loop — dormindo {int(sleep_time)}s", throttle_seconds=6)
                    time.sleep(sleep_time)
                    continue

                try:
                    novos = coletar_historico_dom(driver)

                    if novos and (not historico or novos[0] != historico[0]):
                        added = False
                        with _history_lock:
                            for v in novos:
                                if v not in global_history:
                                    global_history.insert(0, v)
                                    added = True
                            # truncar para 50
                            if len(global_history) > 50:
                                global_history = global_history[:50]

                        if added:
                            with _history_lock:
                                lista = ", ".join(f"{v:.2f}x" for v in global_history[:20])
                                ultimo = global_history[0] if global_history else None
                            send_telegram_text(
                                f"📊 **EBET AVIATOR - ÚLTIMOS 50**\n\n[{lista}]\n\nÚltimo: *{ultimo:.2f}x*",
                                throttle_seconds=10
                            )
                            if random.random() < 0.6:
                                screenshot_and_send(driver, "Histórico atualizado (50)")

                        historico = novos[:]

                except StaleElementReferenceException:
                    time.sleep(1)
                except WebDriverException as e:
                    # Se o driver der erro, sair do loop e reiniciar o scraper (supervisor ou loop externo fará o restart)
                    send_telegram_text(f"⚠️ WebDriverException no monitor loop: {e}", throttle_seconds=6)
                    # raise para terminar a função e permitir supervisor reiniciar
                    raise

                time.sleep(5 + random.uniform(0, 2))

        except Exception as e:
            # Loga e re-lança se for um erro crítico que deve reiniciar (WebDriverException já é re-lançado acima)
            print("Erro geral no scraper:", type(e).__name__, e)
            traceback.print_exc()
            try:
                send_telegram_text(f"🔥 ERRO SCRAPER: {type(e).__name__} - {e}", throttle_seconds=6)
            except Exception:
                pass
            # pequena pausa antes de tentar reiniciar internamente — aqui voltamos ao while True para tentar reconectar,
            # mas também permitimos que esse bloco re-raise se preferir que o supervisor reinicie o processo.
            time.sleep(min(max_backoff, backoff) + random.uniform(1, 3))
            backoff = min(max_backoff, backoff * 2)
            # continue loop externo (recriar driver)
            continue

        finally:
            try:
                if driver:
                    driver.quit()
            except Exception:
                pass
            time.sleep(3)


# ---------------- Supervisor ----------------
def supervisor_thread():
    """
    Inicia o worker (iniciar_scraper) em thread e reinicia se ela terminar.
    Se muitas reinicializacoes acontecerem num curto periodo, faz execv para reiniciar o processo por completo.
    """
    restart_timestamps = []
    backoff = SUPERVISOR_BACKOFF_BASE

    while True:
        worker = threading.Thread(target=iniciar_scraper, name="scraper-worker", daemon=True)
        worker.start()
        send_telegram_text("🔁 Supervisor: worker iniciado", throttle_seconds=6)

        # aguarda termino do worker
        while worker.is_alive():
            worker.join(timeout=5)

        # worker morreu/terminou
        ts = time.time()
        restart_timestamps.append(ts)
        # limpa timestamps antigos
        restart_timestamps = [t for t in restart_timestamps if ts - t <= RESTART_WINDOW_SECONDS]

        send_telegram_text(f"⚠️ Supervisor: worker finalizou (reiniciando). Restarts nos últimos {RESTART_WINDOW_SECONDS}s: {len(restart_timestamps)}", throttle_seconds=6)
        print(f"[supervisor] worker died; restarts_in_window={len(restart_timestamps)}")

        if len(restart_timestamps) >= RESTART_THRESHOLD:
            send_telegram_text("⚠️ Muitos restarts em curto período → reiniciando processo via execv", throttle_seconds=6)
            try:
                python = sys.executable
                os.execv(python, [python] + sys.argv)
            except Exception as ex:
                print("execv failed:", ex)
                time.sleep(backoff)
                backoff = min(SUPERVISOR_BACKOFF_MAX, backoff * 2)
                continue

        # backoff exponencial entre restarts do worker
        time.sleep(backoff + random.uniform(0, 2))
        backoff = min(SUPERVISOR_BACKOFF_MAX, backoff * 2)


# ---------------- Flask endpoints ----------------
@app.route("/api/history")
def api_history():
    with _history_lock:
        return jsonify(global_history)


@app.route("/api/last")
def api_last():
    with _history_lock:
        return jsonify(global_history[0] if global_history else None)


@app.route("/")
def home():
    return "EBET AVIATOR BOT (protected mode + histórico acumulado até 50)"


# ---------------- graceful shutdown ----------------
def _signal_handler(sig, frame):
    try:
        send_telegram_text(f"🛑 Processo recebendo sinal {sig} — desligando.", throttle_seconds=0)
    except Exception:
        pass
    sys.exit(0)

signal.signal(signal.SIGINT, _signal_handler)
signal.signal(signal.SIGTERM, _signal_handler)


# ---------------- entrypoint ----------------
if __name__ == "__main__":
    sup = threading.Thread(target=supervisor_thread, name="supervisor", daemon=True)
    sup.start()
    port = int(os.environ.get("PORT", "8080"))
    app.run(host="0.0.0.0", port=port)
