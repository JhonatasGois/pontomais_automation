# Pontomais Automation

Automação em Python para registrar o ponto no sistema Ponto Mais, com validação de localização, tratamento de falhas e notificações por Telegram.

## Visão geral

Este projeto automatiza o registro de ponto em horários definidos usando Playwright em modo headless. A rotina realiza login, verifica a localização do navegador, usa o último endereço conhecido como fallback quando necessário, registra o ponto e envia notificações para o Telegram com o status da execução.

O objetivo principal é reduzir a intervenção manual e manter o processo monitorado em tempo real.

## Por que o cron-job externo é importante

O workflow do GitHub Actions usa `workflow_dispatch`, e o código deixa explícito que o agendamento nativo do GitHub Actions (`schedule`/cron) não é confiável para disparos pontuais no horário exato. Em ambientes compartilhados, a execução pode atrasar por minutos ou até horas.

Para automatizar o ponto de forma segura e no horário correto, o projeto foi pensado para ser disparado por um serviço externo de cron, como `cron-job.org`, que aciona o workflow com mais precisão.

Esse é um detalhe importante do projeto: o envio externo evita atrasos comuns do cron do GitHub Actions e melhora a confiabilidade da marcação.

## Funcionalidades

- Login automático no Ponto Mais;
- navegação até a tela de registro do ponto;
- validação da localização do navegador e comparação com o último registro;
- uso do endereço do último ponto como fallback quando a localização atual não é confiável;
- clique automatizado no botão de registro do ponto;
- screenshots para debug e diagnóstico de erro;
- envio de mensagens e imagens para o Telegram;
- retry em falhas de conexão ou fluxo;
- timeout global para evitar execução travada por tempo indefinido.

## Estrutura do projeto

```text
.
├── .github/
│   └── workflows/
│       └── pontomais_checkin.yml
├── .gitignore
├── pontomais_automation.py
├── requirements.txt
├── README.md
```

## Requisitos

- Python 3.9+
- Playwright
- python-telegram-bot
- python-dotenv
- Chromium instalado via Playwright
- credenciais válidas do Ponto Mais
- token e chat ID do Telegram

## Dependências

O projeto inclui o arquivo `requirements.txt` com as dependências principais:

```txt
playwright>=1.47.0
python-telegram-bot>=22.0.0
python-dotenv>=1.0.0
```

Para instalar o Chromium do Playwright:

```bash
playwright install chromium --with-deps
```

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
pip install -r requirements.txt
playwright install chromium --with-deps
```

## Configuração

Crie um arquivo `.env` ou `pontomais.env` na raiz do projeto com as seguintes variáveis:

```env
PONTOMAIS_LOGIN=seu_usuario
PONTOMAIS_PASSWORD=sua_senha
TELEGRAM_TOKEN=seu_token_telegram
TELEGRAM_CHAT_ID=seu_chat_id
```

O script carrega automaticamente ambos os arquivos, caso existam:

- `.env`
- `pontomais.env`

No GitHub Actions, as mesmas variáveis devem ser configuradas como secrets:

- `PONTOMAIS_LOGIN`
- `PONTOMAIS_PASSWORD`
- `TELEGRAM_TOKEN`
- `TELEGRAM_CHAT_ID`

## Execução local

Para executar manualmente:

```bash
python pontomais_automation.py
```

A constante abaixo define os horários alvo usados no fluxo:

```python
TARGET_TIMES = ["08:00", "13:00", "14:00", "17:48"]
```

## GitHub Actions e cron-job externo

O workflow em `.github/workflows/pontomais_checkin.yml` usa `workflow_dispatch`, ou seja, ele pode ser acionado manualmente ou por um gatilho externo.

Esse desenho foi escolhido porque o cron nativo do GitHub Actions não é o mecanismo mais confiável para execuções críticas em horários exatos. Isso é especialmente importante quando a automação precisa bater o ponto em momentos determinados.

A estratégia adotada é:

1. um serviço externo, como `cron-job.org`, dispara o workflow;
2. o GitHub Actions inicia a execução;
3. o script valida o momento e segue o fluxo de registro;
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

O projeto inclui vários mecanismos para aumentar confiabilidade:

- retries em etapas críticas;
- fallback para o último endereço registrado;
- screenshots para depuração;
- notificações via Telegram em caso de falha;
- watchdog para interromper a execução se o processo travar;
- retry do fluxo completo em caso de erro.

## Uso gratuito e sem garantia

Este projeto é disponibilizado de forma livre e gratuita para estudo, uso pessoal e adaptação. Ele é entregue "como está", sem garantia de funcionamento contínuo, sem suporte formal e sem compromisso de manutenção permanente.

O código pode ser reutilizado e modificado, desde que seja respeitado o contexto de uso e as políticas internas do ambiente em que for aplicado.

## Licença

Este repositório não possui licença formal definida. O projeto foi disponibilizado como material livre para uso e estudo, sem garantia e sem suporte oficial.

Se for reutilizar em ambiente corporativo, profissional ou de produção, confirme com o responsável do projeto antes de aplicar o código em sistemas reais.

## Contribuição e continuidade

Este projeto foi publicado como referência prática e estável para uso e estudo. Não há promessa de manutenção contínua por parte do autor.

A comunidade pode continuar o projeto em branches próprias e criar forks para evolução, mas esse repositório principal não será usado como base para integração indiscriminada de alterações sem validação.

Além disso, o código não deve ser usado para automações que violem políticas internas, regras de uso de sistemas corporativos ou qualquer comportamento que configure uso indevido ou ilícito.

## Contato

Se quiser entrar em contato, envie um e-mail para:

- jhonatasgois@gmail.com

Não há PIX, doação ou cobrança pública vinculada ao projeto. O repositório deve ser entendido como software gratuito e livre para uso, estudo e adaptação.

## Segurança

- Nunca compartilhe arquivos `.env` ou `pontomais.env`;
- mantenha os secrets do GitHub protegidos;
- revise com frequência os seletores e as dependências do projeto;
- trate dados pessoais e credenciais com cuidado.

## Observações finais

Este projeto automatiza o registro do ponto em um ambiente web, validando localização e monitorando o processo por Telegram. O uso de cron-job externo é fundamental para garantir que o disparo aconteça no momento certo, evitando atrasos comuns no cron do GitHub Actions.

Se você deseja adaptar ou evoluir a automação, faça isso em uma branch própria ou em um fork, e mantenha a responsabilidade de validar o comportamento antes de usar em produção.
