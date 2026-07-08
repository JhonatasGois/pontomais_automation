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

# Teto de segurança para sleep_until_target: precisa cobrir o pior caso real
# (disparo às 08:00 mirando 17:55 => ~10h de espera). NÃO reduzir para valores
# baixos (ex: 15 min) — isso reintroduz o bug de execução prematura.
MAX_WAIT_SECONDS = 12 * 60 * 60  # 12 horas

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
# Fluxo principal (uma tentativa)
# ──────────────────────────────────────────────────────────────────────────────
async def run_flow():
    target_time = get_target_time()
    print(f"[INFO] Horário alvo: {target_time} BRT")
    await sleep_until_target(target_time)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={"width": 1280, "height": 720},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            permissions=["geolocation"],
            geolocation={"latitude": -23.6125, "longitude": -46.6995} # Coordenadas aproximadas da Chucri Zaidan, 920
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
            await page.wait_for_selector("h3:has-text('Registrar ponto')", timeout=30000)

            # Tratamento de Erro de Localização (Toasts Vermelhos)
            print("[INFO] Verificando se há erros de localização...")
            toast_error_selector = "div.dx-toast-error, .pm-alert-danger"
            try:
                if await page.locator(toast_error_selector).is_visible(timeout=5000):
                    print("[WARN] Erro de localização detectado via alerta. Tentando recuperar...")
                    # Se houver erro, forçamos o clique no "Utilizar essa localização" do último registro
                    btn_last_loc = page.locator("small:has-text('Utilizar essa localização')")
                    await btn_last_loc.click()
                    print("[OK] Clique em 'Utilizar essa localização' após erro.")
                    await page.wait_for_timeout(3000)
            except:
                pass

            # Tratamento específico: card "Não foi possível obter sua localização"
            # (mensagem em laranja, com o link "Utilizar a localização do meu
            # último registro" logo abaixo — texto diferente do link tratado acima)
            print("[INFO] Verificando se apareceu 'Não foi possível obter sua localização'...")
            try:
                loc_failed_msg = page.locator("text=Não foi possível obter sua localização")
                if await loc_failed_msg.is_visible(timeout=5000):
                    print("[WARN] Localização não obtida pelo navegador. Clicando em 'Utilizar a localização do meu último registro'...")
                    btn_use_last_registered = page.locator("text=Utilizar a localização do meu último registro")
                    await btn_use_last_registered.click()
                    print("[OK] Clique em 'Utilizar a localização do meu último registro' realizado.")
                    await page.wait_for_timeout(3000)
            except Exception:
                pass

            # ── VALIDAÇÃO DE ENDEREÇO (COMPARAÇÃO RIGOROSA) ────────────────────
            print("[STEP 5] Validando e comparando endereços…")

            # 1. Obtém o endereço de referência (Último Registro)
            try:
                # O endereço do último registro fica dentro de um card específico
                # Usamos .first para evitar erro de múltiplos elementos caso o site mude
                last_loc_card = page.locator("div.pm-card:has-text('Localização do meu último registro')")
                last_loc_text = await last_loc_card.locator("div.pm-text-default").filter(has_text="Av. Dr. Chucri Zaidan").first.inner_text()
                last_loc_text = last_loc_text.replace("home", "").replace("Meu local de trabalho", "").strip()
                print(f"[INFO] Endereço de referência (Último): {last_loc_text}")
            except Exception as e:
                print(f"[WARN] Falha ao ler endereço de referência: {e}")
                last_loc_text = "Av. Dr. Chucri Zaidan, 920" # Fallback manual se falhar a leitura

            # 2. Obtém o endereço atual (obtido via GPS/Navegador)
            try:
                # O endereço atual fica no card de "Localização"
                current_loc_card = page.locator("div.pm-card:has-text('Localização')").filter(has_not=page.locator("text='último registro'"))
                current_loc_text = await current_loc_card.locator("div.pm-text-default").inner_text()
                current_loc_text = current_loc_text.replace("home", "").replace("Meu local de trabalho", "").strip()
                print(f"[INFO] Endereço atual detectado: {current_loc_text}")
            except:
                print("[INFO] Endereço atual não detectado automaticamente. Tentando forçar...")
                current_loc_text = ""

            # 3. Comparação e Tomada de Decisão
            # Se o endereço atual for diferente do último, ou estiver vazio, forçamos o uso do último
            if not current_loc_text or last_loc_text[:20] not in current_loc_text:
                print("[WARN] Endereço atual diverge ou não foi obtido. Forçando 'Utilizar essa localização' do último registro...")
                btn_use_last = page.locator("small:has-text('Utilizar essa localização')")
                await btn_use_last.click()
                await page.wait_for_timeout(3000)

                # Re-valida após o clique
                final_check_text = await page.locator("div.pm-card:has-text('Localização')").first.inner_text()
                if last_loc_text[:20] in final_check_text:
                    print("[OK] Endereço corrigido com sucesso para o do último registro.")
                else:
                    raise Exception("Falha crítica: Endereço não pôde ser validado mesmo após tentativa de correção.")
            else:
                print("[OK] Endereço atual validado e coincide com o registro anterior.")

            # ── BATER PONTO ────────────────────────────────────────────────────
            print("[STEP 7] Clicando 'Bater ponto'…")

            # Seletor preciso: botão pm-primary dentro do container btn-register
            btn_register_selector = "pm-button.btn-register.mt-1 button.pm-primary"

            # Fallback chain única: seletor CSS -> clique via JS -> erro/notify.
            # (Antes havia dois blocos "except Exception" seguidos no mesmo try,
            # o que tornava o segundo bloco código morto e inalcançável.)
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
                print(f"[RETRY] Falha com seletor específico ({e}). Verificando se o clique já registrou antes de tentar de novo...")
                try:
                    await page.wait_for_timeout(1500)

                    # O click() do Playwright pode ter efetivamente registrado o
                    # ponto e SÓ DEPOIS lançar exceção (ex: navegação/re-render
                    # destruindo o contexto de execução). Se o botão já sumiu ou
                    # está desabilitado, o clique anterior provavelmente já
                    # funcionou — NÃO clicar de novo via JS, para evitar bater
                    # ponto duas vezes.
                    already_clicked = await page.evaluate("""
                        () => {
                            const btn = [...document.querySelectorAll('button.pm-primary')]
                                .find(b => b.textContent.includes('Bater ponto'));
                            return !btn || btn.disabled;
                        }
                    """)

                    if already_clicked:
                        print("[OK] Botão já não está mais clicável — clique anterior provavelmente teve efeito. Não vou clicar de novo.")
                    else:
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

                except Exception as e2:
                    print(f"[ERRO] Botão não encontrado.")
                    error_path = "timeout_button.png"
                    await page.screenshot(path=error_path)
                    await send_telegram("Aviso: O botão 'Bater ponto' não foi encontrado.", photo_path=error_path)
                    raise e2

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
            raise
        finally:
            await browser.close()
            print("Navegador fechado.")

# ──────────────────────────────────────────────────────────────────────────────
# Orquestração de retries (fluxo completo)
# ──────────────────────────────────────────────────────────────────────────────
MAX_FLOW_RETRIES = 3

async def run_flow_with_retries():
    last_error = None
    for attempt in range(1, MAX_FLOW_RETRIES + 1):
        try:
            print(f"[FLOW] Tentativa {attempt}/{MAX_FLOW_RETRIES}…")
            await run_flow()
            print(f"[FLOW] Sucesso na tentativa {attempt}.")
            return
        except Exception as e:
            last_error = e
            print(f"[FLOW ERROR] Tentativa {attempt}/{MAX_FLOW_RETRIES} falhou: {e}")
            if attempt < MAX_FLOW_RETRIES:
                await asyncio.sleep(10)

    # Todas as tentativas falharam
    msg = f"Falha definitiva após {MAX_FLOW_RETRIES} tentativas: {str(last_error)[:200]}"
    print(f"[FLOW FAILED] {msg}")
    await send_telegram(msg)

# ──────────────────────────────────────────────────────────────────────────────
# Watchdog global — evita que o job fique preso até o timeout padrão (6h) do
# GitHub Actions caso algo trave de forma inesperada.
#
# ATENÇÃO: decisão em aberto — se o disparo externo (cron-job.org) puder
# acontecer bem antes do horário-alvo (ex: 08:00 disparando para um alvo às
# 17:55, ~10h de espera dentro de sleep_until_target), este valor precisa ser
# maior que esse pior caso (recomenda-se ~12-13h). Se o cron externo sempre
# disparar próximo do horário exato, esse timeout pode ser bem menor
# (ex: 1h), já que não have-rá espera longa dentro do script.
# ──────────────────────────────────────────────────────────────────────────────
GLOBAL_TIMEOUT_SECONDS = 13 * 60 * 60  # 13 horas

async def run():
    try:
        await asyncio.wait_for(run_flow_with_retries(), timeout=GLOBAL_TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        msg = f"Watchdog: job abortado após exceder {GLOBAL_TIMEOUT_SECONDS}s sem concluir."
        print(f"[WATCHDOG TIMEOUT] {msg}")
        await send_telegram(msg)

if __name__ == "__main__":
    asyncio.run(run())