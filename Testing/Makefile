# =============================================================================
#  DFU project — single-command shortcuts (spec C). Works on macOS and the Pi.
#  Usage:  make test | make run | make clear | make seed | make app
#  Pass args:  make seed ARGS="10"      make clear ARGS="--cloud"
# =============================================================================
PY    ?= python3
DEV    = device
DESK   = desktop
ARGS  ?=

.PHONY: help setup test run device clear seed app

help:
	@echo "DFU commands:"
	@echo "  make setup [ARGS=--ai]      FIRST-TIME install of dependencies"
	@echo "  make test            quick self-check / debug (no hardware)"
	@echo "  make run             launch the RPi5 device app"
	@echo "  make clear [ARGS=--cloud]   wipe local images + DB (+ Firestore)"
	@echo "  make seed  [ARGS=N|--cloud] seed N fake sessions locally (+ cloud)"
	@echo "  make app             launch the desktop app (medical staff)"

setup:
	cd $(DEV) && $(PY) manage.py setup $(ARGS)

test:
	cd $(DEV) && $(PY) manage.py test

run device:
	cd $(DEV) && $(PY) manage.py run

clear:
	cd $(DEV) && $(PY) manage.py clear $(ARGS)

seed:
	cd $(DEV) && $(PY) manage.py seed $(ARGS)

app:
	cd $(DESK) && $(PY) run_desktop.py
