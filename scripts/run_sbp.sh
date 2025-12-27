#!/bin/bash
# Copyright (c) Meta Platforms, Inc. and affiliates.

task_id="$TASK_ID"
if [[ -z "$task_id" ]]; then
  echo "TASK_ID need to present in env"
  exit 1
fi
export AWS_REGION_NAME=us-west-2
export AWS_DEFAULT_REGION=us-west-2
export AWS_REGION=us-west-2
cp /data/app.pex /usr/local/bin/
mkdir -p /opt/appenv && tar --no-same-owner -xzf /data/cf_env.tar.gz  -C /opt/appenv && /opt/appenv/bin/conda-unpack
export PEX_PYTHON=/opt/appenv/bin/python
prev_commit=$(git rev-parse HEAD)
if /usr/local/bin/app.pex --prompt /data/problem_statements/"$task_id".txt > /data/logs/"$task_id".log 2>&1; then
    new_commit=$(git rev-parse HEAD)
    if [ "$prev_commit" != "$new_commit" ]; then
        # Case 1: New commit was made
        cd /app && git diff HEAD~1 > /data/solutions/"$task_id".diff
        echo "========== TASK SUCCESS: commit exported ==========" >> /data/logs/"$task_id".log
    elif ! git diff --quiet; then
        # Case 2: No commit, but unstaged changes exist
        cd /app && git diff > /data/solutions/"$task_id".diff
        echo "========== TASK PARTIAL SUCCESS: staged changes exported ==========" >> /data/logs/"$task_id".log
    else
        # Case 3: No commit and no changes
        echo "========== TASK FAILED: no changes made ==========" >> /data/logs/"$task_id".log
    fi
else
    echo "========== TASK FAILED: Exit code $? ==========" >> /data/logs/"$task_id".log
fi

# copy trajectory out
cp /tmp/confucius/traj_*.json  /data/logs/"$task_id".traj.json
