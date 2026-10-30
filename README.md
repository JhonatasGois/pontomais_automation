# Pontomais Automation

Automação em Python para registrar o ponto no sistema Ponto Mais, com validação de localização, tratamento de falhas e notificações via Telegram.

## Visão geral

Este projeto foi desenvolvido para automatizar o registro de ponto em horários definidos, usando o navegador em modo headless com Playwright, e enviar status do processo ao Telegram. A rotina executa um fluxo completo que inclui login, navegação, validação de localização, clique no botão de registrar ponto e respostas automáticas em caso de erro.

## Importância do cron-job externo

O código e o workflow deixam explícito que o agendamento nativo do GitHub Actions (`schedule`/cron) não é confiável para disparos pontuais no horário exato. Em ambientes compartilhados, a execução pode atrasar de minutos a horas, o que seria crítico para registrar o ponto corretamente.

Por isso, o projeto foi pensado para ser disparado por um serviço externo de cron, como o `cron-job.org`, com `workflow_dispatch` do GitHub Actions. Esse modelo garante que a execução aconteça no horário mais próximo do alvo desejado e reduz o risco de atrasos no registro.

## Funcionalidades

- Login automático no Ponto Mais;
- navegação até a tela de ponto;
- validação da localização do navegador e comparação com o último registro;
- uso do endereço do último ponto como fallback quando a localização atual não é confiável;
- clique automatizado no botão de registro do ponto;
- screenshots de debug e relatório de erro;
- envio de mensagens e imagens para o Telegram;
- retry em falhas do fluxo;
- watchdog global para abortar a execução se o processo travar.

## Estrutura do projeto

```text
.
├── .github/
│   └── workflows/
│       └── pontomais_checkin.yml
├── .gitignore
├── pontomais_automation.py
├── README.md
```

## Requisitos

- Python 3.9+
- Playwright
- python-telegram-bot
- python-dotenv
- navegador Chromium instalado via Playwright
- credenciais válidas do Ponto Mais
- token e chat ID do Telegram

## Instalação

1. Clone o repositório:

```bash
git clone https://github.com/JhonatasGois/pontomais_automation.git
cd pontomais_automation
```

2. Crie um ambiente virtual:

```bash
python -m venv .venv
source .venv/bin/activate
```

3. Instale as dependências:

```bash
pip install playwright python-telegram-bot python-dotenv
playwright install chromium --with-deps
```

## Configuração

Crie um arquivo `.env` ou `pontomais.env` na raiz do projeto com as informações abaixo:

```env
PONTOMAIS_LOGIN=seu_usuario
PONTOMAIS_PASSWORD=sua_senha
TELEGRAM_TOKEN=seu_token_telegram
TELEGRAM_CHAT_ID=seu_chat_id
```

O script carrega automaticamente ambos os arquivos, caso existam:

- `.env`
- `pontomais.env`

No GitHub Actions, essas variáveis devem ser configuradas como secrets:

- `PONTOMAIS_LOGIN`
- `PONTOMAIS_PASSWORD`
- `TELEGRAM_TOKEN`
- `TELEGRAM_CHAT_ID`

## Execução local

Para executar manualmente:

```bash
python pontomais_automation.py
```

O fluxo principal aguarda um horário alvo definido na constante:

```python
TARGET_TIMES = ["08:00", "13:00", "14:00", "17:48"]
```

## GitHub Actions e cron-job

O workflow definido em `.github/workflows/pontomais_checkin.yml` utiliza `workflow_dispatch`, ou seja, ele é executado manualmente ou por um gatilho externo.

Esse é um ponto importante do projeto: o cron nativo do GitHub Actions não é recomendado para execuções críticas de ponto, porque ele roda em infraestrutura compartilhada e pode atrasar significativamente.

A estrategia adotada é:

1. um serviço externo (como `cron-job.org`) dispara o workflow em horários específicos;
2. o GitHub Actions inicia a execução;
3. o script valida o momento e continua o fluxo exatamente quando necessário;
4. o Telegram informa sucesso, falha ou timeout.

## Fluxo de execução

1. O script carrega as variáveis de ambiente;
2. calcula o horário alvo mais próximo;
3. espera até o horário desejado, com limite de segurança;
4. inicia o navegador Playwright;
5. acessa a página de login do Ponto Mais;
6. autentica o usuário;
7. abre a tela de registrar ponto;
8. valida a localização e usa o último registro como fallback;
9. clica no botão de envio do ponto;
10. envia mensagem de confirmação ou erro para o Telegram.

## Tratamento de erros

O projeto inclui mecanismos importantes para aumentar confiabilidade:

- retries em etapas críticas;
- fallback para endereço do último registro;
- screenshots para depuração;
- envio de alertas por Telegram quando algo falha;
- timeout global para evitar a execução eterna;
- retry do fluxo completo em caso de falha.

## Observações importantes

- O Ponto Mais pode alterar a interface do sistema, então os seletores do Playwright exigem manutenção periódica.
- Dados sensíveis devem permanecer fora do controle de versão.
- O uso desta automação deve respeitar a política da empresa e as regras do sistema de ponto.

## Segurança

- Nunca compartilhe arquivos `.env` ou `pontomais.env`;
- mantenha os secrets do GitHub protegidos;
- revise com frequência os seletores e as dependências do projeto.

## Licença

Não há licença explícita no repositório. Antes de reutilizar ou distribuir o projeto, confirme a política interna da organização ou do responsável pelo projeto.

## Resumo

Este projeto automatiza o registro do ponto em um ambiente web, validando localização e monitorando o processo por Telegram. O uso de cron-job externo é fundamental para garantir que o disparo aconteça no momento correto, evitando atrasos comuns no cron do GitHub Actions.
