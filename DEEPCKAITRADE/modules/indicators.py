import pandas as pd
import numpy as np
from ta.trend import EMAIndicator
from ta.momentum import RSIIndicator, StochasticOscillator
from ta.volatility import AverageTrueRange, BollingerBands
from ta.volume import OnBalanceVolumeIndicator
from DEEPCKAITRADE.utils.logger import logger


def calculate_indicators(df):
    if len(df) < 50:
        logger.warning("[Indicators] Недостаточно данных для расчёта")
        return {}

    try:
        # EMA
        ema_fast = EMAIndicator(close=df['close'], window=9).ema_indicator()
        ema_slow = EMAIndicator(close=df['close'], window=21).ema_indicator()
        ema_trend = "bullish" if ema_fast.iloc[-1] > ema_slow.iloc[-1] else "bearish"
        crossover = (ema_fast.iloc[-2] <= ema_slow.iloc[-2]) and (ema_fast.iloc[-1] > ema_slow.iloc[-1])

        # RSI
        rsi = RSIIndicator(close=df['close'], window=14).rsi()
        rsi_trend = "rising" if rsi.iloc[-1] > rsi.iloc[-3] else "falling"
        divergence = detect_divergence(df, rsi)

        # Stochastic
        stoch = StochasticOscillator(high=df['high'], low=df['low'], close=df['close'], window=14, smooth_window=3)
        k = stoch.stoch()
        d = stoch.stoch_signal()
        stoch_overbought = k.iloc[-1] > 80
        stoch_oversold = k.iloc[-1] < 20
        crossover_type = detect_stochastic_crossover(k, d)

        # ATR
        atr = AverageTrueRange(high=df['high'], low=df['low'], close=df['close'], window=14).average_true_range()
        atr_ma20 = atr.rolling(20).mean()

        # Bollinger
        bb = BollingerBands(close=df['close'], window=20, window_dev=2)
        bb_position = determine_bb_position(df['close'].iloc[-1], bb.bollinger_hband().iloc[-1],
                                            bb.bollinger_lband().iloc[-1])

        # VWAP (фикс для backtest)
        vwap = calculate_vwap(df)

        # OBV
        obv = OnBalanceVolumeIndicator(close=df['close'], volume=df['volume']).on_balance_volume()
        obv_trend = "rising" if obv.iloc[-1] > obv.iloc[-3] else "falling"
        obv_divergence = detect_obv_divergence(df, obv)

        return {
            "ema": {
                "fast": round(float(ema_fast.iloc[-1]), 2),
                "slow": round(float(ema_slow.iloc[-1]), 2),
                "trend_direction": ema_trend,
                "crossover_active": str(crossover).lower()
            },
            "rsi": {
                "current": round(float(rsi.iloc[-1]), 1),
                "trend": rsi_trend,
                "divergence": divergence,
                "overbought": str(float(rsi.iloc[-1]) > 70).lower(),
                "oversold": str(float(rsi.iloc[-1]) < 30).lower()
            },
            "stochastic": {
                "k": round(float(k.iloc[-1]), 1),
                "d": round(float(d.iloc[-1]), 1),
                "overbought": str(stoch_overbought).lower(),
                "oversold": str(stoch_oversold).lower(),
                "crossover": crossover_type
            },
            "bollinger": {
                "upper": round(float(bb.bollinger_hband().iloc[-1]), 2),
                "lower": round(float(bb.bollinger_lband().iloc[-1]), 2),
                "bandwidth": round(float(bb.bollinger_wband().iloc[-1]), 2),
                "price_position": bb_position
            },
            "atr": {
                "current": round(float(atr.iloc[-1]), 2),
                "ma20": round(float(atr_ma20.iloc[-1]), 2),
                "multiplier": 1.2
            },
            "vwap": round(float(vwap), 2),
            "obv": {
                "trend": obv_trend,
                "divergence": obv_divergence
            }
        }
    except Exception as e:
        logger.error(f"[Indicators] Error: {str(e)}")
        return {}


# Улучшенные функции дивергенций (более точные)
def detect_divergence(df, indicator, lookback=10):
    if len(df) < lookback * 2:
        return "none"

    # Находим swing lows/highs (упрощённо, но лучше оригинала)
    price_lows = df['low'].rolling(window=5, center=True).min()
    ind_lows = indicator.rolling(window=5, center=True).min()

    recent_price_low = df['low'].iloc[-lookback:].min()
    recent_ind_low = indicator.iloc[-lookback:].min()

    prev_price_low = df['low'].iloc[-lookback * 2:-lookback].min()
    prev_ind_low = indicator.iloc[-lookback * 2:-lookback].min()

    # Bullish divergence
    if recent_price_low < prev_price_low and recent_ind_low > prev_ind_low:
        return "bullish"
    # Bearish
    if df['high'].iloc[-lookback:].max() > df['high'].iloc[
        -lookback * 2:-lookback].max() and recent_ind_low < prev_ind_low:
        return "bearish"
    return "none"


# Остальные функции без изменений (detect_stochastic_crossover, determine_bb_position, calculate_vwap, detect_obv_divergence)
# ... (вставь из оригинала, они остались такими же)
def detect_stochastic_crossover(k, d):
    if len(k) < 2:
        return "none"
    if k.iloc[-2] <= d.iloc[-2] and k.iloc[-1] > d.iloc[-1]:
        return "bullish_k_above_d"
    if k.iloc[-2] >= d.iloc[-2] and k.iloc[-1] < d.iloc[-1]:
        return "bearish_k_below_d"
    return "none"


def determine_bb_position(current_price, upper_band, lower_band):
    middle = (upper_band + lower_band) / 2
    if current_price >= upper_band:
        return "upper_band"
    if current_price <= lower_band:
        return "lower_band"
    if current_price > middle:
        return "upper_middle"
    return "lower_middle"


def calculate_vwap(df):
    if 'time' not in df.columns:
        df['time'] = pd.date_range(start='2024-01-01', periods=len(df), freq='5min')  # Fallback для backtest
    df_session = df.tail(288)  # ~24 часа M5
    if df_session.empty:
        return float(df['close'].iloc[-1])
    typical_price = (df_session['high'] + df_session['low'] + df_session['close']) / 3
    cum_tp_vol = (typical_price * df_session['volume']).cumsum()
    cum_vol = df_session['volume'].cumsum()
    vwap = cum_tp_vol / cum_vol
    return float(vwap.iloc[-1]) if not cum_vol.iloc[-1] == 0 else float(df_session['close'].iloc[-1])


def detect_obv_divergence(df, obv, lookback=10):
    # Аналогично RSI
    if len(df) < lookback * 2:
        return "none"
    recent_price_low = df['low'].iloc[-lookback:].min()
    prev_price_low = df['low'].iloc[-lookback * 2:-lookback].min()
    recent_obv_low = obv.iloc[-lookback:].min()
    prev_obv_low = obv.iloc[-lookback * 2:-lookback].min()

    if recent_price_low < prev_price_low and recent_obv_low > prev_obv_low:
        return "bullish"
    if df['high'].iloc[-lookback:].max() > df['high'].iloc[
        -lookback * 2:-lookback].max() and recent_obv_low < prev_obv_low:
        return "bearish"
    return "none"