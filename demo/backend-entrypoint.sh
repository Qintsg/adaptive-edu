#!/bin/sh
# 答辩后端入口：迁移数据库，并在空演示库中建立四账号基线。
set -eu

cd /app/backend
python manage.py migrate --noinput
python manage.py collectstatic --noinput --clear

if [ "${DEMO_SKIP_AUTO_SEED:-0}" != "1" ]; then
    if ! python demo_seed.py --verify-runtime; then
        python demo_seed.py --seed
    fi
fi

exec "$@"
