#!/usr/bin/env python3
"""Back up or restore local backend data while the application is stopped."""
import argparse
import os
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.app.backups import create_backup, restore_backup


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['backup','restore'])
    parser.add_argument('archive',type=Path)
    parser.add_argument('--data-dir',type=Path,default=Path(os.environ.get('AI_WORKSTATION_DATA',Path.home()/'.local/share/ai-workstation')))
    parser.add_argument('--confirm-restore',action='store_true')
    args=parser.parse_args()
    if args.action=='backup':print(create_backup(args.data_dir,args.archive))
    else:
        previous=restore_backup(args.data_dir,args.archive,approved=args.confirm_restore)
        print(f'Restored. Previous data: {previous}')

if __name__=='__main__':main()
