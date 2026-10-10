# -*- coding: utf-8 -*-
"""
Carregador «mundo» — dados públicos → esquema Postgres ``mundo``.

Uso:
    python carregar_mundo.py --dsn postgresql://user:pass@host:5432/db
    MUNDO_DSN=postgresql://... python carregar_mundo.py --so gasolineras --so incidencias
    python carregar_mundo.py --sqlite mundo.sqlite          # teste local, sem Docker

Ver mundo/README.md (cadência por fonte, licenças, CronJob).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mundo.carregar import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
