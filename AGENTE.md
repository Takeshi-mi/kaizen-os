# AGENTE.md — como um agente pessoal opera o Kaizen OS

Use este arquivo como skill/instrução do seu agente (Hermes Agent, Claude Code, OpenClaw, Codex…). Ele assume que o agente roda **no mesmo computador** do Kaizen OS, com acesso ao terminal.

## Configuração

Crie um atalho para a CLI (ajuste os caminhos):

```bash
# ~/.local/bin/kaizen
#!/usr/bin/env bash
set -a; . "$HOME/.config/kaizen-os/env"; set +a
exec python3 "$HOME/kaizen-os/app/app.py" "$@"
```

`chmod +x ~/.local/bin/kaizen`. O arquivo `env` tem `ANCORAS_TOKEN`, `ANCORAS_DB` e o resto. **Nunca imprima nem envie tokens em mensagens.**

## Comandos

| Objetivo | Comando |
|---|---|
| Ver o dia (hábitos marcados, sono, energia, nota) | `kaizen get hoje` (ou `ontem`, `AAAA-MM-DD`) |
| Registrar | `kaizen set hoje academia=sim nota="treino de 40 min"` |
| Apagar uma marca | `kaizen set hoje foco=` |
| Últimos 7 dias | `kaizen resumo` |
| Hábitos, status e % em 21 dias | `kaizen habitos` |
| Novo hábito | `kaizen habito novo agua "Beber 2 L" "garrafa na mesa" "💧" 10` |
| Graduar / pausar / reativar / arquivar | `kaizen habito graduar agua` |
| Nova fase | `kaizen fase nova "Fase 2 · água" 2026-12-07 2026-12-20` |
| Limite de ativos (0 = sem limite) | `kaizen config limite 5` |
| Histórico em CSV | `kaizen export registro.csv` |

Campos do dia além dos hábitos: `dormiu` (HH:MM em que pegou no sono na noite anterior), `sono_h` (0–14), `tela_h` (0–24), `energia` e `ansiedade` (0–10), `nota` (até 500 caracteres). Os ids dos hábitos vêm de `kaizen habitos`; não suponha.

Se o relógio estiver conectado, `dormiu` e `sono_h` chegam sozinhos (fonte `relogio`). A API local também expõe `GET /api/saude?dias=N` (sono com fases, passos, treinos, FC, SpO₂) com `Authorization: Bearer $ANCORAS_TOKEN`.

## Rituais sugeridos

1. **Registro por conversa.** Quando a pessoa contar algo ("treinei", "dormi tarde", "fiz o foco"), rode `kaizen get hoje`, grave com `kaizen set hoje ...` e confirme em uma linha.
2. **Check-in noturno (ex.: 20h).** Rode `kaizen get hoje` e pergunte **só** o que estiver vazio entre os hábitos ativos. Se o relógio já trouxe o sono, apenas informe o horário. Depois, lembre de largar as telas.
3. **Revisão semanal.** Use `kaizen resumo` e `kaizen habitos`: o que funcionou, o que travou, uma prioridade para a semana.
4. **Fim de fase.** Hábitos com 85%+ em 21 dias são candidatos a graduar. Pergunte antes de graduar ou criar hábitos; sugira no máximo 1 ou 2 novos por vez.

## Tom

Gentil e direto. Recaída é dado, não sentença: nada de sermão. Comemore sequências e graduações; o app já toca som e mostra confete quando a pessoa abre.

## Limites

- Não crie, gradue ou apague hábitos sem pedido da pessoa.
- Não invente dados: se não sabe, pergunte ou deixe vazio.
- Dados de saúde são sensíveis: não envie para terceiros nem para outros agentes sem pedido explícito.
