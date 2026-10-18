# Ora prova Flower MCP

[Precedente: Operate](06-operate.md) · [Indice](README.md)

Abbiamo seguito Spazio Comune dal requisito al cambiamento. L'ultimo passo è
portare questo metodo nel tuo progetto: **installare Flower e collegarlo al tuo
coding agent**. Spazio Comune resta uno scenario didattico; il download è il
server Flower MCP, nome pubblico di Flow of Work MCP.

## Repository e download pubblici

- [Repository GitHub](https://github.com/Damel91/flower-mcp): codice, README e documentazione corrente.
- [Release Flower MCP 0.6.1](https://github.com/Damel91/flower-mcp/releases/tag/v0.6.1): sette asset pubblicati della release.
- [Guida corrente di installazione](https://github.com/Damel91/flower-mcp/tree/main/docs/INSTALLATION.md): procedure, configurazione e rimozione.
- [Prerequisiti per sistema operativo](https://github.com/Damel91/flower-mcp/tree/main/docs/INSTALLATION.md#prerequisites): cosa preparare prima del download.

| File | A cosa serve |
| --- | --- |
| [install.sh](https://github.com/Damel91/flower-mcp/releases/download/v0.6.1/install.sh) | Installazione guidata su macOS e Linux. |
| [install.ps1](https://github.com/Damel91/flower-mcp/releases/download/v0.6.1/install.ps1) | Launcher PowerShell per Windows della stessa release. |
| [install_flower.py](https://github.com/Damel91/flower-mcp/releases/download/v0.6.1/install_flower.py) | Installer Python della release; richiede Python 3.11+. |
| [Pacchetto wheel](https://github.com/Damel91/flower-mcp/releases/download/v0.6.1/flow_of_work_mcp-0.6.1-py3-none-any.whl) | Installazione manuale del pacchetto Python. |
| [Archivio sorgente](https://github.com/Damel91/flower-mcp/releases/download/v0.6.1/flow_of_work_mcp-0.6.1.tar.gz) | Sorgente confezionato della release. |
| [SHA256SUMS](https://github.com/Damel91/flower-mcp/releases/download/v0.6.1/SHA256SUMS) | Checksum per verificare i file della release. |
| [BOOTSTRAP.md](https://github.com/Damel91/flower-mcp/releases/download/v0.6.1/BOOTSTRAP.md) | Istruzioni pubbliche per avviare il lavoro dell'agente con Flower. |

La release pubblicata `v0.6.1` contiene sette asset Flower e nessun wheel runtime.
Verifica i download rispetto al suo `SHA256SUMS`. Il launcher Windows installa 0.6.1.
La release storica [0.4.1](https://github.com/Damel91/flower-mcp/releases/tag/v0.4.1) conserva otto asset storici,
incluso runtime-llama `0.4.0`; quel vecchio extra Flower resta immutato.
La distribuzione Python è `flow-of-work-mcp`; il comando è `flower-mcp`.
I link alle guide operative correnti seguono il ramo mutabile `main`. La
[guida storica di installazione](https://github.com/Damel91/flower-mcp/blob/d82eb9f15f5a77961d06012fc25ecde3c5c8f18a/docs/INSTALLATION.md) e i
[prerequisiti storici](https://github.com/Damel91/flower-mcp/blob/d82eb9f15f5a77961d06012fc25ecde3c5c8f18a/docs/INSTALLATION.md#prerequisites)
conservano il checkpoint sorgente congelato. L'archivio immutabile 0.6.0 mantiene
le guide di preparazione; la documentazione corrente successiva non sostituisce quei byte.

## Sorgente corrente e runtime opzionale

Flower `0.6.1` contiene sette asset Flower: wheel, archivio sorgente,
tre installer, `BOOTSTRAP.md` e `SHA256SUMS`. Non incorpora un wheel runtime
né sostituisce gli asset storici 0.4.1.

L'extra `inference` del sorgente corrente seleziona la
[release llama-runtime `0.5.0`](https://github.com/Damel91/llama-runtime/releases/tag/v0.5.0)
pubblicata indipendentemente e il suo [wheel upstream](https://github.com/Damel91/llama-runtime/releases/download/v0.5.0/runtime_llama-0.5.0-py3-none-any.whl).
Il suo SHA256 è
`dc7c2e056f55f68181dd82158417e5f53e0aed8189a07acf10e59314a80f6d13`.
Il wheel upstream include `LICENSE`/`NOTICE` Apache-2.0 e l'attribuzione MIT
di llamatelemetry incorporato.

Flower `0.6.1` pubblicato e il sorgente corrispondente selezionano runtime `0.5.0`.
Flower `0.6.0` storico selezionava lo stesso runtime opzionale.
La release storica Flower `0.5.2` seleziona ancora runtime `0.4.1`; i suoi asset
restano immutabili. Usa questo comando solo in un ambiente nuovo/manuale:

```sh
.venv/bin/python -m pip install '.[inference]'
.venv/bin/python -m pip check
```

Per un **wheel locale 0.6.2 ottenuto dal sorgente o candidato**, usa un ambiente
nuovo/manuale. Questo esempio locale è distinto dall’artefatto pubblicato e verificato:

```sh
.venv/bin/python -m pip install './dist/flow_of_work_mcp-0.6.2-py3-none-any.whl[inference]'
```

Flower 0.6.1 è pubblicato al commit
`8de41beb1368ef772755b068b7404a91d3197f49`. Verifica il wheel ufficiale rispetto
al suo `SHA256SUMS`: release e build locale restano artefatti distinti.
L'extra seleziona runtime `0.5.0`. Un wheel ricostruito da sorgente
con la stessa versione è un altro artefatto; gli asset precedenti restano immutabili.

Per il wheel pubblicato `0.5.2` verificato, usa invece
`'./dist/flow_of_work_mcp-0.5.2-py3-none-any.whl[inference]'`: seleziona runtime
`0.4.1`, non il nuovo pin del sorgente corrente.
Questo comando è per ambienti nuovi/manuali. Un ambiente creato dall'installer
deve usare il wheel/build esatto già registrato nella propria receipt dopo il
normale upgrade core; un build sorgente successivo con la stessa versione non
è l'artefatto di quella receipt.
Windows usa `& .\.venv\Scripts\python.exe` con gli stessi argomenti pip.
Per adottare runtime `0.5.0` in una installazione opzionale esistente, aggiorna
solo lo SDK tramite URL/hash verificati, conservando wheel e receipt Flower.
Reinstallare il vecchio extra può selezionare di nuovo il vecchio SDK. Consulta la
[guida all'inferenza](https://github.com/Damel91/flower-mcp/tree/main/docs/INFERENCE.md)
per il percorso corrente da sorgente/wheel, i vincoli del build posseduto, la
verifica indipendente del checksum e l'acquisizione offline. Questo link operativo
segue il ramo mutabile `main`; i riferimenti congelati restano storici. Conserva
commit sorgente e inventario checksum selezionati. Verifica il wheel scelto
contro i checksum della sua release o build; il wheel storico `0.4.1` resta
immutabile. Gli installer core restano core-only e non configurano provider impliciti.

La [guida corrente alla configurazione avanzata](https://github.com/Damel91/flower-mcp/tree/main/docs/ADVANCED-CONFIGURATION.md)
spiega ruoli LLM, YAML, contratti dei provider esterni e receipt di associazione.
Questo link segue il ramo mutabile `main`; i riferimenti sorgente runtime nelle
altre pagine conservano il checkpoint storico congelato. La release 0.6.0 separa
i requisiti realizzati dalla milestone dai prerequisiti di milestone precedenti,
certifica solo i rifiuti correlati prima della scrittura della milestone e aggiunge
la cancellazione nativa esplicita riservata all'host. Conserva la correzione del
recupero di 0.5.2 e le descrizioni precedenti. Ricarica lo schema dell'host:
`prerequisite_requirement_ids` sostituisce `dependency_closure_ids`; usa `[]`
quando non ci sono prerequisiti. La cancellazione non è un tool MCP né un passo
di aggiornamento; leggi i suoi
[limiti](https://github.com/Damel91/flower-mcp/tree/main/docs/NATIVE-PROJECT-DELETION.md).
La durabilità della cancellazione nativa su Windows resta non qualificata.
Il witness resta differito. I comandi sotto installano 0.6.1 pubblicato;
le modalità di installazione e l'usabilità del provider/client restano evidenze distinte.

La versione 0.6.1 aggiunge un catalogo completo e di sola lettura delle operazioni
delle lens: l’harness può presentare i verbi pertinenti mantenendo i normali gate
di esecuzione. Vedi la
[guida corrente al catalogo](https://github.com/Damel91/flower-mcp/tree/main/docs/LENS-CATALOG.md).
Sette asset anonimi e un aggiornamento HTTPS macOS 0.6.0 → 0.6.1 su stato di test
posseduto sono stati verificati separatamente da sorgente, pacchetto installato e CI.
Nessuna installazione reale dell’utente è stata modificata; questo non certifica
un OS sconosciuto, l’usabilità del modello o l’accettazione.
Tag e asset pubblicati sono preservati per policy, senza immutabilità imposta da GitHub.

## Prima di installare

| Percorso | Prerequisiti essenziali |
| --- | --- |
| macOS / Linux, installer Bash | Bash, curl, awk, sha256sum o shasum, utility shell, accesso HTTPS e Internet. Python adatto viene riutilizzato o preparato dall'installer. |
| Windows, launcher PowerShell | Windows PowerShell 5.1+, accesso HTTPS e Internet. Python adatto viene riutilizzato o preparato dal launcher. |
| Installazione manuale o installer Python | Python 3.11+ con ssl, venv ed ensurepip; accesso alle dipendenze. Git serve solo per clonare il sorgente. |
| Collegamento all'agente | Codex, Claude Code, Cursor, Antigravity o Gemini CLI già installato; directory utente scrivibile. |

**Il core non richiede LM Studio, un modello interno, CodingCastle o una VPN.**
L'inferenza normalmente rimane quella del coding agent scelto. L'inferenza interna
opzionale di Flower richiede un runtime installato esplicitamente e un endpoint
configurato; vedi la [guida all'inferenza](https://github.com/Damel91/flower-mcp/tree/main/docs/INFERENCE.md).
Il reader è consultabile offline, mentre una nuova installazione scarica pacchetti e dipendenze.

## Usi già Flower? Conserva il ledger

Segui il [piano corrente di aggiornamento sicuro](https://github.com/Damel91/flower-mcp/tree/main/docs/UPGRADING.md)
(la [guida storica](https://github.com/Damel91/flower-mcp/blob/d82eb9f15f5a77961d06012fc25ecde3c5c8f18a/docs/UPGRADING.md) conserva il checkpoint sorgente)
con l'ambiente, il profilo e la radice dei profili originali. Ferma tutti i processi
Flower e i coding client che condividono quell'ambiente. Per un'installazione
creata dall'installer, visualizza il piano prima di modificare i pacchetti:

```sh
curl -fsSL https://github.com/Damel91/flower-mcp/releases/download/v0.6.1/install.sh | bash -s -- --upgrade --dry-run
```

Su Windows scarica il nuovo `install.ps1` mostrato sotto, poi visualizza il piano
senza opzioni per la registrazione del client:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\install.ps1 -Version '0.6.1' -Upgrade -DryRun
```

Per percorsi personalizzati aggiungi le opzioni originali `--venv`, `--profile`
e `--profile-root`; Windows usa `-Venv`, `-Profile` e `-ProfileRoot`. Controlla il
piano, poi ripeti senza `--dry-run` / `-DryRun`. L'aggiornamento salva un backup
del ledger SQLite selezionato e dello YAML esatto prima di pip, conserva la
registrazione del client e non aggiunge migrazioni da un profilo schema 55 a
0.6.1. Un'installazione più vecchia 0.3.1/schema 52 usa ancora le migrazioni
additive esistenti da 52 a 55 al successivo avvio del server. Conserva i percorsi
dei backup restituiti. L'aggiornamento non resetta il ledger e non ripristina
automaticamente un backup; un errore di pip può modificare parzialmente l'ambiente.
Le installazioni pip manuali usano la procedura separata di backup
nella stessa guida. Dopo il riavvio riprendi il progetto noto; non crearne uno
sostitutivo per recuperare lo stato.

Questo aggiornamento di core/profilo non richiede l'extra inference e non cambia
le impostazioni del modello. Aggiornare il runtime opzionale è un'operazione
esplicita separata dal sorgente/candidato corrente selezionato; segui la guida
all'inferenza prima di modificare i pacchetti Flower. Il core di un'installazione
posseduta dall'installer deve prima completare il normale upgrade; poi l'extra
deve usare lo stesso wheel/build verificato di Flower registrato nella receipt,
con versione e SHA256 corrispondenti. Non sostituirlo con una build da sorgente
della stessa versione o con un build diverso solo tramite pip.
Usa un ambiente manuale separato per le prove da sorgente/candidato. Conserva endpoint e profilo originali.

## Scegli una strada

### macOS e Linux

Dopo aver controllato i prerequisiti, il comando pubblico avvia l'installer
guidato e permette di scegliere l'agente o la sola installazione:

```sh
curl -fsSL https://github.com/Damel91/flower-mcp/releases/download/v0.6.1/install.sh | bash
```

Lo script prepara un ambiente Python isolato e verifica i checksum del backend
e del wheel. Puoi scaricare e leggere [lo script](https://github.com/Damel91/flower-mcp/releases/download/v0.6.1/install.sh)
prima di eseguirlo. Opzioni e procedure manuali sono nella guida completa.

### Windows

In una directory scrivibile, scarica il launcher pubblico e scegli il client.
Qui l'esempio usa Codex:

```powershell
Invoke-WebRequest -UseBasicParsing -Uri "https://github.com/Damel91/flower-mcp/releases/download/v0.6.1/install.ps1" -OutFile ".\install.ps1"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\install.ps1 -Version '0.6.1' -Platform codex
```

Esegui i due comandi separatamente e fermati se il download fallisce. Puoi
leggere lo script prima di avviarlo. `-Platform claude-code`, `-Platform cursor`,
`-Platform antigravity` o `-Platform gemini-cli` selezionano gli altri client;
`-NoRegister` installa senza registrarne uno.
L'opzione di execution policy vale solo per quel processo PowerShell.

Per installare manualmente, segui [la procedura corrente con wheel e checksum](https://github.com/Damel91/flower-mcp/tree/main/docs/INSTALLATION.md#manual-installation-from-a-release-wheel).
La [procedura storica](https://github.com/Damel91/flower-mcp/blob/d82eb9f15f5a77961d06012fc25ecde3c5c8f18a/docs/INSTALLATION.md#manual-installation-from-a-release-wheel) resta un riferimento sorgente.

## Dall'installazione al primo requisito

1. Conserva il percorso dell'eseguibile e il comando di bootstrap restituiti
   dall'installer. Dopo la registrazione ricarica il client e approva la connessione
   MCP secondo le sue richieste. Il client avvia il server registrato.
2. Chiedi all'agente di eseguire `flower-mcp bootstrap` usando quel percorso.
   Il comando stampa istruzioni: l'agente le integra nel progetto scelto,
   preservando le regole esistenti. [Il bootstrap pubblico](../../BOOTSTRAP.md)
   spiega questo passaggio.
3. L'agente legge `fow_capabilities`, scopre e seleziona esplicitamente il progetto
   tramite `fow_interaction`; se il ledger è nuovo, crea prima il progetto
   concordato con `fow_create_project`.
4. Recupera lo snapshot con `fow_handover` e inizia dalla domanda di Require:
   **quale comportamento vogliamo ottenere, in quale scenario e con quali limiti?**

Per una prima prova usa un progetto separato: puoi riprendere Spazio Comune,
chiarire un caso d'uso e arrivare a un piano esportabile. Installazione riuscita
e `doctor` non dimostrano da soli che il client sia collegato: verifica che
l'agente veda i tool e riesca a recuperare lo snapshot.

Se incontri un problema, riportalo nelle [issue della repository](https://github.com/Damel91/flower-mcp/issues)
indicando sistema operativo, versione, client, operazione ed errore, senza
credenziali o dati personali. Flower `0.6.1` resta in fase di test. Le modalità di
installazione e l'effettiva usabilità nel coding client sono verifiche distinte.

[Torna a Require](01-require.md) · [Repository GitHub](https://github.com/Damel91/flower-mcp) · [Indice](README.md)
