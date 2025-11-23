import json
from datetime import datetime
import os
from DEEPCKAITRADE.config import Config

class PortfolioSimulator:
    def __init__(self, initial_balance):
        self.balance = initial_balance
        self.initial_balance = initial_balance
        self.positions = {}  # {"AAPL": {"quantity": 10, "avg_price": 150.00}}
        self.trades = []     # История сделок
        self.equity_history = []  # Для графиков
    
    def get_equity(self, current_prices):
        """Рассчитывает текущую equity с учётом открытых позиций"""
        equity = self.balance
        for symbol, pos in self.positions.items():
            if symbol in current_prices:
                equity += pos["quantity"] * current_prices[symbol]
        return equity
    
    def execute_trade(self, prediction, current_price, timestamp):
        """Имитирует исполнение сделки"""
        symbol = "SIMULATED"  # Для упрощения
        action = prediction["action"]
        size = prediction["size"]
        sl = prediction["stop_loss"]
        tp = prediction["take_profit"]
        
        if action == "HOLD":
            return
        
        # Расчёт комиссии
        commission = Config().FIXED_COMMISSION + (size * Config().COMMISSION_PER_SHARE)
        cost = size * current_price if action == "BUY" else 0
        
        if action == "BUY":
            # Проверка достаточности средств
            if self.balance < cost + commission:
                print(f"[BACKTEST] Недостаточно средств для BUY {size} по {current_price}")
                return
            
            # Обновление позиции
            if symbol in self.positions:
                old_qty = self.positions[symbol]["quantity"]
                old_avg = self.positions[symbol]["avg_price"]
                new_avg = (old_qty * old_avg + size * current_price) / (old_qty + size)
                self.positions[symbol] = {"quantity": old_qty + size, "avg_price": new_avg}
            else:
                self.positions[symbol] = {"quantity": size, "avg_price": current_price}
            
            self.balance -= (cost + commission)
            
        elif action == "SELL":
            # Для упрощения: закрываем всю позицию
            if symbol in self.positions:
                qty = self.positions[symbol]["quantity"]
                avg_price = self.positions[symbol]["avg_price"]
                proceeds = qty * current_price
                self.balance += (proceeds - commission)
                pnl = (current_price - avg_price) * qty
                del self.positions[symbol]
            else:
                print(f"[BACKTEST] Попытка SELL без позиции")
                return
        
        # Сохраняем сделку
        self.trades.append({
            "timestamp": timestamp,
            "action": action,
            "size": size,
            "price": current_price,
            "sl": sl,
            "tp": tp,
            "commission": commission,
            "balance_after": self.balance
        })
    
    def save_results(self, output_dir="backtest_results"):
        """Сохраняет результаты симуляции"""
        os.makedirs(output_dir, exist_ok=True)
        
        results = {
            "metadata": {
                "initial_balance": self.initial_balance,
                "final_balance": self.balance,
                "total_return_pct": ((self.balance / self.initial_balance) - 1) * 100,
                "total_trades": len(self.trades),
                "start_date": Config().BACKTEST_START,
                "end_date": Config().BACKTEST_END
            },
            "trades": self.trades,
            "final_positions": self.positions
        }
        
        filename = f"{output_dir}/backtest_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(filename, 'w') as f:
            json.dump(results, f, indent=2)
        
        print(f"\n✅ Бэктест завершён! Результаты сохранены в {filename}")
        print(f"📈 Доходность: {results['metadata']['total_return_pct']:.2f}%")
        print(f"💰 Итоговый баланс: ${self.balance:.2f}")
        print(f"📊 Сделок: {len(self.trades)}")
        
        return filename