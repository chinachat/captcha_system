#!/usr/bin/env bash
# 自动选择 Docker 基础镜像源（国内/国际）后构建
#
# 用法:
#   ./build.sh                 # 自动探测并构建
#   ./build.sh --no-cache      # 自动探测并强制重建
#   BASE_IMAGE=python:3.12-slim ./build.sh   # 手动指定基础镜像
set -e
cd "$(dirname "$0")"

echo "== 探测 Docker 基础镜像源 =="
pick_registry() {
  for u in \
    "https://docker.m.daocloud.io/v2/" \
    "https://registry.cn-hangzhou.aliyuncs.com/v2/" \
    "https://registry-1.docker.io/v2/"; do
    if curl -sI --connect-timeout 3 -o /dev/null "$u" 2>/dev/null; then
      case "$u" in
        *daocloud*) echo "docker.m.daocloud.io" && return ;;
        *aliyuncs*) echo "registry.cn-hangzhou.aliyuncs.com" && return ;;
        *)          echo "docker.io" && return ;;
      esac
    fi
  done
  echo "docker.m.daocloud.io"   # 全部不可达时兜底
}

if [ -z "${BASE_IMAGE:-}" ]; then
  REGISTRY=$(pick_registry)
  export BASE_IMAGE="${REGISTRY}/library/python:3.12-slim"
fi
echo "基础镜像源: ${BASE_IMAGE}"

exec docker compose build "$@"
