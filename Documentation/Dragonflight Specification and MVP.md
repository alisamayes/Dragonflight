# Dragon Raiding Strategy Game — MVP Design & Requirements Specification

## 1. Project Overview

A single-player turn-based fantasy strategy game where the player controls a dragon operating from a central citadel.

The dragon raids nearby human settlements for gold while defending its citadel from retaliatory armies.

The game is designed around strategic risk management:
- Raiding settlements increases wealth.
- Aggressive actions provoke retaliation.
- Settlements grow stronger over time.
- The player must balance expansion, survival, and resource management.

The initial version focuses on:
- Core gameplay systems
- Turn-based mechanics
- Strategic map gameplay
- Modular architecture
- Expandability for future features

The MVP should prioritize clean architecture and gameplay stability over graphics complexity.

---

# 2. Core Gameplay Loop

Each game day represents a single turn.

## Turn Flow

### Phase 1 — Player Turn
The dragon begins each day at the citadel.

The player may:
- Move across the map
- Raid settlements
- Attack armies
- Return to the citadel

The dragon has a fixed amount of time available per turn:
- 24 hours per day

All actions consume time.

The dragon MUST always have enough remaining time to return to the citadel before the turn ends.

If an action would prevent returning to the citadel in time, the action is invalid.

### Phase 2 — Citadel Phase
Once the dragon returns:
- Gold may be spent on upgrades
- Citadel repairs may be purchased
- Dragon HP recovery occurs: **restore 50% of max HP** per day at the citadel for MVP (later systems may modify healing rates)

Citadel repair costs:
- **Static but expensive** baseline cost (exact value tuned during development)

Dragon stat upgrades:
- Upgrade costs **scale with current stat levels / progression tier** (tuned during development)

### Phase 3 — Settlement Phase
All settlements:
- Regenerate/rebuild slightly
- Increase eco and power slightly over time
- Increase aggression if recently attacked
- Potentially spawn armies if aggression thresholds are reached

### Phase 4 — Army Phase
At the end of each turn, **all active armies** resolve movement toward the citadel (their sole objective).

Movement resolution rules:
- Armies move **one at a time**
- Order: **closest to the citadel moves first** (by hex distance along army-legal movement — armies cannot fly over impassable terrain)
- Each army moves according to its movement rules for that turn (see Army System)
- When **two or more armies end movement on the same hex**, they **merge into a single army**
  - Combined stats use **sum** for MVP (e.g. combined HP = sum of HP, combined ATK = sum of ATK, combined DFN = sum of DFN) unless later revised — **default is sum across merged stacks**

After movement resolution:
- Armies attack the citadel if they reach it
- Armies despawn after attacking

### Phase 5 — Next Day Begins
The next turn starts.

---

# 3. Victory & Failure Conditions

## Victory Condition
The MVP uses endless survival gameplay.

Goal:
- Survive as long as possible
- Manage increasing settlement pressure over time

No hard win condition exists in the MVP.

## Scoring (MVP)
- Primary score metric: **turns survived**
- Dragon strength tracking as a secondary progression indicator may be added later; it is **not** required for MVP scoring

---

## Failure Conditions
The game ends if:
- The dragon dies
- The citadel HP reaches 0

Game over immediately triggers when either condition occurs.

---

# 4. World Map

## Map Type
- Hex grid map
- Finite/bounded map
- Fixed handcrafted map for MVP
- Procedural generation planned later

## Visibility
- Entire map visible from start
- No fog of war in MVP

## Perspective
- Isometric world-map style presentation. Intial development should just use coloured hexs for simplicity to get mechanical workings in place and later on isometric style artwork for each asset shall be added in to provide more detail

## Hex coordinate system
- Use **axial coordinates** for the hex grid (implementation detail for pathfinding, distance checks, and map authoring)

## Map authoring (MVP vs later)
- **MVP:** fixed handcrafted map; settlement positions, terrain, citadel placement, and baseline scenario stats are defined as part of map/data setup (balanced during development)
- **Later:** procedural map generation; constraints and balance will be designed when that system is implemented

---

# 5. Terrain System

## Terrain Types

### Grassland
- Normal movement
- No modifiers

### Woodland
- Armies move slower
- Armies take additional damage from dragon attacks

### Mountains
- Impassable to armies

### Rivers
- Impassable to armies

### Bridges
- Allow army crossing over rivers

### Settlement Tile
- Occupied by settlement entity
- Functions as dedicated terrain tile

## Dragon movement vs terrain
- Terrain modifiers (movement speed, combat modifiers such as woodland bonus damage **to armies**) apply **only to land armies**
- The dragon’s flight movement **ignores terrain** for movement cost and path legality (still subject to flight range and turn time limits elsewhere)

---

# 6. Settlement System

## Settlement Types

### Village
- Low economy
- Low combat strength
- High aggression threshold

### City
- High economy
- High combat strength
- High aggression threshold

### Fort
- Low economy
- High combat strength
- Medium aggression threshold


- Damaging settlements lowers their eco and power so spawned armies are weaker.
- This encourages the player to pick targets carefully to keep enemies power low while also raiding enough gold for upgrades
- Villages and Cities are population settlements so have a higher threshold to reach before sending out armies. Forts are defensive so easier to trigger an army.

---

## Settlement Attributes
Each settlement contains:
- HP
- Economy (eco)
- Power
- Defence
- Aggression
- Aggression threshold
- Position
- Settlement type

---

## Settlement Growth
Each turn settlements:
- Recover some HP
- Recover eco
- Recover power
- Increase wealth slowly over time

If heavily damaged:
- Recovery prioritizes rebuilding over growth

---

## Settlement Destruction
If settlement eco reaches 0:
- One additional successful attack permanently destroys the settlement
- Settlement tile becomes normal terrain

Destroying settlements removes future gold generation opportunities.

The UI should request player confirmation before permanent destruction.

---

## Settlement Aggression
Aggression is tracked locally per settlement.

### Aggression Rules
Direct attack:
- Adds full aggression to attacked settlement

Nearby settlements:
- Receive partial aggression increase when another settlement is attacked

### Nearby aggression radius (configurable)
- At game start (settings / new-game options), the player may configure how far “nearby” extends (for spreading aggression from attacks)
- **Default:** nearby settlements are those within a hex radius equal to **15% of map width**, rounded as implemented (example: width 100 hexes → radius 15 hexes)
- Use **map width** as the reference dimension for this default unless later changed for specific map shapes

If aggression exceeds threshold:
- Settlement spawns an army
- Aggression resets or reduces after spawning

---

# 7. Dragon System

## Dragon Overview
The player controls a single dragon each playthrough

Initial dragon type:
- Red Fire Dragon

Other dragon type: 
Black Tank Dragon
Yellow Chrono Dragon
Brown Earth Dragon
(More may be implemented later)


Each dragon type is expected to have a **stat baseline** (e.g. red dragons: faster, higher attack, lower defence; black dragons: slower, higher defence — exact numbers decided during development).

Each dragon will have a different set of abilities that can be unlocked as the dragon levels up. The exact nature of these will be determined during development, but the Dragon class should expect one passive ability and two activatable abilities that can be used once each day. This will help to lend some diversity to different dragons and playthoughs.

Passives will be a constant modifier the Dragon has throughout that run. An example would be a "Black Dragons have thick, razor like scales. In each combat round the enemy takes 1 points of damage".

An activatable affect would be a limited use ability the player can use to gain a benefit. For example "Yellow Dragons use their mastery of chrono magic to make the next action not consume any time"

---

## Dragon Stats

### Health
Determines survivability.

### Attack
Determines outgoing combat damage.

### Defence
Reduces incoming combat damage.

### Flight Range
Maximum movement distance.

### Speed
Determines travel time in hours from **hex distance** and **flight speed in hexes per hour**.

Example:
- Flight speed = **2 hexes per hour**
- Moving **10 hexes** consumes **5 hours** of the day (`10 ÷ 2`)

Travel time for multi-step routes uses the **total hex distance** along the chosen path (subject to flight range limits).

---

## Dragon Progression
Gold may be spent to permanently increase dragon stats. At intervals (for example lvl 5, lvl 10, lvl 15) the dragon will unlock their race based skills.

There are different elemental types of dragons, but no different types of damage as of current. All dragons deal the same type of damage

No meta progression exists in intial plans, but later a rougelite aspect may be added.

---

# 8. Combat System

## Combat Type
Combat is automatic stat-based resolution with discrete **damage rounds** inside a lightweight combat flow (no separate tactical combat screen).

---

## Damage rounds and time
- Each time combat starts, **one damage round** resolves first
- Each damage round consumes **30 minutes** of the dragon’s daily time budget (whether versus a settlement or an army)
- After each round:
  - If **either side reaches 0 HP**, combat ends immediately
  - Otherwise the player chooses **continue** (next damage round, another 30 minutes) or **retreat** (exit combat under retreat rules already implied by invalid stranded-dragon constraints elsewhere)

Stronger enemies tend to force more rounds before victory; weaker enemies end sooner — trading HP and time for payoff.

---

## Damage calculation
Per damage round, both sides can take damage from the exchange:

**Damage taken = attacker ATK − defender DFN**

### Damage floors
- **Human / army attacks:** damage dealt **floors at 0** (negative results become 0)
- **Dragon attacks:** damage dealt **floors at 1** (the dragon always deals at least 1 damage when it attacks)

---

## Settlement Combat
Combat continues across successive damage rounds until:
- Dragon retreats
- Dragon dies
- Settlement HP reaches 0

Successful raids (per design/balance):
- Damage settlement
- Reduce eco/power
- Grant gold to dragon

Raid rewards and scaling:
- Exact gold and eco/power penalties **scale with settlement power / tier** and will be **tuned during development**

---

## Army Combat
Armies:
- Fight back when attacked
- Cannot initiate combat directly against dragon
- Despawn when defeated

Armies deal more damage than settlements of equal level.

---

# 9. Army System

## Army Spawning
Armies only spawn when:
- Settlement aggression threshold is exceeded

No passive spawning.

---

## Army Behavior
Armies:
- Spawn at settlement
- Path toward citadel
- Use shortest efficient route
- Avoid impassable terrain (use bridges to cross rivers)
- Move during the **Army Phase** each turn
- When multiple armies exist, movement is processed **sequentially**, **closest-to-citadel first**
- If multiple armies occupy the same hex after movement, **merge** into one army with **summed** combat stats (punishes ignoring stacks)
- Attack citadel on arrival
- Despawn after attack

Armies do not:
- Patrol
- Chase dragon
- Use supply lines
- Defend settlements dynamically

---

## Army Attributes
Suggested MVP stats:
- HP
- Attack
- Defence
- Movement speed
- Position

---

# 10. Citadel System

## Citadel Overview
The citadel is:
- The dragon home base
- Upgrade location
- Core defence objective

---

## Citadel Features
The citadel:
- Has HP
- Can be repaired with gold
- Cannot defend itself
- Has no allied units
- Is the dragon start/end location each turn
- Associated dragon healing at end of day follows Citadel Phase rules (Section 2)

No citadel upgrades exist in MVP.

---

# 11. Economy

## Currency
Single resource only:
- Gold

---

## Gold Sources
Gold earned by:
- Raiding settlements

---

## Gold Usage
Gold spent on:
- Dragon stat upgrades
- Citadel repairs

No additional resources in MVP.

## Economy tuning (development)
- Raid gold rewards and dragon upgrade costs **scale with settlement tier / progression** (exact curves tuned during development)
- Citadel repair uses a **high static** gold cost baseline (tuned during development)
- See Citadel Phase (Section 2) for healing and repair notes

---

# 12. Technical Requirements

## Language
- Python (**3.11, 3.12, or 3.13** recommended for MVP development — see Section 22 Development environment)

## Framework
- Pygame

## Architecture Style
- Object-oriented design

## Repository layout (initial)
- `src/dragonflight/` — installable game package (`pyproject.toml` uses setuptools `src` layout)
- `assets/` — raster art and tile sprites (dragon, citadel, settlements, terrain, UI chrome as needed)
- `tests/` — automated tests (introduced after core gameplay exists)
- `Documentation/` — design specs

## Presentation assets
- Store images under **`assets/`** with predictable naming or a small manifest as the project grows

---

# 13. Recommended Core Classes

## World state
- **MapState** (or equivalent): single authoritative snapshot of world/simulation state where viable — passed into systems or updated through controlled methods so rules stay consistent

## Map System
- GameMap
- Tile
- HexCoordinate
- PathfindingManager

## Entity System
- Entity
- Dragon
- Army
- Settlement
- Citadel

## Terrain
- TerrainType

## Gameplay Systems
- TurnManager
- CombatManager
- EconomyManager
- UpgradeManager
- AggressionManager
- ArmySpawner

## Rendering
- Renderer
- UIManager
- CameraController

---

# 14. Pathfinding Requirements

Army pathfinding must:
- Support **hex grids using axial coordinates** (Section 4)
- Avoid impassable terrain
- Route through bridges when required
- Efficiently find routes to citadel

Suggested algorithm:
- A*

---

# 15. MVP Scope

The MVP MUST include:

## Required Systems
- Hex map (handcrafted data for MVP)
- Tile rendering
- Dragon movement
- Time-based movement system
- Settlement entities
- Army entities
- Automatic combat (damage-round flow — Section 8)
- Aggression system (including configurable nearby radius at new game — Section 6)
- Army spawning
- Army pathfinding (army merge rules — Section 2 Phase 4, Section 9)
- Citadel HP
- Dragon upgrades
- Gold economy
- Turn cycle
- Game over conditions
- Score display using **turns survived** (Section 3)
- **`assets/`** pipeline for simple art (loading from disk)

---

# 16. Out of Scope For MVP

The following are intentionally excluded from the MVP:
- Multiplayer
- Fog of war
- Procedural maps
- Save/load system
- Multiple dragon types
- Elemental systems
- Citadel upgrades
- Dynamic factions
- Diplomacy
- Weather/seasons
- Tactical combat screens
- Terrain destruction
- Minions/allies
- Skill trees
- Naval systems
- Flying enemies
- **Formal input-binding spec** and advanced input UX (worked out with GUI implementation when appropriate)
- **Automated test suite** as a shipping gate (tests added progressively once systems exist; see Section 21)

---

# 17. Future Expansion Possibilities

Potential future systems:
- Procedural map generation
- Fog of war
- Multiple dragon species
- Elemental damage
- Citadel upgrades
- Hero enemies
- Flying units
- Seasonal systems
- Settlement factions
- Diplomacy
- Dynamic world events
- Save/load support
- Roguelite progression
- Dragon abilities
- AI improvements
- Dynamic economy

---

# 18. Development Priorities

Recommended implementation order:

1. Hex map system
2. Tile rendering
3. Dragon movement/time system
4. Settlement placement
5. Turn manager
6. Combat resolution
7. Army spawning
8. Army pathfinding
9. Citadel system
10. Upgrade/economy system
11. UI polish
12. Balancing

---

# 19. Architectural Principles

The codebase should prioritize:
- Modularity
- Loose coupling
- Expandability
- Clear interfaces
- System isolation
- Readability
- Ease of agent collaboration

Systems should communicate through controlled interfaces rather than tightly coupled logic.

Future systems should be addable without requiring major rewrites.

---

# 20. Agent collaboration roles (Mauschen's Mice)

These roles map to existing subagents where applicable; use focused prompts per task.

| Focus | Typical owner | Notes |
|--------|----------------|-------|
| Backend / simulation | Backend Python agent | Turns, `MapState`, combat rounds, economy rules, hex math, pathfinding, loaders for map data |
| Rendering & GUI | GUI agent | Pygame loop, isometric presentation, HUD, confirmations, game-over flow |
| Quality assurance | QA agent | After automated tests exist: regressions on damage floors, illegal stranded-dragon moves, upgrades affecting stats, army merge/order |
| Map authoring (optional specialist) | Map creator agent session | Hand-built hex maps in data files, validation (bridges, spawn points, reachability), later procedural design |

Split suggestion: if backend sessions become too large, separate **map/content authoring** from **rules/simulation** while keeping both in Python.

---

# 21. Testing strategy (incremental)

Testing is **not** required before first playable slices, but should appear as soon as rules stabilize.

Priority examples:
- Damage calculation including **floors** (Section 8)
- Rejecting player actions that strand the dragon (cannot return to citadel in time — Section 2)
- Purchases increase dragon stats / citadel repair affects HP as intended
- Army movement ordering (**closest to citadel first**) and **merge-by-sum** (Section 2, Section 9)

Framework: **pytest** (optional dev dependency in `pyproject.toml`).

---

# 22. Development environment (Python and Pygame)

Pygame is distributed as **pre-built wheels** on Windows for recent-but-not-bleeding-edge CPython versions. Brand-new Python releases (e.g. **3.14+**) may lack wheels; pip then tries to **compile Pygame from source**, which often fails on a typical desktop unless full native build tooling is configured.

**Practical guidance:**
- Prefer a **dedicated virtual environment** using **Python 3.11–3.13** for this project (`pyproject.toml` declares `requires-python = ">=3.11,<3.14"` until Pygame officially supports newer versions).
- You do **not** need to uninstall your existing Python. The OS can hold multiple versions; use the **Python Launcher for Windows** (`py -3.12`) or install another minor version alongside your current one **only if** you want to run Dragonflight while staying on an unsupported-by-Pygame interpreter for other work.

When Pygame publishes wheels for newer Python lines, bump `requires-python` accordingly.

## Local dev helpers (this repo)
- **First time:** `powershell -ExecutionPolicy Bypass -File .\scripts\Setup-DragonflightDev.ps1` (from the Dragonflight project root)
- **Each session in Cursor / VS Code terminal:** dot-source so activation sticks — `. .\DevShell.ps1`
- **Each session in Explorer:** double‑click `scripts\Open-DragonflightDev.cmd` (opens `cmd` with venv active)
