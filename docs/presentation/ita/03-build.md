# 3. Build: il lavoro esce dal server, l'intento no

[Precedente: Plan](02-plan.md) · [Indice](README.md) · [Successivo: Verify](04-verify.md)

> Il piano è pronto. L'agente comincia. A metà lavoro la sessione si interrompe.

## Il codice ha un esecutore

L'agente scrive `reserve_room`, esegue i test e costruisce l'interfaccia usando
gli strumenti del proprio host. Flower **non apre il repository per scrivere
quel codice** e non avvia quei test nella modalità standalone external-agent.

Dal piano accettato, dalla PVP chiusa e dall'ammissione corrente, Flower può
esporre una TODO ordinata per dipendenze. Quando l'agente dichiara un risultato,
Flower conserva unità, autorità del piano, riferimenti agli artefatti e verifiche
con la loro provenienza. Non trasforma quella dichiarazione in un audit del
filesystem che non ha eseguito.

## Se Flower non è disponibile

Un export Markdown completo conserva il contesto necessario: intento, criteri,
decisioni, contratti, ordine delle unità e verifiche. L'host salva l'artefatto e
può lavorare offline **entro l'autorità già ricevuta**.

Non basta che esista un file chiamato «piano». Un export draft espone i suoi gap
e non equivale a lavoro eseguibile. Un nuovo problema d'intento o un'autorità
mancante non si risolvono inventando un'autorizzazione offline.

## Se cambia il piano durante l'interruzione

| Evento | Che cosa deve rimanere distinguibile |
| --- | --- |
| L'agente riconnette e riporta lo stesso risultato. | Un replay identico non deve creare un secondo risultato indipendente. |
| Due report diversi dichiarano l'esito della stessa autorità. | Il conflitto richiede riconciliazione esplicita. |
| Il piano corrente è cambiato. | Il risultato della vecchia revisione rimane storia, non chiusura automatica del nuovo lavoro. |

La TODO è una proiezione dello stato, non una lista parallela che il modello
deve sincronizzare a mano nella memoria della chat.

## Il problema da cui nasce il meccanismo

Un messaggio «finito» non dice quale piano sia stato eseguito, quali output
esistano o che cosa sia rimasto aperto. La continuità non si ottiene copiando
tutta la chat: si recuperano fatti, autorità e prossimo gate dal loro proprietario.

Flower non garantisce che ogni agente rispetti un piano esportato. Conserva e
controlla il confine del proprio protocollo; l'agent loop si qualifica separatamente.

## Nella superficie pubblica

`fow_external_work` offre `export_plan`, `todo`, `report_outcome` e
`reconcile_outcome`. `fow_handover` ricostruisce stato e progresso correnti.
La recipe pertinente è `standalone-external-plan`.

**Domanda al pubblico:** dopo un'interruzione, ripartiamo dall'ultima frase
dell'agente o dal lavoro realmente registrato?

[Approfondisci: autorità ed evidenza](concepts.md#evidenza-corrente) · [Fonti del capitolo](sources.md#build)

[Precedente: Plan](02-plan.md) · [Indice](README.md) · [Successivo: Verify](04-verify.md)
