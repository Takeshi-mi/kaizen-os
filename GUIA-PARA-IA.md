# Guia para a IA: monte o Kaizen OS com a pessoa

> **Para a pessoa:** entregue esta pasta (ou o zip) ao seu assistente de IA (Claude, ChatGPT, Gemini, Claude Code, Cursor...) e diga:
> *"Leia o GUIA-PARA-IA.md e me ajude a montar o meu Kaizen OS, um passo de cada vez."*
>
> **Para a IA:** você vai conduzir a instalação em conversa. As regras abaixo valem para a conversa inteira.

## Regras de conduta (IA, leia primeiro)

1. **Um passo de cada vez.** Dê no máximo 1 a 3 comandos ou ações por mensagem e espere a pessoa confirmar o resultado (ou colar a saída) antes de seguir.
2. **Pergunte antes de supor.** Sistema operacional, onde o app vai rodar, celular (Android/iPhone) e relógio mudam o caminho.
3. **Comandos prontos para colar.** Sempre para o sistema operacional e o shell da pessoa (PowerShell ≠ bash ≠ zsh). Explique em uma linha o que cada comando faz.
4. **Segredos.** O token de acesso nunca deve ser colado na conversa, em grupos ou em prints. Gere no computador da pessoa e peça para ela confirmar só que funcionou. Se vazar, gere outro.
5. **Verifique antes de avançar.** Cada etapa tem um teste ("Como saber que deu certo"). Não pule.
6. **Pouco costuma funcionar melhor.** Não há limite fixo de hábitos: a pessoa decide. Vale comentar que listas enxutas (3 a 5) são mais fáceis de manter e que o app tem "graduar" para abrir espaço; se ela quiser se travar num número, use `config limite N`. A decisão é dela.
7. **Tom.** Simples, encorajador, sem jargão. Recaída é dado, não sentença: isso vale para o app e para a instalação.

## O que é o Kaizen OS

Kaizen (改善): melhoria contínua, um pouco todo dia. Os hábitos do dia são chamados de **âncoras**: poucos, pequenos e inegociáveis.


Um PWA (site que se instala como app no celular) com:

- **Hoje:** check-in Sim/Não dos hábitos do dia, sono da noite (se tiver relógio), passos, energia, ansiedade, nota e o mapa **Kaizen** (21 dias).
- **Sono, Corpo e Hábitos:** gráficos de tendência.
- **Dojo:** XP, níveis, sequências, conquistas com som e confete, e a gestão dos hábitos (criar, graduar, pausar).
- **Servidor:** um único `app.py` em Python 3.9+ sem dependências, banco SQLite local. Nada vai para a nuvem de ninguém.
- **Relógio (opcional, Android):** relógio/pulseira → app do fabricante → **Health Connect** → app **HC Webhook** → servidor. Preenche sono, passos, treinos, SpO₂ etc.

### Modelo dos hábitos (por que não vira um checklist infinito)

- Cada hábito tem início, status (`ativo`, `consolidado`, `pausado`, `arquivado`) e fim.
- **Limite de ativos opcional** (padrão: sem limite; `config limite 5` trava em 5). Hábitos que viram automáticos (o app sugere a partir de 85% em 21 dias) se **graduam**; dá também para **pausar**.
- Graduados saem do check-in diário mas ficam no histórico e viram conquista 🎓.
- **Fases** são blocos de tempo (ex.: "Fase 1 · só as âncoras", 14 dias). Ao fim de uma fase, a pessoa revê: gradua o que está automático e escolhe no máximo 1 ou 2 mini-hábitos novos.

## Roteiro da conversa

### Etapa 0 — Entender a pessoa (sem comandos)

Pergunte, em uma mensagem só:

1. Qual computador vai **ficar ligado** para rodar o app? (Notebook/PC que fica ligado, mini-PC, Raspberry Pi, servidor/VPS.) Qual sistema: Windows, macOS ou Linux?
2. Celular: Android ou iPhone?
3. Usa relógio ou pulseira? Qual e com qual app? (Mi Fitness, Samsung Health, Fitbit/Google, Garmin, Zepp/Amazfit…)
4. Quais 3 a 5 mini-hábitos quer ancorar agora? Para cada um: nome curto, um detalhe que torna fácil ("20 minutos já contam") e um emoji.
5. Como quer chamar o app? (padrão: "Kaizen OS"; ex.: "Kaizen da Ana")

Escolha o caminho:

| Situação | Caminho |
|---|---|
| Linux (inclui Raspberry Pi e VPS) | **A — Linux com systemd** |
| macOS | **B — macOS** (Python já vem; serviço via `launchd` ou só deixar rodando) |
| Windows | **C — Windows com WSL** (Ubuntu dentro do Windows) ou **Docker Desktop** |
| Tem Docker em qualquer sistema | **D — Docker** |

> Se o computador desliga à noite, o app fica fora do ar nesse período. Para quem não tem nada ligado direto, uma VPS barata ou um Raspberry Pi resolvem.

### Etapa 1 — Personalizar o `seed.json`

Com as respostas da etapa 0, gere o arquivo `app/seed.json` a partir de `app/seed.example.json` e mostre para a pessoa colar.

- `id`: minúsculas, números e `_` (ex.: `agua`, `leitura_10min`). Não pode ser `data`, `nota`, `dormiu`, `sono_h`, `tela_h`, `energia`, `ansiedade`.
- `icone`: um emoji (ex.: `"💧"`) ou um dos ícones prontos: `celular`, `acordou7`, `manha`, `academia`, `foco`, `agua`, `livro`, `meditar`, `caminhar`, `cama`, `check`.
- `xp`: 10 para hábitos leves, 15 a 25 para os difíceis.
- `relogio`: nome que aparece na tela (ex.: `"Galaxy Watch"`; sem relógio, `"Relógio"`).
- `fase.inicio`: hoje (AAAA-MM-DD); `fase.dias`: 14.
- `combinados`: 3 a 6 frases curtas que a pessoa quer lembrar.
- `marcos`: datas importantes (opcional), ex.: revisão da fase.

O `seed.json` só é lido **na primeira execução** (banco vazio). Depois, mudanças são feitas pelo app (Dojo) ou pela linha de comando.

**Como saber que deu certo:** `python3 -c "import json;json.load(open('app/seed.json'));print('ok')"` imprime `ok`.

### Etapa 2 — Rodar o servidor

Requisito: Python 3.9 ou mais novo (`python3 --version`).

1. Gerar o token (no computador da pessoa, nunca no chat):
   - Linux/macOS/WSL: `python3 -c "import secrets;print(secrets.token_urlsafe(32))"`
2. Criar o arquivo de ambiente `~/.config/kaizen-os/env` com permissão só do usuário (`chmod 600`):
   ```
   ANCORAS_TOKEN=<token>
   ANCORAS_DB=/home/<usuario>/.local/share/kaizen-os/kaizen.db
   ANCORAS_TZ=America/Sao_Paulo
   ```
3. Teste manual:
   ```bash
   mkdir -p ~/.local/share/kaizen-os
   set -a; . ~/.config/kaizen-os/env; set +a
   python3 app/app.py serve --host 127.0.0.1 --port 8787
   ```
   Em outro terminal: `curl -s localhost:8787/saude` → `{"ok": true}`.
4. Serviço permanente:
   - **Linux (systemd de usuário):** copie `deploy/kaizen-os.service` para `~/.config/systemd/user/`, ajuste o caminho do `app.py`, e rode:
     `systemctl --user daemon-reload && systemctl --user enable --now kaizen-os && loginctl enable-linger $USER`
   - **Docker:** `deploy/docker-compose.yml` (ver comentários no arquivo). `docker compose up -d`.
   - **macOS:** o mais simples é deixar rodando num terminal; se quiser serviço, gere um `launchd` plist com a pessoa.
   - **Windows:** instale o WSL (`wsl --install`, reinicia), abra o Ubuntu e siga o caminho Linux.

**Como saber que deu certo:** `curl -s localhost:8787/saude` responde `{"ok": true}` mesmo depois de fechar o terminal (serviço) ou reiniciar.

### Etapa 3 — Acesso pelo celular com Tailscale (privado, de graça)

O app escuta só em `127.0.0.1`. Para o celular acessar com HTTPS sem expor nada na internet:

1. Criar conta em tailscale.com e instalar o Tailscale **no computador do app** e **no celular**, na mesma conta.
2. No painel do Tailscale (admin → DNS): ligar **MagicDNS** e **HTTPS Certificates**.
3. No computador do app:
   ```bash
   sudo tailscale serve --bg --https=8443 http://127.0.0.1:8787
   tailscale serve status        # mostra o endereço https://NOME.SEU-TAILNET.ts.net:8443
   ```
   (Se a porta 443 estiver livre, pode usar `--https=443` e o endereço fica sem `:8443`.)
4. Colocar o endereço em `ANCORAS_PUBLIC_URL=https://NOME.SEU-TAILNET.ts.net:8443` no arquivo env e reiniciar o serviço.
5. Montar o link de primeiro acesso **no computador** e abrir no celular uma única vez:
   `echo "$ANCORAS_PUBLIC_URL/?k=$ANCORAS_TOKEN"` (com o env carregado). O link grava um cookie de 1 ano; depois disso, basta o endereço sem `?k=`.

**Como saber que deu certo:** com o Tailscale ligado no celular, o endereço abre a tela "Hoje" com os hábitos do `seed.json`.

### Etapa 4 — Instalar como app

- **Android (Chrome):** menu ⋮ → **Instalar app** (ou o botão "Instalar o app" em Hábitos → Relógio e app).
- **iPhone (Safari):** Compartilhar → **Adicionar à Tela de Início**.
- **Computador (Chrome/Edge):** ícone de instalar na barra de endereço.

### Etapa 5 (opcional) — Relógio/pulseira no Android

Funciona com qualquer app que escreva no **Health Connect** (Mi Fitness, Samsung Health, Fitbit/Google, Garmin Connect, Zepp…).

1. No app do fabricante, ligar a sincronização com o **Health Connect** (ex.: Mi Fitness → Perfil → Dados de terceiros → Health Connect).
2. Gerar um segundo token, só para o webhook, e pôr no env: `ANCORAS_HOOK_TOKEN=<outro token>`; reiniciar o serviço.
3. Instalar o **HC Webhook** (código aberto). Versão gratuita: APK `app-foss-release.apk` na página de releases de `github.com/mcnaveen/health-connect-webhook` (a versão da Play Store é paga e é a mesma coisa). O Android vai pedir permissão para "instalar apps desconhecidos".
4. No HC Webhook:
   - Conceder acesso ao Health Connect.
   - Webhooks → adicionar → colar a URL que aparece no app em **Hábitos → Relógio e app → Copiar URL** (formato JSON).
   - Data types: Sono, Passos, Distância, Calorias ativas, Frequência cardíaca, Treinos, SpO₂. **Deixe "Total calories" desligado** (é ruído e pesa).
   - Sincronizar a cada 60 min. Fazer uma sincronização manual dos últimos 30 dias para trazer o histórico.
5. Tirar o HC Webhook e o Tailscale da otimização de bateria do Android.

**Como saber que deu certo:** em Hábitos → Relógio e app, a tabela "O que já chegou" lista sono, passos etc.; a aba Sono mostra as noites.

**iPhone:** não tem Health Connect. Use o check-in manual (o app funciona igual). Integração com Apple Saúde fica fora deste guia.

### Etapa 6 — Primeiro dia e ritual

- Marcar os hábitos de hoje na tela Hoje e ouvir o primeiro som 🙂.
- Combinar com a pessoa um horário fixo para o check-in (ex.: 20h) e, se ela usa um agente de IA no mesmo computador, ele pode registrar pelo chat com a CLI (abaixo).
- No fim da fase (14 dias): ver no Dojo quais hábitos estão em 85%+ e graduar; escolher os próximos mini-hábitos (adicionar poucos por vez costuma funcionar melhor).

### Etapa 7 (recomendada) — Conectar ao agente pessoal

O Kaizen OS foi feito para ser usado junto com um agente pessoal (Hermes Agent, Claude Code, OpenClaw, Codex…) rodando no mesmo computador.

1. Entregue o **`AGENTE.md`** ao agente como skill/instrução permanente.
2. Crie o atalho `kaizen` descrito no `AGENTE.md`.
3. Combine com a pessoa um check-in agendado (ex.: 20h, pelo Telegram/WhatsApp do agente) que pergunta só o que falta, e uma revisão semanal.

**Como saber que deu certo:** a pessoa manda "fiz meu treino" para o agente e o item aparece marcado no app em até 1 minuto.

## Referência rápida da CLI

Com o env carregado (`set -a; . ~/.config/kaizen-os/env; set +a`):

```bash
python3 app/app.py set hoje academia=sim nota="treino curto"   # hoje | ontem | AAAA-MM-DD
python3 app/app.py get hoje
python3 app/app.py resumo                                       # últimos 7 dias
python3 app/app.py habitos                                      # status e % em 21 dias
python3 app/app.py habito novo agua "Beber 2 L" "garrafa na mesa" "💧" 10
python3 app/app.py habito graduar agua    # ou: pausar | reativar | arquivar
python3 app/app.py fase nova "Fase 2 · água" 2026-12-07 2026-12-20
python3 app/app.py config nome "Kaizen da Ana"
python3 app/app.py export registro.csv                          # backup legível
```

## Problemas comuns

| Sintoma | Causa provável | Solução |
|---|---|---|
| Página "401 Abra o link com ?k=" | Cookie ainda não gravado | Abrir uma vez o link com `?k=TOKEN` no mesmo navegador |
| Celular não abre o endereço | Tailscale desligado no celular | Ligar o Tailscale; conferir a mesma conta |
| `tailscale serve` dá "Access denied" | Precisa de root | Usar `sudo`, ou `sudo tailscale set --operator=$USER` uma vez |
| Erro de certificado no Tailscale | HTTPS Certificates desligado | Ligar no painel admin → DNS |
| Sono não aparece | App do fabricante não sincronizou | Abrir o app do relógio de manhã; conferir permissões do Health Connect e otimização de bateria |
| "limite de N hábitos ativos" | A pessoa ligou um limite (`config limite N`) | Graduar/pausar um hábito, ou `config limite 0` para tirar o limite |
| Mudei o `seed.json` e nada mudou | Seed só vale com banco vazio | Use o Dojo/CLI, ou apague o banco (perde histórico) |

## Privacidade

- Os dados ficam só no computador da pessoa (`kaizen.db`) e nos payloads do relógio em `~/.local/share/kaizen-os/payloads/`.
- Backup: copiar `kaizen.db` ou usar `export`.
- O token do webhook só grava dados de saúde; não lê nada.
