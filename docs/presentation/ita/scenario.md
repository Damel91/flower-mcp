# Spazio Comune: una storia da seguire

[Indice](README.md) · [Require](01-require.md)

## «Ci serve un sito per prenotare le sale»

Un'associazione gestisce due sale. Le prenotazioni passano per messaggi e un
foglio condiviso. Due persone possono credere di aver ottenuto lo stesso spazio.
Chi coordina deve ricostruire chi ha chiesto cosa e quale richiesta è confermata.

**Marta** coordina l'associazione. **Luca** organizza gli incontri. Un **agente di
coding** aiuta a costruire il servizio. Flower conserva il progetto del servizio,
non le prenotazioni degli associati: il database dell'applicazione e il ledger
di ingegneria sono due cose diverse.

## Scope iniziale della storia

La prima versione offre una vista delle disponibilità, una richiesta di
prenotazione, un esito esplicito e la cancellazione da parte di chi è autorizzato.
Pagamenti, prenotazioni ricorrenti e notifiche esterne non sono nel primo scope.

Le regole non diventano vere perché le scriviamo qui. Nel racconto le assumiamo
chiarite da Marta e registrate dall'agente nel progetto Flower:

| Etichetta didattica | Comportamento concordato |
| --- | --- |
| SC-R1 | Due prenotazioni confermate non possono occupare la stessa sala nello stesso intervallo. |
| SC-R2 | L'interfaccia distingue conferma, conflitto e indisponibilità temporanea: un errore non diventa una conferma implicita. |
| SC-R3 | Un associato cancella la propria prenotazione; il coordinatore può gestire anche quelle degli altri. |
| SC-R4 | L'esito di una cancellazione rende osservabile la nuova disponibilità. |

`SC-R1` e le altre etichette servono soltanto a seguire la storia. **Non sono ID
emessi da Flower.** I veri ID, le revisioni e i fingerprint si recuperano dal
server; non si inventano per rendere credibile una dimostrazione.

## Le due domande che ritornano

1. **Due richieste simultanee:** la schermata può mostrare disponibilità a entrambe
   le persone. Quale componente deve impedire due conferme?
2. **Conferma non ricevuta:** la connessione cade. Luca riprova. Come distinguere
   una richiesta nuova dall'osservazione di un risultato già esistente?

Sono problemi del prodotto che l'agente deve investigare e realizzare. Flower
aiuta a registrarne il significato e gli obblighi di verifica; non implementa
automaticamente la concorrenza o l'idempotenza del servizio di prenotazione.

## Che cosa non è questa storia

Non è una prova che un modello locale sappia costruire Spazio Comune. Non è un
confronto prestazionale con altri agenti. Non è una dichiarazione di sicurezza,
conformità o qualità production-grade. È un modo concreto di capire che cosa
governa Flower prima, durante e dopo il codice.

[Torna all'indice](README.md) · [Entra nel primo scenario](01-require.md)
