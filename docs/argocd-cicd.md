# Argo CD CI/CD 部署方案

目标：源码或部署配置任意变更后自动更新 Kubernetes 中的 `landppt` 实例。

## 流程

### 1. 源码变更

变更范围包括：

- `src/**`
- `Dockerfile`
- `docker-entrypoint.sh`
- `docker-healthcheck.sh`
- `pyproject.toml`
- `uv.lock`

流程：

```text
push 到 main/master
  -> GitHub Actions 构建 Docker 镜像
  -> 推送 ghcr.io/<owner>/landppt:git-<commit-sha>
  -> 自动更新 helm/landppt/values-argocd.yaml 的 image.repository/image.tag
  -> 提交 chore(deploy) commit
  -> Argo CD 发现 values-argocd.yaml 变化
  -> 自动 sync 到 Kubernetes
```

### 2. 部署配置变更

变更范围包括：

- `helm/landppt/values-argocd.yaml`
- `helm/landppt/values.yaml`
- `helm/landppt/templates/**`
- `helm/landppt/Chart.yaml`

流程：

```text
push 到 master
  -> Argo CD 发现 helm/landppt 变化
  -> 自动 sync 到 Kubernetes
```

配置变更不会重新构建镜像。

## 首次安装 Argo CD

```bash
kubectl create namespace argocd
kubectl apply -n argocd -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml
kubectl rollout status deployment/argocd-server -n argocd
```

## 创建 LandPPT Application

> 注意：需要先把本次新增的 `helm/landppt/values-argocd.yaml` 和 `deploy/argocd/landppt-application.yaml` 推送到 GitHub 的 `master` 分支。若你的默认分支改成 `main`，请同步修改 `deploy/argocd/landppt-application.yaml` 里的 `targetRevision`。

```bash
kubectl apply -f deploy/argocd/landppt-application.yaml
```

查看同步状态：

```bash
kubectl get application landppt -n argocd
kubectl describe application landppt -n argocd
```

## 内置 PostgreSQL 密码管理

当前仓库是 public，`values-argocd.yaml` 不保存真实 PostgreSQL 密码，而是引用集群内手动创建的 Secret：

```yaml
postgresql:
  auth:
    existingSecret: landppt-postgresql-auth
    passwordKey: POSTGRES_PASSWORD
```

首次启用前创建 Secret：

```bash
kubectl create secret generic landppt-postgresql-auth \
  -n landppt \
  --from-literal=POSTGRES_PASSWORD='<current-or-new-db-password>'
```

如果是已经初始化过的内置 PostgreSQL，Secret 中的密码必须和数据库用户当前密码一致；如果要轮换密码，应先在数据库内执行 `ALTER USER landppt WITH PASSWORD 'new-password';`，再更新 Secret 并重启相关 Pod。

## GHCR 镜像拉取权限

GitHub Actions 默认推送到：

```text
ghcr.io/<github-org-or-user>/landppt:git-<commit-sha>
```

如果 GHCR Package 是公开的，集群无需额外配置。

如果 GHCR Package 是私有的，需要创建镜像拉取 Secret：

```bash
kubectl create secret docker-registry ghcr-pull-secret \
  -n landppt \
  --docker-server=ghcr.io \
  --docker-username=<github-user> \
  --docker-password=<github-token-with-read:packages> \
  --docker-email=<email>
```

然后在 `helm/landppt/values-argocd.yaml` 中启用：

```yaml
imagePullSecrets:
  - name: ghcr-pull-secret
```

## 访问 Argo CD UI

```bash
kubectl port-forward svc/argocd-server -n argocd 8080:443
```

默认 admin 密码：

```bash
kubectl get secret argocd-initial-admin-secret -n argocd \
  -o jsonpath='{.data.password}' | base64 -d && echo
```

浏览器打开：

```text
https://localhost:8080
```

## 注意事项

- 当前集群使用 `local-path` + RWO PVC，`values-argocd.yaml` 中 Web 保持 1 副本，避免多副本挂载同一个 RWO PVC。
- `migration.enabled=false`，避免 Helm/Argo CD 同步时遇到 Kubernetes Job 不可变字段问题。需要迁移时建议单独执行一次性 Job。
- 当前 `values-argocd.yaml` 初始镜像仍是 `landppt-local:s3-gallery`，用于不破坏现有部署。下一次源码变更后，GitHub Actions 会自动更新为 GHCR 镜像。
- 不要把真实 API key、数据库密码、S3 secret 等写入 public 仓库；优先使用 Kubernetes Secret、SealedSecret 或 External Secrets。
