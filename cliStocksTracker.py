import io
import pytz
import utils
import plotille
import warnings
import argparse
import webcolors
import autocolors
import contextlib
import configparser
import multiconfigparser
import math

import numpy as np
import yfinance as market

from matplotlib import colors
from colorama import Fore, Style
from datetime import datetime, timedelta


def main():
    config = multiconfigparser.ConfigParserMultiOpt()
    stocks_config = multiconfigparser.ConfigParserMultiOpt()
    args = parse_args()

    portfolio = Portfolio()
    graphs = []

    # get config path
    config_path = "config.ini" if not args.config else args.config
    portfolio_path = "portfolio.ini" if not args.portfolio_config else args.portfolio_config

    # read config files
    config.read(config_path)
    stocks_config.read(portfolio_path)

    # verify that config files are correct
    verify_config_keys(config, stocks_config)

    portfolio.populate(stocks_config, args)

    portfolio.gen_graphs(
        config["General"]["independent_graphs"] == "True" or args.independent_graphs,
        args.graph_width if args.width else int(config["Frame"]["width"]),
        args.graph_height if args.height else int(config["Frame"]["height"]),
        args.timezone or config["General"]["timezone"],
    )
    portfolio.print_graphs()
    portfolio.print_table(args.rounding_mode or config["General"]["rounding_mode"])

    return


def parse_args():
    parser = argparse.ArgumentParser(description="Options for cliStockTracker.py")
    parser.add_argument(
        "--width", type=int, help="integer for the width of the chart (default is 80)"
    )
    parser.add_argument(
        "--height", type=int, help="integer for the height of the chart (default is 20)"
    )
    parser.add_argument(
        "--independent-graphs",
        action="store_true",
        help="show a chart for each stock",
    )
    parser.add_argument(
        "--timezone",
        type=str,
        default="America/New_York",
        help="your timezone (ex: America/New_York)",
    )
    parser.add_argument(
        "-r",
        "--rounding-mode",
        type=str,
        help="how should numbers be rounded (math | down)",
    )
    parser.add_argument(
        "-ti",
        "--time-interval",
        type=str,
        help="specify time interval for graphs (ex: 1m, 15m, 1h)",
    )
    parser.add_argument(
        "-tp",
        "--time-period",
        type=str,
        help="specify time period for graphs (ex: 15m, 1h, 1d)",
    )
    parser.add_argument(
        "--config",
        type=str,
        help="path to a config.ini file",
    )
    parser.add_argument(
        "--portfolio-config",
        type=str,
        help="path to a portfolio.ini file with your list of stonks",
    )
    args = parser.parse_args()
    return args


def verify_config_keys(config, stocks_config):
    config_keys = {
        "DEFAULT": [],
        "Frame": ["width", "height"],
        "General": ["independent_graphs", "timezone", "rounding_mode"],
    }
    if list(config_keys.keys()) != list(config.keys()):
        print("Invalid config.ini, there is a missing section.")
        return
    for section in config_keys:
        if config_keys[section] != list(config[section].keys()):
            print("Invalid config.ini, " + section + " is missing keys.")
            return

    # check that at least one stock is in portfolio.ini
    if list(stocks_config.keys()) == ["DEFAULT"]:
        print(
            "portfolio.ini has no stocks added or does not exist. There is nothing to show."
        )
        return


class Singleton(type):
    _instances = {}

    def __call__(cls, *args, **kwargs):
        if cls not in cls._instances:
            cls._instances[cls] = super(Singleton, cls).__call__(*args, **kwargs)
        return cls._instances[cls]


class Stock:
    def __init__(self, symbol: str, *args, **kwargs):
        self.symbol = symbol
        self.value = 0
        self.data = []
        self.graph = False  # are we going to be graphing this stock?
        self.color = None
        return

    def calc_value(self, stocks_count):
        return self.data[-1] * stocks_count

    def get_curr(self):
        return self.data[-1]

    def get_open(self):
        return self.data[0]

    def get_data(self):
        return self.data

    def __str__(self):
        return (
            "Stock:"
            + str(self.symbol)
            + " "
            + str(self.value)
            + " "
            + str(len(self.data))
            + " "
            + str(self.graph)
        )


class Portfolio(metaclass=Singleton):
    def __init__(self, *args, **kwargs):
        self.stocks = {}
        self.stocks_metadata = {}
        self.initial_value = 0
        self.color_list = []
        return

    def add_stock(self, stock: Stock, count, value, color):
        self.stocks[stock.symbol] = stock
        self.stocks_metadata[stock.symbol] = [float(count), float(value)]
        self.initial_value += (
            self.stocks_metadata[stock.symbol][0]
            * self.stocks_metadata[stock.symbol][1]
        )
        self.color_list.append(color)
        return

    def get_stocks(self):
        return self.stocks

    def get_stock(self, symbol):
        return self.stocks[symbol]

    def get_color_list(self):
        for stock in self.stocks:
            self.color_list.append(stock.color)

    def average_buyin(self, buys: list, sells: list):
        buy_c, buy_p, sell_c, sell_p, count, bought_at = 0, 0, 0, 0, 0, 0
        buys = [_.split("@") for _ in ([buys] if type(buys) is not tuple else buys)]
        sells = [_.split("@") for _ in ([sells] if type(sells) is not tuple else sells)]

        for buy in buys:
            next_c = float(buy[0])
            if next_c <= 0:
                print(
                    'A negative "buy" key was detected. Use the sell key instead to guarantee accurate calculations.'
                )
                exit()
            buy_c += next_c
            buy_p += float(buy[1]) * next_c

        for sell in sells:
            next_c = float(sell[0])
            if next_c <= 0:
                print(
                    'A negative "sell" key was detected. Use the buy key instead to guarantee accurate calculations.'
                )
                exit()
            sell_c += next_c
            sell_p += float(sell[1]) * next_c

        count = buy_c - sell_c
        if count == 0:
            return 0, 0

        bought_at = (buy_p - sell_p) / count

        return count, bought_at

    # download all ticker data in a single request
    # harder to parse but this provides a signficant performance boost
    def download_market_data(self, args, stocks):
        # get graph time interval and period
        time_period = args.time_period if args.time_period else "1d"
        time_interval = args.time_interval if args.time_interval else "1m"

        return market.download(
            tickers=stocks,
            period=time_period,
            interval=time_interval,
            progress = False
        )

    def populate(self, stocks_config, args):
        # download all stock data
        market_data = self.download_market_data(args, stocks_config.sections())

        # iterate through each ticker data
        for td in market_data[["Open"]]:
            stock = td[1]
            new_stock = Stock(stock)

            # convert the numpy array into a list of prices
            data = market_data["Open"][stock].values.tolist()
            new_stock.data = data

            # save the current stock value
            new_stock.value = data[-1]

            # are we graphing this stock?
            if "graph" in list(stocks_config[stock].keys()):
                if stocks_config[stock]["graph"] == "True":
                    new_stock.graph = True

            if "buy" in list(stocks_config[stock].keys()):
                buyin = stocks_config[stock]["buy"]
            else:
                buyin = ()

            if "sell" in list(stocks_config[stock].keys()):
                sellout = stocks_config[stock]["sell"]
            else:
                sellout = ()

            count, bought_at = self.average_buyin(buyin, sellout)

            # Check the stock color for graphing
            if "color" in list(stocks_config[stock].keys()):
                color = str(stocks_config[stock]["color"])
            else:
                color = None

            # Check that the stock color that was entered is legal
            colorWarningFlag = True
            if color == None:
                colorWarningFlag = False
            elif type(color) == str:
                if (color.startswith("#")) or (
                    color in webcolors.CSS3_NAMES_TO_HEX.keys()
                ):
                    colorWarningFlag = False

            if colorWarningFlag:
                warnings.warn(
                    "The color selected for "
                    + stock
                    + " is not in not in the approved list. Automatic color selection will be used."
                )
                color = None

            # finally, add the stock to the portfolio
            self.add_stock(new_stock, count, bought_at, color)
            continue

    def gen_graphs(self, independent_graphs, graph_width, graph_height, cfg_timezone):
        graphs = []
        if not independent_graphs:
            graphing_list = []
            for stock in self.get_stocks().values():
                if stock.graph:
                    graphing_list.append(stock)
            if len(graphing_list) > 0:
                graphs.append(
                    Graph(
                        graphing_list,
                        graph_width,
                        graph_height,
                        self.color_list[: len(graphing_list)],
                        timezone=cfg_timezone,
                    )
                )
        else:
            for i, stock in enumerate(self.get_stocks().values()):
                if stock.graph:
                    graphs.append(
                        Graph(
                            [stock],
                            graph_width,
                            graph_height,
                            [self.color_list[i]],
                            timezone=cfg_timezone,
                        )
                    )
        for graph in graphs:
            graph.gen_graph(autocolors.color_list)
        self.graphs = graphs
        return

    def print_graphs(self):
        for graph in self.graphs:
            graph.draw()
        return

    def print_gains(self, format_str, gain, timespan, mode):
        positive_gain = gain >= 0
        gain_symbol = "+" if positive_gain else "-"
        gain_verboge = "Gained" if positive_gain else "Lost"

        print("{:25}".format("Value " + gain_verboge + " " + timespan + ": "), end="")
        print(Fore.GREEN if positive_gain else Fore.RED, end="")
        print(
            format_str.format(
                gain_symbol + "$" + str(abs(utils.round_value(gain, mode, 2)))
            )
            + format_str.format(
                gain_symbol
                + str(
                    abs(utils.round_value(
                        gain / self.current_value * 100, mode, 2
                    ))
                )
                + "%"
            )
        )
        print(Style.RESET_ALL, end="")
        return

    def print_portfolio_summary(self, format_str, table):
        for line in table:
            if line[-1] is None:
                pass
            else:
                print(Fore.GREEN if line[-1] else Fore.RED, end="")

            print("\t" + "".join([format_str.format(item) for item in line[:-1]]))
            print(Style.RESET_ALL, end="")

        # print the totals line market value then cost
        print("{:112}".format("\nTotals: "), end="")
        print(Fore.GREEN if self.current_value >= self.initial_value else Fore.RED, end="")
        print(format_str.format("$" + str(round(self.current_value, 2))), end = "")
        print(Fore.RESET, end="")
        print(
            "{:13}".format("")
            + format_str.format("$" + str(round(self.initial_value, 2)))
        )
        return

    def print_table(self, mode):
        # table format:
        #   ticker    owned   last    change  change% low high    avg
        # each row will also get a bonus boolean at the end denoting what color to print the line:
        #   None = don't color (headers)
        #   True = green
        #   False = red
        # additional things to print: portfolio total value, portfolio change (and change %)

        cell_width = 13  # buffer space between columns
        table = [
            [
                "Ticker",
                "Last",
                "Change",
                "Change%",
                "Low",
                "High",
                "Daily Avg",
                "Owned",
                "Mkt Value",
                "Avg Share",
                "Total Cost",
                None,
            ]
        ]
        table.append(
            ["-" * cell_width for _ in range(len(table[0])-1)]
        )  # this is the solid line under the header
        table[-1].append(None)  # make sure that solid line is not colored
        self.current_value = 0
        self.opening_value = 0
        for stock in self.stocks.values():
            line = []
            change_d = utils.round_value(
                stock.get_curr() - stock.get_open(), mode, 2
            )  # change
            change_p = utils.round_value(
                (stock.get_curr() - stock.get_open()) / stock.get_curr() * 100, mode, 2
            )  # change %
            line.append(stock.symbol)  # symbol
            line.append(
                "$" + str(utils.round_value(stock.get_curr(), mode, 2))
            )  # current value
            if change_d >= 0:  # insert the changes into the array
                line.append("+$" + str(change_d))
                line.append("+" + str(change_p) + "%")
            else:
                line.append(
                    "-$" + str(change_d)[1:]
                )  # string stripping here is to remove the native '-' sign
                line.append("-" + str(change_p)[1:] + "%")
            line.append(
                "$" + str(utils.round_value(min(stock.get_data()), mode, 2))
            )  # low
            line.append(
                "$" + str(utils.round_value(max(stock.get_data()), mode, 2))
            )  # high
            line.append(
                "$"
                + str(
                    utils.round_value(
                        sum(stock.get_data()) / len(stock.get_data()), mode, 2
                    )
                )
            )  # avg
            line.append(
                str(round(self.stocks_metadata[stock.symbol][0], 3))
            )  # number of stocks owned

            # current market value of shares
            curr_value = stock.calc_value(self.stocks_metadata[stock.symbol][0])
            line.append(
                "$"
                + str(
                    utils.round_value(
                        curr_value, mode, 2
                    )
                )
            )

            # Average buy in cost
            line.append(
                str(round(self.stocks_metadata[stock.symbol][1], 2))
            )

            # total cost of shares
            cost = self.stocks_metadata[stock.symbol][0] * self.stocks_metadata[stock.symbol][1]
            line.append(
                "$"
                + str(
                    utils.round_value(
                        cost, mode, 2
                    )
                )
            )
            line.append(True if change_d >= 0 else False)
            table.append(line)

            # just add in the total value seeing as we're iterating stocks anyways
            self.current_value += stock.calc_value(
                self.stocks_metadata[stock.symbol][0]
            )
            # and the opening value of all the tracked stocks
            self.opening_value += (
                stock.get_open() * self.stocks_metadata[stock.symbol][0]
            )

        # generate ticker daily summary
        print("\nPortfolio Summary:\n")
        format_str = "{:" + str(cell_width) + "}"
        self.print_portfolio_summary(format_str, table)

        # generate overall stats
        print(
            "\n"
            + "{:25}".format("Current Time: ")
            + format_str.format(datetime.now().strftime("%A %b %d, %Y - %I:%M:%S %p"))
        )
        print(
            "{:25}".format("Total Cost: ")
            + format_str.format("$" + str(round(self.initial_value, 2)))
        )
        print(
            "{:25}".format("Total Value: ")
            + format_str.format("$" + str(round(self.current_value, 2)))
        )

        # print daily value
        value_gained_day = self.current_value - self.opening_value
        self.print_gains(format_str, value_gained_day, "Today", mode)

        # print overall value
        value_gained_all = self.current_value - self.initial_value
        self.print_gains(format_str, value_gained_all, "Overall", mode)


class Graph:
    def __init__(
        self, stocks: list, width: int, height: int, colors: list, *args, **kwargs
    ):
        self.stocks = stocks
        self.graph = ""
        self.colors = colors
        self.plot = plotille.Figure()

        self.plot.width = width
        self.plot.height = height
        self.plot.color_mode = "rgb"
        self.plot.X_label = "Time"
        self.plot.Y_label = "Value"

        if "timezone" in kwargs.keys():
            self.timezone = pytz.timezone(kwargs["timezone"])
        else:
            self.timezone = pytz.utc

        if "starttime" in kwargs.keys():
            self.start = (
                kwargs["startend"].replace(tzinfo=pytz.utc).astimezone(self.timezone)
            )
        else:
            self.start = (
                datetime.now()
                .replace(hour=14, minute=30, second=0)
                .replace(tzinfo=pytz.utc)
                .astimezone(self.timezone)
            )

        if "endtime" in kwargs.keys():
            self.end = (
                kwargs["endtime"].replace(tzinfo=pytz.utc).astimezone(self.timezone)
            )
        else:
            self.end = (
                datetime.now()
                .replace(hour=21, minute=0, second=0)
                .replace(tzinfo=pytz.utc)
                .astimezone(self.timezone)
            )

        self.plot.set_x_limits(min_=self.start, max_=self.end)

        return

    def __call__(self):
        return self.graph

    def draw(self):
        print(self.graph)
        return

    def gen_graph(self, auto_colors):
        self.y_min, self.y_max = self.find_y_range()
        self.plot.set_y_limits(min_=self.y_min, max_=self.y_max)

        for i, stock in enumerate(self.stocks):
            if self.colors[i] == None:
                color = webcolors.hex_to_rgb(auto_colors[i % 67])
            elif self.colors[i].startswith("#"):
                color = webcolors.hex_to_rgb(self.colors[i])
            else:
                color = webcolors.hex_to_rgb(
                    webcolors.CSS3_NAMES_TO_HEX[self.colors[i]]
                )

            # some ticker data returns a NaN value for certain points
            # instead of removing them, steal your neighbors value so we can graph
            # iterating all stock data isn't ideal but we can refactor this later
            for q in range(len(stock.data)):
                if math.isnan(stock.data[q]):
                    index = q - 1 if q - 1 >=0 else q + 1
                    stock.data[q] = stock.data[index]

            self.plot.plot(
                [self.start + timedelta(minutes=i) for i in range(len(stock.data))],
                stock.data,
                lc=color,
                label=stock.symbol,
            )

        self.graph = self.plot.show(legend=True)
        return

    def find_y_range(self):
        y_min = 10000000000000  # Arbitrarily large number (bigger than any single stock should ever be worth)
        y_max = 0

        for stock in self.stocks:
            if y_min > min(stock.data):
                y_min = min(stock.data)
            if y_max < max(stock.data):
                y_max = max(stock.data)

        return y_min, y_max


if __name__ == "__main__":
    main()
