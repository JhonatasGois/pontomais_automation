import os
import asyncio
from datetime import datetime, timedelta, timezone
from playwright.async_api import Playwright, async_playwright, expect
from telegram import Bot
from dotenv import load_dotenv
from telegram.request import HTTPXRequest

# Carrega variáveis do arquivo .env ou pontomais.env se existirem
load_dotenv()
load_dotenv("pontomais.env")

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# Horários alvo em BRT
TARGET_TIMES = ["08:00", "13:00", "14:00", "17:48"]

def get_bot():
    request = HTTPXRequest(
        connect_timeout=30,
        read_timeout=30,
        write_timeout=30,
        pool_timeout=30,
    )
    return Bot(token=TELEGRAM_TOKEN, request=request)
    
async def send_telegram_message(message: str, photo_path: str = None):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("Erro: Variáveis de ambiente TELEGRAM_TOKEN ou TELEGRAM_CHAT_ID não configuradas.")
        return

    bot = get_bot()
    try:
        if photo_path:
            with open(photo_path, "rb") as photo_file:
                await bot.send_photo(chat_id=TELEGRAM_CHAT_ID, photo=photo_file, caption=message)
        else:
            await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=message)
        print(f"Mensagem enviada para o Telegram: {message}")
    except Exception as e:
        print(f"Erro ao enviar mensagem para o Telegram: {e}")

def get_brt_time():
    """Retorna a hora atual em BRT (UTC-3)"""
    # GitHub Actions usa UTC, então convertemos para BRT
    utc_now = datetime.now(timezone.utc)
    brt_offset = timedelta(hours=-3)
    brt_now = utc_now + brt_offset
    return brt_now.replace(tzinfo=None)

CRON_TARGET_MAP = {
    "58 10 * * *": "08:00",
    "58 15 * * *": "13:00",
    "58 16 * * *": "14:00",
    "46 20 * * *": "17:48",
}

def _guess_by_current_time():
    """Fallback usado em workflow_dispatch (sem cron associado)."""
    now = get_brt_time()
    current_time = now.strftime("%H:%M")
    for target in TARGET_TIMES:
        if current_time < target:
            return target
    return TARGET_TIMES[0]

def get_target_time():
    cron = os.environ.get("CRON_SCHEDULE")
    if cron in CRON_TARGET_MAP:
        return CRON_TARGET_MAP[cron]
    # fallback pra execução manual (workflow_dispatch)
    return _guess_by_current_time()

async def wait_for_target_time(target_time_str):
    """Aguarda até o horário alvo"""
    now = get_brt_time()
    target_hour, target_minute = map(int, target_time_str.split(':'))
    
    target = now.replace(hour=target_hour, minute=target_minute, second=0, microsecond=0)
    
    # Se o horário alvo já passou hoje, agenda para amanhã
    if now >= target:
        target += timedelta(days=1)
    
    wait_seconds = (target - now).total_seconds()
    
    if wait_seconds > 0:
        print(f"Aguardando até {target_time_str} BRT ({wait_seconds:.0f} segundos)...")
        await asyncio.sleep(wait_seconds)
    else:
        print(f"Horário {target_time_str} já passou ou é agora, prosseguindo...")

async def run():
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={'width': 1280, 'height': 720},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = await context.new_page()
        page.set_default_timeout(60000)

        try:
            # Determina o horário alvo
            target_time = get_target_time()
            print(f"Horário alvo: {target_time} BRT")
            
            # 1. Navegar para a página de login
            print("Navegando para a página de login...")
            await page.goto("https://app2.pontomais.com.br/login", wait_until="domcontentloaded")
            
            # 2. Preencher credenciais de login
            login = os.environ.get("PONTOMAIS_LOGIN")
            password = os.environ.get("PONTOMAIS_PASSWORD")

            print("Aguardando campos de login...")
            await page.wait_for_selector("input[placeholder*='Nome de usuário']", state="visible")

            print("Preenchendo login...")
            await page.fill("input[placeholder*='Nome de usuário']", login)
            
            print("Preenchendo senha...")
            await page.fill("input[type='password']:visible", password)

            # 3. Clicar no botão de login
            print("Clicando no botão Entrar...")
            await page.click("button:has-text('Entrar')")

            # Aguardar o carregamento da dashboard ou menu
            print("Aguardando login ser processado...")
            await page.wait_for_function("() => !document.location.href.includes('login')", timeout=30000)

            # 4. Navegar para a página de registro de ponto
            print("Navegando para a página de registro de ponto...")
            await page.goto("https://app2.pontomais.com.br/registrar-ponto", wait_until="networkidle")

            # 5. Procurar o botão 'Utilizar essa localização'
            print("Procurando botão 'Utilizar essa localização'...")
            btn_loc_selector = "text='Utilizar essa localização'"
            await page.wait_for_selector(btn_loc_selector, state="visible", timeout=45000)
            
            # Clicar no botão de localização
            await page.click(btn_loc_selector)
            print("Botão 'Utilizar essa localização' clicado.")

            # 6. Validar o endereço no card
            print("Validando endereço...")
            expected_address = "Av. Dr. Chucri Zaidan, 920"
            await page.wait_for_selector(f"text={expected_address}", timeout=20000)
            
            # 7. Aguardar até o horário exato
            await wait_for_target_time(target_time)
            
            # 8. Localizar o botão "Bater ponto" e clicar
            print("Procurando o botão 'Bater ponto'...")
            btn_ponto = page.locator("button:has-text('Bater ponto')").first
            await btn_ponto.wait_for(state="visible", timeout=20000)
            
            # Scroll até o botão
            await btn_ponto.scroll_into_view_if_needed()
            
            # Clicar no botão
            print(f"Clicando no botão 'Bater ponto' às {target_time} BRT...")
            await btn_ponto.click()
            
            # Tirar screenshot após clicar
            ponto_screenshot_path = "bater_ponto_success.png"
            await page.screenshot(path=ponto_screenshot_path)
            
            await send_telegram_message(f"Ponto registrado com sucesso às {target_time} BRT! Confira a imagem.", photo_path=ponto_screenshot_path)
            print(f"Ponto registrado com sucesso às {target_time} BRT!")
            
            print("Processo concluído com sucesso!")

        except Exception as e:
            error_path = "error_report.png"
            await page.screenshot(path=error_path)
            await send_telegram_message(f"Erro na execução: {str(e)[:150]}", photo_path=error_path)
            print(f"Erro: {e}")
        finally:
            await browser.close()
            print("Navegador fechado.")

if __name__ == "__main__":
    asyncio.run(run())
