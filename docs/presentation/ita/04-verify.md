# 4. Verify: «verde» rispetto a quale domanda?

[Precedente: Build](03-build.md) · [Indice](README.md) · [Successivo: Deploy](05-deploy.md)

> «Tutti i test passano. Possiamo dire che le doppie prenotazioni sono risolte?»

## Il percorso felice non è la concorrenza

Una richiesta riesce. Una seconda richiesta, arrivata dopo, viene rifiutata.
Questo test è utile, ma non verifica due richieste simultanee. E un test del
servizio non dimostra ancora che l'interfaccia mostri l'esito corretto quando
la connessione cade dopo la conferma.

L'agente deve creare ed eseguire controlli che rispondano ai comportamenti
concordati. Flower conserva obblighi, risultati e collegamenti; non rende
pertinente un test sbagliato solo perché il suo exit code è zero.

## Una lettura onesta del progresso

| Dimensione | Esempio nella storia | Che cosa non implica |
| --- | --- | --- |
| Implementazione | Servizio e interfaccia sono dichiarati prodotti. | Che siano corretti o accettati. |
| Verifica locale | I controlli disponibili all'unità hanno esito dichiarato e riferimenti. | Che una campagna sul sistema reale sia stata eseguita. |
| Verifica differita | Resta la prova completa nell'ambiente di destinazione. | Un fallimento implicito o una promozione automatica a pass. |
| Accettazione | L'autorità competente prende la decisione prevista con evidenze appropriate. | Che bastasse una percentuale di completamento. |

Il progresso derivato riguarda criteri e scope selezionati. Un denominatore
mancante non diventa «100%». L'evidenza di un vecchio piano non viene usata come
se verificasse senza riserve quello corrente.

## La campagna, non soltanto il comando di test

L'agente può strutturare casi, obblighi, risposte attese e fonti dell'oracolo:
richieste simultanee, annullamento, permessi e perdita della risposta. Flower
offre authoring, avanzamento e ispezione di campagne; l'esecuzione tecnica e
l'attestazione dipendono dal percorso e dai prerequisiti disponibili.

Un'analisi semantica opzionale può aiutare: `fow_semantic` prepara incarichi
bounded per SRS o grounding, anche eseguiti dall'host. Una risposta strutturalmente
valida non è una prova universale. L'adozione registra un audit con provenienza,
non l'accettazione automatica del prodotto.

## Il problema da cui nasce il meccanismo

«Verificato», «completato» e «accettato» sono parole troppo comode se non diciamo
da chi, con quali dati e a quale revisione. La distinzione conserva ciò che
sappiamo e rende visibile ciò che ancora non sappiamo.

## Nella superficie pubblica

`fow_campaign_author`, `fow_campaign_advance` e `fow_campaign_inspect` gestiscono
le campagne; `fow_record_verification`, `fow_traceability` e `fow_assurance`
registrano evidenza e decisioni. Le operazioni che richiedono provider o modello
non si fingono disponibili quando quei prerequisiti mancano.

**Domanda al pubblico:** se leggiamo «100%», possiamo sapere anche quali domande
non sono state ancora verificate?

[Approfondisci: i tre significati di finito](concepts.md#tre-significati-di-finito) · [Fonti del capitolo](sources.md#verify)

[Precedente: Build](03-build.md) · [Indice](README.md) · [Successivo: Deploy](05-deploy.md)
