# Deployment & Release Commands

Quick reference of common commands to push code, build images, and deploy.

---

## Git (GitHub / GitLab)
- Stage & commit:
  git add .
  git commit -m "Describe change"
  git push origin main

- Create and push a tag:
  git tag -a v1.2.3 -m "Release v1.2.3"
  git push origin v1.2.3

- Create a PR (GitHub CLI):
  gh pr create --title "Feature" --body "Description" --base main --head my-branch

- Push to additional remote (optional):
  git remote add gitlab https://gitlab.com/<group>/<project>.git
  git push gitlab main

---

## Build frontend (run before building a production image)
cd frontend
npm ci
npm run build
# The Dockerfile typically copies `frontend/build` into the runtime image.

---

## Docker Hub (push image)
# Login
docker login --username <DOCKERHUB_USER>
# Build (root of repo where Dockerfile lives)
docker build -t <dockerhub_user>/lynx:latest .
# Tag (optional for version)
docker tag <dockerhub_user>/lynx:latest <dockerhub_user>/lynx:v1.2.3
# Push
docker push <dockerhub_user>/lynx:latest
docker push <dockerhub_user>/lynx:v1.2.3

# Multi-arch build & push (requires buildx & registered builder)
docker buildx build --platform linux/amd64,linux/arm64 -t <dockerhub_user>/lynx:latest --push .

---

## GitLab Container Registry
# Login using Personal Access Token or CI job token
docker login registry.gitlab.com -u <username> -p <PERSONAL_ACCESS_TOKEN>
# Tag and push
docker tag lynx:latest registry.gitlab.com/<group>/<project>/lynx:latest
docker push registry.gitlab.com/<group>/<project>/lynx:latest

---

## GitHub Packages (ghcr.io)
# Login
echo $GITHUB_TOKEN | docker login ghcr.io -u <github_user> --password-stdin
# Tag & push
docker tag lynx:latest ghcr.io/<owner>/<repo>/lynx:latest
docker push ghcr.io/<owner>/<repo>/lynx:latest

---

## Docker Compose (local / server)
# Build all services
docker compose build
# Pull images defined in compose
docker compose pull
# Start in background
docker compose up -d
# Stop & remove containers
docker compose down
# View logs
docker compose logs -f
# Recreate a single service
docker compose up -d --no-deps --build <service_name>

---

## Inspect & manage containers
# List running containers
docker ps
# Show logs
docker logs -f <container_name_or_id>
# Exec into running container
docker exec -it <container_name_or_id> /bin/sh
# Stop / start / restart
docker stop <id>
docker start <id>
docker restart <id>

---

## Rollback (simple)
# Pull previous tag and restart compose
docker pull <dockerhub_user>/lynx:v1.2.2
docker tag <dockerhub_user>/lynx:v1.2.2 lynx:rollback
# Update compose to use the tag, or replace image and recreate service
# Example: recreate service from pulled image
docker compose up -d --no-deps --force-recreate --build

---

## Clean local images & build cache
# Remove dangling images
docker image prune
# Remove unused images (careful)
docker image prune -a
# Full system prune (containers, networks, images)
docker system prune -af

---

## CI/CD & Secrets (notes)
- Store registry credentials as secrets in your CI provider:
  - Docker Hub: `DOCKERHUB_USERNAME` / `DOCKERHUB_TOKEN`
  - GitHub Actions: `GITHUB_TOKEN` (auto-provided) and `CR_PAT` for ghcr push if needed
  - GitLab CI: use `CI_REGISTRY` and `CI_JOB_TOKEN` or personal token
- Example GitHub Actions job will `docker/login-action` then `docker/build-push-action`.

---

## Helpful checks & troubleshooting
- Check which process listens on a port (macOS):
  lsof -iTCP -sTCP:LISTEN -P | grep 8000

- Test API locally (example):
  curl -v http://localhost:8000/api/settings

- Tail logs for startup errors:
  docker compose logs -f

---

## Replace placeholders
Search and replace angle-bracket placeholders like `<dockerhub_user>` or `<owner>` before running commands.

---

If you want, I can also:
- Add a CI workflow file for GitHub Actions or GitLab CI to automate builds and pushes.
- Create a shell script wrapper that builds, tags and pushes images.
