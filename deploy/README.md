# 公网部署指南（Ubuntu + Docker）

该部署方案由 Caddy 自动申请和续期 HTTPS 证书。网页端、PWA 移动端和 API 使用同一域名，因此不需要额外配置跨域。

## 服务器要求

- Ubuntu 22.04 或 24.04；
- 已绑定公网 IPv4；
- 域名的 A 记录已指向该公网 IPv4；
- 防火墙和云安全组允许 TCP `80`、`443`；
- 服务器内存至少 4 GB；若需要较快推理，建议使用 GPU 实例。

## 安装 Docker

在服务器执行：

```bash
sudo apt-get update
sudo apt-get install -y docker.io docker-compose-plugin git
sudo usermod -aG docker "$USER"
newgrp docker
```

## 上传和配置项目

将项目上传或克隆到服务器，例如 `/opt/river-patrol`，然后执行：

```bash
cd /opt/river-patrol
cp .env.production.example .env.production
nano .env.production
mkdir -p runtime/uploads
```

将 `DOMAIN` 改成实际域名。确认域名 DNS 已生效后启动：

```bash
docker compose up -d --build
docker compose logs -f
```

首次启动时 Caddy 会申请证书。成功后访问：

```text
https://你的域名/
https://你的域名/mobile/
```

## 更新与备份

更新代码或模型后：

```bash
docker compose up -d --build
```

业务数据和上传证据保存在 `runtime/`，定期备份该目录：

```bash
tar -czf river-patrol-backup-$(date +%F).tar.gz runtime/
```

不要将 `.env.production`、`runtime/` 或模型以外的敏感文件提交到版本库。

## 无域名公网 IP 演示

仅需要通过浏览器临时访问时，可不配置域名和 HTTPS。复制配置并使用 IP 部署文件：

```bash
cp .env.server.example .env.server
mkdir -p runtime/uploads
docker compose -f compose.ip.yaml up -d --build
```

随后访问：

```text
http://服务器公网IP/
http://服务器公网IP/mobile/
```

该方式只适合演示或内部测试：浏览器会显示 HTTP 不安全提示，Service Worker 与“安装到主屏幕”等 PWA 功能不可用。后续绑定域名后，切换回上文的 HTTPS 部署方式即可。
