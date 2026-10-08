CREATE TABLE players (
    user_id TEXT PRIMARY KEY,
    dao_name TEXT NOT NULL UNIQUE COLLATE NOCASE,
    stones INTEGER NOT NULL CHECK (stones >= 0),
    active_pet_id INTEGER,
    sign_day TEXT NOT NULL DEFAULT '',
    last_bond_day TEXT NOT NULL DEFAULT '',
    current_bond_streak INTEGER NOT NULL DEFAULT 0 CHECK (current_bond_streak >= 0),
    best_bond_streak INTEGER NOT NULL DEFAULT 0 CHECK (best_bond_streak >= current_bond_streak),
    quest_day TEXT NOT NULL DEFAULT '',
    last_train INTEGER,
    last_explore INTEGER,
    last_pve INTEGER,
    last_pvp INTEGER,
    FOREIGN KEY(user_id, active_pet_id) REFERENCES pets(user_id, pet_id)
        DEFERRABLE INITIALLY DEFERRED
);
CREATE TABLE player_resonance (
    user_id TEXT PRIMARY KEY REFERENCES players(user_id) ON DELETE CASCADE,
    resonance_id TEXT NOT NULL CHECK(length(resonance_id)>0),
    activated_at INTEGER NOT NULL
);
CREATE TABLE adventure_discoveries (
    user_id TEXT NOT NULL REFERENCES players(user_id) ON DELETE CASCADE,
    encounter_id TEXT NOT NULL CHECK(length(encounter_id)>0),
    discovered_at INTEGER NOT NULL,
    PRIMARY KEY(user_id, encounter_id)
);
CREATE TABLE pets (
    pet_id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL REFERENCES players(user_id),
    species_id TEXT NOT NULL,
    name TEXT NOT NULL,
    realm INTEGER NOT NULL DEFAULT 0 CHECK (realm >= 0),
    layer INTEGER NOT NULL DEFAULT 1 CHECK (layer BETWEEN 1 AND 10),
    bloodline INTEGER NOT NULL DEFAULT 0 CHECK (bloodline >= 0),
    lineage_id TEXT,
    archived INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1)),
    exp INTEGER NOT NULL DEFAULT 0 CHECK (exp >= 0),
    affinity INTEGER NOT NULL DEFAULT 0 CHECK (affinity BETWEEN 0 AND 100),
    major_breakthrough_failures INTEGER NOT NULL DEFAULT 0 CHECK (major_breakthrough_failures >= 0),
    energy INTEGER NOT NULL DEFAULT 100 CHECK (energy BETWEEN 0 AND 100),
    energy_updated INTEGER NOT NULL,
    UNIQUE(user_id, pet_id)
);
CREATE INDEX pets_owner ON pets(user_id, archived, pet_id);
CREATE INDEX pets_rank ON pets(archived, realm DESC, layer DESC, exp DESC);
CREATE TABLE active_pet_slots (
    user_id TEXT NOT NULL REFERENCES players(user_id) ON DELETE CASCADE,
    slot INTEGER NOT NULL CHECK(slot BETWEEN 1 AND 3),
    pet_id INTEGER NOT NULL,
    PRIMARY KEY(user_id, slot),
    UNIQUE(user_id, pet_id),
    FOREIGN KEY(user_id, pet_id) REFERENCES pets(user_id, pet_id) ON DELETE CASCADE
);
CREATE INDEX active_pet_slots_pet ON active_pet_slots(pet_id);
CREATE TABLE expeditions (
    job_id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL REFERENCES players(user_id),
    pet_id INTEGER NOT NULL,
    task_id TEXT NOT NULL,
    task_name TEXT NOT NULL,
    source_operation_id TEXT NOT NULL UNIQUE CHECK(length(source_operation_id)>0),
    started_at INTEGER NOT NULL,
    finishes_at INTEGER NOT NULL CHECK(finishes_at>started_at),
    state TEXT NOT NULL CHECK(state IN ('running', 'claimed', 'cancelled')),
    reward_snapshot TEXT NOT NULL,
    settled_at INTEGER,
    FOREIGN KEY(user_id, pet_id) REFERENCES pets(user_id, pet_id),
    CHECK((state='running' AND settled_at IS NULL)
        OR (state='claimed' AND settled_at IS NOT NULL AND settled_at>=finishes_at)
        OR (state='cancelled' AND settled_at IS NOT NULL
            AND settled_at>=started_at AND settled_at<finishes_at))
);
CREATE UNIQUE INDEX expedition_running_player ON expeditions(user_id) WHERE state='running';
CREATE UNIQUE INDEX expedition_running_pet ON expeditions(pet_id) WHERE state='running';
CREATE INDEX expedition_history ON expeditions(user_id, job_id DESC);
CREATE TABLE equipment (
    pet_id INTEGER NOT NULL REFERENCES pets(pet_id),
    slot TEXT NOT NULL CHECK (slot IN ('weapon', 'armor', 'charm')),
    item_id TEXT NOT NULL,
    enhancement INTEGER NOT NULL DEFAULT 0 CHECK(enhancement >= 0),
    PRIMARY KEY(pet_id, slot)
);
CREATE TABLE unequipped_equipment (
    user_id TEXT NOT NULL REFERENCES players(user_id),
    item_id TEXT NOT NULL,
    enhancement INTEGER NOT NULL CHECK(enhancement > 0),
    quantity INTEGER NOT NULL CHECK(quantity >= 0),
    PRIMARY KEY(user_id, item_id, enhancement)
);
CREATE TABLE learned_skills (
    pet_id INTEGER NOT NULL REFERENCES pets(pet_id),
    skill_id TEXT NOT NULL,
    equipped INTEGER NOT NULL CHECK (equipped IN (0, 1)),
    level INTEGER NOT NULL DEFAULT 1 CHECK(level >= 1),
    proficiency INTEGER NOT NULL DEFAULT 0 CHECK(proficiency >= 0),
    PRIMARY KEY(pet_id, skill_id)
);
CREATE TABLE inventory (
    user_id TEXT NOT NULL REFERENCES players(user_id),
    item_id TEXT NOT NULL,
    quantity INTEGER NOT NULL CHECK (quantity >= 0),
    PRIMARY KEY(user_id, item_id)
);
CREATE TABLE quest_progress (
    user_id TEXT NOT NULL REFERENCES players(user_id),
    quest_id TEXT NOT NULL,
    progress INTEGER NOT NULL DEFAULT 0 CHECK (progress >= 0),
    claimed INTEGER NOT NULL DEFAULT 0 CHECK (claimed IN (0, 1)),
    PRIMARY KEY(user_id, quest_id)
);
CREATE TABLE teams (
    team_id INTEGER PRIMARY KEY AUTOINCREMENT,
    leader_id TEXT NOT NULL UNIQUE REFERENCES players(user_id)
);
CREATE TABLE team_members (
    user_id TEXT PRIMARY KEY REFERENCES players(user_id),
    team_id INTEGER NOT NULL REFERENCES teams(team_id) ON DELETE CASCADE,
    ready_pet_id INTEGER REFERENCES pets(pet_id),
    ready_pet_ids TEXT NOT NULL DEFAULT ''
);
CREATE INDEX team_roster ON team_members(team_id);
CREATE TABLE team_requests (
    team_id INTEGER NOT NULL REFERENCES teams(team_id) ON DELETE CASCADE,
    candidate_id TEXT NOT NULL REFERENCES players(user_id) ON DELETE CASCADE,
    kind TEXT NOT NULL CHECK (kind IN ('apply', 'invite')),
    initiator_id TEXT NOT NULL REFERENCES players(user_id) ON DELETE CASCADE,
    created_at INTEGER NOT NULL,
    expires_at INTEGER NOT NULL CHECK (expires_at > created_at),
    PRIMARY KEY(team_id, candidate_id),
    CHECK ((kind='apply' AND initiator_id=candidate_id)
        OR (kind='invite' AND initiator_id!=candidate_id))
);
CREATE INDEX team_request_candidate ON team_requests(candidate_id, expires_at);
CREATE INDEX team_request_expiry ON team_requests(expires_at);
CREATE TABLE seasons (
    season_id TEXT PRIMARY KEY,
    starts_at INTEGER NOT NULL,
    ends_at INTEGER NOT NULL CHECK(ends_at>starts_at),
    closed_at INTEGER CHECK(closed_at>=ends_at),
    observed_at INTEGER NOT NULL CHECK(observed_at>=starts_at),
    rules_snapshot TEXT NOT NULL
);
CREATE TABLE season_entries (
    season_id TEXT NOT NULL REFERENCES seasons(season_id),
    user_id TEXT NOT NULL REFERENCES players(user_id),
    rating INTEGER NOT NULL CHECK(rating>=0),
    wins INTEGER NOT NULL DEFAULT 0 CHECK(wins>=0),
    losses INTEGER NOT NULL DEFAULT 0 CHECK(losses>=0),
    draws INTEGER NOT NULL DEFAULT 0 CHECK(draws>=0),
    PRIMARY KEY(season_id, user_id)
);
CREATE INDEX season_ranking ON season_entries(season_id, rating DESC);
CREATE TABLE pvp_results (
    result_id INTEGER PRIMARY KEY AUTOINCREMENT,
    season_id TEXT NOT NULL REFERENCES seasons(season_id),
    challenger_id TEXT NOT NULL REFERENCES players(user_id),
    target_id TEXT NOT NULL REFERENCES players(user_id),
    challenger_pet_id INTEGER NOT NULL,
    target_pet_id INTEGER NOT NULL,
    winner_id TEXT REFERENCES players(user_id),
    day TEXT NOT NULL,
    played_at INTEGER NOT NULL,
    delta INTEGER NOT NULL CHECK(delta>=0),
    operation_id TEXT NOT NULL UNIQUE CHECK(length(operation_id)>0),
    reply TEXT NOT NULL,
    CHECK(challenger_id!=target_id),
    CHECK(winner_id IS NULL OR winner_id IN (challenger_id, target_id)),
    CHECK(winner_id IS NOT NULL OR delta=0),
    FOREIGN KEY(challenger_id, challenger_pet_id) REFERENCES pets(user_id, pet_id),
    FOREIGN KEY(target_id, target_pet_id) REFERENCES pets(user_id, pet_id)
);
CREATE INDEX result_challenger ON pvp_results(season_id, challenger_id, day);
CREATE INDEX result_target ON pvp_results(season_id, target_id, day);
CREATE TABLE battle_records (
    battle_id INTEGER PRIMARY KEY AUTOINCREMENT,
    operation_id TEXT NOT NULL UNIQUE CHECK(length(operation_id)>0),
    initiator_id TEXT NOT NULL REFERENCES players(user_id),
    kind TEXT NOT NULL CHECK(kind IN ('pvp', 'spar', 'pve', 'pve_stage')),
    battle_key TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL,
    winner_side INTEGER NOT NULL CHECK(winner_side IN (-1, 0, 1)),
    rounds INTEGER NOT NULL CHECK(rounds >= 0),
    played_at INTEGER NOT NULL,
    reply TEXT NOT NULL,
    snapshot TEXT NOT NULL,
    battle_log TEXT NOT NULL
);
CREATE INDEX battle_records_time ON battle_records(played_at DESC, battle_id DESC);
CREATE TABLE battle_participants (
    battle_id INTEGER NOT NULL REFERENCES battle_records(battle_id) ON DELETE CASCADE,
    user_id TEXT NOT NULL REFERENCES players(user_id),
    side INTEGER NOT NULL CHECK(side IN (0, 1)),
    permission TEXT NOT NULL CHECK(permission IN ('participant', 'defender')),
    PRIMARY KEY(battle_id, user_id)
);
CREATE INDEX battle_participant_history ON battle_participants(user_id, battle_id DESC);
CREATE TABLE pve_stage_progress (
    user_id TEXT NOT NULL REFERENCES players(user_id) ON DELETE CASCADE,
    stage_id TEXT NOT NULL,
    first_cleared_at INTEGER NOT NULL,
    first_operation_id TEXT NOT NULL CHECK(length(first_operation_id)>0),
    PRIMARY KEY(user_id, stage_id)
);
CREATE INDEX pve_stage_completion_order ON pve_stage_progress(stage_id, first_cleared_at, user_id);
CREATE TABLE season_claims (
    season_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    reward_snapshot TEXT NOT NULL,
    claimed_at INTEGER NOT NULL,
    PRIMARY KEY(season_id, user_id),
    FOREIGN KEY(season_id, user_id) REFERENCES season_entries(season_id, user_id)
);
CREATE TABLE achievement_claims (
    user_id TEXT NOT NULL REFERENCES players(user_id),
    achievement_id TEXT NOT NULL,
    operation_id TEXT NOT NULL UNIQUE CHECK(length(operation_id)>0),
    claimed_at INTEGER NOT NULL,
    reward_snapshot TEXT NOT NULL,
    reply TEXT NOT NULL,
    PRIMARY KEY(user_id, achievement_id)
);
CREATE INDEX achievement_claim_history ON achievement_claims(user_id, claimed_at DESC);
CREATE TABLE operations (
    operation_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    reply TEXT NOT NULL
);
CREATE INDEX operations_age ON operations(created_at);
