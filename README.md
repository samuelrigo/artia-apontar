# artia-apontar

Skill do [Claude Code](https://claude.com/claude-code) que lê seus commits do
git, agrupa por tarefa/dia, estima horas trabalhadas e cria os apontamentos
correspondentes no [Artia](https://artia.com) — sempre te mostrando uma tabela
de revisão e pedindo confirmação antes de gravar qualquer coisa.

Nada aqui é software oficial do Artia. É um cliente independente da API
GraphQL pública deles (`https://api.artia.com/graphql`), construído a partir
de uma coleção Postman própria.

## Por quê

Apontar horas manualmente todo dia é chato e fácil de esquecer. O git já sabe
o que você fez e quando — essa skill usa isso como fonte de verdade e só pede
pra você revisar/ajustar antes de mandar pro Artia.

## Como funciona

1. Lê `git log` dos repositórios configurados, no período pedido
2. Agrupa commits por `(repositório, dia, branch)`
3. Estima horas por sessão de trabalho (quebra a sessão quando o intervalo
   entre commits passa de um limite configurável)
4. Busca as atividades do projeto no Artia e casa cada grupo com a atividade
   de título mais parecido (top-3 candidatas, sem decidir sozinho em caso de
   empate)
5. Verifica se já existe apontamento naquele dia pra não duplicar
6. Mostra uma tabela markdown pra você revisar e editar
7. Só cria os apontamentos (`createTimeEntry`) depois da sua confirmação
   explícita

Detalhes completos do fluxo estão em [`SKILL.md`](./SKILL.md).

## Instalação

```bash
git clone git@github.com:samuelrigo/artia-apontar.git ~/.claude/skills/artia-apontar
```

(ou copie a pasta pra dentro de `~/.claude/skills/` manualmente)

Depois:

```bash
cp ~/.claude/skills/artia-apontar/config.example.json ~/.config/artia/config.json
```

Edite `~/.config/artia/config.json`:

- `authorMatch`: nomes/emails que aparecem no seu `git log` como autor
- `repos`: caminho absoluto de cada repositório → `organizationId`,
  `accountId` (grupo de trabalho no Artia — aparece na URL do app) e
  `folderId` (descubra rodando `python3 artia.py folders --account <ID>`)
- `defaults.timeEntryStatusId`: confira qual é o status correto pro seu fluxo
  (crie um apontamento manual na UI do Artia e olhe o campo
  `timeEntryStatusId` dele via `artia.py time-entries`)

Exporte suas credenciais do Artia (nunca ficam salvas em arquivo, só em
variável de ambiente):

```bash
export ARTIA_EMAIL="seu-email@exemplo.com"
export ARTIA_PASSWORD="sua-senha"
```

## Uso

```
/artia-apontar hoje --dry-run
/artia-apontar ontem
/artia-apontar 2026-07-20..2026-07-22
/artia-apontar 7d meu-repo
```

`--dry-run` mostra a tabela sem postar nada. Sem essa flag, a skill ainda
para e pede confirmação antes de gravar — nunca cria apontamento sozinha.

## `artia.py`

CLI standalone (só stdlib, sem dependências) que a skill usa por baixo dos
panos, mas que também funciona sozinho:

```
python3 artia.py login
python3 artia.py whoami
python3 artia.py projects --account <ID>
python3 artia.py folders --account <ID>
python3 artia.py activities --folder <ID> --mine
python3 artia.py time-entries --account <ID> --activity <ID> --date 2026-07-22
python3 artia.py create-entry --account <ID> --activity <ID> --date 2026-07-22 \
  --start 09:00 --duration 1.5 --status <ID> --obs "..."   # sem --yes = dry-run
python3 artia.py raw --query '...'   # qualquer query/mutation GraphQL
```

## Segurança

- Senha nunca é gravada em disco — só lida de `ARTIA_EMAIL`/`ARTIA_PASSWORD`
  no ambiente, a cada login
- Só o token JWT é cacheado (`~/.cache/artia/token.json`, modo `0600`),
  expira sozinho
- `create-entry` exige `--yes` explícito pra gravar; sem isso, só mostra o
  payload que seria enviado
- `~/.config/artia/config.json` fica fora de qualquer repositório git

## Licença

MIT — veja [`LICENSE`](./LICENSE).
