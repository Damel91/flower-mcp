# Flower oltre il percorso standalone

[Indice](README.md) · [Confronto](comparison.md) · [Mappa dei tool](tools.md)

**Flower può governare il ciclo di vita senza eseguire codice. Le integrazioni
cross-server collegano quel ciclo a un provider di evidenza ed esecuzione,
senza confonderne le responsabilità.**

Il percorso base resta quello raccontato in [Build](03-build.md): un coding
agent riceve un piano o una TODO, lavora attraverso il proprio host e dichiara
gli esiti. Il percorso integrato aggiunge scambi diretti con servizi compatibili.
CodingCastle è il provider tecnico per cui il sorgente pubblico contiene gli
adapter di packet e test; non è una dipendenza del core Flower.
[Factory dei provider](https://github.com/Damel91/flower-mcp/blob/d832b5e53ab3f1082f9143ae15abc70543f264b6/src/flow_of_work_mcp/runtime_factory.py).

## Chi possiede che cosa

| Parte | Responsabilità |
| --- | --- |
| Flower | Intento, requisiti e scenari, milestone, cambiamenti, packet semantici, finding, campagne, accettazione e handover. |
| Provider tecnico | Contesto tecnico, identità dei target, evidenza sorgente e, dove supportati, packet eseguibili, workspace, compilazione e test. |
| Orchestratore | Scelta dell'evidenza, interpretazione semantica, decisioni consentite dal gate corrente e gestione dei gap. |
| Persona | Conferma dell'intento e decisioni umane di accettazione e consegna previste dal percorso. |

Un provider raggiungibile non è automaticamente il provider del progetto.
Un test passato non è automaticamente una milestone accettata. Queste
separazioni sono parte delle [recipe pubbliche](https://github.com/Damel91/flower-mcp/blob/d832b5e53ab3f1082f9143ae15abc70543f264b6/src/flow_of_work_mcp/application/lifecycle_recipes.py).

## Associazioni portabili, non configurazione nascosta

`fow_bindings` permette di ispezionare, esportare e importare associazioni
host/progetto o progetto/provider mediante receipt JSON versionate. L'associazione
logica può cambiare senza riavviare il plane: il ledger conserva scelta e
revisione, e una sostituzione conflittuale richiede una ragione esplicita.

La receipt **non** installa un server e non configura endpoint, credenziali o
comandi. La route di provider deve essere già autorizzata dall'operatore.
Trasportare un'associazione non significa trasferire l'intero runtime o
ottenere il diritto di modificare una repository.
[Contratto delle associazioni](https://github.com/Damel91/flower-mcp/blob/d832b5e53ab3f1082f9143ae15abc70543f264b6/src/flow_of_work_mcp/application/association_receipts.py).

## Orientamento coordinato delle lens

Quando il contesto tecnico è associato, `fow_interaction` può integrare le aree
di Flower con quelle scoperte tramite `codingcastle_interaction`, mostrando
disponibilità e prerequisiti. Flower mantiene la lens coordinata; la discovery
del provider è di sola lettura e non altera la sua lens standalone.

La lens cambia l'attenzione, non il catalogo dei tool, il lifecycle o i permessi.
Se il provider non è disponibile, il frame espone la modalità coordinata
degradata e l'eventuale area tecnica bloccata, senza fingere disponibilità.
[Adapter di orientamento](https://github.com/Damel91/flower-mcp/blob/d832b5e53ab3f1082f9143ae15abc70543f264b6/src/flow_of_work_mcp/adapters/implementation_intelligence/interaction_provider.py), [proiezione dell'interazione](https://github.com/Damel91/flower-mcp/blob/d832b5e53ab3f1082f9143ae15abc70543f264b6/src/flow_of_work_mcp/application/interaction_projection.py).

## Snapshot sorgente e grounding dell'intento

Gli adapter di evidenza ricevono snapshot bounded di implementazione,
comportamento di bootstrap e target dei packet. Verificano il contratto, il
binding e i riferimenti di revisione richiesti: nomi o descrizioni non diventano
da soli evidenza corrente. La ricerca e il grafo restano nel provider; Flower
consuma una proiezione per il proprio lavoro di ingegneria.
[Adapter degli snapshot](https://github.com/Damel91/flower-mcp/blob/d832b5e53ab3f1082f9143ae15abc70543f264b6/src/flow_of_work_mcp/adapters/implementation_intelligence/mcp_provider.py).

Il grounding mette in relazione intento e implementazione osservata.
`fow_ground_intent` è il percorso interno con modello e provider sorgente.
`fow_semantic` offre anche incarichi eseguibili dall'host, con input e contratto
di risposta preparati da Flower; nel grounding host l'evidenza è una receipt
chiusa e conserva la provenienza dichiarata dall'host. Non è una conversione
automatica in attestazione di provider.
[Recipe semantica](https://github.com/Damel91/flower-mcp/blob/d832b5e53ab3f1082f9143ae15abc70543f264b6/src/flow_of_work_mcp/application/lifecycle_recipes.py).

## Dal packet semantico al lavoro tecnico

Flower mantiene istruzioni ordinate, verifiche, dipendenze e intento delle unità.
L'orchestratore sceglie candidati leggibili; il provider risolve i target tecnici
esatti. Identità del grafo, handle di esecuzione e correlazioni di trasporto
restano dietro quel confine, non diventano contenuto da copiare nel piano.

Nel percorso configurato, `fow_packet_advance` può delegare operazioni all'adapter
di `codingcastle_packet` e riconciliare i receipt. L'esecuzione interna e il
workspace appartengono a CodingCastle; Flower non diventa un secondo motore di
compilazione. Un provider assente, incompatibile o con evidenza stale lascia
un gate aperto, non autorizza un'esecuzione inventata.
[Adapter dei packet](https://github.com/Damel91/flower-mcp/blob/d832b5e53ab3f1082f9143ae15abc70543f264b6/src/flow_of_work_mcp/adapters/implementation_intelligence/packet_provider.py), [recipe di riconciliazione](https://github.com/Damel91/flower-mcp/blob/d832b5e53ab3f1082f9143ae15abc70543f264b6/src/flow_of_work_mcp/application/lifecycle_recipes.py).

## Review del workspace e correzione semantica

La review deve riferirsi al candidato corrente e rendere espliciti target,
copertura ed evidenze. Flower registra la disposizione e la storia dei finding;
il provider identifica il workspace. Una review parziale non diventa approvazione
completa soltanto perché non contiene un errore.

Un difetto semantico rilevato dopo la review alimenta un ordinario packet di
correzione. Non è il retry tecnico automatico di una compilazione fallita.
La recipe distingue proseguimento, verifica, remediation e blocco.
[Review e remediation nelle recipe](https://github.com/Damel91/flower-mcp/blob/d832b5e53ab3f1082f9143ae15abc70543f264b6/src/flow_of_work_mcp/application/lifecycle_recipes.py).

## Campagne, oracoli e test del provider

Flower definisce comportamento atteso, casi, obblighi e significato degli oracoli.
Il provider materializza ed esegue i test nel percorso supportato. L'adapter di
`codingcastle_tests` distingue sorgente fornito dall'orchestratore e IR di oracolo
deterministico; quest'ultimo richiede un profilo compatibile dichiarato dal
provider. Non è una promessa di generazione universale per qualsiasi linguaggio
o framework.

Per avanzare servono autorità di materializzazione e risultati correnti attestati.
Un test che compila ma non ha l'attestazione richiesta non prova un fallimento
autorevole del prodotto. E l'accettazione resta un'altra decisione.
[Adapter dei test](https://github.com/Damel91/flower-mcp/blob/d832b5e53ab3f1082f9143ae15abc70543f264b6/src/flow_of_work_mcp/adapters/implementation_intelligence/test_provider.py), [recipe delle campagne](https://github.com/Damel91/flower-mcp/blob/d832b5e53ab3f1082f9143ae15abc70543f264b6/src/flow_of_work_mcp/application/lifecycle_recipes.py).

## Due destinatari, due proiezioni

Il modello riceve contenuto leggibile in Markdown. Gli scambi server-to-server
consumano invece il canale MCP `structuredContent` secondo contratti versionati:
non reinterpretano il testo del modello come JSON. Il formato leggibile e il
receipt strutturato rispondono a destinatari diversi.
[Decodifica del canale strutturato](https://github.com/Damel91/flower-mcp/blob/d832b5e53ab3f1082f9143ae15abc70543f264b6/src/flow_of_work_mcp/adapters/implementation_intelligence/mcp_provider.py).

## Che cosa è presente e che cosa resta aperto

| Ambito | Stato e prerequisiti |
| --- | --- |
| Core e piano per coding agent esterno | Percorso standalone; nessun provider tecnico o modello interno obbligatorio. |
| Receipt di associazione | Contratto e servizi presenti; la route di un provider richiede autorizzazione operatore. |
| Lens coordinata | Discovery tecnica opzionale; contesto associato e provider disponibile, oppure degrado dichiarato nel frame. |
| Snapshot di evidenza | Adapter presenti; serve un servizio che rispetti lo specifico contratto, binding e revisione. Non basta «parla MCP». |
| Packet e test tecnici | Adapter CodingCastle presenti e opzionali; richiedono servizio, contesto e capacità compatibili. Non rendono automaticamente intercambiabile ogni coding agent. |
| Semantica interna | Richiede il runtime di inferenza; l'alternativa host esiste per i ruoli supportati, non per ogni operazione. |
| PVP cross-server completa | Esplicitamente differita, insieme alla compilazione CodingCastle della famiglia IMPL-67 e alla qualificazione accoppiata. La PVP standalone non certifica questo percorso. |

La presenza degli adapter nel sorgente **non certifica ogni combinazione di
versioni in esecuzione**. Questa pagina descrive capacità e confini del sorgente
di riferimento, non una nuova campagna live della coppia Flower/CodingCastle.
[Factory](https://github.com/Damel91/flower-mcp/blob/d832b5e53ab3f1082f9143ae15abc70543f264b6/src/flow_of_work_mcp/runtime_factory.py), [stato dichiarato nelle recipe](https://github.com/Damel91/flower-mcp/blob/d832b5e53ab3f1082f9143ae15abc70543f264b6/src/flow_of_work_mcp/application/lifecycle_recipes.py).

## Spazio Comune, con un provider

Nel nostro esempio, Flower conserva la regola «due prenotazioni concorrenti non
devono occupare la stessa sala» e governa il packet di correzione. Un provider
compatibile porta i target e il workspace; la campagna lega il test alla regola
e al suo oracolo. Il risultato tecnico ritorna come evidenza, non come decisione
automatica di consegna.

È un percorso illustrativo, non una run già eseguita. Il vantaggio architetturale
è mantenere insieme intento e lavoro tecnico senza farne un unico proprietario.
Per iniziare a usare Flower, il percorso standalone rimane sufficiente.

[Indice](README.md) · [Verify](04-verify.md) · [Fonti delle integrazioni](sources.md#integrazioni-cross-server)
