"""Serve only the local, read-only synthetic telemetry API."""
import argparse
from datetime import UTC, datetime
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from fastapi import FastAPI
import uvicorn
from model_router.telemetry.demo import open_demo
from model_router.telemetry.query import TelemetryQuery
from model_router.service.telemetry import register_telemetry


def create_demo_app(directory='.demo'):
    repository = open_demo(directory)
    app = FastAPI(title='Model Router · Synthetic demo', version='phase-5-v1')
    query = TelemetryQuery(repository, now=lambda: datetime.now(UTC), application_scope=None, synthetic=True)
    register_telemetry(app, query=query)
    return app


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', default='.demo')
    parser.add_argument('--port', type=int, default=8000)
    args = parser.parse_args()
    uvicorn.run(create_demo_app(args.data), host='127.0.0.1', port=args.port, access_log=False)
