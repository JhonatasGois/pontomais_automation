import os
import asyncio
from datetime import datetime, timedelta, timezone
from playwright.async_api import async_playwright
from telegram import Bot
from dotenv import load_dotenv
from telegram.request import HTTPXRequest

# Carrega variáveis de ambiente
load_dotenv()
load_dotenv("pontomais.env")

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
TARGET_TIMES = ["08:00", "13:00", "14:00", "17:55"]

# ──────────────────────────────────────────────────────────────────────────────
# Telegram com Lógica de Retry
# ──────────────────────────────────────────────────────────────────────────────
def get_bot():
    return Bot(
        token=TELEGRAM_TOKEN,
        request=HTTPXRequest(connect_timeout=30, read_timeout=60,
                             write_timeout=60, pool_timeout=30),
    )

async def send_telegram(message: str, photo_path: str = None):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("[WARN] Telegram não configurado.")
        return

    bot = get_bot()
    max_retries = 3
    for attempt in range(max_retries):
        try:
            if photo_path and os.path.exists(photo_path):
                with open(photo_path, "rb") as f:
                    await bot.send_photo(chat_id=TELEGRAM_CHAT_ID, photo=f,
                                         caption=message[:1024])
            else:
                await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=message[:4096])
            print(f"[TELEGRAM] {message[:120]}")
            return
        except Exception as e:
            if attempt < max_retries - 1:
                print(f"[RETRY TELEGRAM] Tentativa {attempt + 1} falhou: {e}. Tentando novamente...")
                await asyncio.sleep(5)
            else:
                print(f"[TELEGRAM ERROR FINAL] {e}")

# ──────────────────────────────────────────────────────────────────────────────
# Horário BRT
# ──────────────────────────────────────────────────────────────────────────────
def get_brt_time():
    return (datetime.now(timezone.utc) + timedelta(hours=-3)).replace(tzinfo=None)

def get_target_time():
    """
    Determina o horário-alvo mais próximo com base no horário atual.
    Como o workflow agora é disparado externamente (cron-job.org) já
    próximo do horário exato, isso serve apenas como referência/log.
    """
    now_str = get_brt_time().strftime("%H:%M")
    for t in TARGET_TIMES:
        if now_str < t:
            return t
    return TARGET_TIMES[0]

MAX_WAIT_SECONDS = 15 * 60  # teto de segurança: nunca espera mais que 15 min

async def sleep_until_target(target_time_str: str):
    """
    Sempre aguarda até o horário-alvo exato antes de prosseguir.
    - Se o job começou antes do horário: espera até o segundo exato.
    - Se já passou do horário: executa imediatamente (não faz sentido esperar 24h).
    - Teto de MAX_WAIT_SECONDS para não travar o job indefinidamente
      caso algo dispare muito errado (ex: horário trocado sem querer).
    """
    now = get_brt_time()
    target = now.replace(
        hour=int(target_time_str[:2]),
        minute=int(target_time_str[3:]),
        second=0,
        microsecond=0
    )
    delta = (target - now).total_seconds()

    if delta <= 0:
        print(f"[INFO] Horário alvo já passou por {abs(delta):.0f}s, executando agora.")
        return

    if delta > MAX_WAIT_SECONDS:
        print(f"[WARN] Delta de {delta:.0f}s excede o teto de {MAX_WAIT_SECONDS}s. "
              f"Executando sem esperar (verifique se o disparo está correto).")
        return

    print(f"[SLEEP] Aguardando {delta:.0f}s até {target_time_str} BRT…")
    await asyncio.sleep(delta)
    print(f"[OK] Horário {target_time_str} BRT atingido.")

# ──────────────────────────────────────────────────────────────────────────────
# Fluxo principal
# ──────────────────────────────────────────────────────────────────────────────
async def run():
    target_time = get_target_time()
    print(f"[INFO] Horário alvo: {target_time} BRT")
    await sleep_until_target(target_time)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={"width": 1280, "height": 720},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = await context.new_page()
        page.set_default_timeout(60000)

        try:
            # ── LOGIN ──────────────────────────────────────────────────────────
            print("[STEP 1] Navegando para login…")
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    await page.goto("https://app2.pontomais.com.br/login", wait_until="domcontentloaded", timeout=60000)
                    break
                except Exception as e:
                    if attempt < max_retries - 1:
                        print(f"[RETRY] Falha ao carregar login (tentativa {attempt + 1}). Erro: {e}")
                        await asyncio.sleep(5)
                    else:
                        raise e

            await page.wait_for_timeout(4000)

            login = os.environ.get("PONTOMAIS_LOGIN")
            password = os.environ.get("PONTOMAIS_PASSWORD")

            await page.fill("input[placeholder*='Nome de usuário']", login)
            await page.fill("input[type='password']:visible", password)
            await page.click("button:has-text('Entrar')")

            print("[STEP 2] Aguardando login…")
            await page.wait_for_function("() => !document.location.href.includes('login')", timeout=45000)

            # ── REGISTRAR PONTO ────────────────────────────────────────────────
            print("[STEP 3] Navegando para registrar-ponto…")
            await page.goto("https://app2.pontomais.com.br/registrar-ponto", wait_until="load")
            await page.wait_for_timeout(5000)

            # ── BOTÃO LOCALIZAÇÃO ──────────────────────────────────────────────
            print("[STEP 4] Verificando estado da localização…")

            # Aguarda o título da seção para garantir carregamento
            await page.wait_for_selector("h3:has-text('Registrar ponto')", timeout=30000)

            # Tenta clicar em "Utilizar essa localização" se disponível
            try:
                btn_utilizar_loc = page.locator("small:has-text('Utilizar essa localização')")
                # Aguarda um pouco para o elemento aparecer
                await btn_utilizar_loc.wait_for(state="visible", timeout=10000)
                await btn_utilizar_loc.click()
                print("[OK] Clique em 'Utilizar essa localização'.")
                await page.wait_for_timeout(2000)
            except Exception as e:
                print(f"[INFO] Botão 'Utilizar essa localização' não encontrado ou já processado: {e}")

            # ── VALIDAÇÃO DE ENDEREÇO ──────────────────────────────────────────
            print("[STEP 5] Validando endereço…")
            expected_address = "Av. Dr. Chucri Zaidan, 920"
            
            # Tenta encontrar o endereço de forma resiliente
            try:
                # Procura por qualquer elemento que contenha o endereço esperado
                await page.wait_for_selector(f"text={expected_address}", timeout=15000)
                print(f"[OK] Endereço validado: {expected_address}")
            except Exception as e:
                print(f"[ERRO] Endereço '{expected_address}' não encontrado na página.")
                error_path = "address_not_found.png"
                await page.screenshot(path=error_path)
                await send_telegram(f"Erro: Endereço '{expected_address}' não encontrado.", photo_path=error_path)
                raise Exception(f"Endereço não validado.")

            # ── BATER PONTO ────────────────────────────────────────────────────
            print("[STEP 7] Clicando 'Bater ponto'…")
            
            # Seletor preciso: botão pm-primary dentro do container btn-register
            btn_register_selector = "pm-button.btn-register.mt-1 button.pm-primary"
            
            try:
                await page.wait_for_selector(btn_register_selector, state="visible", timeout=15000)
                
                # Antes de clicar, tirar um print de depuração para o usuário
                debug_path = "debug_before_click.png"
                await page.screenshot(path=debug_path)
                print(f"[DEBUG] Screenshot salvo em {debug_path}")

                await page.click(btn_register_selector)
                print("[OK] Botão 'Bater ponto' clicado com seletor específico.")
                await page.wait_for_timeout(3000)

            except Exception as e:
                print(f"[RETRY] Falha com seletor específico. Tentando clique via JavaScript...")
                clicked = await page.evaluate("""
                    () => {
                        const buttons = document.querySelectorAll('button.pm-primary');
                        for (const btn of buttons) {
                            if (btn.textContent.includes('Bater ponto')) {
                                btn.click();
                                return true;
                            }
                        }
                        return false;
                    }
                """)
                
                if not clicked:
                    raise Exception("Botão 'Bater ponto' não encontrado via JS.")
                
                print("[OK] Botão 'Bater ponto' clicado via JS.")
                await page.wait_for_timeout(3000)

            except Exception as e:
                print(f"[ERRO] Botão não encontrado.")
                error_path = "timeout_button.png"
                await page.screenshot(path=error_path)
                await send_telegram("Aviso: O botão 'Bater ponto' não foi encontrado.", photo_path=error_path)
                raise e
            
            # Tirar print do botão pronto
            ponto_ready_path = "bater_ponto_ready.png"
            await page.screenshot(path=ponto_ready_path)
            await send_telegram("O botão 'Bater ponto' está pronto e habilitado!", photo_path=ponto_ready_path)
            print("[OK] Sucesso total.")

            print("Processo concluído com sucesso!")

        except Exception as e:
            error_path = "error_report.png"
            await page.screenshot(path=error_path)
            await send_telegram(f"Erro na execução: {str(e)[:150]}", photo_path=error_path)
            print(f"Erro: {e}")
        finally:
            await browser.close()
            print("Navegador fechado.")

if __name__ == "__main__":
    asyncio.run(run())
