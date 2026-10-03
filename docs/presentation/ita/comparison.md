# Quale plane per quale lavoro?

[Indice](README.md) · [Concetti](concepts.md) · [Integrazioni avanzate](advanced.md)

**Il confronto utile non è «chi ha più tool», ma «quale stato deve sopravvivere
alla conversazione, e chi ne governa il cambiamento».**

Flower non è l'unico progetto che organizza il lavoro di un agente. Alcuni
strumenti privilegiano le specifiche, altri il backlog o i gate dei task.
Il Flow of Work documentale parte invece da contratti leggibili e versionabili,
senza richiedere un server MCP.

## Come leggere il confronto

Ricognizione delle fonti ufficiali consultate il **2 ottobre 2026**. La tabella
riporta capacità documentate; pro, compromessi e casi consigliati sono una
valutazione editoriale, non risultati di un benchmark comparativo.

Non abbiamo installato e qualificato tutti i progetti. Una funzione non citata
qui **non va considerata assente**. Stelle, numero di contributor e numero di
tool non sono misure della correttezza del software prodotto.

## Cinque alternative, cinque centri di gravità

| Plane | Centro di gravità | Pro | Compromesso da valutare | Caso d'uso consigliato |
| --- | --- | --- | --- | --- |
| [Flower MCP](../../../README.md) | Requisiti, goal, milestone, cambiamenti, lavoro, evidenze, accettazione e handover in un ledger persistente. | Collega intento e lavoro corrente; distingue completamento, verifica e accettazione; offre piani Markdown e TODO per agenti esterni. | Più concetti da apprendere rispetto a un backlog. Le dichiarazioni dell'host non equivalgono a un audit automatico del codice. | Un prodotto seguito per più iterazioni, dove serve sapere perché si lavora, che cosa è stato verificato e che cosa resta aperto. |
| [LLM Flow of Work documentale](https://github.com/Damel91/LLMs-flow-of-work) | Contratti Markdown, autorità e catene di implementazione; **non è un server MCP**. | Documenti ispezionabili in Git; utilizzabile anche in chat; helper `flowctl` per controlli e orientamento. | Routing umano e disciplina documentale restano centrali; la coerenza non viene interamente governata da un ledger server. | Un team o un ingegnere che vuole rendere espliciti metodo e decisioni senza introdurre un servizio persistente. |
| [Spec Workflow MCP](https://github.com/Pimzino/spec-workflow-mcp) | Specifiche Requirements → Design → Tasks, approvazioni e tracciamento. | Dashboard, integrazione VS Code, revisioni e log di implementazione. | Il percorso di approvazione richiede coordinamento umano nell'interfaccia; approvare un documento non prova il comportamento implementato. | Una feature da chiarire e approvare prima di implementarla. |
| [Task Master AI](https://github.com/eyaltoledano/claude-task-master) | Dal PRD al backlog: task, dipendenze, espansione e prossimo lavoro. | Accesso MCP e CLI; aiuto alla decomposizione e alla ricerca. | I comandi AI richiedono accesso all'inferenza; il piano generato va giudicato, non soltanto eseguito. | Trasformare un brief di prodotto in attività operative per un coding agent. |
| [MCP Task Orchestrator](https://github.com/jpicklyk/task-orchestrator) | Work item persistenti, dipendenze, schemi di note e transizioni governate dal server. | Gate strutturali lato server e attribuzione degli attori. | Va progettato lo schema di lavoro; note obbligatorie e transizioni valide non dimostrano da sole correttezza semantica. | Coordinare agenti o sessioni con deliverable richiesti prima di avanzare. |

## Dove si colloca Flower

La scelta progettuale di Flower è mantenere una **catena di autorità del ciclo di
vita**, non soltanto una lista di attività: requisito e scenario, scope della
milestone, cambiamento, piano, finding, verifica, accettazione e handover.
Le revisioni e la provenienza delle evidenze servono a non promuovere il risultato
di ieri a completamento del lavoro di oggi. Il core può farlo senza CodingCastle
o un modello interno. [Fonti Flower](sources.md#plan), [lavoro esterno](sources.md#build).

**I gate lato server non sono un'esclusiva di Flower.** Il confronto con Task
Orchestrator riguarda soprattutto il dominio governato, non la presenza o
assenza di controllo strutturale. Per preferire Flower bisogna aver bisogno dei
suoi legami di ciclo di vita; per una semplice coda di task potrebbero essere
un costo non necessario.

La portabilità dei piani non elimina il ledger: il documento esportato permette
di lavorare offline, ma risultati, revisione corrente e decisioni vanno
riconciliati al ritorno. Le [integrazioni avanzate](advanced.md) aggiungono
evidenza ed esecuzione tecnica attraverso provider; non sono necessarie per il
percorso standalone.

## La stessa storia, scelte diverse

Per **Spazio Comune**, la domanda pratica può essere:

- «Voglio contratti e decisioni leggibili in Git, con la persona al timone»:
  partire dal Flow documentale.
- «Voglio approvare la specifica della prenotazione prima di implementarla»:
  valutare Spec Workflow MCP.
- «Ho un PRD e devo ricavarne un backlog eseguibile»: valutare Task Master AI.
- «Più agenti devono consegnare note richieste e rispettare dipendenze»:
  valutare Task Orchestrator.
- «Devo distinguere richiesta iniziale, difetto di concorrenza, correzione,
  regressione verificata e accettazione della milestone»: valutare Flower.

Sono indicazioni di scelta, non una graduatoria. Un prototipo di una sera e un
servizio mantenuto per mesi possono richiedere livelli di governance diversi.
Più struttura è utile soltanto se risolve un problema reale.

## Prima di scegliere

Chiedere a ogni soluzione le stesse cose: dove vive lo stato, come si recupera
dopo un'interruzione, quale decisione blocca l'avanzamento, che cosa conta come
evidenza e quanto lavoro richiede all'utente. Poi provare lo stesso piccolo
scenario sul proprio host e con il proprio agente.

Questo confronto non certifica prestazioni, sicurezza, autonomia del modello o
superiorità di Flower. Per queste affermazioni servono campagne comparabili,
non la sola lettura dei README.

[Indice](README.md) · [Fonti del confronto](sources.md#confronto-tra-plane) · [Funzionalità cross-server](advanced.md)
