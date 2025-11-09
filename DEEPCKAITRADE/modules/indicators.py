import pandas as pd
import numpy as np
from ta.trend import EMAIndicator, MACD
from ta.momentum import RSIIndicator, StochasticOscillator
from ta.volatility import AverageTrueRange, BollingerBands
from ta.volume import OnBalanceVolumeIndicator

def calculate_indicators(df):
    """Рассчитывает все индикаторы из промпта с предобработкой"""
    # 1. EMA (быстрая 9, медленная 21)
    ema_fast = EMAIndicator(close=df['close'], window=9).ema_indicator()
    ema_slow = EMAIndicator(close=df['close'], window=21).ema_indicator()
    ema_trend = "bullish" if ema_fast.iloc[-1] > ema_slow.iloc[-1] else "bearish"
    crossover = (ema_fast.iloc[-2] <= ema_slow.iloc[-2]) and (ema_fast.iloc[-1] > ema_slow.iloc[-1])
    
    # 2. RSI (14 периодов) с дивергенцией
    rsi = RSIIndicator(close=df['close'], window=14).rsi()
    rsi_trend = "rising" if rsi.iloc[-1] > rsi.iloc[-3] else "falling"
    divergence = detect_divergence(df, rsi)
    
    # 3. Стохастик (14,3,3)
    stochastic = StochasticOscillator(
        high=df['high'], 
        low=df['low'], 
        close=df['close'],
        window=14,
        smooth_window=3
    )
    k = stochastic.stoch()
    d = stochastic.stoch_signal()
    stoch_overbought = k.iloc[-1] > 80
    stoch_oversold = k.iloc[-1] < 20
    crossover_type = detect_stochastic_crossover(k, d)
    
    # 4. ATR (14 периодов) с MA20
    atr = AverageTrueRange(high=df['high'], low=df['low'], close=df['close'], window=14).average_true_range()
    atr_ma20 = atr.rolling(20).mean()
    
    # 5. Bollinger Bands (20,2)
    bb = BollingerBands(close=df['close'], window=20, window_dev=2)
    bb_position = determine_bb_position(df['close'].iloc[-1], bb.bollinger_hband().iloc[-1], bb.bollinger_lband().iloc[-1])
    
    # 6. VWAP (накопительный за день) — ✅ Исправлено
    vwap = calculate_vwap(df)
    
    # 7. OBV с дивергенцией
    obv = OnBalanceVolumeIndicator(close=df['close'], volume=df['volume']).on_balance_volume()
    obv_trend = "rising" if obv.iloc[-1] > obv.iloc[-3] else "falling"
    obv_divergence = detect_obv_divergence(df, obv)
    
    return {
        "ema": {
            "fast": round(ema_fast.iloc[-1], 2),
            "slow": round(ema_slow.iloc[-1], 2),
            "trend_direction": ema_trend,
            "crossover_active": str(crossover).lower()
        },
        "rsi": {
            "current": round(rsi.iloc[-1], 1),
            "trend": rsi_trend,
            "divergence": divergence,
            "overbought": str(rsi.iloc[-1] > 70).lower(),
            "oversold": str(rsi.iloc[-1] < 30).lower()
        },
        "stochastic": {
            "k": round(k.iloc[-1], 1),
            "d": round(d.iloc[-1], 1),
            "overbought": str(stoch_overbought).lower(),
            "oversold": str(stoch_oversold).lower(),
            "crossover": crossover_type
        },
        "bollinger": {
            "upper": round(bb.bollinger_hband().iloc[-1], 2),
            "lower": round(bb.bollinger_lband().iloc[-1], 2),
            "bandwidth": round(bb.bollinger_wband().iloc[-1], 2),
            "price_position": bb_position
        },
        "atr": {
            "current": round(atr.iloc[-1], 2),
            "ma20": round(atr_ma20.iloc[-1], 2),
            "multiplier": 1.2
        },
        "vwap": round(vwap, 2),
        "obv": {
            "trend": obv_trend,
            "divergence": obv_divergence
        }
    }

# ✅ РЕАЛИЗОВАНЫ НЕДОСТАЮЩИЕ ФУНКЦИИ:

def detect_divergence(prices, indicator, lookback=10):
    """
    Обнаруживает дивергенцию между ценой и индикатором
    - Bullish divergence: цена делает новый минимум, индикатор — нет
    - Bearish divergence: цена делает новый максимум, индикатор — нет
    """
    # Находим локальные экстремумы
    price_highs = prices['high'].rolling(window=5, center=True).max()
    price_lows = prices['low'].rolling(window=5, center=True).min()
    
    # Находим экстремумы индикатора
    indicator_peaks = indicator.rolling(window=5, center=True).max()
    indicator_valleys = indicator.rolling(window=5, center=True).min()
    
    # Проверяем последние экстремумы
    last_price_high = prices['high'].iloc[-1]
    last_price_low = prices['low'].iloc[-1]
    last_indicator_value = indicator.iloc[-1]
    
    # Бычья дивергенция (цена ниже, индикатор выше)
    if (last_price_low < prices['low'].iloc[-5:-1].min() and 
        last_indicator_value > indicator.iloc[-5:-1].max()):
        return "bullish"
    
    # Медвежья дивергенция (цена выше, индикатор ниже)
    if (last_price_high > prices['high'].iloc[-5:-1].max() and 
        last_indicator_value < indicator.iloc[-5:-1].min()):
        return "bearish"
    
    return "none"

def detect_stochastic_crossover(k, d):
    """Определяет тип кроссовера K и D линий"""
    if len(k) < 2 or len(d) < 2:
        return "none"
    
    # K пересекает D снизу вверх (бычий сигнал)
    if k.iloc[-2] <= d.iloc[-2] and k.iloc[-1] > d.iloc[-1]:
        return "bullish_k_above_d"
    
    # K пересекает D сверху вниз (медвежий сигнал)
    if k.iloc[-2] >= d.iloc[-2] and k.iloc[-1] < d.iloc[-1]:
        return "bearish_k_below_d"
    
    return "none"

def determine_bb_position(current_price, upper_band, lower_band):
    """Определяет позицию цены относительно полос Боллинджера"""
    middle_band = (upper_band + lower_band) / 2
    
    if current_price >= upper_band:
        return "upper_band"
    elif current_price <= lower_band:
        return "lower_band"
    elif current_price > middle_band:
        return "upper_middle"
    else:
        return "lower_middle"

def calculate_vwap(df):
    """
    Расчёт VWAP за текущую сессию (для M5 - за последние 24 часа)
    ✅ Исправлено: проверяет наличие колонки 'time' перед использованием
    """
    # Проверяем, есть ли колонка 'time' (нужна только в live-режиме)
    if 'time' in df.columns:
        # Фильтруем данные за последний торговый день
        df_session = df[df['time'] >= df['time'].max() - pd.Timedelta(hours=24)]
    else:
        # Если 'time' нет (например, в бэктесте), используем последние 100 свечей
        df_session = df.tail(100) if len(df) > 100 else df
    
    if df_session.empty:
        return df['close'].iloc[-1]  # Возвращаем цену, если данных нет
    
    typical_price = (df_session['high'] + df_session['low'] + df_session['close']) / 3
    cumulative_tp_volume = (typical_price * df_session['volume']).cumsum()
    cumulative_volume = df_session['volume'].cumsum()
    
    # Избегаем деления на 0
    vwap = np.where(cumulative_volume != 0, cumulative_tp_volume / cumulative_volume, df_session['close'])
    return float(vwap[-1])

def detect_obv_divergence(prices, obv, lookback=10):
    """
    Обнаруживает дивергенцию между ценой и OBV
    """
    # Аналогично RSI - проверяем экстремумы
    price_highs = prices['high'].rolling(window=5, center=True).max()
    price_lows = prices['low'].rolling(window=5, center=True).min()
    
    obv_peaks = obv.rolling(window=5, center=True).max()
    obv_valleys = obv.rolling(window=5, center=True).min()
    
    last_price_high = prices['high'].iloc[-1]
    last_price_low = prices['low'].iloc[-1]
    last_obv_value = obv.iloc[-1]
    
    # Бычья дивергенция
    if (last_price_low < prices['low'].iloc[-5:-1].min() and 
        last_obv_value > obv.iloc[-5:-1].max()):
        return "bullish"
    
    # Медвежья дивергенция
    if (last_price_high > prices['high'].iloc[-5:-1].max() and 
        last_obv_value < obv.iloc[-5:-1].min()):
        return "bearish"
    
    return "none"