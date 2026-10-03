# 6. Operate: quando il mondo risponde

[Precedente: Deploy](05-deploy.md) · [Successivo: prova Flower](try-flower.md) · [Indice](README.md)

> «È successo un conflitto ieri sera. E ci servirebbe prenotare ogni martedì.»

## Due notizie, due percorsi

La prima può essere un difetto rispetto a SC-R1: due conferme incompatibili.
La seconda introduce prenotazioni ricorrenti, escluse dal primo scope.
Metterle nello stesso «fix» rischia di cambiare il prodotto senza dirlo.

| Notizia | Domanda prima di modificare |
| --- | --- |
| Due conferme per lo stesso intervallo | Quale evidenza mostra una divergenza dall'intento corrente? |
| Prenotazione ogni martedì | Come cambia lo scope, e quali nuove regole vanno chiarite e confermate? |

L'agente indaga il difetto con i propri strumenti. Flower non monitora il
servizio, non raccoglie autonomamente incidenti e non diagnostica il database
di Spazio Comune.

## Correggere senza riscrivere il passato

Per una divergenza l'agente registra un finding, rilegge requisito, scenario,
milestone e packet correnti e dichiara la rivalutazione dell'intento. Solo una
valutazione corrente che stabilisca una correzione entro l'intento concordato
permette quel percorso correttivo.

Il nuovo packet rimane collegato al finding e porta un obbligo di regressione.
Una valutazione non è la prova che il bug sia risolto; i risultati successivi
devono ancora sostenere la sua disposizione.

Per le prenotazioni ricorrenti si usa invece il normale cambiamento d'intento:
nuove regole, revisioni e conferma dello scope interessato. Non si modifica
SC-R1 retroattivamente per giustificare due conferme errate.

## Se cambia la persona o l'agente

Un'altra sessione seleziona il progetto e recupera uno snapshot. Può leggere
stato corrente e storia senza considerare il modello il sistema di record.
Il prossimo gate orienta il lavoro; non garantisce che l'agente prenderà ogni
decisione semantica correttamente.

## Il problema da cui nasce il meccanismo

Il ciclo di vita non termina con la prima consegna. Serve conservare il motivo
di un cambiamento, l'autorità che lo ammette e la distinzione tra vecchie prove
e nuovo lavoro. Un log di messaggi non sostituisce queste relazioni.

## Nella superficie pubblica

`fow_assurance` registra finding, rivalutazioni e collegamenti correttivi;
`fow_revise_requirement` mantiene revisioni; `fow_change` governa i cambiamenti;
`fow_handover` permette il recupero. La stessa storia può tornare a Require o
Plan: non è necessario dichiarare un nuovo progetto per ogni correzione.

**Domanda al pubblico:** il prossimo agente saprà se deve riparare una promessa
non mantenuta o progettare una promessa nuova?

[Approfondisci: storia e stato corrente](concepts.md#evidenza-corrente) · [Fonti del capitolo](sources.md#operate)

Il percorso ora passa dalla storia al tuo progetto: [installa e prova Flower](try-flower.md).

[Precedente: Deploy](05-deploy.md) · [Successivo: prova Flower](try-flower.md) · [Indice](README.md) · [Torna a Require](01-require.md)
