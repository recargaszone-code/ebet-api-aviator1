import os
import time
import re
import threading
import traceback
import requests
from flask import Flask, jsonify

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# Fallback manager only if chromedriver binary not found (useful local dev)
try:
    from webdriver_manager.chrome import ChromeDriverManager  # optional fallback
    HAVE_WDM = True
except Exception:
    HAVE_WDM = False

app = Flask(__name__)

# ================= CONFIG (hardcoded conforme pediu) =================
TELEGRAM_TOKEN = "8742776802:AAHSzD1qTwCqMEOdoW9_pT2l5GfmMBWUZQY"
TELEGRAM_CHAT_ID = "7427648935"
PHONE = "857789345"
PASSWORD = "max123ZICO"
URL = "https://ebet.co.mz/games/go/spribe?id=aviator"
# =====================================================================

historico = []                # lista global compartilhada pela API
_last_sent_screenshot = 0     # timestamp do último print enviado (evita floods)


def enviar_telegram(msg):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            data={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "Markdown"},
            timeout=15
        )
    except Exception as e:
        print("Falha ao enviar telegram (msg):", e)


def enviar_print(driver, legenda="📸 Screenshot"):
    global _last_sent_screenshot
    # envia no máximo 1 print a cada 45s (evita muitos envios)
    if time.time() - _last_sent_screenshot < 45:
        return
    try:
        path = "/tmp/print.png"
        driver.save_screenshot(path)
        with open(path, "rb") as f:
            requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto",
                files={"photo": f},
                data={"chat_id": TELEGRAM_CHAT_ID, "caption": legenda},
                timeout=30
            )
        _last_sent_screenshot = time.time()
    except Exception as e:
        print("Falha ao enviar screenshot:", e)


def clicar_aviator(driver, wait):
    """
    Clica especificamente na imagem do Aviator (seletor robusto)
    """
    try:
        imgs = wait.until(
            EC.presence_of_all_elements_located((By.CSS_SELECTOR, "img.landing-page__item-image"))
        )
    except Exception:
        imgs = driver.find_elements(By.CSS_SELECTOR, "img.landing-page__item-image")

    for img in imgs:
        try:
            src = (img.get_attribute("src") or "").lower()
            alt = (img.get_attribute("alt") or "").lower()
            if "aviator" in src or "aviator" in alt:
                driver.execute_script("arguments[0].click();", img)
                print(">> clique aviator executado (img src contains 'aviator')")
                return True
        except Exception:
            continue

    # fallback: tentar clicar qualquer link que pareça jogo aviator
    try:
        links = driver.find_elements(By.CSS_SELECTOR, "a[href*='aviator'], a[href*='spribe']")
        for a in links:
            try:
                driver.execute_script("arguments[0].click();", a)
                print(">> clique aviator executado (fallback link)")
                return True
            except Exception:
                continue
    except Exception:
        pass

    print(">> imagem do Aviator não encontrada")
    return False


def find_frame_with_selector(driver, wait, selector, search_depth=2, timeout_each=8):
    """
    Procura recursivamente por um frame que contenha um elemento que corresponda a `selector`.
    Faz buscas em até `search_depth` níveis.
    Retorna o WebElement do frame encontrado (o elemento <iframe>), ou None.
    """
    def _search_in_context(current_depth):
        # procura no contexto atual
        try:
            if driver.find_elements(By.CSS_SELECTOR, selector):
                return True
        except Exception:
            pass

        if current_depth >= search_depth:
            return False

        # procurar iframes e entrar em cada um temporariamente
        frames = driver.find_elements(By.TAG_NAME, "iframe")
        for f in frames:
            try:
                driver.switch_to.frame(f)
                found = _search_in_context(current_depth + 1)
                driver.switch_to.parent_frame()
                if found:
                    return True
            except Exception:
                try:
                    driver.switch_to.parent_frame()
                except Exception:
                    pass
        return False

    # usar wait curto para garantir DOM carregado
    end_time = time.time() + (timeout_each * max(1, search_depth))
    while time.time() < end_time:
        try:
            driver.switch_to.default_content()
            if _search_in_context(0):
                # achar qual iframe contém o selector (descer para encontrá-lo e retornar o frame element)
                def _find_frame_element(depth_limit):
                    # procura no nível atual
                    try:
                        if driver.find_elements(By.CSS_SELECTOR, selector):
                            return None  # None indica que o elemento está no contexto atual (root)
                    except Exception:
                        pass
                    frames = driver.find_elements(By.TAG_NAME, "iframe")
                    for f in frames:
                        try:
                            driver.switch_to.frame(f)
                            if driver.find_elements(By.CSS_SELECTOR, selector):
                                driver.switch_to.default_content()
                                return f
                            # profundidade adicional
                            if depth_limit > 1:
                                nested = _find_frame_element(depth_limit - 1)
                                if nested is not None:
                                    # se nested==None significa que foi encontrado no contexto atual do nested frame,
                                    # então precisamos retornar o frame que o contém (já temos f)
                                    driver.switch_to.default_content()
                                    return f
                        except Exception:
                            pass
                        finally:
                            try:
                                driver.switch_to.default_content()
                            except Exception:
                                pass
                    return None
                frame_elem = _find_frame_element(search_depth)
                return frame_elem
        except Exception:
            pass
        time.sleep(0.5)
    return None


def iniciar_scraper():
    global historico
    while True:
        driver = None
        try:
            print("=== iniciar_scraper: iniciando navegador ===")
            enviar_telegram("🟢 Iniciando EBET Aviator...")

            chrome_options = Options()
            # Headless e flags
            chrome_options.add_argument("--headless=new")
            chrome_options.add_argument("--no-sandbox")
            chrome_options.add_argument("--disable-dev-shm-usage")
            chrome_options.add_argument("--disable-gpu")
            chrome_options.add_argument("--window-size=1366,768")
            # when running in container the binary is /usr/bin/chromium
            if os.path.exists("/usr/bin/chromium"):
                chrome_options.binary_location = "/usr/bin/chromium"
            elif os.path.exists("/usr/bin/google-chrome"):
                chrome_options.binary_location = "/usr/bin/google-chrome"

            # escolher service: use /usr/bin/chromedriver quando disponível (prod)
            if os.path.exists("/usr/bin/chromedriver"):
                service = Service("/usr/bin/chromedriver")
            else:
                if HAVE_WDM:
                    print("chromedriver não encontrado em /usr/bin → usando webdriver-manager (fallback)")
                    service = Service(ChromeDriverManager().install())
                else:
                    raise RuntimeError("chromedriver não encontrado e webdriver-manager não disponível")

            driver = webdriver.Chrome(service=service, options=chrome_options)
            wait = WebDriverWait(driver, 50)

            # abrir página
            print("Abrindo URL:", URL)
            driver.get(URL)
            time.sleep(5)
            enviar_print(driver, "Página inicial (após open)")

            # clicar aviator (pode abrir popup/iframe)
            clicar_aviator(driver, wait)
            time.sleep(3)

            # preencher login (espera aparecer o campo phone)
            try:
                phone = wait.until(EC.presence_of_element_located((By.ID, "phone-input")))
                phone.clear()
                phone.send_keys(PHONE)
                password = driver.find_element(By.ID, "password-input")
                password.clear()
                password.send_keys(PASSWORD)
                btn = driver.find_element(By.CSS_SELECTOR, "input.btn-session")
                driver.execute_script("arguments[0].click();", btn)
                print("Login enviado")
                enviar_print(driver, "Depois do login")
            except Exception as e:
                print("Aviso: não consegui localizar campos de login imediatamente:", e)

            time.sleep(6)
            # clicar aviator novamente para abrir o jogo
            clicar_aviator(driver, wait)
            time.sleep(4)

            # tratar nova aba (se abriu)
            handles = driver.window_handles
            if len(handles) > 1:
                print("Mudando para última aba (jogo)")
                driver.switch_to.window(handles[-1])

            # procurar frame que contenha o div.payout (procura recursiva)
            print("Procurando frame que contenha 'div.payout' (procura recursiva)...")
            frame_elem = find_frame_with_selector(driver, wait, "div.payout", search_depth=3, timeout_each=8)

            if frame_elem is None:
                # alternativa: procurar iframes por src que indiquem spribe/spribegaming
                print("Não encontrou frame pelo selector; procurando iframe por src contendo 'spribe' ou 'spribegaming'...")
                driver.switch_to.default_content()
                frames = driver.find_elements(By.TAG_NAME, "iframe")
                frame_elem = None
                for f in frames:
                    try:
                        src = f.get_attribute("src") or ""
                        if "spribe" in src or "spribegaming" in src or "launch.spribegaming" in src:
                            frame_elem = f
                            break
                    except Exception:
                        continue

            if frame_elem is None:
                raise RuntimeError("Não foi possível localizar o iframe do jogo (nenhum frame com payouts ou src spribe encontrado)")

            # entrar no frame encontrado; se frame_elem is None significa que o elemento está no contexto atual (root)
            if frame_elem is not None:
                driver.switch_to.frame(frame_elem)
                print("Entrou no frame que contém o jogo (nivel 1)")
                # tentar localizar outro iframe interno (spribe → launch.spribegaming)
                time.sleep(1)
                inner_frames = driver.find_elements(By.TAG_NAME, "iframe")
                inner_frame_found = None
                for f in inner_frames:
                    try:
                        src = f.get_attribute("src") or ""
                        if "spribegaming" in src or "launch.spribegaming" in src or "spribe" in src:
                            inner_frame_found = f
                            break
                    except Exception:
                        continue
                if inner_frame_found:
                    driver.switch_to.frame(inner_frame_found)
                    print("Entrou no iframe interno do Spribe (nivel 2)")
            else:
                print("Elemento 'div.payout' está no contexto root (sem iframe adicional)")

            # aguardar o primeiro payout aparecer
            print("Aguardando elemento 'div.payout' dentro do contexto atual...")
            wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "div.payout")))
            time.sleep(2)
            enviar_print(driver, "Dentro do jogo (antes de coletar histórico)")
            enviar_telegram("🚀 Aviator conectado (frames verificados)")

            # coletar histórico inicial
            def coletar_historico_from_dom():
                items = driver.find_elements(By.CSS_SELECTOR, "div.payout")
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

            historico = coletar_historico_from_dom()
            print("Histórico inicial:", historico)

            # monitor loop
            while True:
                try:
                    novos = coletar_historico_from_dom()
                    if novos and novos != historico:
                        historico = novos
                        print("Novo histórico detectado:", historico[:30])
                        # enviar telegram (apenas os primeiros 20 para não floodar)
                        lista = ", ".join(f"{v:.2f}x" for v in historico[:20])
                        enviar_telegram(f"📊 *EBET AVIATOR*\n\n[{lista}]\n\nÚltimo: *{historico[0]:.2f}x*")
                        enviar_print(driver, "Histórico atualizado")
                    # manter log local
                    time.sleep(5)
                except Exception as e:
                    print("Erro no loop de monitoramento:", e)
                    traceback.print_exc()
                    time.sleep(6)

        except Exception as e:
            print("Erro geral no scraper:", e)
            traceback.print_exc()
            try:
                enviar_telegram(f"🔥 ERRO SCRAPER: {type(e).__name__} - {e}")
            except Exception:
                pass
            # limpa historico se quiser reiniciar
            # historico = []
            time.sleep(15)
        finally:
            try:
                if driver:
                    print("Fechando driver...")
                    driver.quit()
            except Exception:
                pass


# ================= Flask API endpoints =================

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
    return "EBET AVIATOR BOT ONLINE"


# ================= Start background thread & flask =================
if __name__ == "__main__":
    t = threading.Thread(target=iniciar_scraper, daemon=True)
    t.start()
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
