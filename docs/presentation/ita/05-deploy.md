# 5. Deploy: consegnare una promessa delimitata

[Precedente: Verify](04-verify.md) · [Indice](README.md) · [Successivo: Operate](06-operate.md)

> «Sul mio computer funziona. Lo mettiamo a disposizione dell'associazione?»

## Cambia l'ambiente, non soltanto l'indirizzo

Spazio Comune deve usare il database di destinazione, gestire credenziali e
permessi e sopravvivere a un riavvio. Le verifiche locali sono ancora evidenza
utile, ma non costituiscono da sole una prova di questi comportamenti.

L'agente prepara la realizzazione tecnica, usa gli strumenti disponibili e
riporta ciò che ha davvero eseguito. La persona mantiene l'autorità per la
consegna e gli effetti irreversibili che le competono.

**Flower non è un deployer, un gestore di credenziali o un sistema CI/CD.** Il
petalo Deploy rappresenta il governo della consegna: scope, evidenze, obblighi
aperti, decisioni di accettazione e stato recuperabile.

## La consegna della storia

| Dichiarazione | Condizione che deve essere esplicita |
| --- | --- |
| «Questa è la prima versione.» | Quale scope e quali comportamenti include? |
| «Questi controlli sono passati.» | Quali risultati, quale ambiente e quale revisione? |
| «Questa verifica resta da fare.» | Chi la esegue e perché non è stata promossa a completata? |
| «L'associazione accetta il risultato.» | Esiste una decisione reale dell'autorità competente, non un testo generato dall'agente? |

Una milestone pianificata e una milestone accettata sono stati distinti. Flower
offre transizioni governate e riferimenti all'evidenza: non sceglie unilateralmente
la soglia di rischio che Marta deve accettare.

## Il problema da cui nasce il meccanismo

Se la consegna è soltanto un messaggio in chat, chi subentra può confondere il
software prodotto con il software accettato. Un handover recuperabile deve dire
che cosa esiste, cosa governa il lavoro e quale obbligo rimane aperto.

La presenza di un record non è una certificazione production-grade. Anche una
prima release dichiarata sperimentale può avere un handover preciso e onesto.

## Nella superficie pubblica

`fow_accept_milestone` governa l'accettazione prevista; `fow_handover` restituisce
snapshot e handover; `fow_get_artifacts` recupera gli artefatti disponibili.
L'export di un piano e l'accettazione del software non sono la stessa operazione.

**Domanda al pubblico:** chi riceve Spazio Comune può distinguere ciò che è
stato consegnato da ciò che gli è stato soltanto promesso?

[Approfondisci: responsabilità](concepts.md#responsabilità) · [Fonti del capitolo](sources.md#deploy)

[Precedente: Verify](04-verify.md) · [Indice](README.md) · [Successivo: Operate](06-operate.md)
