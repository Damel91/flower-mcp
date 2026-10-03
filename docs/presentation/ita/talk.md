# Una traccia per raccontarlo

[Indice](README.md) · [Scenario](scenario.md) · [Fonti e limiti](sources.md)

## Apertura

«Due persone prenotano la stessa sala. Il codice era compilato, i test erano
verdi e la schermata era bella. Che cosa avevamo realmente chiesto al software?»

La domanda introduce Spazio Comune senza richiedere conoscenza di MCP. Mostrare
il logo dopo la domanda: i petali danno i nomi alle prospettive, non la risposta.

## Percorso principale

| Passaggio | Elemento da mostrare | Messaggio da lasciare |
| --- | --- | --- |
| [Require](01-require.md) | Due richieste simultanee. | Prima della tecnologia serve un risultato osservabile. |
| [Plan](02-plan.md) | Il contratto tra servizio e interfaccia. | Le dipendenze devono contenere significato, non soltanto nomi. |
| [Build](03-build.md) | Il piano che sopravvive a un'interruzione. | L'agente esegue; Flower conserva l'autorità del lavoro. |
| [Verify](04-verify.md) | Quattro dimensioni di stato. | Un controllo locale non si promuove a campagna o accettazione. |
| [Deploy](05-deploy.md) | Una consegna con obblighi aperti. | Precisare i limiti rende la promessa controllabile. |
| [Operate](06-operate.md) | Bug oppure prenotazione ricorrente? | Correzione e nuovo intento richiedono percorsi diversi. |

Per un intervento breve si possono usare solo le sei pagine. Concetti, tool e
fonti restano deviazioni per le domande: non bisogna leggere un catalogo dal palco.
La durata effettiva andrà provata a voce; questa non è una scaletta cronometrata.

Per raccontare l'origine del progetto, aprire [Come l'ho costruito](method.md):
separare il codice scritto dagli agenti dalla progettazione e dalle decisioni
dell'autore. I ritagli mostrano il metodo, non certificano i risultati dei test.

## Se vogliamo una dimostrazione reale

La storia scritta non è un transcript. Una demo successiva dovrebbe selezionare
un progetto isolato, usare i contratti correnti e conservare vere receipt:

1. mostrare un criterio senza verifica o un consumatore senza produttore;
2. leggere il gap restituito da Flower;
3. completare la dichiarazione e mostrare la nuova proiezione;
4. esportare il piano e distinguere il lavoro eseguibile dagli obblighi differiti.

Non inserire ID inventati nelle chiamate. Non usare il progetto runtime privato
come se fosse un ambiente dimostrativo. Non mostrare «accettato» senza una
decisione reale. In caso di assenza di rete il percorso editoriale è già offline;
non deve fingere di essere una demo live riuscita.

## Domande che meritano una risposta esplicita

- **«Perché non basta un documento?»** Il documento esportato è utile. Flower
  aggiunge stato canonico, revisioni, gate e riconciliazione attraverso il server.
- **«Il modello può ignorarlo?»** Sì, un agente può usare altri strumenti: Flower
  non è una sandbox del suo host. L'aderenza si prova, non si presume.
- **«Serve un modello locale?»** No per il core standalone. Modello interno e
  provider sono optional per capacità specifiche.
- **«Garantisce software corretto?»** No. Delimita lavoro, evidenza e decisioni;
  qualità dell'agente, del piano e degli oracoli restano decisive.
- **«Deploy e Operate sono automatizzati?»** No. Il racconto riguarda il governo
  di consegna e cambiamento, non CI/CD o monitoraggio built-in.

## Chiusura

«Non sto chiedendo al modello di ricordare meglio. Sto rendendo recuperabile
che cosa abbiamo deciso, quale lavoro gli abbiamo affidato e che cosa manca
ancora per chiamarlo finito.»

Concludere aprendo [Ora prova Flower](try-flower.md): mostrare la repository,
la release e il percorso di installazione per il sistema del pubblico. Collegare
il bootstrap alla prima domanda di Require, senza presentarlo come un settimo
petalo o come una demo già eseguita.

[Installa e prova Flower](try-flower.md) · [Indice](README.md) · [Catalogo dei tool](tools.md)
