# Ora prova Flower MCP

[Precedente: Operate](06-operate.md) · [Indice](README.md)

Abbiamo seguito Spazio Comune dal requisito al cambiamento. L'ultimo passo è
portare questo metodo nel tuo progetto: **installare Flower e collegarlo al tuo
coding agent**. Spazio Comune resta uno scenario didattico; il download è il
server Flower MCP, nome pubblico di Flow of Work MCP.

## Repository e download pubblici

- [Repository GitHub](https://github.com/Damel91/flower-mcp): codice, README e documentazione corrente.
- [Release Flower MCP 0.1.1](https://github.com/Damel91/flower-mcp/releases/tag/v0.1.1): pacchetti e note della versione.
- [Guida di installazione della revisione documentata](https://github.com/Damel91/flower-mcp/blob/d832b5e53ab3f1082f9143ae15abc70543f264b6/docs/INSTALLATION.md): procedure complete, configurazione e rimozione.
- [Prerequisiti per sistema operativo](https://github.com/Damel91/flower-mcp/blob/d832b5e53ab3f1082f9143ae15abc70543f264b6/docs/INSTALLATION.md#prerequisites): cosa preparare prima del download.

| File | A cosa serve |
| --- | --- |
| [install.sh](https://github.com/Damel91/flower-mcp/releases/download/v0.1.1/install.sh) | Installazione guidata su macOS e Linux. |
| [install.ps1](https://github.com/Damel91/flower-mcp/releases/download/v0.1.1/install.ps1) | Launcher PowerShell per Windows della stessa release. |
| [install_flower.py](https://github.com/Damel91/flower-mcp/releases/download/v0.1.1/install_flower.py) | Installer Python della release; richiede Python 3.11+. |
| [Pacchetto wheel](https://github.com/Damel91/flower-mcp/releases/download/v0.1.1/flow_of_work_mcp-0.1.1-py3-none-any.whl) | Installazione manuale del pacchetto Python. |
| [Archivio sorgente](https://github.com/Damel91/flower-mcp/releases/download/v0.1.1/flow_of_work_mcp-0.1.1.tar.gz) | Sorgente confezionato della release. |
| [SHA256SUMS](https://github.com/Damel91/flower-mcp/releases/download/v0.1.1/SHA256SUMS) | Checksum per verificare i file della release. |
| [BOOTSTRAP.md](https://github.com/Damel91/flower-mcp/releases/download/v0.1.1/BOOTSTRAP.md) | Istruzioni pubbliche per avviare il lavoro dell'agente con Flower. |

La release `v0.1.1` contiene sette asset, incluso `install.ps1`.
Il launcher Windows installa il wheel `0.1.1`.
Il nome della distribuzione Python resta `flow-of-work-mcp`; il comando è
`flower-mcp`. I link di download sono fissati a questa versione, non al sorgente
variabile su `main`. La guida è fissata alla revisione descritta nella
presentazione; il README corrente segue invece gli aggiornamenti della repository.

## Prima di installare

| Percorso | Prerequisiti essenziali |
| --- | --- |
| macOS / Linux, installer Bash | Bash, curl, awk, sha256sum o shasum, utility shell, accesso HTTPS e Internet. Python adatto viene riutilizzato o preparato dall'installer. |
| Windows, launcher PowerShell | Windows PowerShell 5.1+, accesso HTTPS e Internet. Python adatto viene riutilizzato o preparato dal launcher. |
| Installazione manuale o installer Python | Python 3.11+ con ssl, venv ed ensurepip; accesso alle dipendenze. Git serve solo per clonare il sorgente. |
| Collegamento all'agente | Codex, Claude Code oppure Cursor già installato; directory utente scrivibile. |

**Il core non richiede LM Studio, un modello interno, CodingCastle o una VPN.**
L'inferenza rimane quella del coding agent scelto. Il reader è consultabile
offline, mentre una nuova installazione scarica pacchetti e dipendenze.

## Scegli una strada

### macOS e Linux

Dopo aver controllato i prerequisiti, il comando pubblico avvia l'installer
guidato e permette di scegliere l'agente o la sola installazione:

```sh
curl -fsSL https://github.com/Damel91/flower-mcp/releases/download/v0.1.1/install.sh | bash
```

Lo script prepara un ambiente Python isolato e verifica i checksum del backend
e del wheel. Puoi scaricare e leggere [lo script](https://github.com/Damel91/flower-mcp/releases/download/v0.1.1/install.sh)
prima di eseguirlo. Opzioni e procedure manuali sono nella guida completa.

### Windows

In una directory scrivibile, scarica il launcher pubblico e scegli il client.
Qui l'esempio usa Codex:

```powershell
Invoke-WebRequest -UseBasicParsing -Uri "https://github.com/Damel91/flower-mcp/releases/download/v0.1.1/install.ps1" -OutFile ".\install.ps1"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\install.ps1 -Platform codex
```

Esegui i due comandi separatamente e fermati se il download fallisce. Puoi
leggere lo script prima di avviarlo. `-Platform claude-code` o `-Platform cursor`
selezionano gli altri client; `-NoRegister` installa senza registrarne uno.
L'opzione di execution policy vale solo per quel processo PowerShell.

Per installare manualmente, segui [la procedura con wheel e checksum](https://github.com/Damel91/flower-mcp/blob/d832b5e53ab3f1082f9143ae15abc70543f264b6/docs/INSTALLATION.md#manual-installation-from-a-release-wheel).

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
credenziali o dati personali. Flower `0.1.1` è una prima versione in fase di test.

[Torna a Require](01-require.md) · [Repository GitHub](https://github.com/Damel91/flower-mcp) · [Indice](README.md)
