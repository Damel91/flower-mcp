# Fonti, provenienza e limiti

[Indice](README.md) · [Tool](tools.md) · [Traccia del talk](talk.md)

## Che cosa stai leggendo

Questo è un percorso editoriale in italiano, non una nuova specifica del server.
Spazio Comune, le sue regole e i dialoghi sono esempi didattici. Non sono record
runtime, receipt live o un benchmark. La documentazione operativa corrente di
Flower prevale su una spiegazione divulgativa.

La ricostruzione ha usato anche le autorità di sviluppo interne e le ricerche
sull'autorità temporale di CodingCastle come materiale di studio. **Non sono
state esportate nel sito** le loro parti testuali: né documenti privati, né
runtime, host, credenziali o log. La [pagina sul metodo](method.md) mostra
soltanto ritagli degli elenchi documentali, selezionati dall'autore.
Una capacità del motore CodingCastle non viene attribuita a Flower.

Le fonti pubbliche di Flower sotto sono fissate al sorgente
`d82eb9f15f5a77961d06012fc25ecde3c5c8f18a`, versione dichiarata `0.4.1`.
Questi riferimenti di implementazione e installazione conservano quel checkpoint
sorgente storico. Flower 0.5.0 è pubblicato al commit `a46e0ec0efa335e655f3b5b8d7ecdc3843a0fa3c`; la
[guida avanzata corrente](https://github.com/Damel91/flower-mcp/tree/main/docs/ADVANCED-CONFIGURATION.md)
segue il ramo mutabile e non pretende di esistere già al pin congelato.
I download Flower puntano alla release pubblicata immutabile `0.5.0`. La storica
`0.4.1` conserva runtime `0.4.0`; questa fotografia editoriale non qualifica i
binari. Le release pubblicate `0.3.1`, `0.4.0`, `0.4.1` e `0.5.0` rimangono immutabili.
Il reader si rigenera dai Markdown; i riferimenti di
prodotto vanno riesaminati quando cambia il comportamento del server.

## Require

Problema originario: non confondere dialogo, proposta e intento corrente.

- [Template pubblico dell'agente](https://github.com/Damel91/flower-mcp/blob/d82eb9f15f5a77961d06012fc25ecde3c5c8f18a/src/flow_of_work_mcp/resources/agent-bootstrap.md): ruolo dell'ingegnere, scenari, conferma reale della roadmap.
- [Recipe di ciclo di vita](https://github.com/Damel91/flower-mcp/blob/d82eb9f15f5a77961d06012fc25ecde3c5c8f18a/src/flow_of_work_mcp/application/lifecycle_recipes.py): `engineering-bootstrap` e confini di autorità.
- [Guided bootstrap](https://github.com/Damel91/flower-mcp/blob/d82eb9f15f5a77961d06012fc25ecde3c5c8f18a/src/flow_of_work_mcp/application/guided_bootstrap.py): risposte, corrispondenze e conferme.

## Plan

Problema originario: un output futuro non è una dipendenza già materializzata;
copertura strutturale e giudizio semantico non sono intercambiabili.

- [PVP standalone](https://github.com/Damel91/flower-mcp/blob/d82eb9f15f5a77961d06012fc25ecde3c5c8f18a/src/flow_of_work_mcp/core/domain/packet_validation_projection.py): derivazione della validazione del piano.
- [Contratti delle operazioni](https://github.com/Damel91/flower-mcp/blob/d82eb9f15f5a77961d06012fc25ecde3c5c8f18a/src/flow_of_work_mcp/application/operation_contracts.py): dichiarazioni di unità e route esterne.
- [Recipe standalone](https://github.com/Damel91/flower-mcp/blob/d82eb9f15f5a77961d06012fc25ecde3c5c8f18a/src/flow_of_work_mcp/application/lifecycle_recipes.py): produttori, consumatori, verifiche e ammissione.

## Build

Problema originario: un'interruzione o una revisione non deve promuovere un
report vecchio a completamento del lavoro corrente.

- [External work](https://github.com/Damel91/flower-mcp/blob/d82eb9f15f5a77961d06012fc25ecde3c5c8f18a/src/flow_of_work_mcp/application/external_work.py): TODO, export e risultati dichiarati.
- [Bootstrap pubblico](../../BOOTSTRAP.md): istruzioni persistenti, lavoro offline e riconciliazione.
- [Mappa dei tool](tools.md): distingue osservazione, dichiarazione ed esecuzione.

## Verify

Problema originario: compilazione, test, evidenza dichiarata e accettazione
rispondono a domande diverse.

- [Catalogo pubblico](https://github.com/Damel91/flower-mcp/blob/d82eb9f15f5a77961d06012fc25ecde3c5c8f18a/src/flow_of_work_mcp/application/operation_contracts.py): campagne, verification e prerequisiti semantici.
- [Recipe semantiche e campagne](https://github.com/Damel91/flower-mcp/blob/d82eb9f15f5a77961d06012fc25ecde3c5c8f18a/src/flow_of_work_mcp/application/lifecycle_recipes.py): adozione di audit e autorità dell'oracolo.
- [Smoke pubblico](https://github.com/Damel91/flower-mcp/blob/d82eb9f15f5a77961d06012fc25ecde3c5c8f18a/tools/smoke_mcp.py): una verifica meccanica del pacchetto installato, non un benchmark cognitivo.

## Deploy

Problema originario: una consegna deve dichiarare scope, evidenza e obblighi
aperti, senza scambiare un messaggio dell'agente per accettazione.

- [README pubblico](../../../README.md): proprietà del core e separazione dalle azioni dell'agente.
- [Contratti delle operazioni](https://github.com/Damel91/flower-mcp/blob/d82eb9f15f5a77961d06012fc25ecde3c5c8f18a/src/flow_of_work_mcp/application/operation_contracts.py): milestone e handover.

## Operate

Problema originario: non cambiare l'intento per giustificare una realizzazione
sbagliata; conservare la storia senza renderla autorità corrente per errore.

- [Recipe pubbliche](https://github.com/Damel91/flower-mcp/blob/d82eb9f15f5a77961d06012fc25ecde3c5c8f18a/src/flow_of_work_mcp/application/lifecycle_recipes.py): rivalutazione corrente e correzione entro l'intento.
- [Template dell'agente](https://github.com/Damel91/flower-mcp/blob/d82eb9f15f5a77961d06012fc25ecde3c5c8f18a/src/flow_of_work_mcp/resources/agent-bootstrap.md): progressi, gap semantici e responsabilità.

## Catalogo

Le nove lens e i 37 nomi della [mappa](tools.md) corrispondono a `_WORK_AREAS` e
`_PUBLIC_TOOLS` nel [registro pubblico](https://github.com/Damel91/flower-mcp/blob/d82eb9f15f5a77961d06012fc25ecde3c5c8f18a/src/flow_of_work_mcp/application/operation_contracts.py).
Il controllo editoriale verifica che il sito non ometta o inventi nomi.

## Confronto tra plane

La [pagina di confronto](comparison.md) usa le fonti ufficiali dei progetti,
consultate il 2 ottobre 2026. Sono riferimenti correnti e modificabili, non
release esterne qualificate o un audit esaustivo del loro codice. I consigli
d'uso sono valutazioni editoriali; non abbiamo misurato un vincitore.

- [LLM Flow of Work documentale](https://github.com/Damel91/LLMs-flow-of-work).
- [Spec Workflow MCP](https://github.com/Pimzino/spec-workflow-mcp).
- [Task Master AI](https://github.com/eyaltoledano/claude-task-master).
- [MCP Task Orchestrator](https://github.com/jpicklyk/task-orchestrator).

## Integrazioni cross-server

La [pagina avanzata](advanced.md) distingue il core standalone dagli adapter
opzionali. Non esporta configurazioni private né certifica una nuova coppia di
runtime. I riferimenti restano fissati al sorgente Flower dichiarato sopra.

- [Factory dei provider](https://github.com/Damel91/flower-mcp/blob/d82eb9f15f5a77961d06012fc25ecde3c5c8f18a/src/flow_of_work_mcp/runtime_factory.py): percorsi opzionali e adapter selezionati.
- [Associazioni portabili](https://github.com/Damel91/flower-mcp/blob/d82eb9f15f5a77961d06012fc25ecde3c5c8f18a/src/flow_of_work_mcp/application/association_receipts.py): receipt e autorizzazione delle route.
- [Orientamento tecnico](https://github.com/Damel91/flower-mcp/blob/d82eb9f15f5a77961d06012fc25ecde3c5c8f18a/src/flow_of_work_mcp/adapters/implementation_intelligence/interaction_provider.py) e [proiezione delle lens](https://github.com/Damel91/flower-mcp/blob/d82eb9f15f5a77961d06012fc25ecde3c5c8f18a/src/flow_of_work_mcp/application/interaction_projection.py): discovery read-only e disponibilità coordinata.
- [Snapshot MCP](https://github.com/Damel91/flower-mcp/blob/d82eb9f15f5a77961d06012fc25ecde3c5c8f18a/src/flow_of_work_mcp/adapters/implementation_intelligence/mcp_provider.py): evidenza e canale strutturato.
- [Adapter packet](https://github.com/Damel91/flower-mcp/blob/d82eb9f15f5a77961d06012fc25ecde3c5c8f18a/src/flow_of_work_mcp/adapters/implementation_intelligence/packet_provider.py) e [adapter test](https://github.com/Damel91/flower-mcp/blob/d82eb9f15f5a77961d06012fc25ecde3c5c8f18a/src/flow_of_work_mcp/adapters/implementation_intelligence/test_provider.py): integrazione CodingCastle presente nel sorgente.
- [Recipe di ciclo di vita](https://github.com/Damel91/flower-mcp/blob/d82eb9f15f5a77961d06012fc25ecde3c5c8f18a/src/flow_of_work_mcp/application/lifecycle_recipes.py): ownership, review, campagne e PVP cross-server differita.
- [Scadenze del provider e recupero esatto](https://github.com/Damel91/flower-mcp/blob/d82eb9f15f5a77961d06012fc25ecde3c5c8f18a/docs/NOXI-INTEGRATION.md#provider-timeouts-and-exact-recovery-unreleased): l'etichetta storica non ancora rilasciato descrive il budget per RPC ora incluso in 0.5.0 e la riconciliazione del comando UNKNOWN originale; la qualificazione del pacchetto installato e quella accoppiata reale restano separate.

## Installazione e download

La conclusione [Ora prova Flower](try-flower.md) usa la [repository pubblica](https://github.com/Damel91/flower-mcp),
la [release v0.5.0](https://github.com/Damel91/flower-mcp/releases/tag/v0.5.0) e
la [guida di installazione al checkpoint sorgente](https://github.com/Damel91/flower-mcp/blob/d82eb9f15f5a77961d06012fc25ecde3c5c8f18a/docs/INSTALLATION.md).
La release 0.5.0 contiene sette asset Flower: wheel, sorgente, tre installer,
bootstrap e checksum, senza un wheel runtime copiato. La storica
[0.4.1](https://github.com/Damel91/flower-mcp/releases/tag/v0.4.1) conserva otto asset,
incluso runtime-llama `0.4.0`. I download Flower restano fissati alla release.
Le guide operative correnti seguono `main`; documentazione storica e citazioni
sorgente runtime mantengono il checkpoint congelato completo identificato sopra.
I comandi della release richiedono i corrispondenti asset pubblicati.

La nuova dipendenza opzionale appartiene alla
[release llama-runtime `0.4.1`](https://github.com/Damel91/llama-runtime/releases/tag/v0.4.1)
indipendente, con [wheel upstream](https://github.com/Damel91/llama-runtime/releases/download/v0.4.1/runtime_llama-0.4.1-py3-none-any.whl)
SHA256 `8c512eb79b00ac3fdf761036fa0c8d74c24c3581651332736f6a95e6e38ae0aa`.
Non è un asset Flower. Il wheel include `LICENSE`/`NOTICE` Apache-2.0 e
l'attribuzione MIT di llamatelemetry incorporato. La
[guida storica all'inferenza](https://github.com/Damel91/flower-mcp/blob/d82eb9f15f5a77961d06012fc25ecde3c5c8f18a/docs/INFERENCE.md)
registra il checkpoint precedente. Usa la
[guida corrente all'inferenza](https://github.com/Damel91/flower-mcp/tree/main/docs/INFERENCE.md), esplicitamente
mutabile, per l'extra 0.5.0, i vincoli del build posseduto,
l'acquisizione offline e l'aggiornamento del runtime. Il vecchio extra Flower
storico 0.4.1 seleziona ancora `0.4.0`; un aggiornamento di core/profilo non richiede
il nuovo runtime e non configura un provider.

Disponibilità dei collegamenti, test del pacchetto installato e qualificazione
del client sono controlli distinti. Il reader non certifica una nuova
installazione o esperienza nativa Windows/Linux. I controlli di pacchetto,
gateway simulato e container non dimostrano comportamento del modello live,
deployment Glama ospitato autenticato o accettazione umana.
Il README su `main` è corrente.

## Limiti espliciti

- Flower non garantisce la correttezza dell'agente o l'aderenza alle sue recipe.
- La validazione di uno schema o della PVP non dimostra verità semantica.
- Flower standalone non audita automaticamente sorgenti e simboli esterni.
- Il core non è un coding harness, un deployer o un servizio di monitoraggio.
- Un host-report non diventa attestazione di provider o decisione umana.
- Questo sito non promette riduzione di token, qualità superiore o autonomia
  di un modello specifico: sono domande per benchmark separati.

## Reader e attribuzioni

Il reader è un adattamento concettuale del visualizzatore offline del Flow
documentale: layout indice/contenuto, ma documenti pre-renderizzati, collegamenti
per percorso e nessun parser scaricato nel browser. Il corpus usa Markdown
ordinario con tabelle; non replica tutte le estensioni o l'interfaccia di GitHub.

- [github-markdown-css](https://github.com/sindresorhus/github-markdown-css), MIT,
  copia locale fissata a `7f38dcb9054bc5d860fac65291f5c98fef47932c`.
- [markdown-it-py](https://markdown-it-py.readthedocs.io/en/latest/using.html),
  parser usato solo per generare il reader, con HTML raw disabilitato.
- Il logo è quello della repository Flower; i font sono quelli del sistema.

[Indice](README.md) · [Come aprire e rigenerare il reader](reader.md)
