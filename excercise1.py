import datetime as dt

import yfinance
from decimal import Decimal

from nautilus_trader.config import StrategyConfig

from nautilus_trader.indicators.macd import MovingAverageConvergenceDivergence

from nautilus_trader.trading.strategy import Strategy

from nautilus_trader.model.data import BarType
from nautilus_trader.model.data import Bar
from nautilus_trader.model.position import Position
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.enums import PriceType
from nautilus_trader.model.enums import OrderSide
from nautilus_trader.model.enums import PositionSide

from nautilus_trader.model.identifiers import Symbol
from nautilus_trader.model.identifiers import Venue
from nautilus_trader.model.instruments import Equity
from nautilus_trader.model.currencies import USD
from nautilus_trader.model.objects import Price, Quantity

from nautilus_trader.backtest.engine import BacktestEngine

from nautilus_trader.config import BacktestEngineConfig
from nautilus_trader.config import LoggingConfig
from nautilus_trader.config import ImportableStrategyConfig

from nautilus_trader.model.identifiers import TraderId
from nautilus_trader.model.identifiers import Venue
from nautilus_trader.model.enums import AccountType
from nautilus_trader.model.enums import OmsType
from nautilus_trader.model.objects import Money
from nautilus_trader.persistence.wranglers import BarDataWrangler


class MACDStrategyConfig(StrategyConfig, frozen=True):

    instrument_id: InstrumentId
    bar_type_1day: BarType
    fast_period: int = 4
    slow_period: int = 8
    trading_side = 10_000
    enter_threshold: float = 0.00010

# Create a subclass of Strategy class
class MACDStrategy(Strategy):
    def __init__(self, config: MACDStrategyConfig):
        super().__init__()
        self.bar_type_1day = config.bar_type_1day

        self.macd = MovingAverageConvergenceDivergence(
            fast_period = config.fast_period,
            slow_period = config.slow_period,
            price_type = PriceType.MID
        )
        self.instrument_id = config.instrument_id
        self.trade_size = Quantity.from_int(config.trading_side)
        
        self.position: Position | None = None
        self.enter_threshold = config.enter_threshold
        
        self.count_processed_bars = 0
        
        self.start_time = None
        self.end_time = None

    def on_start(self):
        self.start_time = dt.datetime.now()

        self.subscribe_bars(self.bar_type_1day)

        self.log.info(f"My MACD strategy started at {self.start_time}")

    def on_bar(self, bar: Bar):
    
        self.count_processed_bars += 1

        self.macd.handle_bar(bar)
        if not self.macd.initialized:
            return

        self.check_for_entry()
        self.check_for_exit()

    def check_for_entry(self):
        if self.macd.value >= self.enter_threshold:
            # If already in Long position do nothing
            if self.position and self.position.side == PositionSide.LONG:
                return
            # Else make order
            order = self.order_factory.market(
                instrument_id = self.instrument_id,
                order_side = OrderSide.BUY,
                quantity = self.trade_size
            )
            self.submit_order(order)

        elif self.macd.value < -self.enter_threshold:
            # If already in Short poisition do nothing
            if self.position and self.position.side == PositionSide.SHORT:
                return
            # Else make order
            order = self.order_factory.market(
                instrument_id = self.instrument_id,
                order_side = OrderSide.SELL,
                quantity = self.trade_size
            )
            self.submit_order(order)

    def check_for_exit(self):
        # If we are in a Short position, exit when MACD value is positive
        if self.macd.value >= 0:
            if self.position and self.position.side == PositionSide.SHORT:
                self.close_position(self.position)
        
        # If we are in a Long position, exit when MACD value is negative
        else:
            if self.position and self.position.side == PositionSide.LONG:
                self.close_position(self.position)
        
    
    def on_end(self):
        
        self.end_time = dt.datetime.now()
        self.close_all_positions(instrument_id = self.config.instrument_id)
        self.unsubscribe_bars()
        
        self.log.info(f"My MACD strategy finnished at {self.end_time}")
        self.log.info(f"Total count of 1 day bars: {self.count_processed_bars} ")
    


def main():
    instrument_id = InstrumentId(
            symbol=Symbol("NVDA"),
            venue=Venue("NASDAQ"),
        )


    # Create the NVIDIA equity instrument
    NVDA_STOCKS_INSTRUMENT = Equity(
        instrument_id=instrument_id,
        raw_symbol=Symbol("NVDA"),
        currency=USD,
        price_precision=2,  # Prices to 2 decimal places
        price_increment=Price.from_str("0.01"),
        lot_size=Quantity.from_int(1),  # Trading in whole shares
        isin="US67066G1040",  # NVIDIA's ISIN identifier
        ts_event=0,  # Timestamp when the instrument was created/updated
        ts_init=0,   # Timestamp when this object was initialized
    )

    NVDA_STOCKS_1DAY_BARTYPE = BarType.from_str(
        f"{NVDA_STOCKS_INSTRUMENT.id}-1-DAY-LAST-EXTERNAL"
    )

    engine_config = BacktestEngineConfig(
        trader_id = TraderId("BACKTEST-NVDA1DAY-001"),
        strategies = [
            ImportableStrategyConfig(
            strategy_path = '__main__:MACDStrategy',
            config_path = '__main__:MACDStrategyConfig',
            config = {
                "instrument_id": instrument_id,
                "bar_type_1day": NVDA_STOCKS_1DAY_BARTYPE,
                "fast_period": 10,
                "slow_period": 20,
                "enter_threshold": 0.00001
            }
            )
        ],
        logging = LoggingConfig(log_level = "DEBUG"),
        
    )

    engine = BacktestEngine(config = engine_config)

    engine.add_venue(
            venue=Venue("NASDAQ"),
            oms_type=OmsType.NETTING,  # Order Management System type
            account_type=AccountType.MARGIN,  # Type of trading account
            starting_balances=[Money(1_000_000, USD)],  # Initial account balance
            base_currency=USD,  # Base currency for account
            default_leverage=Decimal(1),  # No leverage used for account
        )
    engine.add_instrument(NVDA_STOCKS_INSTRUMENT)

    wrangler = BarDataWrangler(
        NVDA_STOCKS_1DAY_BARTYPE,
        NVDA_STOCKS_INSTRUMENT
    )

    config = MACDStrategyConfig(instrument_id=NVDA_STOCKS_INSTRUMENT.id, bar_type_1day=NVDA_STOCKS_1DAY_BARTYPE)
    strategy = MACDStrategy(config=config)
    engine.add_strategy(strategy)

    ydata_df = yfinance.download(tickers=['NVDA'], start='2000-01-01', end='2025-01-01')
    nvda_1day_bars_list: list[Bar] = wrangler.process(ydata_df)
    engine.add_data(nvda_1day_bars_list)
    
    engine.run()
    engine.dispose()
    engine.trader.generate_orders_report()
    engine.trader.generate_positions_report()

if __name__ == "__main__":
    main()
