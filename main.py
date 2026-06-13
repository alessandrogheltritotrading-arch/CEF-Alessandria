from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import yfinance as yf
import pandas as pd
import numpy as np

app = FastAPI(title="CEF Terminal - Financial Backend")

# Configurazione CORS per permettere all'app Android di comunicare con il backend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Permette le chiamate da qualsiasi origine (incluso Capacitor)
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/api/gex/{ticker}")
def get_gex_data(ticker: str, scadenze: int = 3):
    try:
        # 1. Inizializzazione Ticker e recupero prezzo Spot reale
        asset = yf.Ticker(ticker)
        info = asset.info
        
        # Recupero del prezzo corrente (gestione di diversi tipi di asset)
        spot_price = info.get('regularMarketPrice') or info.get('currentPrice') or info.get('previousClose')
        
        if not spot_price:
            # Fallback se le info standard sono vuote (es. indici come ^SPX)
            history = asset.history(period="1d")
            if not history.empty:
                spot_price = history['Close'].iloc[-1]
            else:
                raise HTTPException(status_code=404, detail="Impossibile recuperare il prezzo Spot corrente.")

        # 2. Recupero delle scadenze disponibili
        all_dates = asset.options
        if not all_dates:
            raise HTTPException(status_code=404, detail=f"Nessuna opzione disponibile per il ticker {ticker}")
        
        # Selezioniamo il numero di scadenze richieste dall'utente
        target_dates = all_dates[:scadenze]
        
        aggregated_calls = pd.DataFrame()
        aggregated_puts = pd.DataFrame()

        # 3. Estrazione e aggregazione delle catene di opzioni reali
        for date in target_dates:
            opt = asset.option_chain(date)
            aggregated_calls = pd.concat([aggregated_calls, opt.calls])
            aggregated_puts = pd.concat([aggregated_puts, opt.puts])

        # Raggruppiamo per Strike per sommare l'Open Interest delle varie scadenze
        calls_grouped = aggregated_calls.groupby('strike')['openInterest'].sum().dropna()
        puts_grouped = aggregated_puts.groupby('strike')['openInterest'].sum().dropna()

        # Uniamo i dati in un unico DataFrame concentrato intorno allo Spot Price (es. +/- 15%)
        strikes_range = (calls_grouped.index >= spot_price * 0.85) & (calls_grouped.index <= spot_price * 1.15)
        valid_strikes = calls_grouped[strikes_range].index

        result_strikes = []
        call_oi_list = []
        put_oi_list = []

        max_call_oi = 0
        call_wall = 0
        max_put_oi = 0
        put_wall = 0

        for strike in valid_strikes:
            c_oi = int(calls_grouped.get(strike, 0))
            p_oi = int(puts_grouped.get(strike, 0))

            result_strikes.append(float(strike))
            call_oi_list.append(c_oi)
            put_oi_list.append(-p_oi)  # Negativo per la visualizzazione grafica speculare

            # Identificazione del Call Wall e Put Wall reali
            if c_oi > max_call_oi:
                max_call_oi = c_oi
                call_wall = strike
            if p_oi > max_put_oi:
                max_put_oi = p_oi
                put_wall = strike

        # 4. Calcolo matematico del Gamma Flip (Punto Zero empirico basato sulla distribuzione dell'OI)
        # Utilizziamo la concentrazione dei volumi d'opzione come proxy del posizionamento dei market maker
        total_call_oi = sum(call_oi_list)
        total_put_oi = abs(sum(put_oi_list))
        
        if (total_call_oi + total_put_oi) > 0:
            oi_ratio = total_call_oi / (total_call_oi + total_put_oi)
            gamma_flip = call_wall * (1 - oi_ratio) + put_wall * oi_ratio
        else:
            gamma_flip = (call_wall + put_wall) / 2

        return {
            "ticker": ticker.upper(),
            "spotPrice": float(spot_price),
            "callWall": float(call_wall),
            "putWall": float(put_wall),
            "gammaFlip": float(gamma_flip),
            "strikes": result_strikes,
            "callOI": call_oi_list,
            "putOI": put_oi_list
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    # Avvio del server sulla porta 8000
    uvicorn.run(app, host="0.0.0.0", port=8000)