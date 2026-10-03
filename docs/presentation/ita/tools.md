# La mappa dei tool pubblici

[Indice](README.md) · [Concetti](concepts.md) · [Fonti](sources.md#catalogo)

I nomi conservano il prefisso tecnico `fow_`. Un client può aggiungere un proprio
prefisso. Questa mappa descrive i **36 tool del sorgente di riferimento**; non è
un elenco di payload da copiare. Un tool multiplexato offre più operazioni con
prerequisiti diversi. Il catalogo corrente del server rimane l'autorità operativa.

## Orientamento e bootstrap

| Tool | A che cosa serve |
| --- | --- |
| `fow_capabilities` | Leggere sintesi, una recipe, un contratto di operazione o documentazione dettagliata. |
| `fow_create_project` | Creare un progetto di ciclo di vita isolato. La creazione non equivale alla selezione. |
| `fow_interaction` | Selezionare progetto e lens, ottenere un frame operativo e risolvere una scelta. La risoluzione suggerisce una chiamata, non la esegue. |
| `fow_bootstrap` | Gestire intake, risposte, corrispondenze, roadmap e conferme. Contiene anche operazioni di binding che hanno prerequisiti propri. |

## Requisiti e comportamento

| Tool | A che cosa serve |
| --- | --- |
| `fow_register_requirement` | Registrare un requisito canonico. |
| `fow_get_requirement` | Recuperare requisito e storia immutabile. |
| `fow_revise_requirement` | Aggiungere una revisione invece di sovrascrivere la precedente. |
| `fow_set_requirement_lifecycle` | Eseguire una transizione ammessa dalla policy. |
| `fow_goal` | Definire e leggere casi d'uso, sequenze e aspettative comportamentali. |
| `fow_validate_srs` | Avviare la validazione strutturale di una SRS con stato job durevole. La semantica usa un percorso distinto. |
| `fow_import_srs` | Validare e importare atomicamente una baseline iniziale accettata. |
| `fow_revise_srs_baseline` | Classificare e registrare una revisione della baseline con provenienza del sorgente. |

## Milestone

| Tool | A che cosa serve |
| --- | --- |
| `fow_promote_milestone` | Definire scope e politiche di una milestone pianificata. |
| `fow_accept_milestone` | Registrare l'accettazione governata, con le evidenze richieste. Non è un sinonimo di pianificazione. |

## Cambiamenti e lavoro

| Tool | A che cosa serve |
| --- | --- |
| `fow_change` | Governare cambiamenti, dipendenze, stato ed evidenze; i packet hanno superfici dedicate. |
| `fow_packet_author` | Costruire packet, unità, dichiarazioni e piani canonici. |
| `fow_packet_advance` | Avanzare i gate deterministici fino a una decisione o a un confine asincrono. Il percorso tecnico scelto può richiedere provider. |
| `fow_packet_inspect` | Leggere scope, unità, gate o storia con proiezioni bounded. |
| `fow_external_work` | Validare il piano standalone, selezionare la modalità esterna, esportare Markdown, leggere TODO e registrare/riconciliare esiti. Non esegue codice. |
| `fow_run` | Gestire record di run, step, dipendenze e viste del lavoro di implementazione. Non è un nuovo agente di coding. |
| `fow_what_next` | Derivare il lavoro successivo dallo stato durevole, con paginazione. |

## Evidenza e campagne

| Tool | A che cosa serve |
| --- | --- |
| `fow_record_verification` | Registrare evidenze deterministiche o live dichiarate. Non genera da solo i risultati di test. |
| `fow_traceability` | Leggere la proiezione paginata della tracciabilità del progetto. |
| `fow_audit_phase` | Avviare un audit di fase su uno scope dichiarato; i prerequisiti dipendono dall'audit. |
| `fow_assurance` | Registrare finding, rivalutare intento, collegare correzioni e governare decisioni di assurance. |
| `fow_campaign_author` | Costruire campagne, casi, obblighi, oracoli e autorità di materializzazione. |
| `fow_campaign_advance` | Avanzare lavoro deterministico fino a un confine semantico, tecnico o di evidenza. L'esecuzione tecnica richiede il percorso disponibile. |
| `fow_campaign_inspect` | Leggere campagna, working sheet, componenti o storia. |

## Continuità e artefatti

| Tool | A che cosa serve |
| --- | --- |
| `fow_handover` | Leggere snapshot coerente, progresso e storia bounded; creare o recuperare handover. |
| `fow_generate_artifacts` | Avviare generazione di artefatti nei profili supportati, con job durevole. |
| `fow_get_artifacts` | Recuperare metadati e contenuti degli artefatti conservati. |
| `fow_get_job` | Osservare lo stato di un job. Osservare non significa riavviarlo. |
| `fow_list_jobs` | Elencare job di un progetto. |

## Associazioni e semantica opzionale

Per ownership e prerequisiti del percorso integrato, leggi le
[funzionalità cross-server](advanced.md).

| Tool | A che cosa serve | Limite da ricordare |
| --- | --- | --- |
| `fow_bindings` | Ispezionare, esportare e importare receipt di associazione host/provider. | Le receipt non installano endpoint, credenziali o comandi. |
| `fow_semantic` | Inventariare ruoli, preparare incarichi SRS/grounding, ispezionare, sottoporre e adottare risultati, oppure invocare esplicitamente la modalità interna. | L'host non richiede un modello interno; la modalità interna sì. I ruoli non supportati restano visibili come limite. |
| `fow_ground_intent` | Avviare il grounding interno dell'intento. | Richiede modello e provider sorgente: non è un requisito del core standalone. |

## Come scoprire i dettagli senza memorizzare tutto

Esempi di chiamate di sola consultazione, senza locatori di progetto inventati:

```json
{"view": "recipe", "recipe_name": "standalone-external-plan"}
```

```json
{"view": "operation", "operation_tool": "fow_external_work", "operation_name": "export_plan"}
```

Sono argomenti di `fow_capabilities`, non comandi di esecuzione del piano.
La recipe spiega il percorso; il contratto dell'operazione espone campi e vincoli;
il frame corrente fornisce le scelte ammesse nello stato del progetto.

[Indice](README.md) · [Segui Build nella storia](03-build.md)
