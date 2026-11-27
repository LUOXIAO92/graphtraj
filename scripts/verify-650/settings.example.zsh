# Task 650: template of the ONE local settings file the steps read. Copy it to
#   scripts/verify-650/local/settings.zsh   (git-ignored; never commit it)
# and replace every value. All values below are fake placeholders. The steps STOP, naming the variable, when a
# REQUIRED one is missing or empty, when an OPTIONAL one is not assigned at all (an empty value is fine: NAME=), and
# when the file is not git-ignored or is tracked. No value is echoed by the steps; 00 prints the variable NAMES only
# (and a cost estimate on the console). Plain assignments only: the file is sourced by zsh.
# One temporary key serves all three Runtimes: the USER enters it at step K; it is stored only as the VM user's
# environment variable KEY_ENV, and the driver hands it to each Runtime under the variable that Runtime reads.
# The evidence scrub replaces the values of PROJECT, ZONE, VM_NAME, MACHINE_TYPE, the label VALUES, VM_USER, KEY_ENV,
# every *_BASE_URL (and its host), every *_MODEL, PI_PROVIDER, PI_KEY_VAR, DSH_CHILD_PROVIDER, DSH_MAIN_KEY_VAR and the
# words of DSH_MAIN_APP_ARGS that do not start with '-': each must be distinctive (4+ characters, not found in
# drive650.py or steps.zsh), or 00 and V STOP naming the variable. NETWORK, label keys, CLAUDE_AUTH_VAR, PI_ROUTE and
# PI_API are not scrubbed (they are generic words).

# --- The cloud project and the VM (as Task 644) -----------------------------------------------------------------
PROJECT=example-project-000000       # cloud project id; every gcloud command names it with --project
ZONE=example-zone1-a                 # zone of the VM (its region is derived by dropping the last '-x')
MACHINE_TYPE=example-machine-2       # machine type of the VM
VCPUS=2                              # vCPUs of MACHINE_TYPE (used only for the cost estimate)
VM_NAME=example-vm-name              # VM name; also its network tag and the stem of the Task rules <VM_NAME>-deny, <VM_NAME>-ssh
VM_LABELS=example-key=example-value  # labels put on the VM (gcloud --labels syntax), so D can find it
VM_USER=example-user                 # Windows account created from the instance's ssh-keys metadata (<= 20 chars)
NETWORK=example-network              # VPC network of the VM; the two Task firewall rules go there
IMAGE_FAMILY=example-image-family    # public Windows Server x64 image family
IMAGE_PROJECT=example-image-project  # public image project that hosts IMAGE_FAMILY
DISK_GB=64                           # boot disk size in GB (balanced persistent disk, deleted with the VM)

# --- The one shared key ------------------------------------------------------------------------------------------
KEY_ENV=EXAMPLE_SHARED_KEY           # REQUIRED. Name of the VM user's environment variable step K stores the key in; also
                                     # the DSH child connection's api_key_env (the child reads the key from it)

# --- Claude Code (the Claude host), an Anthropic-compatible endpoint ---------------------------------------------
CLAUDE_BASE_URL=https://claude.example.invalid/anthropic   # REQUIRED -> ANTHROPIC_BASE_URL
CLAUDE_AUTH_VAR=ANTHROPIC_AUTH_TOKEN # REQUIRED: ANTHROPIC_AUTH_TOKEN (endpoint takes Authorization: Bearer) or
                                     # ANTHROPIC_API_KEY (endpoint takes x-api-key); it gets the shared key
CLAUDE_MODEL=example-claude-model    # REQUIRED -> ANTHROPIC_MODEL
CLAUDE_HAIKU_MODEL=                  # OPTIONAL -> ANTHROPIC_DEFAULT_HAIKU_MODEL (also background work); empty: not set
CLAUDE_SONNET_MODEL=                 # OPTIONAL -> ANTHROPIC_DEFAULT_SONNET_MODEL; empty: not set
CLAUDE_OPUS_MODEL=                   # OPTIONAL -> ANTHROPIC_DEFAULT_OPUS_MODEL; empty: not set
CLAUDE_SUBAGENT_MODEL=               # OPTIONAL -> CLAUDE_CODE_SUBAGENT_MODEL; empty: not set
CLAUDE_API_TIMEOUT_MS=               # OPTIONAL -> API_TIMEOUT_MS (digits) for a slow endpoint; empty: not set

# --- Pi (the Pi host) --------------------------------------------------------------------------------------------
PI_ROUTE=builtin                     # REQUIRED: builtin (a provider Pi ships) or custom (a models.json provider)
PI_PROVIDER=example-pi-provider      # REQUIRED: the provider id (pi --provider)
PI_MODEL=example-pi-model            # REQUIRED: the model id (pi --model)
PI_KEY_VAR=EXAMPLE_PI_PROVIDER_KEY   # builtin: REQUIRED, the provider's own key variable (Pi's docs/providers.md); it
                                     # gets the shared key. custom: leave empty (PI_KEY_VAR=)
PI_BASE_URL=                         # custom: REQUIRED, the provider's baseUrl in models.json. builtin: empty
PI_API=                              # custom: REQUIRED, the provider's api in models.json (Pi's docs/models.md). builtin: empty

# --- DSH: the DSH child of every host (a connection with runtime dsh) --------------------------------------------
DSH_CHILD_MODEL=example-dsh-model    # REQUIRED: the child's model
DSH_CHILD_PROVIDER=                  # OPTIONAL: a provider the installed DSH serves; empty: DSH's built-in route
DSH_CHILD_BASE_URL=                  # OPTIONAL: http(s) endpoint replacing the route's address; empty: the route's own

# --- DSH: the main DSH Session (the DSH host) ---------------------------------------------------------------------
DSH_MAIN_KEY_VAR=EXAMPLE_DSH_KEY_VAR # REQUIRED: the variable the main DSH Session reads its key from; it gets the shared key
DSH_MAIN_BASE_URL=                   # OPTIONAL: the main Session's endpoint, given to DSH through graftling's first
                                     # ambient endpoint variable (graftling.dsh.settings.AMBIENT_ENDPOINTS); empty: none
DSH_MAIN_APP_ARGS=                   # OPTIONAL: extra arguments for `dsh --profile headless`, space-separated, as its
                                     # own help lists them (R0 saves it in out/r0/dsh-headless-help.txt); empty: none

# --- Cost estimate (console only; per-hour list prices in USD, converted at EST_RATE) -----------------------------
PRICE_VM_USD_H=0.10                  # MACHINE_TYPE in ZONE's region, per hour
PRICE_WINLIC_USD_VCPU_H=0.05         # Windows Server licence, per vCPU per hour
PRICE_DISK_USD_GB_MONTH=0.10         # balanced persistent disk, per GB per month
PRICE_IP_USD_H=0.005                 # external IPv4 address in use, per hour
EST_CURRENCY=XXX                     # currency of the estimate
EST_RATE=100                         # EST_CURRENCY per USD
BUDGET=1000                          # the Task's cloud budget in EST_CURRENCY (00 prints the hours it covers)
