# Plan: System, Zsh & iTerm2 Performance Optimization

This plan outlines the systematic diagnostics, system remedies, shell optimizations, and monitoring instrumentation to resolve macOS post-update sluggishness, slow zsh startup, and iTerm2 typing delays, including auto-suggestions and shell intelligence.

## 1. Objective
Diagnose and eliminate system-wide sluggishness, lagging iTerm2 keystrokes, and multi-second zsh shell startup times. Install a robust startup performance alerting mechanism to prevent future silent degradation.

## 2. Key Files & Context
- Target execution directory: /Users/conscious/macos-privacy-cli
- User shell configurations: ~/.zshrc, ~/.zprofile, ~/.zshenv
- Zsh completion cache: ~/.zcompdump
- Zsh history cache: ~/.zsh_history
- macOS Spotlight configuration (mdutil)
- iTerm2 GPU Renderer and preferences

---

## 3. Phased Implementation Plan

### Phase 1: Deep System & Shell Diagnostics
Run these commands to isolate and identify the exact bottlenecks:
1. **OS and CPU load analysis**:
   ```bash
   sw_vers
   ps -Aro pid,%cpu,%mem,comm | head -n 12
   vm_stat
   ```
2. **Spotlight Indexing Check**:
   ```bash
   mdutil -s /
   ```
3. **Zsh Startup Baseline**:
   ```bash
   time zsh -f -c exit # Clean startup (no configuration files)
   time zsh -i -c exit # Interactive startup (with your configurations)
   ```
4. **Zsh History Size & Corruption Check**:
   Check if your history file is bloated or corrupted:
   ```bash
   wc -l ~/.zsh_history
   file ~/.zsh_history
   ```
5. **Zsh Profiler (zprof)**:
   Add `zmodload zsh/zprof` at the very top of `~/.zshrc` and `zprof` at the very bottom. Open a new terminal to see the microsecond timing report of every sourced function.

### Phase 2: Post-Update System Remedies
1. **Xcode Command Line Tools**:
   ```bash
   sudo xcodebuild -license accept
   ```
2. **iTerm2 Terminal Optimization**:
   - In iTerm2 Preferences, toggle **GPU Rendering** (GPU drivers often stutter after OS updates).
   - Enable advanced low-latency typing options in iTerm2 Preferences (Advanced > search "latency").
3. **Spotlight Load Mitigation**:
   Exclude development folders (like `node_modules` or `target`) from being indexed via Spotlight Preferences > Privacy.

### Phase 3: Zsh Startup Performance Engineering
Apply these high-impact performance optimizations to `~/.zshrc`:
1. **Lazy Load Node Version Manager (nvm)**:
   Replace standard `source $(brew --prefix nvm)/nvm.sh` with a lazy-loading function to defer initialization until needed:
   ```bash
   # Lazy Load NVM
   if [ -s "$HOME/.nvm/nvm.sh" ]; then
     declare -a __nvm_commands=('nvm' 'node' 'npm' 'npx' 'yarn' 'pnpm')
     function __init_nvm$() {
       for cmd in "${__nvm_commands[@]}"; do
         unset -f "$cmd"
       done
       export NVM_DIR="$HOME/.nvm"
       [ -s "$NVM_DIR/nvm.sh" ] && \. "$NVM_DIR/nvm.sh"
       [ -s "$NVM_DIR/bash_completion" ] && \. "$NVM_DIR/bash_completion"
     }
     for cmd in "${__nvm_commands[@]}"; do
       eval "function $cmd$() { __init_nvm; "\$0" "\$@"; }"
     done
   fi
   ```
2. **Cache Homebrew Environment**:
   Instead of running `eval $(brew shellenv)` dynamically on every terminal load, cache it:
   ```bash
   if [ -z "$HOMEBREW_PREFIX" ]; then
     eval "$(/opt/homebrew/bin/brew shellenv)"
   fi
   ```
3. **Compinit Optimization**:
   Optimize `compinit` to run once a day instead of on every shell launch:
   ```bash
   autoload -Uz compinit
   if [ $(find ~/.zcompdump -mtime +1 2>/dev/null) ]; then
     compinit
   else
     compinit -C
   fi
   ```
4. **Zsh Auto-Suggestions & Shell Intelligence Optimization**:
   Ensure suggestions are processed in a background thread to remove typing latency, and configure the history file to avoid locking or parsing overhead:
   ```bash
   # Enable asynchronous auto-suggestions (removes inline typing lags)
   export ZSH_AUTOSUGGEST_USE_ASYNC=1

   # High-Performance History Cache Tuning
   export HISTSIZE=50000
   export SAVEHIST=10000
   setopt HIST_EXPIRE_DUPS_FIRST # Prune oldest duplicate first when limit is reached
   setopt HIST_IGNORE_DUPS       # Do not record an event that was just recorded
   setopt HIST_IGNORE_ALL_DUPS   # Remove older duplicates from history
   setopt HIST_FIND_NO_DUPS      # Do not display duplicates during searches
   setopt HIST_REDUCE_BLANKS     # Remove superfluous blanks from history entries
   ```

   *If your history file is corrupted or severely bloated, run this repair routine:*
   ```bash
   mv ~/.zsh_history ~/.zsh_history.bad
   strings ~/.zsh_history.bad > ~/.zsh_history
   rm ~/.zsh_history.bad
   ```

### Phase 4: Alerting & Monitoring Instrumentation
1. **Microsecond Startup Timer**:
   Add this to the absolute top of `~/.zshrc`:
   ```bash
   # Start Timer
   integer __zsh_start_time=$(date +%s%3N)
   ```
   Add this to the absolute bottom of `~/.zshrc`:
   ```bash
   # End Timer & Alert
   integer __zsh_end_time=$(date +%s%3N)
   integer __zsh_startup_duration=$($(__zsh_end_time - __zsh_start_time))
   if $($( __zsh_startup_duration > 150 )); then
     echo -e "[1;33m[Zsh Warning] Startup took ${__zsh_startup_duration}ms! Run 'zsh_profile' to diagnose.[0m"
   fi
   ```
2. **Diagnostics Alias**:
   Add this alias to `~/.zshrc` to quickly profile zsh performance anytime:
   ```bash
   alias zsh_profile="ZSH_PROFILE=1 zsh -i -c exit"
   ```

---

## 4. Verification & Testing
1. Run `time zsh -i -c exit` to ensure total initialization is < 150ms.
2. Confirm lazy-loaded commands $(nvm, node, npm) function perfectly.
3. Verify auto-suggested text paints instantly in a background thread with zero keystroke delay.
4. Confirm iTerm2 typing delay is fully resolved.
