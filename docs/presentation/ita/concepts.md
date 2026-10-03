# Concetti essenziali, senza imparare uno schema

[Indice](README.md) · [Tool pubblici](tools.md) · [Fonti](sources.md)

## Responsabilità

Flower possiede requisiti, Goal Graph, milestone, cambiamenti, piani, finding,
evidenze dichiarate, accettazione e handover. L'agente e i suoi strumenti
tecnici possiedono indagine del repository, codice, build, test e Git. La persona
possiede intento e decisioni finali che le competono.

Il ledger SQLite di Flower non è il database dell'applicazione sviluppata. Non
contiene automaticamente le sue sorgenti o una prova che l'agente le abbia lette.

## Lens

Una lens è una prospettiva operativa sul progetto. Le nove aree sono bootstrap,
requirements, Goal Graph, milestones, changes, packet lifecycle, assurance,
handover e campaigns. Non corrispondono uno-a-uno ai sei petali narrativi.

Selezionare una lens cambia attenzione, **non autorizzazione, completamento o
verità**. Il catalogo MCP del client non viene magicamente nascosto e ricreato
quando si cambia area. Lo snapshot corrente e i gate mantengono la loro autorità.

## Packet

Un incremento di lavoro con intento, scope e criteri. Il piano contiene unità
ordinate, dipendenze, istruzioni e verifiche. I numeri leggibili sono identità
stabili, non una graduatoria da ricompattare dopo una rimozione.

## PVP

La Packet Validation Projection è una derivazione dai dati canonici, non un
secondo piano da mantenere. Rende visibili copertura dei criteri, produttori,
consumatori, dipendenze e obblighi di verifica. Una promessa di output futuro
non diventa sorgente già esistente.

La chiusura strutturale non dimostra correttezza semantica o qualità del codice.
Piano accettato, PVP chiusa e ammissione corrente servono al percorso esterno.
Un finding semantico pertinente può ancora bloccarlo.

## TODO ed export

La TODO deriva dal piano e dai report correnti. Non esegue codice. L'export
Markdown trasferisce un'autorità delimitata; il file salvato dall'host è utile
offline, ma modificarlo non modifica lo stato di Flower.

## Evidenza corrente

Un report dichiara esito, revisione, artefatti e provenienza. Flower controlla la
coerenza con l'autorità emessa e conserva la storia. Evidenza dichiarata dall'host
non significa sorgente auditata dal server.

Se cambia l'autorità pertinente, un risultato precedente può rimanere vero
come fatto storico senza completare il nuovo lavoro. Un retry cieco dopo una
risposta perduta non è il modo corretto di recuperare lo stato.

## Tre significati di finito

| Termine | Significato |
| --- | --- |
| Implementato | Il lavoro materiale è dichiarato prodotto. |
| Verificato | Esistono gli esiti e le evidenze richiesti per quello scope. |
| Accettato | L'autorità competente ha preso la decisione prevista. |

Non sono sinonimi. Le verifiche differite restano aperte anche se implementazione
e controlli locali sono completi. Un progresso senza scope o denominatore è
sconosciuto, non perfetto.

## MCP, in questa storia

Il protocollo permette al client di chiamare strumenti del server. Il contenuto
Markdown orienta il modello; lo structured content mantiene i dati macchina.
Flower non sostituisce il system prompt, il modello, i permessi dell'host o
l'aderenza dell'agente alle recipe. L'assenza di un modello interno non impedisce
i flussi standalone core; alcune operazioni avanzate hanno prerequisiti propri.

[Indice](README.md) · [Rivedi la storia](scenario.md)
