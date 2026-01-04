# Run multiple processes with: honcho start
# Or run individual processes: honcho start dashboard

# Web dashboard for monitoring progress
dashboard: salli dashboard

# Background archive.org checker (runs continuously)
archive_checker: salli check-archive --continuous

# Background uploader (runs continuously)
uploader: while true; do salli upload; sleep 5; done
