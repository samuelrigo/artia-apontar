---
name: artia-apontar
description: Lê commits git de um período, agrupa por tarefa/dia, estima horas, casa cada grupo com a atividade certa no Artia (API GraphQL) e cria os apontamentos — sempre com tabela de revisão e confirmação antes de gravar. Nunca roda sozinha (só via /artia-apontar).
argument-hint: "[hoje|ontem|YYYY-MM-DD|YYYY-MM-DD..YYYY-MM-DD|7d] [repo...] [--dry-run]"
disable-model-invocation: true
---

# /artia-apontar — apontar horas no Artia a partir do git

Ferramenta: `artia.py` (neste diretório da skill), stdlib-only, sem dependências.
Cliente CLI pra API GraphQL do Artia (`https://api.artia.com/graphql`).

**Regra de ouro: nunca chamar `create-entry --yes` sem o usuário ter confirmado
explicitamente a tabela final.** Sem `--yes`, `create-entry` só mostra o payload
(dry-run) e não grava nada — é o comportamento padrão de segurança do script,
não contorne isso.

## 0. Config

Lê `~/.config/artia/config.json` (fora de qualquer repo git, nunca commitado).
Estrutura: `createdBy`, `authorMatch` (lista de nomes/emails do autor no git log),
`defaults` (`startTime`, `timeEntryStatusId`, `kindOfHours`, `gapMinutes`,
`warmupMinutes`), `repos` (mapa `caminho_absoluto -> {organizationId, accountId,
folderId}`). Exemplo em `config.example.json` deste diretório.

**Todo comando abaixo precisa de `--org <organizationId>`** (o organizationId
do repo, do config). Sem isso, `artia.py` usa o default `1` — quase certamente
errado — e a API retorna erros confusos tipo `"Comunidade desconhecida"` ou
`"Organização não encontrada"` mesmo com accountId/folderId corretos. Já
aconteceu nessa mesma sessão de desenvolvimento; não repita.

Se `organizationId`/`accountId`/`folderId` de algum repo estiverem `null`: pare
e peça pro usuário descobrir:
- `organizationId`: aparece na URL do próprio perfil do usuário no Artia —
  `https://app.artia.com/users/edit?organization_id=<ESSE_NÚMERO>`.
- `accountId` (grupo de trabalho): aparece na URL de qualquer atividade —
  `https://app.artia.com/a/<accountId>/f/<folderId>/activities/<activityId>`.
- `folderId`: com organizationId e accountId em mãos, rode
  `python3 artia.py --org <organizationId> folders --account <accountId>` (ou
  `projects --account <accountId>` — "Projetos" costuma ser o nível certo pra
  `folderId` de `listingActivities`, "Pastas" pode ser um nível acima sem
  atividades diretas).

Depois de descoberto, edite `~/.config/artia/config.json` direto.

`defaults.timeEntryStatusId` é o status de workflow/aprovação do apontamento
(ex: "Em validação", "Aprovado") — não é customizável por `listingCustomStatus`
com filtro `statusObject: "TimeEntry"` direto (retorna vazio mesmo quando o id
certo existe). Jeito confiável de achar o valor certo: peça pro usuário criar
1 apontamento manual pela UI do Artia, depois rode `time-entries` pra essa
atividade/data e leia o `timeEntryStatusId` que veio de verdade.

## 1. Credenciais

`ARTIA_EMAIL` / `ARTIA_PASSWORD` via variável de ambiente. **Nunca** peça pra
colar a senha no chat, nunca escreva a senha em arquivo, nunca imprima o valor
de `ARTIA_PASSWORD`. `artia.py login` cacheia só o token JWT (extraído o `exp`
do próprio token) em `~/.cache/artia/token.json`, modo 0600, curta duração —
os outros subcomandos reusam esse cache e só re-logam se expirado.

Se as env vars não estiverem setadas, peça pro usuário exportar antes de
continuar (ex: no `~/.bashrc`/`~/.zshrc` ou só na sessão do terminal) — não
prossiga sem elas.

## 2. Parse de `$ARGUMENTS`

- Período: `hoje` (default) | `ontem` | `YYYY-MM-DD` | `YYYY-MM-DD..YYYY-MM-DD` | `Nd` (últimos N dias).
- Repos: paths opcionais; default = todas as chaves de `repos` no config que
  tiverem commit no período.
- `--dry-run`: roda tudo, mostra a tabela, mas nunca chega a perguntar
  confirmação de postagem (fica implícito que não posta).

## 3. Coleta de commits

Por repo, autor batendo com `authorMatch`:
```
git -C <repo> log --since=<...> --until=<...> --date=iso-strict \
  --pretty='%H|%cI|%D|%s' --author='<regex dos authorMatch, OR-separado>'
```
Agrupe por `(repo, dia, branch)`. Branch vem de `%D` (ref-names) quando
presente; senão usa a branch atual do repo (`git branch --show-current`) como
fallback — é heurística, o usuário revisa/corrige na tabela do passo 6.

## 4. Estimativa de horas (sessões)

Por grupo, ordene os commits do dia. Quebre em sessões sempre que o gap entre
dois commits consecutivos passar de `defaults.gapMinutes`. Duração de cada
sessão = `(timestamp do último commit − timestamp do primeiro)` + `defaults.warmupMinutes`
somado uma vez no início da sessão (compensa o tempo de trabalho antes do
primeiro commit). Some as sessões do grupo, arredonde pra 0,25h.

Isso é **estimativa de partida** — o usuário edita os números no passo 6.

## 5. Resolução da atividade (match por título)

Para cada grupo (repo já resolve `organizationId`/`accountId`/`folderId` via config):
```
python3 artia.py --org <organizationId> activities --folder <folderId> --account <accountId> --mine
```
Normalize (minúsculas, sem acento) o nome da branch (sem prefixo `feat/`,
trocando `-`/`_` por espaço) e os assuntos dos commits do grupo. Compare por
overlap de tokens contra `title` de cada atividade retornada. Guarde as top-3
por score — não decida sozinho quando o placar for ambíguo (top-1 e top-2
muito próximos): deixe as 3 visíveis na tabela pro usuário escolher.

## 6. Dedupe + tabela de proposta

Antes de mostrar, rode dedupe contra as **3 candidatas** do grupo (não só a
top-1) — se o match errar a atividade certa, checar só a top-1 deixa passar
duplicata numa atividade diferente da que já tem entrada real:
```
python3 artia.py --org <organizationId> time-entries --account <accountId> --folder <folderId> --activity <activityId> --date <data>
```
Se **qualquer uma** das 3 já tiver entrada nesse dia: marque a linha como **já
apontado** (mostra `id`/`duration`/qual atividade já tem), e trate isso como
sinal extra de qual candidata é a certa (se foi a #2 ou #3 que já tinha
entrada, é forte indício de que o match top-1 errou). Não proponha criar de
novo a menos que o usuário peça explicitamente.

Monte e mostre uma tabela markdown:

| data | repo/branch | atividade (top-3 candidatas) | horas estimadas | observação | status |
|---|---|---|---|---|---|
| 2026-07-22 | meu-repo / feat/tarefa21-... | **29153781 — Título da atividade (Tarefa 21)** / 29153782 / 29153790 | 3.5 | feat: resumo do que foi commitado... | novo |

## 7. Edição + confirmação

Peça pro usuário revisar: pode trocar a atividade escolhida (entre as
candidatas ou outro id), ajustar horas, editar observação, remover linhas.

**Se o usuário trocar a atividade de alguma linha, refaça o dedupe do passo 6
pra essa nova `(activityId, data)` antes de seguir** — o cheque anterior foi
feito só pra atividade top-1 original, não cobre a troca.

**Só prossiga para o passo 8 depois de uma confirmação explícita** ("pode
postar", "confirma", etc). Em modo `--dry-run`, pare aqui.

## 8. Postagem

Por linha confirmada:
```
python3 artia.py --org <organizationId> create-entry --account <accountId> --activity <activityId> \
  --date <data> --start <defaults.startTime> --duration <horas> \
  --status <defaults.timeEntryStatusId> --by <createdBy> --kind normal \
  --obs "<observação>" --yes
```
Reporte os `id` criados numa lista curta. Se algum `timeEntryStatusId` da
config estiver incorreto pro fluxo real do usuário (API rejeitar), pare,
mostre a mensagem de erro decisiva (não o JSON inteiro) e peça o id certo —
não adivinhe tentando valores em sequência.

Se o projeto tiver alguma convenção própria de log de bugs/erros, registre lá
também — trate um erro de API/gravação aqui como qualquer outro bug do dia a dia.

## Referência rápida da API (GraphQL, `https://api.artia.com/graphql`)

Toda request autenticada leva `Authorization: Bearer <token>` +
`OrganizationId: <organizationId>`. `artia.py` monta esse header sozinho, mas
só com o valor certo se você passar `--org <organizationId>` — sem isso ele
usa um default (`1`) que raramente é o organizationId real do usuário.

- `authenticationByEmail(email, password){ token }`
- `listingProjects(accountId){ id, name, status, costCenterId }`
- `listingFolders(accountId, page){ id, name, status, folderTypeName }`
- `listingActivities(accountId, folderId){ id, title, status, responsible{email} }`
- `listingTimeEntries(accountId, folderId, activityId){ id, dateAt, duration, observation, timeEntryStatusId }`
- `createTimeEntry(accountId, activityId, dateAt, startTime, duration, timeEntryStatusId, createdBy, kindOfHours, observation, customField){ id, ... }`

Qualquer outra operação da coleção "Developers - Artia" (Postman) que não
tenha subcomando dedicado: use `artia.py raw --query '...'` com a query/mutation
completa (mesma sintaxe inline usada nos exemplos acima, sem `variables`).
