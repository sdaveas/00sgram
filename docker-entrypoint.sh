#!/bin/sh
# A display always exists, so the browser provider is never headless and never
# has to care whether one was configured. Started here rather than through
# xvfb-run, which swallowed the app's own log lines and left no trace when the
# child died.
#
# The lock file survives `docker stop` + `start` (the container filesystem is
# kept), and a stale one makes the next Xvfb exit immediately — leaving uvicorn
# running with no display and every browser launch failing. -nolock plus an
# explicit removal covers both halves of that.
rm -f /tmp/.X99-lock /tmp/.X11-unix/X99
Xvfb :99 -screen 0 1280x1024x24 -nolisten tcp -nolock &
export DISPLAY=:99

# Do not start serving before the display can accept a client: a sync that runs
# in the first second would otherwise report "no XServer" for no good reason.
i=0
while [ ! -S /tmp/.X11-unix/X99 ] && [ "$i" -lt 40 ]; do
  i=$((i + 1))
  sleep 0.25
done

exec uvicorn app.asgi:app --host 0.0.0.0 --port 8080
