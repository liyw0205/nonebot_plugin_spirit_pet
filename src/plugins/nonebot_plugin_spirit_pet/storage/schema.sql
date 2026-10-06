CREATE TABLE players (
    user_id TEXT PRIMARY KEY,
    dao_name TEXT NOT NULL UNIQUE COLLATE NOCASE,
    stones INTEGER NOT NULL CHECK (stones >= 0),
    active_pet_id INTEGER,
    sign_day TEXT NOT NULL DEFAULT '',
    quest_day TEXT NOT NULL DEFAULT '',
    last_train INTEGER,
    last_explore INTEGER,
    last_pve INTEGER,
    last_pvp INTEGER,
    rating INTEGER NOT NULL DEFAULT 1000 CHECK (rating >= 0),
    FOREIGN KEY(user_id, active_pet_id) REFERENCES pets(user_id, pet_id)
        DEFERRABLE INITIALLY DEFERRED
);
CREATE TABLE pets (
    pet_id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL REFERENCES players(user_id),
    species_id TEXT NOT NULL,
    name TEXT NOT NULL,
    realm INTEGER NOT NULL DEFAULT 0 CHECK (realm >= 0),
    layer INTEGER NOT NULL DEFAULT 1 CHECK (layer BETWEEN 1 AND 10),
    bloodline INTEGER NOT NULL DEFAULT 0 CHECK (bloodline >= 0),
    exp INTEGER NOT NULL DEFAULT 0 CHECK (exp >= 0),
    affinity INTEGER NOT NULL DEFAULT 0 CHECK (affinity BETWEEN 0 AND 100),
    energy INTEGER NOT NULL DEFAULT 100 CHECK (energy BETWEEN 0 AND 100),
    energy_updated INTEGER NOT NULL,
    UNIQUE(user_id, pet_id)
);
CREATE INDEX pets_owner ON pets(user_id);
CREATE INDEX pets_rank ON pets(realm DESC, layer DESC, exp DESC);
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
    ready_pet_id INTEGER REFERENCES pets(pet_id)
);
CREATE INDEX team_roster ON team_members(team_id);
CREATE TABLE duels (
    duel_id INTEGER PRIMARY KEY AUTOINCREMENT,
    challenger_id TEXT NOT NULL REFERENCES players(user_id),
    target_id TEXT NOT NULL REFERENCES players(user_id),
    mode TEXT NOT NULL CHECK (mode IN ('pvp', 'spar')),
    expires_at INTEGER NOT NULL,
    CHECK(challenger_id != target_id)
);
CREATE INDEX duel_challenger ON duels(challenger_id);
CREATE INDEX duel_target ON duels(target_id);
CREATE TABLE pvp_pairs (
    first_id TEXT NOT NULL REFERENCES players(user_id),
    second_id TEXT NOT NULL REFERENCES players(user_id),
    last_day TEXT NOT NULL,
    PRIMARY KEY(first_id, second_id)
);
CREATE TABLE operations (
    operation_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    reply TEXT NOT NULL
);
CREATE INDEX operations_age ON operations(created_at);
