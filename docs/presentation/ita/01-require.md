# 1. Require: prima del codice, il comportamento

[Indice](README.md) · [Scenario](scenario.md) · [Successivo: Plan](02-plan.md)

> «Voglio che non si prenoti due volte la stessa sala.»

## La domanda nascosta nella richiesta

L'agente potrebbe cominciare da calendario, login e database. Marta potrebbe
approvare una bella schermata senza accorgersi che il comportamento centrale
non è ancora definito.

Luca e un'altra persona vedono una sala libera nello stesso momento. Premono
entrambi «Prenota». Che cosa deve succedere? Una lista aggiornata prima del click
non basta a rispondere.

Il primo lavoro è rendere osservabile l'intento: **una sola conferma, un conflitto
esplicito per l'altra richiesta e nessuna conferma inventata se manca un esito**.
La soluzione tecnica sarà responsabilità dell'ingegnere/agente; Marta chiarisce
il risultato che vuole, non deve scegliere un livello di isolamento del database.

## Che cosa conserva Flower

L'agente registra requisito, motivazione, caso d'uso e sequenza. Nel guided
bootstrap può conservare risposte selezionate con provenienza e collegarle alle
entità canoniche. La corrispondenza è un giudizio dichiarato dall'host, non una
prova semantica automatica.

| Oggetto della storia | Perché serve |
| --- | --- |
| Requisito SC-R1 | Definisce il risultato da preservare. |
| Caso d'uso «Prenotare una sala» | Spiega attore, obiettivo ed esito osservabile. |
| Sequenza con due richieste | Fa emergere un conflitto che il percorso felice nasconde. |
| Risposta di Marta collegata allo scope | Rende recuperabile la decisione, invece di lasciarla in chat. |

Una roadmap derivata viene presentata alla persona e confermata con un riferimento
reale. **Confermare lo scope non significa accettare software non ancora prodotto.**

## Il problema da cui nasce il meccanismo

Una conversazione può contenere proposte, osservazioni e decisioni con autorità
diversa. Una nuova sessione non deve trasformare l'ultima frase letta in un nuovo
requisito. Requisiti revisionati, risposte collegate e scope confermato rendono
esplicito che cosa governa il lavoro corrente.

Flower non impedisce a un agente esterno di usare altri strumenti fuori da quel
percorso: i suoi gate governano le operazioni del server. L'aderenza dell'agente
alle istruzioni resta una proprietà da provare sul suo host.

## Nella superficie pubblica

`fow_bootstrap` guida l'intake; `fow_register_requirement` registra il requisito;
`fow_goal` contiene casi d'uso, sequenze e aspettative. `fow_capabilities` espone
la recipe `engineering-bootstrap` e i contratti esatti delle operazioni.

**Domanda al pubblico:** se cambiamo agente domani, sa perché abbiamo scelto
questo comportamento, oppure trova soltanto una schermata già scritta?

[Approfondisci: intenti e lens](concepts.md#lens) · [Fonti del capitolo](sources.md#require)

[Indice](README.md) · [Successivo: Plan](02-plan.md)
