import os
import asyncio
from datetime import datetime, timedelta, timezone
from playwright.async_api import async_playwright
from telegram import Bot
from dotenv import load_dotenv
from telegram.request import HTTPXRequest

load_dotenv()
load_dotenv("pontomais.env")

TELEGRAM_TOKEN  = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
TARGET_TIMES    = ["08:00", "13:00", "14:00", "17:55"]

# ──────────────────────────────────────────────────────────────────────────────
# Telegram
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
    try:
        if photo_path and os.path.exists(photo_path):
            with open(photo_path, "rb") as f:
                await bot.send_photo(chat_id=TELEGRAM_CHAT_ID, photo=f,
                                     caption=message[:1024])
        else:
            await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=message[:4096])
        print(f"[TELEGRAM] {message[:120]}")
    except Exception as e:
        print(f"[TELEGRAM ERROR] {e}")
        # fallback: tenta mandar só o texto se a foto falhou
        if photo_path:
            try:
                await bot.send_message(chat_id=TELEGRAM_CHAT_ID,
                                       text=f"{message}\n(screenshot falhou: {e})")
            except Exception as e2:
                print(f"[TELEGRAM ERROR fallback] {e2}")

# ──────────────────────────────────────────────────────────────────────────────
# Horário BRT
# ──────────────────────────────────────────────────────────────────────────────
def get_brt_time():
    return (datetime.now(timezone.utc) + timedelta(hours=-3)).replace(tzinfo=None)

CRON_TARGET_MAP = {
    "58 10 * * *": "08:00",
    "58 15 * * *": "13:00",
    "58 16 * * *": "14:00",
    "51 20 * * *": "17:55",   # ← corrigido (era 46 20)
}

def get_target_time():
    cron = os.environ.get("CRON_SCHEDULE", "")
    if cron in CRON_TARGET_MAP:
        return CRON_TARGET_MAP[cron]
    # fallback workflow_dispatch: pega o próximo horário futuro
    now_str = get_brt_time().strftime("%H:%M")
    for t in TARGET_TIMES:
        if now_str < t:
            return t
    return TARGET_TIMES[0]

async def wait_for_target_time(target_time_str: str):
    now = get_brt_time()
    h, m = map(int, target_time_str.split(":"))
    target = now.replace(hour=h, minute=m, second=0, microsecond=0)
    if now >= target:
        target += timedelta(days=1)
    secs = (target - now).total_seconds()
    if secs > 0:
        print(f"[WAIT] Aguardando {secs:.0f}s até {target_time_str} BRT…")
        await asyncio.sleep(secs)

# ──────────────────────────────────────────────────────────────────────────────
# Helpers de debug — despeja elementos interativos da página
# ──────────────────────────────────────────────────────────────────────────────
async def dump_interactive_elements(page, label: str):
    print(f"\n{'='*60}")
    print(f"[DEBUG] {label}  |  URL: {page.url}")
    print(f"{'='*60}")

    inputs = await page.eval_on_selector_all(
        "input, textarea, select",
        """els => els.map(el => ({
            tag: el.tagName,
            type: el.type || '',
            placeholder: el.placeholder || '',
            name: el.name || '',
            id: el.id || '',
            visible: el.offsetParent !== null
        }))"""
    )
    print(f"  INPUTS ({len(inputs)}):")
    for i in inputs:
        print(f"    [{i['tag']}] type={i['type']!r:12} placeholder={i['placeholder']!r:35} "
              f"name={i['name']!r:20} visible={i['visible']}")

    buttons = await page.eval_on_selector_all(
        "button, [role='button'], [type='submit']",
        """els => els.map(el => ({
            tag: el.tagName,
            text: el.innerText.trim().replace(/\\s+/g,' ').substring(0,80),
            type: el.getAttribute('type') || '',
            disabled: el.disabled,
            visible: el.offsetParent !== null,
            class: el.className.substring(0,60)
        }))"""
    )
    print(f"  BUTTONS ({len(buttons)}):")
    for b in buttons:
        print(f"    text={b['text']!r:40} disabled={b['disabled']} visible={b['visible']}")
        print(f"         class={b['class']!r}")

    # Textos visíveis que contenham palavras-chave relevantes
    texts = await page.eval_on_selector_all(
        "[class*='btn'], [class*='button'], mat-button, ion-button",
        "els => els.map(el => el.innerText.trim().substring(0,80))"
    )
    if texts:
        print(f"  MAT/ION BUTTONS ({len(texts)}): {texts}")
    print()

# ──────────────────────────────────────────────────────────────────────────────
# Clique robusto — tenta múltiplas estratégias
# ──────────────────────────────────────────────────────────────────────────────
async def robust_click(page, selectors: list[str], label: str, timeout=30000) -> bool:
    """Tenta cada seletor em ordem; retorna True se algum funcionou."""
    for sel in selectors:
        try:
            loc = page.locator(sel).first
            await loc.wait_for(state="visible", timeout=timeout)
            await loc.scroll_into_view_if_needed()
            await loc.click()
            print(f"[OK] Clicou em '{label}' via seletor: {sel!r}")
            return True
        except Exception as e:
            print(f"[SKIP] Seletor {sel!r} falhou: {type(e).__name__}: {str(e)[:80]}")
    return False

# ──────────────────────────────────────────────────────────────────────────────
# Fluxo principal
# ──────────────────────────────────────────────────────────────────────────────
async def run():
    target_time = get_target_time()
    print(f"[INFO] Horário alvo: {target_time} BRT")
    print(f"[INFO] CRON_SCHEDULE env: {os.environ.get('CRON_SCHEDULE', '(não definido)')!r}")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={"width": 1280, "height": 720},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        )
        page = await context.new_page()
        page.set_default_timeout(60000)

        try:
            # ── LOGIN ──────────────────────────────────────────────────────────
            print("[STEP 1] Navegando para login…")
            await page.goto("https://app2.pontomais.com.br/login",
                            wait_until="domcontentloaded")
            # SPA Angular precisa de tempo extra pra renderizar
            await page.wait_for_timeout(4000)

            await dump_interactive_elements(page, "Página de Login")

            login    = os.environ.get("PONTOMAIS_LOGIN")
            password = os.environ.get("PONTOMAIS_PASSWORD")

            # Campo de usuário — várias estratégias
            user_selectors = [
                "input[placeholder*='Nome de usuário']",
                "input[placeholder*='nome de usuário']",
                "input[placeholder*='usuário']",
                "input[placeholder*='login']",
                "input[placeholder*='Login']",
                "input[placeholder*='e-mail']",
                "input[placeholder*='Email']",
                "input[type='text']:visible",
                "input[type='email']:visible",
                "input:not([type='password']):not([type='hidden']):visible",
            ]
            filled_user = False
            for sel in user_selectors:
                try:
                    await page.wait_for_selector(sel, state="visible", timeout=5000)
                    await page.fill(sel, login)
                    print(f"[OK] Campo usuário preenchido via: {sel!r}")
                    filled_user = True
                    break
                except Exception:
                    continue
            if not filled_user:
                raise Exception("Não encontrou campo de usuário!")

            # Campo de senha
            await page.fill("input[type='password']:visible", password)
            print("[OK] Senha preenchida.")

            # Botão entrar — múltiplas estratégias
            clicked_login = await robust_click(page, [
                "button:has-text('Entrar')",
                "button:has-text('entrar')",
                "button:has-text('Login')",
                "button:has-text('Acessar')",
                "button[type='submit']",
                "[type='submit']",
            ], "Entrar")

            if not clicked_login:
                await page.screenshot(path="error_login_btn.png")
                raise Exception("Não encontrou botão de login!")

            # Aguarda sair da página de login
            print("[STEP 2] Aguardando redirect pós-login…")
            await page.wait_for_function(
                "() => !document.location.href.includes('login')",
                timeout=30000
            )
            print(f"[OK] Logado. URL: {page.url}")

            # ── REGISTRAR PONTO ────────────────────────────────────────────────
            print("[STEP 3] Navegando para registrar-ponto…")
            # Usa load em vez de networkidle (Angular nunca fica idle de vez)
            await page.goto("https://app2.pontomais.com.br/registrar-ponto",
                            wait_until="load")
            await page.wait_for_timeout(4000)

            await dump_interactive_elements(page, "Página Registrar Ponto")

            # ── BOTÃO LOCALIZAÇÃO ──────────────────────────────────────────────
            print("[STEP 4] Procurando botão de localização…")
            loc_selectors = [
                "text='Utilizar essa localização'",
                "text='Utilizar esta localização'",
                "text='Usar essa localização'",
                "button:has-text('localização')",
                "button:has-text('Localização')",
                "[class*='location']:visible",
                "button:has-text('Permitir')",
            ]
            clicked_loc = await robust_click(page, loc_selectors, "Localização", timeout=45000)
            if not clicked_loc:
                await page.screenshot(path="error_localizacao.png")
                await dump_interactive_elements(page, "DEBUG: após falha de localização")
                raise Exception("Não encontrou botão de localização!")

            await page.wait_for_timeout(2000)

            # ── VALIDAÇÃO DE ENDEREÇO ──────────────────────────────────────────
            print("[STEP 5] Validando endereço…")
            expected_address = "Av. Dr. Chucri Zaidan, 920"
            try:
                await page.wait_for_selector(
                    f"text={expected_address}", timeout=20000
                )
                print(f"[OK] Endereço encontrado: {expected_address!r}")
            except Exception:
                print(f"[WARN] Endereço {expected_address!r} não encontrado no DOM — continuando mesmo assim.")
                await page.screenshot(path="warn_address.png")

            # ── AGUARDA HORÁRIO ALVO ───────────────────────────────────────────
            print(f"[STEP 6] Aguardando horário {target_time} BRT…")
            await wait_for_target_time(target_time)

            # ── BATER PONTO ────────────────────────────────────────────────────
            print("[STEP 7] Clicando 'Bater ponto'…")
            await dump_interactive_elements(page, "Antes de clicar Bater Ponto")

            ponto_selectors = [
                "button:has-text('Bater ponto')",
                "button:has-text('bater ponto')",
                "button:has-text('Bater Ponto')",
                "button:has-text('Registrar ponto')",
                "button:has-text('Registrar')",
                "[class*='ponto']:visible",
            ]
            clicked_ponto = await robust_click(page, ponto_selectors, "Bater Ponto")

            if not clicked_ponto:
                await page.screenshot(path="error_bater_ponto.png")
                await dump_interactive_elements(page, "DEBUG: após falha Bater Ponto")
                raise Exception("Não encontrou botão 'Bater ponto'!")

            # Aguarda confirmação visual
            await page.wait_for_timeout(3000)
            await page.screenshot(path="bater_ponto_success.png")

            brt_now = get_brt_time().strftime("%H:%M:%S")
            await send_telegram(
                f"✅ Ponto registrado com sucesso às {brt_now} BRT!",
                photo_path="bater_ponto_success.png"
            )
            print(f"[SUCCESS] Ponto registrado às {brt_now} BRT!")

        except Exception as e:
            print(f"[ERROR] {e}")
            try:
                await page.screenshot(path="error_report.png")
            except Exception:
                pass
            await send_telegram(
                f"❌ Erro no Pontomais ({get_brt_time().strftime('%H:%M')} BRT):\n{str(e)[:300]}",
                photo_path="error_report.png"
            )
        finally:
            await browser.close()
            print("[INFO] Navegador fechado.")

if __name__ == "__main__":
    asyncio.run(run())