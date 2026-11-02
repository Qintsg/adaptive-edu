#!/bin/sh
# 文件描述：迁移数据库并在首次启动时初始化课程。
# 项目名：AdaptiveEdu；文件名：backend-entrypoint.sh；作者：Qintsg；日期：2026-11-02。
set -eu

cd /app/backend
python manage.py migrate --noinput
python manage.py collectstatic --noinput --clear

if [ "${DEMO_SKIP_AUTO_SEED:-0}" != "1" ]; then
    python demo_seed.py --initialize
fi

exec "$@"
