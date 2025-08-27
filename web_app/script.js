// Attendiamo che tutta la pagina HTML sia caricata prima di eseguire il codice
document.addEventListener('DOMContentLoaded', () => {

  const griglia = document.querySelector('.prodotti');
  const filtroSelect = document.getElementById('filtro-tipologia');
  let tuttiIProdotti = []; // Array per memorizzare tutti i prodotti caricati dal JSON

  // Funzione per mostrare/nascondere le card dei prodotti in base al filtro selezionato
  function filtraProdotti() {
    const tipologiaSelezionata = filtroSelect.value;
    const tutteLeCard = document.querySelectorAll('.prodotto');

    tutteLeCard.forEach(card => {
      // Se è selezionato "Tutti" OPPURE la tipologia della card corrisponde a quella selezionata, la mostriamo
      if (tipologiaSelezionata === 'tutti' || card.dataset.tipologia === tipologiaSelezionata) {
        card.style.display = 'block'; // 'block' è il valore di visualizzazione di default per un div
      } else {
        // Altrimenti, la nascondiamo
        card.style.display = 'none';
      }
    });
  }

  // Funzione principale che si avvia all'apertura della pagina
  async function initVetrina() {
    try {
      // Carica i dati dal file 'products.json'
      // Utilizziamo un timestamp per bypassare la cache del browser e avere i dati sempre aggiornati
      const response = await fetch(`products.json?_t=${new Date().getTime()}`); 
      // Controlla se il file è stato trovato e caricato correttamente
      if (!response.ok) {
        throw new Error(`Errore nel caricamento del file JSON: ${response.statusText}`);
      }
      tuttiIProdotti = await response.json();

      // --- 1. Popola il menu a tendina con le tipologie ---
      // Estrae tutte le tipologie uniche dai prodotti, usando Set per eliminare i duplicati
      const tipologieUniche = [...new Set(tuttiIProdotti.map(p => p.tipologia))];
      
      // Aggiunge l'opzione "Tutti" come prima scelta
      filtroSelect.innerHTML = '<option value="tutti">Tutti</option>';

      // Per ogni tipologia unica, crea un'opzione nel menu
      tipologieUniche.forEach(tipologia => {
        const optionHTML = `<option value="${tipologia}">${tipologia}</option>`;
        filtroSelect.innerHTML += optionHTML;
      });

      // --- 2. Crea e visualizza le card di tutti i prodotti ---
      griglia.innerHTML = ''; // Svuota la griglia per sicurezza
      tuttiIProdotti.forEach(prodotto => {
        const prodottoDiv = document.createElement('div');
        prodottoDiv.classList.add('prodotto');
        prodottoDiv.dataset.tipologia = prodotto.tipologia; // Aggiunge l'attributo per il filtraggio

        // Crea il div per il media
        const mediaDiv = document.createElement('div');
        mediaDiv.classList.add('media');

        // Logica per visualizzare IMIMAGINE o VIDEO
        if (prodotto.immagine) {
            const mediaUrl = prodotto.immagine;
            const fileExtension = mediaUrl.split('.').pop().toLowerCase();
            
            if (fileExtension === 'mp4' || fileExtension === 'webm' || fileExtension === 'ogg') {
                // È un video
                const videoElement = document.createElement('video');
                videoElement.src = mediaUrl;
                videoElement.controls = true; // Mostra i controlli di riproduzione
                videoElement.muted = true; // Opzionale: muta all'inizio
                videoElement.autoplay = true; // Opzionale: avvia automaticamente
                videoElement.loop = true; // Opzionale: riproduci in loop
                mediaDiv.appendChild(videoElement);
            } else {
                // Presumiamo sia un'immagine
                const imgElement = document.createElement('img');
                imgElement.src = mediaUrl;
                imgElement.alt = prodotto.nome;
                mediaDiv.appendChild(imgElement);
            }
        } else {
            // Se non c'è immagine, mostra un placeholder o lascia vuoto
            mediaDiv.innerHTML = '<p style="color: #ccc;">Nessun media</p>';
        }

        prodottoDiv.appendChild(mediaDiv); // Aggiunge il media al div del prodotto

        // Aggiunge gli altri dettagli del prodotto
        const titoloDiv = document.createElement('div');
        titoloDiv.classList.add('titolo');
        titoloDiv.textContent = prodotto.nome;
        prodottoDiv.appendChild(titoloDiv);

        const prezzoDiv = document.createElement('div');
        prezzoDiv.classList.add('prezzo');
        prezzoDiv.textContent = `€${prodotto.prezzo}`;
        prodottoDiv.appendChild(prezzoDiv);

        griglia.appendChild(prodottoDiv); // Aggiunge la card completa alla griglia
      });

      // --- 3. Collega la funzione 'filtraProdotti' all'evento 'change' del menu ---
      // Ogni volta che l'utente cambia la selezione, la funzione verrà eseguita
      filtroSelect.addEventListener('change', filtraProdotti);

    } catch (error) {
      // Se c'è un errore (es. file JSON non trovato o malformato), lo mostra nella console
      console.error("Impossibile inizializzare la vetrina:", error);
      griglia.innerHTML = `<p style="text-align: center; grid-column: 1 / -1; color: red;">Errore nel caricamento dei prodotti. Controlla la console per i dettagli.</p>`;
    }
  }

  // Avvia la funzione principale per inizializzare la vetrina
  initVetrina();
});