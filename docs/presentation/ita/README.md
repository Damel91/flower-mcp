# Flower MCP: dal requisito al software

![Flower MCP: Require, Plan, Build, Verify, Deploy, Operate](../assets/flower-mcp-logo.png)

[English](../eng/README.md) · [Lingue disponibili](../README.md)

**Scrivere codice è una parte del lavoro. Tenere insieme ciò che volevamo,
ciò che abbiamo fatto e ciò che possiamo dimostrare è un'altra.**

Questo percorso accompagna lo sviluppo di **Spazio Comune**, un piccolo servizio
per prenotare le sale di un'associazione. La stessa storia attraversa i sei
petali del logo: Require, Plan, Build, Verify, Deploy e Operate.

> Spazio Comune è uno scenario didattico, non un'applicazione prodotta o un
> benchmark superato. Dialoghi, requisiti e piani sono esempi editoriali. I
> comportamenti attribuiti a Flower sono collegati alle sue fonti pubbliche.

## La storia, in sei domande

| Capitolo | Domanda | Il problema che incontreremo |
| --- | --- | --- |
| [1. Require](01-require.md) | Che cosa significa davvero «prenotare una sala»? | Un desiderio comprensibile non è ancora un comportamento definito. |
| [2. Plan](02-plan.md) | Il piano si può eseguire senza inventare le parti mancanti? | Una lista di attività può nascondere dipendenze e decisioni. |
| [3. Build](03-build.md) | Chi scrive il codice, e che cosa mantiene Flower? | Il lavoro dell'agente deve tornare a un'intenzione e a una revisione riconoscibili. |
| [4. Verify](04-verify.md) | Che cosa abbiamo verificato, esattamente? | «I test passano» non equivale a «il comportamento è stato accettato». |
| [5. Deploy](05-deploy.md) | Che cosa siamo autorizzati a consegnare? | Un risultato locale non dimostra il funzionamento nell'ambiente di destinazione. |
| [6. Operate](06-operate.md) | Il problema emerso cambia il software o cambia la richiesta? | Correggere un difetto e introdurre una funzione nuova sono decisioni diverse. |

Il percorso si chiude con [Ora prova Flower](try-flower.md): repository, download
pubblici, prerequisiti e collegamento dell'agente al tuo primo progetto.

## Tre partecipanti, tre responsabilità

- **La persona:** chiarisce l'intento, conferma lo scope e possiede le decisioni
  di accettazione e consegna che le competono.
- **L'agente di coding:** indaga, sceglie la realizzazione tecnica, scrive codice,
  esegue i controlli e dichiara i risultati attraverso gli strumenti del suo host.
- **Flower MCP:** conserva lo stato del ciclo di vita, applica i gate previsti
  dai contratti e restituisce contesto, lavoro e provenienza delle evidenze.

Flower non è un nuovo modello e non sostituisce il coding agent. Il core non
richiede CodingCastle né un modello interno. Un agente capace rimane necessario:
il server non decide al suo posto che un requisito sia giusto o che il software
abbia valore per l'utente.

## Puoi leggere anche per argomento

- [Lo scenario completo](scenario.md): personaggi, scope e punti aperti della storia.
- [I concetti essenziali](concepts.md): lens, packet, PVP, TODO ed evidenza corrente.
- [La mappa dei tool pubblici](tools.md): quali strumenti appartengono a ogni area.
- [Il confronto con altri plane](comparison.md): pro, compromessi e casi d'uso, incluso il Flow documentale.
- [Le integrazioni avanzate](advanced.md): evidenza, packet, workspace e campagne cross-server.
- [Come l'ho costruito](method.md): agenti, plane documentale, tempo e dimensione del sorgente.
- [Fonti e limiti](sources.md): da dove vengono le affermazioni e cosa non promettiamo.
- [La traccia per il talk](talk.md): percorso breve, domande e deviazioni utili.
- [Il reader locale](reader.md): consultazione offline degli stessi Markdown.

Non è una catena a senso unico. Un test può riportarci ai requisiti; un problema
in uso può aprire un cambiamento. I petali raccontano il ciclo, non impongono sei
passaggi automatici o sei tool da eseguire in sequenza.

**Inizia da [Require](01-require.md).**
