# main.py - EBET Aviator com proteção contra rate-limit e StaleElementReference
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

# ================= CONFIG (hardcoded conforme pediu) =================
TELEGRAM_TOKEN = "8742776802:AAHSzD1qTwCqMEOdoW9_pT2l5GfmMBWUZQY"
TELEGRAM_CHAT_ID = "7427648935"
PHONE = "857789345"
PASSWORD = "max123ZICO"
URL = "https://ebet.co.mz/games/go/spribe?id=aviator"
# =====================================================================

historico = []
_last_telegram = 0


def send_telegram_text(msg, throttle_seconds=6):
    global _last_telegram
    now = time.time()
    if now - _last_telegram < throttle_seconds:
        print("Telegram throttle: pulando envio (mensagens muito frequentes)")
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            data={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "Markdown"},
            timeout=15,
        )
        _last_telegram = now
    except Exception as e:
        print("Falha ao enviar Telegram:", e)


def send_telegram_photo(path, caption="", throttle_seconds=30):
    global _last_telegram
    now = time.time()
    if now - _last_telegram < throttle_seconds:
        print("Telegram photo throttle: pulando envio")
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
    except Exception as e:
        print("Falha ao enviar foto Telegram:", e)


def screenshot_and_send(driver, label, path="/tmp/print.png"):
    try:
        driver.save_screenshot(path)
        send_telegram_photo(path, caption=label)
    except Exception as e:
        print("Erro screenshot/send:", e)


def safe_find_elements(driver, selector, max_retries=4, sleep_between=0.3):
    """find_elements com retry para StaleElementReference"""
    for attempt in range(max_retries):
        try:
            elems = driver.find_elements(By.CSS_SELECTOR, selector)
            return elems
        except StaleElementReferenceException:
            time.sleep(sleep_between)
            continue
        except Exception as e:
            print("safe_find_elements erro:", e)
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
                print("Clique Aviator executado")
                return True
        except StaleElementReferenceException:
            continue
        except Exception as e:
            print("Erro ao clicar aviator:", e)
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
    """Detecta sinais óbvios de rate limit na página/iframe"""
    try:
        body = driver.page_source.lower()
    except Exception:
        return False
    checks = ["rate limit", "too many requests", "429", "rate-limited", "rate_limited", "try again later", "too many requests"]
    for token in checks:
        if token in body:
            return True
    return False


def iniciar_scraper():
    global historico
    # backoff settings
    base_backoff = 8       # segundos iniciais
    max_backoff = 600      # máximo (10 min)
    backoff = base_backoff

    while True:
        driver = None
        try:
            print("=== iniciar_scraper: iniciando navegador ===")
            send_telegram_text("🟢 Iniciando EBET Aviator (modo protegido)...")

            chrome_options = Options()
            chrome_options.add_argument("--headless=new")
            chrome_options.add_argument("--no-sandbox")
            chrome_options.add_argument("--disable-dev-shm-usage")
            chrome_options.add_argument("--disable-gpu")
            chrome_options.add_argument("--window-size=1366,768")
            # define user-agent para parecer humano
            chrome_options.add_argument(
                "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36"
            )

            # localizacao do binário no container
            if os.path.exists("/usr/bin/chromium"):
                chrome_options.binary_location = "/usr/bin/chromium"
            elif os.path.exists("/usr/bin/google-chrome"):
                chrome_options.binary_location = "/usr/bin/google-chrome"

            # service chromedriver (prod)
            if os.path.exists("/usr/bin/chromedriver"):
                service = Service("/usr/bin/chromedriver")
            else:
                # fallback - assume chromedriver no PATH (Windows dev). Pode falhar no deploy.
                service = Service()

            driver = webdriver.Chrome(service=service, options=chrome_options)
            wait = WebDriverWait(driver, 30)

            print("Abrindo URL:", URL)
            driver.get(URL)
            time.sleep(6)
            screenshot_and_send(driver, "Página inicial aberta")

            # clique aviator landing
            click_aviator_if_found(driver)
            time.sleep(2)

            # preencher login se existir
            try:
                phone = driver.find_element(By.ID, "phone-input")
                phone.clear()
                phone.send_keys(PHONE)
                password = driver.find_element(By.ID, "password-input")
                password.clear()
                password.send_keys(PASSWORD)
                btn = driver.find_element(By.CSS_SELECTOR, "input.btn-session")
                driver.execute_script("arguments[0].click();", btn)
                print("Login enviado")
                screenshot_and_send(driver, "Login enviado")
            except NoSuchElementException:
                print("Campos de login não encontrados no contexto atual (já logado ou layout diferente).")
            except StaleElementReferenceException:
                print("Stale ao preencher login, tentando adiar")
                time.sleep(2)

            time.sleep(6)
            click_aviator_if_found(driver)
            time.sleep(4)

            # se abriu nova aba, trocar para ela
            handles = driver.window_handles
            if len(handles) > 1:
                driver.switch_to.window(handles[-1])
                print("Trocou para nova aba do jogo")

            # localizar primeiro iframe que contenha 'spribe' no src
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
                print("Entrou no iframe externo")
                time.sleep(2)
            else:
                print("iframe externo não encontrado (continuando, pode estar tudo em root)")

            # tentar achar iframe interno launch.spribegaming
            iframe2 = None
            for f in driver.find_elements(By.TAG_NAME, "iframe"):
                try:
                    src = (f.get_attribute("src") or "").lower()
                    if "spribegaming" in src or "launch.spribegaming" in src or "launch.spribe" in src:
                        iframe2 = f
                        break
                except Exception:
                    continue

            if iframe2:
                driver.switch_to.frame(iframe2)
                print("Entrou no iframe interno Spribe")
                time.sleep(3)
            else:
                print("iframe interno (launch) não encontrado - pode carregar depois")

            # Agora: não recarregamos a Spribe. Vamos monitorar o DOM com polling lento.
            # Esperar payouts aparecerem, mas com proteção contra rate-limit.
            print("Aguardando payouts aparecerem (monitorando sem forçar reloads)...")
            total_wait_start = time.time()
            payouts = []
            while True:
                # Detecta sinais de rate-limit direto no HTML/iframe
                if page_shows_rate_limit(driver):
                    # backoff exponencial com jitter
                    jitter = random.uniform(0.2, 1.2)
                    sleep_time = min(max_backoff, backoff) + jitter
                    send_telegram_text(f"⚠️ Rate limit detectado. Dormindo {int(sleep_time)}s antes de tentar de novo.")
                    print(f"Rate limit detectado → dormindo {sleep_time}s")
                    time.sleep(sleep_time)
                    backoff = min(max_backoff, backoff * 2)
                    # reload suave: voltar ao contexto default e tentar reabrir sem abusar
                    try:
                        driver.switch_to.default_content()
                    except Exception:
                        pass
                    # não reiniciar driver imediatamente - tentar reusar
                    # após backoff, continuará a checar payouts
                # tentar coletar payouts
                try:
                    payouts = driver.find_elements(By.CSS_SELECTOR, "div.payouts-block div.payout")
                    if payouts and len(payouts) > 0:
                        print("Payouts encontrados:", len(payouts))
                        break
                except StaleElementReferenceException:
                    # re-tentar com pequena pausa
                    print("StaleElementReference ao buscar payouts - re-tentando")
                    time.sleep(1)
                except WebDriverException as e:
                    # problema com o driver - possivelmente rate limit ou desconexão
                    print("WebDriverException ao buscar payouts:", e)
                    # backoff
                    sleep_time = min(max_backoff, backoff) + random.uniform(0.5, 1.5)
                    send_telegram_text(f"⚠️ WebDriverException ao buscar payouts. Dormindo {int(sleep_time)}s")
                    time.sleep(sleep_time)
                    backoff = min(max_backoff, backoff * 2)
                # se passou muito tempo (ex.: 90s) sem payouts, aumentar backoff
                if time.time() - total_wait_start > 90:
                    send_telegram_text("⚠️ Ainda sem payouts depois de 90s — aumentando backoff e aguardando.")
                    time.sleep(min(max_backoff, backoff))
                    backoff = min(max_backoff, backoff * 2)
                    total_wait_start = time.time()
                time.sleep(2)

            # reset de backoff quando encontramos payouts
            backoff = base_backoff
            send_telegram_text("🚀 Aviator conectado (payouts detectados).")
            screenshot_and_send(driver, "Dentro do jogo (payouts detectados)")

            # coleta inicial do histórico
            historico = coletar_historico_dom(driver)
            print("Historico inicial:", historico[:8])

            # monitoring loop (não recarrega iframe/URL - apenas consulta DOM)
            while True:
                try:
                    novos = coletar_historico_dom(driver)
                    if novos and novos != historico:
                        historico = novos
                        print("Novo histórico detectado (len):", len(historico))
                        lista = ", ".join(f"{v:.2f}x" for v in historico[:20])
                        # envia só os primeiros 20 para não floodar
                        send_telegram_text(f"📊 EBET AVIATOR\n\n[{lista}]\n\nÚltimo: *{historico[0]:.2f}x*", throttle_seconds=10)
                        # opcional: screenshot ao detectar mudança grande
                        if random.random() < 0.6:  # 60% chance de mandar print (evita flood)
                            screenshot_and_send(driver, "Histórico atualizado")
                    time.sleep(5 + random.uniform(0, 2))
                except StaleElementReferenceException:
                    print("StaleElementReference no loop de monitoramento — re-tentando rápido")
                    time.sleep(1)
                except WebDriverException as e:
                    print("WebDriverException no monitor loop:", e)
                    send_telegram_text(f"⚠️ WebDriverException no monitor loop: {e}")
                    # reiniciar scraper
                    break

        except Exception as e:
            print("Erro geral no scraper:", type(e).__name__, e)
            traceback.print_exc()
            try:
                send_telegram_text(f"🔥 ERRO SCRAPER: {type(e).__name__} - {e}")
            except Exception:
                pass
            # backoff exponencial antes de reiniciar todo o processo
            sleep_time = min(max_backoff, backoff) + random.uniform(1, 3)
            print(f"Dormindo {int(sleep_time)}s antes de reiniciar scraper...")
            time.sleep(sleep_time)
            backoff = min(max_backoff, backoff * 2)
        finally:
            try:
                if driver:
                    print("Fechando driver...")
                    driver.quit()
            except Exception:
                pass
            # pequena pausa antes de tentar reiniciar
            time.sleep(3)


# Flask API
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
    return "EBET AVIATOR BOT (protected mode)"


if __name__ == "__main__":
    t = threading.Thread(target=iniciar_scraper, daemon=True)
    t.start()
    port = int(os.environ.get("PORT", "8080"))
    app.run(host="0.0.0.0", port=port)
