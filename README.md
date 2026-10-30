# Pontomais Automation

Automação em Python para registrar o ponto no sistema Ponto Mais, com validação de localização, tratamento de falhas e notificações por Telegram.

## Visão geral

Este projeto foi desenvolvido para automatizar o registro de ponto em horários definidos usando Playwright em modo headless. A rotina realiza login, valida a localização, usa o último endereço conhecido como fallback quando necessário, registra o ponto e envia mensagens de status para o Telegram.

## Importância do cron-job externo

O código e o workflow deixam explícito que o agendamento nativo do GitHub Actions (`schedule`/cron) não é confiável para disparos pontuais no horário exato. Em ambientes compartilhados, a execução pode atrasar de minutos a horas, o que é crítico para registrar o ponto corretamente.

Por isso, o projeto foi pensado para ser disparado por um serviço externo de cron, como o `cron-job.org`, com `workflow_dispatch` do GitHub Actions. Esse modelo reduz o risco de atrasos e garante que a execução aconteça no momento mais próximo do horário-alvo.

## Funcionalidades

- Login automático no Ponto Mais;
- navegação até a tela de registro do ponto;
- validação da localização do navegador e comparação com o último registro;
- uso do endereço do último ponto como fallback quando a localização atual não é confiável;
- clique automatizado no botão de registro do ponto;
- screenshots de debug e relatórios de erro;
- envio de mensagens e imagens para o Telegram;
- retry em falhas do fluxo;
- watchdog global para interromper a execução caso o processo trave.

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

## Requisitos e dependências

### Dependências principais

- Python 3.9+
- Playwright
- python-telegram-bot
- python-dotenv

### Arquivo de dependências

O projeto inclui o arquivo `requirements.txt`:

```txt
playwright>=1.47.0
python-telegram-bot>=22.0.0
python-dotenv>=1.0.0
```

Além disso, é necessário instalar o chromium do Playwright:

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

O workflow em `.github/workflows/pontomais_checkin.yml` usa `workflow_dispatch`, ou seja, ele é disparado manualmente ou por um gatilho externo.

Esse é um ponto chave do projeto: o cron nativo do GitHub Actions não é recomendado para execuções críticas de ponto, porque ele roda em infraestrutura compartilhada e pode atrasar de forma significativa.

A estratégia adotada é:

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

O projeto inclui mecanismos para aumentar confiabilidade:

- retries em etapas críticas;
- fallback para endereço do último registro;
- screenshots para depuração;
- envio de alertas por Telegram quando algo falha;
- timeout global para evitar execução infinita;
- retry do fluxo completo em caso de falha.

## Uso gratuito e sem garantia

Este projeto é disponibilizado de forma livre e gratuita para estudo, uso pessoal e adaptação. Ele é entregue "como está", sem garantia de funcionamento contínuo, sem suporte formal e sem compromisso de manutenção permanente.

O código pode ser reutilizado e modificado, desde que seja respeitado o contexto de uso e as políticas internas do ambiente em que for aplicado.

## Licença

Este repositório não possui licença formal definida. O projeto foi publicado como material livre para uso e estudo, sem garantia e sem suporte oficial. Caso queira reutilizar em ambiente corporativo ou profissional, confirme com o responsável do projeto antes de aplicar em produção.

A intenção aqui não é oferecer garantia comercial nem suporte contínuo. O objetivo é compartilhar a solução de forma aberta e útil para quem quiser estudar, adaptar ou evoluir a automação.

## Contribuição e continuidade

Este projeto foi publicado como uma referência prática e estável para uso e estudo. Não há promessa de manutenção contínua por parte do autor.

A comunidade pode continuar o projeto em branches próprias e criar forks para evolução, mas esse repositório principal não será utilizado como base para integração indiscriminada de alterações sem validação e sem garantia de que o código será seguro, estável e adequado ao uso.

Além disso, o código não deve ser usado para automações que violem políticas internas, regras de uso de sistemas corporativos ou qualquer comportamento que configure uso indevido ou ilícito.

## Contato

Se quiser entrar em contato, envie um e-mail para:

- jhonatasgois@gmail.com

Não há PIX, doação ou cobrança pública vinculada ao projeto. O repositório deve ser entendido como software gratuito e livre para uso, estudo e adaptação.

## Segurança

- Nunca compartilhe arquivos `.env` ou `pontomais.env`;
- mantenha os secrets do GitHub protegidos;
- revise com frequência os seletores e as dependências do projeto.

## Resumo

Este projeto automatiza o registro do ponto em um ambiente web, validando localização e monitorando o processo por Telegram. O uso de cron-job externo é fundamental para garantir que o disparo aconteça no momento correto, evitando atrasos comuns no cron do GitHub Actions.
