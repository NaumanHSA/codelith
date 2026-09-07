#!/usr/bin/env sh
# Everything that has to be true before the first request.
#
# Both steps are idempotent and both run on every start, because a container has no
# concept of "the first time" that survives a restart, and a check that has to be
# remembered is one that eventually is not.
set -e

echo "codelith: preparing ${CODELITH_HOME:-/data}"

# Creates the schema if the volume is new, then the first account. Both are
# idempotent. A fresh image used to serve a sign-in form whose only documented
# credentials answered 401, because nothing had ever created a user.
python /app/scripts/seed_dev.py

echo "codelith: starting on :8000"
exec "$@"
