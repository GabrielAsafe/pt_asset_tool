#!/usr/bin/env python3
"""Atalho de aplicacao do patch P1_05; requer aplicar_p0p1_patch.py."""
import sys
from aplicar_p0p1_patch import main
if __name__ == '__main__':
    sys.argv = [sys.argv[0], '--id', 'P1_05', *sys.argv[1:]]
    sys.exit(main())
