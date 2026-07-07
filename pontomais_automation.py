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

CRON_TARGET_MAP = {
    "55 10 * * *": "08:00",
    "55 15 * * *": "13:00",
    "55 16 * * *": "14:00",
    "50 20 * * *": "17:48",
}

async def sleep_until_target(target_time_str: str):
    now = get_brt_time()
    target = now.replace(
        hour=int(target_time_str[:2]),
        minute=int(target_time_str[3:]),
        second=0,
        microsecond=0
    )
    delta = (target - now).total_seconds()
    if 0 < delta <= 600:
        print(f"[SLEEP] Aguardando {delta:.0f}s até {target_time_str} BRT…")
        await asyncio.sleep(delta)
    elif delta <= 0:
        print(f"[INFO] Horário alvo já passou por {abs(delta):.0f}s, executando agora.")
    else:
        print(f"[WARN] Delta inesperado ({delta:.0f}s), executando sem esperar.")

async def run():
    target_time = get_target_time()
    print(f"[INFO] Horário alvo: {target_time} BRT")
    await sleep_until_target(target_time)  # ← segura aqui até o horário exato

def get_target_time():
    cron = os.environ.get("CRON_SCHEDULE", "")
    if cron in CRON_TARGET_MAP:
        return CRON_TARGET_MAP[cron]
    now_str = get_brt_time().strftime("%H:%M")
    for t in TARGET_TIMES:
        if now_str < t:
            return t
    return TARGET_TIMES[0]

# ──────────────────────────────────────────────────────────────────────────────
# Fluxo principal
# ──────────────────────────────────────────────────────────────────────────────
async def run():
    target_time = get_target_time()
    print(f"[INFO] Horário alvo: {target_time} BRT")

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

            # Checa se a localização está expirada
            loc_expirada = False
            try:
                await page.wait_for_selector("text='Sua localização expirou!'", state="visible", timeout=5000)
                loc_expirada = True
                print("[INFO] Localização expirada detectada. Clicando para atualizar…")
            except:
                pass

            if loc_expirada:
                btn_atualizar = "button.pm-alert:has-text('Clique aqui para atualizar a localização')"
                await page.wait_for_selector(btn_atualizar, state="visible", timeout=15000)
                await page.click(btn_atualizar)
                print("[OK] Botão 'Atualizar localização' clicado.")
                await page.wait_for_timeout(3000)  # aguarda o site reprocessar a geo

            # Agora clica em "Utilizar essa localização" (fluxo normal ou pós-atualização)
            btn_loc_selector = "text='Utilizar essa localização'"
            await page.wait_for_selector(btn_loc_selector, state="visible", timeout=30000)
            await page.click(btn_loc_selector)
            print("[OK] Localização clicada.")

            # ── VALIDAÇÃO DE ENDEREÇO ──────────────────────────────────────────
            print("[STEP 5] Validando endereço…")
            expected_address = "Av. Dr. Chucri Zaidan, 920"
            await page.wait_for_selector(f"text={expected_address}", timeout=30000)
            print(f"[OK] Endereço validado.")

            # ── GARANTIR LOCALIZAÇÃO ANTES DE BATER ───────────────────────────
            print("[STEP 6.5] Reconfirmando localização antes de bater ponto…")

            expected_address = "Av. Dr. Chucri Zaidan, 920"
            max_loc_retries = 3

            for attempt in range(max_loc_retries):
                try:
                    btn_loc = page.locator("text='Utilizar essa localização'").first
                    await btn_loc.wait_for(state="visible", timeout=10000)
                    await btn_loc.click()
                    print(f"[OK] Localização clicada (tentativa {attempt + 1}).")
                    await page.wait_for_timeout(2000)

                    # Valida se o endereço apareceu corretamente
                    await page.wait_for_selector(f"text={expected_address}", timeout=8000)
                    print(f"[OK] Endereço confirmado: {expected_address}")
                    break  # endereço ok, segue pro bater ponto

                except Exception as e:
                    print(f"[WARN] Endereço não confirmado na tentativa {attempt + 1}: {e}")
                    if attempt < max_loc_retries - 1:
                        await page.wait_for_timeout(3000)
                    else:
                        error_path = "loc_error.png"
                        await page.screenshot(path=error_path)
                        await send_telegram(
                            f"Erro: não foi possível confirmar o endereço após {max_loc_retries} tentativas.",
                            photo_path=error_path
                        )
                        raise Exception("Endereço não confirmado. Abortando para não bater ponto sem localização.")

            # ── BATER PONTO ────────────────────────────────────────────────────
            print("[STEP 7] Clicando 'Bater ponto'…")
            try:
                # Força o clique via JS direto no botão pm-primary dentro do componente de registro
                clicked = await page.evaluate("""
                    () => {
                        const buttons = document.querySelectorAll('vrgente-time-card-register-point button.pm-button.pm-primary');
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
