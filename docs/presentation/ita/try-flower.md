# Ora prova Flower MCP

[Precedente: Operate](06-operate.md) · [Indice](README.md)

Abbiamo seguito Spazio Comune dal requisito al cambiamento. L'ultimo passo è
portare questo metodo nel tuo progetto: **installare Flower e collegarlo al tuo
coding agent**. Spazio Comune resta uno scenario didattico; il download è il
server Flower MCP, nome pubblico di Flow of Work MCP.

## Repository e download pubblici

- [Repository GitHub](https://github.com/Damel91/flower-mcp): codice, README e documentazione corrente.
- [Release Flower MCP 0.4.0](https://github.com/Damel91/flower-mcp/releases/tag/v0.4.0): pacchetti e note della versione.
- [Guida di installazione della release](https://github.com/Damel91/flower-mcp/blob/0a1dfd3043ae5cea628c3cf26107a015336794d3/docs/INSTALLATION.md): procedure complete, configurazione e rimozione.
- [Prerequisiti per sistema operativo](https://github.com/Damel91/flower-mcp/blob/0a1dfd3043ae5cea628c3cf26107a015336794d3/docs/INSTALLATION.md#prerequisites): cosa preparare prima del download.

| File | A cosa serve |
| --- | --- |
| [install.sh](https://github.com/Damel91/flower-mcp/releases/download/v0.4.0/install.sh) | Installazione guidata su macOS e Linux. |
| [install.ps1](https://github.com/Damel91/flower-mcp/releases/download/v0.4.0/install.ps1) | Launcher PowerShell per Windows della stessa release. |
| [install_flower.py](https://github.com/Damel91/flower-mcp/releases/download/v0.4.0/install_flower.py) | Installer Python della release; richiede Python 3.11+. |
| [Pacchetto wheel](https://github.com/Damel91/flower-mcp/releases/download/v0.4.0/flow_of_work_mcp-0.4.0-py3-none-any.whl) | Installazione manuale del pacchetto Python. |
| [Archivio sorgente](https://github.com/Damel91/flower-mcp/releases/download/v0.4.0/flow_of_work_mcp-0.4.0.tar.gz) | Sorgente confezionato della release. |
| [SHA256SUMS](https://github.com/Damel91/flower-mcp/releases/download/v0.4.0/SHA256SUMS) | Checksum per verificare i file della release. |
| [BOOTSTRAP.md](https://github.com/Damel91/flower-mcp/releases/download/v0.4.0/BOOTSTRAP.md) | Istruzioni pubbliche per avviare il lavoro dell'agente con Flower. |
| [Wheel runtime opzionale](https://github.com/Damel91/flower-mcp/releases/download/v0.4.0/runtime_llama-0.4.0-py3-none-any.whl) | Configurazione esplicita dell'inferenza interna; l'installazione core lo esclude. |

La release `v0.4.0` contiene otto asset, inclusi `install.ps1` e il wheel opzionale
runtime-llama `0.4.0`. Verifica tutti i download rispetto a `SHA256SUMS`.
Il launcher Windows installa il wheel `0.4.0`.
Il nome della distribuzione Python resta `flow-of-work-mcp`; il comando è
`flower-mcp`. I download sono fissati alla release e la guida di installazione
al suo checkpoint documentato. Esegui i comandi solo quando i corrispondenti asset sono pubblicati.
Il README corrente segue invece gli aggiornamenti della repository.

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
configurato; vedi la [guida all'inferenza](https://github.com/Damel91/flower-mcp/blob/0a1dfd3043ae5cea628c3cf26107a015336794d3/docs/INFERENCE.md).
Il reader è consultabile offline, mentre una nuova installazione scarica pacchetti e dipendenze.

## Usi già Flower? Conserva il ledger

Segui il [piano di aggiornamento sicuro](https://github.com/Damel91/flower-mcp/blob/0a1dfd3043ae5cea628c3cf26107a015336794d3/docs/UPGRADING.md)
con l'ambiente, il profilo e la radice dei profili originali. Ferma tutti i processi
Flower e i coding client che condividono quell'ambiente. Per un'installazione
creata dall'installer, visualizza il piano prima di modificare i pacchetti:

```sh
curl -fsSL https://github.com/Damel91/flower-mcp/releases/download/v0.4.0/install.sh | bash -s -- --upgrade --dry-run
```

Su Windows scarica il nuovo `install.ps1` mostrato sotto, poi visualizza il piano
senza opzioni per la registrazione del client:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\install.ps1 -Version '0.4.0' -Upgrade -DryRun
```

Per percorsi personalizzati aggiungi le opzioni originali `--venv`, `--profile`
e `--profile-root`; Windows usa `-Venv`, `-Profile` e `-ProfileRoot`. Controlla il
piano, poi ripeti senza `--dry-run` / `-DryRun`. L'aggiornamento salva un backup
del ledger SQLite selezionato e dello YAML esatto prima di pip, conserva la
registrazione del client e applica le migrazioni additive da schema 52 a 55 al
successivo avvio del server. Non resetta il ledger e non ripristina automaticamente
un backup. Le installazioni pip manuali usano la procedura separata di backup
nella stessa guida. Dopo il riavvio riprendi il progetto noto; non crearne uno
sostitutivo per recuperare lo stato.

## Scegli una strada

### macOS e Linux

Dopo aver controllato i prerequisiti, il comando pubblico avvia l'installer
guidato e permette di scegliere l'agente o la sola installazione:

```sh
curl -fsSL https://github.com/Damel91/flower-mcp/releases/download/v0.4.0/install.sh | bash
```

Lo script prepara un ambiente Python isolato e verifica i checksum del backend
e del wheel. Puoi scaricare e leggere [lo script](https://github.com/Damel91/flower-mcp/releases/download/v0.4.0/install.sh)
prima di eseguirlo. Opzioni e procedure manuali sono nella guida completa.

### Windows

In una directory scrivibile, scarica il launcher pubblico e scegli il client.
Qui l'esempio usa Codex:

```powershell
Invoke-WebRequest -UseBasicParsing -Uri "https://github.com/Damel91/flower-mcp/releases/download/v0.4.0/install.ps1" -OutFile ".\install.ps1"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\install.ps1 -Version '0.4.0' -Platform codex
```

Esegui i due comandi separatamente e fermati se il download fallisce. Puoi
leggere lo script prima di avviarlo. `-Platform claude-code`, `-Platform cursor`,
`-Platform antigravity` o `-Platform gemini-cli` selezionano gli altri client;
`-NoRegister` installa senza registrarne uno.
L'opzione di execution policy vale solo per quel processo PowerShell.

Per installare manualmente, segui [la procedura con wheel e checksum](https://github.com/Damel91/flower-mcp/blob/0a1dfd3043ae5cea628c3cf26107a015336794d3/docs/INSTALLATION.md#manual-installation-from-a-release-wheel).

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
credenziali o dati personali. Flower `0.4.0` resta in fase di test. Le modalità di
installazione e l'effettiva usabilità nel coding client sono verifiche distinte.

[Torna a Require](01-require.md) · [Repository GitHub](https://github.com/Damel91/flower-mcp) · [Indice](README.md)
