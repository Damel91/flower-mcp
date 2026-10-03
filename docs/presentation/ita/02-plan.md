# 2. Plan: una lista non è ancora un piano

[Precedente: Require](01-require.md) · [Indice](README.md) · [Successivo: Build](03-build.md)

> «Facciamo API, calendario e test. Poi consegniamo.»

## Una dipendenza nascosta

L'unità del calendario vuole usare un'API che ancora non esiste. Se il piano
contiene soltanto i nomi delle attività, l'agente può inventare firma, stati e
semantica dell'esito. Due pezzi compilano separatamente ma parlano lingue diverse.

Nel nostro esempio l'agente sceglie una realizzazione tecnica e la registra:
una funzione `reserve_room` restituisce conferma, conflitto o errore temporaneo.
È una **dichiarazione di ciò che verrà prodotto**, non evidenza che la funzione
sia già disponibile.

## Un packet didattico, non una ricetta API

| Unità | Azione ordinata | Produce o usa | Verifica al suo confine |
| --- | --- | --- | --- |
| A: servizio | Implementare la decisione atomica di prenotazione e gli esiti concordati. | Produce il contratto «esito prenotazione». | Test del servizio: richieste concorrenti non producono due conferme. |
| B: interfaccia | Consumare il contratto di A, mostrare gli esiti e gestire l'errore temporaneo. | Richiede esplicitamente il contratto di A. | Controlli sui tre esiti e sulla distinzione tra errore e conferma. |
| C: integrazione | Collegare le parti e predisporre la procedura del caso simultaneo. | Dipende dalle parti necessarie già prodotte. | Verifica locale disponibile; prova nell'ambiente reale resta distinta. |

Le unità appartengono a un packet, cioè a un incremento con intento, scope e
criteri di completamento. La tabella spiega la struttura: non contiene i payload
completi delle operazioni Flower e non autorizza da sola un'esecuzione.

## Che cosa controlla Flower

La **Packet Validation Projection, PVP**, deriva la chiusura dai dati del piano:
chi implementa ogni criterio, chi produce un contratto, quali predecessori lo
rendono disponibile al consumatore e quali verifiche sono locali o differite.

Un consumatore non tiene una seconda copia delle clausole del produttore. Un
produttore assente o non disponibile nell'ordine dichiarato lascia un gap. Un
piano strutturalmente chiuso non può ignorare un blocco semantico corrente:
**chiusura, accettazione del piano e ammissione all'esecuzione sono distinte**.

## Il problema da cui nasce il meccanismo

Il modello deve sapere che cosa può usare **adesso**. Un futuro pianificato non
va promosso a sorgente già presente. La separazione tra dichiarazioni, dipendenze
e risultati rende ispezionabile questa differenza senza chiedere all'utente di
approvare ogni singola unità.

PVP non dimostra che `reserve_room` sia corretta né sceglie la migliore architettura.
La progettazione tecnica e la qualità delle clausole restano lavoro dell'agente.

## Nella superficie pubblica

`fow_promote_milestone` definisce scope e politiche della milestone;
`fow_change` governa il cambiamento; `fow_packet_author` costruisce packet e
piano; `fow_external_work` espone validazione e handoff standalone.

**Domanda al pubblico:** un altro agente potrebbe eseguire questo incremento
senza riaprire tutte le decisioni del primo?

[Approfondisci: PVP](concepts.md#pvp) · [Fonti del capitolo](sources.md#plan)

[Precedente: Require](01-require.md) · [Indice](README.md) · [Successivo: Build](03-build.md)
