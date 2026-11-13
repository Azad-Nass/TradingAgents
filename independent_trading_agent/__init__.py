"""Independent Trading Agent.

A self-contained analysis and market-intelligence app that lives beside
TradingAgents without changing it. It analyses symbols the user picks
(mode 1), scans configured markets for opportunities (mode 2), keeps its own
SQLite history, evaluates past signals and writes a Persian daily report.

It never places orders. Every price, headline and figure comes from a data
provider at run time; missing data is reported as missing.
"""

__version__ = "0.1.0"
