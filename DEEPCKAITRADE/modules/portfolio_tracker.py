
from tinkoff.invest import Client
from config import Config

def get_current_positions(client, account_id, instrument_figi):
    """
    Получает текущие позиции по инструменту с брокера
    Возвращает словарь в формате, совместимом с JSON для промпта
    """
    config = Config()
    try:
        # Получаем портфель
        portfolio = client.operations.get_portfolio(account_id=account_id)
        
        # Ищем позицию по FIGI
        for position in portfolio.positions:
            if position.figi == instrument_figi:
                # Конвертируем количество и цену
                quantity = position.quantity.units + position.quantity.nano / 1e9
                avg_price = position.average_position_price.units + position.average_position_price.nano / 1e9
                
                # Определяем направление позиции
                direction = "long" if quantity > 0 else "short" if quantity < 0 else "flat"
                
                # Рассчитываем стоимость позиции (для max_exposure_pct)
                current_price = client.market_data.get_last_prices(figi=[instrument_figi]).last_prices[0].price
                current_price_value = current_price.units + current_price.nano / 1e9
                position_value = abs(quantity) * current_price_value
                position_value_pct = (position_value / config.INITIAL_BALANCE) * 100 if config.INITIAL_BALANCE > 0 else 0.0
                
                return {
                    "direction": direction,
                    "quantity": abs(int(quantity)),
                    "avg_entry": round(avg_price, 2),
                    "unrealized_pnl": round((current_price_value - avg_price) * quantity, 2),
                    "position_value_pct": round(position_value_pct, 2)
                }
        # Если позиции нет, возвращаем пустую
        return {
            "direction": "flat",
            "quantity": 0,
            "avg_entry": 0.0,
            "unrealized_pnl": 0.0,
            "position_value_pct": 0.0
        }
        
    except Exception as e:
        print(f"[PORTFOLIO ERROR] Не удалось получить позиции: {str(e)}")
        # Возвращаем пустую позицию для продолжения работы
        return {
            "direction": "flat",
            "quantity": 0,
            "avg_entry": 0.0,
            "unrealized_pnl": 0.0,
            "position_value_pct": 0.0
        }

def get_all_positions(client, account_id):
    """
    Возвращает все позиции в портфеле (для расширенного анализа)
    """
    try:
        portfolio = client.operations.get_portfolio(account_id=account_id)
        positions = {}
        
        for position in portfolio.positions:
            quantity = position.quantity.units + position.quantity.nano / 1e9
            avg_price = position.average_position_price.units + position.average_position_price.nano / 1e9
            
            # Получаем текущую цену
            current_price = client.market_data.get_last_prices(figi=[position.figi]).last_prices[0].price
            current_price_value = current_price.units + current_price.nano / 1e9
            
            positions[position.figi] = {
                "ticker": position.ticker,
                "quantity": abs(int(quantity)),
                "avg_price": round(avg_price, 2),
                "current_price": round(current_price_value, 2),
                "direction": "long" if quantity > 0 else "short",
                "unrealized_pnl": round((current_price_value - avg_price) * quantity, 2)
            }
        
        return positions
        
    except Exception as e:
        print(f"[PORTFOLIO ERROR] Не удалось получить все позиции: {str(e)}")
        return {}