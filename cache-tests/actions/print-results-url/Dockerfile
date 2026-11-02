FROM alpine:3.21
ENTRYPOINT ["sh", "-c", "echo \"docker action ACTIONS_RESULTS_URL=${ACTIONS_RESULTS_URL:-unset}\"; case \"$ACTIONS_RESULTS_URL\" in http://169.254.77.1:8448/) echo PASS;; *) echo 'FAIL: Docker action does not use the Celesto cache proxy'; exit 1;; esac"]
