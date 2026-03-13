# main_screenshots.py
import os
import time
import re
import requests
import threading
import traceback
from flask import Flask, jsonify

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait

app = Flask(__name__)

# ============== CONFIG (hardcoded conforme pediu) ==============
TELEGRAM_TOKEN = "8742776802:AAHSzD1qTwCqMEOdoW9_pT2l5GfmMBWUZQY"
TELEGRAM_CHAT_ID = "7427648935"

PHONE = "857789345"
PASSWORD = "max123ZICO"

URL = "https://ebet.co.mz/games/go/spribe?id=aviator"
# ==============================================================

historico = []
_step_dir = os.path.join(os.getcwd(), "screenshots_steps")
os.makedirs(_step_dir, exist_ok=True)

def _screenshot_path(step_name):
    ts = int(time.time())
    safe = step_name.replace(" ", "_").lower()
    return os.path.join(_step_dir, f"{ts}_{safe}.png")

def enviar_telegram_text(msg):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            data={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "Markdown"},
            timeout=15
        )
    except Exception as e:
        print("Falha enviar msg Telegram:", e)

def enviar_print(driver, caption="screenshot", step_name="step"):
    """Salva screenshot, envia pra Telegram e faz log."""
    try:
        path = _screenshot_path(step_name)
        # se driver não suportar full page, save_screenshot funciona
        driver.save_screenshot(path)
    except Exception as e:
        print("Erro ao salvar screenshot local:", e)
        return

    # enviar para Telegram
    try:
        with open(path, "rb") as f:
            requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto",
                files={"photo": f},
                data={"chat_id": TELEGRAM_CHAT_ID, "caption": caption},
                timeout=30
            )
    except Exception as e:
        print("Falha ao enviar screenshot ao Telegram:", e)

    print(f"[print] {step_name} -> {path}")

# ---------- funções utilitárias ----------
def clicar_aviator(driver):
    imgs = driver.find_elements(By.CSS_SELECTOR, "img.landing-page__item-image")
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
    items = driver.find_elements(By.CSS_SELECTOR, "div.payouts-block div.payout")
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

# ---------- rotina principal que tira prints em checkpoints ----------
def iniciar_scraper_steps():
    global historico
    while True:
        driver = None
        try:
            enviar_telegram_text("🟢 Iniciando EBET Aviator (com passos e prints)...")

            chrome_options = Options()
            chrome_options.add_argument("--headless=new")
            chrome_options.add_argument("--no-sandbox")
            chrome_options.add_argument("--disable-dev-shm-usage")
            chrome_options.add_argument("--disable-gpu")
            chrome_options.add_argument("--window-size=1366,768")

            # binário chromium (no container). Em Windows, comente esta linha se não existir
            if os.path.exists("/usr/bin/chromium"):
                chrome_options.binary_location = "/usr/bin/chromium"
            elif os.path.exists("/usr/bin/google-chrome"):
                chrome_options.binary_location = "/usr/bin/google-chrome"

            # escolha do chromedriver
            if os.path.exists("/usr/bin/chromedriver"):
                service = Service("/usr/bin/chromedriver")
            else:
                # fallback: assume chromedriver no PATH (Windows local). Ajuste conforme necessário.
                service = Service()

            driver = webdriver.Chrome(service=service, options=chrome_options)
            wait = WebDriverWait(driver, 40)

            # STEP 1: abrir página
            driver.get(URL)
            time.sleep(5)
            enviar_print(driver, caption="Página inicial aberta", step_name="01_pagina_aberta")

            # STEP 2: clicar na imagem do Aviator (landing)
            ok = clicar_aviator(driver)
            time.sleep(2)
            enviar_print(driver, caption=f"Clique Aviator executado? {ok}", step_name="02_clique_aviator_antes_login")

            # STEP 3: preencher login (telefone)
            try:
                phone = wait.until(lambda d: d.find_element(By.ID, "phone-input"))
                phone.clear()
                phone.send_keys(PHONE)
                enviar_print(driver, caption="Telefone preenchido", step_name="03_telefone_preenchido")
            except Exception as e:
                print("Aviso: campo telefone não encontrado ainda:", e)
                enviar_print(driver, caption="Telefone NÃO encontrado", step_name="03_telefone_nao_encontrado")

            # STEP 4: preencher senha
            try:
                password = driver.find_element(By.ID, "password-input")
                password.clear()
                password.send_keys(PASSWORD)
                enviar_print(driver, caption="Senha preenchida", step_name="04_senha_preenchida")
            except Exception as e:
                print("Aviso: campo senha não encontrado:", e)
                enviar_print(driver, caption="Senha NÃO encontrada", step_name="04_senha_nao_encontrada")

            # STEP 5: clicar no botão Conecte-se
            try:
                btn = driver.find_element(By.CSS_SELECTOR, "input.btn-session")
                driver.execute_script("arguments[0].click();", btn)
                time.sleep(6)
                enviar_print(driver, caption="Botão Conecte-se clicado", step_name="05_login_enviado")
            except Exception as e:
                print("Aviso: botão login não encontrado/click falhou:", e)
                enviar_print(driver, caption="Erro ao clicar login", step_name="05_login_erro")

            # STEP 6: clicar Aviator novamente para abrir o jogo
            clicar_aviator(driver)
            time.sleep(4)
            enviar_print(driver, caption="Clique Aviator depois do login", step_name="06_clique_aviator_depois_login")

            # STEP 7: tratar nova aba (se existir)
            handles = driver.window_handles
            if len(handles) > 1:
                driver.switch_to.window(handles[-1])
                enviar_print(driver, caption="Switch para nova aba do jogo", step_name="07_troca_aba")
            else:
                enviar_print(driver, caption="Mesma aba (sem troca)", step_name="07_mesma_aba")

            # STEP 8: entrar em primeiro iframe que contenha 'spribe' no src
            time.sleep(2)
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
                enviar_print(driver, caption="Entrou no iframe externo (spribe)", step_name="08_iframe_externo")
            else:
                enviar_print(driver, caption="iframe externo NÃO encontrado", step_name="08_iframe_externo_nao")

            # STEP 9: procurar iframe interno do Spribe (launch.spribegaming)
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
                time.sleep(4)
                enviar_print(driver, caption="Entrou no iframe interno (launch.spribegaming)", step_name="09_iframe_interno")
            else:
                enviar_print(driver, caption="iframe interno NÃO encontrado", step_name="09_iframe_interno_nao")

            # STEP 10: esperar o histórico (payouts) aparecer — loop ativo, com timeout geral de ~60s
            print("Aguardando payouts aparecer...")
            timeout = time.time() + 60
            payouts = []
            while time.time() < timeout and len(payouts) == 0:
                payouts = driver.find_elements(By.CSS_SELECTOR, "div.payouts-block div.payout")
                print("payouts encontrados:", len(payouts))
                if len(payouts) == 0:
                    time.sleep(2)
            if len(payouts) == 0:
                enviar_print(driver, caption="Payouts NÃO apareceram depois de 60s", step_name="10_payouts_nao")
                enviar_telegram_text("⚠️ Payouts não apareceram — ver logs / layout pode ter mudado")
            else:
                enviar_print(driver, caption=f"Payouts encontrados: {len(payouts)}", step_name="10_payouts_sim")

            # STEP 11: coletar histórico e enviar para API/telegram
            historico = coletar_historico_dom(driver)
            enviar_print(driver, caption=f"Histórico coletado: {len(historico)} items", step_name="11_historico_coletado")
            enviar_telegram_text(f"✅ Histórico coletado: {len(historico)} items. Último: {historico[0] if historico else 'N/A'}")

            # salvar histórico local (arquivo)
            try:
                with open(os.path.join(_step_dir, "historico.json"), "w") as f:
                    import json
                    json.dump(historico, f)
            except Exception:
                pass

            # finalmente: loop de monitoramento (enviar prints quando o histórico mudar)
            while True:
                try:
                    novos = coletar_historico_dom(driver)
                    if novos and novos != historico:
                        historico = novos
                        enviar_print(driver, caption=f"Histórico atualizado: {len(historico)}", step_name="12_historico_atual")
                        enviar_telegram_text(f"🔔 Novo histórico: Último {historico[0]:.2f}x (total {len(historico)})")
                    time.sleep(5)
                except Exception as e:
                    print("Erro loop monitor:", e)
                    traceback.print_exc()
                    time.sleep(6)

        except Exception as e:
            print("Erro geral no scraper:", e)
            traceback.print_exc()
            try:
                enviar_telegram_text(f"🔥 ERRO SCRAPER: {type(e).__name__} - {e}")
            except:
                pass
            time.sleep(20)
        finally:
            try:
                if driver:
                    driver.quit()
            except:
                pass

# ---------- Flask API mínima (mesmo historico global) ----------
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
    return "EBET AVIATOR BOT (with screenshots)"

if __name__ == "__main__":
    t = threading.Thread(target=iniciar_scraper_steps, daemon=True)
    t.start()
    port = int(os.environ.get("PORT", "8080"))
    app.run(host="0.0.0.0", port=port)
