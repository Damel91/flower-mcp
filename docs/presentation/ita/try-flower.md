# Ora prova Flower MCP

[Precedente: Operate](06-operate.md) · [Indice](README.md)

Abbiamo seguito Spazio Comune dal requisito al cambiamento. L'ultimo passo è
portare questo metodo nel tuo progetto: **installare Flower e collegarlo al tuo
coding agent**. Spazio Comune resta uno scenario didattico; il download è il
server Flower MCP, nome pubblico di Flow of Work MCP.

## Repository e download pubblici

- [Repository GitHub](https://github.com/Damel91/flower-mcp): codice, README e documentazione corrente.
- [Release pubblicata Flower MCP 0.4.1](https://github.com/Damel91/flower-mcp/releases/tag/v0.4.1): pacchetti storici immutabili e note della versione.
- [Guida di installazione al checkpoint sorgente](https://github.com/Damel91/flower-mcp/blob/51d1a86e5304c6ef71335dd130c193c84a35f80f/docs/INSTALLATION.md): procedure complete, configurazione e rimozione.
- [Prerequisiti per sistema operativo](https://github.com/Damel91/flower-mcp/blob/51d1a86e5304c6ef71335dd130c193c84a35f80f/docs/INSTALLATION.md#prerequisites): cosa preparare prima del download.

| File | A cosa serve |
| --- | --- |
| [install.sh](https://github.com/Damel91/flower-mcp/releases/download/v0.4.1/install.sh) | Installazione guidata su macOS e Linux. |
| [install.ps1](https://github.com/Damel91/flower-mcp/releases/download/v0.4.1/install.ps1) | Launcher PowerShell per Windows della stessa release. |
| [install_flower.py](https://github.com/Damel91/flower-mcp/releases/download/v0.4.1/install_flower.py) | Installer Python della release; richiede Python 3.11+. |
| [Pacchetto wheel](https://github.com/Damel91/flower-mcp/releases/download/v0.4.1/flow_of_work_mcp-0.4.1-py3-none-any.whl) | Installazione manuale del pacchetto Python. |
| [Archivio sorgente](https://github.com/Damel91/flower-mcp/releases/download/v0.4.1/flow_of_work_mcp-0.4.1.tar.gz) | Sorgente confezionato della release. |
| [SHA256SUMS](https://github.com/Damel91/flower-mcp/releases/download/v0.4.1/SHA256SUMS) | Checksum per verificare i file della release. |
| [BOOTSTRAP.md](https://github.com/Damel91/flower-mcp/releases/download/v0.4.1/BOOTSTRAP.md) | Istruzioni pubbliche per avviare il lavoro dell'agente con Flower. |
| [Wheel runtime opzionale storico](https://github.com/Damel91/flower-mcp/releases/download/v0.4.1/runtime_llama-0.4.0-py3-none-any.whl) | Runtime `0.4.0` conservato nella release pubblicata immutabile; l'installazione core lo esclude. |

L'inventario della release pubblicata `v0.4.1` comprende otto asset storici,
inclusi `install.ps1` e il wheel opzionale runtime-llama `0.4.0`. L'extra del suo
wheel Flower richiede ancora quel runtime precedente. Verifica questi download
rispetto allo `SHA256SUMS` pubblicato.
Il launcher Windows installa il wheel `0.4.1`.
Il nome della distribuzione Python resta `flow-of-work-mcp`; il comando è
`flower-mcp`. I download sono fissati alla release storica e la guida di
installazione al checkpoint sorgente corrente documentato. Esegui i comandi solo quando i corrispondenti asset sono pubblicati.
Il README corrente segue invece gli aggiornamenti della repository.

## Sorgente corrente e runtime opzionale

Il sorgente corrente mantiene la versione Flower `0.4.1` come **candidato non
pubblicato**. Le sue build contengono sette asset Flower: wheel, archivio sorgente,
tre installer, `BOOTSTRAP.md` e `SHA256SUMS`. Non copiano più un wheel runtime.
Questo non sostituisce né rinomina gli otto asset Flower pubblicati sopra.

L'extra `inference` del sorgente/candidato corrente seleziona la
[release llama-runtime `0.4.1`](https://github.com/Damel91/llama-runtime/releases/tag/v0.4.1)
pubblicata indipendentemente e il suo [wheel upstream](https://github.com/Damel91/llama-runtime/releases/download/v0.4.1/runtime_llama-0.4.1-py3-none-any.whl).
Il suo SHA256 è
`8c512eb79b00ac3fdf761036fa0c8d74c24c3581651332736f6a95e6e38ae0aa`.
Il wheel upstream include `LICENSE`/`NOTICE` Apache-2.0 e l'attribuzione MIT
di llamatelemetry incorporato.

Dal sorgente corrente selezionato, usa l'ambiente dedicato di Flower:

```sh
.venv/bin/python -m pip install '.[inference]'
.venv/bin/python -m pip check
```

Per un wheel candidato corrente verificato, usa invece
`'./dist/flow_of_work_mcp-0.4.1-py3-none-any.whl[inference]'`.
Windows usa `& .\.venv\Scripts\python.exe` con gli stessi argomenti pip.
La dipendenza fissa URL e SHA256 upstream. Non usare il vecchio extra del wheel
Flower pubblicato per questo nuovo runtime. Consulta la
[guida all'inferenza](https://github.com/Damel91/flower-mcp/blob/51d1a86e5304c6ef71335dd130c193c84a35f80f/docs/INFERENCE.md)
per il percorso completo da sorgente/wheel, la verifica indipendente del checksum
e l'acquisizione del wheelhouse offline. Conserva commit sorgente e inventario
checksum del candidato: nome del file e versione coincidono con il wheel Flower
storico. Gli installer core restano core-only e non configurano provider impliciti.

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
configurato; vedi la [guida all'inferenza](https://github.com/Damel91/flower-mcp/blob/51d1a86e5304c6ef71335dd130c193c84a35f80f/docs/INFERENCE.md).
Il reader è consultabile offline, mentre una nuova installazione scarica pacchetti e dipendenze.

## Usi già Flower? Conserva il ledger

Segui il [piano di aggiornamento sicuro](https://github.com/Damel91/flower-mcp/blob/51d1a86e5304c6ef71335dd130c193c84a35f80f/docs/UPGRADING.md)
con l'ambiente, il profilo e la radice dei profili originali. Ferma tutti i processi
Flower e i coding client che condividono quell'ambiente. Per un'installazione
creata dall'installer, visualizza il piano prima di modificare i pacchetti:

```sh
curl -fsSL https://github.com/Damel91/flower-mcp/releases/download/v0.4.1/install.sh | bash -s -- --upgrade --dry-run
```

Su Windows scarica il nuovo `install.ps1` mostrato sotto, poi visualizza il piano
senza opzioni per la registrazione del client:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\install.ps1 -Version '0.4.1' -Upgrade -DryRun
```

Per percorsi personalizzati aggiungi le opzioni originali `--venv`, `--profile`
e `--profile-root`; Windows usa `-Venv`, `-Profile` e `-ProfileRoot`. Controlla il
piano, poi ripeti senza `--dry-run` / `-DryRun`. L'aggiornamento salva un backup
del ledger SQLite selezionato e dello YAML esatto prima di pip, conserva la
registrazione del client e non aggiunge migrazioni da 0.4.0 a 0.4.1: lo schema
resta 55. Un'installazione più vecchia 0.3.1/schema52 usa ancora le migrazioni
additive esistenti da 52 a 55 al successivo avvio del server. Conserva i percorsi
dei backup restituiti. L'aggiornamento non resetta il ledger e non ripristina
automaticamente un backup; un errore di pip può modificare parzialmente l'ambiente.
Le installazioni pip manuali usano la procedura separata di backup
nella stessa guida. Dopo il riavvio riprendi il progetto noto; non crearne uno
sostitutivo per recuperare lo stato.

Questo aggiornamento di core/profilo non richiede l'extra inference e non cambia
le impostazioni del modello. Aggiornare il runtime opzionale è un'operazione
esplicita separata dal sorgente/candidato corrente selezionato; segui la guida
all'inferenza prima di sostituire pacchetti Flower della stessa versione.
Conserva endpoint e profilo originali.

## Scegli una strada

### macOS e Linux

Dopo aver controllato i prerequisiti, il comando pubblico avvia l'installer
guidato e permette di scegliere l'agente o la sola installazione:

```sh
curl -fsSL https://github.com/Damel91/flower-mcp/releases/download/v0.4.1/install.sh | bash
```

Lo script prepara un ambiente Python isolato e verifica i checksum del backend
e del wheel. Puoi scaricare e leggere [lo script](https://github.com/Damel91/flower-mcp/releases/download/v0.4.1/install.sh)
prima di eseguirlo. Opzioni e procedure manuali sono nella guida completa.

### Windows

In una directory scrivibile, scarica il launcher pubblico e scegli il client.
Qui l'esempio usa Codex:

```powershell
Invoke-WebRequest -UseBasicParsing -Uri "https://github.com/Damel91/flower-mcp/releases/download/v0.4.1/install.ps1" -OutFile ".\install.ps1"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\install.ps1 -Version '0.4.1' -Platform codex
```

Esegui i due comandi separatamente e fermati se il download fallisce. Puoi
leggere lo script prima di avviarlo. `-Platform claude-code`, `-Platform cursor`,
`-Platform antigravity` o `-Platform gemini-cli` selezionano gli altri client;
`-NoRegister` installa senza registrarne uno.
L'opzione di execution policy vale solo per quel processo PowerShell.

Per installare manualmente, segui [la procedura con wheel e checksum](https://github.com/Damel91/flower-mcp/blob/51d1a86e5304c6ef71335dd130c193c84a35f80f/docs/INSTALLATION.md#manual-installation-from-a-release-wheel).

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
credenziali o dati personali. Flower `0.4.1` resta in fase di test. Le modalità di
installazione e l'effettiva usabilità nel coding client sono verifiche distinte.

[Torna a Require](01-require.md) · [Repository GitHub](https://github.com/Damel91/flower-mcp) · [Indice](README.md)
