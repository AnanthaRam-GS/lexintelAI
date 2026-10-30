# Sourced by the test runners (step 23): on macOS, re-run the calling script under `caffeinate -i` so the machine
# does not idle-sleep while the suites run.
#
# Why: unattended local runs on battery took up to ~29 minutes per module although the tests themselves ran in
# seconds. `pmset -g log` showed Idle Sleep / Maintenance Sleep periods matching each slow module (e.g. 1,009 s asleep
# during a 1,010 s test_ipc_bns_sources run whose "Ran 8 tests in 2.587s"). unittest's clock is monotonic and stops
# during sleep; the runner's wall clock does not. Nothing in the tests was hanging.
#
# Usage, near the top of a runner:  source "$(dirname "${BASH_SOURCE[0]}")/keep_awake.sh"; keep_awake "${BASH_SOURCE[0]}" "$@"
# LEGALAI_ALLOW_SLEEP=1 opts out. caffeinate exits with the script, so nothing outlives the run.
keep_awake() {
  local script="$1"
  shift
  if [ "$(uname -s)" = "Darwin" ] && [ -z "${LEGALAI_KEEP_AWAKE_ACTIVE:-}" ] && [ "${LEGALAI_ALLOW_SLEEP:-}" != "1" ] \
      && command -v caffeinate >/dev/null 2>&1; then
    export LEGALAI_KEEP_AWAKE_ACTIVE=1
    exec caffeinate -i bash "$script" "$@"
  fi
}
