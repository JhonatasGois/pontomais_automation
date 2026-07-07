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

# Quantas vezes tentar o fluxo inteiro (login -> registrar-ponto -> bater ponto)
# antes de desistir e notificar falha definitiva.
MAX_FLOW_RETRIES = 3
FLOW_RETRY_DELAY_SECONDS = 20

# Watchdog: tempo máximo que o processo inteiro (espera + fluxo) pode rodar
# antes de ser abortado à força. Serve pra nunca deixar o job pendurado até
# o limite de 6h do GitHub Actions.
GLOBAL_TIMEOUT_SECONDS = 60 * 60  # 1 hora

# Teto de segurança para a espera até o horário-alvo. Cobre o pior caso real:
# disparo único no início do dia (ex: 08:00) esperando até o último alvo
# (17:55), mais uma margem de folga.
MAX_WAIT_SECONDS = 11 * 60 * 60  # 11 horas


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
    """
    now_str = get_brt_time().strftime("%H:%M")
    for t in TARGET_TIMES:
        if now_str < t:
            return t
    return TARGET_TIMES[0]

async def sleep_until_target(target_time_str: str):
    """
    Sempre aguarda até o horário-alvo exato antes de prosseguir.
    - Se o job começou antes do horário: espera até o segundo exato,
      em pequenos incrementos (permite reagir a cancelamento do job
      e evita ficar preso num único asyncio.sleep gigante).
    - Se já passou do horário: executa imediatamente.
    - MAX_WAIT_SECONDS é só um teto de sanidade (ex: se o horário-alvo
      calculado estiver muito errado por bug); em operação normal a
      espera real (até 11h, cobrindo 08:00 -> 17:55) nunca deve estourar.
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
        print(f"[WARN] Delta de {delta:.0f}s excede o teto de sanidade de {MAX_WAIT_SECONDS}s. "
              f"Executando sem esperar (verifique se o horário-alvo está correto).")
        await send_telegram(
            f"Aviso: delta calculado ({delta:.0f}s) excede o teto de sanidade. "
            f"Executando imediatamente sem esperar {target_time_str}."
        )
        return

    print(f"[SLEEP] Aguardando {delta:.0f}s até {target_time_str} BRT…")
    remaining = delta
    # Dorme em blocos de até 5 minutos para logar progresso e não ficar
    # com um único sleep enorme e opaco.
    CHUNK = 5 * 60
    while remaining > 0:
        step = min(CHUNK, remaining)
        await asyncio.sleep(step)
        remaining -= step
        if remaining > 0:
            print(f"[SLEEP] Ainda faltam ~{remaining:.0f}s até {target_time_str} BRT…")
    print(f"[OK] Horário {target_time_str} BRT atingido.")

# ──────────────────────────────────────────────────────────────────────────────
# Fluxo principal (uma tentativa)
# ──────────────────────────────────────────────────────────────────────────────
async def run_flow_once(attempt: int):
    """
    Executa uma tentativa completa do fluxo: login -> registrar-ponto -> bater ponto.
    Lança exceção se algo falhar (para o chamador decidir sobre retry).
    """
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
            print(f"[STEP 1] (tentativa {attempt}) Navegando para login…")
            max_retries = 3
            for goto_attempt in range(max_retries):
                try:
                    await page.goto("https://app2.pontomais.com.br/login", wait_until="domcontentloaded", timeout=60000)
                    break
                except Exception as e:
                    if goto_attempt < max_retries - 1:
                        print(f"[RETRY] Falha ao carregar login (tentativa {goto_attempt + 1}). Erro: {e}")
                        await asyncio.sleep(5)
                    else:
                        raise

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
            await page.wait_for_selector("h3:has-text('Registrar ponto')", timeout=30000)

            try:
                btn_utilizar_loc = page.locator("small:has-text('Utilizar essa localização')")
                await btn_utilizar_loc.wait_for(state="visible", timeout=10000)
                await btn_utilizar_loc.click()
                print("[OK] Clique em 'Utilizar essa localização'.")
                await page.wait_for_timeout(2000)
            except Exception as e:
                print(f"[INFO] Botão 'Utilizar essa localização' não encontrado ou já processado: {e}")

            # ── VALIDAÇÃO DE ENDEREÇO ──────────────────────────────────────────
            print("[STEP 5] Validando endereço…")
            expected_address = "Av. Dr. Chucri Zaidan, 920"

            try:
                await page.wait_for_selector(f"text={expected_address}", timeout=15000)
                print(f"[OK] Endereço validado: {expected_address}")
            except Exception:
                print(f"[ERRO] Endereço '{expected_address}' não encontrado na página.")
                error_path = "address_not_found.png"
                await page.screenshot(path=error_path)
                await send_telegram(f"Erro: Endereço '{expected_address}' não encontrado.", photo_path=error_path)
                raise Exception("Endereço não validado.")

            # ── BATER PONTO ────────────────────────────────────────────────────
            print("[STEP 7] Clicando 'Bater ponto'…")
            btn_register_selector = "pm-button.btn-register.mt-1 button.pm-primary"
            clicked = False

            try:
                await page.wait_for_selector(btn_register_selector, state="visible", timeout=15000)

                debug_path = "debug_before_click.png"
                await page.screenshot(path=debug_path)
                print(f"[DEBUG] Screenshot salvo em {debug_path}")

                await page.click(btn_register_selector)
                print("[OK] Botão 'Bater ponto' clicado com seletor específico.")
                clicked = True
            except Exception as e:
                print(f"[RETRY] Falha com seletor específico ({e}). Tentando clique via JavaScript...")
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
                if clicked:
                    print("[OK] Botão 'Bater ponto' clicado via JS.")

            if not clicked:
                error_path = "timeout_button.png"
                await page.screenshot(path=error_path)
                await send_telegram("Aviso: O botão 'Bater ponto' não foi encontrado.", photo_path=error_path)
                raise Exception("Botão 'Bater ponto' não encontrado (seletor e JS falharam).")

            await page.wait_for_timeout(3000)

            # Print de confirmação
            ponto_ready_path = "bater_ponto_ready.png"
            await page.screenshot(path=ponto_ready_path)
            await send_telegram("Ponto registrado com sucesso!", photo_path=ponto_ready_path)
            print("[OK] Sucesso total.")
            print("Processo concluído com sucesso!")

        except Exception as e:
            error_path = "error_report.png"
            try:
                await page.screenshot(path=error_path)
            except Exception:
                error_path = None
            print(f"[ERRO] Tentativa {attempt} falhou: {e}")
            # Propaga para o orquestrador de retry decidir o que fazer.
            raise
        finally:
            await browser.close()
            print("Navegador fechado.")


async def run_flow_with_retries():
    """
    Orquestra retries de todo o fluxo (login -> bater ponto).
    Notifica falha definitiva apenas após esgotar as tentativas.
    """
    last_error = None
    for attempt in range(1, MAX_FLOW_RETRIES + 1):
        try:
            await run_flow_once(attempt)
            return  # sucesso, encerra
        except Exception as e:
            last_error = e
            if attempt < MAX_FLOW_RETRIES:
                print(f"[FLOW RETRY] Tentativa {attempt}/{MAX_FLOW_RETRIES} falhou. "
                      f"Aguardando {FLOW_RETRY_DELAY_SECONDS}s antes de tentar novamente…")
                await asyncio.sleep(FLOW_RETRY_DELAY_SECONDS)
            else:
                print(f"[FLOW FAILED] Todas as {MAX_FLOW_RETRIES} tentativas falharam.")

    # Se chegou aqui, esgotou as tentativas.
    await send_telegram(
        f"FALHA DEFINITIVA: {MAX_FLOW_RETRIES} tentativas de bater ponto falharam. "
        f"Último erro: {str(last_error)[:200]}"
    )
    raise last_error


# ──────────────────────────────────────────────────────────────────────────────
# Entrada principal
# ──────────────────────────────────────────────────────────────────────────────
async def main():
    target_time = get_target_time()
    print(f"[INFO] Horário alvo: {target_time} BRT")

    async def full_process():
        await sleep_until_target(target_time)
        await run_flow_with_retries()

    try:
        # Watchdog geral: aborta o processo inteiro se passar do limite,
        # em vez de deixar o job do GitHub Actions rodar até o timeout de 6h.
        await asyncio.wait_for(full_process(), timeout=GLOBAL_TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        msg = (f"FALHA CRÍTICA: processo abortado por watchdog após "
               f"{GLOBAL_TIMEOUT_SECONDS}s sem concluir (alvo era {target_time} BRT).")
        print(f"[WATCHDOG] {msg}")
        await send_telegram(msg)
        raise
    except Exception as e:
        # run_flow_with_retries já notificou a falha definitiva; aqui só logamos.
        print(f"[FATAL] Processo encerrado com erro: {e}")
        raise


if __name__ == "__main__":
    asyncio.run(main())
