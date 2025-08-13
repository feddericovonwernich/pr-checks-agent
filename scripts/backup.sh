#!/bin/bash

set -e

# Configuration
BACKUP_DIR="${BACKUP_DIR:-./backups}"
REDIS_URL="${REDIS_URL:-redis://localhost:6379/0}"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")

echo "🗄️ Starting Redis backup..."

# Create backup directory
mkdir -p "$BACKUP_DIR"

# Extract Redis connection details
REDIS_HOST=$(echo "$REDIS_URL" | sed -n 's|redis://\([^:]*\):.*|\1|p')
REDIS_PORT=$(echo "$REDIS_URL" | sed -n 's|redis://[^:]*:\([0-9]*\)/.*|\1|p')
REDIS_DB=$(echo "$REDIS_URL" | sed -n 's|redis://[^/]*/\([0-9]*\)|\1|p')

# Default values
REDIS_HOST=${REDIS_HOST:-localhost}
REDIS_PORT=${REDIS_PORT:-6379}
REDIS_DB=${REDIS_DB:-0}

echo "📍 Backing up Redis at $REDIS_HOST:$REDIS_PORT (DB: $REDIS_DB)"

# Create backup filename
BACKUP_FILE="$BACKUP_DIR/redis_backup_${TIMESTAMP}.rdb"

# Perform backup using redis-cli
if command -v redis-cli &> /dev/null; then
    echo "💾 Creating Redis backup..."
    redis-cli -h "$REDIS_HOST" -p "$REDIS_PORT" -n "$REDIS_DB" --rdb "$BACKUP_FILE"
    echo "✅ Backup saved to: $BACKUP_FILE"
else
    echo "❌ redis-cli not found. Please install Redis CLI tools."
    exit 1
fi

# Compress backup
echo "🗜️ Compressing backup..."
gzip "$BACKUP_FILE"
COMPRESSED_FILE="${BACKUP_FILE}.gz"

# Clean up old backups (keep last 7 days)
echo "🧹 Cleaning up old backups..."
find "$BACKUP_DIR" -name "redis_backup_*.rdb.gz" -mtime +7 -delete

echo "🎉 Backup complete: $COMPRESSED_FILE"

# Show backup info
BACKUP_SIZE=$(du -h "$COMPRESSED_FILE" | cut -f1)
echo "📊 Backup size: $BACKUP_SIZE"