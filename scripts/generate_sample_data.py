"""Generate a fresh isolated local demo. No API key or network required."""
import argparse
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from model_router.telemetry.demo import generate_demo

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', default='.demo', help='New demo directory (existing data is never overwritten)')
    parser.add_argument('--count', type=int, default=180)
    args = parser.parse_args()
    print(generate_demo(args.output, count=args.count))
