#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from unimac_ui.storage import ensure_demo_files
from unimac_ui.main import WasherUI

def main():
    ensure_demo_files()
    app = WasherUI()
    app.mainloop()

if __name__ == "__main__":
    main()
