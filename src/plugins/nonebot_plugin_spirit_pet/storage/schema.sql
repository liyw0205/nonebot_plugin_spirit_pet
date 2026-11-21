CREATE TABLE players (
    user_id TEXT PRIMARY KEY,
    stones INTEGER NOT NULL CHECK (stones >= 0),
    active_pet_id INTEGER,
    registered_at INTEGER CHECK (registered_at >= 0),
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
CREATE TABLE player_identity (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL UNIQUE REFERENCES players(user_id) ON DELETE CASCADE,
    legacy_dao_name TEXT
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
    slot INTEGER NOT NULL DEFAULT 0 CHECK (slot IN (0, 1)),
    FOREIGN KEY(user_id, pet_id) REFERENCES pets(user_id, pet_id),
    CHECK((state='running' AND settled_at IS NULL)
        OR (state='claimed' AND settled_at IS NOT NULL AND settled_at>=finishes_at)
        OR (state='cancelled' AND settled_at IS NOT NULL
            AND settled_at>=started_at AND settled_at<finishes_at))
);
CREATE UNIQUE INDEX expedition_running_slot ON expeditions(user_id, slot) WHERE state='running';
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
CREATE TABLE sect_week_contributions (
    week_start INTEGER NOT NULL CHECK (week_start >= 0),
    sect_id TEXT NOT NULL,
    user_id TEXT NOT NULL REFERENCES players(user_id) ON DELETE CASCADE,
    contribution INTEGER NOT NULL CHECK (contribution > 0),
    PRIMARY KEY(week_start, sect_id, user_id)
);
CREATE TABLE race_league_config (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    enabled_at INTEGER NOT NULL CHECK (enabled_at >= 0),
    first_week_start INTEGER NOT NULL CHECK (first_week_start >= enabled_at),
    latest_week_start INTEGER CHECK (latest_week_start IS NULL OR latest_week_start >= first_week_start)
);
CREATE TABLE race_track_bests (
    user_id TEXT NOT NULL REFERENCES players(user_id) ON DELETE CASCADE,
    week_start INTEGER NOT NULL CHECK (week_start >= 0),
    track_id TEXT NOT NULL CHECK (length(track_id) > 0),
    best_tenths INTEGER NOT NULL CHECK (best_tenths > 0),
    PRIMARY KEY(user_id, week_start, track_id)
);
CREATE INDEX race_track_week_board
    ON race_track_bests(week_start, track_id, best_tenths, user_id);
CREATE TABLE race_league_claims (
    season_start INTEGER NOT NULL CHECK (season_start >= 0),
    user_id TEXT NOT NULL REFERENCES players(user_id) ON DELETE CASCADE,
    rank INTEGER NOT NULL CHECK (rank BETWEEN 1 AND 3),
    claimed_at INTEGER NOT NULL CHECK (claimed_at >= 0),
    reward_snapshot TEXT NOT NULL,
    PRIMARY KEY(season_start, user_id)
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
CREATE TABLE market_listings (
    listing_id INTEGER PRIMARY KEY AUTOINCREMENT,
    seller_id TEXT NOT NULL REFERENCES players(user_id),
    item_id TEXT NOT NULL,
    quantity INTEGER NOT NULL CHECK(quantity BETWEEN 1 AND 99),
    unit_price INTEGER NOT NULL CHECK(unit_price >= 1),
    created_at INTEGER NOT NULL,
    expires_at INTEGER NOT NULL CHECK(expires_at > created_at),
    state TEXT NOT NULL CHECK(state IN ('active', 'sold', 'cancelled', 'expired')),
    closed_at INTEGER,
    buyer_id TEXT REFERENCES players(user_id),
    CHECK((state='active' AND closed_at IS NULL AND buyer_id IS NULL)
        OR (state='sold' AND closed_at IS NOT NULL AND buyer_id IS NOT NULL AND buyer_id!=seller_id)
        OR (state IN ('cancelled', 'expired') AND closed_at IS NOT NULL AND buyer_id IS NULL))
);
CREATE INDEX market_listing_board ON market_listings(state, item_id, unit_price, listing_id);
CREATE INDEX market_listing_seller ON market_listings(seller_id, state, listing_id DESC);
CREATE TABLE market_sales (
    listing_id INTEGER PRIMARY KEY REFERENCES market_listings(listing_id),
    seller_id TEXT NOT NULL REFERENCES players(user_id),
    buyer_id TEXT NOT NULL REFERENCES players(user_id),
    item_id TEXT NOT NULL,
    quantity INTEGER NOT NULL CHECK(quantity >= 1),
    unit_price INTEGER NOT NULL CHECK(unit_price >= 1),
    gross INTEGER NOT NULL CHECK(gross >= 1),
    fee INTEGER NOT NULL CHECK(fee >= 0),
    net INTEGER NOT NULL CHECK(net >= 0),
    sold_at INTEGER NOT NULL,
    CHECK(fee + net = gross),
    CHECK(buyer_id!=seller_id)
);
CREATE INDEX market_sales_seller ON market_sales(seller_id, sold_at DESC);
CREATE TABLE mail_messages (
    message_id INTEGER PRIMARY KEY AUTOINCREMENT,
    sender_id TEXT NOT NULL REFERENCES players(user_id),
    recipient_id TEXT NOT NULL REFERENCES players(user_id),
    kind TEXT NOT NULL CHECK(kind IN ('item', 'stones')),
    stones INTEGER NOT NULL CHECK(stones >= 0),
    item_id TEXT,
    quantity INTEGER NOT NULL CHECK(quantity >= 0),
    body TEXT NOT NULL CHECK(length(body) <= 60),
    created_at INTEGER NOT NULL,
    expires_at INTEGER NOT NULL CHECK(expires_at > created_at),
    state TEXT NOT NULL CHECK(state IN ('active', 'claimed', 'recalled', 'returned')),
    closed_at INTEGER,
    claimed_at INTEGER,
    CHECK(sender_id != recipient_id),
    CHECK((kind='item' AND stones=0 AND item_id IS NOT NULL AND quantity >= 1)
        OR (kind='stones' AND stones >= 1 AND item_id IS NULL AND quantity=0)),
    CHECK((state='active' AND closed_at IS NULL AND claimed_at IS NULL)
        OR (state='claimed' AND closed_at IS NOT NULL AND claimed_at IS NOT NULL)
        OR (state IN ('recalled', 'returned') AND closed_at IS NOT NULL AND claimed_at IS NULL))
);
CREATE INDEX mail_inbox ON mail_messages(recipient_id, state, message_id);
CREATE INDEX mail_outbox ON mail_messages(sender_id, state, message_id DESC);
CREATE TABLE friend_links (
    user_low TEXT NOT NULL REFERENCES players(user_id),
    user_high TEXT NOT NULL REFERENCES players(user_id),
    created_at INTEGER NOT NULL,
    PRIMARY KEY(user_low, user_high),
    CHECK(user_low < user_high)
);
CREATE INDEX friend_link_low ON friend_links(user_low);
CREATE INDEX friend_link_high ON friend_links(user_high);
CREATE TABLE friend_requests (
    from_id TEXT NOT NULL REFERENCES players(user_id),
    to_id TEXT NOT NULL REFERENCES players(user_id),
    created_at INTEGER NOT NULL,
    expires_at INTEGER NOT NULL CHECK(expires_at > created_at),
    PRIMARY KEY(from_id, to_id),
    CHECK(from_id != to_id)
);
CREATE INDEX friend_request_inbox ON friend_requests(to_id, expires_at);
CREATE INDEX friend_request_outbox ON friend_requests(from_id, expires_at);
CREATE TABLE battle_shares (
    share_id TEXT PRIMARY KEY CHECK(length(share_id) BETWEEN 6 AND 24),
    battle_id INTEGER NOT NULL REFERENCES battle_records(battle_id) ON DELETE CASCADE,
    owner_id TEXT NOT NULL REFERENCES players(user_id),
    created_at INTEGER NOT NULL,
    expires_at INTEGER NOT NULL CHECK(expires_at > created_at),
    state TEXT NOT NULL CHECK(state IN ('active', 'revoked')),
    closed_at INTEGER,
    views INTEGER NOT NULL DEFAULT 0 CHECK(views >= 0),
    CHECK((state='active' AND closed_at IS NULL) OR (state='revoked' AND closed_at IS NOT NULL))
);
CREATE INDEX battle_share_owner ON battle_shares(owner_id, state, created_at DESC);
CREATE INDEX battle_share_battle ON battle_shares(battle_id);
CREATE TABLE market_bids (
    bid_id INTEGER PRIMARY KEY AUTOINCREMENT,
    buyer_id TEXT NOT NULL REFERENCES players(user_id),
    item_id TEXT NOT NULL,
    quantity INTEGER NOT NULL CHECK(quantity BETWEEN 1 AND 99),
    unit_price INTEGER NOT NULL CHECK(unit_price >= 1),
    escrow INTEGER NOT NULL CHECK(escrow >= 1),
    created_at INTEGER NOT NULL,
    expires_at INTEGER NOT NULL CHECK(expires_at > created_at),
    state TEXT NOT NULL CHECK(state IN ('active', 'filled', 'cancelled', 'expired')),
    closed_at INTEGER,
    seller_id TEXT REFERENCES players(user_id),
    CHECK(escrow = quantity * unit_price),
    CHECK((state='active' AND closed_at IS NULL AND seller_id IS NULL)
        OR (state='filled' AND closed_at IS NOT NULL AND seller_id IS NOT NULL AND seller_id!=buyer_id)
        OR (state IN ('cancelled', 'expired') AND closed_at IS NOT NULL AND seller_id IS NULL))
);
CREATE INDEX market_bid_board ON market_bids(state, item_id, unit_price DESC, bid_id);
CREATE INDEX market_bid_buyer ON market_bids(buyer_id, state, bid_id DESC);
CREATE TABLE market_bid_sales (
    bid_id INTEGER PRIMARY KEY REFERENCES market_bids(bid_id),
    buyer_id TEXT NOT NULL REFERENCES players(user_id),
    seller_id TEXT NOT NULL REFERENCES players(user_id),
    item_id TEXT NOT NULL,
    quantity INTEGER NOT NULL CHECK(quantity >= 1),
    unit_price INTEGER NOT NULL CHECK(unit_price >= 1),
    gross INTEGER NOT NULL CHECK(gross >= 1),
    fee INTEGER NOT NULL CHECK(fee >= 0),
    net INTEGER NOT NULL CHECK(net >= 0),
    sold_at INTEGER NOT NULL,
    CHECK(fee + net = gross),
    CHECK(buyer_id != seller_id)
);
CREATE INDEX market_bid_sales_seller ON market_bid_sales(seller_id, sold_at DESC);
CREATE INDEX market_bid_sales_buyer ON market_bid_sales(buyer_id, sold_at DESC);
CREATE TABLE fishing_casts (
    cast_id INTEGER PRIMARY KEY AUTOINCREMENT,
    operation_id TEXT NOT NULL UNIQUE,
    user_id TEXT NOT NULL REFERENCES players(user_id),
    created_at INTEGER NOT NULL CHECK(created_at >= 0),
    snapshot TEXT NOT NULL,
    reply TEXT NOT NULL
);
CREATE INDEX fishing_cast_history ON fishing_casts(user_id, cast_id DESC);
CREATE TABLE duel_actions (
    action_id INTEGER PRIMARY KEY AUTOINCREMENT,
    operation_id TEXT NOT NULL UNIQUE CHECK(length(operation_id)>0),
    user_id TEXT NOT NULL REFERENCES players(user_id),
    created_at INTEGER NOT NULL CHECK(created_at>=0),
    snapshot TEXT NOT NULL,
    reply TEXT NOT NULL
);
CREATE INDEX duel_action_history ON duel_actions(user_id, action_id DESC);
CREATE TABLE sect_boss_weeks (
    week_start INTEGER NOT NULL CHECK(week_start>=0),
    sect_id TEXT NOT NULL CHECK(sect_id IN ('jian_ge', 'xuan_men', 'dan_ding', 'yu_shou')),
    enemy_id TEXT NOT NULL CHECK(length(enemy_id)>0),
    boss_name TEXT NOT NULL CHECK(length(boss_name)>0),
    description TEXT NOT NULL,
    combat_snapshot TEXT NOT NULL,
    max_hp INTEGER NOT NULL CHECK(max_hp>0),
    current_hp INTEGER NOT NULL CHECK(current_hp BETWEEN 0 AND max_hp),
    state TEXT NOT NULL CHECK(state IN ('active', 'defeated', 'expired')),
    started_at INTEGER NOT NULL CHECK(started_at>=week_start),
    closed_at INTEGER,
    PRIMARY KEY(week_start, sect_id),
    CHECK((state='active' AND current_hp>0 AND closed_at IS NULL)
        OR (state='defeated' AND current_hp=0 AND closed_at IS NOT NULL)
        OR (state='expired' AND current_hp>0 AND closed_at>=week_start+604800))
);
CREATE TABLE sect_boss_attacks (
    attack_id INTEGER PRIMARY KEY AUTOINCREMENT,
    week_start INTEGER NOT NULL,
    sect_id TEXT NOT NULL,
    user_id TEXT NOT NULL REFERENCES players(user_id),
    battle_day TEXT NOT NULL CHECK(length(battle_day)=10),
    attempt INTEGER NOT NULL CHECK(attempt BETWEEN 1 AND 3),
    operation_id TEXT NOT NULL UNIQUE CHECK(length(operation_id)>0),
    battle_id INTEGER NOT NULL UNIQUE REFERENCES battle_records(battle_id),
    hp_before INTEGER NOT NULL CHECK(hp_before>0),
    hp_after INTEGER NOT NULL CHECK(hp_after>=0 AND hp_after<=hp_before),
    damage INTEGER NOT NULL CHECK(damage=hp_before-hp_after),
    created_at INTEGER NOT NULL CHECK(created_at>=week_start),
    UNIQUE(week_start, sect_id, user_id, battle_day, attempt),
    FOREIGN KEY(week_start, sect_id) REFERENCES sect_boss_weeks(week_start, sect_id)
);
CREATE INDEX sect_boss_attack_rank ON sect_boss_attacks(week_start, sect_id, user_id, damage);
CREATE INDEX sect_boss_attack_history ON sect_boss_attacks(user_id, week_start DESC, attack_id DESC);
CREATE TABLE sect_boss_claims (
    week_start INTEGER NOT NULL,
    sect_id TEXT NOT NULL,
    user_id TEXT NOT NULL REFERENCES players(user_id),
    scope TEXT NOT NULL CHECK(scope IN ('sect', 'personal')),
    tier INTEGER NOT NULL CHECK(tier BETWEEN 1 AND 6),
    operation_id TEXT NOT NULL CHECK(length(operation_id)>0),
    claimed_at INTEGER NOT NULL CHECK(claimed_at>=0),
    reward_snapshot TEXT NOT NULL,
    reply TEXT NOT NULL,
    PRIMARY KEY(week_start, sect_id, user_id, scope, tier),
    FOREIGN KEY(week_start, sect_id) REFERENCES sect_boss_weeks(week_start, sect_id)
);
CREATE INDEX sect_boss_claim_history ON sect_boss_claims(user_id, claimed_at DESC);
CREATE TABLE wild_capture_runs (
    run_id INTEGER PRIMARY KEY AUTOINCREMENT,
    operation_id TEXT NOT NULL UNIQUE REFERENCES duel_actions(operation_id),
    user_id TEXT NOT NULL REFERENCES players(user_id),
    route_id TEXT NOT NULL CHECK(length(route_id)>0),
    route_name TEXT NOT NULL CHECK(length(route_name)>0),
    day_key TEXT NOT NULL CHECK(length(day_key)=10),
    species_id TEXT NOT NULL CHECK(length(species_id)>0),
    species_name TEXT NOT NULL CHECK(length(species_name)>0),
    rarity TEXT NOT NULL CHECK(rarity IN ('common', 'uncommon', 'rare')),
    enemy_id TEXT NOT NULL CHECK(length(enemy_id)>0),
    enemy_name TEXT NOT NULL CHECK(length(enemy_name)>0),
    enemy_snapshot TEXT NOT NULL,
    capture_item_id TEXT NOT NULL CHECK(length(capture_item_id)>0),
    capture_item_name TEXT NOT NULL CHECK(length(capture_item_name)>0),
    capture_rate REAL NOT NULL CHECK(capture_rate>0 AND capture_rate<=1),
    max_attempts INTEGER NOT NULL CHECK(max_attempts BETWEEN 1 AND 5),
    same_species_limit INTEGER NOT NULL CHECK(same_species_limit BETWEEN 1 AND 10),
    state TEXT NOT NULL CHECK(state IN ('pending', 'captured', 'released', 'escaped')),
    terminal_reason TEXT CHECK(terminal_reason IN ('caught', 'released', 'battle_lost', 'battle_draw', 'expired')),
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK(attempt_count BETWEEN 0 AND 5),
    battle_id INTEGER NOT NULL UNIQUE REFERENCES battle_records(battle_id),
    captured_pet_id INTEGER,
    started_at INTEGER NOT NULL CHECK(started_at>=0),
    expires_at INTEGER NOT NULL CHECK(expires_at>started_at),
    finished_at INTEGER,
    CHECK((state='pending' AND terminal_reason IS NULL AND captured_pet_id IS NULL AND finished_at IS NULL)
        OR (state='captured' AND terminal_reason='caught' AND captured_pet_id IS NOT NULL AND finished_at>=started_at)
        OR (state='released' AND terminal_reason='released' AND captured_pet_id IS NULL AND finished_at>=started_at)
        OR (state='escaped' AND terminal_reason IN ('battle_lost', 'battle_draw', 'expired')
            AND captured_pet_id IS NULL AND finished_at>=started_at)),
    FOREIGN KEY(user_id, captured_pet_id) REFERENCES pets(user_id, pet_id)
);
CREATE UNIQUE INDEX wild_capture_one_pending ON wild_capture_runs(user_id) WHERE state='pending';
CREATE INDEX wild_capture_history ON wild_capture_runs(user_id, run_id DESC);
CREATE INDEX wild_capture_daily ON wild_capture_runs(user_id, day_key, run_id);
CREATE TABLE wild_capture_attempts (
    attempt_id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES wild_capture_runs(run_id),
    operation_id TEXT NOT NULL UNIQUE REFERENCES duel_actions(operation_id),
    attempt_no INTEGER NOT NULL CHECK(attempt_no BETWEEN 1 AND 5),
    item_id TEXT NOT NULL CHECK(length(item_id)>0),
    catch_rate REAL NOT NULL CHECK(catch_rate>0 AND catch_rate<=1),
    roll REAL NOT NULL CHECK(roll>=0 AND roll<=1),
    succeeded INTEGER NOT NULL CHECK(succeeded IN (0, 1)),
    attempted_at INTEGER NOT NULL CHECK(attempted_at>=0),
    UNIQUE(run_id, attempt_no)
);
CREATE INDEX wild_capture_attempt_history ON wild_capture_attempts(run_id, attempt_no);
CREATE TABLE wild_survey_claims (
    user_id TEXT NOT NULL REFERENCES players(user_id),
    route_id TEXT NOT NULL CHECK(length(route_id)>0),
    tier_id TEXT NOT NULL CHECK(length(tier_id)>0),
    operation_id TEXT NOT NULL UNIQUE REFERENCES duel_actions(operation_id),
    claimed_at INTEGER NOT NULL CHECK(claimed_at>=0),
    reward_snapshot TEXT NOT NULL,
    reply TEXT NOT NULL,
    PRIMARY KEY(user_id, route_id, tier_id)
);
CREATE INDEX wild_survey_claim_history ON wild_survey_claims(user_id, claimed_at DESC);
CREATE TABLE wild_habitat_weeks (
    week_start INTEGER PRIMARY KEY CHECK(week_start>=0),
    event_id TEXT NOT NULL CHECK(length(event_id)>0),
    route_id TEXT NOT NULL CHECK(length(route_id)>0),
    event_snapshot TEXT NOT NULL,
    opened_at INTEGER NOT NULL CHECK(opened_at>=week_start AND opened_at<week_start+604800)
);
CREATE TABLE wild_habitat_contributions (
    contribution_id INTEGER PRIMARY KEY AUTOINCREMENT,
    week_start INTEGER NOT NULL REFERENCES wild_habitat_weeks(week_start),
    run_id INTEGER NOT NULL UNIQUE REFERENCES wild_capture_runs(run_id),
    user_id TEXT NOT NULL REFERENCES players(user_id),
    species_id TEXT NOT NULL CHECK(length(species_id)>0),
    contributed_at INTEGER NOT NULL CHECK(contributed_at>=week_start AND contributed_at<week_start+604800),
    UNIQUE(week_start,user_id,species_id)
);
CREATE INDEX wild_habitat_contribution_progress ON wild_habitat_contributions(week_start,user_id,species_id);
CREATE TABLE wild_habitat_claims (
    week_start INTEGER NOT NULL REFERENCES wild_habitat_weeks(week_start),
    user_id TEXT NOT NULL REFERENCES players(user_id),
    tier_id TEXT NOT NULL CHECK(length(tier_id)>0),
    operation_id TEXT NOT NULL UNIQUE REFERENCES duel_actions(operation_id),
    claimed_at INTEGER NOT NULL CHECK(claimed_at>=week_start AND claimed_at<week_start+1209600),
    reward_snapshot TEXT NOT NULL,
    reply TEXT NOT NULL,
    PRIMARY KEY(week_start,user_id,tier_id)
);
CREATE INDEX wild_habitat_claim_history ON wild_habitat_claims(user_id,claimed_at DESC);
CREATE TABLE pet_pedigree_operations (
    operation_id TEXT PRIMARY KEY CHECK(length(operation_id)>0),
    user_id TEXT NOT NULL REFERENCES players(user_id),
    kind TEXT NOT NULL CHECK(kind IN ('breed', 'hatch', 'milestone_claim')),
    created_at INTEGER NOT NULL CHECK(created_at>=0),
    snapshot TEXT NOT NULL,
    reply TEXT NOT NULL
);
CREATE INDEX pet_pedigree_operation_history ON pet_pedigree_operations(user_id,created_at DESC);
CREATE TABLE pet_lineage_eggs (
    egg_record_id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL REFERENCES players(user_id),
    item_id TEXT NOT NULL CHECK(length(item_id)>0),
    species_id TEXT NOT NULL CHECK(length(species_id)>0),
    parent_a_id INTEGER NOT NULL CHECK(parent_a_id>0),
    parent_a_name TEXT NOT NULL CHECK(length(parent_a_name)>0),
    parent_a_species_id TEXT NOT NULL CHECK(parent_a_species_id=species_id),
    parent_b_id INTEGER NOT NULL CHECK(parent_b_id>0 AND parent_b_id<>parent_a_id),
    parent_b_name TEXT NOT NULL CHECK(length(parent_b_name)>0),
    parent_b_species_id TEXT NOT NULL CHECK(parent_b_species_id=species_id),
    operation_id TEXT NOT NULL UNIQUE REFERENCES pet_pedigree_operations(operation_id),
    status TEXT NOT NULL CHECK(status IN ('available', 'reserved', 'hatched', 'consumed')),
    reservation_id TEXT,
    child_pet_id INTEGER CHECK(child_pet_id>0),
    child_name TEXT CHECK(child_name IS NULL OR length(child_name)>0),
    created_at INTEGER NOT NULL CHECK(created_at>=0),
    finished_at INTEGER,
    FOREIGN KEY(parent_a_id) REFERENCES pets(pet_id),
    FOREIGN KEY(parent_b_id) REFERENCES pets(pet_id),
    FOREIGN KEY(child_pet_id) REFERENCES pets(pet_id),
    CHECK((status='available' AND reservation_id IS NULL AND child_pet_id IS NULL
            AND child_name IS NULL AND finished_at IS NULL)
        OR (status='reserved' AND length(reservation_id)>0 AND child_pet_id IS NULL
            AND child_name IS NULL AND finished_at IS NULL)
        OR (status='hatched' AND reservation_id IS NULL AND child_pet_id IS NOT NULL
            AND child_pet_id>parent_a_id AND child_pet_id>parent_b_id
            AND child_name IS NOT NULL AND finished_at>=created_at)
        OR (status='consumed' AND reservation_id IS NULL AND child_pet_id IS NULL
            AND child_name IS NULL AND finished_at>=created_at))
);
CREATE INDEX pet_lineage_egg_inventory ON pet_lineage_eggs(user_id,item_id,status,egg_record_id);
CREATE UNIQUE INDEX pet_lineage_egg_reservation ON pet_lineage_eggs(reservation_id) WHERE reservation_id IS NOT NULL;
CREATE UNIQUE INDEX pet_lineage_child_unique ON pet_lineage_eggs(child_pet_id) WHERE child_pet_id IS NOT NULL;
CREATE INDEX pet_lineage_parent_a ON pet_lineage_eggs(user_id,parent_a_id,status,child_pet_id);
CREATE INDEX pet_lineage_parent_b ON pet_lineage_eggs(user_id,parent_b_id,status,child_pet_id);
CREATE TABLE pet_pedigree_claims (
    user_id TEXT NOT NULL REFERENCES players(user_id),
    milestone_id TEXT NOT NULL CHECK(length(milestone_id)>0),
    operation_id TEXT NOT NULL UNIQUE REFERENCES pet_pedigree_operations(operation_id),
    claimed_at INTEGER NOT NULL CHECK(claimed_at>=0),
    reward_snapshot TEXT NOT NULL,
    reply TEXT NOT NULL,
    PRIMARY KEY(user_id,milestone_id)
);
CREATE INDEX pet_pedigree_claim_history ON pet_pedigree_claims(user_id,claimed_at DESC);
CREATE TABLE family_trial_runs (
    run_id TEXT PRIMARY KEY CHECK(length(run_id)>0),
    user_id TEXT NOT NULL REFERENCES players(user_id) ON DELETE CASCADE,
    week_start INTEGER NOT NULL CHECK(week_start>=0),
    trial_id TEXT NOT NULL CHECK(length(trial_id)>0),
    start_operation_id TEXT NOT NULL UNIQUE REFERENCES duel_actions(operation_id),
    status TEXT NOT NULL CHECK(status IN ('active','completed','defeated','abandoned','expired')),
    current_stage INTEGER NOT NULL CHECK(current_stage>=1),
    started_at INTEGER NOT NULL CHECK(started_at>=week_start AND started_at<week_start+604800),
    updated_at INTEGER NOT NULL CHECK(updated_at>=started_at),
    snapshot TEXT NOT NULL,
    reply TEXT NOT NULL,
    UNIQUE(user_id,week_start),
    UNIQUE(user_id,run_id)
);
CREATE INDEX family_trial_history ON family_trial_runs(user_id,week_start DESC,run_id DESC);
CREATE TABLE family_trial_members (
    run_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    slot INTEGER NOT NULL CHECK(slot BETWEEN 1 AND 3),
    pet_id INTEGER NOT NULL,
    PRIMARY KEY(run_id,slot),
    UNIQUE(run_id,pet_id),
    FOREIGN KEY(user_id,run_id) REFERENCES family_trial_runs(user_id,run_id) ON DELETE CASCADE,
    FOREIGN KEY(user_id,pet_id) REFERENCES pets(user_id,pet_id)
);
CREATE TABLE family_trial_stages (
    run_id TEXT NOT NULL REFERENCES family_trial_runs(run_id) ON DELETE CASCADE,
    stage_no INTEGER NOT NULL CHECK(stage_no>=1),
    battle_id INTEGER NOT NULL UNIQUE REFERENCES battle_records(battle_id),
    outcome TEXT NOT NULL CHECK(outcome IN ('won','lost','draw','timeout')),
    rounds INTEGER NOT NULL CHECK(rounds>=0),
    remaining_hp TEXT NOT NULL,
    played_at INTEGER NOT NULL CHECK(played_at>=0),
    PRIMARY KEY(run_id,stage_no)
);
CREATE TABLE family_trial_rewards (
    run_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    reward_key TEXT NOT NULL CHECK(length(reward_key)>0),
    operation_id TEXT NOT NULL REFERENCES duel_actions(operation_id),
    granted_at INTEGER NOT NULL CHECK(granted_at>=0),
    reward_snapshot TEXT NOT NULL,
    PRIMARY KEY(run_id,reward_key),
    FOREIGN KEY(user_id,run_id) REFERENCES family_trial_runs(user_id,run_id) ON DELETE CASCADE
);
CREATE INDEX family_trial_reward_history ON family_trial_rewards(user_id,granted_at DESC);
CREATE TABLE family_tutelage_courses (
    course_id TEXT PRIMARY KEY CHECK(length(course_id)>0),
    user_id TEXT NOT NULL REFERENCES players(user_id),
    parent_id INTEGER NOT NULL,
    child_id INTEGER NOT NULL CHECK(child_id<>parent_id),
    egg_record_id INTEGER NOT NULL REFERENCES pet_lineage_eggs(egg_record_id),
    skill_id TEXT NOT NULL CHECK(length(skill_id)>0),
    week_start INTEGER NOT NULL CHECK(week_start>=0),
    start_operation_id TEXT NOT NULL UNIQUE REFERENCES duel_actions(operation_id),
    status TEXT NOT NULL CHECK(status IN ('active','completed','failed','cancelled','expired')),
    lessons_done INTEGER NOT NULL DEFAULT 0 CHECK(lessons_done BETWEEN 0 AND 2),
    attempts_used INTEGER NOT NULL DEFAULT 0 CHECK(attempts_used BETWEEN 0 AND 3),
    started_at INTEGER NOT NULL CHECK(started_at>=week_start AND started_at<week_start+604800),
    updated_at INTEGER NOT NULL CHECK(updated_at>=started_at),
    expires_at INTEGER NOT NULL CHECK(expires_at=started_at+604800),
    snapshot TEXT NOT NULL,
    reply TEXT NOT NULL,
    UNIQUE(user_id,course_id),
    FOREIGN KEY(user_id,parent_id) REFERENCES pets(user_id,pet_id),
    FOREIGN KEY(user_id,child_id) REFERENCES pets(user_id,pet_id),
    CHECK(status<>'completed' OR (lessons_done=2 AND attempts_used>=1)),
    CHECK(attempts_used=0 OR lessons_done=2)
);
CREATE UNIQUE INDEX family_tutelage_one_active ON family_tutelage_courses(user_id) WHERE status='active';
CREATE INDEX family_tutelage_history ON family_tutelage_courses(user_id,started_at DESC,course_id);
CREATE INDEX family_tutelage_weekly ON family_tutelage_courses(user_id,week_start);
CREATE TABLE family_tutelage_lessons (
    course_id TEXT NOT NULL REFERENCES family_tutelage_courses(course_id),
    lesson_no INTEGER NOT NULL CHECK(lesson_no BETWEEN 1 AND 2),
    operation_id TEXT NOT NULL UNIQUE REFERENCES duel_actions(operation_id),
    taught_at INTEGER NOT NULL CHECK(taught_at>=0),
    cost_snapshot TEXT NOT NULL,
    PRIMARY KEY(course_id,lesson_no)
);
CREATE TABLE family_tutelage_exams (
    course_id TEXT NOT NULL REFERENCES family_tutelage_courses(course_id),
    attempt_no INTEGER NOT NULL CHECK(attempt_no BETWEEN 1 AND 3),
    operation_id TEXT NOT NULL UNIQUE REFERENCES duel_actions(operation_id),
    battle_id INTEGER NOT NULL UNIQUE REFERENCES battle_records(battle_id),
    outcome TEXT NOT NULL CHECK(outcome IN ('passed','unused','lost','draw','timeout')),
    rounds INTEGER NOT NULL CHECK(rounds>=0),
    target_uses INTEGER NOT NULL CHECK(target_uses>=0),
    examined_at INTEGER NOT NULL CHECK(examined_at>=0),
    PRIMARY KEY(course_id,attempt_no)
);
CREATE TABLE family_tutelage_graduations (
    user_id TEXT NOT NULL,
    child_id INTEGER NOT NULL,
    skill_id TEXT NOT NULL CHECK(length(skill_id)>0),
    course_id TEXT NOT NULL UNIQUE,
    operation_id TEXT NOT NULL UNIQUE REFERENCES duel_actions(operation_id),
    proficiency INTEGER NOT NULL CHECK(proficiency BETWEEN 0 AND 20),
    graduated_at INTEGER NOT NULL CHECK(graduated_at>=0),
    reward_snapshot TEXT NOT NULL,
    PRIMARY KEY(child_id,skill_id),
    FOREIGN KEY(user_id,course_id) REFERENCES family_tutelage_courses(user_id,course_id),
    FOREIGN KEY(user_id,child_id) REFERENCES pets(user_id,pet_id)
);
CREATE TABLE family_outing_runs (
    trip_id TEXT PRIMARY KEY CHECK(length(trip_id)>0),
    user_id TEXT NOT NULL REFERENCES players(user_id),
    parent_id INTEGER NOT NULL,
    child_id INTEGER NOT NULL CHECK(child_id<>parent_id),
    egg_record_id INTEGER NOT NULL REFERENCES pet_lineage_eggs(egg_record_id),
    route_id TEXT NOT NULL CHECK(length(route_id)>0),
    week_start INTEGER NOT NULL CHECK(week_start>=0),
    start_operation_id TEXT NOT NULL UNIQUE REFERENCES duel_actions(operation_id),
    status TEXT NOT NULL CHECK(status IN ('active','completed','cancelled','expired')),
    steps_done INTEGER NOT NULL DEFAULT 0 CHECK(steps_done BETWEEN 0 AND 3),
    rapport INTEGER NOT NULL DEFAULT 0 CHECK(rapport BETWEEN 0 AND 9),
    started_at INTEGER NOT NULL CHECK(started_at>=week_start AND started_at<week_start+604800),
    updated_at INTEGER NOT NULL CHECK(updated_at>=started_at),
    expires_at INTEGER NOT NULL CHECK(expires_at=started_at+86400),
    snapshot TEXT NOT NULL,
    reply TEXT NOT NULL,
    UNIQUE(user_id,trip_id),
    FOREIGN KEY(user_id,parent_id) REFERENCES pets(user_id,pet_id),
    FOREIGN KEY(user_id,child_id) REFERENCES pets(user_id,pet_id),
    CHECK((status='completed' AND steps_done=3) OR (status<>'completed' AND steps_done<3))
);
CREATE UNIQUE INDEX family_outing_one_active ON family_outing_runs(user_id) WHERE status='active';
CREATE INDEX family_outing_history ON family_outing_runs(user_id,started_at DESC,trip_id);
CREATE INDEX family_outing_weekly ON family_outing_runs(user_id,week_start);
CREATE TABLE family_outing_steps (
    trip_id TEXT NOT NULL REFERENCES family_outing_runs(trip_id),
    step_no INTEGER NOT NULL CHECK(step_no BETWEEN 1 AND 3),
    choice_id TEXT NOT NULL CHECK(choice_id IN ('guide','explore','rest')),
    operation_id TEXT NOT NULL UNIQUE REFERENCES duel_actions(operation_id),
    acted_at INTEGER NOT NULL CHECK(acted_at>=0),
    snapshot TEXT NOT NULL,
    PRIMARY KEY(trip_id,step_no)
);
CREATE TABLE family_outing_rewards (
    trip_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    operation_id TEXT NOT NULL UNIQUE REFERENCES duel_actions(operation_id),
    granted_at INTEGER NOT NULL CHECK(granted_at>=0),
    reward_snapshot TEXT NOT NULL,
    FOREIGN KEY(user_id,trip_id) REFERENCES family_outing_runs(user_id,trip_id)
);
