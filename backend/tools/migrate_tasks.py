"""Import legacy task JSON without deleting originals or overwriting existing IDs."""
import argparse
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.sqlite_store import TaskStore

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--db', type=Path, required=True)
    parser.add_argument('--legacy-dir', type=Path, required=True)
    args = parser.parse_args()
    print(f'Imported {TaskStore(args.db, args.legacy_dir).migrate_legacy()} tasks; originals retained.')
