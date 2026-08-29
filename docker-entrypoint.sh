#!/bin/sh
set -e

case "$ROLE" in
  api)
    exec uvicorn n_migrate.api.main:app --host 0.0.0.0 --port 8000
    ;;
  worker)
    exec celery -A n_migrate.api.tasks worker --loglevel=info
    ;;
  *)
    echo "Unknown ROLE '$ROLE' -- expected 'api' or 'worker'" >&2
    exit 1
    ;;
esac
