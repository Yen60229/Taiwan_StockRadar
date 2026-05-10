#!/bin/bash
# 在 Ubuntu 22.04 / 24.04 安裝 Docker Engine + Docker Compose v2
# 用法：bash scripts/install_docker.sh
# 執行一次即可，重複執行安全（冪等）

set -euo pipefail

echo "▶ 更新系統套件..."
sudo apt-get update -y
sudo apt-get install -y ca-certificates curl gnupg lsb-release

echo "▶ 加入 Docker 官方 GPG key..."
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
    | sudo gpg --dearmor --yes -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

echo "▶ 加入 Docker apt repo..."
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
   https://download.docker.com/linux/ubuntu \
   $(lsb_release -cs) stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

echo "▶ 安裝 Docker..."
sudo apt-get update -y
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

echo "▶ 將目前使用者加入 docker group（重新登入後生效）..."
sudo usermod -aG docker "$USER"

echo "▶ 啟動 Docker service..."
sudo systemctl enable docker
sudo systemctl start docker

echo ""
echo "✅ Docker 安裝完成"
echo "   docker version：$(docker version --format '{{.Server.Version}}' 2>/dev/null)"
echo "   docker compose：$(docker compose version --short 2>/dev/null)"
echo ""
echo "⚠️  請重新登入 SSH（或執行 newgrp docker）讓 group 生效"
