# Architecture

Status: Bootstrap placeholder

The router will separate pure routing decisions from provider execution,
persistence, and HTTP delivery. The intended package boundaries are represented
under `src/model_router/`.

## TODO

- Document component responsibilities and dependency direction.
- Add request and decision flow diagrams.
- Define configuration loading, lifecycle, and failure behavior.
- Define FastAPI and storage adapters around the routing core.
