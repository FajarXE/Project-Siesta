# Project Siesta - Telegram Media Downloader Bot

A Python 3.12 Telegram media downloader bot built on Pyrogram, asyncio, and Flask, with ffmpeg, rclone, and async MongoDB for storage and delivery.

## Features

- Multi-platform music downloading (Qobuz, Deezer, Tidal, Beatport)
- Telegram bot interface with admin controls
- Customizable quality and packaging options
- ZIP archive generation and rclone/index links
- Metadata-rich messages
- Anti-spam and authentication controls

## Session Management and Single-Instance Requirements

### Overview

Project Siesta uses Pyrogram for Telegram client communication, which creates session files to maintain authentication state. To prevent `AUTH_KEY_DUPLICATED` errors, only **one instance** should run with the same session configuration.

### Environment Variables

#### Session Configuration
```bash
# Session name (default: siesta)
SESSION_NAME=siesta

# Session directory (default: /data/sessions) 
SESSION_DIR=/data/sessions
```

#### Distributed Lock (Optional)
```bash
# Enable MongoDB-based distributed lock (default: true)
ENABLE_DISTRIBUTED_LOCK=true

# Lock time-to-live in minutes (default: 5)
LOCK_TTL_MINUTES=5
```

### Docker Deployment

#### Volume Mounting
Always mount the session directory as a volume:
```bash
docker run -v /path/to/sessions:/data/sessions ...
```

#### Environment Configuration
```bash
docker run -e SESSION_NAME=siesta \
           -e SESSION_DIR=/data/sessions \
           -e ENABLE_DISTRIBUTED_LOCK=true \
           -v /path/to/sessions:/data/sessions \
           project-siesta
```

### Troubleshooting AUTH_KEY_DUPLICATED

#### Causes
1. **Multiple instances** running with same `SESSION_NAME`/`SESSION_DIR`
2. **Stale session files** from previous deployments
3. **Container restart** without proper cleanup
4. **Shared storage** with multiple replicas

#### Solutions

##### 1. Use Unique Session Names
```bash
# For different environments
SESSION_NAME=siesta-prod
SESSION_NAME=siesta-staging
SESSION_NAME=siesta-dev
```

##### 2. Clean Session Directory
```bash
# Remove existing session files
rm -f /data/sessions/siesta.session*
```

##### 3. Enable Distributed Lock
The MongoDB-based lock prevents multiple instances:
```bash
ENABLE_DISTRIBUTED_LOCK=true
LOCK_TTL_MINUTES=10
```

##### 4. Scale to Single Replica
Ensure only one container replica runs:
```yaml
# docker-compose.yml
deploy:
  replicas: 1
```

### Startup Diagnostics

The bot logs comprehensive startup information:
```
BOT : PROJECT-SIESTA STARTING UP
BOT : Deployment diagnostics:
BOT : - Hostname: container-name
BOT : - Container ID: abc123456789
BOT : - Git commit: a1b2c3d
BOT : - Session name: siesta
BOT : - Session directory: /data/sessions
BOT : - Bot username: my_bot
BOT : - Work directory: ./bot/
BOT : Session directory /data/sessions is writable
LOCK : Attempting to acquire distributed lock...
LOCK : Distributed lock acquired and renewal task started
BOT : Started Successfully
```

### Conflict Detection

When `AUTH_KEY_DUPLICATED` is detected:
```
BOT : AUTH_KEY_DUPLICATED - Session conflict detected!
BOT : Session path: /data/sessions/siesta
BOT : This usually means another instance is running with the same session.
BOT : Solution: Stop the other instance or use a different SESSION_NAME/SESSION_DIR
```

When distributed lock fails:
```
LOCK : Failed to acquire distributed lock - another instance may be running
LOCK : To override, set ENABLE_DISTRIBUTED_LOCK=false or use different SESSION_NAME
```

### Best Practices

1. **Always mount session directory** as external volume
2. **Use unique session names** for different environments
3. **Enable distributed lock** for production deployments
4. **Scale to single replica** to prevent conflicts
5. **Monitor startup logs** for session diagnostics
6. **Clean session files** when changing bot tokens

### Migration Guide

If you're experiencing `AUTH_KEY_DUPLICATED` after deployment:

1. **Stop all running instances**
2. **Clean session directory**:
   ```bash
   docker exec <container> rm -f /data/sessions/*.session*
   ```
3. **Update environment variables** with unique session name
4. **Restart with single replica**
5. **Verify startup logs** show successful initialization

## Configuration

See `sample.env` for all available configuration options.

## Deployment

### Docker
```bash
docker build -t project-siesta .
docker run -d \
  --name siesta-bot \
  -v $(pwd)/sessions:/data/sessions \
  --env-file .env \
  project-siesta
```

### Docker Compose
```yaml
version: '3.8'
services:
  siesta:
    build: .
    volumes:
      - ./sessions:/data/sessions
    environment:
      - SESSION_NAME=siesta
      - SESSION_DIR=/data/sessions
      - ENABLE_DISTRIBUTED_LOCK=true
    deploy:
      replicas: 1
    restart: unless-stopped
```

## Support

For issues related to session management:
1. Check startup logs for diagnostic information
2. Verify session directory permissions and mounting
3. Ensure single replica deployment
4. Clean session files if changing tokens

## License

See LICENSE file for details.
