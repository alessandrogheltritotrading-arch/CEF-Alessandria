from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import yfinance as yf
import pandas as pd
import numpy as np
import requests

app = FastAPI(title="CEF Alessandria - GEX Engine PRO")

# Configurazione CORS obbligatoria per permettere all'app Android di connettersi al cloud
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def home():
    return {"status": "online", "message": "CEF Alessandria GEX Engine operativo"}

@app.get("/api/gex/{ticker}")
async def calcola_gex(ticker: str, scadenze: int = 3):
    try:
        ticker = ticker.upper()
        
        # MASCHERAMENTO RICHIESTA: Creiamo una sessione HTTP che simula un browser reale
        # Questo aggira il filtro anti-bot ("Too Many Requests") sui server cloud
        session = requests.Session()
        session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        })
        
        # Inizializziamo il ticker associando la sessione camuffata
        tk = yf.Ticker(ticker, session=session)
        
        # Recupero del prezzo Spot corrente
        info = tk.fast_info
        spot_price = info.get('last_price', None)
        
        if spot_price is None:
            hist = tk.history(period="1d")
            if not hist.empty:
                spot_price = hist['Close'].iloc[-1]
            else:
                raise HTTPException(status_code=404, detail=f"Impossibile recuperare il prezzo spot per {ticker}")
        
        # Recupero delle scadenze disponibili
        disponibili_scadenze = tk.options
        if not disponibili_scadenze:
            raise HTTPException(status_code=404, detail=f"Nessuna opzione disponibile per il ticker {ticker}")
        
        # Selezioniamo il numero di scadenze richiesto dall'utente
        scadenze_da_aggregare = disponibili_scadenze[:min(scadenze, len(disponibili_scadenze))]
        
        all_calls = []
        all_puts = []
        
        # Estrazione e aggregazione dei dati di Open Interest
        for scadenza in scadenze_da_aggregare:
            catena = tk.option_chain(scadenza)
            all_calls.append(catena.calls[['strike', 'openInterest']])
            all_puts.append(catena.puts[['strike', 'openInterest']])
            
        df_calls = pd.concat(all_calls).groupby('strike')['openInterest'].sum().fillna(0)
        df_puts = pd.concat(all_puts).groupby('strike')['openInterest'].sum().fillna(0)
        
        # Definizione dei livelli volumetrici chiave
        call_wall = float(df_calls.idxmax()) if not df_calls.empty else spot_price
        put_wall = float(df_puts.idxmax()) if not df_puts.empty else spot_price
        
        # Calcolo matematico del Gamma Flip empirico basato sullo sbilanciamento dell'Open Interest
        # Identifica l'area monetaria in cui le forze di copertura (hedging) cambiano regime
        unione_strikes = sorted(list(set(df_calls.index).union(set(df_puts.index))))
        gamma_flip = spot_price # Valore di fallback
        
        min_differenza = float('inf')
        for strike in unione_strikes:
            if abs(strike - spot_price) / spot_price <= 0.05: # Analizziamo l'area ATM (At-The-Money)
                c_oi = df_calls.get(strike, 0)
                p_oi = df_puts.get(strike, 0)
                diff = abs(c_oi - p_oi)
                if diff < min_differenza:
                    min_differenza = diff
                    gamma_flip = float(strike)
        
        # Filtro degli strike attorno allo spot (+/- 12%) per una visualizzazione pulita del grafico Chart.js
        strikes_filtrati = [s for s in unione_strikes if spot_price * 0.88 <= s <= spot_price * 1.12]
        
        call_oi_list = [float(df_calls.get(s, 0)) for s in strikes_filtrati]
        put_oi_list = [float(df_puts.get(s, 0)) for s in strikes_filtrati]
        
        # Payload finale strutturato esattamente come richiesto dall'interfaccia dell'App
        return {
            "ticker": ticker,
            "spotPrice": float(spot_price),
            "callWall": float(call_wall),
            "putWall": float(put_wall),
            "gammaFlip": float(gamma_flip),
            "strikes": [float(s) for s in strikes_filtrati],
            "callOI": call_oi_list,
            "putOI": put_oi_list
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
