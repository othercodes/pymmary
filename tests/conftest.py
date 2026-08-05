# The pytest adapter replaces the terminal output of an entire run, so — unlike
# pyrrange — we must NOT re-export its hooks here. `-p no:pymmary` in addopts
# keeps our own plugin off, and adapter tests drive an isolated inner pytest
# session through `pytester` instead.
pytest_plugins = ["pytester"]
