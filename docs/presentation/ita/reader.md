# Lo stesso percorso, anche offline

[Indice](README.md) · [Fonti](sources.md#reader-e-attribuzioni)

## Leggere su GitHub

Il punto d'ingresso è [README.md](README.md). Tutti i capitoli usano link relativi,
titoli, tabelle, citazioni e blocchi di codice leggibili da GitHub. Il reader
non contiene una seconda versione del racconto.

## Leggere in locale

Apri [index.html](index.html) con un browser. Non servono server HTTP, Python,
Node, Flower, modello, login o connessione a Internet per il percorso.

La directory `presentation` contiene ciò che serve: le due edizioni `ita` ed
`eng`, HTML generato, script, stylesheet e logo condivisi. Copia l'intera cartella
`presentation`, non soltanto una lingua, per leggerla senza il resto del repository.
Il selettore di lingua apre lo stesso capitolo nell'altra edizione. Il reader
include anche il bootstrap pubblico, in inglese, come approfondimento. I link a
sorgenti GitHub e al README del prodotto sono fonti esterne: per consultarli
serve la rete, ma non sono caricati automaticamente.

Indice, link tra capitoli, ancore e avanti/indietro del browser funzionano nel
reader. Lo stile dei contenuti riprende GitHub Markdown; non è una replica
identica della UI GitHub. Il menu si adatta alla larghezza e il tema segue il
sistema. I font non vengono scaricati.

La verifica editoriale ha coperto Chrome su macOS, offline, a larghezze di
1440, 390 e 320 pixel, e una copia di soli HTML e asset. Non equivale a una
certificazione nativa su Windows/Linux o a una campagna del server Flower.

## Aggiornare il percorso

Modifica i Markdown nella lingua appropriata, non il contenuto di `index.html`.
Un solo builder rigenera entrambe le edizioni e l'indice bilingue. Per rigenerare servono
Python 3.11+ e la dipendenza editoriale dichiarata in `requirements-reader.txt`.
Usa un ambiente virtuale editoriale separato dal runtime di Flower. Dal root del
repository, con quell'ambiente attivo:

```sh
python -m pip install -r docs/presentation/requirements-reader.txt
python docs/presentation/build_reader.py
python docs/presentation/build_reader.py --check
python -m unittest discover -s docs/presentation/tests
```

Su macOS/Linux usa `python3` se necessario; su Windows puoi usare `py -3.11`.
I comandi usano Python e percorsi relativi, non script Bash. Nessuna dipendenza
editoriale viene aggiunta all'installazione del server.

`--check` verifica link locali, ancore e corrispondenza dell'HTML generato;
non aggiorna file. Il catalogo dei tool viene confrontato con il sorgente del
repository quando disponibile. Il documento [fonti](sources.md) conserva la
fotografia di prodotto su cui è basata questa edizione.

## Il confine del reader

È una pubblicazione da leggere, non un client MCP: non chiama Flower, non
esegue codice, non scrive il ledger e non genera evidenza di accettazione.
I Markdown rimangono la fonte; l'HTML è una loro proiezione locale.

[Indice](README.md) · [Traccia per il talk](talk.md)
