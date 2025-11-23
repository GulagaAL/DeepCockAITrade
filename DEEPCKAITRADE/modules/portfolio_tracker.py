from tinkoff.invest import Client
from DEEPCKAITRADE.config import Config
from DEEPCKAITRADE.utils.logger import logger


def get_current_positions(client, account_id, instrument_figi):
    """Возвращает позиции в формате {figi: {data}}"""
    config = Config()
    symbol_key = config.INSTRUMENT_FIGI  # Используем FIGI как ключ
    try:
        portfolio = client.operations.get_portfolio(account_id=account_id)

        # Получаем текущую цену
        current_price_resp = client.market_data.get_last_prices(figi=[instrument_figi])
        if not current_price_resp.last_prices:
            raise ValueError("No current price")
        current_price = cast_money(current_price_resp.last_prices[0].price)

        # Рассчитываем текущий equity (сумма всех позиций + cash)
        total_equity = 0.0
        for pos in portfolio.positions:
            if pos.figi and pos.quantity.units != 0:
                pos_price_resp = client.market_data.get_last_prices(figi=[pos.figi])
                if pos_price_resp.last_prices:
                    pos_price = cast_money(pos_price_resp.last_prices[0].price)
                    pos_qty = pos.quantity.units + pos.quantity.nano / 1e9
                    total_equity += pos_price * abs(pos_qty)
        # Добавляем cash (упрощённо, первый money)
        if portfolio.money:
            total_equity += portfolio.money[0].units + portfolio.money[0].nano / 1e9

        # Ищем позицию
        for position in portfolio.positions:
            if position.figi == instrument_figi and (position.quantity.units != 0 or position.quantity.nano != 0):
                qty = position.quantity.units + position.quantity.nano / 1e9
                avg_price = cast_money(position.average_position_price)
                position_value = abs(qty) * current_price
                position_value_pct = (position_value / total_equity * 100) if total_equity > 0 else 0.0

                return {
                    symbol_key: {
                        "direction": "long" if qty > 0 else "short",
                        "quantity": abs(int(qty)),
                        "avg_entry": round(avg_price, 2),
                        "unrealized_pnl": round((current_price - avg_price) * qty, 2),
                        "position_value_pct": round(position_value_pct, 2)
                    }
                }

        # Нет позиции
        return {symbol_key: {
            "direction": "flat",
            "quantity": 0,
            "avg_entry": 0.0,
            "unrealized_pnl": 0.0,
            "position_value_pct": 0.0
        }}
    except Exception as e:
        logger.error(f"[Portfolio] Error: {str(e)}")
        return {config.INSTRUMENT_FIGI: {"direction": "flat", "quantity": 0, "avg_entry": 0.0, "unrealized_pnl": 0.0,
                                         "position_value_pct": 0.0}}


def cast_money(money):
    return money.units + money.nano / 1e9